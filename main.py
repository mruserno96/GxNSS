import os
import logging
import threading
import time
import random
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
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Constants
# -------------------------

# -------------------------
# Channel / Join-check config
# -------------------------
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@GxNSSupdates")
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"



UPI_ID = "MillionaireNaitik69@fam"
QR_IMAGE_URL = "https://mruser96.42web.io/qr.jpg?nocache="
COURSES_MESSAGE = (
    "📚 *GxNSS COURSES*\n\n"
    "🔹 *Programming Courses*\n"
    "C++\nJava\nJavaScript\nPython\n\n"
    "🔹 *Hacking & Cybersecurity Courses*\n"
    "BlackHat Hacking\nEthical Hacking\nAndroid Hacking\nWiFi Hacking\n"
    "Binning (by BlackHat)\nPhishing App Development\nPUBG Hack Development\nAPK Modding (20+ Courses)\n\n"
    "🔹 *System & OS Courses*\n"
    "Linux\nPowerShell\n\n"
    "🔹 *Special Cyber Tools Courses*\n"
    "How to Make Telegram Number\nHow to Make Lifetime RDP\nHow to Call Any Indian Number Free\n"
    "How to Make Own SMS Bomber\nHow to Make Own Temporary Mail Bot.)"
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

def is_member_of_channel(user_id: int) -> bool:
    """
    Return True if the user is a member of CHANNEL_USERNAME (or False otherwise).
    Requires the bot to be admin in the channel to reliably check membership.
    """
    try:
        # get_chat_member will raise if bot lacks permission or user isn't found
        cm = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        status = getattr(cm, "status", None)
        # statuses like 'left' or 'kicked' mean not a member
        if status in ("left", "kicked", None):
            return False
        # 'member', 'administrator', 'creator', 'restricted' -> treat as joined
        return True
    except Exception as e:
        # Could be ApiException if bot is not admin or username invalid.
        logger.info("is_member_of_channel check failed for user %s: %s", user_id, e)
        # Fail-safe: treat as not member
        return False



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
    )
    return markup

def programming_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💻 C++", "☕️ Java", "🌐 JavaScript", "🐍 Python", "⬅ Back")
    return markup

def hacking_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "🎩 BlackHat Hacking", "🛡 Ethical Hacking", "🤖 Android Hacking", "📶 WiFi Hacking",
        "🗑 Binning (by BlackHat)", "🎭 Phishing App Development",
        "🎮 PUBG Hack Development", "📱 APK Modding (20+ Courses)", "⬅ Back"
    )
    return markup

def system_os_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🐧 Linux", "⚡️ PowerShell", "⬅ Back")
    return markup


