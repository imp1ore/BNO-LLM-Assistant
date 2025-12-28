"""
RAG System Evaluation - KPI Metrics
Measures accuracy, formatting compliance, repetition, completeness, and relevance
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent))

from backend.llm_server.rag_engine import RAGEngine
from backend.shared.vector_db import get_vector_db

# Test queries with expected content (for accuracy measurement)
TEST_QUERIES = [
    {
        "query": "what are some common customer issues",
        "expected_keywords": ["connectivity", "performance", "customer", "issues"],
        "expected_format": "numbered_list"
    },
    {
        "query": "what is the troubleshooting workflow in bno",
        "expected_keywords": ["information gathering", "diagnosis", "remote", "on-site"],
        "expected_format": "numbered_list"
    },
    {
        "query": "what are the service level agreements",
        "expected_keywords": ["sla", "service level", "availability", "response time"],
        "expected_format": "paragraph"
    },
    {
        "query": "test",
        "expected_keywords": ["help", "question", "document"],
        "expected_format": "help_message"
    },
    {
        "query": "what is the resolution process for connectivity problems",
        "expected_keywords": ["verify", "check", "test", "connectivity"],
        "expected_format": "numbered_list"
    }
]

def check_formatting_compliance(response: str) -> dict:
    """Check if response follows formatting rules"""
    issues = []
    
    # Check for markdown
    if '**' in response:
        issues.append("double_asterisks")
    if '###' in response:
        issues.append("markdown_headings")
    
    # Check for asterisk bullets
    lines = response.split('\n')
    for line in lines:
        if line.strip().startswith('* '):
            issues.append("asterisk_bullets")
            break
    
    # Check for dash bullets (excluding phrases like "Resolution steps" and separator lines)
    for line in lines:
        stripped = line.strip()
        # Skip separator lines (all dashes)
        if stripped.replace('-', '').strip() == '':
            continue
        # Only flag if it's clearly a bullet point (short line starting with dash and space)
        if (stripped.startswith('- ') and 
            len(stripped) < 100 and  # Not a long sentence
            not any(phrase in stripped.lower() for phrase in ['resolution', 'steps include', 'the steps', 'according to', 'the following'])):
            # Check if it's actually a bullet (not part of a sentence)
            if len(stripped.split()) < 8:  # Short enough to be a bullet
                issues.append("dash_bullets")
                break
    
    # Check for document headers
    if 'e& Business Network Operations Guide' in response or 'Customer Service and Support Procedures' in response:
        issues.append("document_headers")
    
    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "score": max(0, 100 - (len(issues) * 20))  # -20 points per issue
    }

def check_repetition(response: str) -> dict:
    """Check for repetition in response"""
    lines = [l.strip() for l in response.split('\n') if l.strip()]
    
    # Count duplicate lines
    seen_lines = {}
    duplicates = 0
    for line in lines:
        normalized = line.lower()
        if normalized in seen_lines:
            duplicates += 1
        else:
            seen_lines[normalized] = 1
    
    # Check for repeated phrases (3+ word sequences)
    words = response.lower().split()
    phrases = {}
    for i in range(len(words) - 2):
        phrase = ' '.join(words[i:i+3])
        phrases[phrase] = phrases.get(phrase, 0) + 1
    
    repeated_phrases = sum(1 for count in phrases.values() if count > 2)
    
    # Check for repeated sections (same numbered list appearing twice)
    numbered_sections = []
    current_section = []
    for line in lines:
        if line and line[0].isdigit() and '. ' in line:
            if current_section:
                numbered_sections.append('\n'.join(current_section))
            current_section = [line]
        elif current_section:
            current_section.append(line)
    if current_section:
        numbered_sections.append('\n'.join(current_section))
    
    duplicate_sections = len(numbered_sections) - len(set(numbered_sections))
    
    repetition_score = max(0, 100 - (duplicates * 5) - (repeated_phrases * 2) - (duplicate_sections * 15))
    
    return {
        "duplicate_lines": duplicates,
        "repeated_phrases": repeated_phrases,
        "duplicate_sections": duplicate_sections,
        "score": min(100, repetition_score)
    }

def check_completeness(response: str) -> dict:
    """Check if response is complete"""
    issues = []
    
    # Check for cut-off indicators
    if response.endswith('...') or response.endswith('..'):
        issues.append("trailing_ellipsis")
    
    # Check for incomplete sentences (no ending punctuation in last 50 chars)
    last_50 = response[-50:]
    if last_50 and not any(c in last_50 for c in ['.', '!', '?']):
        issues.append("incomplete_sentence")
    
    # Check for very short responses (unless it's a help message)
    if len(response) < 50 and 'help' not in response.lower():
        issues.append("too_short")
    
    # Check for incomplete numbered lists (starts with number but doesn't end properly)
    lines = response.split('\n')
    numbered_lines = [l for l in lines if l.strip() and l.strip()[0].isdigit() and '. ' in l.strip()]
    if numbered_lines:
        last_numbered = numbered_lines[-1]
        if not any(c in last_numbered for c in ['.', ':', ';']) and len(last_numbered) < 20:
            issues.append("incomplete_list")
    
    completeness_score = max(0, 100 - (len(issues) * 25))
    
    return {
        "issues": issues,
        "score": completeness_score,
        "length": len(response)
    }

def check_relevance(response: str, expected_keywords: list) -> dict:
    """Check if response is relevant to the query"""
    response_lower = response.lower()
    
    found_keywords = [kw for kw in expected_keywords if kw.lower() in response_lower]
    
    relevance_score = (len(found_keywords) / len(expected_keywords)) * 100 if expected_keywords else 100
    
    return {
        "expected_keywords": expected_keywords,
        "found_keywords": found_keywords,
        "score": relevance_score
    }

def check_accuracy(response: str, query: str, expected_keywords: list) -> dict:
    """Check accuracy - does response contain expected information?"""
    response_lower = response.lower()
    query_lower = query.lower()
    
    # Check if response contains expected keywords
    keyword_matches = sum(1 for kw in expected_keywords if kw.lower() in response_lower)
    keyword_accuracy = (keyword_matches / len(expected_keywords)) * 100 if expected_keywords else 100
    
    # Check if response is relevant to query (not generic)
    query_words = set(query_lower.split())
    response_words = set(response_lower.split())
    overlap = len(query_words.intersection(response_words))
    relevance_ratio = overlap / len(query_words) if query_words else 0
    
    # Check for "I don't have information" when we expect information
    has_no_info_phrase = "don't have that information" in response_lower or "don't have information" in response_lower
    if has_no_info_phrase and expected_keywords:
        keyword_accuracy = 0  # If it says no info but we expect info, accuracy is 0
    
    accuracy_score = (keyword_accuracy * 0.7) + (relevance_ratio * 100 * 0.3)
    
    return {
        "keyword_accuracy": keyword_accuracy,
        "relevance_ratio": relevance_ratio,
        "score": accuracy_score
    }

def evaluate_rag_system():
    """Run comprehensive evaluation"""
    print("=" * 80)
    print("RAG SYSTEM KPI EVALUATION")
    print("=" * 80)
    
    # Initialize RAG engine
    print("\n[1/6] Initializing RAG Engine...")
    try:
        rag = RAGEngine()
        print("   [OK] RAG Engine initialized")
    except Exception as e:
        print(f"   [ERROR] Failed to initialize: {e}")
        return None
    
    # Check vector database
    print("\n[2/6] Checking Vector Database...")
    try:
        vector_db = get_vector_db()
        if hasattr(vector_db, 'get') and isinstance(vector_db, dict):
            chunks = vector_db.get('chunks', [])
            print(f"   [OK] Vector DB: {len(chunks)} chunks indexed")
        else:
            print(f"   [OK] Vector DB loaded")
    except Exception as e:
        print(f"   [ERROR] Vector DB check failed: {e}")
        return None
    
    # Run tests
    print("\n[3/6] Running Test Queries...")
    print("-" * 80)
    
    results = []
    total_latency = 0
    
    for i, test in enumerate(TEST_QUERIES, 1):
        query = test["query"]
        print(f"\nTest {i}/{len(TEST_QUERIES)}: '{query}'")
        
        start_time = time.time()
        try:
            result = rag.query(query)
            latency = time.time() - start_time
            total_latency += latency
            response = result.get('response', '')
            
            # Evaluate metrics
            formatting = check_formatting_compliance(response)
            repetition = check_repetition(response)
            completeness = check_completeness(response)
            relevance = check_relevance(response, test["expected_keywords"])
            accuracy = check_accuracy(response, query, test["expected_keywords"])
            
            test_result = {
                "query": query,
                "response_length": len(response),
                "latency": latency,
                "formatting": formatting,
                "repetition": repetition,
                "completeness": completeness,
                "relevance": relevance,
                "accuracy": accuracy
            }
            
            results.append(test_result)
            
            print(f"   Latency: {latency:.2f}s")
            print(f"   Formatting: {formatting['score']:.1f}% ({'PASS' if formatting['compliant'] else 'FAIL'})")
            print(f"   Repetition: {repetition['score']:.1f}%")
            print(f"   Completeness: {completeness['score']:.1f}%")
            print(f"   Relevance: {relevance['score']:.1f}%")
            print(f"   Accuracy: {accuracy['score']:.1f}%")
            
        except Exception as e:
            print(f"   [ERROR] Test failed: {e}")
            results.append({
                "query": query,
                "error": str(e)
            })
    
    # Calculate aggregate metrics
    print("\n[4/6] Calculating Aggregate Metrics...")
    print("-" * 80)
    
    valid_results = [r for r in results if "error" not in r]
    
    if not valid_results:
        print("   [ERROR] No valid results to analyze")
        return None
    
    # Aggregate scores
    avg_formatting = sum(r["formatting"]["score"] for r in valid_results) / len(valid_results)
    avg_repetition = sum(r["repetition"]["score"] for r in valid_results) / len(valid_results)
    avg_completeness = sum(r["completeness"]["score"] for r in valid_results) / len(valid_results)
    avg_relevance = sum(r["relevance"]["score"] for r in valid_results) / len(valid_results)
    avg_accuracy = sum(r["accuracy"]["score"] for r in valid_results) / len(valid_results)
    avg_latency = sum(r["latency"] for r in valid_results) / len(valid_results)
    
    # Overall score (weighted)
    overall_score = (
        avg_formatting * 0.15 +
        avg_repetition * 0.15 +
        avg_completeness * 0.20 +
        avg_relevance * 0.20 +
        avg_accuracy * 0.30
    )
    
    # Formatting compliance rate
    formatting_compliance_rate = sum(1 for r in valid_results if r["formatting"]["compliant"]) / len(valid_results) * 100
    
    print("\n[5/6] KPI SUMMARY")
    print("=" * 80)
    print(f"Overall System Score: {overall_score:.1f}%")
    print(f"\nFormatting Compliance: {avg_formatting:.1f}%")
    print(f"  - Compliance Rate: {formatting_compliance_rate:.1f}% of responses")
    print(f"\nRepetition Control: {avg_repetition:.1f}%")
    print(f"\nResponse Completeness: {avg_completeness:.1f}%")
    print(f"\nRelevance Score: {avg_relevance:.1f}%")
    print(f"\nAccuracy Score: {avg_accuracy:.1f}%")
    print(f"\nAverage Latency: {avg_latency:.2f}s per query")
    print(f"Total Test Queries: {len(valid_results)}/{len(TEST_QUERIES)}")
    
    # Performance grades
    print("\n[6/6] PERFORMANCE GRADES")
    print("=" * 80)
    
    def get_grade(score):
        if score >= 90: return "A (Excellent)"
        elif score >= 80: return "B (Good)"
        elif score >= 70: return "C (Acceptable)"
        elif score >= 60: return "D (Needs Improvement)"
        else: return "F (Poor)"
    
    print(f"Overall: {get_grade(overall_score)}")
    print(f"Formatting: {get_grade(avg_formatting)}")
    print(f"Repetition Control: {get_grade(avg_repetition)}")
    print(f"Completeness: {get_grade(avg_completeness)}")
    print(f"Relevance: {get_grade(avg_relevance)}")
    print(f"Accuracy: {get_grade(avg_accuracy)}")
    
    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    
    return {
        "overall_score": overall_score,
        "formatting": avg_formatting,
        "repetition": avg_repetition,
        "completeness": avg_completeness,
        "relevance": avg_relevance,
        "accuracy": avg_accuracy,
        "latency": avg_latency,
        "formatting_compliance_rate": formatting_compliance_rate,
        "results": results
    }

if __name__ == "__main__":
    metrics = evaluate_rag_system()
    sys.exit(0 if metrics and metrics["overall_score"] >= 70 else 1)

