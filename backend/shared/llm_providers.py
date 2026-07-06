"""
LLM Provider abstraction layer
Switch between different LLM providers easily (Ollama, OpenAI, etc.)
"""
from typing import List, Dict, Any, Iterator, Optional
import re
import base64
import config
import json
from pathlib import Path

# Initialize providers lazily
_ollama_client = None
_openai_client = None
_anthropic_client = None
_openai_vision_client = None

def get_embedding(text: str) -> List[float]:
    """Get embedding vector for text based on the configured embedding provider"""
    provider = config.EMBEDDING_PROVIDER
    if provider == "ollama":
        return _get_ollama_embedding(text)
    elif provider == "openai":
        return _get_openai_embedding(text)
    else:
        raise ValueError(f"Embedding not supported for provider: {provider}")


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Get embeddings for a list of texts in one call when the provider supports it.

    Falls back to per-text embedding if batch embedding is unavailable or fails,
    so indexing is always robust even on older Ollama versions.
    """
    if not texts:
        return []
    if config.EMBEDDING_PROVIDER == "ollama":
        try:
            return _get_ollama_embeddings_batch(texts)
        except Exception:
            # Fallback: embed one at a time (slower but reliable)
            return [_get_ollama_embedding(t) for t in texts]
    # Other providers: no batch path implemented, embed individually
    return [get_embedding(t) for t in texts]


def generate_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using the configured answer-generation provider"""
    provider = config.ANSWER_PROVIDER
    if provider == "ollama":
        return _generate_ollama_response(prompt, context, **kwargs)
    elif provider == "openai":
        return _generate_openai_response(prompt, context, **kwargs)
    elif provider == "anthropic":
        return _generate_anthropic_response(prompt, context, **kwargs)
    else:
        raise ValueError(f"Provider not supported: {provider}")


def generate_response_stream(prompt: str, context: str = None, **kwargs) -> Iterator[str]:
    """Yield the response incrementally as it's generated, for providers that
    support it (Ollama, OpenAI). Falls back to yielding the whole response in
    one piece for providers without a streaming path implemented here, so
    callers can always iterate the result the same way.
    """
    provider = config.ANSWER_PROVIDER
    if provider == "ollama":
        yield from _generate_ollama_response_stream(prompt, context, **kwargs)
    elif provider == "openai":
        yield from _generate_openai_response_stream(prompt, context, **kwargs)
    else:
        yield generate_response(prompt, context=context, **kwargs)


# ============================================================================
# Ollama Implementation
# ============================================================================
def _get_ollama_embedding(text: str) -> List[float]:
    """Get embedding using Ollama"""
    global _ollama_client
    if _ollama_client is None:
        import ollama
        # Initialize client with base URL from config
        base_url = config.OLLAMA_CONFIG.get("base_url", "http://localhost:11434")
        _ollama_client = ollama.Client(host=base_url)
    
    # Use embeddings method (plural) with prompt parameter
    response = _ollama_client.embeddings(
        model=config.OLLAMA_CONFIG["embedding_model"],
        prompt=text
    )
    # embeddings() returns a dict with 'embedding' key containing the list
    return response['embedding']


