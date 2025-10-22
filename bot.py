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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error
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
# Database helpers (COMPLETÉ)
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

def save_order(user_id: int, username: str, service: str, country: str, whatsapp: str, pay_reference: str):
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO pending_orders
            (user_id, username, service, country, whatsapp, created_at, pay_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, service, country, whatsapp, int(time.time()), pay_reference),
        )
        conn.commit()
        conn.close()

def load_order(pay_reference: str) -> Optional[Dict]:
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM pending_orders WHERE pay_reference = ? AND paid = 0", (pay_reference,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

def load_order_by_user_id(user_id: int) -> Optional[Dict]:
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM pending_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

def mark_order_paid_by_ref(pay_reference: str):
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "UPDATE pending_orders SET paid = 1 WHERE pay_reference = ?",
            (pay_reference,),
        )
        conn.commit()
        conn.close()

# -------------------------
# Helpers
# -------------------------
def get_admin_ids():
    return [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()] if ADMIN_IDS else []

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

# -------------------------
# UI texts (Votre TEXT existant)
# -------------------------
TEXT = {
    # ... (vos textes existants) ...
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

def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎥 TikTok", callback_data="service_tiktok")],
            [InlineKeyboardButton("📘 Facebook", callback_data="service_facebook")],
            [InlineKeyboardButton("ℹ️ Comment ça marche ?", url=HOW_IT_WORKS_CHANNEL or SUPPORT_LINK)],
        ]
    )

def back_button_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour", callback_data="back_to_service")]])

def pay_button_by_service(service: str, reference: str):
    link = TIKTOK_PAYSTACK_LINK if service == 'tiktok' else FACEBOOK_PAYSTACK_LINK
    if not link:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Lien indisponible", callback_data="none")],
        ])
        
    # NOTE: Paystack's standard payment link/widget requires parameters
    # This requires using the Paystack API to generate a link with an amount and reference,
    # or using a static link if it supports passing parameters.
    # For simplicity here, we assume the link is ready, but in a real scenario, 
    # generate_paystack_link(service, reference) would be needed.

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Payer Maintenant", url=f"{link}?reference={reference}")]
    ])
    
def generate_paystack_link(service: str, email: str, amount: str, reference: str) -> Optional[str]:
    """Génère un lien de paiement Paystack via l'API (non implémenté pour simplicité)."""
    # NOTE: Cette fonction devrait appeler l'API Paystack pour créer une transaction.
    # Pour l'instant, on se contente des liens statiques si les variables ENV les contiennent
    # ou on retourne None si la SECRET_KEY n'est pas là.
    
    if not PAYSTACK_SECRET_KEY:
        logger.error("PAYSTACK_SECRET_KEY manquant pour la génération de lien.")
        return None

    # Ici, vous feriez une requête POST à https://api.paystack.co/transaction/initialize
    # avec l'email, le montant (en kobo/centimes), et la référence.
    # Pour garder le code exécutable, on utilise le lien statique avec la référence.
    
    base_link = TIKTOK_PAYSTACK_LINK if service == 'tiktok' else FACEBOOK_PAYSTACK_LINK
    
    if base_link:
        # On assume que la variable ENV contient l'URL de base du formulaire/widget
        return f"{base_link}?reference={reference}"
        
    return None

# -------------------------
# Tutorial Delivery Function
# -------------------------

async def send_tutorial_to_user(user_id: int, service: str, context: ContextTypes.DEFAULT_TYPE):
    """Sends the tutorial link to the user after payment."""
    tutorial_link = TIKTOK_PAYSTACK_LINK if service == 'tiktok' else FACEBOOK_PAYSTACK_LINK
    
    if not tutorial_link:
        text = "❌ Erreur: Lien tutoriel manquant. Contactez le support."
    else:
        text = (
            f"{TEXT['thanks_auto']}\n\n"
            f"[Cliquez ici pour accéder au tutoriel {service.upper()}]({tutorial_link})\n"
            f"Besoin d'aide ? {SUPPORT_LINK}"
        )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
        logger.info(f"Tutorial sent to user {user_id} for {service}")
    except error.Forbidden:
        logger.warning(f"Failed to send tutorial to user {user_id}: Bot blocked by user.")
    except Exception:
        logger.exception(f"Failed to send tutorial to user {user_id}")
        
    # Send a notification to the admin group
    if GROUP_ID:
        try:
            order_data = load_order_by_user_id(user_id) # Récupère les dernières données
            username = f"@{order_data.get('username')}" if order_data and order_data.get('username') else str(user_id)
            whatsapp = order_data.get('whatsapp', 'N/A') if order_data else "N/A"
            country = order_data.get('country', 'N/A') if order_data else "N/A"
            reference = order_data.get('pay_reference', 'N/A') if order_data else "N/A"
            
            admin_msg = (
                f"🎉 **Nouvelle Vente Confirmée !**\n"
                f"👤 Utilisateur: {username} (ID: `{user_id}`)\n"
                f"🌍 Pays: {country}\n"
                f"📞 WhatsApp: {whatsapp}\n"
                f"📺 Service: **{service.upper()}**\n"
                f"💳 Référence: `{reference}`"
            )
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=admin_msg,
                parse_mode='Markdown'
            )
        except Exception:
            logger.exception("Failed to send admin notification.")


