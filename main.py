import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
import telebot

# ---------------- Load environment ----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CHANNEL = os.getenv("CHANNEL")
ADMINS = [8356178010, 1929429459]  # Replace with your actual Telegram IDs

# ---------------- Initialize ----------------
bot = telebot.TeleBot(BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ---------------- Helper Functions ----------------
def send_message(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if keyboard:
        data["reply_markup"] = keyboard
    requests.post(f"{API_URL}/sendMessage", json=data)

def get_chat_member(user_id):
    url = f"{API_URL}/getChatMember"
    params = {"chat_id": CHANNEL, "user_id": user_id}
    resp = requests.get(url, params=params).json()
    result = resp.get("result")
    if result and result.get("status") in ["member", "administrator"]:
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

# ---------------- Handlers ----------------
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or ""

    if user_id in ADMINS:
        keyboard = build_keyboard(["Help", "View Payments", "View Premium Users"])
        send_message(chat_id, "👋 Welcome Admin! Choose an option below.", keyboard)
    else:
        if get_chat_member(user_id):
            keyboard = build_keyboard(["Buy Now For ₹79"])
            send_message(chat_id, "✅ Channel Joined Successfully!", keyboard)
            send_message(chat_id, get_courses_text())
        else:
            keyboard = build_keyboard(["Join Channel"])
            send_message(chat_id, "📢 Please join the channel to access premium courses.", keyboard)

@bot.message_handler(func=lambda message: message.text == "Help" and message.from_user.id in ADMINS)
def handle_help(message):
    text = (
        "/start - Restart bot\n"
        "View Payments - See pending payments\n"
        "View Premium Users - See all premium users"
    )
    send_message(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == "View Payments" and message.from_user.id in ADMINS)
def handle_view_payments(message):
    payments = supabase.table("payments").select("*").eq("status", "pending").execute()
    lines = [f"ID: {p['chat_id']}, Username: {p['username']}" for p in payments.data]
    text = "\n".join(lines) if lines else "No pending payments."
    send_message(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == "View Premium Users" and message.from_user.id in ADMINS)
def handle_view_premium(message):
    users = supabase.table("payments").select("*").eq("users", "premium").execute()
    lines = [f"ID: {p['chat_id']}, Username: {p['username']}" for p in users.data]
    text = "\n".join(lines) if lines else "No premium users found."
    send_message(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == "Buy Now For ₹79")
def handle_buy(message):
    send_message(message.chat.id, "🚀 Huge Course Bundle – Now Just ₹79!\nGet access to an enormous collection of high-value courses!")
    send_message(message.chat.id, "Please pay ₹79 to UPI ID: `7219011336@fam` and send a screenshot of the payment below.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or ""

    # Get the highest resolution photo
    file_id = message.photo[-1].file_id
    file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
    file_path = file_info["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    # Store screenshot in Supabase
    response = requests.get(file_url)
    filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    supabase.storage.from_("screenshots").upload(filename, response.content)
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"

    # Insert into payments table
    supabase.table("payments").insert({
        "chat_id": user_id,
        "username": username,
        "screenshot_url": public_url,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "users": ""
    }).execute()

    send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment soon.")

# ---------------- Run ----------------
if __name__ == "__main__":
    print("✅ Bot polling started!")
    bot.infinity_polling()
