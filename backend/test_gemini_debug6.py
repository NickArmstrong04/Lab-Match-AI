import json
import urllib.request
import urllib.error
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

def test_model_grounding_plain(model_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = """
    Search for research grant Award ID W81XWH2110565, University of Massachusetts Medical School, title "ADVANCEMENT OF CRISPR-BASED ADIPOSE TISSUE THERAPIES FOR TYPE 2 DIABETES TO NONHUMAN PRIMATES".
    Identify the contact Principal Investigator's name (formatted as 'Dr. First Last').
    Extract a technical research abstract/description of the project (1-2 paragraphs).
    
    Please output the information in the following format:
    PI: [Name]
    ABSTRACT: [Description]
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}]
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            candidates = res_body.get("candidates", [])
            if not candidates:
                print(f"[{model_name}] FAIL: No candidates returned")
                return
            
            cand = candidates[0]
            content = cand.get("content", {})
            parts = content.get("parts", [])
            print(f"[{model_name}] finishReason: {cand.get('finishReason')}")
            print(f"[{model_name}] Has parts? {len(parts) > 0}")
            if parts:
                print(f"[{model_name}] Content text:\n{parts[0].get('text', '')}")
                
    except Exception as e:
        print(f"[{model_name}] Error: {e}")

if __name__ == "__main__":
    test_model_grounding_plain("gemini-2.5-flash")
    test_model_grounding_plain("gemini-2.5-flash-lite")
