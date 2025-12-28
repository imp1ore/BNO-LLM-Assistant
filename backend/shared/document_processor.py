"""
Document processing module - handles PDF, DOCX, PPTX, TXT files
Extracts text and splits into chunks for RAG
"""
import os
from pathlib import Path
from typing import List
import config

# Document processing imports
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file"""
    if PyPDF2 is None:
        raise ImportError("PyPDF2 is required for PDF processing. Install with: pip install PyPDF2")
    
    text = ""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        raise Exception(f"Error reading PDF: {str(e)}")
    
    return text.strip()


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX file"""
    if DocxDocument is None:
        raise ImportError("python-docx is required for DOCX processing. Install with: pip install python-docx")
    
    try:
        doc = DocxDocument(file_path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    except Exception as e:
        raise Exception(f"Error reading DOCX: {str(e)}")
    
    return text.strip()


def extract_text_from_pptx(file_path: str) -> str:
    """Extract text from PPTX file"""
    if Presentation is None:
        raise ImportError("python-pptx is required for PPTX processing. Install with: pip install python-pptx")
    
    try:
        prs = Presentation(file_path)
        text_parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text_parts.append(shape.text)
        text = "\n".join(text_parts)
    except Exception as e:
        raise Exception(f"Error reading PPTX: {str(e)}")
    
    return text.strip()


def extract_text_from_txt(file_path: str) -> str:
    """Extract text from TXT file"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            text = file.read()
    except Exception as e:
        raise Exception(f"Error reading TXT: {str(e)}")
    
    return text.strip()


def extract_text(file_path: str, file_type: str) -> str:
    """Extract text from any supported file type"""
    file_type = file_type.lower().lstrip('.')
    
    if file_type == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_type == 'docx':
        return extract_text_from_docx(file_path)
    elif file_type == 'pptx':
        return extract_text_from_pptx(file_path)
    elif file_type == 'txt':
        return extract_text_from_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def split_text_into_chunks(text: str, chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """
    Split text into chunks for RAG processing
    
    Args:
        text: The text to split
        chunk_size: Size of each chunk in characters (default from config)
        chunk_overlap: Overlap between chunks in characters (default from config)
    
    Returns:
        List of text chunks
    """
    if chunk_size is None:
        chunk_size = config.CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = config.CHUNK_OVERLAP
    
    if len(text) <= chunk_size:
        return [text]
    
    # Ensure overlap is less than chunk size
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 4  # Default to 25% overlap
    
    chunks = []
    start = 0
    max_iterations = len(text) // (chunk_size - chunk_overlap) + 10  # Safety limit
    iteration = 0
    
    while start < len(text) and iteration < max_iterations:
        iteration += 1
        end = min(start + chunk_size, len(text))
        
        # Try to break at sentence boundary (only if not at end of text)
        if end < len(text):
            # Look for sentence endings
            for punct in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
                last_punct = text.rfind(punct, start, end)
                if last_punct != -1:
                    end = last_punct + 2  # Include punctuation and space
                    break
        
        # Ensure we don't go past text length
        end = min(end, len(text))
        
        # Get chunk (don't strip yet - we need to preserve position)
        chunk = text[start:end]
        
        # Only add non-empty chunks
        if chunk.strip():
            chunks.append(chunk.strip())
        
        # If we've reached the end of text, we're done
        if end >= len(text):
            break
        
        # Move start position with overlap
        # Ensure we make progress (at least chunk_size - overlap characters)
        new_start = end - chunk_overlap
        if new_start <= start:
            # Force progress - move forward by at least 1/4 of chunk size
            new_start = start + max(1, (chunk_size - chunk_overlap) // 4)
        
        # Don't go past end of text
        if new_start >= len(text):
            break
            
        start = new_start
    
    return chunks

