import logging
import re
import time
import json
import traceback
import hashlib
from openai import OpenAI
from functools import wraps

# PageIndex RAG Import
from config import Config
from utils.pageindex_store import chat_with_report, lookup_kb

logger = logging.getLogger("Medilo.AI")

# Configure OpenRouter Client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=Config.OPENROUTER_API_KEY,
) if Config.OPENROUTER_API_KEY else None

# ============ API USAGE TRACKING ============
API_USAGE = {
    "openrouter_calls": 0,
    "gemini_calls": 0,
    "pageindex_calls": 0,
    "murf_calls": 0,
    "cache_hits": 0,
    "requests_today": 0
}

# ============ CIRCUIT BREAKER FOR MODELS ============
CIRCUIT_BREAKER = {
    "google/gemini-2.0-flash-lite:free": {"failures": 0, "last_failure": 0, "skip_until": 0},
    "google/gemini-2.0-flash:free": {"failures": 0, "last_failure": 0, "skip_until": 0},
    "meta-llama/llama-3.3-70b-instruct:free": {"failures": 0, "last_failure": 0, "skip_until": 0},
    "google/gemma-2-9b-it:free": {"failures": 0, "last_failure": 0, "skip_until": 0},
}
CIRCUIT_BREAKER_THRESHOLD = 3  # Skip model after 3 consecutive failures
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes cooldown

def is_model_available(model_name: str) -> bool:
    """Check if model is not in circuit breaker state."""
    if model_name not in CIRCUIT_BREAKER:
        return True
    cb = CIRCUIT_BREAKER[model_name]
    if cb["failures"] >= CIRCUIT_BREAKER_THRESHOLD:
        if time.time() - cb["last_failure"] < CIRCUIT_BREAKER_COOLDOWN:
            return False
        # Reset after cooldown
        cb["failures"] = 0
    return True

def record_model_failure(model_name: str):
    """Record a model failure for circuit breaker."""
    if model_name in CIRCUIT_BREAKER:
        CIRCUIT_BREAKER[model_name]["failures"] += 1
        CIRCUIT_BREAKER[model_name]["last_failure"] = time.time()
        logger.warning(f"Circuit breaker - {model_name} failures: {CIRCUIT_BREAKER[model_name]['failures']}")

def record_model_success(model_name: str):
    """Record a model success, resetting failure count."""
    if model_name in CIRCUIT_BREAKER:
        CIRCUIT_BREAKER[model_name]["failures"] = 0

# Load Knowledge Base for local reference (Normalizer/Labeler)
try:
    with open(Config.KB_PATH, 'r', encoding='utf-8') as f:
        BIOMARKERS_KB = json.load(f)
except Exception as e:
    logger.error(f"Error loading biomarkers for AI helper: {e}")
    BIOMARKERS_KB = []

SYSTEM_PROMPT = """You are Medilo, a compassionate medical report technician for seniors. 
Goal: Analyze the medical report and output a structured JSON object that is extremely easy for a 70-year-old to understand.
Tone: Warm, respectful, clear, and reassuring. Address the patient directly.

JSON Structure:
{
  "patient_info": {"name": "...", "age": "...", "gender": "...", "centre": "...", "date": "...", "report_no": "..."},
  "narrative_summary": "Friendly explanation of overall health. Mention abnormal findings clearly.",
  "clinical_metrics": [
    {"label": "...", "status": "red|orange|green", "value_badge": "Value + Range", "description": "Simple explanation"}
  ],
  "urgent_action": {"title": "...", "description": "..."}
}"""

# Hybrid (Report + Web) Knowledge Prompt
FOLLOW_UP_SYSTEM_PROMPT = """You are Medilo, a personal medical librarian for seniors.
RULES:
1. Patient Data: For specific questions about the patient's results, ONLY use the Provided Context. Mention exact values.
2. Medical Terms: For general medical definitions (e.g., 'What is LDL?'), use your internal medical knowledge (the web) to explain simply.
3. Tone: Compassionate, non-alarming, and senior-friendly.
4. Conciseness: BE EXTREMELY CONCISE. Respond in 1-2 SHORT sentences maximum. We want to avoid overwhelming the user with long audio responses.
5. If information is missing from BOTH the report and your knowledge, advise consulting a doctor.
6. Language: Response MUST be in the requested language."""

