import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import json
import urllib.request
import urllib.error
import re
import html
import warnings
from typing import List, Dict, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..database import get_db, generate_embedding

# Constants
DEFAULT_KEYWORDS = [
    # CS & AI
    "CRISPR", "Microfluidics", "Machine Learning", "Deep Learning",
    "Bioinformatics", "RNA-Seq", "Genomics", "Robotics", "Neurobiology",
    "Computer Vision", "Natural Language Processing", "Quantum Computing",
    "Cybersecurity", "Reinforcement Learning", "Autonomous Systems",
    # Physical Sciences & Engineering
    "Nanotechnology", "Fusion Energy", "Materials Science", "Aerospace Engineering",
    "SolidWorks", "Additive Manufacturing", "Semiconductors",
    # Environmental & Climate
    "Wildlife Habitat", "Hydrology", "Ecological Restoration", "Climate Resilience",
    "Marine Biology", "Forestry", "Carbon Sequestration", "Biofuels",
    # Biomedical
    "Gene Therapy", "Somatic Mutations", "Immunotherapy", "Stem Cells",
    "Cancer Genomics", "Medical Devices", "Virology"
]

KEYWORDS_METHODOLOGIES = [
    "CRISPR", "Microfluidics", "Machine Learning", "Deep Learning", "NLP",
    "TensorFlow", "PyTorch", "RNA-Seq", "Sequencing", "Electrophysiology",
    "CAD", "SolidWorks", "Cell Culture", "Imaging", "Mass Spectrometry",
    "Stem Cells", "Gene Editing", "Bioinformatics", "Microtunnels",
    "Organ-on-a-chip", "High-Throughput Screening", "Robotics", "Computer Vision",
    "Quantum Computing", "Cybersecurity", "Nanotechnology", "Fusion", "Hydrology",
    "Ecological", "Immunotherapy", "Cancer", "Aerospace", "Genetics", "Biophysics"
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

def is_valid_pi(name: str) -> bool:
    """
    Check if the resolved PI name is a valid person's name and not a placeholder.
    """
    if not name or name == "Dr. Unknown Investigator":
        return False
    name_lower = name.lower()
    invalid_keywords = [
        "unknown", "not found", "not specified", "not available", 
        "unable to determine", "n/a", "no pi", "information not", 
        "name not", "not provided", "dr. first last", "dr. name",
        "no principal investigator", "not explicitly", "not identified",
        "search results", "not show", "does not contain", "further investigation",
        "not clear", "not list", "no investigator", "not yield", "no name"
    ]
    if any(k in name_lower for k in invalid_keywords):
        return False
        
    # Remove Dr. prefix
    clean_name = re.sub(r'^dr\.\s+', '', name, flags=re.IGNORECASE).strip()
    
    # Person's name should be relatively short (typically 2 to 4 words, and less than 40 chars)
    words = clean_name.split()
    if len(words) < 2 or len(words) > 4 or len(clean_name) > 40:
        return False
        
    # Make sure it's not a full sentence (doesn't contain verbs like 'was', 'is', 'has')
    if any(verb in words for verb in ["was", "is", "has", "been", "were", "are", "have", "would", "could"]):
        return False
        
    return True

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

def fetch_nih_grants(keyword: str, limit: int = 15, offset: int = 0) -> List[dict]:
    """
    Fetch active, funded projects from NIH RePORTER API v2 matching keyword.
    """
    url = "https://api.reporter.nih.gov/v2/projects/search"
    headers = {"Content-Type": "application/json"}
    
    # Create keyword search term
    search_term = f'"{keyword}"'
    
    # "abstracttext" is the field RePORTER v2 actually accepts. "abstract" is silently
    # ignored: the API drops the criterion and returns the whole ~2.9M-project corpus,
    # identically for every keyword. Verified 2026-07-16 — "CRISPR" and "coral reef" both
    # returned total=2951995 with the same top results under "abstract", vs 23620 and 82
    # on-topic results under "abstracttext".
    #
    # No sort_field, so RePORTER ranks by relevance to search_text. Sorting by
    # project_start_date desc returned newest-first regardless of topical fit.
    payload = {
        "criteria": {
            "advanced_text_search": {
                "search_field": "abstracttext",
                "search_text": search_term
            }
        },
        "limit": limit,
        "offset": offset
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

def fetch_nsf_grants(keyword: str, limit: int = 15, offset: int = 0) -> List[dict]:
    """
    Fetch active projects from NSF Award Search API matching keyword.
    """
    # Create keyword search term
    search_term = urllib.parse.quote(f'"{keyword}"')
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
                        "end_date": end_date,
                        # `id` is already requested in printFields above but used to be
                        # discarded, leaving every NSF row with a NULL award_id. Without it
                        # an award can only be re-found by title (see
                        # backfill_abstract_provenance.py), and dedup has no natural key.
                        "award_id": a.get("id")
                    })
                return parsed_grants
            else:
                warnings.warn(f"NSF Award API status code {response.status}")
    except Exception as e:
        warnings.warn(f"Failed to fetch NSF awards: {e}")
        
    return []

