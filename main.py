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

app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data, timeout=1)

def get_chat_member(chat_id, user_id):
    url = f"{API_URL}/getChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    try:
        resp = requests.get(url, params=params, timeout=1)
        return resp.json()
    except requests.exceptions.RequestException:
        return {}

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

        if text == "/start":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                send_courses(chat_id)
            else:
                buttons = [["Join Channel"]]
                send_message(chat_id, "📢 Please join the channel to access premium courses.", reply_markup=chat_keyboard(buttons))

        elif text == "Join Channel":
            send_message(chat_id, f"Please join our channel: {CHANNEL}")

        elif text == "Buy Now For ₹79":
            upi_msg = """💳 Payment Details

QR: https://mruser96.42web.io/qr.jpg
UPI: 7219011336@fam

SEND SS OF PAYMENT WITH YOUR TELEGRAM USERNAME"""
            send_message(chat_id, upi_msg)

        if "photo" in message:
            handle_photo(chat_id, user_id, username, message["photo"])

    return "OK"

def send_courses(chat_id):
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

    offer_text = """🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)

Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!

Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!"""
    buttons = [["Buy Now For ₹79"]]
    send_message(chat_id, offer_text, reply_markup=chat_keyboard(buttons))

def handle_photo(chat_id, user_id, username, photos):
    file_id = photos[-1]["file_id"]
    file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}, timeout=1).json()
    file_path = file_info.get("result", {}).get("file_path", "")
    if not file_path:
        send_message(chat_id, "❌ Failed to upload screenshot.")
        return

    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    file_content = requests.get(file_url, timeout=2).content
    filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

    supabase.storage.from_("screenshots").upload(filename, file_content)

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"

    supabase.table("payments").insert({
        "chat_id": user_id,
        "username": username,
        "screenshot_url": public_url,
        "status": "pending",
        "created_at": datetime.now().isoformat()
    }).execute()

    send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment soon.")

@app.before_first_request
def set_webhook():
    requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL}, timeout=1)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
