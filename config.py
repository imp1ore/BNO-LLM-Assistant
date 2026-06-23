"""
Configuration file for BNO LLM Assistant
Switch between local development and production deployment easily
"""
import os
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent

# Load environment variables from a .env file in the project root (if present).
# This makes all the os.getenv(...) settings below configurable per-environment
# without editing code. Safe no-op if python-dotenv isn't installed.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
VECTORS_DIR = DATA_DIR / "vectors"
DATABASE_PATH = DATA_DIR / "database.db"

# Ensure directories exist
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
VECTORS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# LLM PROVIDER CONFIGURATION
# ============================================================================
# Options: "ollama", "openai", "anthropic", "vllm", "azure_openai"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

# Ollama Configuration (default provider; runs fully on-premises)
# - embedding_model: turns text into vectors for retrieval (bge-base, 768-dim)
# - language_model: generates the answers. llama3.2:3b is a good balance of
#   quality and speed on CPU/modest GPUs. For higher quality on a stronger
#   server, pull a larger model (e.g. `ollama pull llama3.1:8b`) and set it here.
OLLAMA_CONFIG = {
    "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "embedding_model": os.getenv("OLLAMA_EMBEDDING_MODEL", "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf"),
    "language_model": os.getenv("OLLAMA_LANGUAGE_MODEL", "llama3.2:3b"),
    "timeout": 120
}

# OpenAI Configuration (Production Option)
OPENAI_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "embedding_model": "text-embedding-3-small",
    "language_model": "gpt-3.5-turbo",
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
}

# Anthropic Configuration (Production Option)
ANTHROPIC_CONFIG = {
    "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "language_model": "claude-3-haiku-20240307"
}

# vLLM Configuration (Self-hosted Production)
VLLM_CONFIG = {
    "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
    "embedding_model": "BAAI/bge-base-en-v1.5",
    "language_model": "meta-llama/Llama-2-7b-chat-hf"
}

# ============================================================================
# VECTOR DATABASE CONFIGURATION
# ============================================================================
# Current: "chromadb" - Production-ready vector database
# - Handles storage, indexing, and search automatically
# - No disk reload issues (in-memory caching)
# - Requires: pip install chromadb
#
# Future: "pinecone" - Cloud vector database for enterprise scale
# - Fully managed, auto-scaling
# - Requires: pip install pinecone-client
VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "chromadb")

# ChromaDB Configuration (Current - Production-ready)
CHROMADB_CONFIG = {
    "persist_directory": str(VECTORS_DIR / "chromadb"),
    "collection_name": "bno_documents"
}

# Pinecone Configuration (Future - Cloud Production)
PINECONE_CONFIG = {
    "api_key": os.getenv("PINECONE_API_KEY", ""),
    "environment": os.getenv("PINECONE_ENVIRONMENT", ""),
    "index_name": "bno-documents"
}

# ============================================================================
# SERVER CONFIGURATION
# ============================================================================
# A single process serves the web UI, API, and RAG engine. Set API_SERVER_HOST
# to 0.0.0.0 in production so other machines on the network can reach it.
API_SERVER_PORT = int(os.getenv("API_SERVER_PORT", "9000"))
API_SERVER_HOST = os.getenv("API_SERVER_HOST", "127.0.0.1")

# ============================================================================
# APPLICATION CONFIGURATION
# ============================================================================
# Security
# IMPORTANT: In production, set SECRET_KEY via the environment (.env or systemd).
# The default below is for local development only - anyone with the source can
# forge login tokens if it is used on a real server.
_DEFAULT_SECRET_KEY = "verysecretivekey200"
SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET_KEY)
if SECRET_KEY == _DEFAULT_SECRET_KEY:
    # Print to stderr so it never pollutes stdout when scripts read config values.
    print(
        "[config] WARNING: Using the built-in default SECRET_KEY. "
        "Set SECRET_KEY in your .env before deploying to a shared server.",
        file=sys.stderr,
    )
JWT_ALGORITHM = "HS256"

# Default admin account (created on first startup if it doesn't exist).
# Override these in .env so the server does not ship with admin/admin.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# Account / registration policy
# Open self-registration is OFF by default - in a corporate deployment, accounts
# should be created by an admin. Set ALLOW_REGISTRATION=true to enable the public
# /api/auth/register endpoint.
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "false").lower() in ("1", "true", "yes", "on")
# Minimum password length enforced on registration, admin user creation, and
# password changes/resets.
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "8"))
JWT_EXPIRATION_HOURS = 8  # Token expires after 8 hours (enterprise standard)
SESSION_TIMEOUT_MINUTES = 30  # Auto-logout after 30 minutes of inactivity

# RAG Configuration
# Optimized for llama3.2:3b model (smaller context window)
CHUNK_SIZE = 600  # Characters per chunk (optimized for 3B model - prevents overload)
CHUNK_OVERLAP = 120  # Overlap between chunks (20% of chunk size for better context continuity)
TOP_K_RETRIEVAL = 5  # Number of chunks to retrieve (reduced from 10 to prevent model overload)
SIMILARITY_THRESHOLD = 0.3  # Minimum similarity score to include a chunk (0.0-1.0, higher = more strict)

# File Upload
MAX_FILE_SIZE_MB = 50
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

# e& Branding Colors (official brand palette)
BRAND_COLORS = {
    "primary": "#E00800",    # Official e& Red (Pantone 2347C)
    "secondary": "#2B2B2E",  # Dark grey
    "background": "#F6F6F7"
}

