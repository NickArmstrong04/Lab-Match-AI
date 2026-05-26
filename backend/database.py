import hashlib
import math
import warnings
from typing import List, Optional
from supabase import create_client, Client
from .config import settings

# Initialize Supabase client
supabase_client: Optional[Client] = None

if settings.supabase_url and settings.supabase_key:
    try:
        supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    except Exception as e:
        warnings.warn(f"Failed to create Supabase client: {e}")
else:
    warnings.warn(
        "Supabase credentials not configured. Please set SUPABASE_URL and SUPABASE_KEY in your environment or .env file."
    )

def get_db() -> Client:
    """
    Get the initialized Supabase client.
    """
    if supabase_client is None:
        raise ValueError("Supabase client is not initialized. Please verify SUPABASE_URL and SUPABASE_KEY environment variables.")
    return supabase_client

def generate_embedding(text: str) -> List[float]:
    """
    Generate a 1536-dimensional vector embedding for the input text.
    If OPENAI_API_KEY is configured in the environment, it attempts to fetch a real embedding
    from OpenAI (text-embedding-3-small). Otherwise, it fallback to a deterministic,
    normalized mock vector based on the SHA-256 hash of the input text for local development.
    """
    if not text:
        return [0.0] * 1536

    # Attempt real OpenAI embedding if API key is present
    if settings.openai_api_key:
        try:
            import urllib.request
            import json
            
            url = "https://api.openai.com/v1/embeddings"
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json"
            }
            req_data = {
                "input": text,
                "model": "text-embedding-3-small"
            }
            
            req = urllib.request.Request(
                url, 
                data=json.dumps(req_data).encode("utf-8"), 
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    return res_body["data"][0]["embedding"]
        except Exception as e:
            warnings.warn(f"OpenAI embedding API call failed: {e}. Trying Gemini next.")

    # Attempt real Gemini embedding if API key is present
    if settings.gemini_api_key:
        try:
            import urllib.request
            import json
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={settings.gemini_api_key}"
            headers = {
                "Content-Type": "application/json"
            }
            req_data = {
                "model": "models/gemini-embedding-001",
                "content": {
                    "parts": [{"text": text}]
                }
            }
            
            req = urllib.request.Request(
                url, 
                data=json.dumps(req_data).encode("utf-8"), 
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    vec = res_body["embedding"]["values"]
                    # Pad or truncate to 1536 dimensions to match database schema
                    if len(vec) > 1536:
                        vec = vec[:1536]
                        import math
                        sq_sum = sum(v * v for v in vec)
                        norm = math.sqrt(sq_sum) if sq_sum > 0 else 1.0
                        vec = [v / norm for v in vec]
                    elif len(vec) < 1536:
                        vec.extend([0.0] * (1536 - len(vec)))
                    return vec
        except Exception as e:
            warnings.warn(f"Gemini embedding API call failed: {e}.")

    # Raise an error instead of falling back to mock vectors
    raise ValueError("Failed to generate embedding: No valid API key provided or API calls failed.")
