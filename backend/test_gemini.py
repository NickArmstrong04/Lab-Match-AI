import urllib.request
import urllib.error
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={settings.gemini_api_key}"
headers = {"Content-Type": "application/json"}

# Request body specifying outputDimensionality
req_data = {
    "model": "models/gemini-embedding-001",
    "content": {
        "parts": [{"text": "Hello World"}]
    },
    "outputDimensionality": 1536
}

try:
    req = urllib.request.Request(
        url, 
        data=json.dumps(req_data).encode("utf-8"), 
        headers=headers,
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        if response.status == 200:
            res_body = json.loads(response.read().decode("utf-8"))
            vals = res_body["embedding"]["values"]
            print(f"[SUCCESS] Got vector of length {len(vals)}")
            print("First few values:", vals[:5])
except Exception as e:
    print("[ERROR]", e)
