import json
import urllib.request
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

def list_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.gemini_api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            models = [m["name"] for m in res_body.get("models", [])]
            for m in sorted(models):
                print(m)
    except Exception as e:
        print("Error listing models:", e)

if __name__ == "__main__":
    list_models()
