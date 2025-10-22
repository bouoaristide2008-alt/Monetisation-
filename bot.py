      # bot.py
"""
Bot Telegram - Monétisation automatique
- No secrets in code: use env vars on Render
- SQLite persistence, requests.Session with retries, Paystack webhook signature check,
  background delivery (thread), webhook-based Telegram updates handling.

### MODIFICATIONS APPORTÉES :
### 1. Ajout de DB_LOCK pour sécuriser les accès SQLite en environnement multi-thread.
### 2. Remplacement de 'context.application.user_data[user_id]' par 'context.user_data' 
###    dans les gestionnaires de conversation (plus idiomatique pour ConversationHandler).
### 3. CORRECTION DU RUNTIMEWARNING : Utilisation de asyncio.run() pour await set_webhook.
### 4. CORRECTION DU PTBUSERWARNING : Ajout de per_message=True au CallbackQueryHandler.
"""

import os
import logging
import json
import sqlite3
import threading
import asyncio
import time
import hmac
import hashlib
from typing import Optional, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# -------------------------
# Configuration via env vars
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
EXTERNAL_URL = os.getenv("EXTERNAL_URL", "").strip()  # ex: https://monbot.onrender.com

# Paystack secrets (must be set in Render)
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "").strip()

# Optional static Paystack links (if you create Paystack pay pages)
PAYSTACK_TIKTOK = os.getenv("PAYSTACK_TIKTOK", "").strip()
PAYSTACK_FACEBOOK = os.getenv("PAYSTACK_FACEBOOK", "").strip()

# Tutorial / support (can be in env or hardcode here)
TUTORIAL_LINK = os.getenv("TUTORIAL_LINK", "").strip()  # ex: https://t.me/mon_canal_tutoriel
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "").strip() or "https://wa.me/0000000000"

# Prices (defaults)
PRICE_TIKTOK = os.getenv("PRICE_TIKTOK", "6000")
PRICE_FACEBOOK = os.getenv("PRICE_FACEBOOK", "8000")

# Admin / group (optional)
GROUP_ID = int(os.getenv("GROUP_ID", "0"))  # ex -100...
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # csv of ints

# DB
DB_PATH = os.getenv("DB_PATH", "orders.db")
PORT = int(os.getenv("PORT", 5000))

# -------------------------
# Logging
# -------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("monetisation-bot")

# -------------------------
# Flask app (exposed as flask_app)
# -------------------------
flask_app = Flask(__name__)

# -------------------------
# Telegram application (built later)
# -------------------------
telegram_app: Optional[Application] = None

# -------------------------
# HTTP session with retries
# -------------------------
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# -------------------------
# Conversation states
# -------------------------
SERVICE, COUNTRY, WHATSAPP = range(3)

# -------------------------
# Database helpers (SQLite)
# -------------------------
# Ajout d'un verrou pour sérialiser les accès à SQLite
DB_LOCK = threading.Lock()

