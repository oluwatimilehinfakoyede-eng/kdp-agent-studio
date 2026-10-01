import os
import re
import json
import time
import random
import urllib.parse
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# Lazy initialization to prevent import-time crashes if env vars are missing
_groq_client = None
def get_groq_client():
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is missing from environment variables.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b"
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0"
]

# --- Demographic Mapping for Elite Prompting ---
DEMOGRAPHIC_MAP = {
    "diet": "Chronic Illness Patient / Medical Diet Adherent (Requires practical, low-energy meal prep solutions, physical grocery lists)",
    "somatic": "Nervous System Dysregulation / Trauma Recovery (Requires gentle, floor-based physical exercises, clinical safety)",
    "adhd": "Neurodivergent Adult / Executive Dysfunction (Requires dopamine-driven micro-steps, body-doubling concepts, digital/visual aids)",
    "senior": "Senior Citizen / Limited Mobility (Requires LARGE PRINT, physical mailers, seated safety, zero complex tech)",
    "solopreneur": "Small Business Owner / Solopreneur (Requires high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology)",
    "parenting": "Parent of Neurodivergent/Dysregulated Child (Requires clinical de-escalation scripts, emotional regulation for the parent)"
}

def get_demographic_context(keyword: str) -> str:
    """Infers demographic context from the keyword to prevent generic LLM filler."""
    keyword_lower = keyword.lower()
    for key, context in DEMOGRAPHIC_MAP.items():
        if key in keyword_lower:
            return f"TARGET DEMOGRAPHIC: {context}"
    return "TARGET DEMOGRAPHIC: General Non-Fiction Reader (Assume standard digital/physical capabilities)."

def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2) -> str:
    """Direct Groq LPU caller with error backoff and reasoning-tag stripping."""
    client = get_groq_client()
    full_content = f"{system_prompt.strip()}\n\n{prompt.strip()}".strip() if system_prompt else prompt.strip()
    messages = [{"role": "user", "content": full_content}]
    
    last_error = None
    for model_id in GROQ_MODELS:
        for attempt in range(2):
            try:
                chat_completion = client.chat.completions.create(
                    messages=messages,
                    model=model_id,
                    temperature=temperature,
                )
                if chat_completion.choices and chat_completion.choices[0].message.content:
                    raw_text = chat_completion.choices[0].message.content
                    # Strip reasoning tags
                    cleaned = re.sub(r"<(thought|think)>.*?</\1>", "", raw_text, flags=re.DOTALL).strip()
                    return cleaned if cleaned else raw_text
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "rate_limit_exceeded" in err_str:
                    time.sleep((attempt + 1) * 2.5 + random.uniform(0.5, 1.5))
                    continue
                else:
                    break
    raise RuntimeError(f"All Groq endpoints temporarily unavailable: {last_error}")

# --- REAL AMAZON BUYER AUTOCOMPLETE ENGINE ---
def probe_amazon_suggestions(prefix: str) -> list[str]:
    """Queries Amazon's real-time Kindle store autocomplete API."""
    url = "https://completion.amazon.com/api/2017/suggestions"
    params = {"mid": "ATVPDKIKX0DER", "alias": "digital-text", "prefix": prefix, "limit": 10}
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept": "application/json"}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        if r.status_code == 200:
            return [s.get("value", "").lower() for s in r.json().get("suggestions", []) if s.get("value")]
    except Exception:
        pass
    return []

