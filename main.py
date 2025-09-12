import os
from flask import Flask, request
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://gxnss.onrender.com")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Root endpoint just for testing
@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

# Set webhook manually (you can call this once or on startup)
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    bot.remove_webhook()
    full_webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    bot.set_webhook(url=full_webhook_url)
    return f"Webhook set to {full_webhook_url}", 200

# Webhook endpoint for Telegram
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# Example handler
@bot.message_handler(commands=["start"])
def start_handler(message):
    bot.reply_to(message, "Hello! I’m alive on Render 🚀")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
