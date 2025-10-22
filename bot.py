import os
import logging
import requests
import sqlite3
from flask import Flask, request, jsonify
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ---------------- CONFIGURATION ---------------- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
EXTERNAL_URL = os.getenv("EXTERNAL_URL")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "").split(",") if i]
TUTORIAL_LINK = os.getenv("TUTORIAL_LINK", "https://t.me/+PSutZmE0v39iYWJk")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://wa.me/0503651426")
PAYSTACK_TIKTOK = os.getenv("PAYSTACK_TIKTOK", "")
PAYSTACK_FACEBOOK = os.getenv("PAYSTACK_FACEBOOK", "")
PRICE_TIKTOK = int(os.getenv("PRICE_TIKTOK", "6000"))
PRICE_FACEBOOK = int(os.getenv("PRICE_FACEBOOK", "8000"))

# ---------------- LOGGING ---------------- #
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- DATABASE ---------------- #
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    platform TEXT,
    country TEXT,
    whatsapp TEXT,
    payment_link TEXT,
    paid INTEGER DEFAULT 0
)""")
conn.commit()

# ---------------- FLASK APP (PAYSTACK WEBHOOK) ---------------- #
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot en ligne ✅"

@flask_app.route('/paystack-webhook', methods=['POST'])
def paystack_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400

    event = data.get('event')
    if event == "charge.success":
        email = data['data']['customer']['email']
        amount = int(data['data']['amount']) / 100

        # Recherche utilisateur dans la DB
        c.execute("SELECT user_id, platform FROM users WHERE whatsapp = ?", (email,))
        user = c.fetchone()
        if user:
            user_id, platform = user
            # Marque comme payé
            c.execute("UPDATE users SET paid = 1 WHERE whatsapp = ?", (email,))
            conn.commit()

            # Envoi automatique du lien tutoriel
            message = f"✅ Paiement reçu avec succès !\nMerci pour ton achat {platform}.\n\nVoici ton lien pour voir la vidéo :\n{TUTORIAL_LINK}"
            try:
                application.bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Erreur d'envoi : {e}")

            # Notifie le groupe admin
            application.bot.send_message(
                chat_id=GROUP_ID,
                text=f"💸 Nouvel achat validé !\n\nUtilisateur : {user_id}\nPlateforme : {platform}\nMontant : {amount} FCFA"
            )

    return jsonify({"status": "success"}), 200

# ---------------- TELEGRAM BOT ---------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎵 Compte TikTok Monétisé", callback_data="tiktok")],
        [InlineKeyboardButton("📘 Compte Facebook Monétisé", callback_data="facebook")],
        [InlineKeyboardButton("ℹ️ Comment ça marche ?", url=TUTORIAL_LINK)],
        [InlineKeyboardButton("🧑‍💬 Contacter le support", url=SUPPORT_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Bienvenue !\n\nChoisis le type de compte que tu veux monétiser 👇",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data
    context.user_data["platform"] = platform

    await query.message.reply_text("🌍 Entre ton pays :")

async def get_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "platform" not in context.user_data:
        return
    context.user_data["country"] = text
    await update.message.reply_text("📱 Envoie ton numéro WhatsApp (ex: 0700000000) :")

async def get_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    whatsapp = update.message.text
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "inconnu"
    platform = context.user_data["platform"]
    country = context.user_data["country"]

    # Détermination du prix et lien
    if platform == "tiktok":
        price = PRICE_TIKTOK
        pay_link = PAYSTACK_TIKTOK
    else:
        price = PRICE_FACEBOOK
        pay_link = PAYSTACK_FACEBOOK

    # Sauvegarde
    c.execute("INSERT INTO users (user_id, username, platform, country, whatsapp, payment_link) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, platform, country, whatsapp, pay_link))
    conn.commit()

    # Message de confirmation
    message = f"🧾 Récapitulatif :\n\nPlateforme : {platform}\nPays : {country}\nWhatsApp : {whatsapp}\nPrix : {price} FCFA\n\n👉 Clique ici pour payer : {pay_link}\n\nAprès paiement, tu recevras automatiquement le lien de la vidéo 🎥."
    await update.message.reply_text(message)

# ---------------- INITIALISATION ---------------- #
application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_country))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_whatsapp))

def run():
    application.run_polling()

# ---------------- LANCEMENT SUR RENDER ---------------- #
if __name__ == "__main__":
    from threading import Thread
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    run()
