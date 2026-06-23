"""
RAG Engine - Core retrieval and generation logic
"""
from typing import List, Tuple
import sys
from pathlib import Path
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.shared.llm_providers import get_embedding, generate_response
from backend.shared.vector_db import search, get_vector_db
import config

class RAGEngine:
    """Retrieval-Augmented Generation Engine"""
    
    def __init__(self):
        """Initialize RAG engine"""
        # Ensure vector DB is initialized
        # Note: We don't cache the vector DB instance here - always get fresh instance
        get_vector_db()
    
    def _expand_query(self, query: str) -> str:
        """
        Expand query with synonyms and related terms to improve retrieval robustness.
        This helps handle different phrasings of the same question.
        
        NOTE: Made deterministic by sorting synonyms to ensure consistent expansion.
        """
        query_lower = query.lower()
        
        # Domain-specific synonyms for BNO
        synonyms = {
            "workflow": ["process", "procedure", "steps", "method", "approach"],
            "troubleshooting": ["diagnosis", "problem solving", "issue resolution", "debugging"],
            "bno": ["business network operations", "network operations", "BNO department"],
            "customer": ["client", "user", "subscriber"],
            "service": ["support", "assistance"],
            "request": ["ticket", "issue", "problem"],
            "ddos": ["distributed denial of service", "denial of service", "dos attack", "ddos attack"],
            "attack": ["incident", "threat", "breach", "intrusion"],
            "responding": ["response", "handling", "managing", "dealing with"],
            "process": ["procedure", "workflow", "steps", "method"],
            "sla": ["service level agreement", "SLAs", "service level agreements"],
            "slas": ["service level agreement", "SLAs", "service level agreements"],
        }

        # Add synonyms for key terms (sorted for determinism)
        expanded_terms = []
        words = query_lower.split()

        for word in words:
            # Remove punctuation for matching
            clean_word = word.strip('.,!?;:')
            if clean_word in synonyms:
                # Sort synonyms to ensure deterministic expansion
                sorted_synonyms = sorted(synonyms[clean_word])
                expanded_terms.extend(sorted_synonyms)
        
        # Combine original query with expanded terms (sorted and limited for determinism)
        if expanded_terms:
            # Sort and limit to ensure consistent expansion
            unique_terms = sorted(list(set(expanded_terms)))[:5]  # Limit to 5, sorted for consistency
            expanded = f"{query} {' '.join(unique_terms)}"
            return expanded
        
        return query
    
    def retrieve(self, query: str, top_k: int = None) -> List[Tuple[str, float]]:
        """
        Retrieve relevant document chunks for a query
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve (default from config)
        
        Returns:
            List of (chunk_text, similarity_score) tuples filtered by similarity threshold
        """
        if top_k is None:
            top_k = config.TOP_K_RETRIEVAL
        
        # Expand query to improve retrieval robustness
        expanded_query = self._expand_query(query)
        
        # Get query embedding (using expanded query for better semantic matching)
        query_embedding = get_embedding(expanded_query)
        
        # Search vector database - search() already uses force_refresh=True for live sync
        # This ensures we always get the latest data from ChromaDB
        results = search(query_embedding, top_k=top_k)
        
        # Debug logging
        print(f"[RAG] Query: '{query}'")
        print(f"[RAG] Retrieved {len(results)} results from vector DB")
        if results:
            print(f"[RAG] Similarity scores: {[f'{score:.3f}' for _, score in results[:5]]}")
        
        # Filter by similarity threshold and remove None/empty chunks
        threshold = getattr(config, 'SIMILARITY_THRESHOLD', 0.3)
        filtered_results = [
            (chunk, score) 
            for chunk, score in results 
            if chunk is not None and chunk.strip() and score >= threshold
        ]
        
        print(f"[RAG] After threshold filter (>= {threshold}): {len(filtered_results)} results")
        if results and not filtered_results:
            # Log why results were filtered out
            max_score = max(score for _, score in results if score is not None)
            print(f"[RAG] WARNING: All results filtered out! Max similarity: {max_score:.3f}, Threshold: {threshold}")
        
        # If no results meet threshold, return empty (prevents hallucinations)
        if not filtered_results:
            return []
        
        return filtered_results
    
    def generate(self, query: str, context_chunks: List[str] = None) -> str:
        """
        Generate response using retrieved context
        
        Args:
            query: User's question
            context_chunks: Retrieved document chunks (if None, will retrieve automatically)
        
        Returns:
            Generated response
        """
        # If no context provided, retrieve it
        if context_chunks is None:
            retrieved = self.retrieve(query)
            # Filter out None/empty chunks
            context_chunks = [chunk for chunk, score in retrieved if chunk is not None and isinstance(chunk, str) and chunk.strip()]
        
        # CRITICAL: Don't generate if no context - prevents hallucination
        if not context_chunks:
            return "I don't have that information in the available documents. Please upload documents first or check if your question relates to the uploaded documents."
        
        # Combine context chunks
        context = "\n".join([f"- {chunk}" for chunk in context_chunks])
        
        # Generate response (only called if we have context)
        response = generate_response(query, context=context)
        
        return response
    
    def query(self, query: str, top_k: int = None) -> dict:
        """
        Complete RAG pipeline: retrieve + generate
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve
        
        Returns:
            Dictionary with response and retrieved chunks
        """
        # Check if query is too short or non-substantive BEFORE retrieving
        query_lower = query.strip().lower()
        is_short_query = len(query_lower.split()) <= 2 or query_lower in ['test', 'hi', 'hello', 'hey', 'ok', 'yes', 'no']
        
        if is_short_query:
            # For very short queries, return helpful message without retrieving
            return {
                "response": "I'm here to help you with questions about e& Business Network Operations. Please ask a specific question about the documents you've uploaded, or upload documents first to get started.",
                "retrieved_chunks": [],
                "similarity_scores": []
            }
        
        # Retrieve relevant chunks
        retrieved = self.retrieve(query, top_k=top_k)
        
        # If no relevant chunks found, don't generate
        if not retrieved:
            return {
                "response": "I don't have that information in the available documents. Please check if the documents contain this information or try rephrasing your question.",
                "retrieved_chunks": [],
                "similarity_scores": []
            }
        
        # Filter out None/empty chunks (defensive check - should already be filtered in retrieve())
        chunks = [chunk for chunk, score in retrieved if chunk is not None and isinstance(chunk, str) and chunk.strip()]
        scores = [score for chunk, score in retrieved if chunk is not None and isinstance(chunk, str) and chunk.strip()]
        
        # Simplified validation - just check similarity threshold
        max_similarity = max(scores) if scores else 0.0
        
        if len(chunks) == 0 or max_similarity < config.SIMILARITY_THRESHOLD:
            return {
                "response": "I don't have that information in the available documents. Please check if the documents contain this information or try rephrasing your question.",
                "retrieved_chunks": chunks,
                "similarity_scores": scores
            }
        
        # Generate response only if we have relevant context
        response = self.generate(query, context_chunks=chunks)
        
        # Final safety check - ensure no None values in response
        # This is critical - Pydantic validation will fail if we return None
        final_chunks = []
        final_scores = []
        for i, chunk in enumerate(chunks):
            if chunk is not None and isinstance(chunk, str) and chunk.strip():
                final_chunks.append(str(chunk))  # Ensure it's a string
                if i < len(scores):
                    final_scores.append(float(scores[i]))
        
        # If somehow all chunks were filtered out, return empty lists
        if not final_chunks:
            return {
                "response": "I don't have that information in the available documents. Please check if the documents contain this information or try rephrasing your question.",
                "retrieved_chunks": [],
                "similarity_scores": []
            }
        
        return {
            "response": response,
            "retrieved_chunks": final_chunks,
            "similarity_scores": final_scores
        }

