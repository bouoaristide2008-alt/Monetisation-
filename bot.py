import os
import logging
import json
import requests
import asyncio
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
8020027521:AAHRypwd_Xx0AiyrDGfJJtEe8jhYcQ29wlQ
# =================== 🛑 CONFIGURATION - REMPLISSEZ ICI DIRECTEMENT 🛑 ===================

# 1. Votre Jeton (Token) Telegram Bot (ex: "123456:AABBCC...")
TELEGRAM_TOKEN = "8020027521:AAHRypwd_Xx0AiyrDGfJJtEe8jhYcQ29wlQ" 

# 2. Clé Secrète Paystack (sk_live_xxxx... - OBLIGATOIRE pour l'automatisation)
PAYSTACK_SECRET_KEY = "VOTRE_CLE_SECRETE_PAYSTACK_ICI" 

# 3. ID de votre groupe/chat admin (où vous recevez les notifications)
# Doit commencer par -100 si c'est un groupe. (ex: -100123456789)
GROUP_ID = int("-4943478525") 

# 4. ID des administrateurs exemptés de paiement (séparés par des virgules)
ADMIN_IDS = "6357925694, 98765432"

# 5. URL Publique de votre serveur (vous devez la connaître après le déploiement initial)
# Exemple: "https://mon-bot-payant-xxxx.onrender.com"
EXTERNAL_URL = "VOTRE_URL_PUBLIQUE_DE_L_HEBERGEUR_ICI" 

# --- Liens et Prix ---

# Lien du tutoriel à envoyer après paiement
TUTORIAL_LINK ="https://t.me/+TCuZJmqAUj85ZTM8" 
# Lien support WhatsApp
SUPPORT_LINK = "https://wa.me/0503651426" 
# Prix (affichage et montant Paystack)
PRICE_TIKTOK = "6000"
PRICE_FACEBOOK = "8000"
# Port d'écoute du serveur (souvent 5000 par défaut)
PORT = 5000 
# ================================================================================================

# Conversation states
LANG, SERVICE, COUNTRY, WHATSAPP, WAIT_PAYMENT = range(5)

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask App pour les webhooks (Paystack et Telegram)
flask_app = Flask(__name__)

# Base de données temporaire pour stocker les infos utilisateur avant le paiement
PENDING_ORDERS = {} # key: user_id, value: {'service': str, 'country': str, 'whatsapp': str}

# Helper: admin list as ints
def get_admin_ids():
    if not ADMIN_IDS:
        return []
    return [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

# Texts (FR)
TEXT = {
    "choose_language": "🇫🇷 Français\nChoisissez la langue :",
    "welcome": "Bienvenue 👋\nChoisissez une option :",
    "menu": ["Monétiser TikTok", "Monétiser Facebook", "📞 Contacter Support", "❓ Comment ça marche"],
    "ask_country": "Dans quel pays êtes-vous ? 🌍",
    "ask_whatsapp": "Donnez votre numéro WhatsApp (format international recommandé, ex: +22570xxxxxxx) :",
    "price_tiktok": f"💰 Prix TikTok : *{PRICE_TIKTOK} F CFA*.\n\n*Cliquez sur le bouton pour générer votre lien de paiement personnalisé.*",
    "price_facebook": f"💰 Prix Facebook : *{PRICE_FACEBOOK} F CFA*.\n\n*Cliquez sur le bouton pour générer votre lien de paiement personnalisé.*",
    "pay_button_tiktok": f"Générer Lien de Paiement ({PRICE_TIKTOK} F CFA)",
    "pay_button_facebook": f"Générer Lien de Paiement ({PRICE_FACEBOOK} F CFA)",
    "how_it_works": (
        "🔎 *Comment ça marche (Automatisé)*\n\n"
        "1) Choisissez le service (TikTok ou Facebook).\n"
        "2) Indiquez votre pays et votre numéro WhatsApp.\n"
        "3) Le bot génère un lien de paiement Paystack personnalisé.\n"
        "4) Après paiement confirmé par Paystack, *le tutoriel est envoyé automatiquement par le bot*.\n\n"
        "Important : *Le processus est 100% automatique après paiement. Aucun screenshot n'est nécessaire.*"
    ),
    "admin_note": "Vous êtes admin — accès direct au tutoriel sans paiement.",
    "pay_missing": "⚠️ Erreur de configuration: Clé Paystack ou URL non configurée. Contactez le support.",
    "thanks_auto": "✅ Paiement confirmé ! Le tutoriel vous a été envoyé ci-dessous.",
    "no_tutorial": "✅ Paiement confirmé — le tutoriel sera envoyé dès que disponible.",
    "support_text": "Contactez le support via ce lien :",
    "cancel": "Commande annulée. Tapez /start pour recommencer.",
    "error_paystack": "Une erreur est survenue lors de la création du lien de paiement. Veuillez réessayer ou contacter le support.",
    "waiting_payment": "⏳ *En attente de votre paiement...*\n\nCliquez sur le lien ci-dessus pour finaliser la transaction. *La livraison du tutoriel sera automatique.*"
}

# Keyboards
def main_menu_keyboard():
    menu = TEXT["menu"]
    keyboard = [
        [InlineKeyboardButton(menu[0], callback_data="service_tiktok")],
        [InlineKeyboardButton(menu[1], callback_data="service_facebook")],
        [InlineKeyboardButton(menu[2], callback_data="contact_support")],
        [InlineKeyboardButton(menu[3], callback_data="how_it_works")],
    ]
    return InlineKeyboardMarkup(keyboard)

def generate_pay_keyboard(service):
    data = f"generate_pay_{service}"
    text = TEXT["pay_button_tiktok"] if service == "tiktok" else TEXT["pay_button_facebook"]
    keyboard = [
        [InlineKeyboardButton(text, callback_data=data)],
        [InlineKeyboardButton("❌ Annuler", callback_data="cancel_order")]
    ]
    return InlineKeyboardMarkup(keyboard)

def pay_link_keyboard(pay_url):
    keyboard = [
        [InlineKeyboardButton("💳 Payer Maintenant", url=pay_url)],
        [InlineKeyboardButton("❌ Annuler la commande", callback_data="cancel_order")]
    ]
    return InlineKeyboardMarkup(keyboard)

def support_keyboard():
    if SUPPORT_LINK:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support", url=SUPPORT_LINK)]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support (non configuré)", callback_data="no_support")]])

