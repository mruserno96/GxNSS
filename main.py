import os
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
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN or not WEBHOOK_URL or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing required environment variables")

UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")

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
UPI_ID = "MillionaireNaitik69@fam"

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
        "status": "normal",  # new users are normal
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    ins = supabase.table("users").insert(new_user).execute()
    return ins.data[0] if ins.data else None


def upload_to_supabase(bucket, object_path, file_bytes, content_type="image/jpeg"):
    object_path = object_path.lstrip("/")
    storage = supabase.storage.from_(bucket)

    # delete existing file if present
    try:
        storage.remove([object_path])
    except Exception:
        pass

    try:
        # ✅ pass raw bytes (not BytesIO)
        storage.upload(
            object_path,
            file_bytes,
            {"content-type": content_type}
        )
    except Exception as e:
        logger.exception(f"Supabase upload failed: {e}")
        raise

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

# -------------------------
# Bot Handlers
# -------------------------
@bot.message_handler(commands=["start"])
def send_welcome(message):
    cid = message.chat.id
    user = find_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    if user and user.get("status") == "premium":
        bot.send_message(cid, "🎉 Welcome back Premium User!\n\nHere is *Page 1* of your courses.", parse_mode="Markdown")
        # TODO: send actual Page 1 content here
        return

    # For new or normal users
    bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)


# --- BUY flow: QR + Payment Instructions + Inline "I Paid" ---
@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id, "Preparing payment…")

    instr_markup = types.InlineKeyboardMarkup()
    instr_markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))

    caption = f"{PAYMENT_INSTRUCTIONS}\n\n👇 After payment, click the button below."

    bot.send_photo(
        cid,
        QR_IMAGE_URL,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=instr_markup
    )


@bot.callback_query_handler(func=lambda c: c.data == "i_paid")
def handle_paid(call):
    cid = call.message.chat.id
    bot.answer_callback_query(call.id, "Upload screenshot now")
    bot.send_message(cid, "✅ Please upload your payment screenshot here.\n\nMake sure the screenshot clearly shows the transaction details.")


# --- Upload handler ---
@bot.message_handler(content_types=["photo", "document"])
def handle_upload(message):
    user = message.from_user
    telegram_id = user.id
    username = user.username or ""
    fname = user.first_name or ""
    lname = user.last_name or ""

    urow = find_or_create_user(telegram_id, username, fname, lname)

    try:
        if message.content_type == "photo":
            fid = message.photo[-1].file_id
        else:
            fid = message.document.file_id

        file_info = bot.get_file(fid)
        file_bytes = bot.download_file(file_info.file_path)
    except Exception as e:
        logger.exception("Failed to download file from Telegram")
        bot.reply_to(message, "❌ Failed to download your screenshot. Please try again.")
        return

    try:
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
        object_path = f"{UPLOAD_FOLDER_PREFIX}/{telegram_id}_{ts}{ext}"
    except Exception as e:
        logger.exception("Failed to build object path")
        bot.reply_to(message, "❌ Internal error preparing upload.")
        return

    try:
        _, url = upload_to_supabase(BUCKET_NAME, object_path, file_bytes)
    except Exception as e:
        logger.exception("Supabase storage upload failed")
        bot.reply_to(message, f"❌ Upload failed. Error: {e}")
        return

    try:
        prow = create_payment(urow, object_path, url, username)
    except Exception as e:
        logger.exception("Failed to create payments row")
        bot.reply_to(message, "❌ Failed to record your payment. Please try again.")
        return

    bot.send_message(
        message.chat.id,
        f"❤️‍🔥 Payment screenshot received!\n\nAdmin will verify your payment shortly. "
        f"If approved, you'll be upgraded to Premium. 🚀\n\n[🔗 View your screenshot]({url})",
        parse_mode="Markdown",
        disable_web_page_preview=False
    )

    notify_admins(f"🆕 Payment uploaded by @{username or telegram_id}\nUserID: {urow['id']}\nURL: {url}")


# -------------------------
# Admin Commands
# -------------------------
@bot.message_handler(commands=["allpayments"])
def admin_allpayments(message):
    if str(message.from_user.id) not in ADMIN_TELEGRAM_IDS.split(","):
        return
    rows = supabase.table("payments").select("*").eq("verified", False).execute().data
    if not rows:
        bot.reply_to(message, "✅ No pending payments.")
        return
    msg = "📂 *Pending Payments:*\n\n"
    for r in rows:
        msg += f"UserID: {r['user_id']} | @{r['username']}\nURL: {r['file_url']}\n\n"
    bot.reply_to(message, msg, parse_mode="Markdown", disable_web_page_preview=True)


@bot.message_handler(commands=["verify"])
def admin_verify(message):
    if str(message.from_user.id) not in ADMIN_TELEGRAM_IDS.split(","):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /verify <user_id>")
        return
    uid = args[1]

    supabase.table("payments").update({"verified": True}).eq("user_id", uid).execute()
    supabase.table("users").update({"status": "premium"}).eq("id", uid).execute()
    bot.reply_to(message, f"✅ User {uid} upgraded to Premium!")


@bot.message_handler(commands=["upgrade"])
def admin_upgrade(message):
    if str(message.from_user.id) not in ADMIN_TELEGRAM_IDS.split(","):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /upgrade <user_id_or_username>")
        return
    target = args[1]

    if target.isdigit():
        supabase.table("users").update({"status": "premium"}).eq("id", target).execute()
    else:
        supabase.table("users").update({"status": "premium"}).eq("username", target).execute()
    bot.reply_to(message, f"✅ User {target} upgraded to Premium!")


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