MAX_INPUT_CHARS = 10000
REQUEST_TIMEOUT = 15  # seconds - abort request if not responding
FOLLOW_UP_MODELS = Config.OPENROUTER_FOLLOWUP_MODELS
SUMMARY_MODELS = Config.OPENROUTER_SUMMARY_MODELS

def _get_gemini_client():
    if not Config.GEMINI_API_KEY: return None
    try:
        from google import genai
        return genai.Client(api_key=Config.GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Gemini SDK Client Error: {e}")
        return None

def _generate_with_gemini(prompt_text, model_name="gemini-2.0-flash", max_tokens=1000):
    """Generate content using Google Gemini with usage tracking."""
    global API_USAGE
    client = _get_gemini_client()
    if not client: return "", "Missing Credentials"
    
    try:
        API_USAGE["gemini_calls"] += 1
        response = client.models.generate_content(
            model=model_name,
            contents=prompt_text,
            config={"max_output_tokens": max_tokens, "temperature": 0.2}
        )
        return (response.text or "").strip(), None
    except Exception as e:
        logger.error(f"Gemini Generation Error: {e}")
        return "", str(e)

def _extract_text_from_response(response):
    try: return response.choices[0].message.content.strip()
    except: return ""

def _clean_json_string(text):
    text = text.strip()
    if text.startswith("```json"):
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"\s*```", "", text)
    elif text.startswith("```"):
        text = re.sub(r"```\s*", "", text)
        text = re.sub(r"\s*```", "", text)
    return text.strip()

def _canonical_metric_key(label):
    lowered = (label or "").lower()
    for b in BIOMARKERS_KB:
        if lowered == b["marker"].lower() or any(a.lower() in lowered for a in b.get("aliases", [])):
            return b["marker"]
    return label

def _display_metric_label(label):
    canonical = _canonical_metric_key(label)
    return canonical.title() if canonical else label

def normalize_summary_payload(summary_data, report_text="", language="en"):
    """Ensures AI output matches expected UI schema and fills missing gaps."""
    payload = summary_data if isinstance(summary_data, dict) else {}
    metrics = []
    
    for item in payload.get("clinical_metrics", []):
        raw_label = item.get("label", "Health Marker")
        metrics.append({
            "label": _display_metric_label(raw_label),
            "status": item.get("status", "green"),
            "value_badge": item.get("value_badge") or item.get("value", "N/A"),
            "description": item.get("description", "Analyzed value.")
        })

    patient_info = payload.get("patient_info", {})
    return {
        "patient_info": {
            "name": patient_info.get("name", "Valued Patient"),
            "age": patient_info.get("age", "N/A"),
            "gender": patient_info.get("gender", "N/A"),
            "centre": patient_info.get("centre", "Diagnostic Center"),
            "date": patient_info.get("date", "Today"),
            "report_no": patient_info.get("report_no", "NEW"),
        },
        "narrative_summary": payload.get("narrative_summary", "Report processed."),
        "clinical_metrics": metrics,
        "urgent_action": payload.get("urgent_action", {"title": "Advice", "description": "Review with doctor."})
    }

def simplify_medical_report(report_text, language='en'):
    """Initial report simplification using raw text with caching and optimizations."""
    global API_USAGE
    
    if not report_text: return "Error: No text provided."
    
    lang_instr = "Hindi" if language == 'hi' else "English"
    prompt = f"{SYSTEM_PROMPT}\n\nLanguage: {lang_instr}\n\nReport:\n{report_text[:MAX_INPUT_CHARS]}"
    
    # Try bare Gemini first
    text, err = _generate_with_gemini(prompt)
    if text: return _clean_json_string(text)
    
    # Fallback to OpenRouter with circuit breaker and timeout
    if client:
        last_error = ""
        for model in SUMMARY_MODELS:
            # Skip unavailable models (circuit breaker)
            if not is_model_available(model):
                print(f"DEBUG: Skipping {model} (circuit breaker active)")
                continue
            
            try:
                API_USAGE["openrouter_calls"] += 1
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=REQUEST_TIMEOUT
                )
                res_text = _extract_text_from_response(resp)
                if res_text:
                    record_model_success(model)
                    return _clean_json_string(res_text)
            except TimeoutError:
                logger.info(f"Timeout for {model}, trying next...")
                record_model_failure(model)
                continue
            except Exception as e:
                last_error = str(e)
                record_model_failure(model)
                continue
        return f"Error: {last_error}" if last_error else "Error: All models failed."
    return "Error: Analysis failed."

