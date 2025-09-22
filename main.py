import os
import time
import random
import secrets
import logging
import threading
from functools import wraps
from typing import Any, Callable, Dict, Optional
from datetime import datetime, timedelta, timezone

from flask import Flask, request
import telebot
from telebot import types
from supabase import create_client, Client
from telebot.apihelper import ApiException

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------- Config (env) ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "")
CHANNEL_ID2 = int(os.getenv("CHANNEL_ID2", "0"))
CHANNEL_LINK2 = os.getenv("CHANNEL_LINK2", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0")) # set to your owner id
OWNER_ID_LIST = [int(id.strip()) for id in OWNER_ID.split(',')]  # Split and convert each ID to an integer
# ---------------- Config (env) ----------------

UPI_ID = os.getenv("UPI_ID", "your_upi@bank")
QR_IMAGE_URL = os.getenv("QR_IMAGE_URL", "https://mruser96.42web.io/uservip.jpg")

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, WEBHOOK_URL]):
    logger.warning("One or more required environment variables are missing.")

# ---------------- Bot & Flask ----------------
# Note: parse_mode=None by default to avoid entity parsing issues.
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
app = Flask(__name__)

# ---------------- Supabase ----------------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Timezones ----------------
IST = timezone(timedelta(hours=5, minutes=30))  # IST tzinfo
UTC = timezone.utc

# ---------------- Globals ----------------
_lock = threading.Lock()
pending_action: Dict[int, str] = {}
last_start_args: Dict[int, list] = {}
scheduled_deletes: Dict[str, threading.Timer] = {}
active_users: set[int] = set()

FREE_VIEW_LIMIT = 3
VIDEO_DELETE_MINUTES = 15

# ---------------- Utilities ----------------
def backoff_retry(max_retries: int = 4, base_delay: float = 0.5, max_delay: float = 4.0, jitter: float = 0.2):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except ApiException as e:
                    logger.warning("ApiException attempt %d for %s: %s", attempt, func.__name__, e)
                    if attempt == max_retries:
                        logger.exception("Max retries for %s", func.__name__)
                        raise
                except Exception as e:
                    logger.warning("Exception attempt %d for %s: %s", attempt, func.__name__, e)
                    if attempt == max_retries:
                        logger.exception("Max retries for %s", func.__name__)
                        raise
                sleep_time = min(delay, max_delay) + random.uniform(0, jitter)
                time.sleep(sleep_time)
                delay *= 2
            # unreachable
        return wrapper
    return decorator

@backoff_retry(max_retries=5)
def supabase_call(fn: Callable, *args, **kwargs) -> Any:
    """Wrap supabase calls to retry transient failures."""
    return fn()

@backoff_retry(max_retries=3)
def bot_call(fn: Callable, *args, **kwargs) -> Any:
    """Wrap bot API calls to retry transient failures."""
    return fn(*args, **kwargs)

def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()