# -------------------------
# Telegram handlers (CORRIGÉ: Bloc placé AVANT build_telegram_app)
# -------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    if is_admin(user.id):
        await update.message.reply_text(
            f"{TEXT['start']}\n\n{TEXT['admin_note']}",
            reply_markup=main_menu_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            TEXT['start'],
            reply_markup=main_menu_keyboard()
        )
    
    return SERVICE

async def handler_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    if data[0] == "back":
        await query.edit_message_text(TEXT['start'], reply_markup=main_menu_keyboard())
        return SERVICE

    service = data[1]
    context.user_data['service'] = service
    
    price_text = TEXT['price_tiktok'] if service == 'tiktok' else TEXT['price_facebook']

    await query.edit_message_text(
        f"{price_text}\n\n{TEXT['ask_country']}",
        reply_markup=back_button_keyboard(),
        parse_mode='Markdown'
    )
    return COUNTRY

async def handler_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    country = update.message.text.strip()
    if not country:
        await update.message.reply_text("Veuillez entrer un pays valide.")
        return COUNTRY
        
    context.user_data['country'] = country
    
    await update.message.reply_text(
        TEXT['ask_whatsapp']
    )
    return WHATSAPP

async def handler_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    whatsapp = update.message.text.strip()
    user = update.effective_user
    
    if not whatsapp or len(whatsapp) < 8:
        await update.message.reply_text("Veuillez entrer un numéro WhatsApp valide (minimum 8 chiffres).")
        return WHATSAPP
    
    service = context.user_data.get('service')
    country = context.user_data.get('country')
    
    if not service or not country:
        await update.message.reply_text("❌ Erreur de session. Veuillez recommencer avec /start.")
        return ConversationHandler.END

    # 1. ADMIN BYPASS (pour admin, on donne le tutoriel directement)
    if is_admin(user.id):
        await send_tutorial_to_user(user.id, service, context)
        await update.message.reply_text(f"✅ Accès accordé (Admin). Vous pouvez taper /start pour une nouvelle commande.", parse_mode='Markdown')
        return ConversationHandler.END

    # 2. GÉNÉRATION DU LIEN DE PAIEMENT
    reference = f"{user.id}-{int(time.time())}"
    amount = PRICE_TIKTOK if service == 'tiktok' else PRICE_FACEBOOK
    
    # On utilise un email bidon pour Paystack si non disponible
    email = f"user_{user.id}@telegram.com" 

    pay_link = generate_paystack_link(service, email, amount, reference)
    
    if not pay_link:
        await update.message.reply_text(TEXT['pay_error'])
        return ConversationHandler.END
        
    # 3. Sauvegarde de la commande
    save_order(
        user_id=user.id,
        username=user.username or "",
        service=service,
        country=country,
        whatsapp=whatsapp,
        pay_reference=reference
    )
    
    # 4. Envoi du message de paiement
    price_text = TEXT['price_tiktok'] if service == 'tiktok' else TEXT['price_facebook']
    
    await update.message.reply_text(
        f"👍 Super, *{user.first_name}*.\n\n"
        f"**Récapitulatif de votre commande :**\n"
        f"  - Plateforme : {service.upper()}\n"
        f"  - Prix : {price_text.replace('💰 Prix TikTok : ', '').replace('💰 Prix Facebook : ', '')}\n"
        f"  - Référence : `{reference}`\n\n"
        f"Procédez au paiement en cliquant sur le bouton ci-dessous. {TEXT['after_payment']}",
        reply_markup=pay_button_by_service(service, reference),
        parse_mode='Markdown'
    )

    context.user_data.clear()
    return ConversationHandler.END

async def handler_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(TEXT['cancel'])
    context.user_data.clear()
    return ConversationHandler.END
    
