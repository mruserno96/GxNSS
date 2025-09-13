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
# Load env
# -------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")
ADMIN_IDS_RAW = os.getenv("ADMIN_TELEGRAM_IDS", "")
UPLOAD_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ Missing required environment variables")

# Admin IDs as int set
ADMIN_IDS = set()
for aid in ADMIN_IDS_RAW.split(","):
    aid = aid.strip()
    if aid:
        try:
            ADMIN_IDS.add(int(aid))
        except ValueError:
            pass

# -------------------------
# Setup
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Constants
# -------------------------
UPI_ID = "MillionaireNaitik69@fam"
QR_URL = "https://mruser96.42web.io/qr.jpg?nocache="
COURSES_MSG = "📚 *GxNSS COURSES*\n\nCourses here..."
PROMO_MSG = "🚀 *Huge Course Bundle – Just ₹79!*"
PAY_INSTRUCTIONS = f"🔔 *Payment Instructions*\nUPI: `{UPI_ID}`\nUpload screenshot after payment."

# -------------------------
# Helpers
# -------------------------
def is_admin(uid):
    return uid in ADMIN_IDS

def notify_admins(text):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass

def find_or_create_user(tid, username, fname=None, lname=None):
    resp = supabase.table("users").select("*").eq("telegram_id", tid).limit(1).execute()
    if resp.data:
        return resp.data[0]
    user = {
        "telegram_id": tid,
        "username": username,
        "first_name": fname,
        "last_name": lname,
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
    try: storage.remove([path])
    except: pass
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
        bot.send_message(user_row["telegram_id"], "💲 You are now Premium! Click /start.", parse_mode="Markdown")
    except Exception:
        pass

# -------------------------
# User Flow
# -------------------------
@bot.message_handler(commands=["start"])
def start_cmd(msg):
    cid = msg.chat.id
    user = find_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
    if user.get("status")=="premium":
        bot.send_message(cid, "🎉 Welcome back Premium User!", parse_mode="Markdown")
        return
    bot.send_message(cid, COURSES_MSG, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course ₹79", callback_data="buy"))
    bot.send_message(cid, PROMO_MSG, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(lambda c: c.data=="buy")
def buy_cb(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))
    bot.send_photo(cid, QR_URL+datetime.utcnow().strftime("%H%M%S"), caption=PAY_INSTRUCTIONS, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(lambda c: c.data=="i_paid")
def i_paid_cb(call):
    supabase.table("users").update({"pending_upload": True}).eq("telegram_id", call.from_user.id).execute()
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "✅ Upload your payment screenshot now.")

@bot.message_handler(content_types=["photo","document"])
def handle_upload(msg):
    urow = supabase.table("users").select("*").eq("telegram_id", msg.from_user.id).single().execute().data
    if not urow or not urow.get("pending_upload"):
        bot.reply_to(msg, "⚠️ Click 'I Paid' before uploading.", parse_mode="Markdown")
        return
    fid = msg.photo[-1].file_id if msg.content_type=="photo" else msg.document.file_id
    file_info = bot.get_file(fid)
    file_bytes = bot.download_file(file_info.file_path)
    ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
    path = f"{UPLOAD_PREFIX}/{msg.from_user.id}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}{ext}"
    _, url = upload_to_supabase(BUCKET_NAME, path, file_bytes)
    create_payment(urow, path, url, msg.from_user.username or "")
    supabase.table("users").update({"pending_upload": False}).eq("telegram_id", msg.from_user.id).execute()
    bot.send_message(msg.chat.id, "✅ Screenshot received! Admin will verify.", parse_mode="Markdown")
    notify_admins(f"🆕 Payment uploaded by @{msg.from_user.username or msg.from_user.id}\nUserID:{urow['id']}\nURL:{url}")

# -------------------------
# Admin Flow (Fast + Pagination)
# -------------------------
def fetch_pending_payments(limit=50, page=1):
    offset = (page-1)*limit
    res = supabase.table("payments").select("*").order("created_at", desc=True).range(offset, offset+limit-1).execute()
    rows = res.data or []
    pending = [r for r in rows if not r.get("verified", False)]
    return pending

@bot.message_handler(commands=["allpayments"])
def admin_allpayments(msg):
    if not is_admin(msg.from_user.id):
        return
    page = 1
    if " " in msg.text:
        try: page = int(msg.text.split()[1])
        except: page=1
    pending = fetch_pending_payments(limit=20, page=page)
    if not pending:
        bot.reply_to(msg, "✅ No pending payments.")
        return
    text = f"📂 *Pending Payments* (Page {page}):\n\n"
    for r in pending:
        text += f"UserID:{r['user_id']} | @{r.get('username','')}\nURL:{r['file_url']}\n\n"
    text += "\nUse `/allpayments <page>` to see next page."
    bot.reply_to(msg, text.strip(), parse_mode="Markdown", disable_web_page_preview=True)

@bot.message_handler(commands=["upgrade"])
def admin_upgrade(msg):
    if not is_admin(msg.from_user.id): return
    args = msg.text.split()
    if len(args)<2: return bot.reply_to(msg, "Usage: /upgrade <user_id|username>")
    target = args[1].lstrip("@")
    resp = supabase.table("users").select("*").eq("username", target).limit(1).execute() if not target.isdigit() else supabase.table("users").select("*").eq("id", int(target)).limit(1).execute()
    user_row = (resp.data or [None])[0]
    if not user_row: return bot.reply_to(msg, "❌ User not found.")
    if user_row.get("status")=="premium": return bot.reply_to(msg, "✅ Already Premium")
    supabase.table("users").update({"status":"premium","updated_at":datetime.utcnow().isoformat()}).eq("id", user_row["id"]).execute()
    supabase.table("payments").update({"verified":True}).eq("user_id", user_row["id"]).execute()
    notify_user_upgrade(user_row)
    bot.reply_to(msg, f"✅ User upgraded to Premium!")

@bot.message_handler(commands=["allpremiumuser"])
def admin_allpremium(msg):
    if not is_admin(msg.from_user.id): return
    rows = supabase.table("users").select("*").eq("status","premium").execute().data or []
    if not rows: return bot.reply_to(msg,"❌ No Premium users.")
    text = "💎 *Premium Users:*\n\n"
    for u in rows:
        text += f"ID:{u['id']} | TelegramID:{u['telegram_id']} | Username:@{u.get('username','N/A')}\n\n"
    bot.reply_to(msg,text.strip(),parse_mode="Markdown")

# -------------------------
# Flask Webhook
# -------------------------
@app.route("/", methods=["GET"])
def index(): return "Bot running",200
@app.route("/set_webhook", methods=["GET"])
def set_webhook(): bot.remove_webhook(); bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}"); return f"Webhook set: {WEBHOOK_URL}/{BOT_TOKEN}",200
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook(): 
    if request.headers.get("content-type")!="application/json": abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK",200

# -------------------------
# Auto Ping
# -------------------------
def auto_ping():
    while True:
        try:
            if WEBHOOK_URL: requests.get(WEBHOOK_URL,timeout=10)
        except: pass
        time.sleep(300)

# -------------------------
# Run
# -------------------------
if __name__=="__main__":
    threading.Thread(target=auto_ping,daemon=True).start()
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)))
