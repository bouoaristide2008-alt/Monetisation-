# -*- coding: utf-8 -*-
"""
Bot Telegram Monétisation prêt pour Render
Auteur : Aristide
Description :
- Monétisation TikTok / Facebook
- Collecte : Nom, Pays, WhatsApp
- Récapitulatif + lien Paystack
- Bouton support WhatsApp
- Webhook Flask pour Render (sans polling)
"""

from flask import Flask, request
import telebot
from telebot import types

# ==========================
# CONFIGURATION
# ==========================
BOT_TOKEN = "8351407177:AAERierzxpvTwSb5WwlJf_TncwbXhE6xCA0"  # Token Telegram
ADMINS = [6357925694]  # IDs admins

# Liens Paystack
PAYMENT_LINK_TIKTOK = "https://paystack.shop/pay/9-9a5jxmgd"
PAYMENT_LINK_FACEBOOK = "https://paystack.shop/pay/21xb9p3kbn"

# Lien groupe Telegram explicatif
GROUP_INFO = "https://t.me/+TCuZJmqAUj85ZTM8"

# Numéro WhatsApp support
SUPPORT_NUMBER = "2250501436408"
SUPPORT_LINK = f"https://wa.me/{SUPPORT_NUMBER}"

# ==========================
# INITIALISATION
# ==========================
bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}

app = Flask(__name__)

# ==========================
# WEBHOOK FLASK
# ==========================
@app.route("/")
def index():
    return "Bot Telegram actif."

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# ==========================
# MENUS
# ==========================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("Monétisation"),
        types.KeyboardButton("Comment ça marche"),
        types.KeyboardButton("Support")
    )
    return markup

def monetization_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("TikTok"),
        types.KeyboardButton("Facebook"),
        types.KeyboardButton("⬅️ Retour")
    )
    return markup

def previous_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("⬅️ Retour au menu principal")
    )
    return markup

def support_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Contacter le support WhatsApp", url=SUPPORT_LINK))
    return kb

# ==========================
# START
# ==========================
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        f"👋 Bonjour {message.from_user.first_name} !\n\n"
        "Bienvenue dans notre système de monétisation 🎉\n"
        "Veuillez choisir une option ci-dessous 👇",
        reply_markup=main_menu()
    )

# ==========================
# LOGIQUE
# ==========================
@bot.message_handler(func=lambda m: True)
def bot_logic(message):
    user_id = message.from_user.id
    text = message.text.strip()

    # MENU PRINCIPAL
    if text == "Monétisation":
        bot.send_message(message.chat.id, "Choisissez la plateforme :", reply_markup=monetization_menu())
        return

    if text == "Comment ça marche":
        bot.send_message(
            message.chat.id,
            "📌 *Comment fonctionne la monétisation ?*\n\n"
            "1️⃣ *Choix de la plateforme* : TikTok (5 000 F) ou Facebook (10 000 F).\n\n"
            "2️⃣ *Collecte des informations* : Votre nom, pays et numéro WhatsApp.\n\n"
            "3️⃣ *Paiement sécurisé* : Via Paystack, 100% sécurisé.\n\n"
            "4️⃣ *Accès au groupe Telegram* : Après paiement, vous trouverez un tutoriel vidéo complet et un assistant pour créer votre compte.\n\n"
            "5️⃣ *Assistance continue* : Pendant ~1 mois, un assistant vous aide à finaliser votre compte.\n\n"
            f"6️⃣ *Plus d’informations et accompagnement* : [Cliquez ici pour rejoindre le groupe]({GROUP_INFO})\n\n"
            "🎯 Guidé de A à Z, même sans expérience technique.",
            parse_mode="Markdown"
        )
        return

    if text == "Support":
        bot.send_message(
            message.chat.id,
            "📞 *Support officiel 24h/24*\nCliquez ci-dessous pour nous contacter directement.",
            parse_mode="Markdown",
            reply_markup=support_keyboard()
        )
        return

    # RETOURS
    if text == "⬅️ Retour":
        bot.send_message(message.chat.id, "Menu principal :", reply_markup=main_menu())
        return

    if text == "⬅️ Retour au menu principal":
        bot.send_message(message.chat.id, "Menu principal :", reply_markup=main_menu())
        return

    # MONÉTISATION
    if text in ["TikTok", "Facebook"]:
        user_data[user_id] = {"platform": text}
        bot.send_message(message.chat.id, "🎤 Entrez votre *nom complet* :", parse_mode="Markdown", reply_markup=previous_menu())
        return

    # COLLECTE D'INFOS
    if user_id in user_data:
        # Nom
        if "name" not in user_data[user_id]:
            user_data[user_id]["name"] = text
            bot.send_message(message.chat.id, "🌍 Entrez votre *pays* :", parse_mode="Markdown", reply_markup=previous_menu())
            return

        # Pays
        if "country" not in user_data[user_id]:
            user_data[user_id]["country"] = text
            bot.send_message(message.chat.id, "📱 Entrez votre *numéro WhatsApp* :", parse_mode="Markdown", reply_markup=previous_menu())
            return

        # Numéro WhatsApp (aucune validation stricte)
        if "phone" not in user_data[user_id]:
            user_data[user_id]["phone"] = text
            data = user_data[user_id]
            platform = data["platform"]

            price = "5 000 F CFA" if platform == "TikTok" else "10 000 F CFA"
            pay_link = PAYMENT_LINK_TIKTOK if platform == "TikTok" else PAYMENT_LINK_FACEBOOK

            bot.send_message(
                message.chat.id,
                f"🎉 *Informations reçues !*\n\n"
                f"👤 Nom : {data['name']}\n"
                f"🌍 Pays : {data['country']}\n"
                f"📱 WhatsApp : {data['phone']}\n"
                f"🎯 Plateforme : *{platform}*\n"
                f"💵 Prix : *{price}*\n\n"
                "💳 *Étape finale : valider votre paiement*\n"
                f"Cliquez sur le lien ci-dessous pour un paiement sécurisé via Paystack.\n\n"
                f"Après paiement, rejoignez le groupe explicatif ici : {GROUP_INFO}",
                parse_mode="Markdown"
            )

            bot.send_message(message.chat.id, f"💳 Lien de paiement : {pay_link}")

            # Notification admins
            for admin in ADMINS:
                bot.send_message(
                    admin,
                    f"🆕 NOUVELLE DEMANDE :\n"
                    f"Plateforme : {platform}\n"
                    f"Nom : {data['name']}\n"
                    f"Pays : {data['country']}\n"
                    f"WhatsApp : {data['phone']}"
                )

            del user_data[user_id]
            return

# ==========================
# LANCEMENT (Render)
# ==========================
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
