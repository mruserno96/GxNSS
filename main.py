from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CHANNEL_1 = "@GxNSSgiveaway"
CHANNEL_2 = "@GxNSSTOOLS"

app = Flask(__name__)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def get_chat_member(chat_id, user_id):
    url = f"{API_URL}/getChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    resp = requests.get(url, params=params)
    return resp.json()

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        if text == "/start":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Join Channel 1", "url": "https://t.me/GxNSSgiveaway"}],
                    [{"text": "Join Channel 2", "url": "https://t.me/GxNSSTOOLS"}],
                    [{"text": "✅ Try Again", "callback_data": "check_join"}]
                ]
            }
            send_message(chat_id, "📢 Please join both channels to access premium courses.", reply_markup=keyboard)

    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        chat_id = query["message"]["chat"]["id"]

        # Check if user is member in both channels
        member1 = get_chat_member(CHANNEL_1, user_id)
        member2 = get_chat_member(CHANNEL_2, user_id)

        status1 = member1.get("result", {}).get("status", "")
        status2 = member2.get("result", {}).get("status", "")

        if status1 in ["member", "administrator"] and status2 in ["member", "administrator"]:
            send_message(chat_id, "✅ You have joined both channels! Now you can access premium courses.")
        else:
            send_message(chat_id, "⚠ Please join both channels first!")

    return "OK"

@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    requests.post(url, json=data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
