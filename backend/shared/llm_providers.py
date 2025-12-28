"""
LLM Provider abstraction layer
Switch between different LLM providers easily (Ollama, OpenAI, etc.)
"""
from typing import List, Dict, Any
import config

# Initialize providers lazily
_ollama_client = None
_openai_client = None
_anthropic_client = None


def get_embedding(text: str) -> List[float]:
    """Get embedding vector for text based on configured provider"""
    if config.LLM_PROVIDER == "ollama":
        return _get_ollama_embedding(text)
    elif config.LLM_PROVIDER == "openai":
        return _get_openai_embedding(text)
    else:
        raise ValueError(f"Embedding not supported for provider: {config.LLM_PROVIDER}")


def generate_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using configured LLM provider"""
    if config.LLM_PROVIDER == "ollama":
        return _generate_ollama_response(prompt, context, **kwargs)
    elif config.LLM_PROVIDER == "openai":
        return _generate_openai_response(prompt, context, **kwargs)
    elif config.LLM_PROVIDER == "anthropic":
        return _generate_anthropic_response(prompt, context, **kwargs)
    else:
        raise ValueError(f"Provider not supported: {config.LLM_PROVIDER}")


# ============================================================================
# Ollama Implementation
# ============================================================================
def _get_ollama_embedding(text: str) -> List[float]:
    """Get embedding using Ollama"""
    global _ollama_client
    if _ollama_client is None:
        import ollama
        _ollama_client = ollama
    
    response = _ollama_client.embed(
        model=config.OLLAMA_CONFIG["embedding_model"],
        input=text
    )
    return response['embeddings'][0]


def _clean_response(response: str) -> str:
    """Clean response to aggressively remove repetition and formatting issues"""
    if not response:
        return response
    
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
        
        # Check for duplicate content blocks (similar meaning) - more aggressive
        content_sig_full = ' '.join(line_lower.split())
        
        # Skip if we've seen very similar content before (lower threshold for duplicates)
        is_duplicate = False
        for seen_sig in seen_content_signatures:
            seen_words = set(seen_sig.split())
            current_words = set(content_sig_full.split())
            # If more than 60% of words overlap (lowered from 70%), consider it a duplicate
            if len(seen_words) > 0 and len(current_words) > 0:
                overlap = len(seen_words & current_words) / max(len(seen_words), len(current_words))
                if overlap > 0.6 and len(content_sig_full) > 15:  # Lower threshold, shorter minimum
                    is_duplicate = True
                    break
        
        if is_duplicate:
            i += 1
            continue
        
        # Add the line if it's not a duplicate
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
    
    # Additional pass: Remove items that are clearly not commands (like "Update documentation", "Network Security", etc.)
    # These are section headers, not commands
    final_cleaned_lines = []
    non_command_patterns = [
        'update documentation', 'network security', 'access control', 'incident response',
        'privileged access', 'security checklist', 'common network commands',
        'network device ip ranges', 'standard ip addressing', 'geographically diverse',
        'appendices', 'appendix', 'useful commands for', 'these commands are useful',
        'the exact syntax may vary'
    ]
    
    for line in cleaned.split('\n'):
        line_lower = line.strip().lower()
        # Skip lines that are clearly section headers or metadata, not actual commands
        is_non_command = any(pattern in line_lower for pattern in non_command_patterns)
        # Also skip if it's just a number with no actual command (like "1. Update documentation")
        if is_non_command and (line_lower.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')) or 
                              not any(word in line_lower for word in ['show', 'block', 'unblock', 'ping', 'traceroute', 'firewall', 'access', 'session', 'login', 'security', 'event', 'log', 'route', 'interface', 'arp', 'config'])):
            continue
        final_cleaned_lines.append(line)
    
    cleaned = '\n'.join(final_cleaned_lines).strip()
    
    # CRITICAL: Remove contradictory phrases like "I don't have that information" if the response already contains actual information
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
    
    # If response is still too long (more than 1500 characters), truncate it more aggressively
    if len(cleaned) > 1500:
        # Try to find a good stopping point (end of a sentence or list item)
        truncated = cleaned[:1500]
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        cut_point = max(last_period, last_newline)
        if cut_point > 1000:  # Only truncate if we can find a good stopping point
            cleaned = truncated[:cut_point + 1]
    
    return cleaned


def _generate_ollama_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using Ollama - using chat API like the guide"""
    global _ollama_client
    if _ollama_client is None:
        import ollama
        _ollama_client = ollama
    
    # Build system prompt for BNO network assistant
    if context:
        # Use chat API with system message (like the guide)
        system_prompt = """You are a helpful network assistant for e&'s Business Network Operations (BNO) department. 
Your role is to assist with network operations, troubleshooting, and answering questions based ONLY on company documents and knowledge base.

CRITICAL RULES:
1. FIRST, carefully read the entire context provided below. Look for information that answers the question, even if it's phrased differently or uses synonyms.
2. If the answer IS in the context (or related information that answers the question): Extract and provide ALL relevant details from the context. Be thorough and complete.
3. The context may contain the answer using different words or phrases - look for the MEANING, not exact word matches.
4. EXPLAIN information in your own words - synthesize the context and present it clearly and naturally. Do not just copy text verbatim.
5. ALWAYS provide COMPLETE responses - finish all sentences, complete all lists, and ensure nothing is cut off mid-thought. Never leave responses incomplete.
6. If the answer is truly NOT in the context (after thoroughly checking): Respond with ONLY this exact phrase: "I don't have that information in the available documents." Do NOT add any explanations, general knowledge, or examples.
7. DO NOT use information from outside the context, even if you think it's common knowledge.
8. DO NOT provide generic explanations if the specific information isn't in the context.

RESPONSE FORMATTING - ABSOLUTELY CRITICAL - FOLLOW THESE EXACTLY:
- Write in plain text only. NO markdown symbols whatsoever.
- NEVER use asterisks (*) or double asterisks (**) for any purpose - NOT for bold, NOT for bullets, NOT for anything
- NEVER use hash symbols (#) - NOT for headings (###), NOT for anything
- NEVER use dashes (---) as section separators
- NEVER use single dashes (-) for bullets - use numbered lists (1., 2., 3.) instead
- NEVER use underscores (_) for formatting
- NEVER use bold, italics, or any text formatting symbols
- Write everything in plain text with natural paragraphs and simple numbered lists

CRITICAL RULES - ABSOLUTELY NO REPETITION - BE CONCISE:
1. NO REPETITION: Each piece of information appears EXACTLY ONCE in your entire response. If you list items, list them ONCE only. Never repeat the same item or information anywhere in your response.
2. BE CONCISE: Keep responses short and focused. If asked for a list of commands, provide ONLY the commands (e.g., "Show Access Lists", "Show Firewall Rules") - do NOT repeat the same command multiple times with different wording. Maximum 10-15 items in any list.
3. NO DUPLICATE SECTIONS: Do not create multiple sections covering the same topic. One section per topic only.
4. NO REPEATED HEADINGS: Do NOT create multiple headings like "1. The commands are:", "2. The commands are:", "3. The commands are:" - this is WRONG. Use ONE heading like "The commands are:" followed by ONE numbered list.
5. NO REPEATED LISTS: If you've already listed items in one format, do NOT list them again in another format. Do NOT say "Commands include:" and then later say "The commands are:" with the same content.
6. SIMPLE STRUCTURE: One clear answer, organized logically. No redundant sections. Maximum 10-15 items in a list - if you find yourself repeating, STOP.
7. CONSOLIDATE INFORMATION: If multiple sections would cover similar content, combine them into one clear section instead. Do not create separate sections that repeat the same information.
8. NO DOCUMENT HEADERS: Do not include document titles, headers, appendix names, or metadata (like "Appendices A:", "Appendices B:", "e& Business Network Operations Guide") - only provide the actual answer content.
9. NO REDUNDANT DESCRIPTIONS: If listing commands, just list the command names. Do NOT repeat "The exact syntax may vary..." for every single item - say it once at the end if needed.

EXAMPLE OF WRONG FORMAT (NEVER DO THIS):
"The steps to show access lists are:
1. Information Gathering
2. Initial Diagnosis
3. Remote Diagnostics

Steps include:
1. Information Gathering
2. Initial Diagnosis
3. Remote Diagnostics

1. The steps are: Information Gathering
2. The steps are: Initial Diagnosis
3. The steps are: Remote Diagnostics"

EXAMPLE OF CORRECT FORMAT:
"The steps to show access lists are:

1. Information Gathering: Collect details about the issue including symptoms, affected services, time of occurrence, and any recent changes.

2. Initial Diagnosis: Review network monitoring data, check device status, and analyze recent logs to identify potential causes.

3. Remote Diagnostics: Perform connectivity tests, check routing, and verify service configuration using remote tools.

4. On-Site Visit: If remote resolution is not possible, schedule an on-site visit to investigate further."

FORMATTING GUIDELINES:
- Write in natural, flowing paragraphs
- Use section headings in plain text with a colon (e.g., "Troubleshooting Workflow:" or "Connectivity Issues:")
- Do NOT number section headings (use "Troubleshooting Workflow:" not "1. Troubleshooting Workflow:")
- Do NOT use asterisks (*) for bullets - use numbered lists (1., 2., 3.) instead
- Do NOT use dashes (-) for bullets - use numbered lists (1., 2., 3.) instead
- Do NOT use double asterisks (**) for bold - just write the text normally
- Use numbered lists (1., 2., 3.) ONLY for sequential steps or items
- When listing steps, use format: "The steps are:" or "Steps include:" followed by numbered list (1., 2., 3.)
- Keep it simple: One clear answer, one logical structure, no repetition
- Do NOT include document headers or metadata in your response - only provide the actual answer

CORRECT FORMAT EXAMPLE:
"The troubleshooting workflow in BNO involves the following steps:

1. Information Gathering: Collect details about the issue including symptoms, affected services, time of occurrence, and any recent changes.

2. Initial Diagnosis: Review network monitoring data, check device status, and analyze recent logs to identify potential causes.

3. Remote Diagnostics: Perform connectivity tests, check routing, and verify service configuration using remote tools.

4. On-Site Visit: If remote resolution is not possible, schedule an on-site visit to investigate further."

WRONG FORMAT (NEVER DO THIS):
- "1. **Information Gathering**: ..." (no bold, no numbered headings)
- "* Information Gathering: ..." (no asterisks for bullets)
- "- Information Gathering: ..." (no dashes for bullets - use numbered lists)
- "**Information Gathering**" (no markdown bold)
- Repeating the same information in multiple sections
- Creating multiple sections that say the same thing
- Using asterisks (*) or dashes (-) for bullets anywhere in the response
- Including document headers like "e& Business Network Operations Guide" in the response

REMEMBER: 
- Plain text only. No symbols. No markdown. No asterisks. No bold.
- Each piece of information appears ONCE only.
- Simple structure: Natural paragraphs and numbered lists for steps.
- Write clearly and completely, but keep it simple and avoid repetition."""
        
        # Check if query is too short or non-substantive
        query_lower = prompt.strip().lower()
        is_short_query = len(query_lower.split()) <= 2 or query_lower in ['test', 'hi', 'hello', 'hey']
        
        if is_short_query and (not context or len(context.strip()) < 50):
            # For very short queries with no/insufficient context, give a brief helpful response
            return "I'm here to help you with questions about e& Business Network Operations. Please ask a specific question about the documents you've uploaded, or upload documents first to get started."
        
        user_prompt = f"""Context from company documents:
{context}

Question: {prompt}

Instructions: 
- Carefully read the context above. If it contains information that answers the question (even if phrased differently), extract and provide that information.
- Look for related terms, synonyms, or different phrasings of the question in the context.
- If the answer is in the context above, provide a CONCISE and FOCUSED answer using ONLY information from the context.
- IMPORTANT: Be concise - if asked for a list of commands, provide ONLY the commands. Do NOT include section headers, appendix names, or metadata.
- Do NOT include items like "Update documentation", "Network Security", "Access Control" - these are section headers, NOT commands.
- If asked for "common security commands", provide ONLY security-related commands (Show Access Lists, Show Firewall Rules, etc.) - do NOT mix in general network commands unless specifically asked.
- Ensure your response is COMPLETE but CONCISE - do not cut off mid-sentence, but also do not add unnecessary information.

CRITICAL: ABSOLUTELY NO REPETITION - BE CONCISE - THIS IS EXTREMELY IMPORTANT
- Each piece of information appears EXACTLY ONCE in your response
- BE CONCISE: Keep responses short and focused. Maximum 10-15 items in any list
- If you list items, list them ONCE only, in the most appropriate place
- Do NOT create multiple sections covering the same topic
- Do NOT repeat the same items or information under different headings
- Do NOT use multiple headings like "The commands are:", "Commands include:", "1. The commands are:", "2. The commands are:" - use ONE heading followed by ONE list
- If you've already listed items in one format, do NOT list them again in another format
- Do NOT say "Commands include:" and then later say "The commands are:" with the same content
- Do NOT repeat the same command/item multiple times with different wording
- Consolidate similar information into one section instead of creating multiple redundant sections
- NEVER repeat the same numbered list multiple times with different headings
- If listing commands, just list the command names - do NOT add redundant descriptions to each item

FORMATTING RULES:
- Write in natural, flowing paragraphs
- Use section headings in plain text with colon (e.g., "Troubleshooting Workflow:" or "Connectivity Issues:") - do NOT number headings
- Use numbered lists (1., 2., 3.) ONLY for sequential steps or items
- When listing steps, use: "The steps are:" or "Steps include:" followed by numbered list (1., 2., 3.)
- Keep structure simple: One clear answer, one logical flow, no repetition
- Format in plain text only: NO asterisks (*), NO dashes (-) for bullets, NO double asterisks (**), NO markdown, NO symbols
- Do NOT use asterisks (*) or dashes (-) for bullets - use numbered lists (1., 2., 3.) instead
- Do NOT use double asterisks (**) for bold - just write text normally
- Do NOT include document headers, titles, or metadata - only provide the actual answer content

EXAMPLE OF GOOD STRUCTURE:
"The troubleshooting workflow in BNO involves the following steps:

1. Information Gathering: Collect details about the issue including symptoms, affected services, time of occurrence, and any recent changes.

2. Initial Diagnosis: Review network monitoring data, check device status, and analyze recent logs to identify potential causes.

3. Remote Diagnostics: Perform connectivity tests, check routing, and verify service configuration using remote tools.

4. On-Site Visit: If remote resolution is not possible, schedule an on-site visit to investigate further."

WRONG FORMAT (NEVER DO THIS):
- "1. **Information Gathering**: ..." (no bold, no numbered headings)
- "* Information Gathering: ..." (no asterisks)
- "**Information Gathering**" (no markdown)
- Repeating information in multiple sections
- Using any markdown symbols whatsoever"

- If the answer is truly NOT in the context above (after checking thoroughly), respond with ONLY: "I don't have that information in the available documents."
- CRITICAL: If you HAVE provided information from the context (like a list of commands, steps, or details), do NOT add "I don't have that information" at the end - this is contradictory and confusing. Only use that phrase if you found NO relevant information at all.
- CRITICAL: If you HAVE provided information from the context (like a list of commands, steps, or details), do NOT add "I don't have that information" at the end - this is contradictory and confusing. Only use that phrase if you found NO relevant information at all.
- For very short or unclear queries, if there's no relevant context, provide a brief, helpful response asking for clarification.

Answer:"""
        
        # Use chat API (streaming support)
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
        
        # Check if streaming is requested
        stream = kwargs.pop('stream', False)
        
        # Set temperature to 0 for deterministic responses (enterprise standard)
        # This ensures consistent answers to the same question
        # Increase num_predict to allow longer, complete responses
        kwargs.setdefault('options', {})
        if isinstance(kwargs['options'], dict):
            kwargs['options']['temperature'] = 0.0
            kwargs['options']['seed'] = 42  # Fixed seed for reproducibility
            kwargs['options']['num_predict'] = 4096  # Allow longer responses (default is often 128 or 512)
        
        if stream:
            # For streaming, we need to collect the response
            full_response = ""
            for chunk in _ollama_client.chat(
                model=config.OLLAMA_CONFIG["language_model"],
                messages=messages,
                stream=True,
                **kwargs
            ):
                if 'message' in chunk and 'content' in chunk['message']:
                    full_response += chunk['message']['content']
            # Ensure we always return a non-empty string
            if not full_response or full_response.strip() == '':
                return "I apologize, but I didn't receive a response. Please try again."
            # Clean response to remove repetition
            return _clean_response(full_response)
        else:
            response = _ollama_client.chat(
                model=config.OLLAMA_CONFIG["language_model"],
                messages=messages,
                **kwargs
            )
            result = response.get('message', {}).get('content', '')
            # Ensure we always return a non-empty string
            if not result or result.strip() == '':
                return "I apologize, but I didn't receive a response. Please try again."
            # Clean response to remove repetition
            return _clean_response(result)
    else:
        # No context - simple chat
        kwargs.setdefault('options', {})
        if isinstance(kwargs['options'], dict):
            kwargs['options']['temperature'] = 0.0
            kwargs['options']['seed'] = 42
            kwargs['options']['num_predict'] = 4096  # Allow longer responses
        messages = [
            {'role': 'system', 'content': "You are a helpful network assistant for e&'s Business Network Operations (BNO) department. Always provide complete, thorough responses. Never cut off mid-sentence or leave responses incomplete."},
            {'role': 'user', 'content': prompt}
        ]
        response = _ollama_client.chat(
            model=config.OLLAMA_CONFIG["language_model"],
            messages=messages,
            **kwargs
        )
        result = response.get('message', {}).get('content', '')
        # Ensure we always return a non-empty string
        if not result or result.strip() == '':
            return "I'm here to help you with questions about e& Business Network Operations. Please ask a specific question or upload documents to get started."
        # Clean response to remove repetition
        return _clean_response(result)


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


def _generate_openai_response(prompt: str, context: str = None, **kwargs) -> str:
    """Generate response using OpenAI"""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=config.OPENAI_CONFIG["api_key"])
    
    messages = []
    if context:
        messages.append({
            "role": "system",
            "content": f"You are a helpful AI assistant for the e& Business Network Operations department. Use only the provided context to answer questions. If information is not in the context, clearly state that."
        })
        messages.append({
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {prompt}"
        })
    else:
        messages.append({"role": "user", "content": prompt})
    
    response = _openai_client.chat.completions.create(
        model=config.OPENAI_CONFIG["language_model"],
        messages=messages,
        **kwargs
    )
    return response.choices[0].message.content


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

