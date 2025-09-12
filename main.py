import os
import io
import logging
from datetime import datetime

from flask import Flask, request, abort
import telebot
from telebot import types
from supabase import create_client, Client
from dotenv import load_dotenv

# Load .env locally (Render will use environment variables)
load_dotenv()

# --- Config from environment ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")  # e.g. https://your-app.onrender.com
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # service role key (server only)
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")  # storage bucket name
PRIVATE_BUCKET = os.getenv("PRIVATE_BUCKET", "false").lower() in ("1", "true", "yes")
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", "")  # comma separated admin ids for notifications (optional)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is required")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

# Optional configuration
UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")  # e.g. 'payments' => files go under payments/{user}/{ts}.jpg
SIGNED_URL_TTL_SECONDS = int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))  # 1 hour

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup Telegram bot and Flask app
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Setup Supabase client (server side)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Helper: find or create user row by telegram id
def find_or_create_user(telegram_id: int, username: str | None, first_name: str | None = None, last_name: str | None = None):
    """
    Returns user row dict (as stored in your users table).
    Expects your users table to have columns: telegram_id (unique), username, status, created_at
    """
    try:
        # Try to find existing user
        resp = supabase.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
        if resp.data and len(resp.data) > 0:
            user = resp.data[0]
            # Optionally update username if changed
            updated = False
            upd_payload = {}
            if username and user.get("username") != username:
                upd_payload["username"] = username
                updated = True
            if first_name and user.get("first_name") != first_name:
                upd_payload["first_name"] = first_name
                updated = True
            if last_name and user.get("last_name") != last_name:
                upd_payload["last_name"] = last_name
                updated = True
            if updated:
                upd_payload["updated_at"] = datetime.utcnow().isoformat()
                supabase.table("users").update(upd_payload).eq("telegram_id", telegram_id).execute()
                # re-fetch
                resp2 = supabase.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
                return resp2.data[0]
            return user
        else:
            # Create user
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
            if ins.error:
                logger.error("Error creating user: %s", ins.error)
                return None
            return ins.data[0]
    except Exception as e:
        logger.exception("find_or_create_user error: %s", e)
        return None

# Helper: upload bytes to supabase storage and return object path and URL
def upload_screenshot_bytes(bucket: str, object_path: str, file_bytes: bytes, content_type: str = "image/jpeg"):
    """
    Uploads bytes to the specified bucket and returns (object_path, url).
    If PRIVATE_BUCKET is true, returns a signed URL; otherwise a public URL.
    """
    try:
        # object_path should not start with /
        object_path = object_path.lstrip("/")
        # Upload - supabase python client expects bytes or file-like
        resp = supabase.storage.from_(bucket).upload(object_path, io.BytesIO(file_bytes), {"content-type": content_type})
        # resp might be a dict (varies by package version)
        logger.info("Supabase storage upload response: %s", resp)
        # Build URL: if private, create signed url; else get public url
        if PRIVATE_BUCKET:
            signed_resp = supabase.storage.from_(bucket).create_signed_url(object_path, SignedUrlExpire=SIGNED_URL_TTL_SECONDS) if hasattr(supabase.storage.from_(bucket), "create_signed_url") else supabase.storage.from_(bucket).create_signed_url(object_path, SIGNED_URL_TTL_SECONDS)
            # newer client returns dict with 'signedURL' or 'signed_url'
            if isinstance(signed_resp, dict):
                url = signed_resp.get("signedURL") or signed_resp.get("signed_url") or signed_resp.get("signedUrl")
            else:
                url = signed_resp
        else:
            public_resp = supabase.storage.from_(bucket).get_public_url(object_path)
            if isinstance(public_resp, dict):
                url = public_resp.get("publicURL") or public_resp.get("public_url") or public_resp.get("publicUrl")
                if not url:
                    # some clients return {'data': {'publicUrl': '...'}}
                    data = public_resp.get("data")
                    if data and isinstance(data, dict):
                        url = data.get("publicUrl") or data.get("public_url")
            else:
                # fallback: attempt to construct url manually
                url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{object_path}"
        return object_path, url
    except Exception as e:
        logger.exception("upload_screenshot_bytes error: %s", e)
        return None, None

