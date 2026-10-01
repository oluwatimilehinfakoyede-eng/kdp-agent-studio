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
# LLM ORCHESTRATION (Groq LPU pool, fail-fast, bounded worst case)
# ===========================================================================
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

_groq_client = None

def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing from environment variables.")
        _groq_client = Groq(api_key=api_key, timeout=30.0, max_retries=0)
    return _groq_client

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2) -> str:
    client = get_groq_client()
    full_content = f"{system_prompt.strip()}\n\n{prompt.strip()}".strip() if system_prompt else prompt.strip()
    messages = [{"role": "user", "content": full_content}]

    last_error = None
    for model_id in GROQ_MODELS:
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
            if "429" in str(e) or "rate_limit_exceeded" in str(e):
                time.sleep(2.0 + random.uniform(0.3, 1.0))
            continue
    raise RuntimeError(f"All Groq endpoints temporarily unavailable: {last_error}")

# ===========================================================================
# DEMOGRAPHIC AWARENESS
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
    kw = keyword.lower()
    for token, context in DEMOGRAPHIC_MAP.items():
        if token in kw:
            return f"TARGET DEMOGRAPHIC: {context}"
    return "TARGET DEMOGRAPHIC: General non-fiction reader with standard digital and physical capabilities."

# ===========================================================================
# AMAZON BUYER AUTOCOMPLETE ENGINE
# ===========================================================================
def probe_amazon_suggestions(prefix: str) -> list[str]:
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
# KENP QUANTITATIVE ENGINE
# ===========================================================================
def estimate_bsr_from_reviews(reviews) -> int:
    if reviews is None or reviews <= 0:
        return 250000
    bsr = int(150000 / (reviews ** 0.6))
    return max(1000, min(bsr, 300000))

def calculate_kenp_economics(bsr: int, target_pages: int = 180) -> dict:
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

    return {
        "daily_borrows": borrows_day,
        "daily_pages": daily_pages_read,
        "daily_royalty": round(daily_royalty, 2),
        "monthly_single": round(monthly_single_book, 2),
        "monthly_series_ecosystem": round(monthly_single_book * series_multiplier, 2),
    }

def compute_comprehensive_score(books: list[dict], keyword: str = "", demand_verified: bool = False) -> dict:
    if not books or len(books) < 2:
        kenp_data = calculate_kenp_economics(220000)
        return {
            "total": 28, "demand": 10, "competition": 10, "series": 8,
            "avg_reviews": 0.0, "avg_bsr": 220000, "est_daily_sales": 1,
            "kenp_metrics": kenp_data, "verified_count": 0, "vulnerable_count": 0,
            "is_ghost_town": True, "saturation_warning": False, "confidence": "low",
        }

    verified_books = [b for b in books if b.get("reviews") is not None]
    verified = [b["reviews"] for b in verified_books]
    confidence = "high" if len(verified) >= 3 else ("medium" if len(verified) >= 1 else "low")

    avg_reviews = (sum(verified) / len(verified)) if verified else 0.0
    vulnerable_count = sum(1 for r in verified if r < 100)
    heavy_incumbents = sum(1 for r in verified if r > 400)

    bsrs = [b["bsr"] for b in verified_books if b.get("bsr", 0) > 0]
    avg_bsr = int(sum(bsrs) / len(bsrs)) if bsrs else 250000

    kenp_data = calculate_kenp_economics(avg_bsr, target_pages=180)

    if avg_bsr < 12000: demand_pts = 35
    elif avg_bsr < 28000: demand_pts = 29
    elif avg_bsr < 55000: demand_pts = 21
    elif avg_bsr < 95000: demand_pts = 13
    else: demand_pts = 6

    comp_pts = 5
    if confidence != "low":
        if avg_reviews < 60: comp_pts += 18
        elif avg_reviews < 140: comp_pts += 12
        elif avg_reviews < 280: comp_pts += 5
        if vulnerable_count >= 3: comp_pts += 12
        elif vulnerable_count >= 1: comp_pts += 6
        if heavy_incumbents >= 2: comp_pts = max(4, comp_pts - 12)
    comp_pts = min(comp_pts, 35)

    series_pts = 10
    action_tokens = ["protocol", "routine", "exercises", "reset", "system",
                     "workbook", "diet", "plan", "blueprint", "toolkit", "checklist", "sop"]
    if any(t in keyword.lower() for t in action_tokens):
        series_pts += 10
    if demand_verified:
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
        "verified_count": len(verified), "vulnerable_count": vulnerable_count,
        "is_ghost_town": False, "saturation_warning": is_saturated, "confidence": confidence,
    }

