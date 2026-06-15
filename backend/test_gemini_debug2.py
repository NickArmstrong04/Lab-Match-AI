import json
import urllib.request
import urllib.error
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

def run_debug():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = """
    Search for research grant Award ID W81XWH2110565, University of Massachusetts Medical School, title "ADVANCEMENT OF CRISPR-BASED ADIPOSE TISSUE THERAPIES FOR TYPE 2 DIABETES TO NONHUMAN PRIMATES".
    What is the name of the Principal Investigator (PI) and what is the project abstract?
    """
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "tools": [
            {
                "google_search": {}
            }
        ]
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
            print(json.dumps(res_body, indent=2))
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    run_debug()