# Helper: create payment row
def create_payment_row(user_row: dict, file_path: str, file_url: str, username: str | None, amount: int | None = None, currency: str | None = "INR"):
    """
    Inserts a payments row and returns the inserted row.
    Required columns in payments table: user_id (FK to users.id), file_path, file_url, username, verified (bool), created_at
    """
    try:
        payload = {
            "user_id": user_row.get("id"),
            "username": username,
            "file_path": file_path,
            "file_url": file_url,
            "amount": amount,
            "currency": currency,
            "payment_method": "UPI",
            "verified": False,
            "verified_by": None,
            "verified_at": None,
            "notes": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        resp = supabase.table("payments").insert(payload).execute()
        if resp.error:
            logger.error("Error inserting payment row: %s", resp.error)
            return None
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return None
    except Exception as e:
        logger.exception("create_payment_row error: %s", e)
        return None

# Helper: notify admins (optional)
def notify_admins(text: str):
    if not ADMIN_TELEGRAM_IDS:
        return
    ids = [int(x.strip()) for x in ADMIN_TELEGRAM_IDS.split(",") if x.strip()]
    for admin_id in ids:
        try:
            bot.send_message(admin_id, text)
        except Exception as e:
            logger.exception("Failed to notify admin %s: %s", admin_id, e)

# Bot handlers
@bot.message_handler(commands=["start"])
def send_welcome(message: types.Message):
    chat_id = message.chat.id
    try:
        welcome = (
            "Welcome! To buy the premium bundle, press Buy and pay via UPI. "
            "After payment, upload your payment screenshot in this chat and we'll verify it."
        )
        bot.send_message(chat_id, welcome)
    except Exception as e:
        logger.exception("send_welcome error: %s", e)

@bot.message_handler(func=lambda m: True, content_types=["photo", "document", "text"])
def handle_all_messages(message: types.Message):
    """
    This handler will:
      - if user sends a photo or document -> treat as payment screenshot
      - otherwise ignore or reply with guidance
    """
    chat_id = message.chat.id
    user = message.from_user
    username = user.username if user and hasattr(user, "username") else None
    first_name = user.first_name if user and hasattr(user, "first_name") else None
    last_name = user.last_name if user and hasattr(user, "last_name") else None

    # If photo or document => process upload
    if message.content_type == "photo":
        try:
            # Telegram sends photos with different sizes; pick the largest
            photo_sizes = message.photo
            largest = sorted(photo_sizes, key=lambda p: p.file_size or 0)[-1]
            file_id = largest.file_id
            process_payment_screenshot(chat_id, file_id, username, first_name, last_name)
        except Exception as e:
            logger.exception("photo handling error: %s", e)
            bot.send_message(chat_id, "Sorry, something went wrong while processing your screenshot.")
    elif message.content_type == "document":
        try:
            file_id = message.document.file_id
            process_payment_screenshot(chat_id, file_id, username, first_name, last_name)
        except Exception as e:
            logger.exception("document handling error: %s", e)
            bot.send_message(chat_id, "Sorry, something went wrong while processing your screenshot.")
    else:
        # basic guidance for text messages
        text = message.text.strip().lower() if message.text else ""
        if "i paid" in text or "paid" in text:
            bot.send_message(chat_id, "Thanks — please upload the payment screenshot in this chat now.")
        else:
            bot.send_message(chat_id, "To pay: use the UPI given earlier and then upload the payment screenshot here. If you already paid, type 'I paid' and upload the screenshot.")

def process_payment_screenshot(chat_id: int, file_id: str, username: str | None, first_name: str | None, last_name: str | None):
    """
    Download file from Telegram, upload to Supabase Storage, create/find user and insert payments row.
    """
    try:
        # 1) Download file bytes from Telegram
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path  # e.g. 'photos/file_abc.jpg' or 'documents/file.pdf'
        downloaded = bot.download_file(file_path)  # bytes

        if not downloaded:
            bot.send_message(chat_id, "Could not download the file. Please try again.")
            return

        # 2) Resolve user row (create if necessary)
        user_row = find_or_create_user(chat_id, username, first_name, last_name)
        if not user_row:
            bot.send_message(chat_id, "Internal error: could not find or create your user record. Try again later.")
            return

        # 3) Build object path and upload to Supabase storage
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        safe_username = (username or f"user_{chat_id}").replace("@", "")
        ext = os.path.splitext(file_path)[1] or ".jpg"
        object_path = f"{UPLOAD_FOLDER_PREFIX}/{safe_username}/{chat_id}_{ts}{ext}"

        # try determine content type by extension
        content_type = "image/jpeg"
        if ext.lower().endswith(".png"):
            content_type = "image/png"
        elif ext.lower().endswith(".pdf"):
            content_type = "application/pdf"

        uploaded_path, public_url = upload_screenshot_bytes(BUCKET_NAME, object_path, downloaded, content_type=content_type)
        if not uploaded_path or not public_url:
            bot.send_message(chat_id, "Failed to upload screenshot to storage. Try again later.")
            return

        # 4) Create a payments row
        payment_row = create_payment_row(user_row, uploaded_path, public_url, username=username)
        if not payment_row:
            bot.send_message(chat_id, "Failed to record payment. Please contact admin.")
            return

        # 5) Notify user and optionally admins
        bot.send_message(chat_id, "Screenshot received. We'll verify and notify you once approved. Thank you!")
        admin_text = f"New payment screenshot uploaded.\nUser: {username or chat_id} ({chat_id})\nPayment row id: {payment_row.get('id')}\nPreview: {public_url}"
        notify_admins(admin_text)

    except Exception as e:
        logger.exception("process_payment_screenshot error: %s", e)
        bot.send_message(chat_id, "An error occurred while processing your upload. Try again later.")

# Routes for webhook and health
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    try:
        bot.remove_webhook()
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        return f"Webhook set to {webhook_url}", 200
    except Exception as e:
        logger.exception("set_webhook error: %s", e)
        return f"Failed to set webhook: {e}", 500

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    # Telegram posts JSON with content-type application/json
    if request.headers.get("content-type") != "application/json":
        abort(403)
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        logger.exception("Failed to process update: %s", e)
    return "OK", 200

# For local debug
if __name__ == "__main__":
    # Optionally set webhook locally or run polling
    # For Render, use gunicorn (Procfile) and call /set_webhook once after deploy
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
