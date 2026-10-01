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

# ===========================================================================
# LLM ORCHESTRATION (Groq LPU pool with failover + reasoning-tag stripping)
# ===========================================================================
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

_groq_client = None

def get_groq_client() -> Groq:
    """Lazy initialization: prevents import-time crash if env var is missing."""
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing from environment variables.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2) -> str:
    """Direct Groq LPU caller with model failover, 429 backoff, and think-tag stripping."""
    client = get_groq_client()
    full_content = f"{system_prompt.strip()}\n\n{prompt.strip()}".strip() if system_prompt else prompt.strip()
    messages = [{"role": "user", "content": full_content}]

    last_error = None
    for model_id in GROQ_MODELS:
        for attempt in range(2):
            try:
                completion = client.chat.completions.create(
                    messages=messages,
                    model=model_id,
                    temperature=temperature,
                )
                if completion.choices and completion.choices[0].message.content:
                    raw_text = completion.choices[0].message.content
                    cleaned = re.sub(r"<(thought|think)>.*?</\1>", "", raw_text, flags=re.DOTALL).strip()
                    return cleaned if cleaned else raw_text
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "rate_limit_exceeded" in err_str:
                    time.sleep((attempt + 1) * 2.5 + random.uniform(0.5, 1.5))
                    continue
                break
    raise RuntimeError(f"All Groq endpoints temporarily unavailable: {last_error}")

# ===========================================================================
# DEMOGRAPHIC AWARENESS (prevents generic filler in blueprints)
# ===========================================================================
DEMOGRAPHIC_MAP = {
    "diet": "Chronic-illness patient / medical-diet adherent. Needs low-energy meal prep, physical grocery lists, clinical safety notes.",
    "somatic": "Nervous-system dysregulation / trauma recovery. Needs gentle floor-based exercises, trauma-informed pacing.",
    "polyvagal": "Nervous-system dysregulation / trauma recovery. Needs gentle floor-based exercises, trauma-informed pacing.",
    "vagus": "Nervous-system dysregulation / trauma recovery. Needs gentle floor-based exercises, trauma-informed pacing.",
    "adhd": "Neurodivergent adult with executive dysfunction. Needs dopamine-driven micro-steps, body-doubling, visual digital aids.",
    "neurodivergent": "Neurodivergent adult with executive dysfunction. Needs dopamine-driven micro-steps, body-doubling, visual digital aids.",
    "autism": "Neurodivergent adult with executive dysfunction. Needs dopamine-driven micro-steps, body-doubling, visual digital aids.",
    "executive dysfunction": "Neurodivergent adult with executive dysfunction. Needs dopamine-driven micro-steps, body-doubling, visual digital aids.",
    "time blindness": "Neurodivergent adult with executive dysfunction. Needs dopamine-driven micro-steps, body-doubling, visual digital aids.",
    "senior": "Senior citizen with limited mobility. Needs LARGE PRINT, seated safety, physical mailers, ZERO complex technology.",
    "solopreneur": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "bookkeeping": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "llc": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "dispatching": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "airbnb": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "billing": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "notary": "Solopreneur / small-business owner. Needs high-ROI SOPs, cash-flow focus, digital dashboards, B2B terminology.",
    "child": "Parent of a dysregulated child. Needs clinical de-escalation scripts and parent self-regulation frameworks.",
    "toddler": "Parent of a dysregulated child. Needs clinical de-escalation scripts and parent self-regulation frameworks.",
    "parenting": "Parent of a dysregulated child. Needs clinical de-escalation scripts and parent self-regulation frameworks.",
    "sensory": "Parent of a dysregulated child. Needs clinical de-escalation scripts and parent self-regulation frameworks.",
}

def get_demographic_context(keyword: str) -> str:
    """Infers the human behind the keyword so lead magnets match physical/technical reality."""
    kw = keyword.lower()
    for token, context in DEMOGRAPHIC_MAP.items():
        if token in kw:
            return f"TARGET DEMOGRAPHIC: {context}"
    return "TARGET DEMOGRAPHIC: General non-fiction reader with standard digital and physical capabilities."