def special_tools_courses_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "📞 Make a Telegram Number",
        "💻 Lifetime RDP",
        "☎️  Call Any Indian Number Free",
        "💣 Own SMS Bomber",
        "✉️ Own Temporary Mail Bot",
        "⬅ Back"
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

    # premium users: same as before
    if user and user.get("status") == "premium":
        bot.send_message(
            cid,
            "🎉 Welcome back Premium User!",
            reply_markup=main_menu_keyboard()
        )
        return

    # NON-PREMIUM: check channel membership first
    try:
        joined = is_member_of_channel(message.from_user.id)
    except Exception:
        joined = False

    if joined:
        # Show courses + promo as before
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
        return
    else:
        # Not joined -> show Join + Try Again buttons
        kb = types.InlineKeyboardMarkup()
        # join button uses URL
        kb.add(types.InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL))
        # try again callback to re-check membership
        kb.add(types.InlineKeyboardButton("✅ Try Again", callback_data="check_join"))

        sent_msg = bot.send_message(
            cid,
            f"💬 *Please join our Telegram channel first to access courses.*\n\n"
            f"Channel: {CHANNEL_USERNAME}\n\n"
            "Click *Join Channel* then come back and press *Try Again*.",
            parse_mode="Markdown",
            reply_markup=kb
        )
        try:
            # save for possible cleanup
            if user:
                save_message(user["id"], cid, sent_msg.message_id)
        except Exception:
            pass
        return

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
# Callback handler for "Try Again" join check
# -------------------------
@bot.callback_query_handler(func=lambda c: c.data == "check_join")
def handle_check_join(call):
    """User clicked 'Try Again' — re-check membership and either show content or prompt again."""
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    cid = call.message.chat.id
    uid = call.from_user.id

    if is_member_of_channel(uid):
        # user joined — send the regular non-premium start flow
        try:
            sent = bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
            user = get_user_cached(uid) or supabase.table("users").select("*").eq("telegram_id", uid).single().execute().data
            if user:
                try:
                    save_message(user["id"], cid, sent.message_id)
                except Exception:
                    pass

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
            sent2 = bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
            if user:
                try:
                    save_message(user["id"], cid, sent2.message_id)
                except Exception:
                    pass
        except Exception as e:
            logger.exception("Error sending courses after successful join: %s", e)
            try:
                bot.send_message(cid, "✅ You are a channel member — but I couldn't send the content right now. Try again later.")
            except Exception:
                pass
    else:
        # still not a member
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL))
        kb.add(types.InlineKeyboardButton("✅ Try Again", callback_data="check_join"))
        try:
            bot.send_message(
                cid,
                f"💬 You still need to join {CHANNEL_USERNAME} before continuing.\n\n"
                f"Click *Join Channel* and then *Try Again*.",
                parse_mode="Markdown",
                reply_markup=kb
            )
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

# -------------------------
# Admin State & Keyboard
# -------------------------
ADMIN_STATES = {}
ADMIN_KB_BUTTON_UPGRADE = "🔼 Upgrade User"
ADMIN_KB_BUTTON_ALL_PREMIUM = "💎 All Premium Users"
ADMIN_KB_BUTTON_CANCEL = "❌ Cancel"

