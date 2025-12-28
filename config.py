"""
Configuration file for BNO LLM Assistant
Switch between local development and production deployment easily
"""
import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent
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

# Ollama Configuration (Local Development)
OLLAMA_CONFIG = {
    "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "embedding_model": "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf",
    "language_model": "hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF",
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
# Options: "chromadb", "qdrant", "pinecone", "weaviate", "in_memory"
# Using "in_memory" for demo - file-based persistence, works immediately
# Note: "in_memory" now uses file-based storage so both servers can share data
VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "in_memory")

# ChromaDB Configuration (Local/Simple)
CHROMADB_CONFIG = {
    "persist_directory": str(VECTORS_DIR / "chromadb"),
    "collection_name": "bno_documents"
}

# Qdrant Configuration (Production)
QDRANT_CONFIG = {
    "url": os.getenv("QDRANT_URL", "http://localhost:6333"),
    "api_key": os.getenv("QDRANT_API_KEY", ""),
    "collection_name": "bno_documents"
}

# Pinecone Configuration (Cloud Production)
PINECONE_CONFIG = {
    "api_key": os.getenv("PINECONE_API_KEY", ""),
    "environment": os.getenv("PINECONE_ENVIRONMENT", ""),
    "index_name": "bno-documents"
}

# ============================================================================
# SERVER CONFIGURATION
# ============================================================================
API_SERVER_PORT = int(os.getenv("API_SERVER_PORT", "9000"))
LLM_SERVER_PORT = int(os.getenv("LLM_SERVER_PORT", "8000"))
API_SERVER_HOST = os.getenv("API_SERVER_HOST", "127.0.0.1")
LLM_SERVER_HOST = os.getenv("LLM_SERVER_HOST", "127.0.0.1")

# ============================================================================
# APPLICATION CONFIGURATION
# ============================================================================
# Security
SECRET_KEY = os.getenv("SECRET_KEY", "verysecretivekey200")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8  # Token expires after 8 hours (enterprise standard)
SESSION_TIMEOUT_MINUTES = 30  # Auto-logout after 30 minutes of inactivity

# RAG Configuration
CHUNK_SIZE = 500  # Characters per chunk
CHUNK_OVERLAP = 100  # Overlap between chunks (20% of chunk size for better context continuity)
TOP_K_RETRIEVAL = 5  # Number of chunks to retrieve (increased for better context coverage)

# File Upload
MAX_FILE_SIZE_MB = 50
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

# e& Branding Colors
BRAND_COLORS = {
    "primary": "#DC143C",  # Red
    "secondary": "#000000",  # Black
    "background": "#FFFFFF"
}

