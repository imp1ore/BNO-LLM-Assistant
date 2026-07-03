# BNO LLM Assistant - Server Deployment Guide

Step-by-step setup for the BNO private cloud server (Red Hat / RHEL 8.x,
Python 3.10). Assumes you have sudo and the project files on the server.

---

## Easiest path (TL;DR - 3 commands)

If Python 3.10+ and [Ollama](https://ollama.com) are installed on the server, the
whole setup is two scripts:

```bash
cd /path/to/BNOLLM        # the project folder on the server

./scripts/setup.sh                  # 1. makes venv, installs deps, creates .env
                                    #    (downloads the AI models on first run)

sudo ./scripts/install_service.sh   # 2. runs it as an always-on service on boot
```

Then open `http://<server-ip>:9000` and log in.

- `setup.sh` will ask you to pick an admin password (you can skip and set it later
  in the `.env` file).
- That's it for a basic deployment. The sections below explain each piece in
  detail, plus optional extras (nginx, backups, hardening). **You don't need them
  for a first working deployment** - they're reference.

> Just want to try it once without the service? Run `./scripts/setup.sh` then
> `./scripts/start_prod.sh` (stops when you press Ctrl+C).

---

## 0. Before you start

Confirm these are true on the server:

- Python 3.10+ is installed (`python3.10 --version`)
- Ollama is installed (`ollama --version`)
- Port **9000** is open through the firewall (CCF) toward AVD users
- You have the project folder on the box (e.g. unzipped into a working dir)

> **Port note:** the **app** should own its own port (default **9000**). **Ollama**
> should stay on **11434** on a standard install. On some BNO servers Ollama is
> already on **9000** — do **not** run the app on the same port. After setup run:
> `./scripts/configure_bno_server.sh` (moves the app to **8000** and points Ollama
> at `http://localhost:9000`), then restart the service.

---

## 1. Put the app in a standard location

```bash
sudo mkdir -p /opt/bnollm
sudo cp -r BNOLLM /opt/bnollm/
cd /opt/bnollm/BNOLLM
```

(Optional but recommended) run it under a dedicated user instead of root:

```bash
sudo useradd -r -s /sbin/nologin bnollm
sudo chown -R bnollm:bnollm /opt/bnollm
```

---

## 2. Create a virtual environment and install dependencies

> `./scripts/setup.sh` does all of this automatically. The manual steps are here
> only if you prefer to do it yourself.

```bash
cd /opt/bnollm/BNOLLM
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Start Ollama and pull the models

```bash
# Make sure Ollama is running as a service
sudo systemctl enable --now ollama        # if installed as a service
# (or, for a quick manual test only:  ollama serve & )

# Pull the two models the app uses
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
ollama pull llama3.2:3b

# Verify
ollama list
curl -s http://localhost:11434/api/tags
```

---

## 4. Configure the environment (.env)

> `./scripts/setup.sh` already creates `.env` with a secure `SECRET_KEY` and lets
> you set the admin password. Do this manual version only to customize further.

```bash
cd /opt/bnollm/BNOLLM
cp .env.example .env
# Generate a strong secret key:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Edit `.env` and set at minimum:

- `SECRET_KEY=` the generated value
- `ADMIN_PASSWORD=` a real password (not "admin")
- `API_SERVER_HOST=0.0.0.0` (so AVD users can reach it)
- `API_SERVER_PORT=9000`
- `OLLAMA_BASE_URL=http://localhost:11434` (match Ollama's actual port)

Optional tuning (sane defaults already set):

- `MAX_FILE_SIZE_MB=100` - max upload size. Files index in the background, so big
  files don't block or time out. If you raise this and use nginx, also raise
  `client_max_body_size` to match (see section 7).
- `EMBED_BATCH_SIZE=32` - chunks embedded per Ollama call during indexing. Higher
  = faster indexing but more RAM; lower it if the box is memory-constrained.
- `LOGIN_MAX_ATTEMPTS=10` / `LOGIN_WINDOW_MINUTES=5` - login brute-force throttle.

---

## 5. First run (manual smoke test)

```bash
cd /opt/bnollm/BNOLLM
./scripts/start_prod.sh
```

Then from your machine (on the corporate network / AVD), open:

```
http://<server-ip>:9000
```

Log in with the admin username/password you set in `.env`, upload a test
document, and ask a question. Press `Ctrl+C` to stop the manual run.

---

## 6. Make it always-on (systemd - recommended)

> Easiest: `sudo ./scripts/install_service.sh` - it auto-fills the correct paths
> and user for this server, installs the service, and starts it. The manual steps
> below are the equivalent if you'd rather do it by hand.

```bash
# Edit deploy/bnollm.service if your paths/user differ, then:
sudo cp deploy/bnollm.service /etc/systemd/system/bnollm.service
sudo systemctl daemon-reload
sudo systemctl enable --now bnollm

# Status + live logs
sudo systemctl status bnollm
sudo journalctl -u bnollm -f
```

The service auto-starts on boot and restarts on failure. It runs a single process
(port 9000) with the RAG engine inside it. Keep it single-process: SQLite and
ChromaDB are not safe to share across multiple workers.

---

## 7. (Optional) Reverse proxy with nginx

You can serve the app directly on port 9000. If your team prefers nginx in front
(for TLS, a hostname, or to sit behind the CCF), use this. **The key setting is
`client_max_body_size`** - nginx's default is 1MB and will reject larger uploads
with `413` before they ever reach the app.

```nginx
server {
    listen 80;
    server_name bnollm.internal.example;   # adjust to your hostname

    # Must be >= MAX_FILE_SIZE_MB in .env (here: 100MB)
    client_max_body_size 100m;

    location / {
        proxy_pass         http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Uploads return immediately (indexing runs in the background), so long
        # proxy timeouts aren't required, but these are safe defaults.
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

> The app reads `X-Forwarded-For` for the login rate-limiter, so per-user
> throttling still works correctly behind the proxy.

---

## 8. How uploads & indexing behave (for the team)

- **Uploads return instantly.** When a user uploads a file, the request saves it
  and returns right away; the heavy work (extract -> chunk -> embed -> index)
  runs in a **background thread**. The document shows as **Processing**, then
  flips to **Indexed** (or **Failed**) automatically - the UI polls for this.
- **A document is only searchable once it shows "Indexed."** Large files can take
  a while (roughly ~40 chunks/sec on CPU; much faster on a GPU). Embedding speed
  is the main cost, not file size in MB.
- **Failed documents show a reason and a "Retry" button.** Common causes: a
  scanned/image-only PDF with no extractable text (needs OCR, not supported), or
  Ollama being unreachable mid-index. Fix the cause and click Retry (or re-upload).
- **Only users with the upload permission (or admins) can upload.** This is
  enforced on the server, not just hidden in the UI.
- **Re-uploading the same filename replaces the old version** (old chunks and file
  are cleaned up first) - no duplicates.
- A GPU on the server dramatically speeds up indexing and answering; CPU-only
  works but is slower for big documents.

---

## 9. Day-to-day operations

```bash
sudo systemctl restart bnollm     # after changing .env or updating code
sudo systemctl stop bnollm
sudo journalctl -u bnollm --since "1 hour ago"
```

App data lives under `/opt/bnollm/BNOLLM/data/`:
- `database.db`   - users, chats, messages, document metadata (SQLite)
- `vectors/`      - ChromaDB vector index
- `documents/`    - uploaded source files

**Back up the `data/` folder** to preserve users and indexed documents.

---

## 10. Security checklist (do not skip on a shared server)

- [ ] `SECRET_KEY` set to a random value in `.env` (not the default)
- [ ] `ADMIN_PASSWORD` changed from "admin"
- [ ] `.env` is NOT committed to git (already in `.gitignore`)
- [ ] App runs as a non-root user where possible
- [ ] Only port 9000 is exposed; Ollama (11434) stays localhost-only
- [ ] If behind nginx, `client_max_body_size` >= `MAX_FILE_SIZE_MB`
- [ ] Login throttle left on (`LOGIN_MAX_ATTEMPTS`) - tune if needed
- [ ] `data/` folder is included in backups

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Can't reach app from AVD | `API_SERVER_HOST` not `0.0.0.0`, or firewall/CCF not open on 9000 |
| "could not connect to Ollama" | Ollama not running, or `OLLAMA_BASE_URL` port wrong |
| Answers always "I don't have that information" | No documents uploaded yet, or similarity threshold too high (`SIMILARITY_THRESHOLD` in `config.py`) |
| Login fails after restart | `SECRET_KEY` changed - existing tokens are invalidated; just log in again |
| Port 9000 in use | Something else (e.g. Ollama) is on 9000 - move it or change `API_SERVER_PORT` |
| Upload rejected with `413` | nginx `client_max_body_size` lower than the file - raise it to match `MAX_FILE_SIZE_MB` |
| Document stuck on "Processing" | Indexing still running (large file) or Ollama unreachable - check `journalctl -u bnollm`; it will flip to "Failed" with a reason if it errors |
| Document shows "Failed" | Read the reason under the file. Image-only PDF (needs OCR) or Ollama down. Fix and click "Retry" |
| "Too many login attempts" (429) | Brute-force throttle hit - wait `LOGIN_WINDOW_MINUTES`, or raise `LOGIN_MAX_ATTEMPTS` |
