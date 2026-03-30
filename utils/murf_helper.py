import logging
import hashlib
from murf import Murf
from config import Config

logger = logging.getLogger("Medilo.Murf")

def _clean_text_for_tts(text):
    """Clean text for TTS processing."""
    clean_text = text.replace("[ATTENTION NEEDED]", "Attention needed.")
    clean_text = clean_text.replace("[ध्यान दें]", "ध्यान दें.")
    # Remove markdown/formatting artifacts
    clean_text = clean_text.replace("**", "").replace("*", "")
    clean_text = clean_text.replace("#", "").strip()
    return clean_text

def _get_text_hash(text: str) -> str:
    """Generate hash for text to use as cache key."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:16]

def generate_voice_audio(text, language='en'):
    """
    Generates voice audio using Murf AI Python SDK.
    Optimized: Skips TTS for short text and uses audio caching.
    
    Returns:
        dict with 'audioUrl' (or None for short text), 'cached' (bool), 'skipped' (bool)
    """
    # Skip TTS for very short answers - use browser Web Speech API instead
    if len(text.strip()) < Config.MIN_TTS_LENGTH:
        logger.info(f"Skipping TTS for short text ({len(text)} chars). Use browser TTS.")
        return {
            "audioUrl": None, 
            "cached": False, 
            "skipped": True,
            "skipReason": f"text_too_short ({len(text)} < {Config.MIN_TTS_LENGTH})"
        }
    
    # Check audio cache first
    text_hash = _get_text_hash(text)
    try:
        from utils.session_store import get_cached_audio, cache_audio
        cached_url = get_cached_audio(text_hash)
        if cached_url:
            logger.info(f"Using cached TTS audio for hash {text_hash}")
            return {
                "audioUrl": cached_url, 
                "cached": True, 
                "skipped": False
            }
    except ImportError:
        pass  # Cache not available, proceed with API call
    except Exception as e:
        logger.error(f"Audio cache lookup error: {e}")
    
    if not Config.MURF_API_KEY:
        return {"error": "MURF_API_KEY not found in environment", "cached": False, "skipped": False}

    try:
        client = Murf(api_key=Config.MURF_API_KEY)
        clean_text = _clean_text_for_tts(text)

        voice_id = "hi-IN-rahul" if language == 'hi' else "en-IN-rohan"
        locale = "hi-IN" if language == 'hi' else "en-IN"

        logger.info(f"Calling Murf AI for TTS (Voice: {voice_id})")
        response = client.text_to_speech.generate(
            text=clean_text,
            voice_id=voice_id,
            locale=locale,
            model_version="GEN2",
            format="MP3",
            rate=10,
            pitch=0,
            sample_rate=24000
        )

        if hasattr(response, 'audio_file') and response.audio_file:
            # Cache the successful audio URL
            try:
                from utils.session_store import cache_audio
                cache_audio(text_hash, response.audio_file)
            except Exception as cache_error:
                logger.error(f"Failed to cache audio: {cache_error}")
            
            return {"audioUrl": response.audio_file, "cached": False, "skipped": False}

        logger.error(f"Murf API response missing audio_file: {response}")
        return {"error": "No audio URL in Murf response", "cached": False, "skipped": False}

    except Exception as e:
        logger.error(f"Murf SDK Exception: {str(e)}")
        return {"error": f"Error calling Murf AI: {str(e)}", "cached": False, "skipped": False}

def generate_voice_summary(text, language='en'):
    """
    Generate voice summary. Delegates to generate_voice_audio.
    """
    return generate_voice_audio(text, language=language)
