from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CHANNEL = "@GxNSSupdates"  # The channel handle

app = Flask(__name__)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def get_chat_member(chat_id, user_id):
    url = f"{API_URL}/getChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    resp = requests.get(url, params=params)
    return resp.json()

def check_membership(user_id):
    member = get_chat_member(CHANNEL, user_id)
    result = member.get("result")
    if not result:
        return False
    status = result.get("status", "")
    return status in ["member", "administrator"]

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        user_id = data["message"]["from"]["id"]
        text = data["message"]["text"]

        if text == "/start":
            if check_membership(user_id):
                send_message(chat_id, "✅ You have joined the channel! Now you can access premium courses.")
            else:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Join Channel", "url": "https://t.me/GxNSSupdates"}],
                        [{"text": "✅ Try Again", "callback_data": "check_join"}]
                    ]
                }
                send_message(chat_id, "📢 Please join the channel to access premium courses.", reply_markup=keyboard)

    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        chat_id = query["message"]["chat"]["id"]

        if query.get("data") == "check_join":
            if check_membership(user_id):
                send_message(chat_id, "✅ You have joined the channel! Now you can access premium courses.")
            else:
                send_message(chat_id, "⚠ Please join the channel first!")

    return "OK"

@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    requests.post(url, json=data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
