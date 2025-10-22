# bot.py
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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
EXTERNAL_URL = os.getenv("EXTERNAL_URL", "").strip()
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "").strip()
TIKTOK_PAYSTACK_LINK = os.getenv("TIKTOK_PAYSTACK_LINK", "").strip()
FACEBOOK_PAYSTACK_LINK = os.getenv("FACEBOOK_PAYSTACK_LINK", "").strip()
HOW_IT_WORKS_CHANNEL = os.getenv("HOW_IT_WORKS_CHANNEL", "").strip()
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "").strip() or "https://wa.me/0000000000"
PRICE_TIKTOK = os.getenv("PRICE_TIKTOK", "6000")
PRICE_FACEBOOK = os.getenv("PRICE_FACEBOOK", "8000")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
GROUP_ID = int(os.getenv("GROUP_ID", "0")) if os.getenv("GROUP_ID") else 0
DB_PATH = os.getenv("DB_PATH", "orders.db")

# -------------------------
# Logging
# -------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("monetisation-bot")

# -------------------------
# Flask app
# -------------------------
flask_app = Flask(__name__)

# -------------------------
# Telegram application
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
# Database helpers
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

# (Fonctions save_order, load_order, mark_order_paid_by_user, delete_order identiques...)

# -------------------------
# Helpers
# -------------------------
def get_admin_ids():
    return [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()] if ADMIN_IDS else []

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

# -------------------------
# UI texts
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

# (Fonctions main_menu_keyboard, back_button_keyboard, pay_button_by_service identiques...)

# -------------------------
# Telegram handlers
# -------------------------
# (Toutes fonctions handler identiques...)

# -------------------------
# Flask endpoints
# -------------------------
@flask_app.route("/telegram-webhook/" + (TELEGRAM_TOKEN or "token_missing"), methods=["POST"])
def telegram_webhook():
    global telegram_app
    if not telegram_app:
        return "app not ready", 503
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    threading.Thread(target=lambda: asyncio.run(telegram_app.process_update(update)), daemon=True).start()
    return "ok", 200

@flask_app.route("/paystack-webhook", methods=["POST"])
def paystack_webhook():
    # (identique à ton code existant)
    ...

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

# -------------------------
# Initialisation
# -------------------------
init_db()
build_telegram_app()

# -------------------------
# Lancement du webhook Telegram via async (une seule fois)
# -------------------------
async def set_telegram_webhook():
    if TELEGRAM_TOKEN and EXTERNAL_URL:
        try:
            await telegram_app.bot.set_webhook(url=f"{EXTERNAL_URL}/telegram-webhook/{TELEGRAM_TOKEN}")
            logger.info("Telegram webhook set to %s/telegram-webhook/%s", EXTERNAL_URL, TELEGRAM_TOKEN)
        except Exception:
            logger.exception("Failed to set Telegram webhook")

# Exécution du webhook lors du déploiement Render
asyncio.run(set_telegram_webhook())

# ✅ NOTE: Ne pas mettre flask_app.run() ! Gunicorn s’en charge.