def _get_ollama_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts in a single Ollama call via the newer embed() API."""
    global _ollama_client
    if _ollama_client is None:
        import ollama
        base_url = config.OLLAMA_CONFIG.get("base_url", "http://localhost:11434")
        _ollama_client = ollama.Client(host=base_url)

    response = _ollama_client.embed(
        model=config.OLLAMA_CONFIG["embedding_model"],
        input=texts,
    )
    # embed() returns an object/dict with 'embeddings' (list of vectors)
    embeddings = response["embeddings"] if isinstance(response, dict) else response.embeddings
    if len(embeddings) != len(texts):
        raise ValueError("Batch embedding count mismatch")
    return [list(e) for e in embeddings]


def _clean_response(response: str) -> str:
    """Clean response to remove repetition and formatting issues"""
    if not response:
        return response
    
    # Fix repetition bug - detect and remove repeated rejection messages
    # This happens when the LLM generates numbered lists with repeated rejection messages
    response_lower = response.lower()
    rejection_phrase = "i don't have that information in the available documents"
    rejection_count = response_lower.count(rejection_phrase)
    
    # If rejection phrase appears more than once, it's likely a repetition bug
    if rejection_count > 1:
        # Remove all but the first occurrence
        first_occurrence = response_lower.find(rejection_phrase)
        if first_occurrence != -1:
            # Find the end of the first occurrence
            first_end = first_occurrence + len(rejection_phrase)
            # Keep everything before first occurrence, then remove all subsequent occurrences
            before_first = response[:first_occurrence]
            after_first = response[first_end:]
            # Remove all subsequent occurrences
            after_first_cleaned = re.sub(
                re.escape("I don't have that information in the available documents"),
                '',
                after_first,
                flags=re.IGNORECASE
            )
            # Also remove numbered list items that are just rejection messages
            lines = after_first_cleaned.split('\n')
            cleaned_lines = []
            for line in lines:
                line_stripped = line.strip()
                # Skip lines that are just numbers followed by rejection message
                if re.match(r'^\d+\.?\s*(I don\'t have that information|I don\'t have information)', line_stripped, re.IGNORECASE):
                    continue
                cleaned_lines.append(line)
            response = before_first + "I don't have that information in the available documents." + '\n'.join(cleaned_lines)
            response = re.sub(r'\s+', ' ', response).strip()
    
    response_lower = response.lower()
    
    # NOTE: Aggressive phrase/sentence scrubbing and the "misinterpretation ->
    # refuse" logic were removed here. They were overfit to the original sample
    # documents and deleted legitimate content from real documents (and forced
    # false "I don't have that information" answers). Grounding is enforced by
    # retrieval (similarity threshold) and the system prompt instead, so the
    # cleaner now only fixes formatting and de-duplication.

    # Remove all markdown symbols
    # Remove double asterisks first
    response = re.sub(r'\*\*([^*]+)\*\*', r'\1', response)
    # Remove single asterisks (italic markdown *text* or bullets *)
    response = re.sub(r'\*([^*\n]+)\*', r'\1', response)  # Remove *text* but keep text
    response = response.replace('*', '')  # Remove any remaining asterisks
    # Remove hash symbols used for headings
    response = re.sub(r'^#+\s*', '', response, flags=re.MULTILINE)  # Remove # at start of lines
    response = response.replace('###', '')
    response = response.replace('##', '')
    response = response.replace('#', '')
    # Remove markdown dashes used for bullets (but keep regular dashes in text)
    lines = response.split('\n')
    cleaned_lines = []
    for line in lines:
        # Remove leading dashes used for bullets (like "- Item")
        stripped = line.lstrip()
        if stripped.startswith('- ') and len(stripped) > 2:
            # Remove the dash, keep the content
            cleaned_lines.append(line.replace('- ', '', 1))
        else:
            cleaned_lines.append(line)
    response = '\n'.join(cleaned_lines)
    
    lines = response.split('\n')
    cleaned_lines = []
    seen_content_signatures = set()
    seen_numbered_items = {}  # Track numbered items by their content (without number)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Skip empty lines (we'll add them back later)
        if not stripped:
            i += 1
            continue
        
        line_lower = stripped.lower()
        
        # Check if this is a numbered list item (e.g., "1. Something", "2. Something")
        is_numbered_item = False
        numbered_content = None
        
        # Check for patterns like "1. ", "2. ", "10. ", etc.
        if stripped and stripped[0].isdigit():
            # Extract content after the number
            parts = stripped.split('.', 1)
            if len(parts) == 2 and parts[0].strip().isdigit():
                numbered_content = parts[1].strip().lower()
                is_numbered_item = True
        
        # If it's a numbered item, check for duplicates
        if is_numbered_item and numbered_content:
            # Create a signature from the content (remove common filler words)
            content_words = [w for w in numbered_content.split() if w not in ['the', 'a', 'an', 'is', 'are', 'was', 'were', 'this', 'that', 'these', 'those']]
            content_sig = ' '.join(content_words)
            
            # Check if we've seen this exact content before (even with different numbers)
            if content_sig in seen_numbered_items:
                # Skip this duplicate
                i += 1
                continue
            
            seen_numbered_items[content_sig] = True
        
        # Drop only EXACT duplicate lines (safe). Fuzzy 60%-overlap de-duplication
        # was removed because it dropped distinct lines that merely shared words.
        content_sig_full = ' '.join(line_lower.split())
        if content_sig_full in seen_content_signatures:
            i += 1
            continue

        cleaned_lines.append(line)
        seen_content_signatures.add(content_sig_full)
        i += 1
    
    # Remove duplicate consecutive lines
    result_lines = []
    prev_line = None
    for line in cleaned_lines:
        line_stripped = line.strip()
        if line_stripped and line_stripped != prev_line:
            result_lines.append(line)
            prev_line = line_stripped
        elif not line_stripped:
            # Add empty lines but limit consecutive empty lines
            if not result_lines or result_lines[-1].strip():
                result_lines.append(line)
    
    # Remove excessive blank lines (more than 1 consecutive)
    final_lines = []
    blank_count = 0
    for line in result_lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 1:  # Only allow 1 blank line
                final_lines.append(line)
        else:
            blank_count = 0
            final_lines.append(line)
    
    cleaned = '\n'.join(final_lines).strip()
    
    # NOTE: A "remove non-command lines" pass was removed here - it deleted
    # legitimate answer lines (section headers, policy text) for any document
    # that isn't about CLI commands.

    # Remove contradictory phrases if the response already contains actual information
    # This happens when the LLM provides the answer but then adds this phrase at the end
    if cleaned and len(cleaned) > 50:  # If response has substantial content
        # Check if it ends with contradictory phrases
        contradictory_phrases = [
            "i don't have that information in the available documents",
            "i don't have that information",
            "i don't have information about",
            "i don't have access to",
            "the information is not available",
            "this information is not in the documents"
        ]
        cleaned_lower = cleaned.lower()
        for phrase in contradictory_phrases:
            # If the response contains actual content (commands, steps, etc.) but ends with contradictory phrase, remove it
            if phrase in cleaned_lower:
                # Check if there's actual content before the contradictory phrase
                phrase_index = cleaned_lower.rfind(phrase)
                if phrase_index > 50:  # If there's content before the phrase
                    # Remove the contradictory phrase and everything after it
                    cleaned = cleaned[:phrase_index].strip()
                    # Remove any trailing punctuation or incomplete sentences
                    cleaned = cleaned.rstrip('.,;:')
                    break
    
    # NOTE: Hard 1500-char truncation removed - it could cut off legitimate
    # long answers mid-content. Output length is already bounded by the model's
    # num_predict setting.

    return cleaned


def _ensure_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        import ollama
        base_url = config.OLLAMA_CONFIG.get("base_url", "http://localhost:11434")
        _ollama_client = ollama.Client(host=base_url)
    return _ollama_client


def _build_chat_messages(prompt: str, context: str = None):
    """Build the (messages, short_circuit_response) pair for a chat call.

    Shared by every provider (Ollama, OpenAI, ...) so the grounding rules -
    answer only from documents, keep facts exact, use the exact "I don't have
    that information..." phrase when it's not there - stay identical no
    matter which provider is answering. _clean_response()'s de-duplication
    logic also depends on that exact phrase, so don't drift the wording here.

    short_circuit_response is not None when the caller should skip the model
    entirely (e.g. a trivial/empty query) and just use that canned response.
    """
    if context:
        # Simplified prompt - less overloaded
        system_prompt = """You are an assistant for e&'s Business Network Operations (BNO) team. Answer questions using ONLY the information in the provided documents.