def fetch_usaspending_grants(agency_name: str, keyword: str, limit: int = 15, offset: int = 0) -> List[dict]:
    """
    Fetch active, funded projects from USAspending.gov API matching agency and keyword.
    Includes rate-limiting delays and robust retry logic to prevent firewall blocks.
    """
    import time
    
    # Enforce basic rate-limiting delay between calls
    time.sleep(1.0)
    
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "filters": {
            "award_type_codes": ["02", "03", "04", "05"],  # Grants
            "agencies": [
                {
                    "type": "awarding",
                    "tier": "toptier",
                    "name": agency_name
                }
            ],
            "keywords": [keyword]
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Start Date",
            "End Date",
            "Award Amount",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Description"
        ],
        "limit": limit,
        "page": (offset // limit) + 1,
        "sort": "Award Amount",
        "order": "desc"
    }
    
    max_retries = 3
    retry_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    results = res_body.get("results", [])
                    
                    parsed_grants = []
                    for p in results:
                        title = p.get("Description", "Untitled Research Grant")
                        if not title:
                            continue
                        if title.startswith("'") and title.endswith("'"):
                            title = title[1:-1]
                        if title.startswith('"') and title.endswith('"'):
                            title = title[1:-1]
                        title = clean_abstract_html(title)
                        
                        org_name = p.get("Recipient Name", "Unknown Institution").strip().title()
                        
                        start_date = p.get("Start Date")
                        end_date = p.get("End Date")
                        award_amount = p.get("Award Amount", 0)
                        if award_amount is None:
                            award_amount = 0
                            
                        methodologies = scan_methodologies(title, title)
                        
                        if agency_name == "Department of Defense":
                            funding_source = "DOD"
                            funding_badge_url = "https://img.shields.io/badge/DOD-Funding-maroon"
                        elif agency_name == "Department of the Interior":
                            funding_source = "DNR"
                            funding_badge_url = "https://img.shields.io/badge/DNR-Funding-green"
                        elif agency_name == "Department of Energy":
                            funding_source = "DOE"
                            funding_badge_url = "https://img.shields.io/badge/DOE-Funding-darkgreen"
                        elif agency_name == "Environmental Protection Agency":
                            funding_source = "EPA"
                            funding_badge_url = "https://img.shields.io/badge/EPA-Funding-orange"
                        elif agency_name == "National Aeronautics and Space Administration":
                            funding_source = "NASA"
                            funding_badge_url = "https://img.shields.io/badge/NASA-Funding-blue"
                        elif agency_name == "Department of Agriculture":
                            funding_source = "USDA"
                            funding_badge_url = "https://img.shields.io/badge/USDA-Funding-olive"
                        else:
                            funding_source = "Federal"
                            funding_badge_url = "https://img.shields.io/badge/Federal-Funding-grey"
                            
                        parsed_grants.append({
                            "pi_name": "Dr. Unknown Investigator",
                            "university": org_name,
                            "department": p.get("Awarding Sub Agency", "Research Division").strip().title() or "Research Division",
                            "grant_title": title,
                            "grant_abstract": title,
                            "methodologies": methodologies,
                            "funding_source": funding_source,
                            "funding_badge_url": funding_badge_url,
                            "award_amount": float(award_amount),
                            "start_date": start_date,
                            "end_date": end_date,
                            "award_id": p.get("Award ID")
                        })
                    return parsed_grants
                else:
                    raise Exception(f"USAspending API status code {response.status}")
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[USAspending API] Connection error on attempt {attempt + 1}/{max_retries}: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2.0
            else:
                warnings.warn(f"Failed to fetch USAspending grants for {agency_name} after {max_retries} attempts: {e}")
                
    return []

