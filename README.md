# BNO LLM Assistant

Version: Beta v1.0.0
Internal RAG assistant for the e& Business Network Operations (BNO) department.

A private web application for uploading internal documents and asking questions
about them. The assistant answers **only** from the documents you upload — it does
not use outside knowledge, and it says so when the answer is not in the documents.

Everything runs on-premises: documents, the database, the vector index, and the
language model all stay on your server. Nothing is sent to any external API.

---

## How it works (architecture)

A single Python (FastAPI) process serves the web UI, the API, and the RAG engine.
It talks to a local **Ollama** instance for embeddings and text generation.

```
Browser ──HTTP──▶ FastAPI app (port 9000) ──▶ ChromaDB (vector search)
                        │
                        └──▶ Ollama (port 11434): embeddings + LLM
```

- **One process** by design: SQLite + ChromaDB are not safe to share across
  multiple workers, so the app runs as a single process. RAG runs *inside* the API
  process — there is no separate model server to manage.
- **Storage** lives under `data/`: `database.db` (users, chats, metadata),
  `vectors/` (ChromaDB index), and `documents/` (uploaded files).

---

## Quick start (local)

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running
- The two models the app uses (pulled below)

### Steps (easiest)

```bash
# One command: creates the venv, installs deps, makes .env (with a secure key),
# and downloads the AI models. Asks you to pick an admin password.
./scripts/setup.sh

# Start it
./scripts/start_prod.sh
```

Then open <http://127.0.0.1:9000> and log in with the admin account.

<details>
<summary>Or do it manually</summary>

```bash
# 1. Pull the models
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf   # embeddings
ollama pull llama3.2:3b                                   # generation

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. (Optional but recommended) configure environment
cp .env.example .env        # then edit SECRET_KEY / ADMIN_PASSWORD

# 4. Start the app
./scripts/start.sh          # macOS / Linux
scripts\start.bat           # Windows
```

</details>

The default admin is `admin` / `admin` unless you set `ADMIN_PASSWORD` in `.env`
(setup.sh prompts you for it).

> **Deploying to the BNO server?** Follow [`DEPLOYMENT.md`](DEPLOYMENT.md) — it
> starts with a 3-command quick path, then full RHEL + systemd reference.

---

## First login & accounts

- On first startup the app creates one admin account from `ADMIN_USERNAME` /
  `ADMIN_PASSWORD` (defaults to `admin` / `admin` — **change this for any real use**).
- Admins create the other accounts from the **Admin** screen and grant the
  **Upload** and/or **Admin** permissions per user.
- Self-registration is **off** by default (`ALLOW_REGISTRATION=false`). Turn it on
  only if you want anyone who can reach the app to create their own login.
- Users can change their own password (**Change Password** in the top bar); admins
  can reset passwords and delete users from the Admin screen.

To reset the admin password manually: `python scripts/create_admin.py`.

---

## Using it

1. **Upload documents** — open **Documents**, then drag & drop or click to upload
   (PDF, DOCX, PPTX, TXT; up to 50 MB each). Documents are shared across users.
2. **Ask questions** — type in the chat box. Answers come only from the uploaded
   documents; conversations are saved in the sidebar.

---

## Project structure

```
BNOLLM/
├── backend/
│   ├── api_server/     # FastAPI app: auth, chat, documents, admin (port 9000)
│   ├── llm_server/     # rag_engine.py — retrieval + generation (in-process)
│   ├── shared/         # llm_providers, vector_db, database, document_processor
│   ├── middleware/     # logging + error handling
│   └── utils/          # logging + custom exceptions
├── frontend/           # Single-page web UI (HTML/CSS/JS)
├── scripts/            # start/stop + admin helper scripts
├── deploy/             # systemd unit for production
├── data/               # database, vectors, uploaded documents (created at runtime)
├── logs/               # application logs
├── config.py           # all configuration (overridable via .env)
├── requirements.txt
├── DEPLOYMENT.md       # server deployment guide
└── .env.example        # environment template
```

---

## Configuration

All settings live in `config.py` and can be overridden with environment variables
(via a `.env` file). The most important ones:

| Setting | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | JWT signing key — **set a random value in production** | dev default (warns) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | First admin account | `admin` / `admin` |
| `ALLOW_REGISTRATION` | Public self-registration | `false` |
| `MIN_PASSWORD_LENGTH` | Password policy | `8` |
| `API_SERVER_HOST` / `API_SERVER_PORT` | Where the app listens | `127.0.0.1` / `9000` |
| `OLLAMA_BASE_URL` | Ollama endpoint | `http://localhost:11434` |
| `SIMILARITY_THRESHOLD` | Min relevance to use a chunk | `0.3` |
| `CORS_ORIGINS` | Allowed browser origins | localhost:9000 |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not connect to Ollama" | Start Ollama (`ollama serve` / `systemctl start ollama`); check `OLLAMA_BASE_URL` |
| Answers always "I don't have that information" | No documents uploaded yet, or `SIMILARITY_THRESHOLD` too high |
| Port 9000 in use | Change `API_SERVER_PORT`, or stop whatever owns the port |
| Can't reach app from another machine | Set `API_SERVER_HOST=0.0.0.0` and open the port in the firewall |
| Login fails after restart | `SECRET_KEY` changed — existing tokens are invalidated; just log in again |

Logs: `tail -f logs/bno_llm_*.log`

---

## License

Internal use for the e& Business Network Operations department.
