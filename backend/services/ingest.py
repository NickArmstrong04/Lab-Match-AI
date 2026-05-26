import json
import urllib.request
import urllib.error
import re
import html
import warnings
from typing import List, Dict, Optional
from datetime import datetime

from ..database import get_db, generate_embedding

# Constants
DEFAULT_KEYWORDS = [
    "CRISPR", "Microfluidics", "Machine Learning", "Deep Learning",
    "Bioinformatics", "RNA-Seq", "Genomics", "Robotics", "Neurobiology"
]

KEYWORDS_METHODOLOGIES = [
    "CRISPR", "Microfluidics", "Machine Learning", "Deep Learning", "NLP",
    "TensorFlow", "PyTorch", "RNA-Seq", "Sequencing", "Electrophysiology",
    "CAD", "SolidWorks", "Cell Culture", "Imaging", "Mass Spectrometry",
    "Stem Cells", "Gene Editing", "Bioinformatics", "Microtunnels",
    "Organ-on-a-chip", "High-Throughput Screening", "Robotics", "Computer Vision"
]

def clean_pi_name(raw_name: str) -> str:
    """
    Format contact PI names cleanly (e.g. 'SMITH, JOHN A.' -> 'Dr. John Smith')
    """
    if not raw_name:
        return "Dr. Unknown Investigator"
    
    parts = raw_name.split(",")
    if len(parts) == 2:
        last = parts[0].strip().title()
        first_parts = parts[1].strip().split(" ")
        first = first_parts[0].strip().title()
        return f"Dr. {first} {last}"
    
    name = raw_name.strip()
    if not name.lower().startswith("dr."):
        return f"Dr. {name.title()}"
    return name.title()

def clean_nsf_pi(raw_pi: str) -> str:
    """
    Format NSF program directors/PIs.
    """
    if not raw_pi:
        return "Dr. Unknown Investigator"
    name = raw_pi.strip()
    if not name.lower().startswith("dr."):
        return f"Dr. {name.title()}"
    return name.title()

def clean_abstract_html(raw_html: str) -> str:
    """
    Remove HTML tags and unescape symbols from grant abstracts.
    """
    if not raw_html:
        return ""
    # Unescape HTML entities
    unescaped = html.unescape(raw_html)
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', '', unescaped)
    # Replace multiple spaces/newlines
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def parse_nsf_date(date_str: str) -> str:
    """
    Convert NSF dates (MM/DD/YYYY) to ISO format (YYYY-MM-DD).
    """
    if not date_str:
        return None
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0]}-{parts[1]}"
    except Exception:
        pass
    return date_str

def scan_methodologies(title: str, abstract: str) -> List[str]:
    """
    Scan grant text and extract matching methodologies.
    """
    combined = (title + " " + abstract).lower()
    methodologies = []
    for kw in KEYWORDS_METHODOLOGIES:
        if kw.lower() in combined:
            methodologies.append(kw)
    if not methodologies:
        methodologies = ["Research Analysis"]
    return methodologies