# ===========================================================================
# SEARCH BRIDGES (block-aware)
# ===========================================================================
class ScraperBlockedException(Exception):
    pass

DDG_BRIDGES = [
    "https://html.duckduckgo.com/html/",
    "https://lite.duckduckgo.com/lite/",
]

def _fetch_search_page(query: str) -> tuple[str, str]:
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

# ===========================================================================
# LAYOUT-AGNOSTIC RESULT PARSING + MULTI-PROXY PRODUCT EVIDENCE
# ===========================================================================
ASIN_PATTERN = re.compile(r"(?:/dp/|/gp/product/|/exec/obidos/ASIN/)([A-Z0-9]{10})")
REV_PATTERN = re.compile(r"(\d[\d,]*)\s*(?:global ratings|ratings|reviews|customer reviews)", re.I)
REV_PATTERNS = [
    re.compile(r"([\d,]+)\s*(?:global\s+)?ratings", re.I),
    re.compile(r"([\d,]+)\s*customer\s+reviews", re.I),
    re.compile(r"([\d,]+)\s*reviews\b", re.I),
]
BSR_PATTERNS = [
    re.compile(r"Best\s+Sellers\s+Rank[^#0-9]*#?([\d,]+)", re.I | re.S),
    re.compile(r"#([\d,]+)\s+in\s+(?:the\s+)?(?:Kindle\s+Store|Books)", re.I),
]

