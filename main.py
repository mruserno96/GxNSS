from flask import Flask, request
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

CHANNEL = "@GxNSSupdates"

# Initialize app and supabase client
app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
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

def chat_keyboard(buttons):
    return {
        "keyboard": [[{"text": btn} for btn in row] for row in buttons],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        text = message.get("text", "")

        # Handle /start command
        if text == "/start":
            if check_membership(user_id):
                # User joined the channel
                send_message(chat_id, "✅ Channel Joined Successfully!")

                # Send course list
                courses_text = """📚 GxNSS COURSES

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
(and many more…)"""
                send_message(chat_id, courses_text)

                # Send offer with Buy button
                offer_text = """🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)

Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!

Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!"""
                buttons = [["Buy Now For ₹79"]]
                send_message(chat_id, offer_text, reply_markup=chat_keyboard(buttons))

            else:
                # User not joined → ask to join
                buttons = [["Join Channel"]]
                send_message(chat_id, "📢 Please join the channel to access premium courses.", reply_markup=chat_keyboard(buttons))

        # Handle Buy Now click
        elif text == "Buy Now For ₹79":
            upi_msg = """💳 Payment Details

QR: https://mruser96.42web.io/qr.jpg
UPI: 7219011336@fam

SEND SS OF PAYMENT WITH YOUR TELEGRAM USERNAME"""
            send_message(chat_id, upi_msg)

        # Handle Join Channel click
        elif text == "Join Channel":
            send_message(chat_id, f"Please join our channel: {CHANNEL}")

    return "OK"

@app.before_first_request
def set_webhook():
    requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
