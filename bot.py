import os
import io
import re
import json
import asyncio
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
SENT_ALERTS_CACHE = set()


def load_subscribers() -> set:
    """Loads subscribed Telegram chat IDs from disk to survive Railway restarts."""
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()


def save_subscriber(chat_id: int):
    """Persists a new chat ID to disk."""
    subscribers = load_subscribers()
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subscribers), f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers chat permanently for 24/7 radar alerts and displays instructions."""
    chat_id = update.effective_chat.id
    save_subscriber(chat_id)
    
    welcome_msg = (
        "🚀 *KDP Agent Studio Pro — 24/7 Discovery Engine Active*\n\n"
        "*Available Commands:*\n"
        "• `/scout <broad topic>` — Generate & verify 6 commercial search queries\n"
        "• `/research <query>` — Pull market data, score, & generate Full Asset Package\n"
        "• `/radar` — Trigger an immediate sweep on demand\n\n"
        "🛰️ *Autonomous 24/7 Radar:* LOCKED ON. Your chat is registered. "
        "The agent sweeps high-converting non-fiction clusters every *30 minutes* and pings you whenever a *≥ 80/100* gold nugget is detected."
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
            keyboard.append([InlineKeyboardButton(f"Research #{i}: {query[:32]}...", callback_data=f"res_{i}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text("\n".join(reply_lines), reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Scout error: {e}")


async def handle_research_execution(query: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Runs data pipeline and delivers the summary card + downloadable .md file."""
    status_msg = await context.bot.send_message(chat_id=chat_id, text=f"📊 Harvesting Kindle metrics & generating asset package for:\n*{query}*...", parse_mode="Markdown")

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
    """Manual trigger for research command."""
    if not context.args:
        await update.message.reply_text("Usage: `/research <query>`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await handle_research_execution(query, update.effective_chat.id, context)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles clicks from Scout and Radar inline buttons."""
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
        await query.message.reply_text("Session expired. Please run the command again.")


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """On-demand radar scan trigger."""
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
            keyboard.append([InlineKeyboardButton(f"Research: {a['topic'][:32]}...", callback_data=f"rad_{i}")])

        await status_msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Radar sweep error: {e}")


async def radar_background_job(context: ContextTypes.DEFAULT_TYPE):
    """
    24/7 Autonomous Background Hunter:
    Runs every 30 minutes. Sweeps clusters, verifies search intent, and pings
    all subscribed users when fresh >= 80/100 gold nuggets are uncovered.
    """
    subscribers = load_subscribers()
    if not subscribers:
        return

    try:
        alerts = await asyncio.to_thread(scan_niche_radar)
        if alerts:
            for a in alerts:
                topic_key = a["topic"].strip().lower()
                
                # Deduplication cache check
                if topic_key in SENT_ALERTS_CACHE:
                    continue
                SENT_ALERTS_CACHE.add(topic_key)

                alert_text = (
                    f"🚨 *24/7 Autonomous Radar Alert — Gold Nugget Detected!*\n\n"
                    f"• *Topic:* `{a['topic']}`\n"
                    f"• *Viability Score:* *{a['score']}/100*\n"
                    f"• *Est. Borrows Velocity:* ~{a['est_borrows']} borrows/day\n"
                    f"• *Est. Competitor BSR:* #{a['avg_bsr']:,}\n"
                    f"• *Est. Single Book Monthly Royalty:* ~${a['est_monthly_kenp']}/mo\n"
                    f"• *Est. 3-Book Ecosystem Monthly:* ~${a['est_series_kenp']}/mo\n"
                    f"• *Average Competitor Reviews:* {a['avg_reviews']} ({a['vulnerable_count']} vulnerable)\n\n"
                    f"👉 Run `/research {a['topic']}` to generate the complete publishing asset package."
                )

                for chat_id in subscribers:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=alert_text, parse_mode="Markdown")
                    except Exception as send_err:
                        print(f"Could not dispatch alert to chat {chat_id}: {send_err}")

    except Exception as e:
        print(f"Autonomous 24/7 background radar notice: {e}")


def main():
    """Starts the bot with polling and initializes the 30-minute background job."""
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable in Railway.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scout", scout))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Autonomous Sweep: runs every 1,800 seconds (30 minutes), starts 30 seconds after launch
    if app.job_queue:
        app.job_queue.run_repeating(radar_background_job, interval=1800, first=30)

    print("KDP Bot Pro 24/7 Engine is online (30-minute cycle). Send /start in Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