# ======================= FONCTION DE LIVRAISON (Utilisée par le Webhook) =======================

async def deliver_tutorial(user_id: int, service: str, reference: str, app: Application):
    """Envoie le tutoriel à l'utilisateur après confirmation du paiement."""
    
    logger.info(f"Début de livraison automatique pour user: {user_id}, ref: {reference}")
    
    # 1. Envoyer le tutoriel
    if TUTORIAL_LINK:
        text = f"{TEXT['thanks_auto']}\n{TUTORIAL_LINK}"
    else:
        text = TEXT["no_tutorial"]
        
    try:
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Impossible d'envoyer le message de livraison à {user_id}: {e}")
        
    # 2. Notifier les admins
    try:
        # Récupérer les infos utilisateurs depuis le stockage temporaire ou les données de l'application
        user_info = app.user_data.get(user_id, PENDING_ORDERS.get(user_id, {'service': 'N/A', 'country': 'N/A', 'whatsapp': 'N/A'}))
        admin_msg = (
            f"🎉 *PAIEMENT AUTOMATIQUE CONFIRMÉ*\n"
            f"• *Utilisateur ID* : {user_id}\n"
            f"• *Service* : {service}\n"
            f"• *Ref Paystack* : {reference}\n"
            f"• *Pays* : {user_info.get('country')}\n"
            f"• *WhatsApp* : {user_info.get('whatsapp')}"
        )
        await app.bot.send_message(chat_id=GROUP_ID, text=admin_msg, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Erreur en notifiant le groupe admin: {e}")
        
    # 3. Nettoyer les données temporaires
    if user_id in PENDING_ORDERS:
        del PENDING_ORDERS[user_id]
    
# ======================= LOGIQUE DE PAIEMENT PAYSTACK =======================

def initialize_paystack_transaction(user_id, service, email, amount, whatsapp):
    """Appel à l'API Paystack pour obtenir un lien de paiement dynamique."""
    url = "https://api.paystack.co/transaction/initialize"
    try:
        amount_kobo = int(amount) * 100 # Montant en kobo/centimes
    except ValueError:
        logger.error(f"Montant invalide: {amount}")
        return None

    # CRUCIAL : Inclusion de la metadata avec l'ID Telegram
    metadata = {
        "custom_fields": [
            {"display_name": "Telegram ID", "variable_name": "telegram_id", "value": user_id},
            {"display_name": "Service", "variable_name": "service_type", "value": service},
            {"display_name": "WhatsApp", "variable_name": "whatsapp_number", "value": whatsapp},
        ]
    }
    
    payload = {
        "email": email,
        "amount": amount_kobo,
        "metadata": metadata,
        # URL de retour après paiement (optionnel)
        "callback_url": f"{EXTERNAL_URL}/paystack-callback" 
    }

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
        if data.get('status'):
            return data['data']['authorization_url']
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur d'initialisation Paystack: {e}")
        return None

# ======================= HANDLERS TELEGRAM =======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Stocker l'ID de l'utilisateur dans le contexte de l'application (pour le webhook)
    user_id = update.effective_user.id
    if user_id not in context.application.user_data:
         context.application.user_data[user_id] = {}
    
    await update.message.reply_text(TEXT["choose_language"])
    await update.message.reply_text(TEXT["welcome"], reply_markup=main_menu_keyboard())
    return SERVICE

async def service_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    # Utiliser context.application.user_data pour stocker les données de manière persistante
    user_data = context.application.user_data.get(query.from_user.id) or {}
    
    if data == "contact_support":
        await query.message.reply_text(f"{TEXT['support_text']} {SUPPORT_LINK}", reply_markup=support_keyboard())
        return ConversationHandler.END

    if data == "how_it_works":
        await query.message.reply_markdown(TEXT["how_it_works"])
        return ConversationHandler.END

    if data == "service_tiktok":
        user_data["service"] = "tiktok"
        await query.message.reply_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY

    if data == "service_facebook":
        user_data["service"] = "facebook"
        await query.message.reply_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY
    
    await query.message.reply_text("Option inconnue.")
    return ConversationHandler.END

async def country_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = context.application.user_data.get(user_id, {})
    user_data["country"] = update.message.text.strip()
    await update.message.reply_text(TEXT["ask_whatsapp"])
    return WHATSAPP

async def whatsapp_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = context.application.user_data.get(user_id, {})
    user_data["whatsapp"] = update.message.text.strip()
    service = user_data.get("service")
    
    # Stocker temporairement dans PENDING_ORDERS (pour l'accès depuis le webhook)
    PENDING_ORDERS[user_id] = user_data

    # Si admin
    if user_id in get_admin_ids():
        await update.message.reply_text(TEXT["admin_note"])
        if TUTORIAL_LINK:
            await update.message.reply_text(f"Voici le tutoriel :\n{TUTORIAL_LINK}")
        else:
            await update.message.reply_text("Le lien du tutoriel n'est pas encore configuré.")
        
        # Nettoyage
        if user_id in PENDING_ORDERS: del PENDING_ORDERS[user_id]
        return ConversationHandler.END

    # Non-admin: Afficher les infos de prix et le bouton de génération de lien
    if service == "tiktok":
        await update.message.reply_markdown(TEXT["price_tiktok"], reply_markup=generate_pay_keyboard("tiktok"))
    elif service == "facebook":
        await update.message.reply_markdown(TEXT["price_facebook"], reply_markup=generate_pay_keyboard("facebook"))
    else:
        await update.message.reply_text("Service inconnu. Tape /start pour recommencer.")
        if user_id in PENDING_ORDERS: del PENDING_ORDERS[user_id]
        return ConversationHandler.END
        
    return WAIT_PAYMENT

async def generate_payment_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Génération du lien de paiement en cours...")
    
    user_id = query.from_user.id
    user_data = PENDING_ORDERS.get(user_id) or context.application.user_data.get(user_id)
    service = user_data.get("service")
    whatsapp = user_data.get("whatsapp")

    if not PAYSTACK_SECRET_KEY or not EXTERNAL_URL:
        await query.message.reply_text(TEXT["pay_missing"], reply_markup=support_keyboard())
        return WAIT_PAYMENT
    
    if service == "tiktok":
        amount = PRICE_TIKTOK
    elif service == "facebook":
        amount = PRICE_FACEBOOK
    else:
        await query.message.reply_text("Service ou données manquantes. Recommencez avec /start.")
        return ConversationHandler.END
        
    default_email = f"telegram{user_id}@notcollected.com"
        
    # Initialisation de la transaction Paystack
    pay_url = initialize_paystack_transaction(user_id, service, default_email, amount, whatsapp)

    if pay_url:
        await query.edit_message_text(
            TEXT["waiting_payment"], 
            parse_mode="Markdown", 
            reply_markup=pay_link_keyboard(pay_url)
        )
        return WAIT_PAYMENT
    else:
        await query.edit_message_text(TEXT["error_paystack"])
        return ConversationHandler.END

async def wait_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("generate_pay_"):
        return await generate_payment_link(update, context)

    if data == "cancel_order":
        await query.message.reply_text(TEXT["cancel"])
        user_id = update.effective_user.id
        if user_id in PENDING_ORDERS: del PENDING_ORDERS[user_id]
        return ConversationHandler.END
    
    return WAIT_PAYMENT

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT["cancel"])
    user_id = update.effective_user.id
    if user_id in PENDING_ORDERS: del PENDING_ORDERS[user_id]
    return ConversationHandler.END

