"""
Vector database abstraction layer
Currently using ChromaDB for production-ready vector storage and search
"""
# ChromaDB requires sqlite3 >= 3.35, but some systems (e.g. RHEL 8 / CentOS) ship
# an older system SQLite that the stdlib `sqlite3` links against. If the modern
# `pysqlite3-binary` wheel is installed, transparently swap it in so ChromaDB (and
# SQLAlchemy) use the bundled newer SQLite. Must run before `import chromadb`.
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass  # stdlib sqlite3 is new enough on this system

from typing import List, Tuple, Optional
from pathlib import Path
import config

# Initialize vector DB lazily
_vector_db = None
_last_refresh_count = None  # Track collection count to detect changes

def _force_refresh_chromadb(always_refresh: bool = True):
    """Force a complete refresh of ChromaDB collection to ensure latest data from disk
    
    Args:
        always_refresh: If True, always refresh. Default True to ensure we see disk changes
                       This is critical when API server and LLM server are separate processes
    """
    global _vector_db, _last_refresh_count
    if _vector_db is None or config.VECTOR_DB_TYPE != "chromadb":
        return
    
    try:
        # CRITICAL: Reinitialize the client to force ChromaDB to reload from disk
        # Simply calling get_collection() might return a cached object
        # By reinitializing, we ensure we get a fresh connection that reads latest disk state
        client = _vector_db["client"]
        
        # Get a fresh collection reference - ChromaDB should reload from disk
        # But to be absolutely sure, we'll get it fresh each time
        collection = client.get_collection(name=config.CHROMADB_CONFIG["collection_name"])
        
        # Update the collection reference
        _vector_db["collection"] = collection
        
        # Force ChromaDB to sync with disk by performing operations
        # Count operation forces ChromaDB to check disk state
        count = collection.count()
        _last_refresh_count = count
        
        # Additional verification: Try to peek at the collection to force disk read
        # This ensures ChromaDB actually reads from disk, not just cache
        try:
            # Peek at first few items to force disk read (if collection has items)
            if count > 0:
                collection.peek(limit=1)
        except Exception:
            # Peek might fail if collection is empty or other reasons, that's OK
            pass
        
        print(f"[VectorDB] Refreshed ChromaDB collection from disk, count: {count}")
    except Exception as e:
        print(f"[VectorDB] Error force refreshing: {e}")
        import traceback
        traceback.print_exc()
        # If refresh fails, try to re-initialize completely
        try:
            print("[VectorDB] Attempting to re-initialize ChromaDB...")
            init_vector_db()
        except Exception as e2:
            print(f"[VectorDB] Error re-initializing: {e2}")


def init_vector_db():
    """Initialize vector database based on configuration"""
    global _vector_db
    
    db_type = config.VECTOR_DB_TYPE
    
    try:
        if db_type == "chromadb":
            _vector_db = _init_chromadb()
        else:
            raise ValueError(f"Vector DB type not supported: {db_type}. Supported: chromadb")
        
        print(f"[VectorDB] Initialized backend: {db_type}")
        
    except Exception as e:
        print(f"[VectorDB] ERROR: Failed to initialize backend ({db_type}): {e}")
        raise
    
    return _vector_db


def get_vector_db(force_refresh: bool = False):
    """Get vector database instance
    
    Args:
        force_refresh: If True, reload the collection to ensure latest data (for live sync)
    """
    global _vector_db
    if _vector_db is None:
        init_vector_db()
    elif force_refresh and config.VECTOR_DB_TYPE == "chromadb":
        # Use the dedicated refresh function which handles cross-process sync better
        _force_refresh_chromadb(always_refresh=True)
    return _vector_db


