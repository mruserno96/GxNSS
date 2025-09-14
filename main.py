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
    f"UPI: `{UPI_ID}`\n\n"
    "1. Scan the QR or pay using the UPI above.\n"
    "2. Click *I Paid (Upload Screenshot)* below to upload proof.\n\n"
    "We’ll verify and grant access."
)

# -------------------------
# Small in-memory cache to reduce DB calls (helps on free hosts)
# -------------------------
USER_CACHE = {}  # telegram_id -> (status, expire_ts)
USER_CACHE_TTL = 30  # seconds

def get_user_cached(telegram_id):
    """Return user row from cache or DB. Cache only status and id for speed."""
    now = time.time()
    cached = USER_CACHE.get(telegram_id)
    if cached:
        status, expire_ts, user_row = cached
        if expire_ts > now:
            return user_row
        else:
            USER_CACHE.pop(telegram_id, None)
    # fallback to DB
    try:
        resp = supabase.table("users").select("*").eq("telegram_id", int(telegram_id)).single().execute()
        user_row = resp.data
    except Exception:
        user_row = None
    # cache minimal info for short time
    expire_ts = now + USER_CACHE_TTL
    USER_CACHE[telegram_id] = (user_row.get("status") if user_row else None, expire_ts, user_row)
    return user_row

def invalidate_user_cache(telegram_id):
    USER_CACHE.pop(telegram_id, None)

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
    if resp and resp.data:
        user = resp.data[0]
        # cache
        USER_CACHE[telegram_id] = (user.get("status"), time.time() + USER_CACHE_TTL, user)
        return user
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
    user = ins.data[0] if ins.data else None
    if user:
        USER_CACHE[telegram_id] = (user.get("status"), time.time() + USER_CACHE_TTL, user)
    return user

def upload_to_supabase(bucket, object_path, file_bytes, content_type="image/jpeg"):
    object_path = object_path.lstrip("/")
    storage = supabase.storage.from_(bucket)
    try:
        # remove existing if any
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
    try:
        rows = supabase.table("messages").select("*").eq("user_id", user_row["id"]).execute().data or []
        for r in rows:
            try:
                bot.delete_message(r["chat_id"], r["message_id"])
            except Exception:
                pass
        supabase.table("messages").delete().eq("user_id", user_row["id"]).execute()
    except Exception:
        pass

def notify_user_upgrade(user_row):
    try:
        delete_old_messages(user_row)
        sent = bot.send_message(
            user_row["telegram_id"],
            "💲 We upgraded you to Premium User!\n\nClick /start to access your courses 🚀",
            parse_mode="Markdown"
        )
        save_message(user_row["id"], user_row["telegram_id"], sent.message_id)
        # Invalidate cache so /start shows premium menu next time
        invalidate_user_cache(user_row["telegram_id"])
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
        # Directly show premium menu keyboard
        bot.send_message(
            cid,
            "🎉 Welcome back Premium User!",
            reply_markup=main_menu_keyboard()
        )
        return

    # Normal users: unchanged promo/payment flow
    sent = bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
    try:
        save_message(user["id"], cid, sent.message_id)
    except Exception:
        pass

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
    sent2 = bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
    try:
        save_message(user["id"], cid, sent2.message_id)
    except Exception:
        pass

# -------------------------
# Inline callback handlers (Buy + I Paid)
# -------------------------
@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    try:
        bot.answer_callback_query(call.id, "Preparing payment…")
    except Exception:
        pass

    cid = call.message.chat.id
    instr_markup = types.InlineKeyboardMarkup()
    instr_markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))

    caption = f"{PAYMENT_INSTRUCTIONS}\n\n👇 After payment, click the button below."

    try:
        sent = bot.send_photo(
            cid,
            QR_IMAGE_URL + datetime.utcnow().strftime("%H%M%S"),
            caption=caption,
            parse_mode="Markdown",
            reply_markup=instr_markup
        )
        # Save message for deletion later if user exists
        user = get_user_cached(call.from_user.id) or supabase.table("users").select("*").eq("telegram_id", call.from_user.id).single().execute().data
        if user:
            try:
                save_message(user["id"], cid, sent.message_id)
            except Exception:
                pass
    except Exception as e:
        try:
            bot.send_message(cid, "❌ Failed to send QR image. Please try again.")
        except Exception:
            pass
        logger.exception("handle_buy error: %s", e)

@bot.callback_query_handler(func=lambda c: c.data == "i_paid")
def handle_paid(call):
    try:
        bot.answer_callback_query(call.id, "Upload screenshot now")
    except Exception:
        pass

    cid = call.message.chat.id
    try:
        supabase.table("users").update({"pending_upload": True}).eq("telegram_id", call.from_user.id).execute()
    except Exception:
        pass

    sent = bot.send_message(cid, "✅ Please upload your payment screenshot here.\n\nMake sure the screenshot clearly shows the transaction details.")
    try:
        user = get_user_cached(call.from_user.id) or supabase.table("users").select("*").eq("telegram_id", call.from_user.id).single().execute().data
        if user:
            save_message(user["id"], cid, sent.message_id)
    except Exception:
        pass

