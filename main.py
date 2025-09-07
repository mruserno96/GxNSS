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
ADMINS = [8356178010, 1929429459]  # Admin Telegram IDs

app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Function to send message with optional keyboard
def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

# Check if user is member or admin in the channel
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

# Build a keyboard with given buttons
def build_keyboard(button_list):
    keyboard = {
        "keyboard": [[btn] for btn in button_list],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    return keyboard

# Handle payments approval by admin
def approve_payment(admin_chat_id, target_chat_id):
    payments = supabase.table("payments").select("*").eq("chat_id", int(target_chat_id)).eq("status", "pending").execute()
    if payments.data:
        payment = payments.data[0]
        supabase.table("payments").update({
            "status": "approved",
            "users": "premium"
        }).eq("chat_id", int(target_chat_id)).execute()
        
        send_message(admin_chat_id, f"✅ Payment for {target_chat_id} approved and user added as premium!")
        send_message(target_chat_id, "🎉 Your payment has been verified! You now have access to premium courses.")
        
        keyboard = build_keyboard(["Hacking Courses", "Programming Courses", "More Courses"])
        send_message(target_chat_id, "Here are your unlocked premium courses:", keyboard)
    else:
        send_message(admin_chat_id, f"❌ No pending payments found for {target_chat_id}")

# Handle incoming requests from Telegram
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        # Admin welcome message
        if user_id in ADMINS and "text" in message and message["text"] == "/start":
            keyboard = build_keyboard(["Help", "View Payments", "View Premium Users"])
            send_message(chat_id, "👋 Welcome Admin! Choose an option below.", keyboard)
            return "OK"

        # User start command
        if "text" in message and message["text"] == "/start":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                keyboard = build_keyboard(["Buy Now For ₹79"])
                send_message(chat_id, get_courses_text(), keyboard)
            else:
                keyboard = build_keyboard(["Join Channel"])
                send_message(chat_id, "📢 Please join the channel to access premium courses.", keyboard)
            return "OK"

        # Help command for admin
        if user_id in ADMINS and "text" in message and message["text"] == "Help":
            help_text = (
                "/start - Restart bot\n"
                "View Payments - See pending payments\n"
                "View Premium Users - See all premium users"
            )
            send_message(chat_id, help_text)
            return "OK"

        # View Payments
        if user_id in ADMINS and "text" in message and message["text"] == "View Payments":
            payments = supabase.table("payments").select("*").eq("status", "pending").execute()
            lines = [f"ID: {p['chat_id']}, Username: {p['username']}" for p in payments.data]
            text = "\n".join(lines) if lines else "No pending payments."
            send_message(chat_id, text)
            return "OK"

        # View Premium Users
        if user_id in ADMINS and "text" in message and message["text"] == "View Premium Users":
            payments = supabase.table("payments").select("*").eq("users", "premium").execute()
            lines = [f"ID: {p['chat_id']}, Username: {p['username']}" for p in payments.data]
            text = "\n".join(lines) if lines else "No premium users found."
            send_message(chat_id, text)
            return "OK"

        # Buy Now button
        if "text" in message and message["text"] == "Buy Now For ₹79":
            send_message(chat_id, "🚀 Huge Course Bundle – Now Just ₹79!\nGet access to an enormous collection of high-value courses!")
            send_message(chat_id, "Please pay ₹79 to UPI ID: `7219011336@fam` and send a screenshot of the payment below.")
            return "OK"

        # Handle uploaded photo (screenshot)
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
            supabase.storage.from_("screenshots").upload(filename, file_content)
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"
            supabase.table("payments").insert({
                "chat_id": user_id,
                "username": username,
                "screenshot_url": public_url,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "users": ""
            }).execute()
            send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment soon.")
            return "OK"

    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        chat_id = query["message"]["chat"]["id"]
        if query.get("data") == "check_join":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
            else:
                send_message(chat_id, "⚠ Please join the channel first!")
            return "OK"

    return "OK"

# Helper to build the course text message
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

# Setup webhook before starting
@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    requests.post(url, json=data)

# Run the app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