def parse_iso_to_dt(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        if iso_str.endswith("Z"):
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return datetime.fromisoformat(iso_str)
    except Exception:
        try:
            return datetime.fromisoformat(iso_str)
        except Exception:
            return None

def format_dt_ist(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "N/A"
    dt = parse_iso_to_dt(iso_str)
    if not dt:
        return iso_str
    return dt.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p")

def escape_md_v2(text: str) -> str:
    if not text:
        return ""
    to_escape = r'_*\[\]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in to_escape else c for c in text)


def is_channel_member(user_id: int, channel_id: int = None) -> bool:
    """Return True if user is member/admin/creator of CHANNEL_ID channel."""
    try:
        channel_id = channel_id or CHANNEL_ID
        member = bot_call(bot.get_chat_member, channel_id, user_id)
        status = getattr(member, "status", None)
        return status in ("member", "administrator", "creator")
    except Exception as e:
        logger.debug("is_channel_member error: %s", e)
        return False


def join_keyboard():
    kb = telebot.types.InlineKeyboardMarkup()
    if CHANNEL_LINK:
        kb.add(telebot.types.InlineKeyboardButton("🔒 Join Private Channel", url=CHANNEL_LINK))
    if CHANNEL_LINK2:
        kb.add(telebot.types.InlineKeyboardButton("🌐 Visit Public Channel", url=CHANNEL_LINK2))
    kb.add(telebot.types.InlineKeyboardButton("🔄 Try Again", callback_data="try_again"))
    return kb

# ---------------- Safe send helpers ----------------
def safe_reply(message, text, **kwargs):
    try:
        return bot_call(bot.reply_to, message, text, **kwargs)
    except Exception as e:
        logger.debug("safe_reply failed: %s", e)
        try:
            return bot_call(bot.send_message, message.chat.id, text, **kwargs)
        except Exception as e2:
            logger.debug("fallback send_message failed: %s", e2)
            raise


def safe_send(chat_id, text, **kwargs):
    try:
        return bot_call(bot.send_message, chat_id, text, **kwargs)
    except Exception as e:
        logger.debug("safe_send failed: %s", e)
        raise

# ---------------- Keyboards ----------------
def paywall_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("1 Day — ₹49", callback_data="buy_1day"))
    kb.add(types.InlineKeyboardButton("Weekly — ₹129", callback_data="buy_week"))
    kb.add(types.InlineKeyboardButton("Monthly — ₹299", callback_data="buy_month"))
    return kb

def owner_payment_buttons(payment_id: int, days_valid: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_payment:{payment_id}:{days_valid}"))
    kb.add(types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_payment:{payment_id}"))
    return kb

def get_owner_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("➕ Add Admin"),
        types.KeyboardButton("❌ Remove Admin"),
        types.KeyboardButton("👑 List Admins"),
        types.KeyboardButton("📂 List Videos"),
        types.KeyboardButton("🔥 Destroy Video"),
        types.KeyboardButton("📢 Broadcast"),
    )
    kb.add(types.KeyboardButton("🧾 Pending Payments"), types.KeyboardButton("📋 Premiums"))
    return kb

def get_admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton("📂 List Videos"), types.KeyboardButton("🔥 Destroy Video"))
    return kb

# ---------------- DB helpers ----------------


def is_owner(user_id: int) -> bool:
    """Check if the user is an owner by comparing against a list of OWNER_IDs."""
    return user_id in OWNER_ID_LIST

def is_admin(user_id: int) -> bool:
    try:
        resp = supabase_call(lambda: supabase.table("admins").select("user_id").eq("user_id", user_id).execute())
        return bool(getattr(resp, "data", None))
    except Exception as e:
        logger.debug("is_admin error: %s", e)
        return False

def get_view_count(user_id: int) -> int:
    try:
        resp = supabase_call(lambda: supabase.table("views").select("view_count").eq("user_id", user_id).execute())
        if getattr(resp, "data", None):
            return int(resp.data[0].get("view_count", 0))
    except Exception as e:
        logger.debug("get_view_count error: %s", e)
    return 0

def increment_view_count(user_id: int):
    try:
        resp = supabase_call(lambda: supabase.table("views").select("view_count").eq("user_id", user_id).execute())
        if getattr(resp, "data", None):
            current = int(resp.data[0].get("view_count", 0))
            supabase_call(lambda: supabase.table("views").update({"view_count": current + 1, "updated_at": now_utc_iso()}).eq("user_id", user_id).execute())
        else:
            # use upsert to avoid duplicates
            supabase_call(lambda: supabase.table("views").insert({"user_id": user_id, "view_count": 1, "updated_at": now_utc_iso()}).execute())
    except Exception as e:
        logger.debug("increment_view_count error: %s", e)

def reset_view_count(user_id: int):
    try:
        supabase_call(lambda: supabase.table("views").update({"view_count": 0, "updated_at": now_utc_iso()}).eq("user_id", user_id).execute())
    except Exception as e:
        logger.debug("reset_view_count error: %s", e)

def get_active_subscription(user_id: int) -> Optional[Dict]:
    try:
        resp = supabase_call(lambda: supabase.table("subscriptions")
                             .select("id,tier,price,expires_at,notify_status,created_at")
                             .eq("user_id", user_id)
                             .order("expires_at", desc=True)
                             .limit(1)
                             .execute())
        if getattr(resp, "data", None):
            sub = resp.data[0]
            expires = sub.get("expires_at")
            dt = parse_iso_to_dt(expires)
            if dt and dt > datetime.now(UTC):
                return sub
    except Exception as e:
        logger.debug("get_active_subscription error: %s", e)
    return None

def create_pending_payment(user_id: int, tier: str, price: int, days_valid: int):
    try:
        resp = supabase_call(lambda: supabase.table("pending_payments").insert({
            "user_id": user_id,
            "tier": tier,
            "price": price,
            "days_valid": days_valid,
            "status": "initiated",
            "created_at": now_utc_iso()
        }).execute())
        return resp.data[0] if getattr(resp, "data", None) else None
    except Exception as e:
        logger.exception("create_pending_payment error: %s", e)
        return None

def update_pending_with_screenshot(payment_id: int, file_id: str):
    try:
        supabase_call(lambda: supabase.table("pending_payments").update({
            "screenshot_file_id": file_id,
            "status": "done",
            "updated_at": now_utc_iso()
        }).eq("id", payment_id).execute())
        return True
    except Exception as e:
        logger.exception("update_pending_with_screenshot error: %s", e)
        return False

def set_pending_status(payment_id: int, status: str):
    try:
        supabase_call(lambda: supabase.table("pending_payments").update({
            "status": status,
            "updated_at": now_utc_iso()
        }).eq("id", payment_id).execute())
        return True
    except Exception as e:
        logger.exception("set_pending_status error: %s", e)
        return False

def create_subscription(user_id: int, tier: str, price: int, days_valid: int, username: Optional[str] = None):
    try:
        expires = datetime.now(UTC) + timedelta(days=days_valid)
        resp = supabase_call(lambda: supabase.table("subscriptions").insert({
            "user_id": user_id,
            "username": username,
            "tier": tier,
            "price": price,
            "expires_at": expires.isoformat(),
            "created_at": now_utc_iso(),
            "notify_status": 0
        }).execute())
        return resp.data[0] if getattr(resp, "data", None) else None
    except Exception as e:
        logger.exception("create_subscription error: %s", e)
        return None

# ---------------- Video temp send ----------------
def schedule_delete_message(chat_id: int, message_id: int, delay_seconds: int = 900):
    key = f"{chat_id}:{message_id}"
    def _delete_task():
        try:
            bot_call(bot.delete_message, chat_id, message_id)
        except Exception as e:
            logger.debug("delete_message failed for %s: %s", key, e)
        with _lock:
            scheduled_deletes.pop(key, None)
    timer = threading.Timer(delay_seconds, _delete_task)
    with _lock:
        existing = scheduled_deletes.get(key)
        if existing and existing.is_alive():
            try:
                existing.cancel()
            except Exception:
                pass
        scheduled_deletes[key] = timer
    timer.daemon = True
    timer.start()
    return timer

def send_temp_video(chat_id: int, file_id: str, delay_seconds: int = VIDEO_DELETE_MINUTES * 60, user_id: int = None):
    """
    Sends the video, schedules message deletion. For premium users:
      - do NOT send extra "You have premium access until ..." message alongside the video.
      - send the standard deletion notice message ("will be deleted in X minutes").
    """
    try:
        # check subscription only if user_id provided
        has_premium = False
        if user_id:
            sub = get_active_subscription(user_id)
            if sub:
                has_premium = True
            else:
                # increment view count only for non-premium
                count = get_view_count(user_id)
                if count >= FREE_VIEW_LIMIT:
                    caption = (
                        "⚠️ You have reached your free limit of 7 videos.\n\n"
                        "If you need to watch more videos, buy Premium:\n\n"
                        "Choose a plan below:"
                    )
                    kb = paywall_keyboard()
                    bot_call(bot.send_message, chat_id, caption, reply_markup=kb)
                    return
                else:
                    increment_view_count(user_id)

        bot_call(bot.send_chat_action, chat_id, "upload_video")
        sent_video = bot_call(bot.send_video, chat_id, file_id, protect_content=True)
        # always send deletion note (user requested that behavior)
        sent_text = bot_call(bot.send_message, chat_id, f"⚠️ This video will be deleted in {delay_seconds // 60} minutes.")
        schedule_delete_message(chat_id, sent_video.message_id, delay_seconds=delay_seconds)
        schedule_delete_message(chat_id, sent_text.message_id, delay_seconds=delay_seconds)
    except Exception as e:
        logger.exception("send_temp_video error: %s", e)
        try:
            bot_call(bot.send_message, chat_id, "❌ Failed to send video.")
        except Exception:
            pass

# ---------------- Webhook endpoints ----------------
@app.route('/' + BOT_TOKEN, methods=['POST'])
def telegram_webhook():
    try:
        json_str = request.stream.read().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        logger.exception("webhook processing error: %s", e)
        return "ERR", 500

@app.route('/')
def index():
    return "Bot Running", 200

# ---------------- Bot Handlers ----------------
@bot.message_handler(commands=['ping'])
def handle_ping(message: telebot.types.Message):
    try:
        active_users.add(message.from_user.id)
        safe_reply(message, "🏓 Pong! Bot is alive.")
    except Exception as e:
        logger.debug("ping handler error: %s", e)









@bot.message_handler(commands=['start'])
def handle_start(message: telebot.types.Message):
    user_id = message.from_user.id
    username = getattr(message.from_user, "username", None)
    args = message.text.split()
    active_users.add(user_id)

    with _lock:
        last_start_args[user_id] = args

    # --- Enforce channel join for normal users (owner/admin bypass) ---
    try:
        if user_id not in OWNER_ID_LIST and not is_admin(user_id):  # Check if the user is neither owner nor admin
            ok1 = is_channel_member(user_id, CHANNEL_ID) if CHANNEL_ID else False
            ok2 = is_channel_member(user_id, CHANNEL_ID2) if CHANNEL_ID2 else True
            if not (ok1 and ok2):  # If the user is not in either channel
                try:
                    bot_call(
                        bot.send_message,
                        message.chat.id,
                        "⚠️ Please join our channel to continue.\n\n"
                        "Click the button below to join, then press \"Try Again\".",
                        reply_markup=join_keyboard()
                    )
                except Exception:
                    safe_reply(message, "⚠️ Please join the channel: " + CHANNEL_LINK)
                return
    except Exception as e:
        logger.debug("Channel check failed: %s", e)

    # Cache username if available
    if username:
        try:
            supabase_call(lambda: supabase.table("users")
                          .upsert(
                              {"user_id": user_id, "username": username, "updated_at": now_utc_iso()},
                              on_conflict=["user_id"]
                          )
                          .execute())
        except Exception as e:
            logger.debug("User upsert error: %s", e)

    # If /start has token -> send temporary video
    if len(args) > 1:
        token = args[1]
        try:
            resp = supabase_call(lambda: supabase.table("videos").select("file_id").eq("token", token).limit(1).execute())
            if not getattr(resp, "data", None):
                safe_reply(message, "❌ Invalid or deleted link.")
                return
            file_id = resp.data[0]["file_id"]
            send_temp_video(message.chat.id, file_id, delay_seconds=VIDEO_DELETE_MINUTES * 60, user_id=user_id)
        except Exception as e:
            logger.exception("Start token error: %s", e)
            safe_reply(message, "❌ Error fetching the video. Try again later.")
        return

    # owner/admin UI
    if user_id in OWNER_ID_LIST:  # Check if the user is in the OWNER_ID_LIST
        bot_call(bot.send_message, message.chat.id, "👑 Welcome Owner! Use the buttons below:", reply_markup=get_owner_keyboard())
        return

    if is_admin(user_id):
        if username:
            try:
                supabase_call(lambda: supabase.table("admins").update({"username": username}).eq("user_id", user_id).execute())
            except Exception:
                pass
        bot_call(bot.send_message, message.chat.id, "👋 Welcome Admin! You can manage videos.", reply_markup=get_admin_keyboard())
        return

    # Normal user welcome
    safe_reply(message, """Welcome! You’ve Joined Successfully ✅

👋 Hello there!
To unlock exclusive premium videos, join our special channel now! 🔥🎥

🔗 Join Here: https://t.me/+iVhgogd-M4wwNGY1

✨ Don’t miss out on high-quality, exclusive content — available only for our premium members! 🚀""", protect_content=True)

@bot.callback_query_handler(func=lambda call: call.data == "try_again")
def handle_try_again(call: telebot.types.CallbackQuery):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    active_users.add(user_id)
    args = last_start_args.get(user_id, ["/start"])

    # --- Re-check channel membership ---
    try:
        if not is_owner(user_id) and not is_admin(user_id):  # Check if the user is neither owner nor admin
            ok1 = is_channel_member(user_id, CHANNEL_ID) if CHANNEL_ID else False
            ok2 = is_channel_member(user_id, CHANNEL_ID2) if CHANNEL_ID2 else True
            if not (ok1 and ok2):
                try:
                    bot_call(
                        bot.send_message,
                        chat_id,
                        "⚠️ You are still not a member of the channel.\n\n"
                        "Please join first, then press \"Try Again\".",
                        reply_markup=join_keyboard()
                    )
                except Exception:
                    safe_send(chat_id, "⚠️ Please join the channel: " + CHANNEL_LINK)
                return
    except Exception as e:
        logger.debug("Try_again channel check failed: %s", e)

    if len(args) > 1:
        token = args[1]
        try:
            resp = supabase_call(lambda: supabase.table("videos").select("file_id").eq("token", token).execute())
            if not getattr(resp, "data", None):
                bot_call(bot.send_message, chat_id, "❌ Invalid or deleted link.")
                return
            file_id = resp.data[0]["file_id"]
            send_temp_video(chat_id, file_id, delay_seconds=VIDEO_DELETE_MINUTES * 60, user_id=user_id)
        except Exception as e:
            logger.exception("Try_again error: %s", e)
            bot_call(bot.send_message, chat_id, "❌ Error retrieving the video. Try again later.")
    else:
        bot_call(bot.send_message, chat_id, "✅ You joined! Now you can use the bot.\n\n"  
                                             "👋 Hello there!\n"
                                             "To unlock exclusive premium videos, join our special channel now! 🔥🎥\n\n"
                                             "🔗 Join Here: https://t.me/+iVhgogd-M4wwNGY1\n\n"
                                             "✨ Don’t miss out on high-quality, exclusive content — available only for our premium members! 🚀", protect_content=True)















# ---------------- Video Upload (admins) ----------------
@bot.message_handler(content_types=['video', 'document'])
def handle_video_upload(message: telebot.types.Message):
    user_id = message.from_user.id
    active_users.add(user_id)
    try:
        if not (user_id == OWNER_ID or is_admin(user_id)):
            safe_reply(message, "❌ Only admins can upload videos.")
            return
        video = message.video or (message.document if getattr(message.document, "mime_type", "").startswith("video/") else None)
        if not video:
            safe_reply(message, "⚠️ Please send a valid video file.")
            return
        token = secrets.token_urlsafe(8)
        supabase_call(lambda: supabase.table("videos").insert({
            "token": token,
            "file_id": video.file_id
        }).execute())
        bot_username = bot_call(bot.get_me).username
        link = f"https://t.me/{bot_username}?start={token}"
        safe_reply(message, f"✅ Permanent link generated:\n{link}")
    except Exception as e:
        logger.exception("video upload error: %s", e)
        try:
            safe_reply(message, "❌ Upload failed. Try again later.")
        except Exception:
            pass


# ---------------- Owner/Admin buttons ----------------
@bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text in [
    "➕ Add Admin", "❌ Remove Admin", "👑 List Admins", "📂 List Videos", "🔥 Destroy Video", "📢 Broadcast",
    "🧾 Pending Payments", "📋 Premiums"
])
def handle_buttons(message: telebot.types.Message):
    user_id = message.from_user.id
    text = message.text
    active_users.add(user_id)
    try:
        if text == "➕ Add Admin":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can add admins.")
                return
            with _lock:
                pending_action[user_id] = "add_admin"
            safe_reply(message, "👉 Enter user_id to add as admin:")
            return

        if text == "❌ Remove Admin":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can remove admins.")
                return
            with _lock:
                pending_action[user_id] = "remove_admin"
            safe_reply(message, "👉 Enter user_id to remove from admins:")
            return
        
   
 





        if text == "👑 List Admins":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can list admins.")
                return

            try:
                # fetch only user_id and username
                resp = supabase_call(lambda: supabase.table("admins").select("user_id,username").execute())
                admins = getattr(resp, "data", []) or []
            except Exception as e:
                logger.exception("list admins error: %s", e)
                admins = []

            text_out = "👑 Current Admins:\n"
            text_out += f"- Owner: {OWNER_ID}\n"

            if admins:
                for a in admins:
                    uid = a.get("user_id")
                    if not uid:
                        continue
                    uname = a.get("username")
                    if uname:
                        text_out += f"- {uid}  @{uname}\n"
                    else:
                        text_out += f"- {uid}\n"
            else:
                text_out += "ℹ️ No extra admins."

            safe_reply(message, text_out)
            return


















        if text == "📂 List Videos":
            if not (user_id == OWNER_ID or is_admin(user_id)):
                safe_reply(message, "❌ Only admins can list videos.")
                return
            try:
                resp = supabase_call(lambda: supabase.table("videos").select("token,file_id").execute())
                videos = resp.data or []
            except Exception as e:
                logger.exception("list videos error: %s", e)
                videos = []
            if not videos:
                safe_reply(message, "ℹ️ No videos found.")
                return

            bot_username = bot_call(bot.get_me).username or ""
            batch = []
            for idx, v in enumerate(videos, start=1):
                token = v.get('token') or ""
                link = f"https://t.me/{bot_username}?start={token}"
                batch.append(f"{idx}. 🎬 Token: {token}\n🔗 {link}")

                # Har 40 videos ke baad bhej do
                if len(batch) >= 40:
                    text_out = "📂 Video Links:\n\n" + "\n\n".join(batch)
                    safe_send(message.chat.id, text_out)
                    batch = []

            # agar kuch bacha ho to usko bhi bhej do
            if batch:
                text_out = "📂 Video Links:\n\n" + "\n\n".join(batch)
                safe_send(message.chat.id, text_out)

            return











        if text == "🔥 Destroy Video":
            if not (user_id == OWNER_ID or is_admin(user_id)):
                safe_reply(message, "❌ Only admins can destroy videos.")
                return
            with _lock:
                pending_action[user_id] = "destroy_video"
            safe_reply(message, "👉 Enter token to destroy video:")
            return

        if text == "📢 Broadcast":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can broadcast.")
                return
            with _lock:
                pending_action[user_id] = "broadcast"
            safe_reply(message, "📢 Send me the text, image, or video you want to broadcast:")
            return

        if text == "🧾 Pending Payments":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can view pending payments.")
                return
            try:
                resp = supabase_call(lambda: supabase.table("pending_payments").select("*").order("created_at", desc=True).execute())
                rows = resp.data or []
                if not rows:
                    safe_reply(message, "ℹ️ No pending payments.")
                    return
                out = "🧾 Pending Payments:\n\n"
                for r in rows:
                    uid = r.get("user_id")
                    tier = r.get("tier")
                    price = r.get("price")
                    pid = r.get("id")
                    status = r.get("status")
                    created = r.get("created_at") or ""
                    created_fmt = format_dt_ist(created)
                    uname = ""
                    try:
                        chat_user = bot_call(bot.get_chat, uid)
                        uname = getattr(chat_user, "username", "") or ""
                    except Exception:
                        uname = ""
                    if uname:
                        out += f"Payment id: {pid}\nUsername: @{uname}\nUser: {uid}\nPlan: {tier} — ₹{price}\nStatus: {status}\nCreated: {created_fmt}\n\n"
                    else:
                        out += f"Payment id: {pid}\nUser: {uid}\nPlan: {tier} — ₹{price}\nStatus: {status}\nCreated: {created_fmt}\n\n"
                safe_reply(message, out)
            except Exception as e:
                logger.exception("pending payments error: %s", e)
                safe_reply(message, "❌ Failed to fetch pending payments.")
            return

        if text == "📋 Premiums":
            if user_id != OWNER_ID:
                safe_reply(message, "❌ Only the owner can view premiums.")
                return
            try:
                resp = supabase_call(lambda: supabase.table("subscriptions").select("*").order("expires_at", desc=False).execute())
                rows = resp.data or []
                if not rows:
                    safe_reply(message, "ℹ️ No subscriptions found.")
                    return

                out = "📋 Premium Users:\n\n"
                for r in rows:
                    uid = r.get("user_id")
                    tier = r.get("tier")
                    price = r.get("price")
                    expires = r.get("expires_at")
                    created = r.get("created_at")
                    notify_status = r.get("notify_status", 0)

                    expires_fmt = format_dt_ist(expires)
                    created_fmt = format_dt_ist(created)

                    uname = ""
                    try:
                        chat_user = bot_call(bot.get_chat, uid)
                        uname = getattr(chat_user, "username", "") or ""
                    except Exception:
                        uname = ""

                    if uname:
                        out += (
                            f"Username: @{uname}\n"
                            f"User: {uid}\n"
                            f"Plan: {tier} — ₹{price}\n"
                            f"Taken: {created_fmt}\n"
                            f"Expires: {expires_fmt}\n"
                            f"NotifyStatus: {notify_status}\n\n"
                        )
                    else:
                        out += (
                            f"User: {uid}\n"
                            f"Plan: {tier} — ₹{price}\n"
                            f"Taken: {created_fmt}\n"
                            f"Expires: {expires_fmt}\n"
                            f"NotifyStatus: {notify_status}\n\n"
                        )

                safe_reply(message, out)
                return
            except Exception as e:
                logger.exception("premium list error: %s", e)
                safe_reply(message, "❌ Failed to fetch premiums.")
            return

    except Exception as e:
        logger.exception("handle_buttons error: %s", e)
        try:
            safe_reply(message, "❌ Something went wrong. Try again later.")
        except Exception:
            pass