def simplify_medical_report_with_pageindex(pi_doc_id, language='en'):
    """Uses PageIndex Cloud for reasoning-based JSON summary."""
    lang_instr = "Hindi" if language == 'hi' else "English"
    prompt = f"Analyze the following indexed medical report context. Generate a clinical JSON summary report in {lang_instr} language as requested."
    text = chat_with_report(pi_doc_id, prompt, system_prompt=SYSTEM_PROMPT)
    if text.startswith("Error"): return text
    return _clean_json_string(text)

def get_clinical_recommendations(language='en', pi_doc_id=None, kb_data=None):
    """Hybrid clinical insights."""
    lang_instr = "Hindi" if language == 'hi' else "English"
    prompt = f"""Provide a 2-sentence medical summary:
1. AI Insight: Important finding about patient's results.
2. Key Focus: Next step or suggestion.
Output format: JSON {{"ai_insight": "...", "key_focus": "..."}}
Language: {lang_instr}"""
    
    if pi_doc_id:
        try:
            result = chat_with_report(pi_doc_id, prompt)
            if result and not result.startswith("Error"):
                return json.loads(_clean_json_string(result))
        except: pass
    
    if language == 'hi':
        return {"ai_insight": "रिपोर्ट विश्लेषण पूरा हुआ।", "key_focus": "मुख्य मापदंडों की जांच करें।"}
    return {"ai_insight": "Report analysis complete.", "key_focus": "Focus on flagged metrics."}

def answer_followup_question(report_id, question, language='en', pi_doc_id=None, kb_data=None, raw_text=""):
    """
    Resilient multi-layered Q&A system with caching optimization.
    Checks cache before making API calls to reduce rate limit usage.
    """
    global API_USAGE
    
    # --- CHECK CACHE FIRST ---
    try:
        from utils.session_store import get_cached_response
        cached = get_cached_response(report_id, question, language, cache_type="qa")
        if cached:
            API_USAGE["cache_hits"] += 1
            print(f"DEBUG: CACHE HIT for Q: '{question[:50]}...' (hits: {cached.get('hit_count', 1)})")
            return cached["text"]
    except ImportError:
        pass
    except Exception as e:
        print(f"DEBUG: Cache lookup error: {e}")
    # --- END CACHE CHECK ---
    
    instr = "Hindi" if language == 'hi' else "English"
    kb_context = lookup_kb(question, kb_data or []) if kb_data else ""
    system_prompt = f"{FOLLOW_UP_SYSTEM_PROMPT}\nLanguage Requested: {instr}\n{kb_context}"

    # --- LEVEL 1: PageIndex RAG (Primary) ---
    if pi_doc_id:
        try:
            logger.info(f"Attempting LEVEL 1 Q&A (PageIndex) for {report_id}")
            API_USAGE["pageindex_calls"] += 1
            result = chat_with_report(pi_doc_id, question, system_prompt=system_prompt)
            if result and not result.startswith("Error"):
                logger.info(f"LEVEL 1 Success.")
                # Cache the result
                try:
                    from utils.session_store import cache_response
                    cache_response(report_id, question, language, result, 
                                   api_source="pageindex", model_used=pi_doc_id, cache_type="qa")
                except: pass
                return result
        except Exception as e:
            logger.error(f"LEVEL 1 Failure: {e}")

    # --- LEVEL 2: High-Fidelity Raw Text RAG (Primary Backup) ---
    if raw_text and len(raw_text.strip()) > 50:
        try:
            print(f"DEBUG: Attempting LEVEL 2 Q&A (Raw Text Context) for {report_id}")
            context_prompt = f"REPORT CONTEXT FROM PDF:\n{raw_text[:MAX_INPUT_CHARS]}\n\nQUESTION FROM PATIENT: {question}"
            full_p = f"{system_prompt}\n\n{context_prompt}"
            
            # Try Gemini Direct first
            text, err = _generate_with_gemini(full_p)
            if text:
                logger.info(f"LEVEL 2 Success (Gemini).")
                # Cache the result
                try:
                    from utils.session_store import cache_response
                    cache_response(report_id, question, language, text,
                                   api_source="gemini_direct", model_used="gemini-2.0-flash", cache_type="qa")
                except: pass
                return text
            
            # Failover to OpenRouter with circuit breaker
            if client:
                for model in FOLLOW_UP_MODELS:
                    # Skip unavailable models
                    if not is_model_available(model):
                        print(f"DEBUG: Skipping {model} (circuit breaker)")
                        continue
                    
                    try:
                        API_USAGE["openrouter_calls"] += 1
                        resp = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": full_p}],
                            timeout=REQUEST_TIMEOUT
                        )
                        ans = _extract_text_from_response(resp)
                        if ans:
                            logger.info(f"LEVEL 2 Success (OpenRouter - {model}).")
                            record_model_success(model)
                            # Cache the result
                            try:
                                from utils.session_store import cache_response
                                cache_response(report_id, question, language, ans,
                                               api_source="openrouter", model_used=model, cache_type="qa")
                            except: pass
                            return ans
                    except TimeoutError:
                        logger.warning(f"Timeout for {model}")
                        record_model_failure(model)
                        continue
                    except Exception as e:
                        logger.error(f"OpenRouter error: {e}")
                        record_model_failure(model)
                        continue
        except Exception as e:
            print(f"DEBUG: LEVEL 2 Critical Failure: {e}")
            traceback.print_exc()

    # --- LEVEL 3: General Knowledge / Emergency Fallback ---
    logger.info(f"Attempting LEVEL 3 Q&A (General Knowledge) for {report_id}")
    prompt = f"[CRITICAL: No specific report context available. Answer as a general medical assistant.]\n{system_prompt}\n\nQuestion: {question}"
    
    text, err = _generate_with_gemini(prompt)
    if text:
        # Cache even the fallback response
        try:
            from utils.session_store import cache_response
            cache_response(report_id, question, language, text,
                           api_source="gemini_fallback", model_used="gemini-general", cache_type="qa")
        except: pass
        return text
    
    if language == 'hi':
        return "मुझे खेद है, मैं अभी आपकी रिपोर्ट के विवरण तक नहीं पहुंच पा रहा हूं। कृपया बाद में प्रयास करें या अपने डॉक्टर से परामर्श करें।"
    return "I'm sorry, I'm having trouble accessing your report context right now. Please try again later or consult your doctor."


