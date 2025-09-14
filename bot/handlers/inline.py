from telebot import types
from bot import bot
from bot.utils import get_user_cached
from courses import PAYMENT_INSTRUCTIONS, QR_IMAGE_URL

@bot.callback_query_handler(func=lambda c: c.data == "buy")
def handle_buy(call):
    cid = call.message.chat.id
    instr_markup = types.InlineKeyboardMarkup()
    instr_markup.add(types.InlineKeyboardButton("I Paid (Upload Screenshot)", callback_data="i_paid"))
    bot.send_photo(cid, QR_IMAGE_URL, caption=PAYMENT_INSTRUCTIONS, reply_markup=instr_markup)