# ---------------- Pending actions ----------------
@bot.message_handler(func=lambda m: m.from_user.id in pending_action)
def handle_pending(message: telebot.types.Message):
    user_id = message.from_user.id
    with _lock:
        action = pending_action.pop(user_id, None)
    try:
        if action == "add_admin":
            try:
                new_admin_id = int(message.text.strip())
                uname = ""
                try:
                    chat_user = bot_call(bot.get_chat, new_admin_id)
                    uname = getattr(chat_user, "username", "") or ""
                except Exception:
                    uname = ""
                # upsert admin to avoid duplicate-key errors
                supabase_call(lambda: supabase.table("admins").upsert({
                    "user_id": new_admin_id,
                    "username": uname,
                }, on_conflict=["user_id"]).execute())
                safe_reply(message, f"✅ Added admin: {new_admin_id}")
            except Exception as e:
                logger.exception("add_admin error: %s", e)
                safe_reply(message, "❌ Invalid user_id or DB error.")
            return

        if action == "remove_admin":
            try:
                remove_id = int(message.text.strip())
                resp = supabase_call(lambda: supabase.table("admins").delete().eq("user_id", remove_id).execute())
                if getattr(resp, "data", None):
                    safe_reply(message, f"✅ Removed admin: {remove_id}")
                else:
                    safe_reply(message, f"ℹ️ User {remove_id} not found as admin.")
            except Exception as e:
                logger.exception("remove_admin error: %s", e)
                safe_reply(message, "❌ Invalid user_id.")
            return

        if action == "destroy_video":
            token = message.text.strip()
            try:
                resp = supabase_call(lambda: supabase.table("videos").delete().eq("token", token).execute())
                if getattr(resp, "data", None):
                    safe_reply(message, f"🔥 Destroyed video with token {token}")
                else:
                    safe_reply(message, f"ℹ️ Token {token} not found.")
            except Exception as e:
                logger.exception("destroy_video error: %s", e)
                safe_reply(message, "❌ Failed to destroy video.")
            return

        if action == "broadcast":
            try:
                if not active_users:
                    safe_reply(message, "ℹ️ No active users to broadcast.")
                    return
                # run broadcast in a thread to avoid long handler lock
                def _broadcast(msg):
                    sent_count = 0
                    failed_count = 0
                    for uid in list(active_users):
                        try:
                            if msg.content_type == "text":
                                bot_call(bot.send_message, uid, msg.text, protect_content=True)
                            elif msg.content_type == "photo":
                                bot_call(bot.send_photo, uid, msg.photo[-1].file_id, caption=msg.caption or "", protect_content=True)
                            elif msg.content_type == "video":
                                bot_call(bot.send_video, uid, msg.video.file_id, caption=msg.caption or "", protect_content=True)
                            else:
                                continue
                            sent_count += 1
                        except Exception as e:
                            logger.debug("broadcast to %s failed: %s", uid, e)
                            failed_count += 1
                    try:
                        bot_call(bot.send_message, message.chat.id, f"📢 Broadcast finished.\n✅ Sent: {sent_count}\n❌ Failed: {failed_count}")
                    except Exception:
                        pass
                threading.Thread(target=_broadcast, args=(message,), daemon=True).start()
                safe_reply(message, "📢 Broadcasting started.")
            except Exception as e:
                logger.exception("broadcast error: %s", e)
                safe_reply(message, "❌ Broadcast failed.")
            return

    except Exception as e:
        logger.exception("handle_pending error: %s", e)
        try:
            safe_reply(message, "❌ Action failed.")
        except Exception:
            pass

