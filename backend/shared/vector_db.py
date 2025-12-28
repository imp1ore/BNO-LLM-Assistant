"""
Vector database abstraction layer
Switch between different vector databases easily (ChromaDB, Qdrant, etc.)
"""
from typing import List, Tuple, Optional
import config

# Initialize vector DB lazily
_vector_db = None


def init_vector_db():
    """Initialize vector database based on configuration"""
    global _vector_db
    
    if config.VECTOR_DB_TYPE == "chromadb":
        _vector_db = _init_chromadb()
    elif config.VECTOR_DB_TYPE == "qdrant":
        _vector_db = _init_qdrant()
    elif config.VECTOR_DB_TYPE == "in_memory":
        _vector_db = _init_in_memory()
    else:
        raise ValueError(f"Vector DB type not supported: {config.VECTOR_DB_TYPE}")
    
    return _vector_db


def get_vector_db():
    """Get vector database instance"""
    global _vector_db
    if _vector_db is None:
        init_vector_db()
    
    # For file-based in-memory, reload from disk to get latest data
    if config.VECTOR_DB_TYPE == "in_memory" and _vector_db:
        storage_file = _vector_db.get("storage_file")
        if storage_file and storage_file.exists():
            try:
                with open(storage_file, "rb") as f:
                    data = pickle.load(f)
                    _vector_db["chunks"] = data.get("chunks", _vector_db["chunks"])
                    _vector_db["embeddings"] = data.get("embeddings", _vector_db["embeddings"])
                    _vector_db["metadata"] = data.get("metadata", _vector_db["metadata"])
            except Exception:
                pass  # Use existing data if load fails
    
    return _vector_db


def add_documents(chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add documents to vector database"""
    db = get_vector_db()
    
    if config.VECTOR_DB_TYPE == "chromadb":
        _add_to_chromadb(db, chunks, embeddings, metadata)
    elif config.VECTOR_DB_TYPE == "qdrant":
        _add_to_qdrant(db, chunks, embeddings, metadata)
    elif config.VECTOR_DB_TYPE == "in_memory":
        _add_to_in_memory(db, chunks, embeddings, metadata)


def search(query_embedding: List[float], top_k: int = None) -> List[Tuple[str, float]]:
    """Search for similar documents"""
    if top_k is None:
        top_k = config.TOP_K_RETRIEVAL
    
    db = get_vector_db()
    
    if config.VECTOR_DB_TYPE == "chromadb":
        return _search_chromadb(db, query_embedding, top_k)
    elif config.VECTOR_DB_TYPE == "qdrant":
        return _search_qdrant(db, query_embedding, top_k)
    elif config.VECTOR_DB_TYPE == "in_memory":
        return _search_in_memory(db, query_embedding, top_k)


def delete_documents(document_ids: List[str] = None, user_id: int = None):
    """Delete documents from vector database"""
    db = get_vector_db()
    
    if config.VECTOR_DB_TYPE == "chromadb":
        _delete_from_chromadb(db, document_ids, user_id)
    elif config.VECTOR_DB_TYPE == "qdrant":
        _delete_from_qdrant(db, document_ids, user_id)
    elif config.VECTOR_DB_TYPE == "in_memory":
        _delete_from_in_memory(db, document_ids, user_id)


# ============================================================================
# ChromaDB Implementation
# ============================================================================
def _init_chromadb():
    """Initialize ChromaDB"""
    import chromadb
    from chromadb.config import Settings
    
    client = chromadb.PersistentClient(
        path=config.CHROMADB_CONFIG["persist_directory"],
        settings=Settings(anonymized_telemetry=False)
    )
    
    collection = client.get_or_create_collection(
        name=config.CHROMADB_CONFIG["collection_name"]
    )
    
    return {"client": client, "collection": collection}


def _add_to_chromadb(db: dict, chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add documents to ChromaDB"""
    collection = db["collection"]
    ids = [f"doc_{i}_{hash(chunk)}" for i, chunk in enumerate(chunks)]
    
    if metadata is None:
        metadata = [{}] * len(chunks)
    
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadata
    )


