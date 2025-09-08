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
CHANNEL = os.getenv("CHANNEL")  # Example: "@YourChannelUsername"
ADMINS = [8356178010, 1929429459]  # Admin Telegram IDs

# ---------------- Initialize ----------------
app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Telegram Helper Functions ----------------
def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def send_photo(chat_id, photo_url, caption=None):
    data = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "Markdown"
    requests.post(f"{API_URL}/sendPhoto", json=data)

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

def is_premium(user_id):
    res = supabase.table("payments").select("status").eq("chat_id", user_id).execute()
    if res.data and res.data[0]["status"] == "premium":
        return True
    return False

def build_keyboard(button_list):
    keyboard = {
        "keyboard": [[btn] for btn in button_list],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    return keyboard

def get_courses_text():
    return """📚 *GxNSS COURSES*

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

def get_offer_text():
    return """🚀 *Huge Course Bundle – Now Just ₹79!* (Originally ₹199)

Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!

Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!"""

def get_upi_text():
    return """💳 *UPI ID:* `7219011336@fam`

Send a screenshot of your payment with your Telegram username below. We will verify and upgrade your account to premium."""

# ---------------- Webhook Route ----------------
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        # ---------------- Admin Commands ----------------
        if user_id in ADMINS and message.get("text") == "/start":
            keyboard = build_keyboard(["Help", "View Payments", "View Premium Users"])
            send_message(chat_id, "👋 Hello Admin! Choose an option.", keyboard)
            return "OK"

        if user_id in ADMINS and message.get("text") == "Help":
            help_text = "/start - Restart bot\nView Payments - See pending payments\nView Premium Users - See all premium users"
            send_message(chat_id, help_text)
            return "OK"

        if user_id in ADMINS and message.get("text") == "View Payments":
            payments = supabase.table("payments").select("*").eq("status", "pending").execute()
            lines = [f"Chat ID: {p['chat_id']}\nUsername: @{p['username'] or 'N/A'}\n" for p in payments.data]
            text = "\n".join(lines) if lines else "No pending payments."
            send_message(chat_id, text)
            return "OK"

        if user_id in ADMINS and message.get("text") == "View Premium Users":
            payments = supabase.table("payments").select("*").eq("status", "premium").execute()
            lines = [f"Chat ID: {p['chat_id']}\nUsername: @{p['username'] or 'N/A'}\n" for p in payments.data]
            text = "\n".join(lines) if lines else "No premium users."
            send_message(chat_id, text)
            return "OK"

        # ---------------- User Commands ----------------
        if message.get("text") == "/start":
            if is_premium(user_id):
                send_message(chat_id, "✅ Welcome back Premium User!")
                send_message(chat_id, get_courses_text())
            elif check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                send_message(chat_id, get_courses_text(), build_keyboard(["Buy Now For ₹79"]))
                send_message(chat_id, get_offer_text())
            else:
                send_message(chat_id, "⚠ Please join the channel to access premium courses.", build_keyboard(["Join Channel", "Try Again"]))
            return "OK"

        if message.get("text") == "Join Channel":
            url = f"https://t.me/{CHANNEL.strip('@')}"
            send_message(chat_id, f"🔗 Please join here: {url}")
            return "OK"

        if message.get("text") == "Try Again":
            if is_premium(user_id):
                send_message(chat_id, "✅ Welcome back Premium User!")
                send_message(chat_id, get_courses_text())
            elif check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                send_message(chat_id, get_courses_text(), build_keyboard(["Buy Now For ₹79"]))
                send_message(chat_id, get_offer_text())
            else:
                send_message(chat_id, "⚠ Still not a member. Please join and try again.", build_keyboard(["Join Channel", "Try Again"]))
            return "OK"

        if message.get("text") == "Buy Now For ₹79":
            send_photo(chat_id, "https://mruser96.42web.io/qr.jpg")
            send_message(chat_id, get_upi_text())
            return "OK"

        # ---------------- Handle Payment Screenshot ----------------
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

            try:
                supabase.storage.from_("screenshots").upload(filename, file_content)
                public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"
            except Exception as e:
                public_url = ""
                print("Storage upload error:", e)

            supabase.table("payments").insert({
                "chat_id": user_id,
                "username": username,
                "screenshot_url": public_url,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }).execute()

            send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment.")
            return "OK"

    return "OK"

# ---------------- Set Webhook ----------------
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
