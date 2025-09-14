import time
from datetime import datetime
from bot import bot, supabase
from config import ADMIN_TELEGRAM_IDS, CHANNEL_USERNAME

USER_CACHE = {}
USER_CACHE_TTL = 30

def get_user_cached(telegram_id):
    now = time.time()
    cached = USER_CACHE.get(telegram_id)
    if cached and cached[1] > now:
        return cached[2]
    # fetch from DB
    try:
        resp = supabase.table("users").select("*").eq("telegram_id", telegram_id).single().execute()
        user_row = resp.data
    except Exception:
        user_row = None
    USER_CACHE[telegram_id] = (user_row.get("status") if user_row else None, now + USER_CACHE_TTL, user_row)
    return user_row

def invalidate_user_cache(telegram_id):
    USER_CACHE.pop(telegram_id, None)

def is_admin(user_id):
    return int(user_id) in ADMIN_TELEGRAM_IDS

def notify_admins(text):
    for aid in ADMIN_TELEGRAM_IDS:
        try:
            bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass

def is_member_of_channel(user_id):
    try:
        cm = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return cm.status not in ("left", "kicked", None)
    except Exception:
        return False