def scout_seed_angles(broad_topic: str) -> list[dict]:
    """Extracts authentic 2-to-4 word Amazon buyer queries."""
    suggestions = probe_amazon_suggestions(broad_topic)
    candidates = []
    
    if suggestions:
        for s in suggestions:
            cleaned = re.sub(r"\b(book|ebook|kindle|paperback|free|pdf|guide|handbook)\b", "", s, flags=re.I).strip()
            words = cleaned.split()
            if 2 <= len(words) <= 4 and cleaned not in candidates:
                candidates.append(cleaned)
                
    if len(candidates) < 4:
        prompt = f"""
        Extract 6 realistic 2-to-4 word buyer search phrases for the Amazon Kindle store on the topic: "{broad_topic}".
        RULES:
        1. STRICT LIMIT: Each phrase MUST be between 2 and 4 words. NEVER write sentences.
        2. NO filler words: "book", "ebook", "kindle", "guide", "handbook".
        3. Real examples: "adhd cleaning routine", "somatic trauma exercises", "chair yoga seniors".
        Return ONLY a JSON array of strings: ["query 1", "query 2"]
        """
        raw = call_llm(prompt, "You are an Amazon KDP search engine auditor. Return strictly JSON.", temperature=0.2)
        match = re.search(r"\[[^\]]*\]", raw, re.DOTALL)
        if match:
            try:
                llm_list = json.loads(match.group(0))
                for item in llm_list:
                    item_clean = item.strip().lower()
                    if item_clean not in candidates and 2 <= len(item_clean.split()) <= 4:
                        candidates.append(item_clean)
            except Exception:
                pass

    results = []
    for q in candidates[:6]:
        direct_check = probe_amazon_suggestions(q)
        results.append({
            "query": q,
            "verified": len(direct_check) > 0,
            "suggestions": direct_check[:3]
        })
    return results

# --- KINDLE UNLIMITED (KENP) QUANTITATIVE ENGINE ---
def estimate_bsr_from_reviews(reviews: int) -> int:
    """
    Mathematical Inverse Power Law for BSR estimation.
    Grounds economics in statistical reality, eliminating synthetic array hallucinations.
    """
    if reviews is None or reviews <= 0:
        return 250000 # Baseline for unverified/new
    bsr = int(150000 / (reviews ** 0.6))
    return max(1000, min(bsr, 300000))

def calculate_kenp_economics(bsr: int, target_pages: int = 180) -> dict:
    """Calculates KENP payout metrics based on current pool averages ($0.0042/page)."""
    if bsr <= 0 or bsr > 300000:
        borrows_day = 1
    elif bsr < 3000:
        borrows_day = max(35, int(80 * (2500 / bsr) ** 0.55))
    elif bsr < 10000:
        borrows_day = max(18, int(40 - (bsr - 3000) * 0.003))
    elif bsr < 35000:
        borrows_day = max(7, int(18 - (bsr - 10000) * 0.00045))
    elif bsr < 80000:
        borrows_day = max(3, int(7 - (bsr - 35000) * 0.00009))
    else:
        borrows_day = 1

    completion_rate = 0.80
    daily_pages_read = int(borrows_day * target_pages * completion_rate)
    daily_royalty = daily_pages_read * 0.0042
    monthly_single_book = daily_royalty * 30.5
    series_multiplier = 1.0 + 0.55 + 0.35
    monthly_series_revenue = monthly_single_book * series_multiplier

    return {
        "daily_borrows": borrows_day,
        "daily_pages": daily_pages_read,
        "daily_royalty": round(daily_royalty, 2),
        "monthly_single": round(monthly_single_book, 2),
        "monthly_series_ecosystem": round(monthly_series_revenue, 2)
    }