async def admin_send_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_ids = get_admin_ids()
    user_id = update.effective_user.id
    if user_id not in admin_ids:
        await update.message.reply_text("Commande réservée aux admins.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /sendtutorial <telegram_user_id>")
        return
    try:
        target_id = int(args[0])
        if TUTORIAL_LINK:
            await context.bot.send_message(chat_id=target_id, text=f"Voici le tutoriel :\n{TUTORIAL_LINK}")
            await update.message.reply_text("Tutoriel envoyé.")
        else:
            await update.message.reply_text("TUTORIAL_LINK non configuré.")
    except Exception as e:
        await update.message.reply_text("Erreur lors de l'envoi.")
        logger.exception(e)


# ======================= LOGIQUE FLASK & WEBHOOK PAYSTACK =======================

@flask_app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
async def telegram_webhook_handler():
    """Gère toutes les mises à jour Telegram (messages, boutons, etc.)."""
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return 'ok'

@flask_app.route('/paystack-webhook', methods=['POST'])
async def paystack_webhook_handler():
    """Gère la notification de paiement Paystack."""
    data = request.get_json(force=True)
    
    # ⚠️ Vérification de sécurité de la signature (Crucial en Prod) - OMPLÉTÉE par la vérification API
    
    event = data.get('event')
    
    if event == 'charge.success':
        transaction = data.get('data')
        reference = transaction.get('reference')
        
        # --- (A) Vérification de la Transaction avec l'API Paystack ---
        verification_url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        
        try:
            response = requests.get(verification_url, headers=headers)
            response.raise_for_status()
            verification_data = response.json()
        
            if not verification_data.get('status') or verification_data.get('data').get('status') != 'success':
                logger.error(f"Paystack verification failed for ref {reference} (API check)")
                return jsonify({'status': 'failed', 'message': 'Verification failed'}), 200
            
            # --- (B) Récupérer l'ID Utilisateur depuis la Metadata ---
            metadata = verification_data.get('data').get('metadata', {})
            custom_fields = metadata.get('custom_fields', [])
            user_id_val = next((f['value'] for f in custom_fields if f.get('variable_name') == 'telegram_id'), None)
            service = next((f['value'] for f in custom_fields if f.get('variable_name') == 'service_type'), 'N/A')
            
            if not user_id_val:
                logger.error(f"User ID missing in metadata for ref {reference}")
                return jsonify({'status': 'error', 'message': 'Missing user_id'}), 200

            user_id = int(user_id_val)
            
            # --- (C) Livrer le Tutoriel ---
            # Nécessite de lancer une tâche asynchrone pour la livraison
            asyncio.run(deliver_tutorial(user_id, service, reference, telegram_app))
            
            return jsonify({'status': 'ok', 'message': 'Delivery initiated'}), 200

        except Exception as e:
            logger.exception(f"Error processing Paystack webhook: {e}")
            return jsonify({'status': 'error', 'message': 'Internal Error'}), 200
            
    return jsonify({'status': 'ignored', 'message': f'Event {event} ignored'}), 200

# ======================= CONSTRUCTION ET LANCEMENT =======================

def build_app():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN non configuré.")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SERVICE: [CallbackQueryHandler(service_handler, pattern="^(service_|contact_support|how_it_works)")],
            COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, country_received)],
            WHATSAPP: [MessageHandler(filters.TEXT & ~filters.COMMAND, whatsapp_received)],
            WAIT_PAYMENT: [
                CallbackQueryHandler(wait_payment_handler, pattern="^(generate_pay_|cancel_order)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Bot actif ✅")))
    application.add_handler(CommandHandler("sendtutorial", admin_send_tutorial))
    return application

telegram_app = build_app()

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not EXTERNAL_URL or not PAYSTACK_SECRET_KEY:
        print("ERREUR: Veuillez configurer toutes les variables cruciales dans le code.")
    else:
        # Configuration du webhook Telegram
        print("Configuration du Webhook Telegram...")
        telegram_app.bot.set_webhook(url=f"{EXTERNAL_URL}/{TELEGRAM_TOKEN}")
        
        # Lancement de l'application Flask pour écouter les webhooks Paystack et Telegram
        print(f"Lancement du serveur Flask sur le port {PORT}...")
        
        flask_app.run(host='0.0.0.0', port=PORT)
