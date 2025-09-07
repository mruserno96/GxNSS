from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CHANNEL_1 = "@GxNSSgiveaway"
CHANNEL_2 = "@GxNSSTOOLS"

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=0, use_context=True)

@app.before_first_request
def set_webhook():
    bot.delete_webhook()
    bot.set_webhook(WEBHOOK_URL)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK"

def start(update, context):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel 1", url="https://t.me/GxNSSgiveaway")],
        [InlineKeyboardButton("Join Channel 2", url="https://t.me/GxNSSTOOLS")],
        [InlineKeyboardButton("✅ Try Again", callback_data="check_join")]
    ])
    update.message.reply_text("📢 Please join both channels to access premium courses.", reply_markup=keyboard)

def check_join(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    try:
        member1 = bot.get_chat_member(CHANNEL_1, user_id)
        member2 = bot.get_chat_member(CHANNEL_2, user_id)
    except Exception as e:
        query.answer("Error checking membership!", show_alert=True)
        return

    if member1.status in ['member', 'administrator'] and member2.status in ['member', 'administrator']:
        bot.send_message(user_id, "✅ You have joined both channels! Now you can access premium courses.")
    else:
        query.answer("⚠ Please join both channels first!", show_alert=True)

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CallbackQueryHandler(check_join, pattern="check_join"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