# ---------------- Purchase callbacks ---------------
@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("buy_"))
def handle_purchase_callbacks(call: telebot.types.CallbackQuery):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data
    if data == "buy_1day":
        price = 49; tier = "1day"; days = 1
    elif data == "buy_week":
        price = 129; tier = "weekly"; days = 7
    elif data == "buy_month":
        price = 299; tier = "monthly"; days = 30
    else:
        return
    created = create_pending_payment(user_id, tier, price, days)
    caption = (
        "🔔 Payment Instructions\n\n"
        f"UPI: {UPI_ID}\n\n"
        "1. Scan the QR or pay using the UPI above.\n"
        f"2. Pay ₹{price} for {tier} plan.\n"
        "3. After paying upload the screenshot here (attach image) — do not send other filetypes.\n\n"
        "We’ll verify and grant access once approved."
    )
    try:
        bot_call(bot.send_photo, chat_id, QR_IMAGE_URL, caption=caption, protect_content=True)
    except Exception:
        bot_call(bot.send_message, chat_id, caption)
    try:
        bot.answer_callback_query(call.id, text="Payment instructions sent. Upload screenshot after payment.")
    except Exception:
        pass

# ---------------- Screenshot upload handler ----------
@bot.message_handler(content_types=['photo'])
def handle_payment_screenshot(message: telebot.types.Message):
    user_id = message.from_user.id
    try:
        resp = supabase_call(lambda: supabase.table("pending_payments")
            .select("*")
            .eq("user_id", user_id)
            .in_("status", ["initiated", "awaiting_screenshot", "done"])
            .order("created_at", desc=True)
            .limit(1)
            .execute())
    except Exception as e:
        logger.exception("pending_payments query error: %s", e)
        resp = None
    if not resp or not getattr(resp, "data", None):
        safe_reply(message, "⚠️ No active payment found. Please select a plan first (1 Day / Weekly / Monthly).")
        return
    pay = resp.data[0]
    file_id = message.photo[-1].file_id
    ok = update_pending_with_screenshot(pay["id"], file_id)
    if not ok:
        safe_reply(message, "❌ Failed to save screenshot. Try again later.")
        return
    safe_reply(message, "✅ Screenshot received. We'll verify and notify you after approval. Thank you!")
    # Notify owner with approve/reject buttons
    approve_kb = owner_payment_buttons(pay["id"], pay.get("days_valid") or 1)
    uname = ""
    try:
        chat_user = bot_call(bot.get_chat, user_id)
        uname = getattr(chat_user, "username", "") or ""
    except Exception:
        uname = ""
    lines = []
    if uname:
        lines.append(f"Username: @{uname}")
    lines.append(f"Userid: {user_id}")
    lines.append(f"Plan: {pay.get('tier')} — ₹{pay.get('price')}")
    lines.append(f"Payment id: {pay.get('id')}")
    lines.append(f"Created: {format_dt_ist(pay.get('created_at') or '')}")
    notice = "📥 New payment upload\n\n" + "\n".join(lines) + "\n\nTap Approve to grant subscription or Reject to decline."
    try:
        bot_call(bot.send_photo, OWNER_ID, file_id, caption=notice, reply_markup=approve_kb)
    except Exception:
        bot_call(bot.send_message, OWNER_ID, notice, reply_markup=approve_kb)

