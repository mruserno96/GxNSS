import os
import logging
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, abort
import telebot
from telebot import types
from supabase import create_client, Client
from dotenv import load_dotenv

# -------------------------
# Load environment
# -------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")
_ADMIN_TELEGRAM_IDS_RAW = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ Missing required environment variables")

# Parse admin IDs
ADMIN_IDS = set()
for part in (_ADMIN_TELEGRAM_IDS_RAW or "").split(","):
    part = part.strip()
    if not part:
        continue
    try:
        ADMIN_IDS.add(int(part))
    except ValueError:
        pass

UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")

# -------------------------
# Setup
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=5)
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Constants
# -------------------------
UPI_ID = "MillionaireNaitik69@fam"
QR_IMAGE_URL = "https://mruser96.42web.io/qr.jpg?nocache="
COURSES_MESSAGE = (
    "📚 *GxNSS COURSES*\n\n"
    "🔹 *Programming Courses*\n"
    "C++\nJava\nJavaScript\nPython\n\n"
    "🔹 *Hacking & Cybersecurity Courses*\n"
    "BlackHat Hacking\nEthical Hacking\nAndroid Hacking\nWiFi Hacking\n"
    "Binning (by BlackHat)\nAntivirus Development\nPhishing App Development\nPUBG Hack Development\nAPK Modding (20+ Courses)\n\n"
    "🔹 *System & OS Courses*\n"
    "Linux\nPowerShell\n\n"
    "🔹 *Special Cyber Tools Courses*\n"
    "How to Make Telegram Number\nHow to Make Lifetime RDP\nHow to Call Any Indian Number Free\n"
    "How to Make Own SMS Bomber\nHow to Make Own Temporary Mail Bot\n\n"
    "🔹 *Premium Courses Bundle (31 Paid Courses)*\n"
    "Cyber Security\nPython\nMachine Learning\nPro Music Production\nPhotoshop CC\n(and many more…)"
)
PROMO_MESSAGE = (
    "🚀 *Huge Course Bundle – Just ₹79!* (Originally ₹199)\n\n"
    "Get 30+ premium courses with guaranteed results. Don’t miss this offer!"
)
PAYMENT_INSTRUCTIONS = (
    f"🔔 *Payment Instructions*\n\n"
    f"UPI: {UPI_ID}\n\n"
    "1. Scan the QR or pay using the UPI above.\n"
    "2. Click *I Paid (Upload Screenshot)* below to upload proof.\n\n"
    "We’ll verify and grant access."
)

# -------------------------
# Helpers
# -------------------------
def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False

def notify_admins(text):
    if not ADMIN_IDS:
        return
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass

def find_or_create_user(telegram_id, username, first_name=None, last_name=None):
    try:
        telegram_id = int(telegram_id)
    except Exception:
        pass
    resp = supabase.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
    if resp.data:
        return resp.data[0]
    new_user = {
        "telegram_id": telegram_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "status": "normal",
        "pending_upload": False,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    ins = supabase.table("users").insert(new_user).execute()
    return ins.data[0] if ins.data else None

def upload_to_supabase(bucket, object_path, file_bytes, content_type="image/jpeg"):
    object_path = object_path.lstrip("/")
    storage = supabase.storage.from_(bucket)
    try:
        storage.remove([object_path])
    except Exception:
        pass
    storage.upload(object_path, file_bytes, {"content-type": content_type})
    return object_path, storage.get_public_url(object_path)

def create_payment(user_row, file_path, file_url, username):
    payload = {
        "user_id": user_row["id"],
        "username": username,
        "file_path": file_path,
        "file_url": file_url,
        "verified": False,
        "created_at": datetime.utcnow().isoformat(),
    }
    res = supabase.table("payments").insert(payload).execute()
    return res.data[0] if res.data else None

def save_message(user_id, chat_id, message_id):
    try:
        supabase.table("messages").insert({
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id
        }).execute()
    except Exception:
        pass

def delete_old_messages(user_row):
    rows = supabase.table("messages").select("*").eq("user_id", user_row["id"]).execute().data
    for r in rows:
        try:
            bot.delete_message(r["chat_id"], r["message_id"])
        except Exception:
            pass
    supabase.table("messages").delete().eq("user_id", user_row["id"]).execute()

def notify_user_upgrade(user_row):
    try:
        delete_old_messages(user_row)
        sent = bot.send_message(
            user_row["telegram_id"],
            "💲 We upgraded you to Premium User!\n\nClick /start to access your courses 🚀",
            parse_mode="Markdown"
        )
        save_message(user_row["id"], user_row["telegram_id"], sent.message_id)
    except Exception:
        pass

# -------------------------
# Premium Menu Keyboards
# -------------------------
def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        "🔹 Programming Courses",
        "🔹 Hacking & Cybersecurity Courses",
        "🔹 System & OS Courses",
        "🔹 Special Cyber Tools Courses",
        "🔹 Premium Courses Bundle (31 Paid Courses)"
    )
    return markup

