import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request
from dotenv import load_dotenv
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.startup.register(lambda _: set_webhook())
app = Flask(__name__)

# Channel usernames
CHANNEL_1 = "@GxNSSgiveaway"
CHANNEL_2 = "@GxNSSTOOLS"

async def set_webhook():
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    update = types.Update(**data)
    asyncio.run(dp.feed_update(bot, update))
    return "OK"

@dp.message(commands=["start"])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("Join Channel 1", url="https://t.me/GxNSSgiveaway"),
        InlineKeyboardButton("Join Channel 2", url="https://t.me/GxNSSTOOLS"),
        InlineKeyboardButton("✅ Try Again", callback_data="check_join")
    )
    await message.answer("📢 Please join both channels to access premium courses.", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "check_join")
async def check_join(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    try:
        member1 = await bot.get_chat_member(CHANNEL_1, user_id)
        member2 = await bot.get_chat_member(CHANNEL_2, user_id)
    except Exception as e:
        await callback_query.answer("Error checking membership.", show_alert=True)
        return

    if member1.status in ['member', 'administrator'] and member2.status in ['member', 'administrator']:
        await bot.send_message(user_id, "✅ You have joined both channels! Now you can access the premium courses.")
        # Aage ka message bhejo yahan
    else:
        await callback_query.answer("⚠ Please join both channels first!", show_alert=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