async def admin_send_tutorial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande admin pour envoyer manuellement le tutoriel. Usage: /sendtutorial <user_id> <service>"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    try:
        parts = context.args
        if len(parts) != 2:
            await update.message.reply_text("Usage: `/sendtutorial <user_id> <tiktok|facebook>`", parse_mode='Markdown')
            return

        target_user_id = int(parts[0])
        service = parts[1].lower()
        if service not in ('tiktok', 'facebook'):
            await update.message.reply_text("Service doit être 'tiktok' ou 'facebook'.")
            return

        await send_tutorial_to_user(target_user_id, service, context)
        await update.message.reply_text(f"✅ Tutoriel **{service.upper()}** envoyé à l'utilisateur `{target_user_id}`.", parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("L'ID utilisateur doit être un nombre.")
    except Exception:
        logger.exception("Error in admin_send_tutorial_cmd")
        await update.message.reply_text("❌ Une erreur est survenue.")

# -------------------------
# Flask endpoints (PAYSTACK WEBHOOK COMPLÉTÉ)
# -------------------------
@flask_app.route("/telegram-webhook/" + (TELEGRAM_TOKEN or "token_missing"), methods=["POST"])
def telegram_webhook():
    global telegram_app
    if not telegram_app:
        return "app not ready", 503
    data = request.get_json(force=True)
    
    def run_process_update():
        update = Update.de_json(data, telegram_app.bot)
        asyncio.run(telegram_app.process_update(update))

    threading.Thread(target=run_process_update, daemon=True).start()
    return "ok", 200

@flask_app.route("/paystack-webhook", methods=["POST"])
def paystack_webhook():
    """Gère le webhook de Paystack après la complétion d'une transaction."""
    # 1. Vérification de la signature
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        logger.warning("Webhook Paystack: Entête de signature manquant.")
        return jsonify({"message": "Forbidden"}), 403

    raw_body = request.get_data()
    
    if not PAYSTACK_WEBHOOK_SECRET:
         logger.error("Webhook Paystack: PAYSTACK_WEBHOOK_SECRET n'est pas configuré.")
         return jsonify({"message": "Server Error"}), 500
         
    hash_obj = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode("utf-8"), 
        msg=raw_body, 
        digestmod=hashlib.sha512
    )
    generated_signature = hash_obj.hexdigest()

    if generated_signature != signature:
        logger.warning("Webhook Paystack: Signature invalide.")
        return jsonify({"message": "Forbidden"}), 403

    # 2. Traitement de l'événement
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.error("Webhook Paystack: Corps JSON invalide.")
        return jsonify({"message": "Bad Request"}), 400

    event_type = event.get("event")
    data = event.get("data", {})
    
    if event_type == "charge.success":
        reference = data.get("reference")
        status = data.get("status")

        if status == "success" and reference:
            # Charge la commande en attente (paid=0)
            order = load_order(reference)
            
            if order:
                user_id = order["user_id"]
                service = order["service"]
                
                if order["paid"] == 1:
                    logger.info(f"Webhook Paystack: Référence {reference} déjà traitée (utilisateur: {user_id}).")
                    return jsonify({"message": "Already processed"}), 200
                
                logger.info(f"Webhook Paystack: Paiement réussi pour la référence {reference}, utilisateur {user_id}, service {service}.")
                
                # Marquer comme payé dans la base de données
                mark_order_paid_by_ref(reference)
                
                # Exécuter l'envoi du tutoriel de manière asynchrone
                async def deliver_tutorial_async():
                    if telegram_app:
                        context = ContextTypes.DEFAULT_TYPE(application=telegram_app)
                        await send_tutorial_to_user(user_id, service, context)
                
                threading.Thread(target=lambda: asyncio.run(deliver_tutorial_async()), daemon=True).start()

                return jsonify({"message": "Webhook processed"}), 200

            else:
                logger.warning(f"Webhook Paystack: Paiement réussi mais aucune commande en attente trouvée pour la référence {reference}.")
                return jsonify({"message": "No matching order"}), 200
        else:
            logger.info(f"Webhook Paystack: Statut de la transaction non 'success'. Statut: {status}")
            return jsonify({"message": "Not a successful transaction"}), 200
    else:
        return jsonify({"message": "Event ignored"}), 200

# -------------------------
# Build & run the Telegram Application
# -------------------------
def build_telegram_app() -> Application:
    global telegram_app
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not configured")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        # cmd_start, handler_service_choice, etc. sont maintenant définis plus haut !
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SERVICE: [CallbackQueryHandler(handler_service_choice, pattern="^service_|^back_to_service", per_message=True)],
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
build_telegram_app() # Cette ligne appelle la fonction build_telegram_app APRÈS la définition de cmd_start

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