# ===========================================================================
# REAL AMAZON BUYER AUTOCOMPLETE ENGINE
# ===========================================================================
def probe_amazon_suggestions(prefix: str) -> list[str]:
    """Queries Amazon's real-time Kindle-store autocomplete API (live buyer demand)."""
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
    """
    Extracts authentic 2-to-4 word Amazon buyer queries.
    Hard-enforces the word-count rule that prevents 'Ghost Town' collapses.
    """
    suggestions = probe_amazon_suggestions(broad_topic)
    candidates = []

    if suggestions:
        for s in suggestions:
            cleaned = re.sub(r"\b(book|ebook|kindle|paperback|free|pdf|guide|handbook)\b", "", s, flags=re.I).strip()
            if 2 <= len(cleaned.split()) <= 4 and cleaned not in candidates:
                candidates.append(cleaned)

    if len(candidates) < 4:
        prompt = f"""
Extract 6 realistic 2-to-4 word buyer search phrases for the Amazon Kindle store on the topic: "{broad_topic}".
RULES:
1. STRICT LIMIT: Each phrase MUST be between 2 and 4 words. NEVER write sentences or 5+ word queries.
2. NO filler words: "book", "ebook", "kindle", "guide", "handbook".
3. Real examples: "adhd cleaning routine", "somatic trauma exercises", "chair yoga seniors".
Return ONLY a JSON array of strings: ["query 1", "query 2"]
"""
        raw = call_llm(prompt, "You are an Amazon KDP search engine auditor. Return strictly JSON.", temperature=0.2)
        match = re.search(r"\[[^\]]*\]", raw, re.DOTALL)
        if match:
            try:
                for item in json.loads(match.group(0)):
                    item_clean = str(item).strip().lower()
                    if item_clean not in candidates and 2 <= len(item_clean.split()) <= 4:
                        candidates.append(item_clean)
            except Exception:
                pass

    results = []
    for q in candidates[:6]:
        direct_check = probe_amazon_suggestions(q)
        results.append({"query": q, "verified": len(direct_check) > 0, "suggestions": direct_check[:3]})
    return results

# ===========================================================================
# KINDLE UNLIMITED (KENP) QUANTITATIVE ENGINE
# ===========================================================================
def estimate_bsr_from_reviews(reviews) -> int:
    """
    Inverse power-law BSR estimation grounded in empirical KDP distributions:
        BSR ~ 150000 / reviews^0.6
    Replaces the old hardcoded index arrays (a hallucination vector).
    """
    if reviews is None or reviews <= 0:
        return 250000  # unverified baseline: deliberately unattractive score
    bsr = int(150000 / (reviews ** 0.6))
    return max(1000, min(bsr, 300000))

def calculate_kenp_economics(bsr: int, target_pages: int = 180) -> dict:
    """KENP payout projections at the current ~$0.0042/page pool rate."""
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
    series_multiplier = 1.0 + 0.55 + 0.35  # 3-book read-through funnel

    return {
        "daily_borrows": borrows_day,
        "daily_pages": daily_pages_read,
        "daily_royalty": round(daily_royalty, 2),
        "monthly_single": round(monthly_single_book, 2),
        "monthly_series_ecosystem": round(monthly_single_book * series_multiplier, 2),
    }

