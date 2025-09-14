import logging
from telebot import TeleBot
from supabase import create_client
from config import BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = TeleBot(BOT_TOKEN, threaded=True, num_threads=10)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
