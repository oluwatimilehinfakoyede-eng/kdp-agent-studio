import os
import io
import re
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
SUBSCRIBED_CHATS = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the command directory and registers chat for radar alerts."""
    chat_id = update.effective_chat.id
    SUBSCRIBED_CHATS.add(chat_id)
    
    welcome_msg = (
        "🚀 *KDP Agent Studio Pro Active*\n\n"
        "Available Commands:\n"
        "• `/scout <broad topic>` — Generate & verify 6 commercial search queries\n"
        "• `/research <query>` — Pull market data, score, & generate Full Asset Package\n"
        "• `/radar` — Trigger an immediate sweep of evergreen non-fiction niches\n\n"
        "📡 *Autonomous Radar:* Active in background. Alerts are sent automatically when $\\ge 72/100$ opportunity niches are found."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def scout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates 6 verified buyer search queries."""
    if not context.args:
        await update.message.reply_text("Usage: `/scout <topic>`\nExample: `/scout container gardening for apartments`", parse_mode="Markdown")
        return

    broad_topic = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Scouting verified angles for: *{broad_topic}*...", parse_mode="Markdown")

    try:
        results = scout_seed_angles(broad_topic)
        keyboard = []
        reply_lines = [f"🎯 *Scouted Buyer Queries for:* _{broad_topic}_\n"]

        for i, res in enumerate(results, 1):
            query = res["query"]
            context.user_data[f"q_{i}"] = query
            status_emoji = "✅ [Amazon Verified]" if res["verified"] else "⚠️ Unverified"
            suggestions_text = f"Suggestions: {', '.join(res['suggestions'])}" if res["suggestions"] else "Suggestions: None"

            reply_lines.append(f"{i}. *{query}*\n   {status_emoji} — _{suggestions_text}_")
            keyboard.append([InlineKeyboardButton(f"Research #{i}: {query[:35]}...", callback_data=f"res_{i}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text("\n".join(reply_lines), reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Scout error: {e}")


async def handle_research_execution(query: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Runs data pipeline and delivers the summary card + downloadable .md file."""
    status_msg = await context.bot.send_message(chat_id=chat_id, text=f"📊 Harvesting data & generating asset package for:\n*{query}*...", parse_mode="Markdown")

    try:
        metrics, blueprint = generate_research_blueprint(query)

        summary_card = (
            f"📈 *KDP Opportunity Report: {query}*\n\n"
            f"• *Viability Score:* {metrics['total']}/100\n"
            f"  - Demand: {metrics['demand']}/40\n"
            f"  - Competition Barrier: {metrics['competition']}/35\n"
            f"  - Series Potential: {metrics['series']}/25\n"
            f"• *Est. Competitor Avg BSR:* #{metrics['avg_bsr']:,}\n"
            f"• *Est. Daily Sales Velocity:* ~{metrics['est_daily_sales']} copies/day\n"
            f"• *Top-Ranked Indie Books:* {metrics['indie_count']}\n"
            f"• *Avg Reviews (Top 8):* {metrics['avg_reviews']}\n\n"
            f"📁 *Complete Production Package Attached Below:*"
        )
        await status_msg.edit_text(summary_card, parse_mode="Markdown")

        # Package full deliverable as a clean Markdown document
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
    """Handles clicks from Scout inline buttons."""
    query = update.callback_query
    await query.answer()

    index = query.data.split("_")[1]
    search_query = context.user_data.get(f"q_{index}")

    if search_query:
        await handle_research_execution(search_query, query.message.chat_id, context)
    else:
        await query.message.reply_text("Query session expired. Please run /scout again.")


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """On-demand radar scan trigger."""
    status_msg = await update.message.reply_text("📡 *Sweeping evergreen niches for high-yield opportunities...*", parse_mode="Markdown")
    try:
        alerts = scan_niche_radar()
        if not alerts:
            await status_msg.edit_text("📡 Radar sweep complete. No evergreen angles passed the 72/100 threshold on this pass. Running next sweep cycle.")
            return

        lines = ["🚨 *High-Opportunity Niches Detected by Radar:*\n"]
        keyboard = []
        for i, a in enumerate(alerts, 1):
            lines.append(
                f"{i}. *{a['topic']}*\n"
                f"   • Score: *{a['score']}/100* | Est. BSR: #{a['avg_bsr']:,} (~{a['est_sales']} sales/day)\n"
                f"   • Avg Reviews: {a['avg_reviews']}\n"
            )
            context.user_data[f"rad_{i}"] = a["topic"]
            keyboard.append([InlineKeyboardButton(f"Research: {a['topic'][:30]}...", callback_data=f"rad_{i}")])

        await status_msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"❌ Radar sweep error: {e}")


async def radar_background_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task executed every 12 hours to alert subscribed users."""
    if not SUBSCRIBED_CHATS:
        return

    try:
        alerts = scan_niche_radar()
        if alerts:
            for chat_id in SUBSCRIBED_CHATS:
                for a in alerts:
                    alert_text = (
                        f"🚨 *Radar Alert: High-Potential Niche Found!*\n\n"
                        f"• *Topic:* {a['topic']}\n"
                        f"• *Score:* {a['score']}/100\n"
                        f"• *Est. Daily Sales:* ~{a['est_sales']} copies/day\n"
                        f"• *Avg Competitor Reviews:* {a['avg_reviews']}\n\n"
                        f"Run `/research {a['topic']}` to generate the publishing package."
                    )
                    await context.bot.send_message(chat_id=chat_id, text=alert_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Background radar notice: {e}")


def main():
    """Starts the bot with polling and initializes the background radar job."""
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scout", scout))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Autonomous Radar: runs every 12 hours (43,200 seconds), first run after 30 seconds
    if app.job_queue:
        app.job_queue.run_repeating(radar_background_job, interval=43200, first=30)

    print("KDP Bot Pro is live and polling. Send /start in Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