def _search_chromadb(db: dict, query_embedding: List[float], top_k: int) -> List[Tuple[str, float]]:
    """Search ChromaDB"""
    collection = db["collection"]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    if not results['documents'] or not results['documents'][0]:
        return []
    
    chunks = results['documents'][0]
    distances = results['distances'][0]
    
    # Convert distance to similarity (ChromaDB returns distance, we want similarity)
    similarities = [(chunk, 1 - dist) for chunk, dist in zip(chunks, distances)]
    return similarities


def _delete_from_chromadb(db: dict, document_ids: List[str] = None, user_id: int = None):
    """Delete from ChromaDB"""
    collection = db["collection"]
    if document_ids:
        collection.delete(ids=document_ids)
    elif user_id:
        # Get all documents with this user_id and delete
        results = collection.get(where={"user_id": user_id})
        if results['ids']:
            collection.delete(ids=results['ids'])


# ============================================================================
# File-Based In-Memory Implementation (persists to disk for multi-process access)
# ============================================================================
import json
import pickle
import os
from pathlib import Path

def _init_in_memory():
    """Initialize file-based vector storage"""
    storage_file = config.VECTORS_DIR / "vector_store.pkl"
    
    # Load existing data if it exists
    if storage_file.exists():
        try:
            with open(storage_file, "rb") as f:
                data = pickle.load(f)
                return {
                    "chunks": data.get("chunks", []),
                    "embeddings": data.get("embeddings", []),
                    "metadata": data.get("metadata", []),
                    "storage_file": storage_file
                }
        except Exception as e:
            print(f"Warning: Could not load vector store: {e}")
    
    return {
        "chunks": [],
        "embeddings": [],
        "metadata": [],
        "storage_file": storage_file
    }


