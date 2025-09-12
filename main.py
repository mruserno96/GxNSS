import os
import io
import logging
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")  # e.g. https://yourapp.onrender.com
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")
PRIVATE_BUCKET = os.getenv("PRIVATE_BUCKET", "false").lower() in ("1", "true", "yes")
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing required environment variables")

UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")
SIGNED_URL_TTL_SECONDS = int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))

# -------------------------
# Setup
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Constants
# -------------------------
QR_IMAGE_URL = "https://mruser96.42web.io/qr.jpg"
UPI_ID = "MillionaireNaitik69@fam"   # ✅ updated UPI

COURSES_MESSAGE = (
    "📚 *GxNSS COURSES*\n\n"
    "🔹 *Programming*\n• C++\n• Java\n• JavaScript\n• Python\n\n"
    "🔹 *Hacking & Cybersecurity*\n• BlackHat\n• Ethical Hacking\n• Android Hacking\n• WiFi Hacking\n"
    "• Antivirus Development\n• Phishing App Development\n• PUBG Hack Development\n• APK Modding (20+)\n\n"
    "🔹 *System & OS*\n• Linux\n• PowerShell\n\n"
    "🔹 *Special Tools*\n• Telegram Number\n• Lifetime RDP\n• Call Any Number Free\n• SMS Bomber\n• Temp Mail Bot\n\n"
    "🔹 *Premium Bundle (31 Courses)*"
)

PROMO_MESSAGE = (
    "🚀 *Huge Course Bundle – Just ₹79!* (Originally ₹199)\n\n"
    "Get 30+ premium courses with guaranteed results. Don’t miss this offer!"
)

PAYMENT_INSTRUCTIONS = (
    f"🔔 *Payment Instructions*\n\n"
    f"UPI: `{UPI_ID}`\n\n"
    "1. Scan the QR or pay using the UPI above.\n"
    "2. Upload your payment screenshot here.\n\n"
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
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    ins = supabase.table("users").insert(new_user).execute()
    return ins.data[0] if ins.data else None

def upload_to_supabase(bucket, object_path, file_bytes, content_type="image/jpeg"):
    object_path = object_path.lstrip("/")
    supabase.storage.from_(bucket).upload(object_path, io.BytesIO(file_bytes), {"content-type": content_type})
    if PRIVATE_BUCKET:
        signed_resp = supabase.storage.from_(bucket).create_signed_url(object_path, SIGNED_URL_TTL_SECONDS)
        return object_path, signed_resp.get("signedURL") or signed_resp.get("signed_url")
    else:
        return object_path, supabase.storage.from_(bucket).get_public_url(object_path)

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
            bot.send_message(int(aid.strip()), text)
        except Exception:
            pass

# -------------------------
# Bot Handlers
# -------------------------
@bot.message_handler(commands=["start"])
def send_welcome(message):
    cid = message.chat.id
    bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))
    bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id, "Preparing payment…")
    bot.send_photo(cid, QR_IMAGE_URL, caption=f"Scan QR or pay to UPI: `{UPI_ID}`", parse_mode="Markdown")
    bot.send_message(cid, PAYMENT_INSTRUCTIONS, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "i_paid")
def handle_paid(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id, "Upload screenshot now")
    bot.send_message(cid, "✅ Please upload your payment screenshot here.")

@bot.message_handler(content_types=["photo", "document"])
def handle_upload(message):
    cid = message.chat.id
    user = message.from_user
    username = user.username
    fname = user.first_name
    lname = user.last_name

    # get file
    fid = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
    file_info = bot.get_file(fid)
    file_bytes = bot.download_file(file_info.file_path)

    # user + upload
    urow = find_or_create_user(cid, username, fname, lname)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
    object_path = f"{UPLOAD_FOLDER_PREFIX}/{cid}_{ts}{ext}"
    _, url = upload_to_supabase(BUCKET_NAME, object_path, file_bytes)

    prow = create_payment(urow, object_path, url, username)

    # ✅ Success message to user
    bot.send_message(
        cid,
        "❤️‍🔥 Please wait some time…\n\nAdmin will verify your payment.\n"
        "After verification, you can use your bot features. 🚀"
    )

    # notify admins
    notify_admins(f"🆕 Payment uploaded by {username or cid}\nUserID: {urow['id']}\nURL: {url}")

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
# Run Locally
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