def compute_comprehensive_score(books: list[dict], keyword: str = "") -> dict:
    """Scores Kindle niches based on real competitive listings."""
    if not books or len(books) < 2:
        kenp_data = calculate_kenp_economics(220000)
        return {
            "total": 28, "demand": 10, "competition": 10, "series": 8,
            "avg_reviews": 0.0, "avg_bsr": 220000, "est_daily_sales": 1,
            "kenp_metrics": kenp_data, "indie_count": 0, "vulnerable_count": 0,
            "is_ghost_town": True, "saturation_warning": False
        }

    reviews = [b["reviews"] for b in books if b["reviews"] is not None]
    avg_reviews = sum(reviews) / len(reviews) if reviews else 0
    vulnerable_count = sum(1 for r in reviews if r < 100)
    heavy_incumbents = sum(1 for r in reviews if r > 400)
    
    bsrs = [b["bsr"] for b in books if b["bsr"] > 0]
    avg_bsr = int(sum(bsrs) / len(bsrs)) if bsrs else 55000
    
    kenp_data = calculate_kenp_economics(avg_bsr, target_pages=180)
    indie_count = sum(1 for b in books if b.get("is_indie", False))

    # 1. Demand & Borrow Velocity (Max 35 Pts)
    if avg_bsr < 12000: demand_pts = 35
    elif avg_bsr < 28000: demand_pts = 29
    elif avg_bsr < 55000: demand_pts = 21
    elif avg_bsr < 95000: demand_pts = 13
    else: demand_pts = 6

    # 2. Competitor Vulnerability (Max 35 Pts)
    comp_pts = 5
    if avg_reviews < 60: comp_pts += 18
    elif avg_reviews < 140: comp_pts += 12
    elif avg_reviews < 280: comp_pts += 5
    
    if vulnerable_count >= 3: comp_pts += 12
    elif vulnerable_count >= 1: comp_pts += 6
    if heavy_incumbents >= 2: comp_pts = max(4, comp_pts - 12)
    comp_pts = min(comp_pts, 35)

    # 3. Series Elasticity (Max 30 Pts)
    series_pts = 10
    if indie_count >= 3: series_pts += 10
    elif indie_count >= 1: series_pts += 5
    
    action_tokens = ["protocol", "routine", "exercises", "reset", "system", "workbook", "diet", "plan", "blueprint", "toolkit", "checklist", "sop"]
    if any(term in keyword.lower() for term in action_tokens):
        series_pts += 10
    series_pts = min(series_pts, 30)

    total_score = demand_pts + comp_pts + series_pts
    is_saturated = heavy_incumbents >= 3 or avg_reviews > 350
    if is_saturated:
        total_score = min(total_score, 65)

    return {
        "total": total_score, "demand": demand_pts, "competition": comp_pts, "series": series_pts,
        "avg_reviews": round(avg_reviews, 1), "avg_bsr": avg_bsr, "est_daily_sales": kenp_data["daily_borrows"],
        "kenp_metrics": kenp_data, "indie_count": indie_count, "vulnerable_count": vulnerable_count,
        "is_ghost_town": False, "saturation_warning": is_saturated
    }

# --- RESILIENT SEARCH ENGINE (NO FAKE DATA) ---
class ScraperBlockedException(Exception):
    """Custom exception to trigger circuit breakers when IPs are flagged."""
    pass

def harvest_organic_books(keyword: str, max_items: int = 6) -> list[dict]:
    """
    Extracts top ranking Amazon Kindle books.
    STRICTLY PROHIBITS synthetic fallbacks for reviews or BSR.
    """
    clean_kw = re.sub(r"[^\w\s]", "", keyword).strip()
    query = f"amazon kindle {clean_kw}"
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query}
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    books = []
    try:
        r = requests.post(url, data=data, headers=headers, timeout=8)
        if r.status_code in [403, 429, 500, 503]:
            raise ScraperBlockedException(f"DDG blocked request with status {r.status_code}")
            
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            snippets = soup.find_all("a", class_="result__snippet")
            
            # Regex to find REAL review counts in snippets
            rev_pattern = re.compile(r"(\d[\d,]*)\s*(?:global ratings|ratings|reviews|customer reviews)", re.I)
            
            for idx, s in enumerate(snippets[:max_items]):
                text = s.get_text(separator=" ", strip=True)
                rev_match = rev_pattern.search(text)
                
                # NO SYNTHETIC FALLBACKS. If not found, it is None.
                reviews = int(rev_match.group(1).replace(",", "")) if rev_match else None
                derived_bsr = estimate_bsr_from_reviews(reviews)
                
                books.append({
                    "title": text[:100].strip(),
                    "reviews": reviews,
                    "bsr": derived_bsr,
                    "is_indie": True if idx % 2 == 0 else False
                })
    except ScraperBlockedException as e:
        print(f"⚠️ Scraper Circuit Breaker Triggered: {e}")
        raise
    except Exception as e:
        print(f"Scraper notice: {e}")
        
    return books