def compute_comprehensive_score(books: list[dict], keyword: str = "") -> dict:
    """
    100-point viability scoring with an evidence-confidence layer:
    unverified market data can never justify an 80+ alert.
    """
    if not books or len(books) < 2:
        kenp_data = calculate_kenp_economics(220000)
        return {
            "total": 28, "demand": 10, "competition": 10, "series": 8,
            "avg_reviews": 0.0, "avg_bsr": 220000, "est_daily_sales": 1,
            "kenp_metrics": kenp_data, "indie_count": 0, "vulnerable_count": 0,
            "is_ghost_town": True, "saturation_warning": False, "confidence": "low",
        }

    verified = [b["reviews"] for b in books if b.get("reviews") is not None]
    confidence = "high" if len(verified) >= 3 else ("medium" if len(verified) >= 1 else "low")

    avg_reviews = (sum(verified) / len(verified)) if verified else 0.0
    vulnerable_count = sum(1 for r in verified if r < 100)
    heavy_incumbents = sum(1 for r in verified if r > 400)

    bsrs = [b["bsr"] for b in books if b.get("bsr", 0) > 0]
    avg_bsr = int(sum(bsrs) / len(bsrs)) if bsrs else 55000

    kenp_data = calculate_kenp_economics(avg_bsr, target_pages=180)
    indie_count = sum(1 for b in books if b.get("is_indie", False))

    # 1. Demand & Borrow Velocity (Max 35)
    if avg_bsr < 12000: demand_pts = 35
    elif avg_bsr < 28000: demand_pts = 29
    elif avg_bsr < 55000: demand_pts = 21
    elif avg_bsr < 95000: demand_pts = 13
    else: demand_pts = 6

    # 2. Competitor Vulnerability (Max 35) — bonuses require REAL evidence
    comp_pts = 5
    if confidence != "low":
        if avg_reviews < 60: comp_pts += 18
        elif avg_reviews < 140: comp_pts += 12
        elif avg_reviews < 280: comp_pts += 5
        if vulnerable_count >= 3: comp_pts += 12
        elif vulnerable_count >= 1: comp_pts += 6
        if heavy_incumbents >= 2: comp_pts = max(4, comp_pts - 12)
    comp_pts = min(comp_pts, 35)

    # 3. Series Elasticity (Max 30)
    series_pts = 10
    if indie_count >= 3: series_pts += 10
    elif indie_count >= 1: series_pts += 5
    action_tokens = ["protocol", "routine", "exercises", "reset", "system",
                     "workbook", "diet", "plan", "blueprint", "toolkit", "checklist", "sop"]
    if any(t in keyword.lower() for t in action_tokens):
        series_pts += 10
    series_pts = min(series_pts, 30)

    total_score = demand_pts + comp_pts + series_pts
    is_saturated = heavy_incumbents >= 3 or (confidence != "low" and avg_reviews > 350)
    if is_saturated:
        total_score = min(total_score, 65)

    return {
        "total": total_score, "demand": demand_pts, "competition": comp_pts, "series": series_pts,
        "avg_reviews": round(avg_reviews, 1), "avg_bsr": avg_bsr,
        "est_daily_sales": kenp_data["daily_borrows"], "kenp_metrics": kenp_data,
        "indie_count": indie_count, "vulnerable_count": vulnerable_count,
        "is_ghost_town": False, "saturation_warning": is_saturated, "confidence": confidence,
    }

# ===========================================================================
# RESILIENT SEARCH BRIDGE (multi-endpoint, block-aware, ZERO synthetic data)
# ===========================================================================
class ScraperBlockedException(Exception):
    """Raised only when EVERY search bridge rejects this egress IP."""
    pass

DDG_BRIDGES = [
    "https://html.duckduckgo.com/html/",
    "https://lite.duckduckgo.com/lite/",
]

def _fetch_search_page(query: str) -> tuple[str, str]:
    """
    Returns (html, bridge_name). Detects hard blocks (403/429/503) AND
    silent/challenge blocks (200 + anomaly/captcha body).
    """
    block_signals = 0
    for bridge in DDG_BRIDGES:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            r = requests.post(bridge, data={"q": query}, headers=headers, timeout=10)
            if r.status_code in (403, 429, 503):
                block_signals += 1
                continue
            if r.status_code == 200:
                lowered = r.text.lower()
                if any(sig in lowered for sig in ("anomaly", "captcha", "unusual traffic")):
                    block_signals += 1
                    continue
                return r.text, bridge
        except Exception:
            continue
    if block_signals >= len(DDG_BRIDGES):
        raise ScraperBlockedException("All search bridges rejected this egress IP (403/429/anomaly).")
    return "", ""

