import os
import io
import re
import json
import asyncio
import urllib.parse
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUBSCRIBERS_FILE = "subscribers.json"
ALERTS_CACHE_FILE = "alerts_cache.json"

# Prevents /radar and the 30-min job from double-hitting the search bridges
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
        "• `/diag` — Bridge & IP health diagnostics\n\n"
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
    """
    Generates the asset package. When Radar-cached metrics AND summary are passed,
    zero re-scraping occurs — the blueprint matches the score exactly (desync eliminated).
    """
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Compiling Kindle metrics & generating asset package for:\n*{query}*...",
        parse_mode="Markdown",
    )
    try:
        metrics, blueprint, _summary = await asyncio.to_thread(
            generate_research_blueprint, query, cached_metrics, cached_summary
        )

        summary_card = (
            f"📈 *KDP Opportunity Report: {query}*\n\n"
            f"• *Viability Score:* {metrics['total']}/100\n"
            f"  - Demand: {metrics['demand']}/35\n"
            f"  - Competition Barrier: {metrics['competition']}/35\n"
            f"  - Series Potential: {metrics['series']}/30\n"
            f"• *Evidence Confidence:* {metrics['confidence']}\n"
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
    """Inline callbacks. Radar buttons carry BOTH metrics and competitor summary."""
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
    if SWEEP_LOCK.locked():
        await update.message.reply_text("⏳ A sweep is already running (manual or background). Try again shortly.")
        return

    status_msg = await update.message.reply_text("📡 Sweeping verified evergreen clusters (≥ 80/100 threshold)...", parse_mode="Markdown")
    async with SWEEP_LOCK:
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
                    "📡 *Partial sweep — request budget reached (IP protection).*\n"
                    f"Clusters evaluated: {result['scanned']} | Best: *{result['best_score']}/100* (`{result['best_topic']}`)\n"
                    "Remaining clusters defer to the next cycle. No niches cleared 80/100 yet.",
                    parse_mode="Markdown",
                )
                return

            if not alerts:
                await status_msg.edit_text(
                    "📡 *Sweep complete — bridges healthy, no IP issues.*\n"
                    f"Clusters evaluated: {result['scanned']} (cold scrapes: {result['cold_scrapes']})\n"
                    f"Best score this pass: *{result['best_score']}/100* (`{result['best_topic']}`)\n"
                    "Nothing cleared the 80/100 threshold. This is a market verdict, not a scraper failure.",
                    parse_mode="Markdown",
                )
                return

            lines = ["🚨 *High-Opportunity Niches Detected by Radar (≥ 80/100):*\n"]
            keyboard = []
            for i, a in enumerate(alerts, 1):
                lines.append(
                    f"{i}. *{a['topic']}*\n"
                    f"   • *Score:* {a['score']}/100 | *Confidence:* {a['confidence']} | *Est. BSR:* #{a['avg_bsr']:,} (~{a['est_borrows']} borrows/day)\n"
                    f"   • *Reviews:* {a['avg_reviews']} | *Vulnerable Competitors:* {a['vulnerable_count']}\n"
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

async def diag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🩺 Probing bridges and egress reputation...")
    d = await asyncio.to_thread(run_diagnostics)
    verdict = "🚧 BLOCKED" if d["ddg_blocked"] else ("✅ HEALTHY" if d["ddg_snippets"] > 0 else "⚠️ EMPTY (silent block suspected)")
    lr = d["last_radar"]
    # Legacy Markdown rejects lone underscores: sanitize every dynamic enum/slug
    status_clean = str(lr["status"]).replace("_", " ")
    topic_clean = str(lr["best_topic"]).replace("_", " ")
    text = (
        "🩺 *Bridge Diagnostics*\n"
        f"• Egress IP: `{d['egress_ip']}`\n"
        f"• Amazon autocomplete: {d['amazon_suggestions']} suggestions\n"
        f"• Search bridge reached: {d['ddg_bridge']}\n"
        f"• Snippets parsed: {d['ddg_snippets']}\n"
        f"• Bridge verdict: {verdict}\n"
        f"• Last radar: status {status_clean} | scanned {lr['scanned']} | best {lr['best_score']}/100 ({topic_clean})\n"
        + (f"• Error: {d['error']}" if d["error"] else "")
    )
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        await msg.edit_text(re.sub(r"[*_`]", "", text))  # plain-text fallback, never freeze again

# ---------------------------------------------------------------------------
# 24/7 AUTONOMOUS BACKGROUND HUNTER
# ---------------------------------------------------------------------------
async def radar_background_job(context: ContextTypes.DEFAULT_TYPE):
    subscribers = load_subscribers()
    if not subscribers or SWEEP_LOCK.locked():
        return

    async with SWEEP_LOCK:
        try:
            result = await asyncio.to_thread(scan_niche_radar)
            print(f"[radar-job] status={result['status']} scanned={result['scanned']} "
                  f"cold={result['cold_scrapes']} best={result['best_score']} ({result['best_topic']})")

            for a in result["alerts"]:
                topic_key = a["topic"].strip().lower()
                if topic_key in load_alerts_cache():
                    continue
                cache_alert(topic_key)
                alert_text = (
                    f"🚨 *24/7 Autonomous Radar Alert — Gold Nugget Detected!*\n\n"
                    f"• *Topic:* `{a['topic']}`\n"
                    f"• *Viability Score:* *{a['score']}/100* (confidence: {a['confidence']})\n"
                    f"• *Est. Borrows Velocity:* ~{a['est_borrows']} borrows/day\n"
                    f"• *Est. Competitor BSR:* #{a['avg_bsr']:,}\n"
                    f"• *Est. Single Book Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                    f"• *Est. 3-Book Ecosystem:* ~${a['est_series_kenp']}/mo\n"
                    f"• *Average Reviews:* {a['avg_reviews']} ({a['vulnerable_count']} vulnerable)\n\n"
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
    app.add_handler(CallbackQueryHandler(button_callback))

    if app.job_queue:
        app.job_queue.run_repeating(radar_background_job, interval=1800, first=30)

    print("KDP Bot Pro 24/7 Engine is online (30-minute cycle, budgeted scraping). Send /start in Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()
