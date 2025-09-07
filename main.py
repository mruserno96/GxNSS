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

# Cache already verified users to speed up /start
verified_users = set()

# Messages
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

bundle_text = """🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)
Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!
Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!
"""

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
    try:
        resp = requests.get(f"{API_URL}/getChatMember", params={
            "chat_id": chat_id,
            "user_id": user_id
        }, timeout=3)
        resp.raise_for_status()
        return resp.json().get("result", {})
    except Exception as e:
        print(f"Membership check failed: {e}")
        return {}

def check_membership(user_id):
    if user_id in verified_users:
        return True
    member = get_chat_member(CHANNEL, user_id)
    status = member.get("status", "")
    if status in ["member", "administrator"]:
        verified_users.add(user_id)
        return True
    return False

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    # Handle messages
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]

        if "text" in message and message["text"] in ["/start", "try_again"]:
            if check_membership(user_id):
                # Step 1: Channel joined
                send_message(chat_id, "✅ Channel Joined Successfully!")

                # Step 2: Courses
                send_message(chat_id, courses_text)

                # Step 3: Bundle + inline button
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

    # Handle callback queries
    if "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        user_id = query["from"]["id"]

        if query.get("data") == "check_join":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")

                # Send course list + bundle
                send_message(chat_id, courses_text)
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Buy Now For ₹79", "callback_data": "buy_79"}]
                    ]
                }
                send_message(chat_id, bundle_text, reply_markup=keyboard)
            else:
                send_message(chat_id, "⚠ Please join the channel first!")

        elif query.get("data") == "buy_79":
            # Send QR + payment instructions
            send_photo(chat_id, "https://mruser96.42web.io/qr.jpg")
            send_message(chat_id, "📌 UPI - 7219011336@fam\n\nSEND SS OF PAYMENT WITH YOUR TELEGRAM USERNAME")

    return "OK"

@app.before_first_request
def set_webhook():
    requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
