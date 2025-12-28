"""
RAG Engine - Core retrieval and generation logic
"""
from typing import List, Tuple
import sys
from pathlib import Path

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
            List of (chunk_text, similarity_score) tuples
        """
        if top_k is None:
            top_k = config.TOP_K_RETRIEVAL
        
        # Expand query to improve retrieval robustness
        expanded_query = self._expand_query(query)
        
        # Get query embedding (using expanded query for better semantic matching)
        query_embedding = get_embedding(expanded_query)
        
        # Search vector database
        results = search(query_embedding, top_k=top_k)
        
        return results
    
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
            context_chunks = [chunk for chunk, score in retrieved]
        
        # Combine context chunks
        if context_chunks:
            context = "\n".join([f"- {chunk}" for chunk in context_chunks])
        else:
            context = None
        
        # Generate response
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
        chunks = [chunk for chunk, score in retrieved]
        
        # Generate response
        response = self.generate(query, context_chunks=chunks)
        
        return {
            "response": response,
            "retrieved_chunks": chunks,
            "similarity_scores": [score for chunk, score in retrieved]
        }

