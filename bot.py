# bot.py
# Bot Monétisation — Français pur
# Remplir : TELEGRAM_TOKEN, GROUP_ID, ADMIN_IDS, PAYSTACK_TIKTOK, PAYSTACK_FACEBOOK, TUTORIAL_LINK, SUPPORT_LINK

import os
import logging
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

# =================== CONFIG - REMPLIS ICI (ou mets en vars d'env sur Render) ===================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")      # TON TOKEN (ou variable d'env)
GROUP_ID = int(os.getenv("GROUP_CHAT_ID", "0"))       # ID du groupe admin
# Admins autorisés (exemptés du paiement) -> string CSV ou list d'ids ; exemple: "12345678,98765432"
ADMIN_IDS = os.getenv("ADMIN_IDS", "")                # ex: "123456789,111222333"
# Liens Paystack (deux liens séparés)
PAYSTACK_TIKTOK = os.getenv("PAYSTACK_TIKTOK", "")   # lien paiement pour TikTok (5000)
PAYSTACK_FACEBOOK = os.getenv("PAYSTACK_FACEBOOK", "") # lien paiement pour Facebook (8000)
# Lien du tutoriel (canal / vidéo) à envoyer après paiement
TUTORIAL_LINK = os.getenv("TUTORIAL_LINK", "")
# Lien support WhatsApp
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "")
# Prix (affichage)
PRICE_TIKTOK = os.getenv("PRICE_TIKTOK", "5000")
PRICE_FACEBOOK = os.getenv("PRICE_FACEBOOK", "8000")
# ================================================================================================

# Conversation states
LANG, SERVICE, COUNTRY, WHATSAPP, WAIT_PAYMENT = range(5)

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

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
    "price_tiktok": f"💰 Prix TikTok : *{PRICE_TIKTOK} F CFA*.\nCliquez sur le bouton PAYER pour procéder au paiement.",
    "price_facebook": f"💰 Prix Facebook : *{PRICE_FACEBOOK} F CFA*.\nCliquez sur le bouton PAYER pour procéder au paiement.",
    "how_it_works": (
        "🔎 *Comment ça marche*\n\n"
        "1) Choisissez le service (TikTok ou Facebook).\n"
        "2) Indiquez votre pays et votre numéro WhatsApp.\n"
        "3) Le bot affiche le prix et le bouton de paiement.\n"
        "4) Après paiement confirmé (Paystack), le tutoriel est envoyé automatiquement.\n\n"
        "Important : *Vous devez payer avant d’accéder au tutoriel.*\n"
        "Le bot n'est pas responsable si vous ne suivez pas la procédure. *Aucun remboursement.*"
    ),
    "admin_note": "Vous êtes admin — accès direct au tutoriel sans paiement.",
    "pay_missing": "⚠️ Le lien de paiement n'est pas configuré. Contactez le support.",
    "thanks_auto": "✅ Paiement confirmé — le tutoriel vous a été envoyé.",
    "no_tutorial": "✅ Paiement confirmé — le tutoriel sera envoyé dès que disponible.",
    "support_text": "Contactez le support via ce lien :",
    "cancel": "Commande annulée. Tapez /start pour recommencer."
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

def pay_keyboard_for_service(service_key):
    # service_key: "tiktok" or "facebook"
    if service_key == "tiktok" and PAYSTACK_TIKTOK:
        pay_button = InlineKeyboardButton("Payer (Paystack) - TikTok", url=PAYSTACK_TIKTOK)
    elif service_key == "facebook" and PAYSTACK_FACEBOOK:
        pay_button = InlineKeyboardButton("Payer (Paystack) - Facebook", url=PAYSTACK_FACEBOOK)
    else:
        pay_button = InlineKeyboardButton("Payer (lien non configuré)", callback_data="no_link")
    keyboard = [
        [pay_button],
        [InlineKeyboardButton("✅ J'ai payé (envoyer preuve)", callback_data="i_paid")],
        [InlineKeyboardButton("❌ Annuler", callback_data="cancel_order")]
    ]
    return InlineKeyboardMarkup(keyboard)

def support_keyboard():
    if SUPPORT_LINK:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support", url=SUPPORT_LINK)]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("Contacter support (non configuré)", callback_data="no_support")]])

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT["choose_language"])
    # On skip language selection since only FR required by you
    await update.message.reply_text(TEXT["welcome"], reply_markup=main_menu_keyboard())
    return SERVICE

async def service_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "contact_support":
        await query.message.reply_text(f"{TEXT['support_text']} {SUPPORT_LINK}", reply_markup=support_keyboard())
        return ConversationHandler.END

    if data == "how_it_works":
        await query.message.reply_markdown(TEXT["how_it_works"])
        return ConversationHandler.END

    if data == "service_tiktok":
        context.user_data["service"] = "tiktok"
        await query.message.reply_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY

    if data == "service_facebook":
        context.user_data["service"] = "facebook"
        await query.message.reply_text(TEXT["ask_country"], reply_markup=ReplyKeyboardRemove())
        return COUNTRY

    # fallback
    await query.message.reply_text("Option inconnue.")
    return ConversationHandler.END

