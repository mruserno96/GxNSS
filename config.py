import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "screenshots")
UPLOAD_FOLDER_PREFIX = os.getenv("UPLOAD_FOLDER_PREFIX", "payments")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@GxNSSupdates")
ADMIN_TELEGRAM_IDS = set(
    int(x.strip()) for x in (os.getenv("ADMIN_TELEGRAM_IDS", "")).split(",") if x.strip().isdigit()
)
