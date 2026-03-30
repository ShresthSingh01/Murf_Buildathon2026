import logging
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
import uuid
import threading
import json
import re

# Import utilities
from config import Config, validate_config
from utils.pdf_reader import extract_text_from_pdf
from utils.ai_helper import simplify_medical_report, answer_followup_question, get_clinical_recommendations, normalize_summary_payload, simplify_medical_report_with_pageindex, get_api_usage_stats, reset_api_usage
from utils.murf_helper import generate_voice_summary, generate_voice_audio

# PageIndex RAG Imports
from utils.pageindex_store import init_kb, index_report, lookup_kb
from utils.session_store import init_db, save_session, load_all_sessions, get_session, cleanup_expired_cache

# --- Initial Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Medilo")

app = Flask(__name__)
app.config.from_object(Config)

# Validate environment
if not validate_config():
    logger.critical("MEDILO PRODUCTION ERROR: Required API keys are missing from the environment.")

# Initialize Medical KB once at startup
kb_data = init_kb(Config.KB_PATH)

if not os.path.exists(Config.UPLOAD_FOLDER):
    os.makedirs(Config.UPLOAD_FOLDER)

# Initialize Session DB and load existing sessions
init_db()
REPORT_CONTEXTS = load_all_sessions()

# Cleanup expired cache on startup
logger.info("Cleaning up expired cache entries...")
cleaned = cleanup_expired_cache()
logger.info(f"Removed {cleaned} expired cache entries.")

# --- Custom Error Handlers ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal Server Error: {e}")
    return render_template('500.html'), 500

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

# --- Core Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyzing/<report_id>')
def analyzing(report_id):
    # Check if report exists
    if report_id not in REPORT_CONTEXTS:
         # Check if it exists in DB (could have been loaded via persistence)
         session_data = get_session(report_id)
         if not session_data:
             return redirect(url_for('index'))
         REPORT_CONTEXTS[report_id] = session_data

    # If it's already ready, redirect to report
    if REPORT_CONTEXTS[report_id].get("ready"):
        return redirect(url_for('report', report_id=report_id))
    
    return render_template('analyzing.html', report_id=report_id)

@app.route('/report/<report_id>')
def report(report_id):
    # Load session
    if report_id not in REPORT_CONTEXTS:
        session_data = get_session(report_id)
        if not session_data:
            return redirect(url_for('index'))
        REPORT_CONTEXTS[report_id] = session_data
    
    context = REPORT_CONTEXTS[report_id]
    if not context.get("ready"):
        return redirect(url_for('analyzing', report_id=report_id))
    
    return render_template('report.html', 
                          report_id=report_id, 
                          data=context["summary_data"], 
                          audio_url=context.get("audio_url"), 
                          language=context.get("language", "en"))

# --- API Endpoints ---

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        report_id = str(uuid.uuid4())
        filename = secure_filename(f"{report_id}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        language = request.form.get('language', 'en')
        
        # Initialize placeholder in context
        REPORT_CONTEXTS[report_id] = {"ready": False, "status": "Initializing..."}
        
        # Start background processing
        logger.info(f"Starting background processing for report {report_id}")
        thread = threading.Thread(target=process_report_async, args=(report_id, filepath, language))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "reportId": report_id,
            "redirect": url_for('analyzing', report_id=report_id)
        }), 200
    
    return jsonify({"error": "Allowed file types: PDF"}), 400

@app.route('/status/<report_id>')
def get_status(report_id):
    if report_id not in REPORT_CONTEXTS:
        session_data = get_session(report_id)
        if session_data:
            REPORT_CONTEXTS[report_id] = session_data
        else:
            return jsonify({"error": "Not found"}), 404
    
    context = REPORT_CONTEXTS[report_id]
    return jsonify({
        "ready": context.get("ready", False),
        "status": context.get("status", "Processing...")
    })