Rules:
- Use only what is written in the documents. Do not add outside knowledge.
- Keep facts (numbers, names, times, commands) exactly as written.
- Give a complete answer; include all relevant details from the documents.
- Do NOT cite or invent source labels like "document 1" or "according to document N" - just state the information.
- If the answer is not in the documents, reply exactly: "I don't have that information in the available documents." """
    else:
        system_prompt = "You are a helpful network assistant for e&'s Business Network Operations (BNO) department. Always provide complete, thorough responses. Never cut off mid-sentence or leave responses incomplete."

        # Check if query is too short or non-substantive
        query_lower = prompt.strip().lower()
        is_short_query = len(query_lower.split()) <= 2 or query_lower in ['test', 'hi', 'hello', 'hey']

        if is_short_query and (not context or len(context.strip()) < 50):
            # For very short queries with no/insufficient context, give a brief helpful response
            return None, "I'm here to help you with questions about e& Business Network Operations. Please ask a specific question about the documents you've uploaded, or upload documents first to get started."

    if context:
        user_prompt = f"""Documents:
{context}

Question: {prompt}

Answer using only the information from the documents above. Do not refer to the documents by number. If the information is not in the documents, say "I don't have that information in the available documents."

Answer:"""
    else:
        user_prompt = prompt

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt}
    ]
    return messages, None


def _ollama_perf_options(kwargs: dict) -> dict:
    """Apply the shared CPU performance tuning to an Ollama request's kwargs
    (options dict + top-level keep_alive) and return kwargs for convenience.
    """
    kwargs.setdefault('options', {})
    if isinstance(kwargs['options'], dict):
        kwargs['options']['temperature'] = 0.0
        kwargs['options']['seed'] = 42
        # Bounds worst-case CPU decode time (was 768; see config.py notes).
        kwargs['options']['num_predict'] = config.OLLAMA_NUM_PREDICT
        # Ollama defaults to a small 2048-token context window regardless of the
        # model's real limit. With TOP_K_RETRIEVAL=8 chunks of ~900 chars each,
        # the prompt can exceed that easily on large/detailed documents, silently
        # dropping context. Raise it explicitly (7B-class models handle this fine).
        kwargs['options'].setdefault('num_ctx', 8192)
        # Make sure Ollama actually uses all available CPU cores per request.
        kwargs['options'].setdefault('num_thread', config.OLLAMA_NUM_THREAD)
    kwargs.setdefault('keep_alive', config.OLLAMA_KEEP_ALIVE)
    return kwargs


def _generate_ollama_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using Ollama"""
    client = _ensure_ollama_client()

    messages, short_circuit = _build_chat_messages(prompt, context)
    if short_circuit is not None:
        return short_circuit

    stream = kwargs.pop('stream', False)
    kwargs = _ollama_perf_options(kwargs)

    if stream:
        full_response = ""
        for chunk in client.chat(
            model=config.OLLAMA_CONFIG["language_model"],
            messages=messages,
            stream=True,
            **kwargs
        ):
            if 'message' in chunk and 'content' in chunk['message']:
                full_response += chunk['message']['content']
        if not full_response or full_response.strip() == '':
            return "I apologize, but I didn't receive a response. Please try again."

        cleaned = _clean_response(full_response)
        if not cleaned or len(cleaned.strip()) == 0:
            return "I don't have that information in the available documents."
        return cleaned
    else:
        response = client.chat(
            model=config.OLLAMA_CONFIG["language_model"],
            messages=messages,
            **kwargs
        )
        result = response.get('message', {}).get('content', '')

        if not result or result.strip() == '':
            return "I apologize, but I didn't receive a response. Please try again."

        cleaned = _clean_response(result)
        if not cleaned or len(cleaned.strip()) == 0:
            return "I don't have that information in the available documents."
        return cleaned


