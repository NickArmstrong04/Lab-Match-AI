import json
import urllib.request
import urllib.error
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import settings

def run_debug():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = """
    Search for research grant Award ID W81XWH2110565, University of Massachusetts Medical School, title "ADVANCEMENT OF CRISPR-BASED ADIPOSE TISSUE THERAPIES FOR TYPE 2 DIABETES TO NONHUMAN PRIMATES".
    Identify the contact Principal Investigator's name (formatted as 'Dr. First Last').
    Extract a technical research abstract/description of the project (1-2 paragraphs).
    
    Return a raw JSON object with exactly two keys:
    - "pi_name": the formatted PI name (or "Dr. Unknown Investigator" if not found)
    - "grant_abstract": the technical abstract (or the original title if not found)
    
    Do not output any markdown wrap or text other than the raw JSON object.
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
            # Safely print using sys.stdout.buffer to avoid Windows charmap encoding errors
            sys.stdout.buffer.write(json.dumps(res_body, indent=2).encode('utf-8'))
            print()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    run_debug()
