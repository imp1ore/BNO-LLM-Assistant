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

### Speeding up answers on a CPU-only server

Chat answers stream to the browser as they're generated (first words appear in
a few seconds instead of waiting for the whole answer), which is already live
with no setup needed. For extra CPU speed with no quality loss, run:

```bash
sudo ./scripts/tune_ollama_performance.sh
```

This enables flash attention and a quantized KV cache on the Ollama service
(daemon-level settings, ~15-30% faster generation on CPU). Combine with
`OLLAMA_LANGUAGE_MODEL=qwen2.5:3b` in `.env` (see `.env.example`) for a bigger
speed win if 7B answers still feel too slow.

### Image/diagram comprehension in design documents (optional, uses OpenAI)

Local Ollama vision models were evaluated and rejected for this: `moondream`
hallucinated device names/IPs on a complex synthetic network diagram, and
`llama3.2-vision` was accurate but far too slow on CPU-only hardware.

Instead, `ENABLE_VISION_EXTRACTION=true` (in `.env`) uses OpenAI's `gpt-4o`
just for images: when a **PDF, Word (.docx), or PowerPoint (.pptx)** file is
uploaded, embedded images/diagrams are pulled out, described in detail by
`gpt-4o` (device names, IPs, VLANs, connections - transcribed as text), and
that description becomes part of the searchable index alongside the
document's normal text. **Normal text Q&A stays on local Ollama** - only the
images themselves are ever sent to OpenAI, and only when this flag is on.

**Cost model - this runs once per upload, not once per question.** The
description is generated a single time when a document is indexed and stored
permanently as a chunk. Every later question that touches that diagram is
answered by searching the already-stored text - it never calls OpenAI vision
again. Cost only recurs if you re-upload or click "Retry" on the same
document (since that re-processes it from scratch), not from normal usage.

Multiple images per document run concurrently (small worker pool) rather than
one-at-a-time, so figure-heavy documents index noticeably faster.

**Large, dense diagrams are automatically tiled.** OpenAI internally
downscales any single image above its own resolution cap before the model
reads it - on a big diagram packed with many small labeled nodes, that can
blur small text into illegibility (tested: a single call on a 3600x2600
diagram with 81 labeled nodes fabricated wrong IDs/IPs for most rows and
completely missed one specific critical node placed in a corner). Any image
wider or taller than `VISION_TILE_THRESHOLD_PX` (default 1600px) is instead
split into 4 overlapping quadrants plus one lower-res overview pass, each
described separately at full resolution, then merged - in the same test this
correctly transcribed every node and caught the one placed in the corner.
This costs ~5x more vision calls for that one image, but only kicks in for
genuinely large diagrams.

**Tiny images below `VISION_MIN_IMAGE_DIM` (default 150px, either dimension)
are skipped entirely** - this exists to filter out logos/bullet icons/
dividers that would otherwise add noise and cost. If your documents have
small-but-important diagrams (e.g. compact port maps) that are legitimately
under 150px, lower this value in `.env`.