# ---------------- Approve / Reject handler ---------------
@bot.callback_query_handler(func=lambda call: call.data and (call.data.startswith("approve_payment:") or call.data.startswith("reject_payment:")))
def handle_payment_approval(call: telebot.types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        try:
            bot.answer_callback_query(call.id, "❌ Only owner can approve/reject payments.")
        except Exception:
            pass
        return
    parts = call.data.split(":")
    action = parts[0]
    try:
        payment_id = int(parts[1])
    except Exception:
        payment_id = None
    if not payment_id:
        try:
            bot.answer_callback_query(call.id, "Invalid payment id.")
        except Exception:
            pass
        return
    try:
        resp = supabase_call(lambda: supabase.table("pending_payments").select("*").eq("id", payment_id).execute())
        if not getattr(resp, "data", None):
            bot.answer_callback_query(call.id, "Payment not found.")
            return
        pending = resp.data[0]
    except Exception as e:
        logger.exception("fetch pending error: %s", e)
        try:
            bot.answer_callback_query(call.id, "Error fetching payment.")
        except Exception:
            pass
        return
    user_id = int(pending.get("user_id"))
    tier = pending.get("tier")
    price = int(pending.get("price") or 0)
    days_default = int(pending.get("days_valid") or 1)
    current_status = pending.get("status")
    if current_status in ("approved", "rejected"):
        try:
            bot.answer_callback_query(call.id, "This payment was already processed.")
        except Exception:
            pass
        return
    if action == "approve_payment":
        days = int(parts[2]) if len(parts) > 2 else days_default
        # try fetch username
        username = ""
        try:
            uobj = bot_call(bot.get_chat, user_id)
            username = getattr(uobj, "username", "") or ""
        except Exception:
            username = ""
        sub = create_subscription(user_id, tier, price, days_valid=days, username=username)
        set_pending_status(payment_id, "approved")
        reset_view_count(user_id)
        expires_fmt = format_dt_ist(sub.get("expires_at") if sub else "")
        # notify user (single message)
        lines = []
        if username:
            lines.append(f"Hello @{username},")
        lines.append(f"✅ Your payment for {tier} (₹{price}) has been approved.")
        lines.append(f"🎟 You have access until {expires_fmt} (IST). Enjoy!")
        to_user = "\n".join(lines)
        try:
            bot_call(bot.send_message, user_id, to_user)
        except Exception:
            pass
        try:
            bot.answer_callback_query(call.id, "Approved and subscription granted.")
        except Exception:
            pass
    elif action == "reject_payment":
        set_pending_status(payment_id, "rejected")
        username = ""
        try:
            uobj = bot_call(bot.get_chat, user_id)
            username = getattr(uobj, "username", "") or ""
        except Exception:
            username = ""
        if username:
            text = f"❌ @{username}, your payment (id {payment_id}) was rejected. Please re-upload a clear screenshot or contact support."
        else:
            text = f"❌ Your payment (id {payment_id}) was rejected. Please re-upload a clear screenshot or contact support."
        try:
            bot_call(bot.send_message, user_id, text)
        except Exception:
            pass
        try:
            bot.answer_callback_query(call.id, "Payment rejected.")
        except Exception:
            pass

# ---------------- Subscription notifier (background) ----------------
def subscription_notifier_loop(interval_seconds: int = 60 * 15):
    """
    Background loop:
    - notify_status 0 -> 1  (24h warning)
    - notify_status !=2 and expired -> set 2 and notify expired
    """
    while True:
        try:
            now = datetime.now(timezone.utc)
            warn_until = now + timedelta(hours=24)

            # 24h warning
            try:
                resp = supabase_call(lambda: supabase.table("subscriptions")
                                     .select("*")
                                     .lt("expires_at", warn_until.isoformat())
                                     .gt("expires_at", now.isoformat())
                                     .eq("notify_status", 0)
                                     .execute())
                items = resp.data or []
            except Exception as e:
                logger.debug("warn query failed: %s", e)
                items = []

            for sub in items:
                uid = int(sub.get("user_id"))
                exp_str = sub.get("expires_at")
                try:
                    exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    exp_dt_ist = exp_dt.astimezone(IST)
                    exp_fmt = exp_dt_ist.strftime("%d-%m-%Y %I:%M %p")
                except Exception:
                    exp_fmt = exp_str
                try:
                    bot_call(bot.send_message, uid, f"⏳ Reminder: Your premium ({sub.get('tier')}) will expire on {exp_fmt} (IST). Renew to keep unlimited access.")
                except Exception:
                    pass
                try:
                    supabase_call(lambda: supabase.table("subscriptions").update({"notify_status": 1}).eq("id", sub.get("id")).execute())
                except Exception:
                    pass

            # Expired notify
            try:
                resp2 = supabase_call(lambda: supabase.table("subscriptions")
                                      .select("*")
                                      .lte("expires_at", now.isoformat())
                                      .neq("notify_status", 2)
                                      .execute())
                expired_items = resp2.data or []
            except Exception as e:
                logger.debug("expired query failed: %s", e)
                expired_items = []

            for sub in expired_items:
                uid = int(sub.get("user_id"))
                try:
                    bot_call(bot.send_message, uid, "⚠️ Your premium subscription has expired. You can buy a new plan to regain unlimited access.")
                except Exception:
                    pass
                try:
                    supabase_call(lambda: supabase.table("subscriptions").update({"notify_status": 2}).eq("id", sub.get("id")).execute())
                except Exception:
                    pass

        except Exception as e:
            logger.exception("subscription_notifier_loop error: %s", e)

        time.sleep(interval_seconds)

# ---------------- Run ----------------

# def auto_ping_loop(interval_seconds: int = 300):
#     """Background loop: every 5 minutes send heartbeat to OWNER_ID"""
#     while True:
#         try:
#             if OWNER_ID:
#                 bot_call(bot.send_message, OWNER_ID, "🤖 Bot heartbeat: still alive!")
#         except Exception as e:
#             logger.debug("auto_ping failed: %s", e)
#         time.sleep(interval_seconds)

if __name__ == "__main__":
    # Start background subscription notifier
    threading.Thread(target=subscription_notifier_loop, daemon=True).start()

# threading.Thread(target=auto_ping_loop, daemon=True).start()

    # Set webhook
    try:
        bot.remove_webhook()
        time.sleep(1)
        # Ensure webhook URL ends up as https://host/<BOT_TOKEN>
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        logger.info("Webhook set successfully: %s", webhook_url)
    except Exception as e:
        logger.exception("Webhook setup error: %s", e)

    # Run Flask app
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