def init_db(path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_orders (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                service TEXT,
                country TEXT,
                whatsapp TEXT,
                created_at INTEGER,
                paid INTEGER DEFAULT 0,
                pay_reference TEXT
            )
            """
        )
        conn.commit()
        conn.close()

def save_order(user_id: int, data: Dict, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            "REPLACE INTO pending_orders (user_id, username, service, country, whatsapp, created_at, paid) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, data.get("username"), data.get("service"), data.get("country"), data.get("whatsapp"), int(time.time()), 0)
        )
        conn.commit()
        conn.close()

def load_order(user_id: int, path: str = DB_PATH) -> Optional[Dict]:
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT username, service, country, whatsapp, paid, pay_reference FROM pending_orders WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
    if row:
        return {"username": row[0], "service": row[1], "country": row[2], "whatsapp": row[3], "paid": row[4], "pay_reference": row[5]}
    return None

def mark_order_paid_by_user(user_id: int, reference: str, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("UPDATE pending_orders SET paid = 1, pay_reference = ? WHERE user_id = ?", (reference, user_id))
        conn.commit()
        conn.close()

def delete_order(user_id: int, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("DELETE FROM pending_orders WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

# -------------------------
# Helpers
# -------------------------
def get_admin_ids():
    if not ADMIN_IDS:
        return []
    return [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

# -------------------------
# UI texts (FR)
# -------------------------
TEXT = {
    "start": "👋 Bienvenue ! Choisissez la plateforme à monétiser :",
    "ask_country": "🌍 Dans quel pays êtes-vous ?",
    "ask_whatsapp": "📞 Envoie ton numéro WhatsApp (format international, ex: +22570xxxxxxx) :",
    "price_tiktok": f"💰 Prix TikTok : *{PRICE_TIKTOK} F CFA*.",
    "price_facebook": f"💰 Prix Facebook : *{PRICE_FACEBOOK} F CFA*.",
    "after_payment": "🔔 Après paiement, Paystack redirigera automatiquement vers la vidéo tutoriel (et le bot confirmera).",
    "admin_note": "🔰 Vous êtes admin — accès direct au tutoriel.",
    "pay_error": "❌ Impossible de générer le lien de paiement. Contactez le support.",
    "cancel": "❌ Commande annulée. Tape /start pour recommencer.",
    "thanks_auto": "✅ Paiement confirmé. Voici le tutoriel :"
}

# -------------------------
# Keyboards
# -------------------------
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎬 Monétiser TikTok", callback_data="tiktok")],
        [InlineKeyboardButton("📘 Monétiser Facebook", callback_data="facebook")],
        [InlineKeyboardButton("ℹ️ Comment ça marche", url=TUTORIAL_LINK or "https://t.me/")],
        [InlineKeyboardButton("📞 Contacter Support", url=SUPPORT_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

def pay_button_by_service(pay_url: str):
    kb = [[InlineKeyboardButton("💳 Payer maintenant", url=pay_url)], [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Paystack helpers
# -------------------------
def initialize_paystack_transaction(user_id: int, service: str, email: str, amount: str, whatsapp: str) -> Optional[str]:
    """
    Initialize Paystack transaction via API, return authorization_url or None.
    metadata includes telegram_id and service_type to match after webhook.
    """
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY not set")
        return None
    try:
        # NOTE: If prices were converted to int early, this try/except would be unnecessary
        amount_kobo = int(amount) * 100
    except Exception as e:
        logger.exception("Invalid amount: %s", e)
        return None

    url = "https://api.paystack.co/transaction/initialize"
    metadata = {
        "custom_fields": [
            {"display_name": "Telegram ID", "variable_name": "telegram_id", "value": str(user_id)},
            {"display_name": "Service", "variable_name": "service_type", "value": service},
            {"display_name": "WhatsApp", "variable_name": "whatsapp_number", "value": whatsapp},
        ]
    }
    payload = {
        "email": email,
        "amount": amount_kobo,
        "metadata": metadata,
        "callback_url": f"{EXTERNAL_URL}/thank-you" if EXTERNAL_URL else None
    }
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    try:
        resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status"):
            return data["data"]["authorization_url"]
        logger.error("Paystack init failed: %s", data)
        return None
    except requests.RequestException as e:
        logger.exception("Paystack initialize error: %s", e)
        return None

def verify_paystack_transaction(reference: str) -> Optional[Dict]:
    """Verify transaction via Paystack API and return verification data if success."""
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY not set (verify)")
        return None
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") and data.get("data", {}).get("status") == "success":
            return data["data"]
        logger.warning("Paystack verify not successful: %s", data)
        return None
    except requests.RequestException as e:
        logger.exception("Paystack verify error: %s", e)
        return None

# -------------------------
# Delivery (async)
# -------------------------
async def deliver_tutorial(user_id: int, service: str, reference: str, app: Application):
    """Send tutorial link to user and notify admin group. Add small sleeps to avoid rate limits."""
    try:
        text = f"{TEXT['thanks_auto']}\n{TUTORIAL_LINK}" if TUTORIAL_LINK else TEXT['thanks_auto']
        await app.bot.send_message(chat_id=user_id, text=text)
        await asyncio.sleep(0.15)  # tiny pause
    except Exception:
        logger.exception("Failed to send tutorial to %s", user_id)

    # Notify admin group
    order = load_order(user_id) or {}
    admin_msg = (
        f"🎉 PAIEMENT CONFIRMÉ\n"
        f"• Utilisateur: {user_id}\n"
        f"• Service: {service}\n"
        f"• Réf: {reference}\n"
        f"• Pays: {order.get('country','N/A')}\n"
        f"• WhatsApp: {order.get('whatsapp','N/A')}"
    )
    try:
        if GROUP_ID:
            await app.bot.send_message(chat_id=GROUP_ID, text=admin_msg)
    except Exception:
        logger.exception("Failed to notify admin group")

    # cleanup
    try:
        delete_order(user_id)
    except Exception:
        logger.exception("Failed to delete order after delivery")

# helper to run async deliver in background thread
def start_delivery_bg(user_id: int, service: str, reference: str, app: Application):
    try:
        # Use a new event loop for the thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(deliver_tutorial(user_id, service, reference, app))
        loop.close()
    except Exception:
        logger.exception("Error running deliver_tutorial in bg")

# -------------------------
# Telegram handlers
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT["start"], reply_markup=main_menu_keyboard())
    return SERVICE

async def handler_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    
    if data in ("tiktok", "facebook"):
        context.user_data["service"] = data
        context.user_data["username"] = q.from_user.username or ""
        # Modification du message précédent pour une UI plus propre
        await q.message.edit_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY

    await q.message.reply_text("Option inconnue.")
    return ConversationHandler.END

async def handler_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["country"] = update.message.text.strip()
    await update.message.reply_text(TEXT["ask_whatsapp"])
    return WHATSAPP

async def handler_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    context.user_data["whatsapp"] = update.message.text.strip()
    user_data = context.user_data # Récupération des données pour la persistance

    # persist order
    save_order(user_id, user_data)

    # Admin direct access
    if is_admin(user_id):
        await update.message.reply_text(TEXT["admin_note"])
        if TUTORIAL_LINK:
            await update.message.reply_text(f"Voici le tutoriel :\n{TUTORIAL_LINK}")
        delete_order(user_id)
        # Nettoyage des données de conversation
        context.user_data.clear() # Ajout d'un nettoyage explicite
        return ConversationHandler.END

    # Prepare payment link (static or dynamic)
    service = user_data.get("service")
    if service == "tiktok":
        amount = PRICE_TIKTOK
        if PAYSTACK_TIKTOK:
            pay_url = PAYSTACK_TIKTOK
        else:
            pay_url = initialize_paystack_transaction(user_id, "tiktok", f"telegram{user_id}@noemail.local", PRICE_TIKTOK, user_data.get("whatsapp",""))
    else:
        amount = PRICE_FACEBOOK
        if PAYSTACK_FACEBOOK:
            pay_url = PAYSTACK_FACEBOOK
        else:
            pay_url = initialize_paystack_transaction(user_id, "facebook", f"telegram{user_id}@noemail.local", PRICE_FACEBOOK, user_data.get("whatsapp",""))

    if not pay_url:
        await update.message.reply_text(TEXT["pay_error"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support", url=SUPPORT_LINK)]]))
        delete_order(user_id)
        context.user_data.clear() # Nettoyage en cas d'erreur
        return ConversationHandler.END

    # send recap + pay link
    price_text = TEXT["price_tiktok"] if service == "tiktok" else TEXT["price_facebook"]
    await update.message.reply_text(f"{price_text}\n\n{TEXT['after_payment']}", reply_markup=pay_button_by_service(pay_url))
    
    return ConversationHandler.END

async def handler_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Répondre au callback_query (si l'annulation vient d'un bouton inline)
    if q:
        await q.answer()
        await q.message.edit_text(TEXT["cancel"], reply_markup=None)
    else:
        # Si l'annulation vient d'une commande /cancel
        await update.message.reply_text(TEXT["cancel"])
    
    user_id = update.effective_user.id
    delete_order(user_id)
    context.user_data.clear() # Nettoyage des données de conversation
    return ConversationHandler.END

async def admin_send_tutorial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Commande réservée aux admins.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /sendtutorial <telegram_user_id>")
        return
    try:
        tid = int(args[0])
        if TUTORIAL_LINK:
            await context.bot.send_message(chat_id=tid, text=f"Voici le tutoriel :\n{TUTORIAL_LINK}")
            await update.message.reply_text("Tutoriel envoyé.")
        else:
            await update.message.reply_text("TUTORIAL_LINK non configuré.")
    except Exception:
        logger.exception("admin_send_tutorial error")
        await update.message.reply_text("Erreur lors de l'envoi.")

# -------------------------
# Flask endpoints (webhooks)
# -------------------------
@flask_app.route("/telegram-webhook/" + (TELEGRAM_TOKEN or "token_missing"), methods=["POST"])
def telegram_webhook():
    """Receive Telegram updates (set webhook to EXTERNAL_URL/telegram-webhook/<TOKEN>)"""
    global telegram_app
    if not telegram_app:
        return "app not ready", 503
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    # Process update in background to avoid blocking webhook
    threading.Thread(target=lambda: asyncio.run(telegram_app.process_update(update)), daemon=True).start()
    return "ok", 200

@flask_app.route("/paystack-webhook", methods=["POST"])
def paystack_webhook():
    """Handle Paystack webhook: verify signature and process successful charges"""
    payload = request.data or b""
    
    try:
        data = request.get_json(force=True)
    except Exception:
        logger.exception("Invalid JSON in Paystack webhook")
        return jsonify({"status": "error", "message": "invalid json"}), 400

    # Verify signature header if available (use PAYSTACK_WEBHOOK_SECRET)
    signature = request.headers.get("x-paystack-signature", "")
    if PAYSTACK_WEBHOOK_SECRET:
        computed = hmac.new(PAYSTACK_WEBHOOK_SECRET.encode(), payload, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(computed, signature):
            logger.warning("Invalid Paystack webhook signature")
            return jsonify({"status": "error", "message": "invalid signature"}), 400

    event = data.get("event")
    if event != "charge.success":
        logger.info("Ignored Paystack event: %s", event)
        return jsonify({"status": "ignored", "message": f"event {event} ignored"}), 200

    # Extract transaction reference and verify via Paystack API
    transaction = data.get("data", {}) or {}
    reference = transaction.get("reference")
    if not reference:
        logger.error("Paystack webhook missing reference")
        return jsonify({"status": "error", "message": "missing reference"}), 400

    verification = verify_paystack_transaction(reference)
    if not verification:
        logger.error("Paystack verification failed for %s", reference)
        return jsonify({"status": "error", "message": "verification failed"}), 200

    # Extract metadata: custom_fields -> telegram_id & service_type
    metadata = verification.get("metadata", {}) or {}
    custom_fields = metadata.get("custom_fields", [])
    user_id_val = None
    service_type = None
    for f in custom_fields:
        if f.get("variable_name") == "telegram_id":
            user_id_val = f.get("value")
        if f.get("variable_name") == "service_type":
            service_type = f.get("value")
    if not user_id_val:
        logger.error("No telegram_id in metadata for ref %s", reference)
        return jsonify({"status": "error", "message": "no telegram id"}), 200

    try:
        user_id = int(user_id_val)
    except Exception:
        logger.exception("Invalid telegram_id in metadata: %s", user_id_val)
        return jsonify({"status": "error", "message": "invalid telegram id"}), 200

    # Mark the order paid in DB (non-blocking)
    try:
        # DB access is now secured by DB_LOCK inside mark_order_paid_by_user
        mark_order_paid_by_user(user_id, reference)
    except Exception:
        logger.exception("Failed to mark order paid in DB")

    # Start background delivery to avoid blocking webhook response
    threading.Thread(target=start_delivery_bg, args=(user_id, service_type or "N/A", reference, telegram_app), daemon=True).start()

    return jsonify({"status": "ok", "message": "delivery initiated"}), 200

# -------------------------
# Build & run
# -------------------------
def build_telegram_app() -> Application:
    global telegram_app
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not configured")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            # CORRECTION PTBUserWarning : Ajout de per_message=True
            SERVICE: [CallbackQueryHandler(handler_service_choice, per_message=True)], 
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_country)],
            WHATSAPP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_whatsapp)],
        },
        fallbacks=[CommandHandler("cancel", handler_cancel), CallbackQueryHandler(handler_cancel, pattern="^cancel$")], # Ajout du pattern de cancel
        allow_reentry=True,
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Bot actif ✅")))
    application.add_handler(CommandHandler("sendtutorial", admin_send_tutorial_cmd))
    telegram_app = application
    return application

# Initialize DB and build app
init_db()
build_telegram_app()

# If run directly (local dev) set webhook and run Flask
if __name__ == "__main__":
    if TELEGRAM_TOKEN and EXTERNAL_URL:
        try:
            # CORRECTION RUNTIMEWARNING: Utiliser asyncio.run() pour await la coroutine
            asyncio.run(telegram_app.bot.set_webhook(url=f"{EXTERNAL_URL}/telegram-webhook/{TELEGRAM_TOKEN}"))
            logger.info("Telegram webhook set to %s/telegram-webhook/%s", EXTERNAL_URL, TELEGRAM_TOKEN)
        except Exception:
            logger.exception("Failed to set Telegram webhook")
    else:
        logger.warning("TELEGRAM_TOKEN or EXTERNAL_URL not set; you may use polling for local dev.")

    logger.info("Starting Flask app on port %s", PORT)
    # Lancement du serveur de développement Flask.
    # SUR RENDER, REMPLACEZ LA COMMANDE DE DÉMARRAGE PAR GUNICORN :
    # gunicorn -w 4 -b 0.0.0.0:$PORT bot:flask_app
    flask_app.run(host="0.0.0.0", port=PORT)
# bot.py
"""
Bot Telegram - Monétisation automatique
- No secrets in code: use env vars on Render
- SQLite persistence, requests.Session with retries, Paystack webhook signature check,
  background delivery (thread), webhook-based Telegram updates handling.

### MODIFICATIONS APPORTÉES :
### 1. Ajout de DB_LOCK pour sécuriser les accès SQLite en environnement multi-thread.
### 2. Remplacement de 'context.application.user_data[user_id]' par 'context.user_data' 
###    dans les gestionnaires de conversation (plus idiomatique pour ConversationHandler).
### 3. CORRECTION DU RUNTIMEWARNING : Utilisation de asyncio.run() pour await set_webhook.
### 4. CORRECTION DU PTBUSERWARNING : Ajout de per_message=True au CallbackQueryHandler.
"""

import os
import logging
import json
import sqlite3
import threading
import asyncio
import time
import hmac
import hashlib
from typing import Optional, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# -------------------------
# Configuration via env vars
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
EXTERNAL_URL = os.getenv("EXTERNAL_URL", "").strip()  # ex: https://monbot.onrender.com

# Paystack secrets (must be set in Render)
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "").strip()

# Optional static Paystack links (if you create Paystack pay pages)
PAYSTACK_TIKTOK = os.getenv("PAYSTACK_TIKTOK", "").strip()
PAYSTACK_FACEBOOK = os.getenv("PAYSTACK_FACEBOOK", "").strip()

# Tutorial / support (can be in env or hardcode here)
TUTORIAL_LINK = os.getenv("TUTORIAL_LINK", "").strip()  # ex: https://t.me/mon_canal_tutoriel
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "").strip() or "https://wa.me/0000000000"

# Prices (defaults)
PRICE_TIKTOK = os.getenv("PRICE_TIKTOK", "6000")
PRICE_FACEBOOK = os.getenv("PRICE_FACEBOOK", "8000")

# Admin / group (optional)
GROUP_ID = int(os.getenv("GROUP_ID", "0"))  # ex -100...
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # csv of ints

# DB
DB_PATH = os.getenv("DB_PATH", "orders.db")
PORT = int(os.getenv("PORT", 5000))

# -------------------------
# Logging
# -------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("monetisation-bot")

# -------------------------
# Flask app (exposed as flask_app)
# -------------------------
flask_app = Flask(__name__)

# -------------------------
# Telegram application (built later)
# -------------------------
telegram_app: Optional[Application] = None

# -------------------------
# HTTP session with retries
# -------------------------
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# -------------------------
# Conversation states
# -------------------------
SERVICE, COUNTRY, WHATSAPP = range(3)

# -------------------------
# Database helpers (SQLite)
# -------------------------
# Ajout d'un verrou pour sérialiser les accès à SQLite
DB_LOCK = threading.Lock()

def init_db(path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_orders (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                service TEXT,
                country TEXT,
                whatsapp TEXT,
                created_at INTEGER,
                paid INTEGER DEFAULT 0,
                pay_reference TEXT
            )
            """
        )
        conn.commit()
        conn.close()