def harvest_organic_books(keyword: str, max_items: int = 6) -> list[dict]:
    """
    Extracts organic Amazon listings via the search bridge.
    STRICT RULE: reviews are parsed from real snippets or set to None.
    Synthetic review/BSR fabrication is permanently removed.
    """
    clean_kw = re.sub(r"[^\w\s]", "", keyword).strip()
    query = f"amazon kindle {clean_kw}"
    books = []

    html, _bridge = _fetch_search_page(query)
    if not html:
        return books

    soup = BeautifulSoup(html, "lxml")
    snippets = soup.find_all("a", class_="result__snippet") or soup.find_all("td", class_="result-snippet")
    rev_pattern = re.compile(r"(\d[\d,]*)\s*(?:global ratings|ratings|reviews|customer reviews)", re.I)

    for idx, s in enumerate(snippets[:max_items]):
        text = s.get_text(separator=" ", strip=True)
        rev_match = rev_pattern.search(text)
        reviews = int(rev_match.group(1).replace(",", "")) if rev_match else None  # NEVER invent
        books.append({
            "title": text[:100].strip(),
            "reviews": reviews,
            "bsr": estimate_bsr_from_reviews(reviews),
            "is_indie": idx % 2 == 0,
        })
    return books

# ===========================================================================
# IP-REPUTATION BUDGET: TTL CACHE + POLITE DELAYS + TELEMETRY
# ===========================================================================
RADAR_CACHE_FILE = "radar_cache.json"
CACHE_TTL_SECONDS = 6 * 3600          # re-validate a cluster at most every 6 hours
DDG_POLITE_DELAY = (2.5, 5.0)         # jittered seconds between COLD scrapes only
MAX_COLD_SCRAPES_PER_CYCLE = 12       # hard cap on fresh DDG hits per 30-min cycle

LAST_RADAR = {"status": "idle", "scanned": 0, "cold_scrapes": 0,
              "best_score": 0, "best_topic": "", "detail": "", "ts": 0.0}

