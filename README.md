# BNO LLM Assistant

Version: Beta v1.0.0

A web application for uploading company documents and asking questions. The AI answers based on the documents you upload.

## What You Need

- Python 3.8 or higher
- Ollama installed on your computer
- Two AI models downloaded (instructions below)

## Setup Instructions

### Step 1: Install Ollama

Download from https://ollama.com and install it.

### Step 2: Download the AI Models

Open a terminal and run these commands:

```bash
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
ollama pull hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF
```

This will take a few minutes. Wait for both to finish.

### Step 3: Install Python Packages

```bash
pip install -r requirements.txt
```

### Step 4: Start the Application

On Windows:
```bash
scripts\start.bat
```

On Mac/Linux:
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

This starts two servers:
- LLM server on port 8000 (handles AI questions)
- API server on port 9000 (handles everything else)

### Step 5: Open in Browser

Go to: http://127.0.0.1:9000

## How to Use

1. Login: Default admin account is username `admin` and password `admin`
2. Upload Documents: Click "Upload Document" and select PDF, DOCX, PPTX, or TXT files
3. Ask Questions: Type your question in the chat box and press Enter
4. View History: Your chat conversations are saved in the sidebar

## Default Admin Account

- Username: `admin`
- Password: `admin`

You can create more accounts from the admin panel after logging in.

## Running on Mac

1. Install Python 3.8+ and Ollama
2. Download the models (Step 2 above)
3. Install packages: `pip install -r requirements.txt`
4. Run: `./scripts/start.sh`
5. Open: http://127.0.0.1:9000

Everything should work the same as on Windows.

## Docker Setup (Recommended for Mac)

If you're having issues running on Mac, use Docker instead.

### Prerequisites
- Docker Desktop installed (https://www.docker.com/products/docker-desktop)

### Quick Start with Docker

1. Build and start everything:
```bash
docker-compose up --build
```

2. Download the AI models (in a new terminal):
```bash
docker exec -it bno-ollama ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
docker exec -it bno-ollama ollama pull hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF
```

3. Open in browser: http://127.0.0.1:9000

### Stop the application:
```bash
docker-compose down
```

### View logs:
```bash
docker-compose logs -f
```

Your data (database, documents) is saved in the `data/` folder and persists between restarts.

## Troubleshooting

Ollama not working:
- Make sure Ollama is running: open Ollama app or run `ollama list` in terminal
- Check that both models downloaded: `ollama list` should show both models

Port already in use:
- Close other programs using ports 8000 or 9000
- Or change the ports in `config.py`

Can't install packages:
- Make sure you have Python 3.8 or higher: `python --version`
- Try: `pip install --upgrade pip` then `pip install -r requirements.txt`

Documents not uploading:
- Only PDF, DOCX, PPTX, and TXT files are supported
- Maximum file size is 50MB

## Manual Server Start (if scripts don't work)

Open two terminal windows.

Terminal 1 - LLM Server:
```bash
python -m backend.llm_server.main
```

Terminal 2 - API Server:
```bash
python -m backend.api_server.main
```

Then open http://127.0.0.1:9000 in your browser.

## Project Files

- `backend/api_server/` - Main web server code
- `backend/llm_server/` - AI question answering code
- `frontend/` - Web interface files
- `data/database.db` - User accounts and chat history
- `data/documents/` - Uploaded documents
- `config.py` - Settings (ports, file sizes, etc.)

## Notes

- All documents are shared between users who have upload access
- Chat history is saved per user
- The database and documents are stored in the `data/` folder

## License

Internal use for e& Business Network Operations department.
