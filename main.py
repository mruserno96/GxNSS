from flask import Flask, request
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
CHANNEL = os.getenv("CHANNEL")
ADMINS = list(map(int, os.getenv("ADMINS").split(',')))

app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=data)

def send_keyboard(chat_id, buttons):
    keyboard = {
        "keyboard": [[{"text": btn}] for btn in buttons],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    return keyboard

def get_chat_member(chat_id, user_id):
    url = f"{API_URL}/getChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    resp = requests.get(url, params=params)
    return resp.json()

def check_membership(user_id):
    member = get_chat_member(CHANNEL, user_id)
    result = member.get("result")
    if not result:
        return False
    status = result.get("status", "")
    return status in ["member", "administrator"]

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        text = message.get("text", "")

        # Admin handling
        if user_id in ADMINS:
            if text == "/start":
                buttons = send_keyboard(chat_id, ["Help", "View Payments", "View Premium Users"])
                send_message(chat_id, "👋 Welcome Admin! You can manage payments and users here.", buttons)
                return "OK"
            if text == "Help":
                help_text = (
                    "/start - Restart bot\n"
                    "View Payments - See pending payments\n"
                    "View Premium Users - See all premium users"
                )
                send_message(chat_id, help_text)
                return "OK"
            if text == "View Payments":
                payments = supabase.table("payments").select("*").eq("status", "pending").execute()
                lines = []
                for p in payments.data:
                    lines.append(f"ID: {p['chat_id']}\nUsername: {p['username']}\nTime: {p['created_at']}")
                msg = "\n\n".join(lines) if lines else "No pending payments."
                send_message(chat_id, msg)
                return "OK"
            if text == "View Premium Users":
                payments = supabase.table("payments").select("*").eq("users", "premium").execute()
                lines = []
                for p in payments.data:
                    lines.append(f"ID: {p['chat_id']}\nUsername: {p['username']}")
                msg = "\n\n".join(lines) if lines else "No premium users."
                send_message(chat_id, msg)
                return "OK"

        # User handling
        if text == "/start":
            if check_membership(user_id):
                send_message(chat_id, "✅ Channel Joined Successfully!")
                send_message(chat_id, "📚 GxNSS COURSES\n\n🔹 Programming Courses\nC++, Java, Python\n\n🔹 Hacking & Cybersecurity Courses\nBlackHat, Ethical Hacking...")
                buttons = send_keyboard(chat_id, ["Buy Now For ₹79"])
                send_message(chat_id, "🚀 Huge Course Bundle – Now Just ₹79!\nGet access to an enormous collection of high-value courses!", buttons)
            else:
                send_message(chat_id, "⚠ Please join our channel first!", send_keyboard(chat_id, ["Join Channel"]))
        
        elif text == "Buy Now For ₹79":
            image_url = "https://mruser96.42web.io/qr.jpg"
            msg = "📌 UPI - 7219011336@fam\nSend SS of payment with your Telegram username below."
            send_message(chat_id, msg)
            send_message(chat_id, image_url)

        elif text == "Join Channel":
            send_message(chat_id, "Please join the channel and restart the bot.")
        
        elif "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

            supabase.storage.from_("screenshots").upload(filename, file_content)
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/screenshots/{filename}"

            supabase.table("payments").insert({
                "chat_id": user_id,
                "username": username,
                "screenshot_url": public_url,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "users": ""
            }).execute()

            send_message(chat_id, "✅ Screenshot uploaded! Our team will verify your payment soon.")

        elif text.startswith("approve"):
            if user_id in ADMINS:
                parts = text.split()
                if len(parts) == 2 and parts[1].isdigit():
                    target_id = int(parts[1])
                    payments = supabase.table("payments").select("*").eq("chat_id", target_id).eq("status", "pending").execute()
                    if payments.data:
                        supabase.table("payments").update({
                            "status": "approved",
                            "users": "premium"
                        }).eq("chat_id", target_id).execute()
                        send_message(chat_id, f"✅ Approved payment for {target_id}.")
                        send_message(target_id, "🎉 Your payment has been verified! Premium access granted.")
                        buttons = send_keyboard(target_id, ["Hacking Courses", "Programming Courses", "More Courses"])
                        send_message(target_id, "Here are your unlocked premium courses:", buttons)
                    else:
                        send_message(chat_id, f"❌ No pending payment found for {target_id}")
                else:
                    send_message(chat_id, "Usage: approve <user_chat_id>")
        
        elif text in ["Hacking Courses", "Programming Courses", "More Courses"]:
            send_message(chat_id, f"Here are the {text.lower()}!")
        
        else:
            send_message(chat_id, "Unknown command. Please use /start.")

    return "OK"

@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    requests.post(url, json=data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