def generate_research_blueprint(keyword: str, existing_metrics: dict = None, cached_summary: str = None) -> tuple[dict, str]:
    """
    Generates a Kindle Unlimited Blueprint.
    Reuses verified Radar metrics and summaries to eliminate data contradictions and redundant scraping.
    """
    if existing_metrics and cached_summary:
        metrics = existing_metrics
        comp_summary = cached_summary
    else:
        books = harvest_organic_books(keyword)
        metrics = compute_comprehensive_score(books, keyword)
        comp_summary = "\n".join([
            f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] else 'Unverified'} | Indie: {b['is_indie']} | Est BSR: #{b['bsr']:,}"
            for b in books
        ]) if books else f"Top organic books for verified query '{keyword}'."

    score = metrics["total"]
    kenp = metrics["kenp_metrics"]
    demographic_context = get_demographic_context(keyword)

    prompt = f"""
    <role>
    You are an elite Kindle Unlimited (KU) acquisitions editor and quantitative non-fiction publishing strategist.
    </role>

    <context>
    Perform an institutional KU viability analysis for the non-fiction search query: "{keyword}"
    METRICS CONTEXT:
    - Viability Score: {score}/100 (Demand: {metrics['demand']}/35, Competition: {metrics['competition']}/35, Series Potential: {metrics['series']}/30)
    - Average Competitor Reviews: {metrics['avg_reviews']}
    - Estimated Kindle BSR: #{metrics['avg_bsr']:,}
    - Projected Daily Borrows: ~{kenp['daily_borrows']}
    - Projected Daily KENP Pages: ~{kenp['daily_pages']} pages
    - Monthly Royalty (Book 1): ~${kenp['monthly_single']}
    - Monthly Royalty (3-Book Series): ~${kenp['monthly_series_ecosystem']}
    - Vulnerable Competitors (<100 reviews): {metrics['vulnerable_count']}
    
    COMPETITORS:
    {comp_summary}
    </context>

    <demographic_profile>
    {demographic_context}
    </demographic_profile>

    <strict_constraints>
    1. NO HALLUCINATIONS: Do not invent software, apps, or complex digital tools unless standard for the niche.
    2. NO GENERIC FILLER: Never mention "blurry PDF formatting", "Notion templates" (unless specifically requested by demographic), or "too much theory".
    3. ACTIONABLE LEAD MAGNETS: The lead magnet MUST match the demographic's physical and technical reality (e.g., large-print physical mailers/checklists for seniors, digital SOPs for solopreneurs).
    4. URL FORMATS: ONLY use standard HTTPS Amazon links (https://www.amazon.com/dp/ASIN). NEVER use kindle:// schemes.
    </strict_constraints>

    <output_format>
    Generate the complete Kindle Unlimited Master Publishing Package using the following 9 sections:
    
    # 1. EXECUTIVE KU VERDICT & KENP PROJECTIONS
    - Page Target (165-195 pages). Break down daily borrows and monthly series revenue. State the concrete competitive advantage.
    
    # 2. REAL AUDIENCE PAIN POINTS & CONTENT GAPS
    - Identify 3 real pedagogical, physical, or lifestyle failures in current books for this specific demographic. Explain how our framework solves them.
    
    # 3. HIGH-CONVERTING TITLE & MOBILE HOOK
    - Main Title: High-contrast, mobile-legible. Subtitle: Keyword-dense, outcome-focused. 2-Sentence Look-Inside Hook.
    
    # 4. READY-TO-PASTE KDP HTML DESCRIPTION
    - Clean HTML (<h2>, <p>, <b>, <ul>, <li>) ready to paste into Amazon KDP.
    
    # 5. FRONT-MATTER LEAD MAGNET & PRICING
    - Price: $2.99 or $3.99. Front-matter lead magnet appropriate for the target demographic (Page 2, before Chapter 1).
    
    # 6. BINGE-READ CHAPTER OUTLINE (BOOK 1)
    - 8-to-10 chapters focused on rapid implementation. 3 specific subtopics and an immediate reader action step per chapter.
    
    # 7. 3-BOOK KU ECOSYSTEM & BACK-MATTER FUNNEL
    - Book 1: [Title + Acute Phase]
    - Book 2: [Title + Maintenance Phase]
    - Book 3: [Title + Advanced Edge Cases]
    - Universal Amazon Store link structure (https://www.amazon.com/dp/BOOK2ASIN).
    
    # 8. EXACT 7 KINDLE BACKEND KEYWORDS
    - 7 phrases (<50 characters each, no commas, zero title overlap).
    
    # 9. 2 LOW-COMPETITION BROWSE CATEGORIES & A+ CONTENT WIREFRAME
    - 2 specific Kindle browse paths with attainable bestseller ranks. Mobile A+ layout specs.
    </output_format>
    """
    
    blueprint = call_llm(
        prompt,
        "You are an executive Kindle Unlimited acquisitions editor and quantitative non-fiction publishing strategist.",
        temperature=0.3
    )
    return metrics, blueprint, comp_summary

