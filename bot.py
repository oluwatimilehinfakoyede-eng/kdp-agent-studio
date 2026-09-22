import os
import re
import asyncio
import tempfile
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import agents

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 *KDP Agent Studio Active*\n\n"
        "Commands:\n"
        "• `/scout <broad topic>` — Generate 6 angles & verify against live Amazon search queries.\n"
        "• `/research <seed niche>` — Scrape listings, compute 100-pt score, & generate Gemini 3.8 Flash blueprint."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def scout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/scout <broad topic>`\nExample: `/scout nervous system regulation`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    topic = " ".join(context.args)
    status_msg = await update.message.reply_text(
        f"🔍 *Scout Agent running for:* `{topic}`...",
        parse_mode=ParseMode.MARKDOWN
    )

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(None, agents.scout_seed_angles, topic)
        reply = [f"🎯 *Scouted Angles for:* `{topic}`\n"]
        keyboard = []

        for i, item in enumerate(results, 1):
            q = item["query"]
            status = "✅ [Amazon Verified]" if item["verified"] else "⚠️ [Unverified]"
            sug = ", ".join(item["suggestions"]) if item["suggestions"] else "None"
            reply.append(f"*{i}. {q}*\n   {status} — _Suggestions: {sug}_")
            keyboard.append([InlineKeyboardButton(f"Research #{i}", callback_data=f"do_{q[:40]}")])

        await status_msg.delete()
        await update.message.reply_text(
            "\n".join(reply),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Scout error: {e}")

async def run_research_pipeline(keyword: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚙️ *Research Agent running for:* `{keyword}`\n• Scraping organic books...\n• Calculating 100-pt score...\n• Synthesizing blueprint with Gemini 3.8 Flash...",
        parse_mode=ParseMode.MARKDOWN
    )
    loop = asyncio.get_running_loop()
    try:
        metrics, blueprint = await loop.run_in_executor(None, agents.generate_research_blueprint, keyword)

        summary = (
            f"📊 *KDP Opportunity Report: {keyword}*\n\n"
            f"• *Score:* `{metrics['total']}/100`\n"
            f"• *Demand Factor:* `{metrics['demand']}/40`\n"
            f"• *Competition Barrier:* `{metrics['competition']}/35`\n"
            f"• *Series Potential:* `{metrics['series']}/25`\n"
            f"• *Avg Reviews (Top 10):* `{metrics['avg_reviews']}`\n\n"
            "📄 _Full strategy document generated below._"
        )
        await status_msg.delete()
        await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.MARKDOWN)

        # Generate downloadable text report
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tf:
            tf.write(f"KDP BLUEPRINT: {keyword}\n")
            tf.write("=" * 60 + "\n\n")
            tf.write(f"Viability: {metrics['total']}/100 | Avg Reviews: {metrics['avg_reviews']}\n\n")
            tf.write(blueprint)
            temp_path = tf.name

        with open(temp_path, "rb") as doc:
            clean_filename = re.sub(r'[^a-zA-Z0-9]', '_', keyword)
            await context.bot.send_document(
                chat_id=chat_id,
                document=doc,
                filename=f"KDP_Blueprint_{clean_filename}.txt",
                caption=f"Full publishing blueprint for '{keyword}'"
            )
        os.remove(temp_path)
    except Exception as e:
        await status_msg.edit_text(f"❌ Research error: {e}")

async def research_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/research <seed niche>`\nExample: `/research somatic exercises for women`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    keyword = " ".join(context.args)
    await run_research_pipeline(keyword, update.effective_chat.id, context)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("do_"):
        keyword = query.data.replace("do_", "")
        await run_research_pipeline(keyword, update.effective_chat.id, context)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scout", scout_cmd))
    app.add_handler(CommandHandler("research", research_cmd))
    app.add_handler(CallbackQueryHandler(button_click))

    print("Bot is live and polling. Send /start in Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()