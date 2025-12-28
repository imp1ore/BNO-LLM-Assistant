# BNO LLM Assistant

**Version:** Beta v1.0.0

A local AI assistant web application for the e& Business Network Operations department. Users can upload company documents and ask questions, with the AI providing answers based on the uploaded content using Retrieval-Augmented Generation (RAG).

## Features

- 🔐 **User Authentication** - Secure login/registration system
- 👥 **User Management** - Admin panel for managing users
- 📄 **Document Upload** - Support for PDF, DOCX, PPTX, and TXT files
- 🤖 **AI Chat** - Ask questions and get answers based on uploaded documents
- 💬 **Chat History** - Save and manage multiple conversations
- 🗑️ **Chat Management** - Delete individual chats or bulk delete
- 🎨 **e& Branding** - Custom UI with e& red (#DC143C) and black color scheme

## Architecture

The application consists of two servers:

1. **LLM Server** (Port 8000) - Handles RAG queries and AI inference
2. **API Server** (Port 9000) - Handles authentication, document management, and chat

## Prerequisites

- Python 3.8 or higher
- Ollama installed and running
- Required Ollama models downloaded (see Setup below)

## Git Repository Setup

This project uses Git for version control. To set up:

1. **Install Git** (if not installed): https://git-scm.com/download/win
2. **Run the setup script**: `setup_git.bat` (Windows) or follow `SETUP_GIT.md`
3. **Push to your repository**: `git push -u origin main`

Repository: https://github.com/imp1ore/BNOLLM.git

## Quick Start

### 1. Install Ollama

Download and install Ollama from [ollama.com](https://ollama.com)

### 2. Download Models

Open a terminal and run:

```bash
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
ollama pull hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run System Test

Verify everything is set up correctly:

```bash
python test_system.py
```

### 5. Start the Application

**Windows:**
```bash
scripts\start.bat
```

**Linux/macOS:**
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### 6. Open in Browser

Navigate to: http://127.0.0.1:9000

## Usage

1. **Register/Login** - Create an account or login
2. **Upload Documents** - Click "Upload Document" and select PDF, DOCX, PPTX, or TXT files
3. **Ask Questions** - Type questions in the chat input and get AI-powered answers
4. **Manage Chats** - View chat history in the sidebar, create new chats, or delete old ones

## Project Structure

```
BNO-LLM/
├── backend/
│   ├── api_server/          # FastAPI server (port 9000)
│   │   ├── main.py          # Main API server
│   │   ├── auth.py           # Authentication utilities
│   │   └── models.py         # Pydantic models
│   ├── llm_server/          # LLM/RAG server (port 8000)
│   │   ├── main.py          # LLM server
│   │   └── rag_engine.py    # RAG engine
│   └── shared/              # Shared utilities
│       ├── database.py      # Database models
│       ├── document_processor.py  # Document parsing
│       ├── llm_providers.py # LLM abstraction layer
│       └── vector_db.py      # Vector database abstraction
├── frontend/                # Web UI
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/                 # Startup scripts
│   ├── start.bat           # Windows
│   └── start.sh            # Linux/macOS
├── data/                    # Data storage
│   ├── documents/          # Uploaded documents
│   ├── vectors/            # Vector database
│   └── database.db         # SQLite database
├── config.py               # Configuration
├── requirements.txt        # Python dependencies
├── test_system.py         # System test script
└── README.md
```

## Configuration

Edit `config.py` to customize:

- **LLM Provider** - Switch between Ollama, OpenAI, Anthropic, etc.
- **Vector Database** - Choose ChromaDB, Qdrant, Pinecone, etc.
- **Server Ports** - Change default ports if needed
- **Chunk Size** - Adjust document chunking parameters

### Environment Variables

You can override settings using environment variables:

```bash
# LLM Provider
export LLM_PROVIDER=ollama  # or openai, anthropic

# Vector Database
export VECTOR_DB_TYPE=chromadb  # or qdrant, pinecone

# Server Ports
export API_SERVER_PORT=9000
export LLM_SERVER_PORT=8000

# API Keys (for cloud providers)
export OPENAI_API_KEY=your-key-here
export ANTHROPIC_API_KEY=your-key-here
```

## Enterprise Deployment

This application is designed to be easily deployable to enterprise environments:

### Local Development (Current Setup)
- Uses Ollama for local LLM inference
- ChromaDB for vector storage
- SQLite for user data

### Production Deployment Options

1. **LLM Providers:**
   - Keep Ollama on a GPU server
   - Switch to OpenAI/Anthropic APIs
   - Use vLLM for self-hosted production

2. **Vector Database:**
   - Upgrade to Qdrant (self-hosted or cloud)
   - Use Pinecone (managed cloud)
   - Use Weaviate

3. **Database:**
   - Migrate from SQLite to PostgreSQL
   - Add connection pooling

4. **Infrastructure:**
   - Deploy behind load balancer
   - Add multiple API server instances
   - Set up monitoring and logging

Simply change the configuration in `config.py` or use environment variables to switch between local and production setups.

## Troubleshooting

### Ollama Connection Error
- Make sure Ollama is running: `ollama list`
- Check if models are downloaded: `ollama list`
- Verify Ollama service is accessible

### Port Already in Use
- Change ports in `config.py`
- Or stop the process using the port

### Import Errors
- Run: `pip install -r requirements.txt`
- Make sure you're using Python 3.8+

### Document Processing Fails
- Check file format is supported (PDF, DOCX, PPTX, TXT)
- Verify file is not corrupted
- Check file size (max 50MB by default)

## Development

### Running Tests

```bash
python test_system.py
```

### Manual Server Start

Start LLM server:
```bash
python -m backend.llm_server.main
```

Start API server (in another terminal):
```bash
python -m backend.api_server.main
```

## Security Notes

- Change `SECRET_KEY` in `config.py` for production
- Use environment variables for sensitive data
- Implement proper authentication for production
- Add rate limiting for API endpoints
- Use HTTPS in production

## License

Internal use for e& Business Network Operations department.

## Support

For issues or questions, contact the development team.

