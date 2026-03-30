import os
from dotenv import load_dotenv

load_dotenv(override=True)

class Config:
    """Central configuration for Medilo."""
    
    # Flask Settings
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        # Critical security warning if missing in production
        print("WARNING: SECRET_KEY not set in environment. Using insecure fallback.")
        SECRET_KEY = "medi-speak-dev-only-secret"
    
    # API Keys
    MURF_API_KEY = os.getenv("MURF_API_KEY")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    PAGEINDEX_API_KEY = os.getenv("PAGEINDEX_API_KEY")
    
    # Paths
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    KB_PATH = os.path.join(BASE_DIR, "knowledge_base", "biomarkers.json")
    DB_PATH = os.path.join(BASE_DIR, ".session_store.db")
    
    # App Settings
    ALLOWED_EXTENSIONS = {'pdf'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB limit
    
    # AI Config
    OPENROUTER_SUMMARY_MODELS = [m.strip() for m in os.getenv("OPENROUTER_SUMMARY_MODELS", "google/gemini-2.0-flash-lite:free,google/gemini-2.0-flash:free,openrouter/auto").split(",")]
    OPENROUTER_FOLLOWUP_MODELS = [m.strip() for m in os.getenv("OPENROUTER_FOLLOWUP_MODELS", "google/gemini-2.0-flash-lite:free,meta-llama/llama-3.1-8b-instruct:free,openrouter/auto").split(",")]
    
    # TTS Config
    MIN_TTS_LENGTH = 50
    CACHE_TTL_DAYS = 7

def validate_config():
    """Verify that essential API keys are present."""
    missing = []
    if not Config.MURF_API_KEY: missing.append("MURF_API_KEY")
    if not Config.PAGEINDEX_API_KEY: missing.append("PAGEINDEX_API_KEY")
    
    if missing:
        print(f"CRITICAL: Missing required environment variables: {', '.join(missing)}")
        return False
    return True