def _generate_ollama_response_stream(prompt: str, context: str = None, **kwargs) -> Iterator[str]:
    """Yield raw response text chunks as Ollama generates them.

    Chunks are NOT run through _clean_response (that needs the full text to
    de-dupe/strip markdown) - callers that need the polished final text should
    run _clean_response() on the accumulated chunks once streaming finishes.
    """
    client = _ensure_ollama_client()

    messages, short_circuit = _build_chat_messages(prompt, context)
    if short_circuit is not None:
        yield short_circuit
        return

    kwargs.pop('stream', None)
    kwargs = _ollama_perf_options(kwargs)

    got_any = False
    for chunk in client.chat(
        model=config.OLLAMA_CONFIG["language_model"],
        messages=messages,
        stream=True,
        **kwargs
    ):
        # The ollama client returns ChatResponse objects, which support the same
        # dict-style .get() used for the non-streaming response below.
        piece = chunk.get('message', {}).get('content', '')
        if piece:
            got_any = True
            yield piece

    if not got_any:
        yield "I apologize, but I didn't receive a response. Please try again."


# ============================================================================
# OpenAI Implementation
# ============================================================================
def _get_openai_embedding(text: str) -> List[float]:
    """Get embedding using OpenAI"""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=config.OPENAI_CONFIG["api_key"])
    
    response = _openai_client.embeddings.create(
        model=config.OPENAI_CONFIG["embedding_model"],
        input=text
    )
    return response.data[0].embedding


