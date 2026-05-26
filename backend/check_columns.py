import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db

try:
    db = get_db()
    res = db.table("students").select("*").limit(1).execute()
    print("Success! Table data:")
    print(res.data)
except Exception as e:
    print("Error querying students table:", e)
