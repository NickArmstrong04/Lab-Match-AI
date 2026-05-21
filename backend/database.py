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
            # Silently log/warn and proceed to fallback so development doesn't break
            warnings.warn(f"OpenAI embedding API call failed: {e}. Falling back to mock generator.")

    # Fallback: Deterministic mock vector generation based on SHA-256 hash
    hash_digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw_vals = []
    for i in range(1536):
        byte_val = hash_digest[(i * 7) % len(hash_digest)]
        # Map byte 0..255 to a baseline value between -1.0 and 1.0
        val = (byte_val - 128.0) / 128.0
        # Overlay a sine wave to create index-specific variation
        val += math.sin(i / 15.0)
        raw_vals.append(val)
        
    # Normalize the vector to a unit length of 1.0 (vital for cosine similarity math)
    sq_sum = sum(v * v for v in raw_vals)
    norm = math.sqrt(sq_sum) if sq_sum > 0 else 1.0
    return [v / norm for v in raw_vals]
