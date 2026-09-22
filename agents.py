import os
import re
import json
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-3.1-pro"

def call_gemini(prompt: str, system_prompt: str = "") -> str:
    """Calls Gemini with an automated fallback for reliability."""
    config = types.GenerateContentConfig(
        system_instruction=system_prompt if system_prompt else None,
        temperature=0.7,
    )
    for model in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            res = client.models.generate_content(model=model, contents=prompt, config=config)
            if res.text:
                return res.text
        except APIError:
            continue
    raise RuntimeError("Gemini API calls failed on both primary and fallback models.")

# --- SCOUT AGENT TOOLS & LOGIC ---

def probe_amazon_suggestions(prefix: str) -> list[str]:
    """Tool: Probes Amazon's live book search bar to verify buyer traffic."""
    url = "https://completion.amazon.com/api/2017/suggestions"
    params = {
        "mid": "ATVPDKIKX0DER",
        "alias": "stripbooks",
        "prefix": prefix,
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        if r.status_code == 200:
            return [item.get("value", "") for item in r.json().get("suggestions", [])]
    except Exception:
        pass
    return []

def scout_seed_angles(broad_topic: str) -> list[dict]:
    """Generates 6 angles using [Audience + Constraint + Format] and validates them."""
    prompt = f"""
    Deconstruct the topic "{broad_topic}" into 6 specific non-fiction book seed queries.
    Formula: [Specific Target Audience] + [Key Constraint / Pain Point] + [Book Format].
    Return ONLY a raw JSON array of 6 query strings. No markdown backticks, no text:
    ["query 1", "query 2", "query 3", "query 4", "query 5", "query 6"]
    """
    raw = call_gemini(prompt, "You are a KDP keyword expansion specialist. Return strictly JSON.")
    cleaned = re.sub(r"```(json)?", "", raw).strip()
    candidates = json.loads(cleaned)

    verified_results = []
    for query in candidates:
        suggestions = probe_amazon_suggestions(query)
        verified_results.append({
            "query": query,
            "verified": len(suggestions) > 0,
            "suggestions": suggestions[:2]
        })
    return verified_results

# --- RESEARCH AGENT TOOLS & LOGIC ---

def harvest_organic_books(keyword: str, max_items: int = 10) -> list[dict]:
    """Tool: Scrapes Amazon book results while filtering out sponsored ads."""
    url = f"https://www.amazon.com/s?k={requests.utils.quote(keyword)}&i=stripbooks"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    books = []

    for item in soup.find_all("div", {"data-component-type": "s-search-result"}):
        # Skip sponsored ads
        if item.find("span", string=re.compile(r"Sponsored", re.I)) or "s-sponsored-label-info-icon" in item.decode_contents():
            continue

        title_elem = item.find("h2")
        title = title_elem.text.strip() if title_elem else "Unknown"

        price_elem = item.find("span", class_="a-offscreen")
        price = price_elem.text.strip() if price_elem else "N/A"

        rev_elem = item.find("span", {"class": re.compile(r"s-underline-text")})
        reviews = int(re.sub(r"[^\d]", "", rev_elem.text)) if rev_elem else 0

        books.append({"title": title, "price": price, "reviews": reviews})
        if len(books) >= max_items:
            break

    return books

def compute_100_point_score(books: list[dict]) -> dict:
    """Calculates market viability based on review saturation and listings volume."""
    if not books:
        return {"total": 0, "demand": 0, "competition": 0, "series": 0, "avg_reviews": 0}

    reviews = [b["reviews"] for b in books]
    avg_reviews = sum(reviews) / len(reviews)

    # Demand: up to 40 pts
    demand_pts = 35 if len(books) >= 8 else 20

    # Competition: up to 35 pts (lower reviews = lower barrier)
    if avg_reviews < 150:
        comp_pts = 35
    elif avg_reviews < 400:
        comp_pts = 25
    elif avg_reviews < 800:
        comp_pts = 15
    else:
        comp_pts = 5

    # Series Potential: 25 pts
    series_pts = 25

    return {
        "total": demand_pts + comp_pts + series_pts,
        "demand": demand_pts,
        "competition": comp_pts,
        "series": series_pts,
        "avg_reviews": round(avg_reviews, 1)
    }

def generate_research_blueprint(keyword: str) -> tuple[dict, str]:
    """Runs the harvester, computes metrics, and generates the Gemini blueprint."""
    books = harvest_organic_books(keyword)
    metrics = compute_100_point_score(books)

    comp_summary = "\n".join([f"- {b['title']} (Reviews: {b['reviews']}, Price: {b['price']})" for b in books])

    prompt = f"""
    Analyze this Amazon KDP Niche: "{keyword}"
    Viability Score: {metrics['total']}/100 (Demand: {metrics['demand']}/40, Competition: {metrics['competition']}/35, Series: {metrics['series']}/25)
    Average Reviews in Top 10: {metrics['avg_reviews']}

    Competitors:
    {comp_summary if comp_summary else "No live listings scraped - provide baseline projection."}

    Provide:
    1. MARKET VERDICT: Go / Iterate / Pass.
    2. CUSTOMER COMPLAINTS / GAPS: What do 1-3 star reviews typically complain about in this space that our book must resolve?
    3. HOOK & TITLE FORMULA: High-converting Title and Subtitle.
    4. 3-BOOK SERIES BLUEPRINT: Outline for Book 1, Book 2, and Book 3 to maximize Kindle Unlimited read-through royalties.
    5. 7 BACKEND SEARCH KEYWORDS & 2 BISAC CATEGORIES.
    """
    blueprint = call_gemini(prompt, "You are a professional Amazon KDP publishing director. Output dense, actionable blueprints.")
    return metrics, blueprint