def fetch_nih_grants(keywords: List[str], limit: int = 15, offset: int = 0) -> List[dict]:
    """
    Fetch active, funded projects from NIH RePORTER API v2 matching keywords.
    """
    url = "https://api.reporter.nih.gov/v2/projects/search"
    headers = {"Content-Type": "application/json"}
    
    # Create keyword search term
    search_term = " OR ".join(f'"{kw}"' for kw in keywords)
    
    payload = {
        "criteria": {
            "advanced_text_search": {
                "search_field": "abstract",
                "search_text": search_term
            }
        },
        "limit": limit,
        "offset": offset,
        "sort_field": "project_start_date",
        "sort_order": "desc"
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                res_body = json.loads(response.read().decode("utf-8"))
                results = res_body.get("results", [])
                
                parsed_grants = []
                for p in results:
                    title = p.get("project_title", "Untitled NIH Research Grant")
                    abstract = clean_abstract_html(p.get("abstract_text", ""))
                    
                    # Extract PI name
                    pi_name = "Dr. Unknown Investigator"
                    pis = p.get("principal_investigators", [])
                    if pis:
                        c_pi = next((pi for pi in pis if pi.get("is_contact_pi")), pis[0])
                        first = c_pi.get("first_name", "").strip().title()
                        last = c_pi.get("last_name", "").strip().title()
                        if first or last:
                            pi_name = f"Dr. {first} {last}"
                    else:
                        pi_name = clean_pi_name(p.get("contact_pi_name"))
                    
                    # Extract Organization
                    org_info = p.get("organization", {})
                    org_name = org_info.get("org_name", "Unknown Institution").strip().title()
                    
                    # Extract dates
                    start_date = p.get("project_start_date")
                    if start_date:
                        start_date = start_date[:10]  # Take YYYY-MM-DD
                    end_date = p.get("project_end_date")
                    if end_date:
                        end_date = end_date[:10]
                        
                    award_amount = p.get("award_amount", 0)
                    if award_amount is None:
                        award_amount = 0
                        
                    methodologies = scan_methodologies(title, abstract)
                    
                    parsed_grants.append({
                        "pi_name": pi_name,
                        "university": org_name,
                        "department": p.get("duns_description", "Research Department").strip().title() or "Research Division",
                        "grant_title": title,
                        "grant_abstract": abstract,
                        "methodologies": methodologies,
                        "funding_source": "NIH",
                        "funding_badge_url": "https://img.shields.io/badge/NIH-Funding-blue",
                        "award_amount": float(award_amount),
                        "start_date": start_date,
                        "end_date": end_date
                    })
                return parsed_grants
            else:
                warnings.warn(f"NIH RePORTER API status code {response.status}")
    except Exception as e:
        warnings.warn(f"Failed to fetch NIH RePORTER grants: {e}")
        
    return []

def fetch_nsf_grants(keywords: List[str], limit: int = 15, offset: int = 0) -> List[dict]:
    """
    Fetch active projects from NSF Award Search API matching keywords.
    """
    # Create keyword search term
    search_term = "+OR+".join(urllib.parse.quote(f'"{kw}"') for kw in keywords)
    fields = "id,title,startDate,expDate,abstractText,fundsObligatedAmt,pdPIName,awardeeName"
    
    url = f"https://api.nsf.gov/services/v1/awards.json?ActiveAwards=True&keyword={search_term}&printFields={fields}&rpp={limit}&offset={offset}"
    
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                res_body = json.loads(response.read().decode("utf-8"))
                results = res_body.get("response", {}).get("award", [])
                
                parsed_grants = []
                for a in results:
                    title = a.get("title", "Untitled NSF Research Award")
                    abstract = clean_abstract_html(a.get("abstractText", ""))
                    pi_name = clean_nsf_pi(a.get("pdPIName"))
                    org_name = a.get("awardeeName", "Unknown Institution").strip().title()
                    
                    start_date = parse_nsf_date(a.get("startDate"))
                    end_date = parse_nsf_date(a.get("expDate"))
                    
                    award_amount = a.get("fundsObligatedAmt", 0)
                    if award_amount is None:
                        award_amount = 0
                        
                    methodologies = scan_methodologies(title, abstract)
                    
                    parsed_grants.append({
                        "pi_name": pi_name,
                        "university": org_name,
                        "department": "Department of Science & Engineering",
                        "grant_title": title,
                        "grant_abstract": abstract,
                        "methodologies": methodologies,
                        "funding_source": "NSF",
                        "funding_badge_url": "https://img.shields.io/badge/NSF-Funding-blue",
                        "award_amount": float(award_amount),
                        "start_date": start_date,
                        "end_date": end_date
                    })
                return parsed_grants
            else:
                warnings.warn(f"NSF Award API status code {response.status}")
    except Exception as e:
        warnings.warn(f"Failed to fetch NSF awards: {e}")
        
    return []

def run_grant_ingestion(keywords: List[str] = None, limit: int = 15, offset: int = 0) -> dict:
    """
    Ingest research awards from NIH & NSF, deduplicate, calculate embeddings, and save to Supabase.
    """
    if not keywords:
        keywords = DEFAULT_KEYWORDS
        
    print(f"Starting grant ingestion for keywords: {keywords}")
    
    # 1. Fetch from APIs
    nih_list = fetch_nih_grants(keywords, limit=limit, offset=offset)
    nsf_list = fetch_nsf_grants(keywords, limit=limit, offset=offset)
    
    combined_grants = nih_list + nsf_list
    print(f"Fetched {len(nih_list)} NIH grants and {len(nsf_list)} NSF awards. Total: {len(combined_grants)}")
    
    if not combined_grants:
        return {"status": "success", "inserted": 0, "skipped": 0, "message": "No new grants found from external APIs."}
        
    db = get_db()
    inserted_count = 0
    skipped_count = 0
    
    # 2. Sync to Supabase
    for grant in combined_grants:
        try:
            # Check for duplicates by title to prevent duplication
            existing = db.table("labs_cached_grants").select("id").eq("grant_title", grant["grant_title"]).execute()
            if hasattr(existing, 'data') and existing.data:
                skipped_count += 1
                continue
                
            # Compute vector embedding
            import time
            time.sleep(1.5) # Prevent Gemini API rate limit exceptions during massive bulk ingestion
            emb_text = f"Title: {grant['grant_title']}. Abstract: {grant['grant_abstract']} PI: {grant['pi_name']} Methodologies: {', '.join(grant['methodologies'])}."
            embedding = generate_embedding(emb_text)
            
            # Prepare payload
            grant_data = {
                "pi_name": grant["pi_name"],
                "university": grant["university"],
                "department": grant["department"],
                "grant_title": grant["grant_title"],
                "grant_abstract": grant["grant_abstract"],
                "methodologies": grant["methodologies"],
                "funding_source": grant["funding_source"],
                "funding_badge_url": grant["funding_badge_url"],
                "award_amount": grant["award_amount"],
                "start_date": grant["start_date"],
                "end_date": grant["end_date"],
                "embedding": embedding
            }
            
            db.table("labs_cached_grants").insert(grant_data).execute()
            inserted_count += 1
            
        except Exception as e:
            warnings.warn(f"Failed to save grant '{grant.get('grant_title')[:40]}...': {e}")
            skipped_count += 1
            
    print(f"Ingestion complete: {inserted_count} inserted, {skipped_count} skipped/failed.")
    return {
        "status": "success",
        "inserted": inserted_count,
        "skipped": skipped_count,
        "message": f"Successfully ingested {inserted_count} awards (skipped/existing: {skipped_count})."
    }