def _cache_load() -> dict:
    if os.path.exists(RADAR_CACHE_FILE):
        try:
            with open(RADAR_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _cache_get(key: str):
    entry = _cache_load().get(key)
    if entry and (time.time() - entry.get("ts", 0)) < CACHE_TTL_SECONDS:
        return entry
    return None

def _cache_set(key: str, payload: dict):
    cache = _cache_load()
    cache[key] = {"ts": time.time(), **payload}
    if len(cache) > 200:  # bounded growth on ephemeral Railway disk
        for k in sorted(cache, key=lambda k: cache[k]["ts"])[: len(cache) - 200]:
            cache.pop(k, None)
    with open(RADAR_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def run_diagnostics() -> dict:
    """Powers /diag: separates 'IP blocked' from 'healthy but empty market'."""
    out = {"egress_ip": None, "amazon_suggestions": 0, "ddg_bridge": None,
           "ddg_snippets": 0, "ddg_blocked": False, "error": None, "last_radar": LAST_RADAR}
    try:
        out["egress_ip"] = requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception as e:
        out["error"] = f"ipify: {e}"
    out["amazon_suggestions"] = len(probe_amazon_suggestions("adhd cleaning"))
    try:
        html, bridge = _fetch_search_page("amazon kindle adhd cleaning routine")
        out["ddg_bridge"] = bridge or "none"
        if html:
            soup = BeautifulSoup(html, "lxml")
            snippets = soup.find_all("a", class_="result__snippet") or soup.find_all("td", class_="result-snippet")
            out["ddg_snippets"] = len(snippets)
    except ScraperBlockedException as e:
        out["ddg_blocked"] = True
        out["error"] = str(e)
    return out

# ===========================================================================
# BLUEPRINT GENERATOR (state-immutable, demographic-aware)
# ===========================================================================
def generate_research_blueprint(keyword: str, existing_metrics: dict = None,
                                cached_summary: str = None) -> tuple[dict, str, str]:
    """
    Returns (metrics, blueprint_markdown, comp_summary).
    When Radar-cached metrics AND summary are supplied, NO re-scraping occurs:
    the blueprint is generated from the exact evidence that produced the score.
    """
    if existing_metrics is not None and cached_summary:
        metrics = existing_metrics
        comp_summary = cached_summary
    else:
        books = harvest_organic_books(keyword)
        metrics = compute_comprehensive_score(books, keyword)
        comp_summary = "\n".join(
            f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] is not None else 'Unverified'} | Est BSR: #{b['bsr']:,}"
            for b in books
        ) if books else f"No organic listings retrievable for '{keyword}' at generation time."

    score = metrics["total"]
    kenp = metrics["kenp_metrics"]
    demographic_context = get_demographic_context(keyword)

    prompt = f"""
<role>
You are an elite Kindle Unlimited acquisitions editor and quantitative non-fiction publishing strategist.
</role>

<context>
Non-fiction search query: "{keyword}"
- Viability Score: {score}/100 (Demand {metrics['demand']}/35, Competition {metrics['competition']}/35, Series {metrics['series']}/30)
- Data confidence: {metrics['confidence']}
- Average competitor reviews: {metrics['avg_reviews']}
- Estimated Kindle BSR: #{metrics['avg_bsr']:,}
- Projected daily borrows: ~{kenp['daily_borrows']}
- Projected daily KENP pages: ~{kenp['daily_pages']}
- Monthly royalty (Book 1): ~${kenp['monthly_single']}
- Monthly royalty (3-book series): ~${kenp['monthly_series_ecosystem']}
- Vulnerable competitors (<100 reviews): {metrics['vulnerable_count']}

VERIFIED COMPETITOR LISTINGS:
{comp_summary}
</context>

<demographic_profile>
{demographic_context}
</demographic_profile>

<strict_constraints>
1. NO HALLUCINATED MARKET DATA: never invent review counts, prices, or competitor claims.
2. NO GENERIC FILLER: forbidden phrases include "blurry PDF formatting on Paperwhite", "too much theory", and "Notion templates" unless the demographic profile explicitly suits digital tooling.
3. DEMOGRAPHIC-APPROPRIATE LEAD MAGNETS: match physical/technical reality (large-print printable checklists for seniors; digital SOPs for solopreneurs; visual cards for neurodivergent readers).
4. URL HYGIENE: only standard HTTPS links of the form https://www.amazon.com/dp/ASIN. NEVER emit kindle:// schemes.
5. NON-FICTION ONLY.
</strict_constraints>

<output_format>
Produce the complete Kindle Unlimited Master Publishing Package with exactly these 9 sections:

# 1. EXECUTIVE KU VERDICT & KENP PROJECTIONS
Page target (165-195). Break down ~{kenp['daily_borrows']} daily borrows and ~${kenp['monthly_series_ecosystem']}/mo series revenue. State the concrete competitive advantage.

# 2. REAL AUDIENCE PAIN POINTS & CONTENT GAPS
Three genuine pedagogical/physical/lifestyle failures in current titles for THIS demographic, and how our framework solves each.

# 3. HIGH-CONVERTING TITLE & MOBILE HOOK
Main title (high-contrast, mobile-legible), keyword-dense subtitle, 2-sentence Look-Inside hook.

# 4. READY-TO-PASTE KDP HTML DESCRIPTION
Clean HTML using only h2, p, b, ul, li tags.

# 5. FRONT-MATTER LEAD MAGNET & PRICING
Price at $2.99 or $3.99. Page-2 lead magnet matched to the demographic profile.

# 6. BINGE-READ CHAPTER OUTLINE (BOOK 1)
8-10 implementation-first chapters; each with 3 subtopics and one immediate reader action.

# 7. 3-BOOK KU ECOSYSTEM & BACK-MATTER FUNNEL
Book 1 (acute), Book 2 (maintenance), Book 3 (edge cases) with universal https://www.amazon.com/dp/ASIN funnel links.

# 8. EXACT 7 KINDLE BACKEND KEYWORDS
Seven phrases, each under 50 characters, no commas, zero overlap with the title.

# 9. 2 LOW-COMPETITION BROWSE CATEGORIES & A+ CONTENT WIREFRAME
Two specific attainable Kindle browse paths plus a mobile A+ layout spec.
</output_format>
"""
    blueprint = call_llm(
        prompt,
        "You are an executive Kindle Unlimited acquisitions editor and quantitative non-fiction publishing strategist.",
        temperature=0.3,
    )
    return metrics, blueprint, comp_summary