def process_report_async(report_id, filepath, language):
    try:
        REPORT_CONTEXTS[report_id]["status"] = "Extracting text..."
        raw_text = extract_text_from_pdf(filepath)
        
        REPORT_CONTEXTS[report_id]["status"] = "Indexing report..."
        pi_doc_id = None
        try:
            pi_doc_id = index_report(filepath)
            logger.info(f"Successfully indexed {report_id} with pi_doc_id: {pi_doc_id}")
        except Exception as e:
            logger.error(f"PageIndex index error for {report_id}: {e}")

        REPORT_CONTEXTS[report_id]["status"] = "Analyzing biomarkers..."
        summary_raw = "Error: Not processed"
        if pi_doc_id:
            summary_raw = simplify_medical_report_with_pageindex(pi_doc_id, language=language)
            
        if summary_raw.startswith("Error"):
            logger.warning(f"PageIndex summary failed for {report_id}, using high-fidelity raw text fallback.")
            summary_raw = simplify_medical_report(raw_text, language=language)
        
        cleaned_json = summary_raw.strip()
        try:
            summary_data = json.loads(cleaned_json)
        except:
            if "```json" in cleaned_json:
                match = re.search(r'```json\s*(.*?)\s*```', cleaned_json, re.DOTALL)
                if match: cleaned_json = match.group(1)
            elif "{" in cleaned_json:
                match = re.search(r'(\{.*\})', cleaned_json, re.DOTALL)
                if match: cleaned_json = match.group(1)
            summary_data = json.loads(cleaned_json)

        summary_data = normalize_summary_payload(summary_data, raw_text, language=language)
        
        REPORT_CONTEXTS[report_id]["status"] = "Synthesizing voice..."
        voice_text = summary_data.get("narrative_summary", "Summary processing complete.")
        voice_result = generate_voice_summary(voice_text, language=language)
        audio_url = voice_result.get("audioUrl")
        
        # Insights
        recommendations = get_clinical_recommendations(language=language, pi_doc_id=pi_doc_id, kb_data=kb_data)
        summary_data["aiInsight"] = recommendations.get("ai_insight", "Analysis complete.")
        summary_data["keyFocus"] = recommendations.get("key_focus", "Review metrics below.")

        # Update Context and DB
        REPORT_CONTEXTS[report_id].update({
            "ready": True,
            "raw_text": raw_text,
            "summary_data": summary_data,
            "language": language,
            "pi_doc_id": pi_doc_id,
            "audio_url": audio_url
        })
        # SAVE FULL CONTEXT (including raw_text)
        save_session(report_id, summary_data, language, pi_doc_id=pi_doc_id, audio_url=audio_url, raw_text=raw_text)
        logger.info(f"Background process complete for {report_id}")
        
    except Exception as e:
        logger.error(f"Background process failed for {report_id}: {e}")
        REPORT_CONTEXTS[report_id]["status"] = f"Error: {e}"

@app.route('/ask-followup', methods=['POST'])
def ask_followup():
    try:
        data = request.get_json(silent=True) or {}
        report_id = data.get('reportId')
        question = (data.get('question') or '').strip()
        language = data.get('language', 'en')

        if not report_id:
            return jsonify({"error": "Report ID required"}), 400

        # Sync memory if needed
        if report_id not in REPORT_CONTEXTS:
            session_data = get_session(report_id)
            if session_data:
                REPORT_CONTEXTS[report_id] = session_data
            else:
                return jsonify({"error": "Context not found. Re-upload."}), 404

        report_context = REPORT_CONTEXTS[report_id]
        pi_doc_id = report_context.get("pi_doc_id")
        raw_text = report_context.get("raw_text", "")
        
        # PASS RAW TEXT AS HIGH-FIDELITY FALLBACK
        answer_text = answer_followup_question(
            report_id=report_id, 
            question=question, 
            language=language, 
            pi_doc_id=pi_doc_id, 
            kb_data=kb_data,
            raw_text=raw_text
        )
        voice_result = generate_voice_audio(answer_text, language=language)

        return jsonify({
            "answer": answer_text,
            "audioUrl": voice_result.get("audioUrl"),
            "voiceError": voice_result.get("error")
        }), 200
    except Exception as e:
        logger.error(f"Error in /ask-followup: {e}")
        return jsonify({"error": "Assistant is temporarily unavailable. Please try again."}), 200

