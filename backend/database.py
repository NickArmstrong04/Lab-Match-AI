import hashlib
import math
import warnings
from typing import List, Optional, Tuple
from supabase import create_client, Client
from .config import settings

# Embedding model identifiers, stamped onto every row we embed (labs_cached_grants.
# embedding_model) so provenance is explicit and a future model switch is detectable.
# OpenAI is preferred only when a key is set; in this deployment it is unset, so the
# corpus is single-model Gemini by construction. Changing OUTPUT dimensionality (Gemini
# defaults to >1536 and we hand-truncate + renormalize below) would require re-embedding
# the whole corpus, so that is deliberately out of scope here.
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

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
    """1536-dim embedding for `text`. Thin wrapper over generate_embedding_with_model
    for callers that don't need to record which model produced the vector."""
    vec, _ = generate_embedding_with_model(text)
    return vec


def generate_embedding_with_model(text: str) -> Tuple[List[float], Optional[str]]:
    """Generate a 1536-dimensional embedding and return (vector, model_id).

    model_id is the identifier of the model that actually produced this vector, so the
    caller can stamp labs_cached_grants.embedding_model truthfully rather than assuming.
    OpenAI is used only if a key is configured; otherwise Gemini. Raises if neither
    succeeds -- we never substitute a mock/hash vector, which would poison the match space.
    An empty input yields a zero vector with no model (nothing was embedded).
    """
    if not text:
        return [0.0] * 1536, None

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
                "model": OPENAI_EMBEDDING_MODEL
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
                    return res_body["data"][0]["embedding"], OPENAI_EMBEDDING_MODEL
        except Exception as e:
            warnings.warn(f"OpenAI embedding API call failed: {e}. Trying Gemini next.")

    # Attempt real Gemini embedding if API key is present
    if settings.gemini_api_key:
        try:
            import urllib.request
            import json

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_EMBEDDING_MODEL}:embedContent?key={settings.gemini_api_key}"
            headers = {
                "Content-Type": "application/json"
            }
            req_data = {
                "model": f"models/{GEMINI_EMBEDDING_MODEL}",
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
                        sq_sum = sum(v * v for v in vec)
                        norm = math.sqrt(sq_sum) if sq_sum > 0 else 1.0
                        vec = [v / norm for v in vec]
                    elif len(vec) < 1536:
                        vec.extend([0.0] * (1536 - len(vec)))
                    return vec, GEMINI_EMBEDDING_MODEL
        except Exception as e:
            warnings.warn(f"Gemini embedding API call failed: {e}.")

    # Raise an error instead of falling back to mock vectors
    raise ValueError("Failed to generate embedding: No valid API key provided or API calls failed.")