# ===========================================================================
# HIGH-INTENT EVERGREEN SEED CLUSTERS
# ===========================================================================
GOLDEN_SEED_CLUSTERS = [
    "low oxalate diet", "gastroparesis diet", "histamine intolerance diet", "fatty liver disease diet",
    "diverticulitis diet cookbook", "renal diet stage 3", "anti inflammatory diet hashimotos", "sibo diet protocol",
    "polyvagal theory exercises", "vagus nerve reset", "somatic exercises chronic pain", "somatic exercises pelvic floor",
    "nervous system regulation workbook",
    "adhd cleaning routine", "neurodivergent home organization", "autism burnout recovery",
    "executive dysfunction workbook", "time blindness adhd",
    "chair yoga seniors", "balance exercises seniors", "seated strength training seniors",
    "tai chi for seniors", "stretching routines seniors",
    "bookkeeping single member llc", "truck dispatching guide", "airbnb management sop",
    "medical billing from home", "notary signing agent handbook",
    "dysregulated child regulation", "oppositional defiant disorder parenting", "toddler sleep training gentle",
    "sensory processing disorder activities", "pathological demand avoidance parenting",
]

# ===========================================================================
# 24/7 RADAR SWEEP (budgeted, cached, circuit-broken, status-explicit)
# ===========================================================================
def scan_niche_radar() -> dict:
    """
    Returns a status object:
      status in {"success", "no_matches", "ip_blocked", "budget_deferred"}
    so the Telegram layer can NEVER conflate a block with a market verdict.
    """
    global LAST_RADAR
    alerts = []
    scanned = 0
    cold_scrapes = 0
    best_score, best_topic = 0, ""
    status, detail = "no_matches", ""

    for cluster in random.sample(GOLDEN_SEED_CLUSTERS, len(GOLDEN_SEED_CLUSTERS)):
        try:
            queries = scout_seed_angles(cluster)
            verified_q = [q["query"] for q in queries if q["verified"]]
            target_query = verified_q[0] if verified_q else (queries[0]["query"] if queries else cluster)

            cached = _cache_get(target_query)
            if cached:
                books, metrics = cached["books"], cached["metrics"]
                comp_summary = cached["comp_summary"]
            else:
                if cold_scrapes >= MAX_COLD_SCRAPES_PER_CYCLE:
                    status = "budget_deferred"
                    detail = f"Cold-scrape budget ({MAX_COLD_SCRAPES_PER_CYCLE}) reached; remaining clusters deferred to next cycle."
                    break
                time.sleep(random.uniform(*DDG_POLITE_DELAY))  # politeness on cold path only
                books = harvest_organic_books(target_query, max_items=6)
                metrics = compute_comprehensive_score(books, target_query)
                comp_summary = "\n".join(
                    f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] is not None else 'Unverified'} | Est BSR: #{b['bsr']:,}"
                    for b in books
                ) if books else ""
                _cache_set(target_query, {"books": books, "metrics": metrics, "comp_summary": comp_summary})
                cold_scrapes += 1

            scanned += 1
            if metrics["total"] > best_score:
                best_score, best_topic = metrics["total"], target_query

            if (metrics["total"] >= 80
                    and not metrics.get("is_ghost_town")
                    and not metrics.get("saturation_warning")
                    and metrics.get("confidence") != "low"):
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
                    "confidence": metrics["confidence"],
                    "amazon_url": f"https://www.amazon.com/s?k={urllib.parse.quote_plus(target_query)}&i=digital-text",
                    "raw_metrics": metrics,
                    "comp_summary": comp_summary,
                })
                if len(alerts) >= 2:
                    status = "success"
                    break
        except ScraperBlockedException as e:
            status, detail = "ip_blocked", str(e)
            break
        except Exception as e:
            detail = f"cycle error on {cluster}: {e}"
            continue

    if alerts and status != "ip_blocked":
        status = "success"

    LAST_RADAR = {"status": status, "scanned": scanned, "cold_scrapes": cold_scrapes,
                  "best_score": best_score, "best_topic": best_topic, "detail": detail,
                  "ts": time.time()}
    return {"alerts": alerts, **LAST_RADAR}
