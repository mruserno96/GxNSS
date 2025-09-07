from flask import Flask, request
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ----------------- Environment Variables -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
CHANNEL = "@GxNSSupdates"

# ----------------- Initialize App & Supabase -----------------
app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------- Helper Functions -----------------
def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def check_membership(user_id):
    resp = requests.get(f"{API_URL}/getChatMember", params={"chat_id": CHANNEL, "user_id": user_id}).json()
    result = resp.get("result")
    if not result:
        return False
    status = result.get("status", "")
    return status in ["member", "administrator"]

def send_course_flow(chat_id):
    # 1️⃣ Channel joined confirmation
    send_message(chat_id, "✅ Channel Joined Successfully!")

    # 2️⃣ Full course list
    course_list = """📚 GxNSS COURSES

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
    send_message(chat_id, course_list)

    # 3️⃣ Payment offer with button
    keyboard = {
        "inline_keyboard": [
            [{"text": "Buy Now For ₹79", "callback_data": "get_premium"}]
        ]
    }
    payment_msg = """🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)

Get access to an enormous collection of high-value courses that work effectively — 99% guaranteed success!

Don’t miss this incredible offer. Unlock all courses today for only ₹79 and save big!"""
    send_message(chat_id, payment_msg, reply_markup=keyboard)

# ----------------- Flask Webhook -----------------
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    # ----- Handle messages -----
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        # /start command
        if "text" in message and message["text"] == "/start":
            if check_membership(user_id):
                send_course_flow(chat_id)
            else:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Join Channel", "url": f"https://t.me/{CHANNEL[1:]}"}],
                        [{"text": "✅ Try Again", "callback_data": "check_join"}]
                    ]
                }
                send_message(chat_id, "📢 Please join the channel first.", reply_markup=keyboard)

        # Handle screenshot upload (photo)
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            # Download file
            file_content = requests.get(file_url).content
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

            # Upload to Supabase storage
            supabase.storage.from_("screenshots").upload(filename, file_content)

            # Create public URL
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"

            # Insert into payments table
            supabase.table("payments").insert({
                "chat_id": user_id,
                "username": username,
                "screenshot_url": public_url,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }).execute()

            send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment soon.")

    # ----- Handle callback queries -----
    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        chat_id = query["message"]["chat"]["id"]

        # Try Again button
        if query.get("data") == "check_join":
            if check_membership(user_id):
                send_course_flow(chat_id)
            else:
                send_message(chat_id, "⚠ Please join the channel first!")

        # Buy Now button
        if query.get("data") == "get_premium":
            qr_url = "https://mruser96.42web.io/qr.jpg"
            payment_msg = """UPI - 7219011336@fam

SEND SS OF PAYMENT WITH YOUR TELEGRAM USERNAME"""
            requests.post(
                f"{API_URL}/sendPhoto",
                json={
                    "chat_id": chat_id,
                    "photo": qr_url,
                    "caption": payment_msg
                }
            )

    return "OK"

# ----------------- Set Webhook -----------------
@app.before_first_request
def set_webhook():
    requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL})

# ----------------- Run App -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
