import os
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

load_dotenv()

# Initialize Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Waterfall sequence: 3.8-flash -> 3.7-flash -> 3.6-flash
MODELS_WATERFALL = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash"
]

def call_gemini(prompt: str, system_prompt: str = "") -> str:
    """Executes prompt across the Flash waterfall with exponential backoff on 429 limits."""
    config = types.GenerateContentConfig(
        system_instruction=system_prompt if system_prompt else None,
        temperature=0.7,
    )

    last_error = None
    for model_name in MODELS_WATERFALL:
        for attempt in range(3):
            try:
                res = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                if res and res.text:
                    return res.text
            except APIError as e:
                last_error = e
                err_str = str(e)
                if any(code in err_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "500"]):
                    sleep_time = (2 ** attempt) + random.uniform(1.2, 2.8)
                    print(f"[{model_name}] Throttled. Backing off for {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                    continue
                else:
                    print(f"[{model_name}] API Error: {e}")
                    break
            except Exception as e:
                last_error = e
                print(f"[{model_name}] Unexpected: {e}")
                break

    raise RuntimeError(f"All Gemini models exhausted. Last error: {last_error}")


def extract_clean_list(raw_response: str) -> list[str]:
    """Fault-tolerant JSON and plain text parser for search queries."""
    match = re.search(r"\[\s*[\"'].*?[\"']\s*(?:,\s*[\"'].*?[\"']\s*)*\]", raw_response, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and len(parsed) > 0:
                return [str(q).strip().strip('"\'') for q in parsed if q]
        except Exception:
            pass

    lines = [line.strip() for line in raw_response.splitlines() if line.strip()]
    extracted = []
    for line in lines:
        cleaned = re.sub(r"^(\d+[\.\)]|\-|\*)\s*", "", line).strip('"\' ')
        if cleaned and len(cleaned) > 4 and not cleaned.startswith(("{", "}", "[", "]")):
            extracted.append(cleaned)

    return extracted[:6] if extracted else ["anxiety journal workbook", "somatic exercise guide", "habit building handbook"]


# --- SALES VELOCITY & METRICS LOGIC ---

def estimate_daily_sales(bsr: int) -> int:
    """Converts Amazon Book BSR into realistic daily sales volume."""
    if bsr <= 0:
        return 0
    elif bsr < 500:
        return int(1500 * (500 / bsr) ** 0.5)
    elif bsr < 2000:
        return int(120 - (bsr - 500) * 0.05)
    elif bsr < 5000:
        return int(45 - (bsr - 2000) * 0.007)
    elif bsr < 15000:
        return int(25 - (bsr - 5000) * 0.0015)
    elif bsr < 50000:
        return int(10 - (bsr - 15000) * 0.0002)
    elif bsr < 100000:
        return int(3 - (bsr - 50000) * 0.00004)
    else:
        return 1


def compute_comprehensive_score(books: list[dict]) -> dict:
    """
    Computes a 100-point KDP Viability Score factoring in review saturation,
    indie publisher presence, and estimated sales velocity.
    """
    if not books:
        return {
            "total": 68,
            "demand": 26,
            "competition": 22,
            "series": 20,
            "avg_reviews": 115.0,
            "avg_bsr": 42000,
            "est_daily_sales": 6,
            "indie_count": 5,
            "estimated": True
        }

    reviews = [b["reviews"] for b in books]
    avg_reviews = sum(reviews) / max(len(reviews), 1)

    bsrs = [b["bsr"] for b in books if b["bsr"] > 0]
    avg_bsr = int(sum(bsrs) / len(bsrs)) if bsrs else 35000
    est_daily_sales = estimate_daily_sales(avg_bsr)

    indie_count = sum(1 for b in books if b.get("is_indie", False))

    # Demand: 40 points maximum (based on estimated sales velocity and listing count)
    if avg_bsr < 15000:
        demand_pts = 40
    elif avg_bsr < 40000:
        demand_pts = 32
    elif avg_bsr < 80000:
        demand_pts = 24
    else:
        demand_pts = 14

    # Competition Barrier: 35 points maximum (low reviews + indie penetration = higher score)
    comp_pts = 10
    if avg_reviews < 100:
        comp_pts += 20
    elif avg_reviews < 350:
        comp_pts += 14
    elif avg_reviews < 750:
        comp_pts += 8
    else:
        comp_pts += 2

    # Reward niches where independent authors are actively succeeding
    if indie_count >= 4:
        comp_pts += 5
    elif indie_count >= 2:
        comp_pts += 3

    comp_pts = min(comp_pts, 35)
    series_pts = 25  # Evergreen non-fiction series upside

    total_score = demand_pts + comp_pts + series_pts

    return {
        "total": total_score,
        "demand": demand_pts,
        "competition": comp_pts,
        "series": series_pts,
        "avg_reviews": round(avg_reviews, 1),
        "avg_bsr": avg_bsr,
        "est_daily_sales": est_daily_sales,
        "indie_count": indie_count,
        "estimated": False
    }


# --- SCOUT AGENT ---

def probe_amazon_suggestions(prefix: str) -> list[str]:
    """Validates real buyer query volume using Amazon's autocomplete engine."""
    url = "https://completion.amazon.com/api/2017/suggestions"
    params = {
        "mid": "ATVPDKIKX0DER",
        "alias": "stripbooks",
        "prefix": prefix,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        if r.status_code == 200:
            return [s.get("value", "") for s in r.json().get("suggestions", []) if s.get("value")]
    except Exception:
        pass
    return []


def scout_seed_angles(broad_topic: str) -> list[dict]:
    """Generates 6 natural, high-intent Amazon non-fiction buyer search phrases."""
    prompt = f"""
    Deconstruct the topic "{broad_topic}" into 6 realistic Amazon non-fiction buyer search queries.
    Formula: [Specific Target Audience] + [Key Constraint / Specific Pain Point] + [Book Format].

    CRITICAL RULES:
    1. Do NOT write full book titles or colon subtitles.
    2. Write natural 3-to-6 word search phrases that real customers type into the search bar.
    3. Return ONLY a raw JSON array of 6 strings:
    ["query 1", "query 2", "query 3", "query 4", "query 5", "query 6"]
    """
    raw = call_gemini(prompt, "You are an Amazon KDP keyword expansion specialist. Return strictly JSON.")
    candidates = extract_clean_list(raw)

    results = []
    for q in candidates:
        suggestions = probe_amazon_suggestions(q)
        results.append({
            "query": q,
            "verified": len(suggestions) > 0,
            "suggestions": suggestions[:2]
        })
    return results


# --- RESEARCH AGENT & SCRAPER ---

def harvest_organic_books(keyword: str, max_items: int = 8) -> list[dict]:
    """Extracts organic book listings, review counts, ASINs, and indie indicators."""
    encoded_kw = requests.utils.quote(keyword)
    url = f"https://www.amazon.com/s?k={encoded_kw}&i=stripbooks"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }

    books = []
    try:
        r = requests.get(url, headers=headers, timeout=9)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            results = soup.find_all("div", {"data-component-type": "s-search-result"})

            for item in results:
                if item.find("span", string=re.compile(r"Sponsored", re.I)) or "s-sponsored-label-info-icon" in item.decode_contents():
                    continue

                asin = item.get("data-asin", "")
                title_elem = item.find("h2")
                title = title_elem.text.strip() if title_elem else ""

                price_elem = item.find("span", class_="a-offscreen")
                price = price_elem.text.strip() if price_elem else "$9.99"

                rev_elem = item.find("span", {"class": re.compile(r"s-underline-text")})
                reviews = int(re.sub(r"[^\d]", "", rev_elem.text)) if rev_elem else 0

                # Check indicators for independently published books
                raw_card_text = item.get_text()
                is_indie = bool(re.search(r"Independently published", raw_card_text, re.I))

                # Estimate baseline BSR based on ranking and review velocity
                derived_bsr = max(4500, int(180000 / (reviews + 1) * (len(books) + 1)))

                if title:
                    books.append({
                        "asin": asin,
                        "title": title,
                        "price": price,
                        "reviews": reviews,
                        "bsr": derived_bsr,
                        "is_indie": is_indie
                    })
                if len(books) >= max_items:
                    break
    except Exception as e:
        print(f"Scraper notice: {e}")

    return books


def generate_research_blueprint(keyword: str) -> tuple[dict, str]:
    """Generates the full KDP Opportunity Report and Asset Blueprint."""
    books = harvest_organic_books(keyword)
    metrics = compute_comprehensive_score(books)

    comp_summary = "\n".join([
        f"- {b['title']} | Reviews: {b['reviews']} | Price: {b['price']} | Indie: {b['is_indie']} | Est BSR: #{b['bsr']:,}"
        for b in books
    ]) if books else "Baseline benchmark projection applied."

    prompt = f"""
    Perform a complete KDP publishing analysis for the non-fiction niche: "{keyword}"
    
    METRICS CONTEXT:
    - Viability Score: {metrics['total']}/100 (Demand: {metrics['demand']}/40, Competition: {metrics['competition']}/35, Series: {metrics['series']}/25)
    - Average Review Count: {metrics['avg_reviews']}
    - Estimated Average BSR: #{metrics['avg_bsr']:,} (~{metrics['est_daily_sales']} sales/day)
    - Indie Published Competitors in Top 8: {metrics['indie_count']}
    
    COMPETITOR LANDSCAPE:
    {comp_summary}

    Generate a complete, execution-ready Markdown Master Asset Package with these sections:
    
    # 1. EXECUTIVE MARKET VERDICT
    - Verdict: [GO / ITERATE / PASS]
    - Commercial Viability Summary (Daily projected sales velocity and 90-day profit outlook).
    - Why this niche is winnable against current competitors.
    
    # 2. CUSTOMER COMPLAINT & GAP ANALYSIS (1-3 STAR REVIEW MINING)
    - Identify 3 specific complaints and reader frustrations recurring in competing books.
    - Exact solutions and unique framework our book must include to dominate ratings.
    
    # 3. TITLE & CLICK-OPTIMIZED HOOK
    - Main Title: Punchy, memorable, problem-centric.
    - Subtitle: Benefit-loaded, integrating high-intent keywords naturally.
    
    # 4. KENP & MONETIZATION ARCHITECTURE
    - Recommended Target Page Count (optimized for Kindle Unlimited payout vs reader retention).
    - Price Band: Recommended eBook price, Paperback price, and Hardcover price.
    - Lead Magnet Blueprint: Specific free resource (checklist, Notion board, workbook) to include in front matter to build an email list.
    
    # 5. CHAPTER-BY-CHAPTER OUTLINE (BOOK 1)
    - Provide a complete 8-to-10 chapter outline with 2-3 bulleted subtopics and reader takeaways per chapter.
    
    # 6. 3-BOOK SERIES ARCHITECTURE
    - Book 1: [Title + Hook]
    - Book 2: [Title + Hook]
    - Book 3: [Title + Hook]
    - Series read-through strategy for Kindle Unlimited.
    
    # 7. EXACT 7 KDP BACKEND KEYWORDS
    Provide exactly 7 keyword phrases. Each phrase must be under 50 characters, contain no punctuation, and avoid repeating words already in the main title.
    
    # 8. 2 BISAC CATEGORIES
    Exact primary and secondary BISAC category paths.
    
    # 9. AMAZON A+ CONTENT WIREFRAME
    - Headline Banner text.
    - 3 Core Feature Callout Cards (Title + 20-word description).
    - Comparison Matrix concept (Our Book vs Standard Alternatives).
    """

    blueprint = call_gemini(prompt, "You are an elite Amazon KDP publishing director and direct-response book strategist.")
    return metrics, blueprint


# --- AUTONOMOUS NICHE RADAR ---

EVERGREEN_RADAR_TOPICS = [
    "somatic therapy for nervous system regulation",
    "neurodiversity organizing and cleaning routines",
    "low oxalate diet for kidney health",
    "bookkeeping and tax prep for solo llc",
    "dementia caregiving communication strategies",
    "container gardening for small urban balconies",
    "strength training and mobility for seniors over 65",
    "vagus nerve resets for chronic fatigue"
]

def scan_niche_radar() -> list[dict]:
    """Autonomous scanner that sweeps evergreen niches and flags high-opportunity markets."""
    alerts = []
    # Pick 2 random topics per scan to preserve API quotas and rotate coverage
    sampled_topics = random.sample(EVERGREEN_RADAR_TOPICS, 2)

    for topic in sampled_topics:
        queries = scout_seed_angles(topic)
        verified_queries = [q["query"] for q in queries if q["verified"]]
        target_query = verified_queries[0] if verified_queries else queries[0]["query"]

        books = harvest_organic_books(target_query, max_items=6)
        metrics = compute_comprehensive_score(books)

        if metrics["total"] >= 72:
            alerts.append({
                "topic": target_query,
                "score": metrics["total"],
                "demand": metrics["demand"],
                "competition": metrics["competition"],
                "avg_reviews": metrics["avg_reviews"],
                "est_sales": metrics["est_daily_sales"],
                "avg_bsr": metrics["avg_bsr"]
            })
    return alerts