# -------------------------
# Upload handler (photo/document)
# -------------------------
@bot.message_handler(content_types=["photo", "document"])
def handle_upload(message):
    user = message.from_user
    try:
        t_id = int(user.id)
    except Exception:
        t_id = user.id

    try:
        uresp = supabase.table("users").select("*").eq("telegram_id", t_id).single().execute()
        urow = uresp.data
    except Exception:
        urow = None

    if not urow or not urow.get("pending_upload"):
        bot.reply_to(message, "⚠️ Please click *I Paid (Upload Screenshot)* before sending a screenshot.", parse_mode="Markdown")
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

    try:
        supabase.table("users").update({"pending_upload": False}).eq("telegram_id", user.id).execute()
    except Exception:
        pass

    bot.send_message(
        message.chat.id,
        "❤️‍🔥 Payment screenshot received!\n\n"
        "Admin will verify your payment shortly. If approved, you'll be upgraded to Premium. 🚀",
        parse_mode="Markdown"
    )
    notify_admins(f"🆕 Payment uploaded by @{user.username or user.id}\nUserID: {urow.get('id')}\nURL: {url}")

# -------------------------
# /admin and admin helpers
# -------------------------
@bot.message_handler(commands=["admin"])
def admin_help(message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, (
        "👮 *Admin Commands*\n\n"
        "/upgrade <userid|username> – Upgrade manually\n"
        "/allpremiumuser – View all Premium users"
    ), parse_mode="Markdown")

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

    try:
        if target.isdigit():
            resp = supabase.table("users").select("*").eq("id", int(target)).limit(1).execute()
        else:
            username_lookup = target.lstrip("@")
            resp = supabase.table("users").select("*").eq("username", username_lookup).limit(1).execute()
    except Exception:
        bot.reply_to(message, "❌ Database error while searching for user.")
        return

    user_row = (resp.data or [None])[0]
    if not user_row:
        bot.reply_to(message, f"❌ User {target} not found.")
        return

    if user_row.get("status") == "premium":
        bot.reply_to(message, f"✅ User {target} is already Premium.")
        return

    try:
        supabase.table("users").update({"status": "premium", "updated_at": datetime.utcnow().isoformat()}).eq("id", user_row["id"]).execute()
        supabase.table("payments").update({"verified": True}).eq("user_id", user_row["id"]).execute()
        invalidate_user_cache(user_row["telegram_id"])
    except Exception:
        bot.reply_to(message, f"❌ Failed to upgrade {target}.")
        return

    notify_user_upgrade(user_row)
    bot.reply_to(message, f"✅ User {target} upgraded to Premium!")

# -------------------------
# -------------------------
# Premium Menu Handler
# -------------------------
@bot.message_handler(func=lambda message: True)
def handle_menu(message):
    text = message.text
    chat_id = message.chat.id

    user_row = get_user_cached(message.from_user.id)
    if not user_row:
        try:
            uresp = supabase.table("users").select("*").eq("telegram_id", message.from_user.id).single().execute()
            user_row = uresp.data
            if user_row:
                USER_CACHE[message.from_user.id] = (user_row.get("status"), time.time()+USER_CACHE_TTL, user_row)
        except Exception:
            user_row = None

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
    elif text == "⬅ Back":
        bot.send_message(chat_id, "Main Menu:", reply_markup=main_menu_keyboard())
    else:
        course = COURSE_DATA.get(text)
        if course:
            msg = f"{course['description']}\n\n🔗 Download: {course['link']}"
            bot.send_message(chat_id, msg)
        else:
            bot.send_message(chat_id, "⚠️ This course is not available yet.")

