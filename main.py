import os
from datetime import datetime
import requests
from flask import Flask, request
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------- Load environment variables ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
CHANNEL = os.getenv("CHANNEL")  # e.g., "@YourChannel"
ADMINS = [8356178010, 1929429459]

app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Telegram Helpers ----------------
def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
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
    result = get_chat_member(CHANNEL, user_id).get("result")
    if not result:
        return False
    return result.get("status") in ["member", "administrator"]

def build_keyboard(button_list):
    keyboard = {
        "keyboard": [[btn] for btn in button_list],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    return keyboard

def get_courses_text():
    return """📚 GxNSS COURSES

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

# ---------------- Webhook route ----------------
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        if message.get("text") == "/start":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                keyboard = build_keyboard(["View Courses"])
                send_message(chat_id, get_courses_text(), keyboard)
            else:
                keyboard = build_keyboard(["Join Channel", "Try Again"])
                send_message(chat_id, "⚠ Please join the channel to access courses.", keyboard)
            return "OK"

        if message.get("text") == "Join Channel":
            url = f"https://t.me/{CHANNEL.strip('@')}"
            send_message(chat_id, f"🔗 Please join here: {url}")
            return "OK"

        if message.get("text") == "Try Again":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                keyboard = build_keyboard(["View Courses"])
                send_message(chat_id, get_courses_text(), keyboard)
            else:
                keyboard = build_keyboard(["Join Channel", "Try Again"])
                send_message(chat_id, "⚠ Still not a member. Please join and try again.", keyboard)
            return "OK"

        if message.get("text") == "View Courses":
            send_message(chat_id, get_courses_text())
            return "OK"

    return "OK"

# ---------------- Set Webhook before first request ----------------
@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    try:
        resp = requests.post(url, json=data)
        print("Webhook set:", resp.text)
    except Exception as e:
        print("Webhook error:", e)

# ---------------- Run Flask ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