async def country_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["country"] = update.message.text.strip()
    await update.message.reply_text(TEXT["ask_whatsapp"])
    return WHATSAPP

async def whatsapp_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["whatsapp"] = update.message.text.strip()
    service = context.user_data.get("service")
    user_id = update.effective_user.id
    admin_ids = get_admin_ids()

    # If user is admin -> send tutorial directly (admin exempt)
    if user_id in admin_ids:
        # send admin note and tutorial
        await update.message.reply_text(TEXT["admin_note"])
        if TUTORIAL_LINK:
            await update.message.reply_text(f"Voici le tutoriel :\n{TUTORIAL_LINK}")
        else:
            await update.message.reply_text("Le lien du tutoriel n'est pas encore configuré.")
        # also send record to admin group that admin viewed
        admin_msg = (
            f"🔰 *ADMIN VIEW*\n"
            f"• Admin id: {user_id}\n"
            f"• Service: {service}\n"
        )
        try:
            await context.bot.send_message(chat_id=GROUP_ID, text=admin_msg, parse_mode="Markdown")
        except Exception as e:
            logger.exception("Erreur en notifiant le groupe admin: %s", e)
        context.user_data.clear()
        return ConversationHandler.END

    # Non-admin: show price & pay link for the chosen service
    if service == "tiktok":
        await update.message.reply_markdown(TEXT["price_tiktok"], reply_markup=pay_keyboard_for_service("tiktok"))
    elif service == "facebook":
        await update.message.reply_markdown(TEXT["price_facebook"], reply_markup=pay_keyboard_for_service("facebook"))
    else:
        await update.message.reply_text("Service inconnu. Tape /start pour recommencer.")
        context.user_data.clear()
        return ConversationHandler.END

    # Inform user of policies (no refund, bot not responsible)
    policy = (
        "⚠️ *Important*\n"
        "- Vous devez payer avant d'accéder au tutoriel.\n"
        "- Aucun remboursement.\n"
        "- Le bot n'est pas responsable si vous ne suivez pas la procédure.\n"
    )
    await update.message.reply_markdown(policy)
    return WAIT_PAYMENT

async def wait_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "no_link":
        await query.message.reply_text(TEXT["pay_missing"], reply_markup=support_keyboard())
        return WAIT_PAYMENT

    if data == "cancel_order":
        await query.message.reply_text(TEXT["cancel"])
        context.user_data.clear()
        return ConversationHandler.END

    if data == "i_paid":
        # ask user to send screenshot (we keep fallback check even if Auto Paystack is used)
        await query.message.reply_text("➡️ Merci. Envoie ici la capture du paiement (image).")
        # now wait for image/document; handled by screenshot handler below
        return WAIT_PAYMENT

    return WAIT_PAYMENT

async def screenshot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If user sends screenshot (photo/document) — forward to admin group and remind that webhook will auto-deliver if Paystack used
    user = update.effective_user
    service = context.user_data.get("service", "—")
    country = context.user_data.get("country", "—")
    whatsapp = context.user_data.get("whatsapp", "—")
    caption = (
        f"📥 *Preuve manuelle reçue*\n"
        f"• *Utilisateur* : {user.full_name} (id:{user.id})\n"
        f"• *Service* : {service}\n"
        f"• *Pays* : {country}\n"
        f"• *WhatsApp* : {whatsapp}\n"
    )
    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            await context.bot.send_photo(chat_id=GROUP_ID, photo=photo.file_id, caption=caption, parse_mode="Markdown")
        elif update.message.document:
            doc = update.message.document
            await context.bot.send_document(chat_id=GROUP_ID, document=doc.file_id, caption=caption, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=caption, parse_mode="Markdown")
            await context.bot.forward_message(chat_id=GROUP_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as e:
        logger.exception("Erreur en envoyant la preuve au groupe: %s", e)
        await update.message.reply_text("Erreur interne. Contacte le support.")
        context.user_data.clear()
        return ConversationHandler.END

    # remind user that if Paystack webhook is configured the tutorial will be sent automatically; otherwise admin will validate.
    await update.message.reply_text("✅ Preuve reçue. Si votre paiement a bien été reçu, vous recevrez automatiquement le tutoriel une fois la transaction confirmée (ou l'admin vous validera).")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT["cancel"])
    context.user_data.clear()
    return ConversationHandler.END

# Admin-only command to send tutorial to a user (for manual override)
async def admin_send_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_ids = get_admin_ids()
    user_id = update.effective_user.id
    if user_id not in admin_ids:
        await update.message.reply_text("Commande réservée aux admins.")
        return
    # usage: /sendtutorial <telegram_id>
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
                CallbackQueryHandler(wait_payment_handler, pattern="^(no_link|i_paid|cancel_order)$"),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.Document.FILE, screenshot_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Bot actif ✅")))
    application.add_handler(CommandHandler("sendtutorial", admin_send_tutorial))
    return application

# Entrée pour exécution directe (polling) utile en local
if __name__ == "__main__":
    app = build_app()
    print("Lancement du bot en mode polling (local/test).")
    app.run_polling()