# -------------------------
# External Course Hosting Map
# -------------------------
COURSE_DATA = {
    "C++": {
        "description": (
            "👩‍💻 C++ Programming for Beginners - From Beginner to Beyond 👩‍💻\n\n"
            "🥵 What you'll learn​:-) \n\n"
            "🚩 Learn to program with one of the most powerful programming languages that exists today, C++.\n\n"
            "🚩 Obtain the key concepts of programming that will also apply to other programming languages.\n\n"
            "🚩 Learn Modern C++ rather than an obsolete version of C++ that most other courses teach.\n\n"
            "🚩 Learn C++ features from basic to more advanced such as inheritance and polymorphic functions.\n\n"
            "🚩 Learn C++ using a proven curriculum that covers more material than most C++ university courses.\n\n"
            "🚩 Learn C++ from an experienced university full professor who has been using and teaching C++ for more than 25 years.\n\n"
            "🚩 Includes Quizzes, Live Coding Exercises, Challenge Coding Exercises and Assignments.\n\n"
            "👥 Size:-) 2.44 GB\n"
            "⏳ Time:-) 31:07:29"
        ),
        "link": "https://drive.google.com/file/d/1Ur5T9dGb_e5EBNJzpTg08ieSHKxwBoeQ/view"
    },
    "Java": {
   "description": (
        "🚀 Master Java Programming Today! 👨‍💻\n\n"
        "📘 Exclusive JAVA Learning PDFs\n"
        "Level up your coding skills with these high-quality resources – perfect for beginners to advanced learners.\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.38 GB"
    ),
    "link": "https://drive.google.com/file/d/1U_yVhz5sJwXtYdgZfo_D_Kb4usSDe7YF/view"
},
    "Python":{
    "description": (
        "🐍 Python Full Course 2025 🚀\n\n"
        "🔥 Master Python programming from scratch – perfect for beginners to advanced learners!\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.44 GB"
    ),
    "link": "https://drive.google.com/file/d/1CXMjGRsANgEYFgXOOQMVz0RazKzbBArz/view"
},
  "JavaScript":{
    "description": (
        "🚀 The Complete JavaScript Course 2025: From Zero to Expert! 💻\n\n"
        "🔥 Learn JavaScript like a pro – from the absolute basics to advanced concepts, all in one course!\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.48 GB"
    ),
    "link": "https://drive.google.com/file/d/1MbkUaXVsmcnR_7n5H12F0-DcI83NIYSy/view?usp=drive_link"
},
  "BlackHat Hacking":{
    "description": (
        "🕵️‍♂️ Black Hat Hacking Course 💻\n\n"
        "🔥 Learn the dark side of cybersecurity – from the basics to advanced hacking techniques!\n\n"
        "⏳ Length: 05:04:30\n"
        "💾 Size: 516 MB\n\n"
        "✨ Support & Share this Bot to help us grow! ❤️"
    ),
    "link": "https://drive.google.com/file/d/1tU96CXdNJyCAKFgN8GvyV9oPiizVKIgm/view"
},
  "PowerShell":{
    "description": (
        "⚡️ PowerShell Course 2025 💻\n\n"
        "🔥 Master automation and scripting with PowerShell – from fundamentals to advanced techniques!\n\n"
        "⏳ Length: 03:00:01\n"
        "💾 Size: 800 MB\n\n"
        "✨ Support & Share this Bot to help us grow! ❤️"
    ),
    "link": "https://drive.google.com/file/d/1VmOkMbujab1ogkPC3k9t24ws2nu1nfJH/view"
},
 "Linux":{
   "description": (
        "🐧 Linux Mastery Course 2025 💻\n\n"
        "🔥 Become a Linux pro – from beginner essentials to advanced system administration!\n\n"
        "⏳ Length: 07:53:22\n"
        "💾 Size: 1.29 GB\n\n"
        "✨ Support & Share this Bot to help us grow! ❤️"
    ),
    "link": "https://drive.google.com/file/d/1gG3lCo_jqhRTAr7MXkrs6QqO6RPqiZCE/view"
},
 "PUBG Hack Development":{
   "description": (
        "🌹 PUBG Hack Making Course – Free Download 🌹\n\n"
        "📜 Course Topics:\n\n"
        "🔹 Basics About App\n"
        "🔹 Introduction to Sketchware\n"
        "🔹 UI Design of Log Cleaner APK\n"
        "🔹 Designing Progress 2\n"
        "🔹 Designing Progress 3\n"
        "🔹 UI Design Final\n"
        "🔹 Root Permission\n"
        "🔹 Login\n"
        "🔹 Log Cleaner\n"
        "🔹 Log Cleaner Final\n"
        "🔹 Antiban APK Basic Setup\n"
        "🔹 UI Improvement\n"
        "🔹 Firebase Authentication\n"
        "🔹 One Device Login\n"
        "🔹 Dialog Box\n"
        "🔹 Home Page Setup\n"
        "🔹 Save & Load Key\n"
        "🔹 Inbuilt Injector\n"
        "🔹 Floating Icon\n"
        "🔹 CPP Making\n"
        "🔹 Features & Values Finding\n"
        "🔹 Encryption & Online\n"
        "🔹 Basic Commands & Lua\n"
        "🔹 Completing the Script\n"
        "🔹 Memory-Antiban\n"
        "🔹 Fast Execution Script Making\n\n"
        "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
    ),
    "link": "https://www.mediafire.com/file/y78pzecdr5bmj7y/Pubg_Hack_Making_Course.rar/file"
},
"Binning (by BlackHat)":{
   "description": (
          "🎩 Binning by BlackHat Full Course 2025 (A-Z) 🎩\n"
        "Learn advanced blackhat techniques and tools in a structured manner.\n"
        "Full Course\n💾 Size: Check each part individually\n"
        "Support & Share this resource to help us grow! ❤️\n\n"
        "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/drive/folders/1fQqJnMQP2GwlpaV7seqAyL19vHbZno5M"
},
    # Add other courses in the same format
}

# -------------------------
# Flask Routes (webhook)
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    bot.remove_webhook()
    full_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    # drop_pending_updates True helps when switching from polling to webhook or after downtime
    bot.set_webhook(url=full_url, drop_pending_updates=True)
    return f"Webhook set to {full_url}", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    # Accept content types that start with application/json (handles charset)
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        abort(403)
    try:
        payload = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(payload)
        bot.process_new_updates([update])
    except Exception as e:
        # log but return 200 so Telegram doesn't retry excessively
        logger.exception("Failed to process update: %s", e)
        return "OK", 200
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