# ============ API USAGE AND MONITORING ============

def get_api_usage_stats() -> dict:
    """
    Get current API usage statistics for monitoring.
    """
    global API_USAGE
    stats = API_USAGE.copy()
    
    # Add cache stats from session store
    try:
        from utils.session_store import get_cache_stats
        cache_stats = get_cache_stats()
        stats["cache"] = cache_stats
        
        # Calculate cache hit rate
        total_cache_requests = stats["cache_hits"] + stats.get("cache", {}).get("qa_cache", 0)
        if total_cache_requests > 0:
            stats["cache_hit_rate"] = round((stats["cache_hits"] / total_cache_requests) * 100, 2)
        else:
            stats["cache_hit_rate"] = 0
    except Exception as e:
        stats["cache_error"] = str(e)
    
    # Add circuit breaker status
    stats["circuit_breakers"] = {}
    for model, cb in CIRCUIT_BREAKER.items():
        stats["circuit_breakers"][model] = {
            "failures": cb["failures"],
            "available": is_model_available(model),
            "cooldown_remaining": max(0, CIRCUIT_BREAKER_COOLDOWN - (time.time() - cb["last_failure"])) 
                                  if cb["failures"] >= CIRCUIT_BREAKER_THRESHOLD else 0
        }
    
    return stats


def reset_api_usage():
    """Reset API usage counters (for testing/new day)."""
    global API_USAGE
    API_USAGE = {
        "openrouter_calls": 0,
        "gemini_calls": 0,
        "pageindex_calls": 0,
        "murf_calls": 0,
        "cache_hits": 0,
        "requests_today": 0
    }
    # Reset circuit breakers
    for model in CIRCUIT_BREAKER:
        CIRCUIT_BREAKER[model] = {"failures": 0, "last_failure": 0, "skip_until": 0}
    print("DEBUG: API usage counters reset")
