# app.py
import os
from flask import Flask, request, abort
import telebot
from telebot import types

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")  # e.g. https://gxnss.onrender.com
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is required")

QR_IMAGE_URL = "https://mruser96.42web.io/qr.jpg"  # your uploaded QR image
UPI_ID = "7219011336@fam"  # UPI text to show to users

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# -------------------------
# Message contents
# -------------------------
COURSES_MESSAGE = (
    "📚 *GxNSS COURSES*\n\n"
    "🔹 *Programming Courses*\n\n"
    "• C++\n• Java\n• JavaScript\n• Python\n\n"
    "🔹 *Hacking & Cybersecurity Courses*\n\n"
    "• BlackHat Hacking\n• Ethical Hacking\n• Android Hacking\n• WiFi Hacking\n• Binning (by BlackHat)\n"
    "• Antivirus Development\n• Phishing App Development\n• PUBG Hack Development\n• APK Modding (20+ Courses)\n\n"
    "🔹 *System & OS Courses*\n\n"
    "• Linux\n• PowerShell\n\n"
    "🔹 *Special Cyber Tools Courses*\n\n"
    "• How to Make Telegram Number\n• How to Make Lifetime RDP\n• How to Call Any Indian Number Free\n"
    "• How to Make Own SMS Bomber\n• How to Make Own Temporary Mail Bot\n\n"
    "🔹 *Premium Courses Bundle (31 Paid Courses)*\n\n"
    "Cyber Security, Python, Machine Learning, Pro Music Production, Photoshop CC\n(and many more…)"
)

PROMO_MESSAGE = (
    "🚀 *Huge Course Bundle – Now Just ₹79!* (Originally ₹199)\n\n"
    "Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!\n\n"
    "Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!"
)

PAYMENT_INSTRUCTIONS = (
    "🔔 *Payment Instructions*\n\n"
    f"UPI: `{UPI_ID}` — *Tap and hold to copy*\n\n"
    "1. Scan the QR or pay using the UPI above.\n"
    "2. After payment, send a screenshot of the successful payment here in chat.\n\n"
    "We will verify and grant access after receipt."
)


# -------------------------
# /start handler
# -------------------------
@bot.message_handler(commands=["start"])
def send_welcome(message: types.Message):
    chat_id = message.chat.id
    try:
        # 1) Send the main courses message
        bot.send_message(chat_id, COURSES_MESSAGE, parse_mode="Markdown")
    except Exception as e:
        # non-fatal: continue to promo
        print("Error sending courses message:", e)

    try:
        # 2) Send promo message with the Buy button
        markup = types.InlineKeyboardMarkup()
        buy_btn = types.InlineKeyboardButton(text="Buy Course For ₹79", callback_data="buy_79")
        markup.add(buy_btn)
        bot.send_message(chat_id, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print("Error sending promo message:", e)


# -------------------------
# Callback query handlers
# -------------------------
@bot.callback_query_handler(func=lambda call: call.data == "buy_79")
def handle_buy_79(call: types.CallbackQuery):
    chat_id = call.message.chat.id
    try:
        # Acknowledge the button press (small popup)
        bot.answer_callback_query(call.id, text="Preparing payment details...", show_alert=False)
    except Exception:
        pass

    try:
        # Send the QR image by URL — Telegram will fetch it (reduces load on your server)
        bot.send_photo(chat_id, QR_IMAGE_URL, caption="Scan this QR to pay ₹79")
    except Exception as e:
        # If Telegram can't fetch the image, fallback to sending the URL and a message
        print("Error sending photo by URL:", e)
        bot.send_message(chat_id, f"Could not load QR image. Open this link to view QR:\n{QR_IMAGE_URL}")

    # Send the UPI text + instructions
    try:
        # Send the UPI + instructions
        bot.send_message(chat_id, PAYMENT_INSTRUCTIONS, parse_mode="Markdown")
    except Exception as e:
        print("Error sending payment instructions:", e)
        bot.send_message(chat_id, f"UPI: {UPI_ID}\nPlease pay and send screenshot.")


# Optional: you can handle a "I paid" callback if you want another button to confirm
@bot.callback_query_handler(func=lambda call: call.data == "i_paid")
def handle_i_paid(call: types.CallbackQuery):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, text="Thanks! Please upload the payment screenshot here.", show_alert=False)
    bot.send_message(chat_id, "Upload the payment screenshot in this chat now. We'll verify and reply.")


# -------------------------
# Webhook endpoints for Render
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    try:
        bot.remove_webhook()
        full_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        bot.set_webhook(url=full_url)
        return f"Webhook set to {full_url}", 200
    except Exception as e:
        return f"Failed to set webhook: {e}", 500


# Telegram will POST updates to /<BOT_TOKEN>
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        print("Failed to process update:", e)
    return "OK", 200


# Run server (only for local dev). On Render, use gunicorn app:app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
