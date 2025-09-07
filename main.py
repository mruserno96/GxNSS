from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
CHANNEL = "@GxNSSupdates"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def send_photo(chat_id, photo_url):
    requests.post(f"{API_URL}/sendPhoto", json={
        "chat_id": chat_id,
        "photo": photo_url
    })

def get_chat_member(chat_id, user_id):
    resp = requests.get(f"{API_URL}/getChatMember", params={"chat_id": chat_id, "user_id": user_id})
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

    # Message handling
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]

        # /start or text message
        if "text" in message and message["text"] in ["/start"]:
            if check_membership(user_id):
                # Step 1: Channel joined
                send_message(chat_id, "✅ Channel Joined Successfully!")

                # Step 2: Course list
                courses_text = """
📚 GxNSS COURSES

🔹 Programming Courses
C++
Java
JavaScript
Python

🔹 Hacking & Cybersecurity Courses
BlackHat Hacking
Ethical Hacking
Android Hacking
WiFi Hacking
Binning (by BlackHat)
Antivirus Development
Phishing App Development
PUBG Hack Development
APK Modding (20+ Courses)

🔹 System & OS Courses
Linux
PowerShell

🔹 Special Cyber Tools Courses
How to Make Telegram Number
How to Make Lifetime RDP
How to Call Any Indian Number Free
How to Make Own SMS Bomber
How to Make Own Temporary Mail Bot

🔹 Premium Courses Bundle (31 Paid Courses)
Cyber Security
Python
Machine Learning
Pro Music Production
Photoshop CC
(and many more…)
"""
                send_message(chat_id, courses_text)

                # Step 3: Huge bundle + inline button
                bundle_text = """🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)
Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!
Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!
"""
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Buy Now For ₹79", "callback_data": "buy_79"}]
                    ]
                }
                send_message(chat_id, bundle_text, reply_markup=keyboard)
            else:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Join Channel", "url": f"https://t.me/{CHANNEL.strip('@')}"}],
                        [{"text": "✅ Try Again", "callback_data": "check_join"}]
                    ]
                }
                send_message(chat_id, "📢 Please join the channel to access premium courses.", reply_markup=keyboard)

    # Callback query handling
    if "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        user_id = query["from"]["id"]

        if query.get("data") == "check_join":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
            else:
                send_message(chat_id, "⚠ Please join the channel first!")

        if query.get("data") == "buy_79":
            # Send UPI QR + instructions
            send_photo(chat_id, "https://mruser96.42web.io/qr.jpg")
            send_message(chat_id, "📌 UPI - 7219011336@fam\n\nSEND SS OF PAYMENT WITH YOUR TELEGRAM USERNAME")

    return "OK"

@app.before_first_request
def set_webhook():
    requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