def programming_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("C++", "Java", "JavaScript", "Python", "⬅ Back")
    return markup

def hacking_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "BlackHat Hacking", "Ethical Hacking", "Android Hacking", "WiFi Hacking",
        "Binning (by BlackHat)", "Antivirus Development", "Phishing App Development",
        "PUBG Hack Development", "APK Modding 20+ Course", "⬅ Back"
    )
    return markup

def system_os_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("Linux", "PowerShell", "⬅ Back")
    return markup

def special_tools_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "Telegram Number", "Lifetime RDP",
        "Call Any Indian Number Free", "Make Own SMS Bomber",
        "Own Temporary Mail Bot", "⬅ Back"
    )
    return markup

def premium_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "Cyber Security", "Python", "Machine Learning", "Pro Music Production",
        "Photoshop CC", "⬅ Back"
    )
    return markup

# -------------------------
# /start handler
# -------------------------
@bot.message_handler(commands=["start"])
def send_welcome(message):
    cid = message.chat.id
    user = find_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )

    if user and user.get("status") == "premium":
        bot.send_message(
            cid,
            "🎉 Welcome back Premium User!",
            reply_markup=main_menu_keyboard()
        )
        return

    # Normal users
    sent = bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    save_message(user["id"], cid, sent.message_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    sent2 = bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
    save_message(user["id"], cid, sent2.message_id)

# -------------------------
# Premium Menu Handler
# -------------------------
@bot.message_handler(func=lambda message: True)
def handle_menu(message):
    text = message.text
    chat_id = message.chat.id

    # Only premium users can access the menu
    uresp = supabase.table("users").select("*").eq("telegram_id", message.from_user.id).single().execute()
    user_row = uresp.data
    if not user_row or user_row.get("status") != "premium":
        return

    if text == "🔹 Programming Courses":
        bot.send_message(chat_id, "Select a course:", reply_markup=programming_courses_keyboard())
    elif text == "🔹 Hacking & Cybersecurity Courses":
        bot.send_message(chat_id, "Select a course:", reply_markup=hacking_courses_keyboard())
    elif text == "🔹 System & OS Courses":
        bot.send_message(chat_id, "Select a course:", reply_markup=system_os_courses_keyboard())
    elif text == "🔹 Special Cyber Tools Courses":
        bot.send_message(chat_id, "Select a course:", reply_markup=special_tools_courses_keyboard())
    elif text == "🔹 Premium Courses Bundle (31 Paid Courses)":
        bot.send_message(chat_id, "Select a course:", reply_markup=premium_courses_keyboard())
    elif text == "⬅ Back":
        bot.send_message(chat_id, "Main Menu:", reply_markup=main_menu_keyboard())
    else:
        course_links = {
            "C++": "https://link_to_cpp_course",
            "Java": "https://link_to_java_course",
            "Python": "https://link_to_python_course",
            "BlackHat Hacking": "https://link_to_blackhat_course",
            "Ethical Hacking": "https://link_to_ethical_course",
            "Linux": "https://link_to_linux_course",
            "Cyber Security": "https://link_to_cyber_course",
        }
        link = course_links.get(text)
        if link:
            bot.send_message(chat_id, f"Here is your course: {link}")

# -------------------------
# Payment Handlers
# -------------------------
# Keep all your existing handle_buy, handle_paid, handle_upload functions as-is

# -------------------------
# Admin Handlers
# -------------------------
# Keep all your admin /upgrade and /allpremiumuser functions as-is

# -------------------------
# Flask Routes
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    bot.remove_webhook()
    full_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    bot.set_webhook(url=full_url)
    return f"Webhook set to {full_url}", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

# -------------------------
# Auto Ping
# -------------------------
def auto_ping():
    while True:
        try:
            if WEBHOOK_URL:
                requests.get(WEBHOOK_URL, timeout=10)
        except Exception:
            pass
        time.sleep(300)

# -------------------------
# Run Locally
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
