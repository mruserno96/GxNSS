from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CHANNEL_1 = "@GxNSSgiveaway"
CHANNEL_2 = "@GxNSSTOOLS"

app = Flask(__name__)

# Telegram Application setup
application = ApplicationBuilder().token(BOT_TOKEN).build()
bot = application.bot

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel 1", url="https://t.me/GxNSSgiveaway")],
        [InlineKeyboardButton("Join Channel 2", url="https://t.me/GxNSSTOOLS")],
        [InlineKeyboardButton("✅ Try Again", callback_data="check_join")]
    ])
    await update.message.reply_text("📢 Please join both channels to access premium courses.", reply_markup=keyboard)

# Callback handler for checking join
async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    try:
        member1 = await bot.get_chat_member(CHANNEL_1, user_id)
        member2 = await bot.get_chat_member(CHANNEL_2, user_id)
    except Exception as e:
        await query.answer("Error checking membership!", show_alert=True)
        return

    if member1.status in ['member', 'administrator'] and member2.status in ['member', 'administrator']:
        await bot.send_message(user_id, "✅ You have joined both channels! Now you can access premium courses.")
    else:
        await query.answer("⚠ Please join both channels first!", show_alert=True)

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(check_join, pattern="check_join"))

# Webhook endpoint
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    asyncio.run(application.update_queue.put(update))
    return "OK"

# Setup webhook before first request
@app.before_first_request
def set_webhook():
    asyncio.run(bot.delete_webhook())
    asyncio.run(bot.set_webhook(WEBHOOK_URL))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
