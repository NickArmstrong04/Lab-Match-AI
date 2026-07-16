import sys
import os

# Allow absolute imports from backend folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, generate_embedding

def seed():
    print("Connecting to Supabase and seeding database with high-quality research grants...")
    try:
        db = get_db()
    except Exception as e:
        print(f"\n[CONNECTION ERROR] Could not connect to Supabase.")
        print(f"Details: {e}")
        print("\nPlease ensure you have created a '/backend/.env' file with real SUPABASE_URL and SUPABASE_KEY values.")
        return

    sample_grants = [
        {
            "pi_name": "Dr. Sarah Jenkins",
            "university": "Stanford University",
            "department": "Bioengineering",
            "grant_title": "Deep Learning for Genomic Mutation Analysis",
            "grant_abstract": "This research focuses on utilizing deep neural networks to identify non-coding genomic variants associated with cardiovascular diseases. We apply transformer models and convolutional neural networks to predict splicing disruption and transcription factor binding shifts.",
            "methodologies": ["Deep Learning", "Genomics", "Transformers", "Python"],
            "funding_source": "NIH",
            "funding_badge_url": "https://upload.wikimedia.org/wikipedia/commons/e/e1/National_Institutes_of_Health_Logo.svg",
            "award_amount": 750000.0,
            "start_date": "2026-09-01",
            "end_date": "2029-08-31"
        },
        {
            "pi_name": "Dr. Chen Wei",
            "university": "UC Berkeley",
            "department": "EECS",
            "grant_title": "Autonomous Robotics for Pediatric Surgical Assistance",
            "grant_abstract": "Developing computer vision algorithms and reinforcement learning policies to assist surgeons in pediatric micro-surgery. The project targets automated tool tracking, semantic segmentation of blood vessels, and real-time path planning in delicate environments.",
            "methodologies": ["Computer Vision", "Robotics", "Reinforcement Learning", "Semantic Segmentation"],
            "funding_source": "NSF",
            "funding_badge_url": "https://upload.wikimedia.org/wikipedia/commons/d/d4/US-NSF-Logo.svg",
            "award_amount": 540000.0,
            "start_date": "2026-07-15",
            "end_date": "2028-07-14"
        },
        {
            "pi_name": "Dr. James Fletcher",
            "university": "MIT",
            "department": "Computer Science & AI Lab (CSAIL)",
            "grant_title": "Large Language Models for Automatic Clinical Report Summarization",
            "grant_abstract": "Researching parameter-efficient fine-tuning (PEFT) and retrieval-augmented generation (RAG) to summarize clinical patient notes into structured medical cards. We explore safety alignment, hallucination reduction, and multi-turn clinical reasoning.",
            "methodologies": ["Large Language Models", "NLP", "RAG", "PEFT", "PyTorch"],
            "funding_source": "NIH",
            "funding_badge_url": "https://upload.wikimedia.org/wikipedia/commons/e/e1/National_Institutes_of_Health_Logo.svg",
            "award_amount": 900000.0,
            "start_date": "2026-10-01",
            "end_date": "2030-09-30"
        }
    ]

    for grant in sample_grants:
        # These labs are fictional and their abstracts were hand-written, not taken
        # verbatim from NIH/NSF, so they must carry the provenance flag rather than
        # pose as federal text. See migration 20260716000006.
        grant["abstract_is_generated"] = True

        # Build text string to calculate embedding
        text_representation = f"PI: {grant['pi_name']}. Title: {grant['grant_title']}. Abstract: {grant['grant_abstract']}. Methodologies: {', '.join(grant['methodologies'])}."
        grant["embedding"] = generate_embedding(text_representation)
        
        try:
            # Check for existing record
            existing = db.table("labs_cached_grants").select("id").eq("grant_title", grant["grant_title"]).execute()
            if existing.data:
                print(f"[INFO] Skipping '{grant['grant_title']}' (already present).")
                continue
                
            response = db.table("labs_cached_grants").insert(grant).execute()
            if response.data:
                print(f"[SUCCESS] Successfully seeded: {grant['grant_title']}")
        except Exception as e:
            print(f"[ERROR] Failed to seed '{grant['grant_title']}': {e}")

if __name__ == "__main__":
    seed()