def _ensure_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=config.OPENAI_CONFIG["api_key"])
    return _openai_client


def _generate_openai_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using OpenAI, with the same grounding rules as Ollama."""
    client = _ensure_openai_client()

    messages, short_circuit = _build_chat_messages(prompt, context)
    if short_circuit is not None:
        return short_circuit

    kwargs.pop('stream', None)
    response = client.chat.completions.create(
        model=config.OPENAI_CONFIG["language_model"],
        messages=messages,
        temperature=0,
        **kwargs
    )
    result = response.choices[0].message.content or ""

    if not result.strip():
        return "I apologize, but I didn't receive a response. Please try again."

    cleaned = _clean_response(result)
    if not cleaned or len(cleaned.strip()) == 0:
        return "I don't have that information in the available documents."
    return cleaned


def _generate_openai_response_stream(prompt: str, context: str = None, **kwargs) -> Iterator[str]:
    """Yield raw response text chunks as OpenAI generates them (real streaming,
    not a fake one-shot yield) - same grounding rules as the non-streaming path.
    """
    client = _ensure_openai_client()

    messages, short_circuit = _build_chat_messages(prompt, context)
    if short_circuit is not None:
        yield short_circuit
        return

    kwargs.pop('stream', None)
    got_any = False
    stream = client.chat.completions.create(
        model=config.OPENAI_CONFIG["language_model"],
        messages=messages,
        temperature=0,
        stream=True,
        **kwargs
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content or ""
        if piece:
            got_any = True
            yield piece

    if not got_any:
        yield "I apologize, but I didn't receive a response. Please try again."


# ============================================================================
# Vision (image/diagram description) - independent of LLM_PROVIDER
# ============================================================================
def describe_image(image_bytes: bytes, image_ext: str = "png") -> Optional[str]:
    """Describe an image using OpenAI vision (gpt-4o by default).

    Used during indexing to turn embedded diagrams/screenshots into searchable
    text. Returns None (caller should skip this image) if no OpenAI API key is
    configured or the call fails - this must never take down the whole
    document indexing job over one bad image.
    """
    global _openai_vision_client
    api_key = config.OPENAI_CONFIG.get("api_key")
    if not api_key:
        return None

    if _openai_vision_client is None:
        from openai import OpenAI
        _openai_vision_client = OpenAI(api_key=api_key)

    mime = "jpeg" if image_ext.lower() in ("jpg", "jpeg") else image_ext.lower()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = (
        "This image is embedded in an internal network/IT design document. "
        "Describe it precisely and completely: transcribe every visible label, "
        "device/node name, IP address, VLAN, port, and any other text exactly "
        "as written. If it's a diagram, describe how the nodes connect to each "
        "other. If it's a screenshot, describe what is shown. Be thorough - "
        "this description is the only way this image's content becomes "
        "searchable, so do not omit any legible detail."
    )

    try:
        response = _openai_vision_client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{mime};base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            }],
            max_tokens=1000,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[VISION] describe_image failed: {e}")
        return None


# ============================================================================
# Anthropic Implementation
# ============================================================================
def _generate_anthropic_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using Anthropic Claude"""
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=config.ANTHROPIC_CONFIG["api_key"])
    
    if context:
        full_prompt = f"""You are a helpful AI assistant for the e& Business Network Operations department.

Use only the following context to answer the question. If the information is not in the context, clearly state that you don't have that information.

Context:
{context}

Question: {prompt}

Answer:"""
    else:
        full_prompt = prompt
    
    response = _anthropic_client.messages.create(
        model=config.ANTHROPIC_CONFIG["language_model"],
        max_tokens=1024,
        messages=[{"role": "user", "content": full_prompt}],
        **kwargs
    )
    return response.content[0].text