def save_order(user_id: int, data: Dict, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            "REPLACE INTO pending_orders (user_id, username, service, country, whatsapp, created_at, paid) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, data.get("username"), data.get("service"), data.get("country"), data.get("whatsapp"), int(time.time()), 0)
        )
        conn.commit()
        conn.close()

def load_order(user_id: int, path: str = DB_PATH) -> Optional[Dict]:
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT username, service, country, whatsapp, paid, pay_reference FROM pending_orders WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
    if row:
        return {"username": row[0], "service": row[1], "country": row[2], "whatsapp": row[3], "paid": row[4], "pay_reference": row[5]}
    return None

def mark_order_paid_by_user(user_id: int, reference: str, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("UPDATE pending_orders SET paid = 1, pay_reference = ? WHERE user_id = ?", (reference, user_id))
        conn.commit()
        conn.close()

def delete_order(user_id: int, path: str = DB_PATH):
    with DB_LOCK:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("DELETE FROM pending_orders WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

# -------------------------
# Helpers
# -------------------------
def get_admin_ids():
    if not ADMIN_IDS:
        return []
    return [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

# -------------------------
# UI texts (FR)
# -------------------------
TEXT = {
    "start": "👋 Bienvenue ! Choisissez la plateforme à monétiser :",
    "ask_country": "🌍 Dans quel pays êtes-vous ?",
    "ask_whatsapp": "📞 Envoie ton numéro WhatsApp (format international, ex: +22570xxxxxxx) :",
    "price_tiktok": f"💰 Prix TikTok : *{PRICE_TIKTOK} F CFA*.",
    "price_facebook": f"💰 Prix Facebook : *{PRICE_FACEBOOK} F CFA*.",
    "after_payment": "🔔 Après paiement, Paystack redirigera automatiquement vers la vidéo tutoriel (et le bot confirmera).",
    "admin_note": "🔰 Vous êtes admin — accès direct au tutoriel.",
    "pay_error": "❌ Impossible de générer le lien de paiement. Contactez le support.",
    "cancel": "❌ Commande annulée. Tape /start pour recommencer.",
    "thanks_auto": "✅ Paiement confirmé. Voici le tutoriel :"
}

# -------------------------
# Keyboards
# -------------------------
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎬 Monétiser TikTok", callback_data="tiktok")],
        [InlineKeyboardButton("📘 Monétiser Facebook", callback_data="facebook")],
        [InlineKeyboardButton("ℹ️ Comment ça marche", url=TUTORIAL_LINK or "https://t.me/")],
        [InlineKeyboardButton("📞 Contacter Support", url=SUPPORT_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

def pay_button_by_service(pay_url: str):
    kb = [[InlineKeyboardButton("💳 Payer maintenant", url=pay_url)], [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Paystack helpers
# -------------------------
def initialize_paystack_transaction(user_id: int, service: str, email: str, amount: str, whatsapp: str) -> Optional[str]:
    """
    Initialize Paystack transaction via API, return authorization_url or None.
    metadata includes telegram_id and service_type to match after webhook.
    """
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY not set")
        return None
    try:
        # NOTE: If prices were converted to int early, this try/except would be unnecessary
        amount_kobo = int(amount) * 100
    except Exception as e:
        logger.exception("Invalid amount: %s", e)
        return None

    url = "https://api.paystack.co/transaction/initialize"
    metadata = {
        "custom_fields": [
            {"display_name": "Telegram ID", "variable_name": "telegram_id", "value": str(user_id)},
            {"display_name": "Service", "variable_name": "service_type", "value": service},
            {"display_name": "WhatsApp", "variable_name": "whatsapp_number", "value": whatsapp},
        ]
    }
    payload = {
        "email": email,
        "amount": amount_kobo,
        "metadata": metadata,
        "callback_url": f"{EXTERNAL_URL}/thank-you" if EXTERNAL_URL else None
    }
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    try:
        resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status"):
            return data["data"]["authorization_url"]
        logger.error("Paystack init failed: %s", data)
        return None
    except requests.RequestException as e:
        logger.exception("Paystack initialize error: %s", e)
        return None

def verify_paystack_transaction(reference: str) -> Optional[Dict]:
    """Verify transaction via Paystack API and return verification data if success."""
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY not set (verify)")
        return None
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") and data.get("data", {}).get("status") == "success":
            return data["data"]
        logger.warning("Paystack verify not successful: %s", data)
        return None
    except requests.RequestException as e:
        logger.exception("Paystack verify error: %s", e)
        return None

# -------------------------
# Delivery (async)
# -------------------------
async def deliver_tutorial(user_id: int, service: str, reference: str, app: Application):
    """Send tutorial link to user and notify admin group. Add small sleeps to avoid rate limits."""
    try:
        text = f"{TEXT['thanks_auto']}\n{TUTORIAL_LINK}" if TUTORIAL_LINK else TEXT['thanks_auto']
        await app.bot.send_message(chat_id=user_id, text=text)
        await asyncio.sleep(0.15)  # tiny pause
    except Exception:
        logger.exception("Failed to send tutorial to %s", user_id)

    # Notify admin group
    order = load_order(user_id) or {}
    admin_msg = (
        f"🎉 PAIEMENT CONFIRMÉ\n"
        f"• Utilisateur: {user_id}\n"
        f"• Service: {service}\n"
        f"• Réf: {reference}\n"
        f"• Pays: {order.get('country','N/A')}\n"
        f"• WhatsApp: {order.get('whatsapp','N/A')}"
    )
    try:
        if GROUP_ID:
            await app.bot.send_message(chat_id=GROUP_ID, text=admin_msg)
    except Exception:
        logger.exception("Failed to notify admin group")

    # cleanup
    try:
        delete_order(user_id)
    except Exception:
        logger.exception("Failed to delete order after delivery")

# helper to run async deliver in background thread
def start_delivery_bg(user_id: int, service: str, reference: str, app: Application):
    try:
        # Use a new event loop for the thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(deliver_tutorial(user_id, service, reference, app))
        loop.close()
    except Exception:
        logger.exception("Error running deliver_tutorial in bg")

# -------------------------
# Telegram handlers
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT["start"], reply_markup=main_menu_keyboard())
    return SERVICE

async def handler_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    
    if data in ("tiktok", "facebook"):
        context.user_data["service"] = data
        context.user_data["username"] = q.from_user.username or ""
        # Modification du message précédent pour une UI plus propre
        await q.message.edit_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY

    await q.message.reply_text("Option inconnue.")
    return ConversationHandler.END

async def handler_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["country"] = update.message.text.strip()
    await update.message.reply_text(TEXT["ask_whatsapp"])
    return WHATSAPP

async def handler_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    context.user_data["whatsapp"] = update.message.text.strip()
    user_data = context.user_data # Récupération des données pour la persistance

    # persist order
    save_order(user_id, user_data)

    # Admin direct access
    if is_admin(user_id):
        await update.message.reply_text(TEXT["admin_note"])
        if TUTORIAL_LINK:
            await update.message.reply_text(f"Voici le tutoriel :\n{TUTORIAL_LINK}")
        delete_order(user_id)
        # Nettoyage des données de conversation
        context.user_data.clear() # Ajout d'un nettoyage explicite
        return ConversationHandler.END

    # Prepare payment link (static or dynamic)
    service = user_data.get("service")
    if service == "tiktok":
        amount = PRICE_TIKTOK
        if PAYSTACK_TIKTOK:
            pay_url = PAYSTACK_TIKTOK
        else:
            pay_url = initialize_paystack_transaction(user_id, "tiktok", f"telegram{user_id}@noemail.local", PRICE_TIKTOK, user_data.get("whatsapp",""))
    else:
        amount = PRICE_FACEBOOK
        if PAYSTACK_FACEBOOK:
            pay_url = PAYSTACK_FACEBOOK
        else:
            pay_url = initialize_paystack_transaction(user_id, "facebook", f"telegram{user_id}@noemail.local", PRICE_FACEBOOK, user_data.get("whatsapp",""))

    if not pay_url:
        await update.message.reply_text(TEXT["pay_error"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support", url=SUPPORT_LINK)]]))
        delete_order(user_id)
        context.user_data.clear() # Nettoyage en cas d'erreur
        return ConversationHandler.END

    # send recap + pay link
    price_text = TEXT["price_tiktok"] if service == "tiktok" else TEXT["price_facebook"]
    await update.message.reply_text(f"{price_text}\n\n{TEXT['after_payment']}", reply_markup=pay_button_by_service(pay_url))
    
    return ConversationHandler.END

async def handler_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Répondre au callback_query (si l'annulation vient d'un bouton inline)
    if q:
        await q.answer()
        await q.message.edit_text(TEXT["cancel"], reply_markup=None)
    else:
        # Si l'annulation vient d'une commande /cancel
        await update.message.reply_text(TEXT["cancel"])
    
    user_id = update.effective_user.id
    delete_order(user_id)
    context.user_data.clear() # Nettoyage des données de conversation
    return ConversationHandler.END

async def admin_send_tutorial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Commande réservée aux admins.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /sendtutorial <telegram_user_id>")
        return
    try:
        tid = int(args[0])
        if TUTORIAL_LINK:
            await context.bot.send_message(chat_id=tid, text=f"Voici le tutoriel :\n{TUTORIAL_LINK}")
            await update.message.reply_text("Tutoriel envoyé.")
        else:
            await update.message.reply_text("TUTORIAL_LINK non configuré.")
    except Exception:
        logger.exception("admin_send_tutorial error")
        await update.message.reply_text("Erreur lors de l'envoi.")

# -------------------------
# Flask endpoints (webhooks)
# -------------------------
@flask_app.route("/telegram-webhook/" + (TELEGRAM_TOKEN or "token_missing"), methods=["POST"])
def telegram_webhook():
    """Receive Telegram updates (set webhook to EXTERNAL_URL/telegram-webhook/<TOKEN>)"""
    global telegram_app
    if not telegram_app:
        return "app not ready", 503
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    # Process update in background to avoid blocking webhook
    threading.Thread(target=lambda: asyncio.run(telegram_app.process_update(update)), daemon=True).start()
    return "ok", 200

@flask_app.route("/paystack-webhook", methods=["POST"])
def paystack_webhook():
    """Handle Paystack webhook: verify signature and process successful charges"""
    payload = request.data or b""
    
    try:
        data = request.get_json(force=True)
    except Exception:
        logger.exception("Invalid JSON in Paystack webhook")
        return jsonify({"status": "error", "message": "invalid json"}), 400

    # Verify signature header if available (use PAYSTACK_WEBHOOK_SECRET)
    signature = request.headers.get("x-paystack-signature", "")
    if PAYSTACK_WEBHOOK_SECRET:
        computed = hmac.new(PAYSTACK_WEBHOOK_SECRET.encode(), payload, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(computed, signature):
            logger.warning("Invalid Paystack webhook signature")
            return jsonify({"status": "error", "message": "invalid signature"}), 400

    event = data.get("event")
    if event != "charge.success":
        logger.info("Ignored Paystack event: %s", event)
        return jsonify({"status": "ignored", "message": f"event {event} ignored"}), 200

    # Extract transaction reference and verify via Paystack API
    transaction = data.get("data", {}) or {}
    reference = transaction.get("reference")
    if not reference:
        logger.error("Paystack webhook missing reference")
        return jsonify({"status": "error", "message": "missing reference"}), 400

    verification = verify_paystack_transaction(reference)
    if not verification:
        logger.error("Paystack verification failed for %s", reference)
        return jsonify({"status": "error", "message": "verification failed"}), 200

    # Extract metadata: custom_fields -> telegram_id & service_type
    metadata = verification.get("metadata", {}) or {}
    custom_fields = metadata.get("custom_fields", [])
    user_id_val = None
    service_type = None
    for f in custom_fields:
        if f.get("variable_name") == "telegram_id":
            user_id_val = f.get("value")
        if f.get("variable_name") == "service_type":
            service_type = f.get("value")
    if not user_id_val:
        logger.error("No telegram_id in metadata for ref %s", reference)
        return jsonify({"status": "error", "message": "no telegram id"}), 200

    try:
        user_id = int(user_id_val)
    except Exception:
        logger.exception("Invalid telegram_id in metadata: %s", user_id_val)
        return jsonify({"status": "error", "message": "invalid telegram id"}), 200

    # Mark the order paid in DB (non-blocking)
    try:
        # DB access is now secured by DB_LOCK inside mark_order_paid_by_user
        mark_order_paid_by_user(user_id, reference)
    except Exception:
        logger.exception("Failed to mark order paid in DB")

    # Start background delivery to avoid blocking webhook response
    threading.Thread(target=start_delivery_bg, args=(user_id, service_type or "N/A", reference, telegram_app), daemon=True).start()

    return jsonify({"status": "ok", "message": "delivery initiated"}), 200

# -------------------------
# Build & run
# -------------------------
def build_telegram_app() -> Application:
    global telegram_app
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not configured")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            # CORRECTION PTBUserWarning : Ajout de per_message=True
            SERVICE: [CallbackQueryHandler(handler_service_choice, per_message=True)], 
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_country)],
            WHATSAPP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_whatsapp)],
        },
        fallbacks=[CommandHandler("cancel", handler_cancel), CallbackQueryHandler(handler_cancel, pattern="^cancel$")], # Ajout du pattern de cancel
        allow_reentry=True,
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Bot actif ✅")))
    application.add_handler(CommandHandler("sendtutorial", admin_send_tutorial_cmd))
    telegram_app = application
    return application

# Initialize DB and build app
init_db()
build_telegram_app()

# If run directly (local dev) set webhook and run Flask
if __name__ == "__main__":
    if TELEGRAM_TOKEN and EXTERNAL_URL:
        try:
            # CORRECTION RUNTIMEWARNING: Utiliser asyncio.run() pour await la coroutine
            asyncio.run(telegram_app.bot.set_webhook(url=f"{EXTERNAL_URL}/telegram-webhook/{TELEGRAM_TOKEN}"))
            logger.info("Telegram webhook set to %s/telegram-webhook/%s", EXTERNAL_URL, TELEGRAM_TOKEN)
        except Exception:
            logger.exception("Failed to set Telegram webhook")
    else:
        logger.warning("TELEGRAM_TOKEN or EXTERNAL_URL not set; you may use polling for local dev.")

    logger.info("Starting Flask app on port %s", PORT)
    # Lancement du serveur de développement Flask.
    # SUR RENDER, REMPLACEZ LA COMMANDE DE DÉMARRAGE PAR GUNICORN :
    # gunicorn -w 4 -b 0.0.0.0:$PORT bot:flask_app
    flask_app.run(host="0.0.0.0", port=PORT)