@bot.message_handler(commands=["admin"])
def admin_help(message):
    if not is_admin(message.from_user.id):
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(ADMIN_KB_BUTTON_UPGRADE, ADMIN_KB_BUTTON_ALL_PREMIUM)
    markup.add(ADMIN_KB_BUTTON_CANCEL)
    bot.send_message(
        message.chat.id,
        "👮 *Admin Panel*\n\nChoose an action:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

def _perform_upgrade_by_target(target, chat_id):
    try:
        if target.isdigit():
            resp = supabase.table("users").select("*").eq("id", int(target)).limit(1).execute()
        else:
            username_lookup = target.lstrip("@")
            resp = supabase.table("users").select("*").eq("username", username_lookup).limit(1).execute()
    except Exception:
        bot.send_message(chat_id, "❌ Database error while searching for user.")
        return

    user_row = (resp.data or [None])[0]
    if not user_row:
        bot.send_message(chat_id, f"❌ User {target} not found.")
        return

    if user_row.get("status") == "premium":
        bot.send_message(chat_id, f"✅ User {target} is already Premium.")
        return

    try:
        supabase.table("users").update({"status": "premium", "updated_at": datetime.utcnow().isoformat()}).eq("id", user_row["id"]).execute()
        supabase.table("payments").update({"verified": True}).eq("user_id", user_row["id"]).execute()
        invalidate_user_cache(user_row["telegram_id"])
    except Exception:
        bot.send_message(chat_id, f"❌ Failed to upgrade {target}.")
        return

    notify_user_upgrade(user_row)
    bot.send_message(chat_id, f"✅ User {target} upgraded to Premium!")


@bot.message_handler(commands=["allpremiumuser"])
def admin_allpremiumuser(message):
    # ensure the caller is admin
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ You are not an admin.")
        logger.warning("Unauthorized /allpremiumuser call from %s", message.from_user.id)
        return

    try:
        # Use ilike for case-insensitive match (handles 'Premium', 'premium', etc.)
        # NOTE: .ilike is supported by the supabase-py client interface.
        resp = supabase.table("users").select("*").ilike("status", "premium").execute()
    except Exception as e:
        logger.exception("Supabase query failed in /allpremiumuser: %s", e)
        bot.reply_to(message, "❌ Database error while fetching premium users (see logs).")
        return

    # debug log the raw response object for troubleshooting
    logger.info("/allpremiumuser supabase raw resp: %r", resp)

    # Try to extract rows in multiple possible shapes
    rows = None
    try:
        # typical supabase-py response has .data
        rows = getattr(resp, "data", None)
    except Exception:
        rows = None

    # Some client versions return a dict
    if rows is None and isinstance(resp, dict) and "data" in resp:
        rows = resp["data"]

    # Some older clients return list directly
    if rows is None and isinstance(resp, (list, tuple)):
        rows = resp

    if not rows:
        # helpful hint for operators
        hint = (
            "No premium users returned.\n"
            "- If you expect rows, check Supabase table data and 'status' column values.\n"
            "- If Row Level Security is enabled, ensure your server key has permission.\n"
            "- Check server logs for the Supabase response above."
        )
        bot.reply_to(message, f"❌ No Premium users found.\n\n{hint}")
        return

    # Build reply with safe chunking (Telegram max ~4096 chars)
    header = "💎 *Premium Users:*\n\n"
    lines = []
    for u in rows:
        try:
            lines.append(
                "ID: {id}\nTelegramID: {telegram_id}\nUsername: @{username}\nName: {first} {last}\nStatus: {status}\nCreated: {created}\n\n".format(
                    id=u.get("id"),
                    telegram_id=u.get("telegram_id"),
                    username=u.get("username") or "N/A",
                    first=u.get("first_name", ""),
                    last=u.get("last_name", ""),
                    status=u.get("status"),
                    created=u.get("created_at")
                )
            )
        except Exception:
            # fallback for unexpected row shape
            lines.append(str(u) + "\n\n")

    # chunk message into pieces under 3500 chars to be safe
    chunks = []
    current = header
    for l in lines:
        if len(current) + len(l) > 3500:
            chunks.append(current)
            current = l
        else:
            current += l
    if current:
        chunks.append(current)

    # send chunks
    for c in chunks:
        try:
            bot.reply_to(message, c, parse_mode="Markdown")
        except Exception:
            # fallback: send without markdown
            try:
                bot.reply_to(message, c)
            except Exception:
                logger.exception("Failed to send /allpremiumuser chunk")

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

    # --- Admin Keyboard Handling (runs first, before premium check) ---
    if is_admin(message.from_user.id):
        state = ADMIN_STATES.get(message.from_user.id)
        if text == ADMIN_KB_BUTTON_ALL_PREMIUM:
            admin_allpremiumuser(message)
            return
        if text == ADMIN_KB_BUTTON_UPGRADE:
            ADMIN_STATES[message.from_user.id] = {'mode': 'await_upgrade'}
            bot.send_message(chat_id, "Please enter the target: <user_id> or @username")
            return
        if text == ADMIN_KB_BUTTON_CANCEL:
            ADMIN_STATES.pop(message.from_user.id, None)
            bot.send_message(chat_id, "Cancelled.")
            return
        if state and state.get("mode") == "await_upgrade":
            ADMIN_STATES.pop(message.from_user.id, None)
            _perform_upgrade_by_target(text.strip(), chat_id)
            return

    # --- Normal Premium User Menu ---
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
    "💻 C++": {
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
            "⏳ Time:-) 31:07:29\n"
                         "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

        ),
        "link": "https://drive.google.com/file/d/1Ur5T9dGb_e5EBNJzpTg08ieSHKxwBoeQ/view"
    },
    "☕️ Java": {
   "description": (
        "🚀 Master Java Programming Today! 👨‍💻\n\n"
        "📘 Exclusive JAVA Learning PDFs\n"
        "Level up your coding skills with these high-quality resources – perfect for beginners to advanced learners.\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.38 GB\n"
                     "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

    ),
    "link": "https://drive.google.com/file/d/1U_yVhz5sJwXtYdgZfo_D_Kb4usSDe7YF/view"
},
    "🐍 Python":{
    "description": (
        "🐍 Python Full Course 2025 🚀\n\n"
        "🔥 Master Python programming from scratch – perfect for beginners to advanced learners!\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.44 GB\n"
                     "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

    ),
    "link": "https://drive.google.com/file/d/1CXMjGRsANgEYFgXOOQMVz0RazKzbBArz/view"
},
  "🌐 JavaScript":{
    "description": (
        "🚀 The Complete JavaScript Course 2025: From Zero to Expert! 💻\n\n"
        "🔥 Learn JavaScript like a pro – from the absolute basics to advanced concepts, all in one course!\n\n"
        "⏳ Length: 12:00:00\n"
        "💾 Size: 1.48 GB\n"
     "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

    ),
    "link": "https://drive.google.com/file/d/1MbkUaXVsmcnR_7n5H12F0-DcI83NIYSy/view?usp=drive_link"
},
  "🎩 BlackHat Hacking":{
    "description": (
        "🕵️‍♂️ Black Hat Hacking Course 💻\n\n"
        "🔥 Learn the dark side of cybersecurity – from the basics to advanced hacking techniques!\n\n"
        "⏳ Length: 05:04:30\n"
        "💾 Size: 516 MB\n\n"
        "✨ Support & Share this Bot to help us grow! ❤️\n"
                     "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

    ),
    "link": "https://drive.google.com/file/d/1tU96CXdNJyCAKFgN8GvyV9oPiizVKIgm/view"
},
  "⚡️ PowerShell":{
    "description": (
        "⚡️ PowerShell Course 2025 💻\n\n"
        "🔥 Master automation and scripting with PowerShell – from fundamentals to advanced techniques!\n\n"
        "⏳ Length: 03:00:01\n"
        "💾 Size: 800 MB\n\n"
        "✨ Support & Share this Bot to help us grow! ❤️\n"
      "💡 Credit: @WinTheBetWithMe , @Paise_wala69"

    ),
    "link": "https://drive.google.com/file/d/1VmOkMbujab1ogkPC3k9t24ws2nu1nfJH/view"
},
 "🐧 Linux":{
   "description": (
        "🐧 Linux Mastery Course 2025 💻\n\n"
        "🔥 Become a Linux pro – from beginner essentials to advanced system administration!\n\n"
        "⏳ Length: 07:53:22\n"
        "💾 Size: 1.29 GB\n"
      "💡 Credit: @WinTheBetWithMe , @Paise_wala69\n"
        "✨ Support & Share this Bot to help us grow! ❤️"
    ),
    "link": "https://drive.google.com/file/d/1gG3lCo_jqhRTAr7MXkrs6QqO6RPqiZCE/view"
},
 "🎮 PUBG Hack Development":{
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
"🗑 Binning (by BlackHat)":{
   "description": (
          "🎩 Binning by BlackHat Full Course 2025 (A-Z) 🎩\n"
        "Learn advanced blackhat techniques and tools in a structured manner.\n"
        "Full Course\n💾 Size: Check each part individually\n"
        "Support & Share this resource to help us grow! ❤️\n\n"
        "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/drive/folders/1fQqJnMQP2GwlpaV7seqAyL19vHbZno5M"
},
"🤖 Android Hacking":{
   "description": (
          "🚀 Android Hacking Course 🔐📱\n"
     "💡 Master Android security, exploit vulnerabilities, and level up your ethical hacking skills! ⚡️\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/drive/folders/11dqpULb1h14jyoZeSwsAo_bd3XN4t602"
},

"📶 WiFi Hacking":{
   "description": (
              "💢 WiFi Hacking Course in Hindi 💢\n\n"
        "📍 What you'll learn :-\n\n"
        "🌀 Students will get the intermediate knowledge of Kali Linux and learn to crack passwords of vulnerable WiFi routers.\n\n"
        "🌀 Attacks before gaining access to router and hiding your identity in the process.\n\n"
        "🌀 Various methods to gain access to router.\n\n"
        "🤓 Who this course is for:-\n"
        "1. Anyone who wants to learn professional wireless hacking.\n"
        "2. Penetration testing or WiFi hacking just for fun.\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/folderview?id=1tgkKt4lSpXD3GnMQRgUb4bbtlmpP9XOE"
},

"🛡 Ethical Hacking":{
   "description": (
                "🔰 ETHICAL HACKING COURSE 🔰\n"
                "🌀 Language ~ Hindi\n"
                "🌀 Content - 20 Folders, 80+ videos\n"
                "Password: ###gr3y@n0n###\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "http://www.mediafire.com/file/qiax38wizsnj8zm/HACK2ED+-+Tech+Vansh.rar/file"
},

"🎭 Phishing App Development":{
   "description": (
       
       "This is Zpisher Famous Phishing Tool\n"
       "apt update\n"
       "apt upgrade\n"
       "apt install git php openssh curl -y\n"
       "git clone https://github.com/htr-tech/zphisher\n"
       "cd zphisher\n"
       "chmod +x zphisher.sh (https://zphisher.sh/)\n"
       "bash zphisher.sh (https://zphisher.sh/)\n"
       "run\n"
       "cd zphisher\n"
       "bash zphisher.sh (https://zphisher.sh/)\n\n"
        "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://github.com/htr-tech/zphisher"
},

"📱 APK Modding (20+ Courses)":{
   "description": (
                  "📱 APK Modding & Game Guardian Masterclass\n\n"
        "💻 Learn to Create, Modify, and Secure Android Apps & Games!\n\n"
        "📚 APK Making Course\n"
        "🎬 Beginner to Advanced Tutorials\n\n"
        "1️⃣ Part 1 – Basics About Apps\n"
        "2️⃣ Part 2 – Introduction to Sketchware\n"
        "3️⃣ Part 3 – UI Design for Log Cleaner APK\n"
        "4️⃣ Part 4 – Designing Progress (Stage 2)\n"
        "5️⃣ Part 5 – Designing Progress (Stage 3)\n"
        "6️⃣ Part 6 – Final UI Design\n"
        "7️⃣ Part 7 – Root Permission Integration\n"
        "8️⃣ Part 8 – Login System Setup\n"
        "9️⃣ Parts 9 & 10 – Log Cleaner APK Final Build\n\n"
        "🛡 Antiban APK Tutorials\n"
        "1️⃣ Part 11 – Antiban APK Basic Setup\n"
        "2️⃣ Part 12 – UI Improvement Techniques\n"
        "3️⃣ Part 13 – Firebase Authentication\n"
        "4️⃣ Part 14 – One Device Login System\n"
        "5️⃣ Part 15 – Custom Dialog Box Design\n"
        "6️⃣ Part 16 – Home Page Setup\n"
        "7️⃣ Part 17 – Save & Load Key Functionality\n"
        "8️⃣ Part 18 – In-Build Injector with Sketchware\n"
        "9️⃣ Part 19 – Floating Icon Injector (Sketchware)\n\n"
        "🖥 CPP Making Tutorial\n"
        "Complete Guide to CPP APK Development (First & Final Video)\n\n"
        "🎮 Game Guardian Mastery\n"
        "🔍 Game Guardian Basics\n"
        "Part 1 – Features & Value Finding\n\n"
        "🧩 Game Guardian Script Making\n"
        "1️⃣ Part 1 – Basic Commands & Lua Scripting\n"
        "2️⃣ Part 2 – Completing the Script\n"
        "3️⃣ Part 3 – Memory Antiban Creation\n"
        "4️⃣ Part 4 – Fast Execution Script (XS Script)\n\n"
        "⚡ Final Advanced Guide\n"
        "Game Guardian Script Final Part – Encryption & Online Deployment\n\n"
        "🔗 All Course Links\n"
        "📥 All video links are combined in one single file for easy access!\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://pastebin.com/raw/RmnWccvp"
},

"📞 Make a Telegram Number":{
   "description": (
                "📲 How To Make Unlimited Numbers for Telegram or WhatsApp\n\n"
        "💡 Follow the method carefully to generate multiple working numbers.\n\n"
        "⭐ Watch the full video carefully to learn the method step by step.\n\n"
        "🛡 Enjoy and use responsibly!\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/file/d/1VoQYPQU2weBfhZJsMe5sHInO9HJTwSwK/view"
},

"💻 Lifetime RDP":{
   "description": (
       "☠️ How To Make Lifetime RDP For Free\n\n1."
   " First Go On Chrome And Open This Website - rdphostings.com\n"
   "2. Select Windows RDP\n"
   "3. Select Plan - Solo Server / Expert Server ( We Prefer Expert Server )\n"
   "4. And Then Buy it at Zero (0$) Cost , No Need To Give Any Card Details.\n"
   "5. Fill All Real Information Of Your's.\n"
   "6. Verify Gmail By Click On Link Which Is Send By rdphostings.com On Your Gmail Account.\n"
   "7. Wait 24 Hours.\n"
   "8. You Will Get Your Username And Ip on Your Gmail. And you will also get the password from Gmail itself.\n\n"
   "And if you want to use rdp in mobile then you have to install one app. App Name is ( RD Clients )\n\n"
   "Tip - iF You Need High Speed Internet Then Select Linux Solo Server, Speed Upto 500Mbps 😱\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "rdphostings.com"
},

"☎️  Call Any Indian Number Free":{
   "description": (
        "📞 UNLIMITED CALLS ANY INDIAN NUMBERS FOR FREE\n\n"
        "New App Trick / Method\n\n"
        "Any Indian Numbers Call fake number 30 Days Trial\n"
        "Get many times trials trick leaked by hacker Alok\n"
        "Call any Indian number for free using this trick.\n\n"
             "💡 Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/file/d/1_1qgSlxSFOshlkXaoFtcWq2G1_JTPtxX/view"
},

"💣 Own SMS Bomber":{
   "description": (
       "💥 CREATE YOUR OWN SMS BOMBER 💥\n\n"
        "🚀 Learn step-by-step how to make a powerful SMS Bomber tool from scratch.\n\n"
        "🎬 VIDEO COURSE LINK INCLUDED\n\n"
        "💡 What You Will Learn:\n"
        "1️⃣ Fundamentals of SMS bombing scripts and techniques.\n"
        "2️⃣ How to safely test your tool without breaking laws.\n"
        "3️⃣ Integrating APIs for bulk SMS sending.\n"
        "4️⃣ Adding stylish features and customizations.\n"
        "5️⃣ Protecting your tool from detection.\n\n"
        "⚠️ WARNING: Use responsibly! Only for educational purposes.\n\n"
        "✨ Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/file/d/1_yvmp1Httou9u06-EjxPy5V9e2qFk9ob/view"
},

"✉️ Own Temporary Mail Bot":{
   "description": (
            "📬 HOW TO CREATE YOUR OWN TEMP MAIL TELEGRAM BOT 📬\n\n"
        "🚀 Learn how to make a fully functional temporary mail bot for Telegram from scratch!\n\n"
        "🎬 Video Tutorial Included\n"
        "1 Download the 'Bots.Business' app from Play Store or Google.\n\n"
        "✨ Credit: @WinTheBetWithMe , @Paise_wala69"
  ),
    "link": "https://drive.google.com/file/d/1nxp-k8BloK2TIQWWPAsHhqKt0ssRNvb7/view"
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
# -------------------------
# Auto Ping with backoff
# -------------------------
def auto_ping():
    base_delay = 300  # normal interval in seconds (5 minutes)
    max_retry_delay = 600  # max delay on failure (10 minutes)

    while True:
        try:
            if WEBHOOK_URL:
                response = requests.get(WEBHOOK_URL, timeout=10)
                if response.status_code != 200:
                    logger.warning("Auto ping returned status code %s", response.status_code)
            # success, reset delay to normal
            sleep_time = base_delay
        except Exception as e:
            logger.warning("Auto ping failed: %s", e)
            # exponential backoff with jitter
            sleep_time = min(base_delay * 2, max_retry_delay) + random.randint(0, 30)
        time.sleep(sleep_time)

# -------------------------
# Run Locally
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
