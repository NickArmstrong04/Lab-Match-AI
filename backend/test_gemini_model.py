import urllib.request
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

def test_model(model_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": "Say hello!"}]}]
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                res_body = json.loads(response.read().decode("utf-8"))
                text = res_body["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[SUCCESS] Model {model_name} responded: {text.strip()}")
                return True
    except Exception as e:
        print(f"[ERROR] Model {model_name} failed: {e}")
        return False

print("Testing different model identifiers...")
test_model("gemini-2.5-flash-lite")
test_model("gemini-2.5-pro")
test_model("gemini-2.0-flash")
test_model("gemini-2.5-flash")