def _save_to_disk(db: dict):
    """Save vector database to disk"""
    storage_file = db.get("storage_file")
    if not storage_file:
        return
    
    try:
        # Ensure directory exists
        storage_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Simple write (Windows doesn't support fcntl, and simple write should work for demo)
        with open(storage_file, "wb") as f:
            pickle.dump({
                "chunks": db["chunks"],
                "embeddings": db["embeddings"],
                "metadata": db["metadata"]
            }, f)
        print(f"Saved {len(db['chunks'])} chunks to {storage_file}")
    except Exception as e:
        print(f"ERROR: Could not save vector store to {storage_file}: {e}")
        import traceback
        traceback.print_exc()


def _add_to_in_memory(db: dict, chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add to file-based storage"""
    db["chunks"].extend(chunks)
    db["embeddings"].extend(embeddings)
    if metadata:
        db["metadata"].extend(metadata)
    else:
        db["metadata"].extend([{}] * len(chunks))
    
    # Persist to disk
    _save_to_disk(db)


def _search_in_memory(db: dict, query_embedding: List[float], top_k: int) -> List[Tuple[str, float]]:
    """Search file-based storage using cosine similarity"""
    import math
    
    # Reload from disk to get latest data (in case another process added data)
    storage_file = db.get("storage_file")
    if storage_file and storage_file.exists():
        try:
            with open(storage_file, "rb") as f:
                data = pickle.load(f)
                db["chunks"] = data.get("chunks", db["chunks"])
                db["embeddings"] = data.get("embeddings", db["embeddings"])
                db["metadata"] = data.get("metadata", db["metadata"])
        except Exception:
            pass  # Use in-memory data if load fails
    
    similarities = []
    for chunk, embedding in zip(db["chunks"], db["embeddings"]):
        # Cosine similarity
        dot_product = sum(a * b for a, b in zip(query_embedding, embedding))
        magnitude1 = math.sqrt(sum(a * a for a in query_embedding))
        magnitude2 = math.sqrt(sum(a * a for a in embedding))
        similarity = dot_product / (magnitude1 * magnitude2) if magnitude1 * magnitude2 > 0 else 0
        similarities.append((chunk, similarity))
    
    # Sort by similarity (descending) and return top_k
    # Use stable sort with secondary key (chunk text) for deterministic results when scores are equal
    similarities.sort(key=lambda x: (-x[1], x[0]))  # Negative score for descending, chunk text for tie-breaking
    return similarities[:top_k]


def _delete_from_in_memory(db: dict, document_ids: List[str] = None, user_id: int = None):
    """Delete from file-based storage - fully synchronized deletion"""
    # Reload from disk first to ensure we have latest data
    storage_file = db.get("storage_file")
    if storage_file and storage_file.exists():
        try:
            with open(storage_file, "rb") as f:
                data = pickle.load(f)
                db["chunks"] = data.get("chunks", db["chunks"])
                db["embeddings"] = data.get("embeddings", db["embeddings"])
                db["metadata"] = data.get("metadata", db["metadata"])
        except Exception as e:
            print(f"[WARNING] Could not reload vector store: {e}")
    
    if document_ids is None and user_id is None:
        return
    
    # Filter out chunks to delete
    filtered_chunks = []
    filtered_embeddings = []
    filtered_metadata = []
    removed_count = 0
    
    for chunk, embedding, meta in zip(db["chunks"], db["embeddings"], db["metadata"]):
        should_remove = False
        
        # Check if this chunk should be deleted
        if document_ids and str(meta.get("document_id", "")) in [str(did) for did in document_ids]:
            should_remove = True
        if user_id and meta.get("user_id") == user_id:
            should_remove = True
        
        if not should_remove:
            filtered_chunks.append(chunk)
            filtered_embeddings.append(embedding)
            filtered_metadata.append(meta)
        else:
            removed_count += 1
    
    db["chunks"] = filtered_chunks
    db["embeddings"] = filtered_embeddings
    db["metadata"] = filtered_metadata
    
    print(f"[DELETE] Removed {removed_count} chunks from vector database")
    
    # Persist to disk immediately
    _save_to_disk(db)
    
    # Verify deletion
    remaining = sum(1 for meta in db.get("metadata", []) 
                   if (document_ids and str(meta.get("document_id", "")) in [str(did) for did in document_ids]) or
                      (user_id and meta.get("user_id") == user_id))
    if remaining > 0:
        print(f"[WARNING] {remaining} chunks still remain after deletion - may need manual cleanup")


# ============================================================================
# Qdrant Implementation (placeholder - can be implemented later)
# ============================================================================
def _init_qdrant():
    """Initialize Qdrant"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    
    client = QdrantClient(
        url=config.QDRANT_CONFIG["url"],
        api_key=config.QDRANT_CONFIG.get("api_key")
    )
    
    # Create collection if it doesn't exist
    try:
        client.get_collection(config.QDRANT_CONFIG["collection_name"])
    except:
        client.create_collection(
            collection_name=config.QDRANT_CONFIG["collection_name"],
            vectors_config=VectorParams(size=768, distance=Distance.COSINE)
        )
    
    return {"client": client, "collection_name": config.QDRANT_CONFIG["collection_name"]}


def _add_to_qdrant(db: dict, chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add to Qdrant"""
    from qdrant_client.models import PointStruct
    
    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_metadata = metadata[i] if metadata else {}
        point_metadata["text"] = chunk
        points.append(PointStruct(
            id=i,
            vector=embedding,
            payload=point_metadata
        ))
    
    db["client"].upsert(
        collection_name=db["collection_name"],
        points=points
    )


def _search_qdrant(db: dict, query_embedding: List[float], top_k: int) -> List[Tuple[str, float]]:
    """Search Qdrant"""
    results = db["client"].search(
        collection_name=db["collection_name"],
        query_vector=query_embedding,
        limit=top_k
    )
    
    return [(result.payload["text"], result.score) for result in results]


def _delete_from_qdrant(db: dict, document_ids: List[str] = None, user_id: int = None):
    """Delete from Qdrant"""
    if document_ids:
        db["client"].delete(
            collection_name=db["collection_name"],
            points_selector=document_ids
        )

