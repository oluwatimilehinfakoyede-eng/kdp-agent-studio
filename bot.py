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
    scan_niche_radar
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUBSCRIBERS_FILE = "subscribers.json"
ALERTS_CACHE_FILE = "alerts_cache.json"


def load_subscribers() -> set:
    """Loads subscriber chat IDs from persistent storage."""
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()


def save_subscriber(chat_id: int):
    """Saves a new chat ID to persistent storage."""
    subscribers = load_subscribers()
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subscribers), f)


def load_alerts_cache() -> set:
    """Loads sent alerts to prevent duplicate notifications across restarts."""
    if os.path.exists(ALERTS_CACHE_FILE):
        try:
            with open(ALERTS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()


def cache_alert(topic: str):
    """Appends an alert topic to persistent cache."""
    cache = load_alerts_cache()
    clean_topic = topic.strip().lower()
    if clean_topic not in cache:
        cache.add(clean_topic)
        with open(ALERTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(cache), f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers chat and outputs the command interface."""
    chat_id = update.effective_chat.id
    save_subscriber(chat_id)
    
    welcome_msg = (
        "🚀 *KDP Agent Studio Pro — High-Yield Discovery Engine Active*\n\n"
        "*Available Commands:*\n"
        "• `/scout <topic>` — Deconstruct & verify commercial search queries\n"
        "• `/research <query>` — Pull market data, score, & generate full asset package\n"
        "• `/radar` — Trigger an immediate sweep of evergreen non-fiction niches\n\n"
        "📡 *24/7 Autonomous Radar:* LOCKED ON. Your chat is registered.\n"
        "The agent sweeps high-converting non-fiction clusters every *30 minutes* and pings you whenever an *≥ 80/100* opportunity is detected."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def scout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates 6 verified buyer search queries."""
    if not context.args:
        await update.message.reply_text("Usage: `/scout <topic>`\nExample: `/scout low oxalate cookbook`", parse_mode="Markdown")
        return

    broad_topic = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Scouting verified angles for: *{broad_topic}*...", parse_mode="Markdown")

    try:
        results = await asyncio.to_thread(scout_seed_angles, broad_topic)
        keyboard = []
        reply_lines = [f"🎯 *Scouted Buyer Queries for:* _{broad_topic}_\n"]

        for i, res in enumerate(results, 1):
            query = res["query"]
            context.user_data[f"q_{i}"] = query
            status_emoji = "✅ [Amazon Verified]" if res["verified"] else "⚠️ Unverified"
            suggestions_text = f"Suggestions: {', '.join(res['suggestions'])}" if res["suggestions"] else "Suggestions: None"

            reply_lines.append(f"{i}. *{query}*\n   {status_emoji} — _{suggestions_text}_")
            
            # Action row: Research button + Direct Amazon search link
            amz_url = f"https://www.amazon.com/s?k={urllib.parse.quote_plus(query)}&i=digital-text"
            keyboard.append([
                InlineKeyboardButton(f"📊 Blueprint #{i}", callback_data=f"res_{i}"),
                InlineKeyboardButton("🛒 Amazon Live", url=amz_url)
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text("\n".join(reply_lines), reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Scout error: {e}")


async def handle_research_execution(query: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Executes market analysis and uploads the markdown asset package."""
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Harvesting Kindle metrics & generating asset package for:\n*{query}*...",
        parse_mode="Markdown"
    )

    try:
        metrics, blueprint = await asyncio.to_thread(generate_research_blueprint, query)

        summary_card = (
            f"📈 *KDP Opportunity Report: {query}*\n\n"
            f"• *Viability Score:* {metrics['total']}/100\n"
            f"  - Demand: {metrics['demand']}/35\n"
            f"  - Competition Barrier: {metrics['competition']}/35\n"
            f"  - Series Potential: {metrics['series']}/30\n"
            f"• *Est. Competitor Avg BSR:* #{metrics['avg_bsr']:,}\n"
            f"• *Est. Daily Borrows Velocity:* ~{metrics['est_daily_sales']} borrows/day\n"
            f"• *Top-Ranked Indie Books:* {metrics['indie_count']}\n"
            f"• *Avg Reviews (Top 8):* {metrics['avg_reviews']}\n\n"
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
            parse_mode="Markdown"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Research error: {e}")


async def research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual research trigger."""
    if not context.args:
        await update.message.reply_text("Usage: `/research <query>`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await handle_research_execution(query, update.effective_chat.id, context)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Scout and Radar inline callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    prefix, index = data.split("_")

    if prefix == "rad":
        search_query = context.user_data.get(f"rad_{index}")
    else:
        search_query = context.user_data.get(f"q_{index}")

    if search_query:
        await handle_research_execution(search_query, query.message.chat_id, context)
    else:
        await query.message.reply_text("Session expired. Please trigger the command again.")


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """On-demand radar execution."""
    status_msg = await update.message.reply_text("📡 *Sweeping evergreen Kindle Unlimited clusters (≥ 80/100 threshold)...*", parse_mode="Markdown")
    try:
        alerts = await asyncio.to_thread(scan_niche_radar)
        if not alerts:
            await status_msg.edit_text("📡 Radar sweep complete. No angles met criteria on this pass. Running next sweep cycle.", parse_mode="Markdown")
            return

        lines = ["🚨 *High-Opportunity Niches Detected by Radar (≥ 80/100):*\n"]
        keyboard = []
        for i, a in enumerate(alerts, 1):
            lines.append(
                f"{i}. *{a['topic']}*\n"
                f"   • *Score:* {a['score']}/100 | *Est. BSR:* #{a['avg_bsr']:,} (~{a['est_borrows']} borrows/day)\n"
                f"   • *Reviews:* {a['avg_reviews']} | *Vulnerable Competitors:* {a['vulnerable_count']}\n"
                f"   • *Est. Single Book Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                f"   • *Est. 3-Book Ecosystem:* ~${a['est_series_kenp']}/mo\n"
            )
            context.user_data[f"rad_{i}"] = a["topic"]
            keyboard.append([
                InlineKeyboardButton(f"📊 Blueprint: {a['topic'][:24]}...", callback_data=f"rad_{i}"),
                InlineKeyboardButton("🛒 Amazon Live", url=a["amazon_url"])
            ])

        await status_msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Radar sweep error: {e}")


async def radar_background_job(context: ContextTypes.DEFAULT_TYPE):
    """
    24/7 Autonomous Background Hunter:
    Sweeps clusters every 30 minutes, validates intent, and dispatches new opportunities.
    """
    subscribers = load_subscribers()
    if not subscribers:
        return

    try:
        alerts = await asyncio.to_thread(scan_niche_radar)
        if alerts:
            sent_cache = load_alerts_cache()

            for a in alerts:
                topic_key = a["topic"].strip().lower()
                if topic_key in sent_cache:
                    continue

                cache_alert(topic_key)

                alert_text = (
                    f"🚨 *24/7 Autonomous Radar Alert — Gold Nugget Detected!*\n\n"
                    f"• *Topic:* `{a['topic']}`\n"
                    f"• *Viability Score:* *{a['score']}/100*\n"
                    f"• *Est. Borrows Velocity:* ~{a['est_borrows']} borrows/day\n"
                    f"• *Est. Competitor BSR:* #{a['avg_bsr']:,}\n"
                    f"• *Est. Single Book Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                    f"• *Est. 3-Book Ecosystem:* ~${a['est_series_kenp']}/mo\n"
                    f"• *Average Reviews:* {a['avg_reviews']} ({a['vulnerable_count']} vulnerable)\n\n"
                    f"👉 Run `/research {a['topic']}` to generate the publishing asset package."
                )

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 View on Amazon Live", url=a["amazon_url"])]
                ])

                for chat_id in subscribers:
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=alert_text,
                            reply_markup=keyboard,
                            parse_mode="Markdown"
                        )
                    except Exception as send_err:
                        print(f"Could not dispatch alert to chat {chat_id}: {send_err}")

    except Exception as e:
        print(f"Autonomous 24/7 background radar notice: {e}")


def main():
    """Initializes polling and sets the repeating 30-minute background job."""
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable in Railway.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scout", scout))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CallbackQueryHandler(button_callback))

    if app.job_queue:
        app.job_queue.run_repeating(radar_background_job, interval=1800, first=30)

    print("KDP Bot Pro 24/7 Engine is online (30-minute cycle). Send /start in Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