@app.route('/generate-voice', methods=['POST'])
def generate_voice():
    try:
        data = request.get_json(silent=True) or {}
        text = data.get('text')
        language = data.get('language', 'en')
        if not text: return jsonify({"error": "No text"}), 400
        voice_result = generate_voice_audio(text, language=language)
        return jsonify({
            "audioUrl": voice_result.get("audioUrl"),
            "error": voice_result.get("error")
        }), 200
    except Exception as e:
        logger.error(f"Error in /generate-voice: {e}")
        return jsonify({"error": "Voice synthesis failed. Using browser speech fallback."}), 200

@app.route('/api-usage-stats')
def api_usage_stats():
    """Get current API usage statistics for monitoring."""
    stats = get_api_usage_stats()
    return jsonify({
        "success": True,
        "stats": stats
    }), 200

@app.route('/api-reset-usage', methods=['POST'])
def api_reset_usage():
    """Reset API usage counters (admin endpoint)."""
    reset_api_usage()
    return jsonify({"success": True, "message": "Usage counters reset"}), 200

# ============ RATE LIMITING ============
# In-memory rate limit tracking
RATE_LIMIT_STATE = {
    "report_asks": {},  # report_id -> [(timestamp, question_hash)]
    "global_asks": []   # [(timestamp, question_hash)]
}

RATE_LIMIT_CONFIG = {
    "per_report": {"max": 10, "window": 60},      # 10 questions per report per minute
    "global": {"max": 30, "window": 60},           # 30 questions per minute globally
}

@app.route('/check-rate-limit', methods=['POST'])
def check_rate_limit():
    """Check if a question can be asked without rate limiting."""
    data = request.get_json(silent=True) or {}
    report_id = data.get('reportId', 'global')
    question = data.get('question', '')
    
    import hashlib
    from time import time
    
    current_time = time()
    q_hash = hashlib.md5(f"{report_id}:{question}".encode()).hexdigest()[:8]
    
    # Clean old entries
    window = RATE_LIMIT_CONFIG["per_report"]["window"]
    RATE_LIMIT_STATE["report_asks"][report_id] = [
        (t, h) for t, h in RATE_LIMIT_STATE["report_asks"].get(report_id, [])
        if current_time - t < window
    ]
    RATE_LIMIT_STATE["global_asks"] = [
        (t, h) for t, h in RATE_LIMIT_STATE["global_asks"]
        if current_time - t < window
    ]
    
    # Check limits
    report_count = len(RATE_LIMIT_STATE["report_asks"].get(report_id, []))
    global_count = len(RATE_LIMIT_STATE["global_asks"])
    
    can_ask_report = report_count < RATE_LIMIT_CONFIG["per_report"]["max"]
    can_ask_global = global_count < RATE_LIMIT_CONFIG["global"]["max"]
    
    if can_ask_report and can_ask_global:
        # Record the request
        if report_id not in RATE_LIMIT_STATE["report_asks"]:
            RATE_LIMIT_STATE["report_asks"][report_id] = []
        RATE_LIMIT_STATE["report_asks"][report_id].append((current_time, q_hash))
        RATE_LIMIT_STATE["global_asks"].append((current_time, q_hash))
        
        return jsonify({
            "allowed": True,
            "remaining_report": RATE_LIMIT_CONFIG["per_report"]["max"] - report_count - 1,
            "remaining_global": RATE_LIMIT_CONFIG["global"]["max"] - global_count - 1
        }), 200
    
    report_requests = RATE_LIMIT_STATE["report_asks"].get(report_id, [])
    first_request_time = report_requests[0][0] if report_requests else current_time
    retry_after = max(1, int(window - (current_time - first_request_time)))
    
    return jsonify({
        "allowed": False,
        "reason": "rate_limited",
        "report_remaining": 0,
        "global_remaining": max(0, RATE_LIMIT_CONFIG["global"]["max"] - global_count),
        "retry_after": retry_after
    }), 429

if __name__ == '__main__':
    logger.info("Medilo Aurora Server Starting on Port 5000...")
    logger.info("API Rate Limiting enabled - 10 questions/minute per report")
    app.run(debug=True, port=int(os.getenv("PORT", 5000)))
