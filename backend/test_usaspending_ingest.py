import sys
import os
import unittest

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.ingest import fetch_usaspending_grants, resolve_grant_pi_and_abstract
from backend.database import get_db

class TestUSASpendingIngest(unittest.TestCase):
    def test_fetch_dod(self):
        print("Testing fetch_usaspending_grants for DOD...")
        grants = fetch_usaspending_grants("Department of Defense", "CRISPR", limit=2)
        self.assertGreater(len(grants), 0, "Should fetch at least one DOD grant")
        print(f"Fetched {len(grants)} DOD grants successfully.")
        for g in grants:
            self.assertEqual(g["funding_source"], "DOD")
            self.assertIsNotNone(g["award_id"])
            print(f"  - [{g['award_id']}] {g['grant_title'][:60]}...")
            
    def test_fetch_dnr(self):
        print("\nTesting fetch_usaspending_grants for DNR (Department of the Interior)...")
        grants = fetch_usaspending_grants("Department of the Interior", "Wildlife", limit=2)
        self.assertGreater(len(grants), 0, "Should fetch at least one DNR/DOI grant")
        print(f"Fetched {len(grants)} DNR grants successfully.")
        for g in grants:
            self.assertEqual(g["funding_source"], "DNR")
            self.assertIsNotNone(g["award_id"])
            print(f"  - [{g['award_id']}] {g['grant_title'][:60]}...")

    def test_resolve_pi(self):
        print("\nTesting resolve_grant_pi_and_abstract using Gemini Search Grounding...")
        # W81XWH2110565 (University of Massachusetts Medical School, CRISPR Adipose therapies)
        award_id = "W81XWH2110565"
        uni = "UNIVERSITY OF MASSACHUSETTS MEDICAL SCHOOL"
        title = "ADVANCEMENT OF CRISPR-BASED ADIPOSE TISSUE THERAPIES FOR TYPE 2 DIABETES TO NONHUMAN PRIMATES"
        
        resolved = resolve_grant_pi_and_abstract(award_id, uni, title)
        print("Resolved result:")
        print(resolved)
        self.assertNotEqual(resolved["pi_name"], "Dr. Unknown Investigator", "Should resolve a real PI name")
        self.assertNotEqual(resolved["grant_abstract"], title, "Should resolve a richer abstract description")
        
if __name__ == "__main__":
    unittest.main()
