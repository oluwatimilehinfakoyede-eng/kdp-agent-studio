import os
import io
import re
import json
import asyncio
import urllib.parse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from agents import (
    scout_seed_angles,
    generate_research_blueprint,
    scan_niche_radar,
    run_diagnostics,
    run_selftest,
    get_last_radar,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUBSCRIBERS_FILE = "subscribers.json"
ALERTS_CACHE_FILE = "alerts_cache.json"

SWEEP_LOCK = asyncio.Lock()

# ---------------------------------------------------------------------------
# PERSISTENCE HELPERS
# ---------------------------------------------------------------------------
def load_subscribers() -> set:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()

def save_subscriber(chat_id: int):
    subscribers = load_subscribers()
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subscribers), f)

def load_alerts_cache() -> set:
    if os.path.exists(ALERTS_CACHE_FILE):
        try:
            with open(ALERTS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()

def cache_alert(topic: str):
    cache = load_alerts_cache()
    clean_topic = topic.strip().lower()
    if clean_topic not in cache:
        cache.add(clean_topic)
        with open(ALERTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(cache), f)

def _evidence_line(result: dict) -> str:
    line = (f"Evidence health: {result['verified_clusters']}/{result['scanned']} clusters verified | "
            f"product-page fetches {result['reader_successes']}/{result['reader_attempts']} succeeded | "
            f"saturated rejections: {result.get('saturated_count', 0)}.")
    if result.get("verified_clusters", 0) == 0:
        line += "\n⚠️ Evidence gap: no review counts retrievable this pass — scores capped at the evidence floor BY DESIGN. Run /selftest to probe each evidence tier live."
    elif result.get("saturated_count", 0) > 0:
        line += "\nℹ️ Saturated = real demand but zero vulnerable competitors (no crack in the moat). Correct rejections, not failures."
    return line

# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_subscriber(chat_id)
    welcome_msg = (
        "🚀 *KDP Agent Studio Pro — High-Yield Discovery Engine Active*\n\n"
        "*Available Commands:*\n"
        "• `/scout <topic>` — Deconstruct & verify commercial 2-to-4 word search queries\n"
        "• `/research <query>` — Pull market data, score, & generate full asset package\n"
        "• `/radar` — Trigger an immediate sweep of verified evergreen non-fiction niches\n"
        "• `/diag` — Bridge & IP health diagnostics\n"
        "• `/selftest` — Live-probe every evidence tier (autocomplete, bridges, ASIN pairing, reader proxies)\n\n"
        "📡 *24/7 Autonomous Radar:* LOCKED ON. Your chat is registered.\n"
        "The agent sweeps high-converting micro-clusters every *30 minutes* and pings you "
        "whenever a genuine *≥ 80/100* opportunity with verified evidence is detected."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def scout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/scout <topic>`\nExample: `/scout low oxalate diet`", parse_mode="Markdown")
        return

    broad_topic = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Scouting verified angles for: *{broad_topic}*...", parse_mode="Markdown")
    try:
        results = await asyncio.to_thread(scout_seed_angles, broad_topic)
        keyboard, reply_lines = [], [f"🎯 *Scouted Buyer Queries for:* _{broad_topic}_\n"]

        for i, res in enumerate(results, 1):
            query = res["query"]
            context.user_data[f"q_{i}"] = query
            status_emoji = "✅ [Amazon Verified]" if res["verified"] else "⚠️ Unverified"
            suggestions_text = f"Suggestions: {', '.join(res['suggestions'])}" if res["suggestions"] else "Suggestions: None"
            reply_lines.append(f"{i}. *{query}*\n   {status_emoji} — _{suggestions_text}_")
            amz_url = f"https://www.amazon.com/s?k={urllib.parse.quote_plus(query)}&i=digital-text"
            keyboard.append([
                InlineKeyboardButton(f"📊 Blueprint #{i}", callback_data=f"res_{i}"),
                InlineKeyboardButton("🛒 Amazon Live", url=amz_url),
            ])

        await status_msg.edit_text("\n".join(reply_lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Scout error: {e}")

async def handle_research_execution(query: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                                    cached_metrics: dict = None, cached_summary: str = None):
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Compiling Kindle metrics & generating asset package for:\n*{query}*...",
        parse_mode="Markdown",
    )
    try:
        metrics, blueprint, _summary = await asyncio.to_thread(
            generate_research_blueprint, query, cached_metrics, cached_summary
        )
        entry_bar = metrics.get("entry_bar")
        entry_txt = f"{entry_bar} reviews" if entry_bar is not None else "n/a (no verified evidence)"

        summary_card = (
            f"📈 *KDP Opportunity Report: {query}*\n\n"
            f"• *Viability Score:* {metrics['total']}/100\n"
            f"  - Demand: {metrics['demand']}/35\n"
            f"  - Competition Barrier: {metrics['competition']}/35\n"
            f"  - Series Potential: {metrics['series']}/30\n"
            f"• *Evidence Confidence:* {metrics['confidence']}\n"
            f"• *Evidence Mode:* {metrics.get('evidence_mode', 'unknown')}\n"
            f"• *Entry Bar (weakest ranking competitor):* {entry_txt}\n"
            f"• *Verified Review Evidence:* {metrics['verified_count']} listings\n"
            f"• *Est. Competitor Avg BSR:* #{metrics['avg_bsr']:,}\n"
            f"• *Est. Daily Borrows Velocity:* ~{metrics['est_daily_sales']} borrows/day\n"
            f"• *Avg Reviews:* {metrics['avg_reviews']}\n\n"
            f"📁 *Complete Production Package Attached Below:*"
        )
        await status_msg.edit_text(summary_card, parse_mode="Markdown")

        clean_filename = re.sub(r"[^\w\s-]", "", query).strip().replace(" ", "_")[:40]
        file_bytes = io.BytesIO(blueprint.encode("utf-8"))
        file_bytes.name = f"KDP_Blueprint_{clean_filename}.md"
        await context.bot.send_document(
            chat_id=chat_id,
            document=file_bytes,
            caption=f"📘 Master Publishing Package: *{query}*",
            parse_mode="Markdown",
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Research error: {e}")

async def research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/research <query>`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await handle_research_execution(query, update.effective_chat.id, context)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prefix, index = query.data.split("_")

    if prefix == "rad":
        search_query = context.user_data.get(f"rad_{index}")
        cached_metrics = context.user_data.get(f"rad_metrics_{index}")
        cached_summary = context.user_data.get(f"rad_summary_{index}")
    else:
        search_query = context.user_data.get(f"q_{index}")
        cached_metrics = None
        cached_summary = None

    if search_query:
        await handle_research_execution(
            search_query, query.message.chat_id, context,
            cached_metrics=cached_metrics, cached_summary=cached_summary,
        )
    else:
        await query.message.reply_text(
            "⚠️ Session cache expired (bot restart clears inline-button memory). "
            "Re-run /radar or /scout, then tap the fresh button."
        )

async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📡 Sweeping verified evergreen clusters (≥ 80/100 threshold)...", parse_mode="Markdown")

    try:
        acquired = await asyncio.wait_for(SWEEP_LOCK.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        acquired = False

    if not acquired:
        lr = get_last_radar()
        if lr.get("status") == "idle":
            await status_msg.edit_text(
                "⏳ The first sweep since boot is still running (the background job starts 30s after deploy).\n"
                "It is cold-scanning up to 12 clusters with polite delays; results land within ~3 minutes.\n"
                "Retry /radar shortly — or wait for the automatic alert if it hits ≥80/100.",
                parse_mode="Markdown",
            )
            return
        status_clean = str(lr["status"]).replace("_", " ")
        topic_clean = str(lr["best_topic"]).replace("_", " ")
        await status_msg.edit_text(
            "⏳ A sweep is already in progress (24/7 job or another manual run).\n"
            f"Last completed sweep: status {status_clean} | best {lr['best_score']}/100 ({topic_clean}).\n"
            "Sweeps are bounded to ~3 minutes. Retry shortly, or wait for the automatic alert if the running sweep hits ≥80/100.",
            parse_mode="Markdown",
        )
        return

    try:
        result = await asyncio.to_thread(scan_niche_radar)
        alerts = result["alerts"]

        if result["status"] == "ip_blocked":
            await status_msg.edit_text(
                "🚧 *Sweep aborted — egress IP reputation block.*\n"
                f"Detail: {result['detail']}\n"
                f"Clusters scanned before abort: {result['scanned']}. Cached verdicts remain usable.\n"
                "The 24/7 job retries next cycle with polite backoff. Run /diag for bridge health.",
                parse_mode="Markdown",
            )
            return

        if result["status"] == "budget_deferred":
            await status_msg.edit_text(
                "📡 *Partial sweep — request budget or time deadline reached (IP protection).*\n"
                f"Clusters evaluated: {result['scanned']} | Best: *{result['best_score']}/100* (`{result['best_topic']}`)\n"
                + _evidence_line(result) + "\n"
                "Remaining clusters defer to the next cycle. No niches cleared 80/100 yet.",
                parse_mode="Markdown",
            )
            return

        if not alerts:
            await status_msg.edit_text(
                "📡 *Sweep complete — bridges healthy, no IP issues.*\n"
                f"Clusters evaluated: {result['scanned']} (cold scrapes: {result['cold_scrapes']})\n"
                f"Best score this pass: *{result['best_score']}/100* (`{result['best_topic']}`)\n"
                + _evidence_line(result) + "\n"
                "Nothing cleared the 80/100 threshold.",
                parse_mode="Markdown",
            )
            return

        lines = ["🚨 *High-Opportunity Niches Detected by Radar (≥ 80/100):*\n"]
        keyboard = []
        for i, a in enumerate(alerts, 1):
            entry_txt = f"{a['entry_bar']} reviews" if a.get("entry_bar") is not None else "n/a"
            lines.append(
                f"{i}. *{a['topic']}*\n"
                f"   • *Score:* {a['score']}/100 | *Confidence:* {a['confidence']} | *Evidence:* {a.get('evidence_mode', 'none')}\n"
                f"   • *Est. BSR:* #{a['avg_bsr']:,} (~{a['est_borrows']} borrows/day)\n"
                f"   • *Entry Bar:* {entry_txt} | *Vulnerable Competitors:* {a['vulnerable_count']}\n"
                f"   • *Est. Single Book Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                f"   • *Est. 3-Book Ecosystem:* ~${a['est_series_kenp']}/mo\n"
            )
            context.user_data[f"rad_{i}"] = a["topic"]
            context.user_data[f"rad_metrics_{i}"] = a["raw_metrics"]
            context.user_data[f"rad_summary_{i}"] = a["comp_summary"]
            keyboard.append([
                InlineKeyboardButton(f"📊 Blueprint: {a['topic'][:24]}...", callback_data=f"rad_{i}"),
                InlineKeyboardButton("🛒 Amazon Live", url=a["amazon_url"]),
            ])
        await status_msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Radar sweep error: {e}")
    finally:
        SWEEP_LOCK.release()

async def diag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🩺 Probing bridges and egress reputation...")
    d = await asyncio.to_thread(run_diagnostics)
    verdict = "🚧 BLOCKED" if d["ddg_blocked"] else ("✅ HEALTHY" if d["ddg_snippets"] > 0 else "⚠️ EMPTY (silent block suspected)")
    lr = d["last_radar"]
    status_clean = str(lr["status"]).replace("_", " ")
    topic_clean = str(lr["best_topic"]).replace("_", " ")
    text = (
        "🩺 *Bridge Diagnostics*\n"
        f"• Egress IP: `{d['egress_ip']}`\n"
        f"• Amazon autocomplete: {d['amazon_suggestions']} suggestions\n"
        f"• Search bridge reached: {d['ddg_bridge']}\n"
        f"• Result pairs parsed: {d['ddg_snippets']}\n"
        f"• Bridge verdict: {verdict}\n"
        f"• Last radar: status {status_clean} | scanned {lr['scanned']} | best {lr['best_score']}/100 ({topic_clean})\n"
        f"• Evidence: {lr['verified_clusters']} verified clusters | reader {lr['reader_successes']}/{lr['reader_attempts']}\n"
        + (f"• Error: {d['error']}" if d["error"] else "")
    )
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        await msg.edit_text(re.sub(r"[*_`]", "", text))

async def selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🧪 Running live evidence-tier self-test (this touches every bridge once)...")
    d = await asyncio.to_thread(run_selftest)
    proxy_lines = "\n".join(f"   - {k}: {v}" for k, v in d["proxy_results"].items()) or "   - (not reached)"
    keyed = ", ".join(d["keyed_providers"]) if d["keyed_providers"] else "none configured (free tier only)"
    sample_txt = ", ".join(str(s) for s in d["sample"]) if d["sample"] else "empty"
    text = (
        "🧪 *Evidence-Tier Self-Test*\n"
        f"• Tier 0 Amazon autocomplete: {d['amazon']} / {d['amazon2']} suggestions (two probes)\n"
        f"• Tier 1 search bridge: {d['ddg_bridge']} | pairs {d['pairs']} | ASINs {d['asins']}\n"
        f"• Tier 1.5 ratings-biased sample: [{sample_txt}]\n"
        f"• Tier 2 providers (keyed: {keyed}):\n{proxy_lines}\n"
        "• Interpretation: a Tier 1.5 sample with 2+ numbers OR any provider parse YES unlocks medium/high confidence and 80+ alerts."
    )
    try:
        await msg.edit_text(text, parse_mode="Markdown", link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception:
        try:
            await msg.edit_text(re.sub(r"[*_`]", "", text))
        except Exception:
            pass

# ---------------------------------------------------------------------------
# 24/7 AUTONOMOUS BACKGROUND HUNTER
# ---------------------------------------------------------------------------
async def radar_background_job(context: ContextTypes.DEFAULT_TYPE):
    subscribers = load_subscribers()
    if not subscribers:
        return

    try:
        acquired = await asyncio.wait_for(SWEEP_LOCK.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        print("[radar-job] skipped: manual sweep in progress")
        return

    try:
        result = await asyncio.to_thread(scan_niche_radar)
        print(f"[radar-job] status={result['status']} scanned={result['scanned']} "
              f"cold={result['cold_scrapes']} verified={result['verified_clusters']} "
              f"saturated={result['saturated_count']} "
              f"reader={result['reader_successes']}/{result['reader_attempts']} "
              f"best={result['best_score']} ({result['best_topic']})")

        for a in result["alerts"]:
            topic_key = a["topic"].strip().lower()
            if topic_key in load_alerts_cache():
                continue
            cache_alert(topic_key)
            entry_txt = f"{a['entry_bar']} reviews" if a.get("entry_bar") is not None else "n/a"
            alert_text = (
                f"🚨 *24/7 Autonomous Radar Alert — Gold Nugget Detected!*\n\n"
                f"• *Topic:* `{a['topic']}`\n"
                f"• *Viability Score:* *{a['score']}/100* (confidence: {a['confidence']}, evidence: {a.get('evidence_mode', 'none')})\n"
                f"• *Est. Borrows Velocity:* ~{a['est_borrows']} borrows/day\n"
                f"• *Est. Competitor BSR:* #{a['avg_bsr']:,}\n"
                f"• *Entry Bar:* {entry_txt} | *Vulnerable:* {a['vulnerable_count']}\n"
                f"• *Est. Single Book Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                f"• *Est. 3-Book Ecosystem:* ~${a['est_series_kenp']}/mo\n"
                f"• *Average Reviews:* {a['avg_reviews']}\n\n"
                f"👉 Run `/research {a['topic']}` to generate the publishing asset package."
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 View on Amazon Live", url=a["amazon_url"])]])
            for chat_id in subscribers:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=alert_text,
                                                   reply_markup=keyboard, parse_mode="Markdown")
                except Exception as send_err:
                    print(f"Could not dispatch alert to chat {chat_id}: {send_err}")
    except Exception as e:
        print(f"Autonomous 24/7 background radar notice: {e}")
    finally:
        SWEEP_LOCK.release()

# ---------------------------------------------------------------------------
# BOOTSTRAP
# ---------------------------------------------------------------------------
def main():
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable in Railway.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scout", scout))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CommandHandler("diag", diag))
    app.add_handler(CommandHandler("selftest", selftest))
    app.add_handler(CallbackQueryHandler(button_callback))

    if app.job_queue:
        app.job_queue.run_repeating(radar_background_job, interval=1800, first=30)

    print("KDP Bot Pro 24/7 Engine is online (30-minute cycle, budgeted scraping). Send /start in Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()
