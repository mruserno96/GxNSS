import os
import logging
import threading
import time
from datetime import datetime
from flask import Flask, request, abort
import telebot
from telebot import types
from supabase import create_client, Client
from dotenv import load_dotenv
import requests

# -------------------------
# Load environment
# -------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")
ADMIN_IDS_RAW = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ Missing required environment variables")

# Parse admin IDs
ADMIN_IDS = set()
for aid in ADMIN_IDS_RAW.split(","):
    aid = aid.strip()
    if aid:
        try:
            ADMIN_IDS.add(int(aid))
        except ValueError:
            pass

UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")

# -------------------------
# Setup
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)  # webhook mode, no threading
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Constants
# -------------------------
UPI_ID = "MillionaireNaitik69@fam"
QR_IMAGE_URL = "https://mruser96.42web.io/qr.jpg?nocache="

COURSES_MESSAGE = "📚 *GxNSS COURSES*\n\nCourses here..."  # truncated for brevity
PROMO_MESSAGE = "🚀 *Huge Course Bundle – Just ₹79!*"
PAYMENT_INSTRUCTIONS = f"🔔 *Payment Instructions*\nUPI: `{UPI_ID}`\nUpload screenshot after payment."

# -------------------------
# Helpers
# -------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def notify_admins(text):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass

def find_or_create_user(tid, username, first_name=None, last_name=None):
    resp = supabase.table("users").select("*").eq("telegram_id", tid).limit(1).execute()
    if resp.data:
        return resp.data[0]
    user = {
        "telegram_id": tid,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "status": "normal",
        "pending_upload": False,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = supabase.table("users").insert(user).execute()
    return res.data[0] if res.data else None

def upload_to_supabase(bucket, path, file_bytes, content_type="image/jpeg"):
    path = path.lstrip("/")
    storage = supabase.storage.from_(bucket)
    try:
        storage.remove([path])
    except Exception:
        pass
    storage.upload(path, file_bytes, {"content-type": content_type})
    return path, storage.get_public_url(path)

def create_payment(user_row, file_path, file_url, username):
    payload = {
        "user_id": user_row["id"],
        "username": username,
        "file_path": file_path,
        "file_url": file_url,
        "verified": False,
        "created_at": datetime.utcnow().isoformat()
    }
    res = supabase.table("payments").insert(payload).execute()
    return res.data[0] if res.data else None

def notify_user_upgrade(user_row):
    try:
        bot.send_message(user_row["telegram_id"], "💲 You are upgraded to Premium! Click /start.", parse_mode="Markdown")
    except Exception:
        pass

# -------------------------
# User Flow
# -------------------------
@bot.message_handler(commands=["start"])
def start_cmd(msg):
    cid = msg.chat.id
    user = find_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
    if user.get("status") == "premium":
        bot.send_message(cid, "🎉 Welcome back Premium User!", parse_mode="Markdown")
        return
    bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course ₹79", callback_data="buy"))
    bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(lambda c: c.data=="buy")
def buy_cb(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))
    bot.send_photo(cid, QR_IMAGE_URL+datetime.utcnow().strftime("%H%M%S"), caption=PAYMENT_INSTRUCTIONS, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(lambda c: c.data=="i_paid")
def i_paid_cb(call):
    cid = call.message.chat.id
    supabase.table("users").update({"pending_upload": True}).eq("telegram_id", call.from_user.id).execute()
    bot.answer_callback_query(call.id)
    bot.send_message(cid, "✅ Upload your payment screenshot now.")

@bot.message_handler(content_types=["photo","document"])
def handle_upload(msg):
    user_row = supabase.table("users").select("*").eq("telegram_id", msg.from_user.id).single().execute().data
    if not user_row or not user_row.get("pending_upload"):
        bot.reply_to(msg, "⚠️ Click 'I Paid' before uploading.")
        return
    try:
        fid = msg.photo[-1].file_id if msg.content_type=="photo" else msg.document.file_id
        file_info = bot.get_file(fid)
        file_bytes = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
        path = f"{UPLOAD_FOLDER_PREFIX}/{msg.from_user.id}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}{ext}"
        _, url = upload_to_supabase(BUCKET_NAME, path, file_bytes)
        create_payment(user_row, path, url, msg.from_user.username or "")
        supabase.table("users").update({"pending_upload": False}).eq("telegram_id", msg.from_user.id).execute()
        bot.send_message(msg.chat.id, "✅ Screenshot received! Admin will verify.", parse_mode="Markdown")
        notify_admins(f"🆕 Payment uploaded by @{msg.from_user.username or msg.from_user.id}\nUserID:{user_row['id']}\nURL:{url}")
    except Exception:
        bot.reply_to(msg, "❌ Upload failed. Try again.")

# -------------------------
# Admin Flow
# -------------------------
@bot.message_handler(commands=["allpayments"])
def admin_allpayments(msg):
    if not is_admin(msg.from_user.id): return
    rows = supabase.table("payments").select("*").order("created_at", desc=True).execute().data or []
    pending = [r for r in rows if not r.get("verified", False)]
    if not pending:
        bot.reply_to(msg, "✅ No pending payments.")
        return
    text = "📂 *Pending Payments:*\n\n"
    for r in pending:
        text += f"UserID: {r['user_id']} | @{r.get('username','')}\nURL: {r['file_url']}\n\n"
    bot.reply_to(msg, text.strip(), parse_mode="Markdown", disable_web_page_preview=True)

@bot.message_handler(commands=["upgrade"])
def admin_upgrade(msg):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args)<2:
        bot.reply_to(msg, "Usage: /upgrade <user_id|username>")
        return
    target = args[1]
    if target.isdigit():
        resp = supabase.table("users").select("*").eq("id", int(target)).limit(1).execute()
    else:
        resp = supabase.table("users").select("*").eq("username", target.lstrip("@")).limit(1).execute()
    user_row = (resp.data or [None])[0]
    if not user_row:
        bot.reply_to(msg, "❌ User not found.")
        return
    if user_row.get("status")=="premium":
        bot.reply_to(msg, "✅ Already Premium.")
        return
    supabase.table("users").update({"status":"premium"}).eq("id", user_row["id"]).execute()
    supabase.table("payments").update({"verified": True}).eq("user_id", user_row["id"]).execute()
    notify_user_upgrade(user_row)
    bot.reply_to(msg, "✅ User upgraded to Premium.")

@bot.message_handler(commands=["allpremiumuser"])
def admin_allpremium(msg):
    if not is_admin(msg.from_user.id): return
    rows = supabase.table("users").select("*").eq("status","premium").execute().data or []
    if not rows:
        bot.reply_to(msg, "❌ No Premium users.")
        return
    text = "💎 *Premium Users:*\n\n"
    for u in rows:
        text += f"ID:{u.get('id')}\nTelegramID:{u.get('telegram_id')}\nUsername:@{u.get('username','N/A')}\n\n"
    bot.reply_to(msg, text.strip(), parse_mode="Markdown")

# -------------------------
# Flask Routes
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    return f"Webhook set: {WEBHOOK_URL}/{BOT_TOKEN}", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
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
# Run
# -------------------------
if __name__=="__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