def resolve_grant_pi_and_abstract(award_id: str, institution: str, title: str) -> dict:
    """
    Use Google Gemini 2.5 Flash with search grounding to resolve the Principal Investigator
    and abstract/description of a grant. Includes robust retries and backoff for rate limits.
    """
    from ..config import settings
    if not settings.gemini_api_key:
        warnings.warn("GEMINI_API_KEY is not configured. Skipping PI resolution.")
        return {"pi_name": "Dr. Unknown Investigator", "grant_abstract": title}
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""
    You are an expert research grant metadata extractor. Your job is to find the Principal Investigator (PI) name and a short project abstract for the following U.S. federal research grant award:
    Award ID: {award_id}
    Recipient Institution: {institution}
    Title: {title}
    
    Use Google Search to find the official award record (e.g. from DTIC, CDMRP, NSF, NIH, USAspending, or the university's research page).
    Identify the contact Principal Investigator's name (formatted as 'Dr. First Last').
    Extract a technical research abstract/description of the project (1-2 paragraphs).
    
    Please output the information in the following format exactly:
    PI: [Name]
    ABSTRACT: [Description]
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
    
    max_retries = 3
    backoff = 10.0
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    candidates = res_body.get("candidates", [])
                    if not candidates:
                        raise Exception("API returned status code 200 but candidates list is empty.")
                    
                    cand = candidates[0]
                    content = cand.get("content", {})
                    parts = content.get("parts", [])
                    if not parts:
                        raise Exception(f"API returned status code 200 but content parts is empty. finishReason={cand.get('finishReason')}, contentKeys={list(content.keys())}")
                    
                    text_content = parts[0].get("text", "")
                    if not text_content:
                        raise Exception("API returned status code 200 but text field in parts is empty.")
                    
                    text_content = text_content.strip()
                    
                    # Parse the plain text response
                    pi_name = "Dr. Unknown Investigator"
                    grant_abstract = title
                    
                    lines = text_content.split("\n")
                    pi_found = False
                    abstract_lines = []
                    in_abstract = False
                    
                    for line in lines:
                        line_strip = line.strip()
                        if not line_strip:
                            if in_abstract and abstract_lines:
                                abstract_lines.append("")
                            continue
                            
                        # Check for PI line
                        if re.match(r'^(?:PI|Principal Investigator)\s*:\s*(.*)', line_strip, re.IGNORECASE):
                            pi_name = re.sub(r'^(?:PI|Principal Investigator)\s*:\s*', '', line_strip, flags=re.IGNORECASE).strip()
                            pi_name = re.sub(r'[\*\#\_\[\]]', '', pi_name).strip()
                            pi_found = True
                            in_abstract = False
                            continue
                            
                        # Check for Abstract header
                        if re.match(r'^(?:ABSTRACT|Description)\s*:\s*(.*)', line_strip, re.IGNORECASE):
                            first_part = re.sub(r'^(?:ABSTRACT|Description)\s*:\s*', '', line_strip, flags=re.IGNORECASE).strip()
                            first_part = re.sub(r'[\*\#\_\[\]]', '', first_part).strip()
                            if first_part:
                                abstract_lines.append(first_part)
                            in_abstract = True
                            continue
                            
                        # If we are in abstract mode, accumulate lines
                        if in_abstract:
                            line_clean = re.sub(r'[\*\#\_\[\]]', '', line_strip).strip()
                            abstract_lines.append(line_clean)
                        elif not pi_found and ("dr." in line_strip.lower() or "investigator" in line_strip.lower()):
                            # Fallback check for PI name in text
                            dr_match = re.search(r'Dr\.\s+[A-Z][a-zA-Z\-\']+\s+[A-Z][a-zA-Z\-\']+', line_strip)
                            if dr_match:
                                pi_name = dr_match.group(0)
                                pi_found = True
                                
                    if abstract_lines:
                        grant_abstract = "\n".join(abstract_lines).strip()
                        grant_abstract = re.sub(r'\n{3,}', '\n\n', grant_abstract)
                        
                    return {
                        "pi_name": pi_name,
                        "grant_abstract": grant_abstract
                    }
                else:
                    raise Exception(f"API returned status code {response.status}")
                
        except urllib.error.HTTPError as he:
            if he.code == 429:
                print(f"[Gemini API] Rate limit hit (429) on attempt {attempt + 1}/{max_retries}. Sleeping {backoff}s...")
            else:
                print(f"[Gemini API] HTTP Error {he.code} on attempt {attempt + 1}/{max_retries}. Sleeping {backoff}s...")
        except Exception as e:
            print(f"[Gemini API] Error on attempt {attempt + 1}/{max_retries}: {e}. Sleeping {backoff}s...")
            
        if attempt < max_retries - 1:
            import time
            time.sleep(backoff)
            backoff *= 2.0
            
    warnings.warn(f"Failed to resolve PI/abstract via Gemini for Award ID {award_id} after {max_retries} attempts.")
    return {"pi_name": "Dr. Unknown Investigator", "grant_abstract": title}

def is_brief_abstract(abstract: str, title: str) -> bool:
    """
    Check if the grant abstract is missing, too brief, or contains placeholder text.
    """
    if not abstract:
        return True
    
    a_clean = abstract.strip().lower()
    t_clean = title.strip().lower()
    
    # Remove final periods/spaces for comparison
    a_compare = re.sub(r'[\s\.]+$', '', a_clean)
    t_compare = re.sub(r'[\s\.]+$', '', t_clean)
    
    if a_compare == t_compare:
        return True
        
    # Check for placeholder indicators
    placeholders = [
        "not available", "information not found", "no abstract", 
        "n/a", "unknown", "not specified", "not provided", 
        "information not available", "not show", "does not contain"
    ]
    if any(p in a_clean for p in placeholders) and len(abstract.split()) < 15:
        return True
        
    # Check length: if less than 25 words, it's considered brief
    if len(abstract.split()) < 25:
        return True
        
    return False

def expand_grant_abstract_via_llm(grant: dict) -> str:
    """
    Use Google Gemini (gemini-2.5-flash) to generate a comprehensive, scientifically-accurate
    project description/synthesis based on the grant metadata.
    """
    from ..config import settings
    if not settings.gemini_api_key:
        warnings.warn("GEMINI_API_KEY is not configured. Skipping abstract expansion.")
        return grant.get("grant_abstract") or grant.get("grant_title") or ""
        
    title = grant.get("grant_title", "Untitled Research Project")
    pi_name = grant.get("pi_name", "Dr. Unknown Investigator")
    university = grant.get("university", "Unknown Institution")
    funding_source = grant.get("funding_source", "Federal Agency")
    methodologies = grant.get("methodologies") or ["Research Analysis"]
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""
    You are an expert science writer and research grant advisor. We have a research grant with the following metadata:
    Title: {title}
    Principal Investigator: {pi_name}
    Institution: {university}
    Funding Agency: {funding_source}
    Methodologies: {', '.join(methodologies)}
    
    The current description/abstract is either missing or too brief. Please generate a comprehensive, technical, and scientifically accurate research abstract and project synthesis (1-2 paragraphs, around 150-250 words) that describes what this research project likely entails.
    
    Focus on:
    - The background, significance, and objective of the research based on the title.
    - How the methodologies ({', '.join(methodologies)}) are likely applied to achieve these objectives.
    - The potential impact on the field (e.g., healthcare, energy, computer science, environment).
    
    Ensure it sounds professional, scientific, and reads like a real federal grant abstract. Do not include any meta-text, intro/outro, or pleasantries. Output only the generated abstract text.
    """
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    
    max_retries = 3
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    candidates = res_body.get("candidates", [])
                    if not candidates:
                        raise Exception("API returned status code 200 but candidates list is empty.")
                    
                    cand = candidates[0]
                    content = cand.get("content", {})
                    parts = content.get("parts", [])
                    if not parts:
                        raise Exception("API returned status code 200 but content parts is empty.")
                    
                    text_content = parts[0].get("text", "")
                    if not text_content:
                        raise Exception("API returned status code 200 but text field in parts is empty.")
                    
                    text_content = text_content.strip()
                    # Strip any markdown formatting block if Gemini tried to put it in a block
                    text_content = re.sub(r'^```[a-zA-Z]*\n', '', text_content)
                    text_content = re.sub(r'\n```$', '', text_content)
                    text_content = text_content.strip()
                    
                    if text_content:
                        return text_content
                else:
                    raise Exception(f"API returned status code {response.status}")
        except Exception as e:
            print(f"[Gemini Abstract Expansion] Error on attempt {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(backoff)
                backoff *= 2.0
                
    warnings.warn("Failed to expand abstract via Gemini. Using fallback.")
    return grant.get("grant_abstract") or grant.get("grant_title") or ""

def process_single_grant(grant: dict) -> Optional[dict]:
    """
    Process a single grant: resolve PI/abstract if needed, and compute vector embedding.
    """
    title = grant.get("grant_title")
    if not title:
        return None
    try:
        # Provenance: flips to True the moment the abstract text stops being
        # verbatim federal API output (see abstract_is_generated migration).
        abstract_is_generated = False

        # For USAspending grants, dynamically resolve PI name and abstract before embedding calculation
        if grant["funding_source"] in ["DOD", "DNR", "DOE", "EPA", "NASA", "USDA"]:
            print(f"    Resolving PI and abstract for {grant['funding_source']} grant: '{title[:40]}...' (Award ID: {grant.get('award_id')})")
            resolved = resolve_grant_pi_and_abstract(grant.get("award_id"), grant["university"], title)
            resolved_pi = resolved["pi_name"]
            if not is_valid_pi(resolved_pi):
                resolved_pi = "Dr. Unknown Investigator"
            grant["pi_name"] = resolved_pi
            grant["grant_abstract"] = resolved["grant_abstract"]
            # USAspending provides no abstract; this text is LLM-mediated even
            # when grounded in search results.
            abstract_is_generated = True
            # Re-scan methodologies using the resolved abstract
            grant["methodologies"] = scan_methodologies(title, grant["grant_abstract"])

        # Check if the abstract is brief/uninformative and expand it via LLM
        if is_brief_abstract(grant.get("grant_abstract", ""), title):
            print(f"    Abstract is brief/missing for '{title[:40]}...'. Expanding via Gemini...")
            expanded_abstract = expand_grant_abstract_via_llm(grant)
            if expanded_abstract != grant.get("grant_abstract", ""):
                abstract_is_generated = True
            grant["grant_abstract"] = expanded_abstract
            # Re-scan methodologies with the newly expanded abstract
            grant["methodologies"] = scan_methodologies(title, expanded_abstract)

        # Compute vector embedding
        emb_text = f"Title: {title}. Abstract: {grant['grant_abstract']} PI: {grant['pi_name']} Methodologies: {', '.join(grant['methodologies'])}."
        embedding = generate_embedding(emb_text)
        
        return {
            "pi_name": grant["pi_name"],
            "university": grant["university"],
            "department": grant["department"],
            "grant_title": title,
            "grant_abstract": grant["grant_abstract"],
            "methodologies": grant["methodologies"],
            "funding_source": grant["funding_source"],
            "funding_badge_url": grant["funding_badge_url"],
            "award_amount": grant["award_amount"],
            "start_date": grant["start_date"],
            "end_date": grant["end_date"],
            "embedding": embedding,
            "award_id": grant.get("award_id"),
            "abstract_is_generated": abstract_is_generated
        }
    except Exception as e:
        warnings.warn(f"Failed to process grant '{title[:40]}...': {e}")
        return None

def load_all_existing_titles(db) -> set:
    """
    Load all existing grant titles from database in batches to bypass Postgrest default limits.
    """
    titles = set()
    limit = 1000
    offset = 0
    while True:
        try:
            res = db.table("labs_cached_grants").select("grant_title").range(offset, offset + limit - 1).execute()
            batch = res.data or []
            if not batch:
                break
            for item in batch:
                t = item.get("grant_title")
                if t:
                    titles.add(t)
            if len(batch) < limit:
                break
            offset += limit
        except Exception as e:
            warnings.warn(f"Failed to fetch titles batch at offset {offset}: {e}")
            break
    return titles

def run_grant_ingestion(keywords: List[str] = None, pages: int = 10, limit_per_page: int = 25) -> dict:
    """
    Ingest research awards from NIH, NSF, and USAspending (DOD, DNR, DOE, EPA, NASA, USDA)
    by querying each keyword individually, deduplicating in-memory, calculating embeddings,
    and saving new unique awards to Supabase.
    """
    if not keywords:
        keywords = DEFAULT_KEYWORDS
        
    print(f"Starting keyword-by-keyword grant ingestion for {len(keywords)} keywords, pages: {pages}, limit_per_page: {limit_per_page}")
    
    db = get_db()
    
    # Pre-fetch existing titles to optimize duplicate checking and avoid redundant DB queries
    try:
        existing_titles = load_all_existing_titles(db)
        print(f"Pre-loaded {len(existing_titles)} existing grant titles from database.")
    except Exception as e:
        existing_titles = set()
        warnings.warn(f"Failed to pre-fetch existing grant titles from DB: {e}")
        
    seen_titles = existing_titles.copy()
    
    # USAspending agencies
    agencies = [
        "Department of Defense",
        "Department of the Interior",
        "Department of Energy",
        "Environmental Protection Agency",
        "National Aeronautics and Space Administration",
        "Department of Agriculture"
    ]
    
    inserted_count = 0
    skipped_count = 0
    # Per-source fetch tallies. A source that fetches 0 across an entire run is almost
    # certainly failing (blocked / changed API), not legitimately empty -- the fetchers
    # swallow their errors and return [], so without this a starved source is invisible.
    fetched_by_source = {"NIH": 0, "NSF": 0, "USASpending": 0}

    for kw_idx, keyword in enumerate(keywords):
        print(f"\n[{kw_idx + 1}/{len(keywords)}] Querying keyword: '{keyword}'...")

        for page in range(pages):
            offset = page * limit_per_page
            print(f"  Fetching page {page + 1}/{pages} (offset: {offset})...")

            # Fetch from NIH, NSF, and USAspending
            nih_list = fetch_nih_grants(keyword, limit=limit_per_page, offset=offset)
            nsf_list = fetch_nsf_grants(keyword, limit=limit_per_page, offset=offset)

            usa_list = []
            for agency in agencies:
                usa_list += fetch_usaspending_grants(agency, keyword, limit=limit_per_page, offset=offset)

            fetched_by_source["NIH"] += len(nih_list)
            fetched_by_source["NSF"] += len(nsf_list)
            fetched_by_source["USASpending"] += len(usa_list)

            batch_grants = nih_list + nsf_list + usa_list
            
            # Filter batch grants to get new ones
            new_grants = []
            for grant in batch_grants:
                title = grant["grant_title"]
                if not title:
                    continue
                    
                # Deduplication check
                if title in seen_titles:
                    skipped_count += 1
                    continue
                    
                seen_titles.add(title)
                new_grants.append(grant)
                
            if new_grants:
                print(f"  Processing {len(new_grants)} new unique grants in parallel...")
                processed_grants = []
                # Process in parallel using up to 10 workers (safe for API and concurrent embedding gen)
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(process_single_grant, g): g for g in new_grants}
                    for future in as_completed(futures):
                        res = future.result()
                        if res:
                            processed_grants.append(res)
                            
                if processed_grants:
                    try:
                        db.table("labs_cached_grants").insert(processed_grants).execute()
                        inserted_count += len(processed_grants)
                        print(f"  Successfully batch inserted {len(processed_grants)} grants.")
                    except Exception as e:
                        warnings.warn(f"Failed to batch insert grants: {e}")
                        skipped_count += len(new_grants)
                else:
                    print("  No grants successfully processed in this batch.")
                    
    # A source that returned nothing across the whole run is flagged as a likely failure.
    starved_sources = [s for s, n in fetched_by_source.items() if n == 0]
    for s in starved_sources:
        warnings.warn(f"Ingestion source '{s}' returned 0 grants across all keywords -- likely a failing/blocked API, not empty results.")

    print(f"\nIngestion complete: {inserted_count} inserted, {skipped_count} skipped/failed. By source fetched: {fetched_by_source}")
    return {
        "status": "success",
        "inserted": inserted_count,
        "skipped": skipped_count,
        "by_source": fetched_by_source,
        "starved_sources": starved_sources,
        "message": f"Successfully ingested {inserted_count} awards (skipped/existing: {skipped_count})."
    }
