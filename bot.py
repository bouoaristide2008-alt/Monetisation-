# bot.py
"""
Bot Telegram - Monétisation automatique (version finale)
- Aucune clé en dur : tout est lu depuis les Environment Variables sur Render.
- SQLite sécurisé par DB_LOCK pour accès multi-thread.
- Paystack webhook vérifié (signature HMAC + verification API).
- Livraison automatique en tâche de fond.
- Bouton "⬅️ Retour" présent à chaque étape.
- Compatible python-telegram-bot v20+ / Python 3.10+.
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

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
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
# Configuration via env vars (Render)
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
EXTERNAL_URL = os.getenv("EXTERNAL_URL", "").strip()  # ex: https://monbot.onrender.com

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "").strip()

TIKTOK_PAYSTACK_LINK = os.getenv("TIKTOK_PAYSTACK_LINK", "").strip()
FACEBOOK_PAYSTACK_LINK = os.getenv("FACEBOOK_PAYSTACK_LINK", "").strip()

HOW_IT_WORKS_CHANNEL = os.getenv("HOW_IT_WORKS_CHANNEL", "").strip()  # canal "comment ça marche"
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "").strip() or "https://wa.me/0000000000"

PRICE_TIKTOK = os.getenv("PRICE_TIKTOK", "6000")
PRICE_FACEBOOK = os.getenv("PRICE_FACEBOOK", "8000")

ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # CSV
GROUP_ID = int(os.getenv("GROUP_ID", "0")) if os.getenv("GROUP_ID") else 0

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
# Database helpers (SQLite) with lock
# -------------------------
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
# Keyboards (with Retour buttons)
# -------------------------
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎬 Monétiser TikTok", callback_data="tiktok")],
        [InlineKeyboardButton("📘 Monétiser Facebook", callback_data="facebook")],
        [InlineKeyboardButton("ℹ️ Comment ça marche", url=HOW_IT_WORKS_CHANNEL or "https://t.me/")],
        [InlineKeyboardButton("📞 Contacter Support", url=SUPPORT_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button_keyboard(target: str):
    # `target` is the callback_data to go back to
    kb = [[InlineKeyboardButton("⬅️ Retour", callback_data=target)], [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]]
    return InlineKeyboardMarkup(kb)

def pay_button_by_service(pay_url: str):
    kb = [[InlineKeyboardButton("💳 Payer maintenant", url=pay_url)], [InlineKeyboardButton("⬅️ Retour", callback_data="back_to_menu")]]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Paystack helpers
# -------------------------
def initialize_paystack_transaction(user_id: int, service: str, email: str, amount: str, whatsapp: str) -> Optional[str]:
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY not set")
        return None
    try:
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
        # Choose tutorial: here we use the HOW_IT_WORKS_CHANNEL as delivery target (you can change)
        text = f"{TEXT['thanks_auto']}\n{HOW_IT_WORKS_CHANNEL or 'Le tutoriel n est pas configuré.'}"
        await app.bot.send_message(chat_id=user_id, text=text)
        await asyncio.sleep(0.15)
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

def start_delivery_bg(user_id: int, service: str, reference: str, app: Application):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(deliver_tutorial(user_id, service, reference, app))
        loop.close()
    except Exception:
        logger.exception("Error running deliver_tutorial in bg")

# -------------------------
# Telegram handlers (Conversation)
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # reset any leftover state
    context.user_data.clear()
    await update.message.reply_text(TEXT["start"], reply_markup=main_menu_keyboard())

    return SERVICE

# handler for callback choices and back navigation
async def handler_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # back navigation targets
    if data == "back_to_menu":
        context.user_data.clear()
        await q.message.edit_text(TEXT["start"], reply_markup=main_menu_keyboard())
        return SERVICE

    if data == "cancel":
        context.user_data.clear()
        await q.message.edit_text(TEXT["cancel"])
        return ConversationHandler.END

    if data == "tiktok" or data == "facebook":
        # store service and ask country; show back button to main menu
        context.user_data["service"] = data
        context.user_data["username"] = q.from_user.username or ""
        await q.message.edit_text(TEXT["ask_country"], reply_markup=back_button_keyboard("back_to_menu"))
        return COUNTRY

    # fallback: show menu
    await q.message.edit_text("Option inconnue.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def handler_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Allow user to type '⬅️ Retour' by pressing the inline back button; text input here is country
    text = update.message.text.strip()
    context.user_data["country"] = text
    # ask whatsapp with a back button to service choice
    await update.message.reply_text(TEXT["ask_whatsapp"], reply_markup=back_button_keyboard("back_to_menu"))
    return WHATSAPP

async def handler_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    # store whatsapp
    context.user_data["whatsapp"] = text
    user_data = context.user_data

    # persist order to DB
    save_order(user_id, user_data)

    # if admin -> immediate access
    if is_admin(user_id):
        await update.message.reply_text(TEXT["admin_note"])
        if HOW_IT_WORKS_CHANNEL:
            await update.message.reply_text(f"Voici le tutoriel :\n{HOW_IT_WORKS_CHANNEL}")
        delete_order(user_id)
        context.user_data.clear()
        return ConversationHandler.END

    # Prepare payment link
    service = user_data.get("service")
    if service == "tiktok":
        amount = PRICE_TIKTOK
        pay_url = TIKTOK_PAYSTACK_LINK or initialize_paystack_transaction(user_id, "tiktok", f"telegram{user_id}@noemail.local", PRICE_TIKTOK, user_data.get("whatsapp",""))
    else:
        amount = PRICE_FACEBOOK
        pay_url = FACEBOOK_PAYSTACK_LINK or initialize_paystack_transaction(user_id, "facebook", f"telegram{user_id}@noemail.local", PRICE_FACEBOOK, user_data.get("whatsapp",""))

    if not pay_url:
        await update.message.reply_text(TEXT["pay_error"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support", url=SUPPORT_LINK)]]))
        delete_order(user_id)
        context.user_data.clear()
        return ConversationHandler.END

    price_text = TEXT["price_tiktok"] if service == "tiktok" else TEXT["price_facebook"]
    await update.message.reply_text(
        f"{price_text}\n\n{TEXT['after_payment']}",
        reply_markup=pay_button_by_service(pay_url)
    )
    # keep data until paid or canceled
    return ConversationHandler.END

async def handler_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # supports /cancel command
    context.user_data.clear()
    user_id = update.effective_user.id
    delete_order(user_id)
    await update.message.reply_text(TEXT["cancel"])
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
        if HOW_IT_WORKS_CHANNEL:
            await context.bot.send_message(chat_id=tid, text=f"Voici le tutoriel :\n{HOW_IT_WORKS_CHANNEL}")
            await update.message.reply_text("Tutoriel envoyé.")
        else:
            await update.message.reply_text("HOW_IT_WORKS_CHANNEL non configuré.")
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
        if not signature:
            logger.warning("Paystack webhook missing signature header")
            return jsonify({"status": "error", "message": "missing signature"}), 400
        computed = hmac.new(PAYSTACK_WEBHOOK_SECRET.encode(), payload, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(computed, signature):
            logger.warning("Invalid Paystack webhook signature")
            return jsonify({"status": "error", "message": "invalid signature"}), 400

    event = data.get("event")
    if event != "charge.success":
        logger.info("Ignored Paystack event: %s", event)
        return jsonify({"status": "ignored", "message": f"event {event} ignored"}), 200

    transaction = data.get("data", {}) or {}
    reference = transaction.get("reference")
    if not reference:
        logger.error("Paystack webhook missing reference")
        return jsonify({"status": "error", "message": "missing reference"}), 400

    verification = verify_paystack_transaction(reference)
    if not verification:
        logger.error("Paystack verification failed for %s", reference)
        return jsonify({"status": "error", "message": "verification failed"}), 200

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

    # Mark paid
    try:
        mark_order_paid_by_user(user_id, reference)
    except Exception:
        logger.exception("Failed to mark order paid in DB")

    # Start background delivery
    threading.Thread(target=start_delivery_bg, args=(user_id, service_type or "N/A", reference, telegram_app), daemon=True).start()

    return jsonify({"status": "ok", "message": "delivery initiated"}), 200

# -------------------------
# Build & run the Telegram Application
# -------------------------
def build_telegram_app() -> Application:
    global telegram_app
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not configured")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SERVICE: [CallbackQueryHandler(handler_service_choice, per_message=True)],
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_country)],
            WHATSAPP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler_whatsapp)],
        },
        fallbacks=[CommandHandler("cancel", handler_cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Bot actif ✅")))
    application.add_handler(CommandHandler("sendtutorial", admin_send_tutorial_cmd))
    telegram_app = application
    return application

# Initialize DB and app
init_db()
build_telegram_app()

# -------------------------
# Start (safe webhook set + Flask)
# -------------------------
if __name__ == "__main__":
    # Validate required env vars early
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not PAYSTACK_SECRET_KEY:
        missing.append("PAYSTACK_SECRET_KEY")
    if missing:
        logger.error("Missing required env vars: %s. Exiting.", ", ".join(missing))
        raise SystemExit(1)

    # Set webhook safely if EXTERNAL_URL given
    if TELEGRAM_TOKEN and EXTERNAL_URL:
        try:
            # set_webhook can be coroutine depending on PTB version; use asyncio.run to be safe
            asyncio.run(telegram_app.bot.set_webhook(url=f"{EXTERNAL_URL}/telegram-webhook/{TELEGRAM_TOKEN}"))
            logger.info("Telegram webhook set to %s/telegram-webhook/%s", EXTERNAL_URL, TELEGRAM_TOKEN)
        except Exception:
            logger.exception("Failed to set Telegram webhook")

    logger.info("Starting Flask app on port %s", PORT)
    flask_app.run(host="0.0.0.0", port=PORT)