**Regular/small images with genuinely tiny embedded text are auto-upscaled
before sending.** Tiling only fixes the "OpenAI downscales a huge image"
problem - it doesn't help an image that was already small to begin with
(tested: forcing tiling on a small image just gave the model even smaller
crops and didn't fix anything). The real issue there is too few source
pixels per character, so every image below ~2000px on its longest side is
now upscaled (LANCZOS, up to 4x) before being sent - confirmed via testing
that this fixes most misreads of small text.

**Honesty check - this isn't a 100% guarantee.** On a stress-test image with
deliberately tiny (10px) text, even with upscaling, the model occasionally
still misread a single digit in one identifier on a re-run (non-deterministic
model output) - it went from "usually wrong" to "usually right, rarely
slightly off" rather than "always perfect." Real-world diagrams sized for
human readability should be fine in practice, but for anything where a wrong
digit in a description would actually matter (e.g. a VLAN/IP someone might
act on), treat the vision description as aiding search/retrieval, not as an
authoritative transcription - the original document/image is still the
source of truth.

File size is not a concern either way - uploads up to `MAX_FILE_SIZE_MB`
(default 100MB, comfortably covers a 20MB file) are streamed to disk rather
than loaded fully into memory, and indexing runs in the background so the
upload itself returns immediately regardless of file size.

**Known gaps** (a document still indexes fine without these, just without a
description for that specific image):
- Native PowerPoint charts/SmartArt and Word charts (not pasted-in pictures)
  aren't stored as images at all, so they aren't caught - only actual
  picture/screenshot content is.
- Legacy WMF/EMF vector metafile images (common for charts pasted from very
  old Office versions) are skipped, since they can't be read as a normal
  raster image.
- Vector graphics drawn natively on a PDF page (not embedded as a raster
  image) aren't caught either - this would need rendering whole pages to
  images instead of extracting embedded images, which is a bigger change.

**Before enabling on the real server**, check two things:

1. **Data policy** - confirm sending document images to OpenAI's API is
   acceptable. Leave this off otherwise.
2. **Network egress** - many corporate/telecom networks block outbound
   internet from servers by default. Test from the BNO server itself (not
   your laptop) before relying on this:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

   - `200` - reachable, key works, you're good to enable the feature.
   - Connection timeout / `curl: (7)` / `(28)` - the server can't reach the
     internet at all (firewall/proxy blocking egress). This needs a firewall
     rule or an HTTP proxy config from your network team before OpenAI-backed
     features can work here - the app itself is not misconfigured in that case.
   - `401`/`403` - key issue (revoked/invalid), not a network issue.

Setup once cleared:

```bash
# in .env
OPENAI_API_KEY=sk-...
ENABLE_VISION_EXTRACTION=true
# optional overrides (defaults shown):
# OPENAI_VISION_MODEL=gpt-4o
# VISION_MIN_IMAGE_DIM=150
# VISION_MAX_IMAGES_PER_DOC=0   # 0 = unlimited, all diagrams get described
```

Then `sudo systemctl restart bnollm` and re-upload (or Retry) any documents
with diagrams so they get indexed with the new image descriptions.

### Fast chat answers via OpenAI (optional, bigger data exposure than vision)

Local Ollama answers are slow on CPU-only hardware (30-60s+ for a 7B model).
If that's not acceptable and OpenAI is cleared for use, you can route just
the answer-generation step to OpenAI (`gpt-4o-mini`, near-instant) while
**keeping embeddings on Ollama** so your already-indexed documents keep
working:

```bash
# in .env - do NOT also set EMBEDDING_PROVIDER=openai on a server with
# existing indexed documents (see the .env.example comment for why)
OPENAI_API_KEY=sk-...
ANSWER_PROVIDER=openai
```

```bash
sudo systemctl restart bnollm
```

**This is a bigger data exposure than vision extraction** - every question
and all retrieved document context (not just images) now goes to OpenAI.
Confirm that's cleared with BNO's data policy before enabling on real
documents. `./scripts/doctor.sh` will confirm the key/connectivity are good
before you flip this on.

---

## 9. Day-to-day operations

```bash
sudo systemctl restart bnollm     # after changing .env or updating code
sudo systemctl stop bnollm
sudo journalctl -u bnollm --since "1 hour ago"
```

**If something seems off** (won't start, crashed after a restart, fresh
server, just pulled new code) - run this first instead of guessing:

```bash
./scripts/doctor.sh
```

It checks Python/dependencies/`.env`/disk space/Ollama+models/port conflicts/
OpenAI connectivity in one pass, auto-fixes anything safe to fix (missing
deps, missing models, missing `.env`), and - if the `bnollm` systemd service
exists and isn't active - automatically prints its last 30 log lines so you
don't have to dig for the crash reason yourself.

App data lives under `/opt/bnollm/BNOLLM/data/`:
- `database.db`   - users, chats, messages, document metadata (SQLite)
- `vectors/`      - ChromaDB vector index
- `documents/`    - uploaded source files

**Back up the `data/` folder** to preserve users and indexed documents.

---

## 10. Security checklist (do not skip on a shared server)

- [ ] `SECRET_KEY` set to a random value in `.env` (not the default, and NOT
      an API key - generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
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
