import sqlite3
import json
import os
import hashlib
import time

DB_PATH = os.path.join(os.getcwd(), ".session_store.db")

# Cache configuration
CACHE_TTL_DAYS = 7  # Cache expires after 7 days
MIN_TTS_LENGTH = 50  # Skip TTS for answers shorter than this

def init_db():
    """Creates the sessions table and cache table if they don't exist."""
    print(f"DEBUG: Initializing Session Store at {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                report_id TEXT PRIMARY KEY,
                summary_data TEXT,
                language TEXT,
                pi_doc_id TEXT,
                audio_url TEXT,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create API response cache table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_response_cache (
                cache_key TEXT PRIMARY KEY,
                response_text TEXT NOT NULL,
                audio_url TEXT,
                api_source TEXT,
                model_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hit_count INTEGER DEFAULT 1,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index for faster cache lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cache_created 
            ON api_response_cache(created_at)
        ''')
        
        # Robust schema upgrades
        try:
            cursor.execute('ALTER TABLE sessions ADD COLUMN pi_doc_id TEXT')
        except: pass
        try:
            cursor.execute('ALTER TABLE sessions ADD COLUMN audio_url TEXT')
        except: pass
        try:
            cursor.execute('ALTER TABLE sessions ADD COLUMN raw_text TEXT')
        except: pass
        conn.commit()


# ============ API RESPONSE CACHING FUNCTIONS ============

def generate_cache_key(report_id: str, question: str, language: str, cache_type: str = "qa") -> str:
    """
    Generate a unique cache key for API responses.
    Uses MD5 hash of normalized question + report_id + language.
    """
    normalized_question = question.lower().strip()
    content = f"{cache_type}:{report_id}:{normalized_question}:{language}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def get_cached_response(report_id: str, question: str, language: str, cache_type: str = "qa") -> dict:
    """
    Retrieve a cached API response if available and not expired.
    Returns dict with 'text', 'audio_url', 'source', 'model' or None if not found.
    """
    cache_key = generate_cache_key(report_id, question, language, cache_type)
    
    if not os.path.exists(DB_PATH):
        return None
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get cached response
            cursor.execute('''
                SELECT response_text, audio_url, api_source, model_used, hit_count, created_at
                FROM api_response_cache 
                WHERE cache_key = ?
            ''', (cache_key,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            response_text, audio_url, api_source, model_used, hit_count, created_at = row
            
            # Check if cache is expired
            created_timestamp = time.mktime(time.strptime(created_at, '%Y-%m-%d %H:%M:%S'))
            if time.time() - created_timestamp > (CACHE_TTL_DAYS * 24 * 60 * 60):
                # Cache expired, delete it
                cursor.execute('DELETE FROM api_response_cache WHERE cache_key = ?', (cache_key,))
                conn.commit()
                return None
            
            # Update hit count and last accessed
            cursor.execute('''
                UPDATE api_response_cache 
                SET hit_count = hit_count + 1, last_accessed = CURRENT_TIMESTAMP
                WHERE cache_key = ?
            ''', (cache_key,))
            conn.commit()
            
            return {
                "text": response_text,
                "audio_url": audio_url,
                "source": api_source,
                "model": model_used,
                "hit_count": hit_count + 1,
                "cached": True
            }
            
    except Exception as e:
        print(f"DEBUG: Error getting cached response: {e}")
        return None


def cache_response(report_id: str, question: str, language: str, 
                   response_text: str, audio_url: str = None,
                   api_source: str = None, model_used: str = None,
                   cache_type: str = "qa") -> bool:
    """
    Store an API response in the cache.
    """
    cache_key = generate_cache_key(report_id, question, language, cache_type)
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO api_response_cache 
                (cache_key, response_text, audio_url, api_source, model_used, created_at, hit_count, last_accessed)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)
            ''', (cache_key, response_text, audio_url, api_source, model_used))
            conn.commit()
            return True
    except Exception as e:
        print(f"DEBUG: Error caching response: {e}")
        return False


def get_cached_audio(text_hash: str) -> str:
    """
    Get cached audio URL by text hash (for TTS caching).
    """
    if not os.path.exists(DB_PATH):
        return None
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT audio_url FROM api_response_cache 
                WHERE cache_key LIKE ? AND audio_url IS NOT NULL
                ORDER BY last_accessed DESC LIMIT 1
            ''', (f'%{text_hash[:16]}%',))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        print(f"DEBUG: Error getting cached audio: {e}")
        return None


def cache_audio(text_hash: str, audio_url: str) -> bool:
    """
    Cache TTS audio URL.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO api_response_cache 
                (cache_key, response_text, audio_url, api_source, model_used, created_at, hit_count, last_accessed)
                VALUES (?, ?, ?, 'murf_tts_cache', 'tts', CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)
            ''', (f"tts_{text_hash[:16]}", text_hash, audio_url))
            conn.commit()
            return True
    except Exception as e:
        print(f"DEBUG: Error caching audio: {e}")
        return False


