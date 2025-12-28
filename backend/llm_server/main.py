"""
LLM Server - Handles RAG queries on port 8000
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.llm_server.rag_engine import RAGEngine
import config

app = FastAPI(title="BNO LLM Server", version="1.0.0")

# Initialize RAG engine
rag_engine = RAGEngine()


class QueryRequest(BaseModel):
    """Request model for RAG query"""
    query: str
    top_k: Optional[int] = None


class QueryResponse(BaseModel):
    """Response model for RAG query"""
    response: str
    retrieved_chunks: List[str]
    similarity_scores: List[float]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    provider: str
    vector_db: str


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        provider=config.LLM_PROVIDER,
        vector_db=config.VECTOR_DB_TYPE
    )


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """
    Process RAG query
    
    Args:
        request: Query request with question
    
    Returns:
        Response with answer and retrieved chunks
    """
    try:
        result = rag_engine.query(request.query, top_k=request.top_k)
        return QueryResponse(
            response=result["response"],
            retrieved_chunks=result["retrieved_chunks"],
            similarity_scores=result["similarity_scores"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "BNO LLM Server",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "query": "/query (POST)"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.LLM_SERVER_HOST,
        port=config.LLM_SERVER_PORT,
        log_level="info"
    )

