from telebot import types
from bot import bot
from bot.utils import get_user_cached, is_member_of_channel, notify_admins
from courses import COURSES_MESSAGE, PROMO_MESSAGE
from bot.utils import save_message
from supabase import supabase

@bot.message_handler(commands=["start"])
def send_welcome(message):
    user = get_user_cached(message.from_user.id)
    cid = message.chat.id
    if user and user.get("status") == "premium":
        from bot.handlers.menu import main_menu_keyboard
        bot.send_message(cid, "🎉 Welcome back Premium User!", reply_markup=main_menu_keyboard())
        return

    if is_member_of_channel(message.from_user.id):
        sent = bot.send_message(cid, COURSES_MESSAGE, parse_mode="Markdown")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Buy Course For ₹79", callback_data="buy"))
        bot.send_message(cid, PROMO_MESSAGE, parse_mode="Markdown", reply_markup=markup)
    else:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"))
        kb.add(types.InlineKeyboardButton("✅ Try Again", callback_data="check_join"))
        bot.send_message(cid, "💬 Please join the channel first.", reply_markup=kb)