def _decode_ddg_href(href: str) -> str:
    """Resolves DuckDuckGo redirect hrefs (uddg=, protocol-relative) to the true destination."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    m = re.search(r"uddg=([^&]+)", href)
    if m:
        return urllib.parse.unquote(m.group(1))
    return urllib.parse.unquote(href)

def _iter_result_pairs(soup):
    """
    Yields (snippet_text, destination_url) across ALL known bridge layouts.
    Strategy A: html bridge containers. Strategy B: lite bridge tables.
    Strategy C: generic index pairing. No CSS-class assumption can kill all three.
    """
    containers = soup.find_all("div", class_="result")
    if containers:
        for c in containers:
            snip = c.find("a", class_="result__snippet") or c.find(class_="result__snippet")
            link = c.find("a", class_="result__a") or c.find("a", href=True)
            if snip:
                yield snip.get_text(separator=" ", strip=True), _decode_ddg_href(link.get("href", "") if link else "")
        return

    snippets = soup.find_all("td", class_="result-snippet")
    if snippets:
        for td in snippets:
            link = td.find_previous("a", href=True)
            yield td.get_text(separator=" ", strip=True), _decode_ddg_href(link.get("href", "") if link else "")
        return

    links = [a for a in soup.find_all("a", href=True)
             if "uddg=" in a.get("href", "") or "amazon." in a.get("href", "")]
    generic_snippets = soup.find_all("a", class_="result__snippet") or soup.find_all("td", class_="result-snippet")
    for idx, snip in enumerate(generic_snippets):
        href = links[idx].get("href", "") if idx < len(links) else ""
        yield snip.get_text(separator=" ", strip=True), _decode_ddg_href(href)

READER_PROXIES = [
    ("jina", lambda u: f"https://r.jina.ai/{u}"),
    ("allorigins", lambda u: f"https://api.allorigins.win/raw?url={urllib.parse.quote(u, safe='')}"),
    ("corsproxy", lambda u: f"https://corsproxy.io/?url={urllib.parse.quote(u, safe='')}"),
]

_reader_used = 0
_reader_success = 0
READER_BUDGET_PER_CYCLE = 4

def reset_reader_budget():
    global _reader_used, _reader_success
    _reader_used = 0
    _reader_success = 0

def fetch_product_page(asin: str) -> tuple[str, str]:
    """Tries each reader proxy in order; returns (body, proxy_name) on first usable response."""
    url = f"https://www.amazon.com/dp/{asin}"
    for name, wrap in READER_PROXIES:
        try:
            r = requests.get(wrap(url), headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=20)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text, name
        except Exception:
            continue
    return "", ""

def enrich_via_reader(books: list[dict], budget: int) -> list[dict]:
    """Tier-2 evidence: genuine review counts + BSR from real product pages. Never invents."""
    global _reader_used, _reader_success
    for b in books:
        if _reader_used >= budget or b.get("reviews") is not None or not b.get("asin"):
            continue
        _reader_used += 1
        body, proxy = fetch_product_page(b["asin"])
        if not body:
            continue
        for pat in REV_PATTERNS:
            m = pat.search(body)
            if m:
                b["reviews"] = int(m.group(1).replace(",", ""))
                b["evidence"] = f"reader:{proxy}"
                break
        for pat in BSR_PATTERNS:
            m = pat.search(body)
            if m:
                b["bsr"] = min(300000, max(1000, int(m.group(1).replace(",", ""))))
                b["evidence"] = f"reader:{proxy}"
                break
        if b.get("reviews") is not None:
            _reader_success += 1
    return books

def harvest_organic_books(keyword: str, max_items: int = 6) -> list[dict]:
    clean_kw = re.sub(r"[^\w\s]", "", keyword).strip()
    query = f"amazon kindle {clean_kw}"
    books = []

    html, _bridge = _fetch_search_page(query)
    if not html:
        return books

    soup = BeautifulSoup(html, "lxml")
    for text, dest in list(_iter_result_pairs(soup))[:max_items]:
        m = ASIN_PATTERN.search(dest or "")
        asin = m.group(1) if m else None
        rev_match = REV_PATTERN.search(text)
        reviews = int(rev_match.group(1).replace(",", "")) if rev_match else None  # NEVER invent
        books.append({
            "title": text[:100].strip(),
            "reviews": reviews,
            "bsr": estimate_bsr_from_reviews(reviews),
            "asin": asin,
            "evidence": "snippet" if reviews is not None else "none",
        })
    return books

# ===========================================================================
# BUDGET, CACHE (SCHEMA-VERSIONED), TELEMETRY
# ===========================================================================
RADAR_CACHE_FILE = "radar_cache.json"
CACHE_TTL_SECONDS = 6 * 3600
CACHE_SCHEMA = 2                    # bump to invalidate stale evidence-poor entries instantly
DDG_POLITE_DELAY = (2.5, 5.0)
MAX_COLD_SCRAPES_PER_CYCLE = 12
CYCLE_DEADLINE_SECONDS = 180

LAST_RADAR = {"status": "idle", "scanned": 0, "cold_scrapes": 0, "best_score": 0,
              "best_topic": "", "detail": "", "verified_clusters": 0,
              "reader_attempts": 0, "reader_successes": 0, "ts": 0.0}

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
    if (entry and entry.get("schema") == CACHE_SCHEMA
            and (time.time() - entry.get("ts", 0)) < CACHE_TTL_SECONDS):
        return entry
    return None

def _cache_set(key: str, payload: dict):
    cache = _cache_load()
    cache[key] = {"ts": time.time(), "schema": CACHE_SCHEMA, **payload}
    if len(cache) > 200:
        for k in sorted(cache, key=lambda k: cache[k]["ts"])[: len(cache) - 200]:
            cache.pop(k, None)
    with open(RADAR_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def get_last_radar() -> dict:
    return dict(LAST_RADAR)

def run_diagnostics() -> dict:
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
            out["ddg_snippets"] = sum(1 for _ in _iter_result_pairs(soup))
    except ScraperBlockedException as e:
        out["ddg_blocked"] = True
        out["error"] = str(e)
    return out

def run_selftest() -> dict:
    """
    Live-probes EVERY evidence tier from the host network and reports per-tier results.
    This is the ground-truth instrument for 'which tier works on Railway right now'.
    """
    out = {"amazon": 0, "ddg_bridge": None, "pairs": 0, "asins": 0,
           "proxy_results": {}, "error": None}
    out["amazon"] = len(probe_amazon_suggestions("chair yoga seniors"))
    try:
        html, bridge = _fetch_search_page("amazon kindle chair yoga seniors")
        out["ddg_bridge"] = bridge or "none"
        if html:
            soup = BeautifulSoup(html, "lxml")
            pairs = list(_iter_result_pairs(soup))
            out["pairs"] = len(pairs)
            asin = None
            for _text, dest in pairs:
                m = ASIN_PATTERN.search(dest or "")
                if m:
                    asin = m.group(1)
                    break
            out["asins"] = sum(1 for _t, d in pairs if ASIN_PATTERN.search(d or ""))
            if asin:
                for name, wrap in READER_PROXIES:
                    try:
                        r = requests.get(wrap(f"https://www.amazon.com/dp/{asin}"),
                                         headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=20)
                        ok = r.status_code == 200 and len(r.text) > 500
                        parsed = bool(ok) and any(p.search(r.text) for p in REV_PATTERNS)
                        out["proxy_results"][name] = f"HTTP {r.status_code} len {len(r.text)} parse {'YES' if parsed else 'no'}"
                    except Exception as e:
                        out["proxy_results"][name] = f"ERR {type(e).__name__}"
            else:
                out["proxy_results"]["note"] = "no ASIN found in result set; proxy tier untestable this run"
    except ScraperBlockedException as e:
        out["error"] = str(e)
    return out

# ===========================================================================
# BLUEPRINT GENERATOR
# ===========================================================================
def generate_research_blueprint(keyword: str, existing_metrics: dict = None,
                                cached_summary: str = None) -> tuple[dict, str, str]:
    if existing_metrics is not None and cached_summary:
        metrics = existing_metrics
        comp_summary = cached_summary
    else:
        books = harvest_organic_books(keyword)
        books = enrich_via_reader(books, 3)
        metrics = compute_comprehensive_score(books, keyword)
        comp_summary = "\n".join(
            f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] is not None else 'Unverified'} "
            f"| Est BSR: #{b['bsr']:,} | Evidence: {b['evidence']}"
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
# SEED CLUSTERS
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
# 24/7 RADAR SWEEP
# ===========================================================================
def scan_niche_radar() -> dict:
    global LAST_RADAR
    reset_reader_budget()
    cycle_start = time.time()
    alerts = []
    scanned = 0
    cold_scrapes = 0
    verified_clusters = 0
    best_score, best_topic = 0, ""
    status, detail = "no_matches", ""

    for cluster in random.sample(GOLDEN_SEED_CLUSTERS, len(GOLDEN_SEED_CLUSTERS)):
        if time.time() - cycle_start > CYCLE_DEADLINE_SECONDS:
            status = "budget_deferred"
            detail = f"Cycle deadline ({CYCLE_DEADLINE_SECONDS}s) reached; remaining clusters deferred to next cycle."
            break
        try:
            cached = _cache_get(cluster)
            if cached and cached.get("target_query"):
                target_query = cached["target_query"]
                books = cached["books"]
                metrics = cached["metrics"]
                comp_summary = cached["comp_summary"]
                demand_verified = cached.get("demand_verified", False)
            else:
                if cold_scrapes >= MAX_COLD_SCRAPES_PER_CYCLE:
                    status = "budget_deferred"
                    detail = f"Cold-scrape budget ({MAX_COLD_SCRAPES_PER_CYCLE}) reached; remaining clusters deferred to next cycle."
                    break
                queries = scout_seed_angles(cluster)
                verified_q = [q["query"] for q in queries if q["verified"]]
                target_query = verified_q[0] if verified_q else (queries[0]["query"] if queries else cluster)
                time.sleep(random.uniform(*DDG_POLITE_DELAY))
                books = harvest_organic_books(target_query, max_items=6)
                books = enrich_via_reader(books, READER_BUDGET_PER_CYCLE)
                demand_verified = bool(verified_q)
                metrics = compute_comprehensive_score(books, target_query, demand_verified=demand_verified)
                comp_summary = "\n".join(
                    f"- {b['title']} | Reviews: {b['reviews'] if b['reviews'] is not None else 'Unverified'} "
                    f"| Est BSR: #{b['bsr']:,} | Evidence: {b['evidence']}"
                    for b in books
                ) if books else ""
                _cache_set(cluster, {
                    "target_query": target_query,
                    "books": books,
                    "metrics": metrics,
                    "comp_summary": comp_summary,
                    "demand_verified": demand_verified,
                })
                cold_scrapes += 1

            scanned += 1
            if metrics.get("confidence") != "low":
                verified_clusters += 1
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
                  "verified_clusters": verified_clusters,
                  "reader_attempts": _reader_used, "reader_successes": _reader_success,
                  "ts": time.time()}
    return {"alerts": alerts, **LAST_RADAR}