def get_cache_stats() -> dict:
    """
    Get cache statistics for monitoring.
    """
    if not os.path.exists(DB_PATH):
        return {"total_entries": 0, "qa_cache": 0, "tts_cache": 0, "total_hits": 0}
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*), SUM(hit_count) FROM api_response_cache')
            total_count, total_hits = cursor.fetchone()
            
            cursor.execute('''
                SELECT COUNT(*), SUM(hit_count) 
                FROM api_response_cache 
                WHERE cache_key NOT LIKE 'tts_%'
            ''')
            qa_count, qa_hits = cursor.fetchone()
            
            cursor.execute('''
                SELECT COUNT(*), SUM(hit_count) 
                FROM api_response_cache 
                WHERE cache_key LIKE 'tts_%'
            ''')
            tts_count, tts_hits = cursor.fetchone()
            
            return {
                "total_entries": total_count or 0,
                "qa_cache": qa_count or 0,
                "tts_cache": tts_count or 0,
                "total_hits": total_hits or 0,
                "qa_hits": qa_hits or 0,
                "tts_hits": tts_hits or 0
            }
    except Exception as e:
        print(f"DEBUG: Error getting cache stats: {e}")
        return {"error": str(e)}


def cleanup_expired_cache():
    """
    Remove expired cache entries (older than CACHE_TTL_DAYS).
    Should be called periodically (e.g., on app startup).
    """
    if not os.path.exists(DB_PATH):
        return 0
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                DELETE FROM api_response_cache 
                WHERE datetime(created_at) < datetime('now', '-{CACHE_TTL_DAYS} days')
            ''')
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                print(f"DEBUG: Cleaned up {deleted} expired cache entries")
            return deleted
    except Exception as e:
        print(f"DEBUG: Error cleaning up cache: {e}")
        return 0

def save_session(report_id, summary_data, language, pi_doc_id=None, audio_url=None, raw_text=None):
    """Upserts a session record as a JSON blob."""
    try:
        summary_json = json.dumps(summary_data)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sessions (report_id, summary_data, language, pi_doc_id, audio_url, raw_text)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (report_id, summary_json, language, pi_doc_id, audio_url, raw_text))
            conn.commit()
    except Exception as e:
        print(f"DEBUG: Error saving session to SQLite: {e}")

def get_session(report_id):
    """Retrieves a single session."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT summary_data, language, pi_doc_id, audio_url, raw_text FROM sessions WHERE report_id = ?', (report_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "summary_data": json.loads(row[0]),
                    "language": row[1],
                    "pi_doc_id": row[2],
                    "audio_url": row[3],
                    "raw_text": row[4],
                    "ready": True
                }
    except Exception as e:
        print(f"DEBUG: Error getting session {report_id}: {e}")
    return None

def load_all_sessions():
    """Returns all sessions."""
    sessions = {}
    if not os.path.exists(DB_PATH):
        return sessions
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Dynamic query to handle older schemas safely
            cursor.execute('PRAGMA table_info(sessions)')
            columns = [c[1] for c in cursor.fetchall()]
            
            select_cols = ['report_id', 'summary_data', 'language']
            if 'pi_doc_id' in columns: select_cols.append('pi_doc_id')
            if 'audio_url' in columns: select_cols.append('audio_url')
            if 'raw_text' in columns: select_cols.append('raw_text')
            
            query = f"SELECT {', '.join(select_cols)} FROM sessions"
            cursor.execute(query)
            rows = cursor.fetchall()
            
            for row in rows:
                rid = row[0]
                sessions[rid] = {
                    "summary_data": json.loads(row[1]),
                    "language": row[2],
                    "ready": True
                }
                idx = 3
                if 'pi_doc_id' in columns: 
                    sessions[rid]['pi_doc_id'] = row[idx]
                    idx += 1
                if 'audio_url' in columns:
                    sessions[rid]['audio_url'] = row[idx]
                    idx += 1
                if 'raw_text' in columns:
                    sessions[rid]['raw_text'] = row[idx]
                    idx += 1
                    
    except Exception as e:
        print(f"DEBUG: Error loading sessions from SQLite: {e}")
        
    return sessions

def delete_session(report_id):
    """Removes a session from the store."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sessions WHERE report_id = ?', (report_id,))
            conn.commit()
    except Exception as e:
        print(f"DEBUG: Error deleting session: {e}")
