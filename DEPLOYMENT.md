# BNO LLM Assistant - Server Deployment Guide

Step-by-step setup for the BNO private cloud server (Red Hat / RHEL 8.x,
Python 3.10). Assumes you have sudo and the project files on the server.

---

## 0. Before you start

Confirm these are true on the server:

- Python 3.10+ is installed (`python3.10 --version`)
- Ollama is installed (`ollama --version`)
- Port **9000** is open through the firewall (CCF) toward AVD users
- You have the project folder on the box (e.g. unzipped into a working dir)

> **Port note:** the **app** should own port **9000**. **Ollama** should stay on its
> default **11434**, reachable only from localhost. Don't put Ollama on 9000 - that
> collides with the app. If Ollama must run on another port, set `OLLAMA_BASE_URL`
> in `.env` to match.

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

## 7. Day-to-day operations

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

## 8. Security checklist (do not skip on a shared server)

- [ ] `SECRET_KEY` set to a random value in `.env` (not the default)
- [ ] `ADMIN_PASSWORD` changed from "admin"
- [ ] `.env` is NOT committed to git (already in `.gitignore`)
- [ ] App runs as a non-root user where possible
- [ ] Only port 9000 is exposed; Ollama (11434) stays localhost-only
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