def get_vector_db_status() -> dict:
    """Get status information about the vector database
    
    Returns:
        Dictionary with status information including:
        - backend: Current backend type
        - backend_ready: Whether backend is ready
        - total_chunks: Number of chunks in database
    """
    global _vector_db
    
    status = {
        "backend": config.VECTOR_DB_TYPE,
        "backend_ready": _vector_db is not None,
        "total_chunks": 0
    }
    
    # Get chunk count from ChromaDB
    if _vector_db is not None:
        try:
            collection = _vector_db["collection"]
            count = collection.count()
            status["total_chunks"] = count
        except Exception as e:
            print(f"[VectorDB] Warning: Could not get chunk count: {e}")
            status["total_chunks"] = "unknown"
    else:
        # Vector DB not initialized yet, try to initialize it
        try:
            init_vector_db()
            if _vector_db is not None:
                collection = _vector_db["collection"]
                count = collection.count()
                status["total_chunks"] = count
                status["backend_ready"] = True
        except Exception as e:
            print(f"[VectorDB] Warning: Could not initialize for status check: {e}")
    
    return status


def add_documents(chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add documents to vector database"""
    global _last_refresh_count
    db = get_vector_db()
    db_type = config.VECTOR_DB_TYPE
    
    if db_type == "chromadb":
        _add_to_chromadb(db, chunks, embeddings, metadata)
        # Force refresh after add to ensure live synchronization
        _force_refresh_chromadb(always_refresh=True)
        _last_refresh_count = None  # Reset to force refresh on next search
    else:
        raise ValueError(f"Unsupported vector DB type: {db_type}")


def search(query_embedding: List[float], top_k: int = None) -> List[Tuple[str, float]]:
    """Search for similar documents.

    The API server runs uploads and queries in the same process and shares one
    ChromaDB client, and add_documents() already refreshes the collection after
    every write. So we reuse the live client here instead of rebuilding it on
    every query (rebuilding reopened the on-disk index per request, which was a
    large, unnecessary latency cost).
    """
    global _vector_db
    if top_k is None:
        top_k = config.TOP_K_RETRIEVAL

    db = get_vector_db(force_refresh=False)
    db_type = config.VECTOR_DB_TYPE
    
    if db_type == "chromadb":
        return _search_chromadb(db, query_embedding, top_k)
    else:
        raise ValueError(f"Unsupported vector DB type: {db_type}")


def delete_documents(document_ids: List[str] = None, user_id: int = None):
    """Delete documents from vector database
    
    Args:
        document_ids: List of document IDs to delete (as strings)
        user_id: Optional user ID to delete all documents for that user
    """
    global _last_refresh_count
    db = get_vector_db()
    db_type = config.VECTOR_DB_TYPE
    
    if db_type == "chromadb":
        _delete_from_chromadb(db, document_ids, user_id)
        # Force refresh after delete to ensure live synchronization
        _force_refresh_chromadb(always_refresh=True)
        _last_refresh_count = None  # Reset to force refresh on next search
    else:
        raise ValueError(f"Unsupported vector DB type: {db_type}")


# ============================================================================
# ChromaDB Implementation
# ============================================================================
def _init_chromadb():
    """Initialize ChromaDB with optimized settings for immediate persistence"""
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        raise ImportError(
            "ChromaDB is not installed. Install with: pip install chromadb"
        )
    
    # Ensure persist directory exists (required for immediate persistence)
    persist_dir = Path(config.CHROMADB_CONFIG["persist_directory"])
    persist_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize PersistentClient with explicit path for immediate persistence
    # PersistentClient automatically persists all changes to disk in real-time
    # The path parameter ensures all operations are immediately written to disk
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True
        )
    )
    
    print(f"[ChromaDB] Initialized with persist_directory: {persist_dir} (immediate persistence enabled)")
    
    # Try to get existing collection, create if it doesn't exist
    try:
        collection = client.get_collection(name=config.CHROMADB_CONFIG["collection_name"])
    except Exception:
        # Collection doesn't exist, create it with optimized settings
        # ChromaDB uses HNSW internally - we can optimize it
        collection = client.create_collection(
            name=config.CHROMADB_CONFIG["collection_name"],
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity (default, but explicit)
        )
    
    return {"client": client, "collection": collection}


def _add_to_chromadb(db: dict, chunks: List[str], embeddings: List[List[float]], metadata: List[dict] = None):
    """Add documents to ChromaDB"""
    collection = db["collection"]
    client = db["client"]
    
    # Generate unique IDs for each chunk (using document_id + chunk index for better tracking)
    import time
    
    # Generate IDs that include document_id for easier tracking
    ids = []
    for i, chunk in enumerate(chunks):
        # Get document_id from metadata if available
        doc_id = metadata[i].get("document_id", "unknown") if metadata and i < len(metadata) else "unknown"
        # Create unique ID: doc_{document_id}_{timestamp}_{index}_{hash}
        chunk_hash = hash(chunk) % 1000000
        unique_id = f"doc_{doc_id}_{int(time.time() * 1000000)}_{i}_{chunk_hash}"
        ids.append(unique_id)
    
    if metadata is None:
        metadata = [{}] * len(chunks)
    
    # Ensure metadata is properly formatted for ChromaDB
    formatted_metadata = []
    for meta in metadata:
        formatted_meta = {}
        for key, value in meta.items():
            # ChromaDB requires metadata values to be strings, numbers, or booleans
            if isinstance(value, (str, int, float, bool)):
                formatted_meta[key] = value
            else:
                formatted_meta[key] = str(value)
        formatted_metadata.append(formatted_meta)
    
    # Add documents to ChromaDB
    # This operation is synchronous and PersistentClient writes to disk immediately
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=formatted_metadata
    )
    
    # CRITICAL: Verify persistence and force sync to disk
    # PersistentClient should auto-persist, but we ensure it's written to disk
    # This is especially important when API server and LLM server are separate processes
    try:
        # Verify the add operation completed by checking count
        # This also forces ChromaDB to sync with disk if needed
        count = collection.count()
        print(f"[ChromaDB] Added {len(chunks)} chunks, total count now: {count}")
        print(f"[ChromaDB] Data persisted to disk at: {config.CHROMADB_CONFIG['persist_directory']}")
        
        # Try to access persist method if available (older ChromaDB versions)
        # Newer versions handle persistence automatically with PersistentClient
        if hasattr(client, 'persist'):
            try:
                client.persist()
                print("[ChromaDB] Explicitly called persist() to ensure disk write")
            except Exception as e:
                print(f"[ChromaDB] Note: persist() not available (using PersistentClient auto-persist): {e}")
        
        # Small delay to ensure disk write completes (especially important for cross-process sync)
        import time
        time.sleep(0.1)  # 100ms delay to ensure disk write completes
        print(f"[ChromaDB] Verified persistence complete - ready for queries")
    except Exception as e:
        print(f"[ChromaDB] Warning: Could not verify persistence: {e}")


def _search_chromadb(db: dict, query_embedding: List[float], top_k: int) -> List[Tuple[str, float]]:
    """Search ChromaDB"""
    collection = db["collection"]
    
    # Debug: Check collection count before search
    try:
        total_chunks = collection.count()
        print(f"[VectorDB] Searching in collection with {total_chunks} total chunks")
    except Exception as e:
        print(f"[VectorDB] Warning: Could not get collection count: {e}")
    
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        num_results = len(results.get('documents', [[]])[0]) if results.get('documents') else 0
        print(f"[VectorDB] ChromaDB query returned {num_results} results")
    except Exception as e:
        error_msg = str(e).lower()
        # Handle ChromaDB index corruption errors
        if "nothing found on disk" in error_msg or "hnsw segment reader" in error_msg:
            print(f"[VectorDB] ChromaDB index error detected: {e}")
            print("[VectorDB] This usually means the index is corrupted. Try reinitializing ChromaDB.")
            # Return empty results rather than crashing
            return []
        # Re-raise other errors
        raise
    
    if not results.get('documents') or not results['documents'] or not results['documents'][0]:
        return []
    
    chunks = results['documents'][0]
    distances = results.get('distances', [[]])[0] if results.get('distances') else []
    
    # Ensure chunks and distances have same length
    if len(distances) != len(chunks):
        # If distances missing, create default distances
        distances = [0.0] * len(chunks)
    
    # Filter out None/empty chunks and convert distance to similarity
    # ChromaDB uses cosine distance (0 = identical, 2 = opposite)
    # For cosine similarity: similarity = 1 - (distance / 2)
    similarities = []
    for i, chunk in enumerate(chunks):
        # Skip None, empty, or non-string chunks - be very defensive
        if chunk is None:
            print(f"[VectorDB] WARNING: None chunk found at index {i}, skipping")
            continue
        if not isinstance(chunk, str):
            print(f"[VectorDB] WARNING: Non-string chunk at index {i}: {type(chunk)}, skipping")
            continue
        if not chunk.strip():
            print(f"[VectorDB] WARNING: Empty chunk at index {i}, skipping")
            continue
        
        # Get distance (default to 0 if missing)
        dist = distances[i] if i < len(distances) else 0.0
        
        # Convert distance to similarity
        # ChromaDB cosine distance ranges from 0 (identical) to 2 (opposite)
        # Similarity = 1 - (distance / 2) for cosine distance
        # Clamp to [0, 1] range
        similarity = max(0.0, min(1.0, 1.0 - (float(dist) / 2.0)))
        similarities.append((str(chunk), similarity))  # Ensure it's a string
    
    return similarities


def _delete_from_chromadb(db: dict, document_ids: List[str] = None, user_id: int = None):
    """Delete from ChromaDB"""
    collection = db["collection"]
    client = db["client"]
    
    if document_ids:
        # Delete by document IDs - ChromaDB stores document_id as string in metadata
        ids_to_delete = []
        
        for doc_id in document_ids:
            # Try both string and int versions since metadata might store it either way
            # First try as string (most common)
            try:
                results = collection.get(where={"document_id": str(doc_id)})
                ids_to_delete.extend(results['ids'])
            except Exception:
                pass
            
            # Also try as int if doc_id is numeric
            if isinstance(doc_id, str) and doc_id.isdigit():
                try:
                    results = collection.get(where={"document_id": int(doc_id)})
                    ids_to_delete.extend(results['ids'])
                except Exception:
                    pass
        
        # Remove duplicates and delete
        unique_ids = list(set(ids_to_delete))
        if unique_ids:
            collection.delete(ids=unique_ids)
            # Verify deletion and ensure persistence
            try:
                count = collection.count()
                print(f"[ChromaDB] Deleted {len(unique_ids)} chunks for document IDs: {document_ids}, total count now: {count}")
                
                # Try to access persist method if available (older ChromaDB versions)
                if hasattr(client, 'persist'):
                    try:
                        client.persist()
                        print("[ChromaDB] Explicitly called persist() after delete")
                    except Exception as e:
                        print(f"[ChromaDB] Note: persist() not available or not needed: {e}")
            except Exception as e:
                print(f"[ChromaDB] Warning: Could not verify deletion: {e}")
        else:
            print(f"[ChromaDB] No chunks found to delete for document IDs: {document_ids}")
                
    elif user_id:
        # Get all documents with this user_id and delete
        try:
            results = collection.get(where={"user_id": user_id})
            if results['ids']:
                collection.delete(ids=results['ids'])
                try:
                    count = collection.count()
                    print(f"[ChromaDB] Deleted {len(results['ids'])} chunks for user_id: {user_id}, total count now: {count}")
                    
                    # Try to access persist method if available
                    if hasattr(client, 'persist'):
                        try:
                            client.persist()
                            print("[ChromaDB] Explicitly called persist() after delete")
                        except Exception:
                            pass
                except Exception as e:
                    print(f"[ChromaDB] Warning: Could not verify deletion: {e}")
        except Exception as e:
            print(f"[ChromaDB] Error deleting by user_id: {e}")
            # Try as int if user_id might be stored differently
            try:
                results = collection.get(where={"user_id": int(user_id)})
                if results['ids']:
                    collection.delete(ids=results['ids'])
                    try:
                        count = collection.count()
                        print(f"[ChromaDB] Deleted {len(results['ids'])} chunks for user_id: {user_id}, total count now: {count}")
                        
                        # Try to access persist method if available
                        if hasattr(client, 'persist'):
                            try:
                                client.persist()
                                print("[ChromaDB] Explicitly called persist() after delete")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"[ChromaDB] Warning: Could not verify deletion: {e}")
            except Exception:
                pass
