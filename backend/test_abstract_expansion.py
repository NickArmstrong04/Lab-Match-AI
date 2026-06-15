import unittest
import os
import sys

# Allow absolute imports from backend folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.ingest import is_brief_abstract, expand_grant_abstract_via_llm

class TestAbstractExpansion(unittest.TestCase):
    def test_brief_abstract_detection(self):
        # 1. Identical to title
        title = "COVID-19 SYSTEMS ANALYSES OF EMERGING CORONAVIRUS DISEASES"
        abstract = "COVID-19 SYSTEMS ANALYSES OF EMERGING CORONAVIRUS DISEASES"
        self.assertTrue(is_brief_abstract(abstract, title))
        
        # 2. Identical with trailing period
        self.assertTrue(is_brief_abstract(abstract + ".", title))
        
        # 3. Placeholder values
        self.assertTrue(is_brief_abstract("Not Available", title))
        self.assertTrue(is_brief_abstract("Information not found", title))
        
        # 4. Too short (< 25 words)
        short_abstract = "This project aims to study the structural aspects of coronavirus diseases using computational modeling tools."
        self.assertTrue(is_brief_abstract(short_abstract, title))
        
        # 5. Non-brief (sufficiently long and distinct)
        long_abstract = (
            "This research focuses on utilizing deep neural networks to identify non-coding genomic variants associated "
            "with cardiovascular diseases. We apply transformer models and convolutional neural networks to predict "
            "splicing disruption and transcription factor binding shifts in order to characterize key regulatory regions. "
            "Our ultimate goal is to discover novel biomarkers and targetable pathways for clinical therapy."
        )
        self.assertFalse(is_brief_abstract(long_abstract, title))

    def test_live_abstract_expansion(self):
        from backend.config import settings
        if not settings.gemini_api_key:
            self.skipTest("GEMINI_API_KEY is not configured. Skipping live API test.")
            
        test_grant = {
            "grant_title": "COVID-19 SYSTEMS ANALYSES OF EMERGING CORONAVIRUS DISEASES WITH BIG DATA AND MACHINE LEARNING",
            "grant_abstract": "COVID-19 SYSTEMS ANALYSES OF EMERGING CORONAVIRUS DISEASES WITH BIG DATA AND MACHINE LEARNING",
            "pi_name": "Dr. Durgesh Kumar",
            "university": "Yale Univ",
            "funding_source": "DOD",
            "methodologies": ["Machine Learning"]
        }
        
        print("Calling live Gemini model for abstract expansion test...")
        expanded = expand_grant_abstract_via_llm(test_grant)
        print(f"Expanded Abstract: {expanded}\n")
        
        self.assertIsNotNone(expanded)
        self.assertNotEqual(expanded, test_grant["grant_abstract"])
        self.assertFalse(is_brief_abstract(expanded, test_grant["grant_title"]))
        self.assertGreater(len(expanded.split()), 30)

if __name__ == "__main__":
    unittest.main()
