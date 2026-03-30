"""
PageIndex Cloud SDK wrapper for Medilo.
Replaces ChromaDB + embeddings with PageIndex's reasoning-based RAG.

API Flow:
  1. submit_document(pdf_path) → doc_id
  2. chat_completions(messages, doc_id) → answer
  3. get_tree(doc_id) → hierarchical structure
"""
import os
import json
import time
import traceback
from dotenv import load_dotenv

load_dotenv(override=True)

_PI_CLIENT = None

def get_pi_client():
    """Returns a singleton PageIndex cloud client."""
    global _PI_CLIENT
    if _PI_CLIENT is None:
        try:
            from pageindex import PageIndexClient
            api_key = os.getenv("PAGEINDEX_API_KEY", "").strip()
            if not api_key:
                print("WARNING: PAGEINDEX_API_KEY not set in .env")
                return None
            _PI_CLIENT = PageIndexClient(api_key=api_key)
            print("DEBUG: PageIndex cloud client initialized.")
        except ImportError:
            print("ERROR: pageindex SDK not found. Please install it.")
            return None
        except Exception as e:
            print(f"ERROR: PageIndex init error: {e}")
            return None
    return _PI_CLIENT


def index_report(pdf_path: str) -> str:
    """Submits a PDF to PageIndex for processing. Returns doc_id."""
    client = get_pi_client()
    if not client:
        print("ERROR: PageIndex client not initialized. PageIndex RAG will be unavailable.")
        return ""
    
    abs_path = os.path.abspath(pdf_path)
    if not os.path.exists(abs_path):
        print(f"ERROR: PDF file not found at {abs_path}")
        return ""

    print(f"DEBUG: Submitting PDF to PageIndex: {abs_path}")
    try:
        result = client.submit_document(abs_path)
        print(f"DEBUG: Submission raw response: {result}")
        
        # Check for multiple possible ID keys (robust matching)
        doc_id = result.get("doc_id") or result.get("id") or result.get("document_id")
        if not doc_id:
            print(f"ERROR: No doc_id found in PageIndex response: {result}")
            return ""

        print(f"DEBUG: PageIndex doc_id = {doc_id}. Polling for completion...")
        
        # Poll until processing completes (timeout after 120s)
        for i in range(24):
            status_resp = client.get_tree(doc_id)
            print(f"DEBUG: Polling ({i+1}). Status response: {status_resp}")
            
            # Check for multiple possible status keys
            current_status = (status_resp.get("status") or status_resp.get("state") or "").lower()
            if current_status in ["completed", "success", "processed", "ready"]:
                print(f"DEBUG: PageIndex processing completed for {doc_id}")
                return doc_id
            elif current_status in ["failed", "error", "rejected"]:
                print(f"ERROR: PageIndex processing failed for {doc_id}: {status_resp}")
                return ""
            
            # Rate limiting / heartbeat
            time.sleep(5)
        
        print(f"WARNING: PageIndex processing timed out for {doc_id}, proceeding with fallback.")
        return doc_id
    except Exception as e:
        print(f"ERROR: PageIndex submission failed: {e}")
        traceback.print_exc()
        return ""


def chat_with_report(doc_id: str, question: str, system_prompt: str = "") -> str:
    """Uses PageIndex Chat API for reasoning-based retrieval + answer."""
    client = get_pi_client()
    if not client:
        return "Error: PageIndex client not available."
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})
    
    print(f"DEBUG: Chatting with PageIndex for doc_id {doc_id}")
    try:
        # Added strict timeout to prevent hangs
        response = client.chat_completions(
            messages=messages,
            doc_id=doc_id,
            timeout=15 
        )
        # Robust response parsing
        if hasattr(response, "choices"):
             return response.choices[0].message.content
        return response.get("choices", [{}])[0].get("message", {}).get("content", "Error: Empty response")
    except Exception as e:
        print(f"ERROR: PageIndex chat-with-report failed: {e}")
        return f"Error: {e}"


def get_tree_structure(doc_id: str) -> dict:
    """Returns the hierarchical tree index for a processed document."""
    client = get_pi_client()
    if not client:
        return {}
    try:
        result = client.get_tree(doc_id)
        return result.get("result", {})
    except Exception as e:
        print(f"DEBUG: Error getting tree: {e}")
        return {}


def init_kb(kb_path: str) -> list:
    """Loads biomarkers.json as a plain list."""
    if not os.path.exists(kb_path):
        return []
    try:
        with open(kb_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"DEBUG: Error loading KB: {e}")
        return []


def lookup_kb(query: str, kb_data: list, n_results: int = 3) -> str:
    """Simple keyword-based lookup in the biomarkers KB."""
    if not kb_data or not query:
        return ""
    
    query_lower = query.lower()
    scored = []
    for b in kb_data:
        score = 0
        marker = (b.get("marker") or "").lower()
        aliases = [a.lower() for a in b.get("aliases", [])]
        
        if marker and marker in query_lower:
            score += 10
        for alias in aliases:
            if alias in query_lower:
                score += 5
        
        # Category match
        category = (b.get("category") or "").lower()
        if category and category in query_lower:
            score += 2
            
        if score > 0:
            scored.append((score, b))
    
    scored.sort(key=lambda x: -x[0])
    top = scored[:n_results]
    
    if not top:
        return ""
    
    parts = ["[BACKGROUND MEDICAL KNOWLEDGE]"]
    for _, b in top:
        entry = f"Marker: {b.get('marker')} ({b.get('category')})\n"
        entry += f"Normal: {b.get('normal_range')}\n"
        entry += f"Explanation: {b.get('plain_english')}\n"
        entry += f"Senior Tip: {b.get('senior_tip')}"
        parts.append(entry)
    
    return "\n".join(parts)
