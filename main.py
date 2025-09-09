import os
import telebot
from flask import Flask, request

# Get tokens from environment
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialize bot and Flask app
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# /start command
@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Hello 👋 Welcome!")

# Webhook route
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def getMessage():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# Root route to set webhook
@app.route("/")
def webhook():
    bot.remove_webhook()
    url = os.getenv("WEBHOOK_URL", "")
    bot.set_webhook(url=f"{url}/{BOT_TOKEN}")
    return "Webhook set", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
