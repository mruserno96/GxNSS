import os
from datetime import datetime
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from threading import Thread
from appwrite.client import Client
from appwrite.services.databases import Databases
from appwrite.services.storage import Storage
from appwrite.input_file import InputFile
from appwrite.id import ID
from appwrite.query import Query

# ---------------- Load env ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
APPWRITE_URL = os.getenv("APPWRITE_URL")
APPWRITE_PROJECT = os.getenv("APPWRITE_PROJECT")
APPWRITE_API_KEY = os.getenv("APPWRITE_API_KEY")
DB_ID = os.getenv("APPWRITE_DB_ID")
COLLECTION_ID = os.getenv("APPWRITE_COLLECTION_ID")
BUCKET_ID = os.getenv("APPWRITE_BUCKET_ID")
CHANNEL = os.getenv("CHANNEL")
ADMINS = [8356178010, 1929429459]

# ---------------- Init ----------------
app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

client = Client()
client.set_endpoint(APPWRITE_URL).set_project(APPWRITE_PROJECT).set_key(APPWRITE_API_KEY)

databases = Databases(client)
storage = Storage(client)

# ---------------- Telegram Helpers ----------------
def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    return requests.post(f"{API_URL}/sendMessage", json=data).json()

def send_photo(chat_id, photo_url, caption=None):
    data = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "Markdown"
    return requests.post(f"{API_URL}/sendPhoto", json=data).json()

def get_chat_member(chat_id, user_id):
    url = f"{API_URL}/getChatMember"
    return requests.get(url, params={"chat_id": chat_id, "user_id": user_id}).json()

def check_membership(user_id):
    result = get_chat_member(CHANNEL, user_id).get("result")
    return result and result.get("status") in ["member", "administrator"]

def is_premium(user_id):
    payments = databases.list_documents(
        DB_ID,
        COLLECTION_ID,
        [Query.equal("chat_id", user_id), Query.equal("status", "premium")]
    )
    return len(payments["documents"]) > 0

def build_keyboard(button_list):
    return {"keyboard": [[btn] for btn in button_list], "resize_keyboard": True, "one_time_keyboard": False}

# ---------------- Static Texts ----------------
def get_courses_text():
    return "📚 GxNSS COURSES\n(Your course list here…)"

def get_offer_text():
    return "🚀 Huge Course Bundle – Now Just ₹79! (Originally ₹199)\nGet all courses today for only ₹79!"

def get_upi_text():
    return "💳 UPI ID: 7219011336@fam\nSend a screenshot of your payment with your Telegram username."

# ---------------- Process Updates ----------------
def process_update(data):
    if "message" not in data:
        return

    message = data["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    username = message["from"].get("username", "")
    text = message.get("text", "")

    # ----- Admin -----
    if user_id in ADMINS:
        if text == "/start":
            send_message(chat_id, "👋 Hello Admin!", build_keyboard(["Help", "View Payments", "View Premium Users"]))
        elif text == "Help":
            send_message(chat_id, "/start - Restart bot\nView Payments - Pending\nView Premium Users - Premium list")
        elif text == "View Payments":
            payments = databases.list_documents(DB_ID, COLLECTION_ID, [Query.equal("status", "pending")])
            lines = [f"Chat ID: {p['chat_id']}\nUsername: @{p.get('username','N/A')}" for p in payments["documents"]]
            send_message(chat_id, "\n".join(lines) if lines else "No pending payments.")
        elif text == "View Premium Users":
            payments = databases.list_documents(DB_ID, COLLECTION_ID, [Query.equal("status", "premium")])
            lines = [f"Chat ID: {p['chat_id']}\nUsername: @{p.get('username','N/A')}" for p in payments["documents"]]
            send_message(chat_id, "\n".join(lines) if lines else "No premium users.")
        return

    # ----- User -----
    if text == "/start":
        if is_premium(user_id):
            send_message(chat_id, "✅ Welcome back Premium User!")
            send_message(chat_id, get_courses_text())
        elif check_membership(user_id):
            send_message(chat_id, "✅ Channel Joined Successfully!")
            send_message(chat_id, get_courses_text(), build_keyboard(["Buy Now For ₹79"]))
            send_message(chat_id, get_offer_text())
        else:
            send_message(chat_id, "⚠ Please join the channel first.", build_keyboard(["Join Channel", "Try Again"]))
        return

    if text == "Join Channel":
        send_message(chat_id, f"🔗 Join here: https://t.me/{CHANNEL.strip('@')}")
        return

    if text == "Try Again":
        if is_premium(user_id):
            send_message(chat_id, "✅ Welcome back Premium User!")
            send_message(chat_id, get_courses_text())
        elif check_membership(user_id):
            send_message(chat_id, "✅ Channel Joined Successfully!")
            send_message(chat_id, get_courses_text(), build_keyboard(["Buy Now For ₹79"]))
            send_message(chat_id, get_offer_text())
        else:
            send_message(chat_id, "⚠ Still not a member.", build_keyboard(["Join Channel", "Try Again"]))
        return

    if text == "Buy Now For ₹79":
        send_photo(chat_id, "https://mruser96.42web.io/qr.jpg")
        send_message(chat_id, get_upi_text())
        return

    # ----- Payment Screenshot -----
    if "photo" in message:
        try:
            file_id = message["photo"][-1]["file_id"]
            file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

            # Upload to Appwrite Storage
            result = storage.create_file(
                BUCKET_ID,
                ID.unique(),
                InputFile.from_bytes(file_content, filename)
            )
            public_url = f"{APPWRITE_URL}/storage/buckets/{BUCKET_ID}/files/{result['$id']}/view?project={APPWRITE_PROJECT}"

            # Insert DB record
            databases.create_document(
                DB_ID,
                COLLECTION_ID,
                ID.unique(),
                {
                    "chat_id": user_id,
                    "username": username,
                    "screenshot_url": public_url,
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat()
                }
            )
            send_message(chat_id, "✅ Screenshot uploaded! We will verify your payment.")
        except Exception as e:
            print("Error handling photo:", e)
            send_message(chat_id, "❌ Failed to upload screenshot. Please try again.")
        return

# ---------------- Webhook ----------------
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    # Respond immediately to Telegram
    Thread(target=process_update, args=(data,)).start()
    return jsonify({"status": "ok"})

# ---------------- Set Webhook ----------------
@app.before_first_request
def set_webhook():
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    try:
        resp = requests.post(url, json=data)
        print("Webhook set:", resp.text)
    except Exception as e:
        print("Webhook error:", e)

# ---------------- Run Flask ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