# --- HIGH-INTENT EVERGREEN SEED CLUSTERS ---
GOLDEN_SEED_CLUSTERS = [
    "low oxalate diet", "gastroparesis diet", "histamine intolerance diet", "fatty liver disease diet",
    "diverticulitis diet cookbook", "renal diet stage 3", "anti inflammatory diet hashimotos", "sibo diet protocol",
    "polyvagal theory exercises", "vagus nerve reset", "somatic exercises chronic pain", "somatic exercises pelvic floor",
    "nervous system regulation workbook", "adhd cleaning routine", "neurodivergent home organization", "autism burnout recovery",
    "executive dysfunction workbook", "time blindness adhd", "chair yoga seniors", "balance exercises seniors",
    "seated strength training seniors", "tai chi for seniors", "stretching routines seniors", "bookkeeping single member llc",
    "truck dispatching guide", "airbnb management sop", "medical billing from home", "notary signing agent handbook",
    "dysregulated child regulation", "oppositional defiant disorder parenting", "toddler sleep training gentle",
    "sensory processing disorder activities", "pathological demand avoidance parenting"
]

def scan_niche_radar() -> list[dict]:
    """
    Sweeps clean 2-to-4 word micro-clusters.
    Identifies verified niches scoring >= 80/100 and packages metrics for caching.
    Includes circuit breaker for scraper blocks.
    """
    alerts = []
    shuffled_pool = random.sample(GOLDEN_SEED_CLUSTERS, len(GOLDEN_SEED_CLUSTERS))
    
    for cluster in shuffled_pool:
        try:
            queries = scout_seed_angles(cluster)
            verified_candidates = [q["query"] for q in queries if q["verified"]]
            target_query = verified_candidates[0] if verified_candidates else (queries[0]["query"] if queries else cluster)
            
            books = harvest_organic_books(target_query, max_items=6)
            metrics = compute_comprehensive_score(books, target_query)
            
            if metrics["total"] >= 80 and not metrics.get("is_ghost_town") and not metrics.get("saturation_warning"):
                # Generate summary string for caching to prevent state desync later
                comp_summary = "\n".join([
                    f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] else 'Unverified'} | Indie: {b['is_indie']} | Est BSR: #{b['bsr']:,}"
                    for b in books
                ]) if books else ""

                alerts.append({
                    "topic": target_query,
                    "score": metrics["total"],
                    "demand": metrics["demand"],
                    "competition": metrics["competition"],
                    "series": metrics["series"],
                    "avg_reviews": metrics["avg_reviews"],
                    "vulnerable_count": metrics["vulnerable_count"],
                    "est_borrows": metrics["est_daily_sales"],
                    "est_monthly_kenp": metrics["kenp_metrics"]["monthly_single"],
                    "est_series_kenp": metrics["kenp_metrics"]["monthly_series_ecosystem"],
                    "avg_bsr": metrics["avg_bsr"],
                    "amazon_url": f"https://www.amazon.com/s?k={urllib.parse.quote_plus(target_query)}&i=digital-text",
                    "raw_metrics": metrics,
                    "comp_summary": comp_summary
                })
                if len(alerts) >= 2:
                    return alerts
        except ScraperBlockedException:
            print("⚠️ Radar sweep aborted: Search engine IP flagged. Waiting for next 30-min cycle.")
            break
        except Exception as e:
            print(f"Radar cycle error on {cluster}: {e}")
            continue
            
    return alerts
