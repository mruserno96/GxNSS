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
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ Missing required environment variables")

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
    f"UPI: `{UPI_ID}`\n\n"
    "1. Scan the QR or pay using the UPI above.\n"
    "2. Click *I Paid (Upload Screenshot)* below to upload proof.\n\n"
    "We’ll verify and grant access."
)

# -------------------------
# DB Helpers
# -------------------------
def find_or_create_user(telegram_id, username, first_name=None, last_name=None):
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
    return supabase.table("payments").insert(payload).execute().data[0]


def notify_admins(text):
    if not ADMIN_TELEGRAM_IDS:
        return
    for aid in ADMIN_TELEGRAM_IDS.split(","):
        try:
            bot.send_message(int(aid.strip()), text, disable_web_page_preview=True)
        except Exception:
            pass


def is_admin(user_id: int) -> bool:
    return str(user_id) in ADMIN_TELEGRAM_IDS.split(",")


def notify_user_upgrade(user_row):
    try:
        bot.send_message(
            user_row["telegram_id"],
            "💲 We upgraded you to Premium User!\n\nClick /start to access your courses 🚀",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# -------------------------
# Message Tracking
# -------------------------
def send_and_track(user_id, chat_id, text=None, photo=None, **kwargs):
    if photo:
        msg = bot.send_photo(chat_id, photo, caption=text, **kwargs)
    else:
        msg = bot.send_message(chat_id, text, **kwargs)

    supabase.table("messages").insert({
        "user_id": user_id,
        "telegram_id": chat_id,
        "message_id": msg.message_id
    }).execute()
    return msg


def delete_user_messages(user_row):
    rows = supabase.table("messages").select("*").eq("user_id", user_row["id"]).execute().data
    for r in rows:
        try:
            bot.delete_message(r["telegram_id"], r["message_id"])
        except Exception:
            pass
    supabase.table("messages").delete().eq("user_id", user_row["id"]).execute()


# -------------------------
# User Flow
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
        send_and_track(user["id"], cid, text="🎉 Welcome back Premium User!\n\nHere is *Page 1* of your courses.", parse_mode="Markdown")
        return

    send_and_track(user["id"], cid, text=COURSES_MESSAGE, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    send_and_track(user["id"], cid, text=PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    cid = call.message.chat.id
    user = supabase.table("users").select("*").eq("telegram_id", call.from_user.id).single().execute().data
    bot.answer_callback_query(call.id, "Preparing payment…")

    instr_markup = types.InlineKeyboardMarkup()
    instr_markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))

    caption = f"{PAYMENT_INSTRUCTIONS}\n\n👇 After payment, click the button below."

    send_and_track(user["id"], cid,
                   text=caption,
                   photo=QR_IMAGE_URL + datetime.utcnow().strftime("%H%M%S"),
                   parse_mode="Markdown",
                   reply_markup=instr_markup)


@bot.callback_query_handler(func=lambda c: c.data == "i_paid")
def handle_paid(call):
    cid = call.message.chat.id
    supabase.table("users").update({"pending_upload": True}).eq("telegram_id", call.from_user.id).execute()
    bot.answer_callback_query(call.id, "Upload screenshot now")
    send_and_track(None, cid, text="✅ Please upload your payment screenshot here.\n\nMake sure the screenshot clearly shows the transaction details.")


@bot.message_handler(content_types=["photo", "document"])
def handle_upload(message):
    user = message.from_user
    urow = supabase.table("users").select("*").eq("telegram_id", user.id).single().execute().data
    if not urow or not urow.get("pending_upload"):
        bot.reply_to(message, "⚠️ Please click *I Paid (Upload Screenshot)* before sending a screenshot.")
        return

    try:
        fid = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
        file_info = bot.get_file(fid)
        file_bytes = bot.download_file(file_info.file_path)
    except Exception:
        bot.reply_to(message, "❌ Failed to download your screenshot. Please try again.")
        return

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
    object_path = f"{UPLOAD_FOLDER_PREFIX}/{user.id}_{ts}{ext}"

    try:
        _, url = upload_to_supabase(BUCKET_NAME, object_path, file_bytes)
    except Exception as e:
        bot.reply_to(message, f"❌ Upload failed. Error: {e}")
        return

    try:
        create_payment(urow, object_path, url, user.username or "")
    except Exception:
        bot.reply_to(message, "❌ Failed to record your payment. Please try again.")
        return

    supabase.table("users").update({"pending_upload": False}).eq("telegram_id", user.id).execute()

    send_and_track(urow["id"], message.chat.id,
                   text="❤️‍🔥 Payment screenshot received!\n\nAdmin will verify your payment shortly. If approved, you'll be upgraded to Premium. 🚀",
                   parse_mode="Markdown")
    notify_admins(f"🆕 Payment uploaded by @{user.username or user.id}\nUserID: {urow['id']}\nURL: {url}")


# -------------------------
# Admin Flow
# -------------------------
@bot.message_handler(commands=["admin"])
def admin_help(message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, (
        "👮 *Admin Commands*\n\n"
        "/allpayments – View pending payments\n"
        "/upgrade <userid|username> – Upgrade manually\n"
        "/allpremiumuser – View all Premium users"
    ), parse_mode="Markdown")


@bot.message_handler(commands=["allpayments"])
def admin_allpayments(message):
    if not is_admin(message.from_user.id):
        return
    rows = supabase.table("payments").select("*").eq("verified", False).execute().data or []
    if not rows:
        bot.reply_to(message, "✅ No pending payments.")
        return
    msg = "📂 *Pending Payments:*\n\n"
    for r in rows:
        msg += f"UserID: {r['user_id']} | @{r.get('username','')}\nURL: {r['file_url']}\n\n"
    bot.reply_to(message, msg.strip(), parse_mode="Markdown", disable_web_page_preview=True)


@bot.message_handler(commands=["allpremiumuser"])
def admin_allpremiumuser(message):
    if not is_admin(message.from_user.id):
        return
    rows = supabase.table("users").select("*").eq("status", "premium").execute().data or []
    if not rows:
        bot.reply_to(message, "❌ No Premium users found.")
        return
    msg = "💎 *Premium Users:*\n\n"
    for u in rows:
        msg += (
            f"ID: {u.get('id')}\n"
            f"TelegramID: {u.get('telegram_id')}\n"
            f"Username: @{u.get('username') or 'N/A'}\n"
            f"Name: {u.get('first_name','')} {u.get('last_name','')}\n"
            f"Status: {u.get('status')}\n"
            f"Created: {u.get('created_at')}\n\n"
        )
    bot.reply_to(message, msg.strip(), parse_mode="Markdown")


@bot.message_handler(commands=["upgrade"])
def admin_upgrade(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /upgrade <user_id|username>")
        return
    target = args[1]

    if target.isdigit():
        data = supabase.table("users").update({"status": "premium"}).eq("id", target).execute().data
        user_row = data[0] if data else None
        supabase.table("payments").update({"verified": True}).eq("user_id", target).execute()
    else:
        data = supabase.table("users").update({"status": "premium"}).eq("username", target).execute().data
        user_row = data[0] if data else None
        supabase.table("payments").update({"verified": True}).eq("username", target).execute()

    if user_row:
        # Delete old messages
        delete_user_messages(user_row)

        # Send fresh premium message
        send_and_track(user_row["id"], user_row["telegram_id"],
                       text="💎 Welcome to *Premium*! Here are your exclusive courses 🚀",
                       parse_mode="Markdown")

        bot.reply_to(message, f"✅ User {target} upgraded and old messages deleted!")
        notify_user_upgrade(user_row)
    else:
        bot.reply_to(message, f"❌ User {target} not found.")


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
# Auto Ping (Prevent Sleep)
# -------------------------
def auto_ping():
    while True:
        try:
            url = WEBHOOK_URL or ""
            if url:
                requests.get(url, timeout=10)
                logger.info("🔄 Auto-ping successful")
        except Exception as e:
            logger.warning(f"⚠️ Auto-ping failed: {e}")
        time.sleep(300)  # 5 minutes


# -------------------------
# Run Locally
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
