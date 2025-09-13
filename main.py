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
UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")
_ADMIN_IDS_RAW = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ Missing required environment variables")

# Parse admin IDs
ADMIN_IDS = set()
for part in (_ADMIN_IDS_RAW or "").split(","):
    part = part.strip()
    if not part:
        continue
    try:
        ADMIN_IDS.add(int(part))
    except ValueError:
        pass

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

COURSES_MESSAGE = "📚 *GxNSS COURSES*\n\n...courses list..."
PROMO_MESSAGE = "🚀 *Huge Course Bundle – Just ₹79!* ...promo..."
PAYMENT_INSTRUCTIONS = f"🔔 *Payment Instructions*\n\nUPI: `{UPI_ID}`\n\n1. Scan QR or pay using UPI.\n2. Click *I Paid* to upload proof."

# -------------------------
# Helpers
# -------------------------
def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

def notify_admins(text):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass

def find_or_create_user(tid, username, first_name=None, last_name=None):
    tid = int(tid)
    resp = supabase.table("users").select("*").eq("telegram_id", tid).limit(1).execute()
    if resp.data:
        return resp.data[0]
    new_user = {
        "telegram_id": tid,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "status": "normal",
        "pending_upload": False,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    ins = supabase.table("users").insert(new_user).execute()
    return ins.data[0] if ins.data else None

def upload_to_supabase(bucket, object_path, file_bytes, content_type="image/jpeg"):
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
        "created_at": datetime.utcnow().isoformat()
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
    rows = supabase.table("messages").select("*").eq("user_id", user_row["id"]).execute().data or []
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
            "💲 We upgraded you to Premium User!\nClick /start to access your courses 🚀",
            parse_mode="Markdown"
        )
        save_message(user_row["id"], user_row["telegram_id"], sent.message_id)
    except Exception:
        pass

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

    if user.get("status") == "premium":
        sent = bot.send_message(cid, "🎉 Welcome back Premium User!\nPage 1 of your courses.", parse_mode="Markdown")
        save_message(user["id"], cid, sent.message_id)
        return

    sent = bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    save_message(user["id"], cid, sent.message_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    sent2 = bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
    save_message(user["id"], cid, sent2.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id, "Preparing payment…")
    instr_markup = types.InlineKeyboardMarkup()
    instr_markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))
    sent = bot.send_photo(
        cid,
        QR_IMAGE_URL + datetime.utcnow().strftime("%H%M%S"),
        caption=f"{PAYMENT_INSTRUCTIONS}\n\n👇 After payment, click below.",
        parse_mode="Markdown",
        reply_markup=instr_markup
    )
    user = supabase.table("users").select("*").eq("telegram_id", call.from_user.id).single().execute().data
    if user:
        save_message(user["id"], cid, sent.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "i_paid")
def handle_paid(call):
    cid = call.message.chat.id
    supabase.table("users").update({"pending_upload": True}).eq("telegram_id", call.from_user.id).execute()
    bot.answer_callback_query(call.id, "Upload screenshot now")
    sent = bot.send_message(cid, "✅ Please upload your payment screenshot here.")
    user = supabase.table("users").select("*").eq("telegram_id", call.from_user.id).single().execute().data
    if user:
        save_message(user["id"], cid, sent.message_id)

@bot.message_handler(content_types=["photo", "document"])
def handle_upload(message):
    user = message.from_user
    urow = supabase.table("users").select("*").eq("telegram_id", user.id).single().execute().data
    if not urow or not urow.get("pending_upload"):
        bot.reply_to(message, "⚠️ Click *I Paid* first.", parse_mode="Markdown")
        return

    fid = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
    file_info = bot.get_file(fid)
    file_bytes = bot.download_file(file_info.file_path)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
    object_path = f"{UPLOAD_FOLDER_PREFIX}/{user.id}_{ts}{ext}"
    _, url = upload_to_supabase(BUCKET_NAME, object_path, file_bytes)
    create_payment(urow, object_path, url, user.username or "")
    supabase.table("users").update({"pending_upload": False}).eq("telegram_id", user.id).execute()
    bot.send_message(message.chat.id, "❤️‍🔥 Payment screenshot received!\nAdmin will verify shortly.", parse_mode="Markdown")
    notify_admins(f"🆕 Payment uploaded by @{user.username or user.id}\nUserID: {urow['id']}\nURL: {url}")

# -------------------------
# Admin Flow
# -------------------------
@bot.message_handler(commands=["allpayments"])
def admin_allpayments(message):
    if not is_admin(message.from_user.id):
        return
    limit = 50
    page = 1
    offset = (page-1)*limit
    res = supabase.table("payments").select("*").order("created_at", desc=True).range(offset, offset+limit-1).execute()
    rows = res.data or []
    pending = [r for r in rows if r.get("verified") in (False, None) and r.get("user_id")]

    if not pending:
        bot.reply_to(message, "✅ No pending payments.")
        return

    msg = "📂 *Pending Payments:*\n\n"
    for r in pending:
        msg += f"UserID: {r.get('user_id')} | @{r.get('username','')}\nURL: {r.get('file_url')}\n\n"
    bot.reply_to(message, msg.strip(), parse_mode="Markdown", disable_web_page_preview=True)

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
        resp = supabase.table("users").select("*").eq("id", int(target)).limit(1).execute()
    else:
        resp = supabase.table("users").select("*").eq("username", target.lstrip("@")).limit(1).execute()

    user_row = (resp.data or [None])[0]
    if not user_row:
        bot.reply_to(message, f"❌ User {target} not found.")
        return
    if user_row.get("status")=="premium":
        bot.reply_to(message, f"✅ User {target} is already Premium.")
        return

    supabase.table("users").update({"status":"premium","updated_at":datetime.utcnow().isoformat()}).eq("id", user_row["id"]).execute()
    supabase.table("payments").update({"verified":True}).eq("user_id", user_row["id"]).execute()
    notify_user_upgrade(user_row)
    bot.reply_to(message, f"✅ User {target} upgraded to Premium!")

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
    return f"Webhook set to {WEBHOOK_URL}/{BOT_TOKEN}", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

# -------------------------
# Auto ping
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
if __name__ == "__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
