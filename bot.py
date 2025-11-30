# -*- coding: utf-8 -*-
"""
Bot Telegram Monétisation
Auteur : Aristide
Description :
Bot complet pour monétiser TikTok et Facebook.
Fonctionne 24h/24 sur Render.
Collecte : nom, pays, numéro WhatsApp.
Envoie : résumé + instructions + lien Paystack + accès groupe.
"""

import telebot
from telebot import types
import re

# ==========================
# CONFIGURATION (À MODIFIER)
# ==========================

BOT_TOKEN = "8351407177:AAERierzxpvTwSb5WwlJf_TncwbXhE6xCA0"  # Ton token Telegram
ADMINS = [6357925694]           # Ton ID admin Telegram

# Liens Paystack
PAYMENT_LINK_TIKTOK = "https://paystack.shop/pay/9-9a5jxmgd"
PAYMENT_LINK_FACEBOOK = "https://paystack.shop/pay/21xb9p3kbn"

# Groupes privés
GROUP_TIKTOK = "https://paystack.shop/pay/9-9a5jxmgd"
GROUP_FACEBOOK = "https://paystack.shop/pay/21xb9p3kbn"

# ==========================
# INITIALISATION
# ==========================

bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}   # stocke les infos temporairement

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

# ==========================
# VALIDATION
# ==========================

def is_valid_number(number):
    return re.fullmatch(r"\+?\d{8,15}", number) is not None

# ==========================
# COMMAND START
# ==========================

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        f"👋 Bonjour {message.from_user.first_name} !\n\n"
        "Bienvenue dans notre système de monétisation 🎉\n"
        "Choisissez une option ci-dessous 👇",
        reply_markup=main_menu()
    )

# ==========================
# GESTION DES TEXTES
# ==========================

@bot.message_handler(func=lambda msg: True)
def bot_logic(message):
    user_id = message.from_user.id
    text = message.text

    # Menu principal
    if text == "Monétisation":
        bot.send_message(message.chat.id, "Choisissez la plateforme :", reply_markup=monetization_menu())
        return

    if text == "Comment ça marche":
        bot.send_message(
            message.chat.id,
            "📌 *Comment ça marche ?*\n\n"
            "1️⃣ Choisissez une plateforme que tu veut monétiser(TikTok ou Facebook)\n"
            "2️⃣ Remplissez vos informations\n"
            "3️⃣ Payez les frais de monétisation\n"
            "4️⃣ Vous recevez l’accès instantané au groupe privé\n"
            "5️⃣ Vous êtes guidé étape par étape pour la création n",
            parse_mode="Markdown"
        )
        return

    if text == "Support":
        bot.send_message(
            message.chat.id,
            "📞 *Support disponible 24h/24 :*\n"
            "👉 Contactez un administrateur pour toute assistance.",
            parse_mode="Markdown"
        )
        return

    if text == "⬅️ Retour":
        bot.send_message(message.chat.id, "Menu principal :", reply_markup=main_menu())
        return

    # ==========================
    # MONÉTISATION → TIKTOK
    # ==========================
    if text == "TikTok":
        user_data[user_id] = {"platform": "TikTok"}
        bot.send_message(message.chat.id, "🎤 Entrez votre *nom complet* :", parse_mode="Markdown")
        return

    if text == "Facebook":
        user_data[user_id] = {"platform": "Facebook"}
        bot.send_message(message.chat.id, "🎤 Entrez votre *nom complet* :", parse_mode="Markdown")
        return

    # ==========================
    # COLLECTE DES INFOS
    # ==========================
    if user_id in user_data:

        # Nom
        if "name" not in user_data[user_id]:
            user_data[user_id]["name"] = text
            bot.send_message(message.chat.id, "🌍 Entrez votre *pays* :", parse_mode="Markdown")
            return

        # Pays
        if "country" not in user_data[user_id]:
            user_data[user_id]["country"] = text
            bot.send_message(message.chat.id, "📱 Entrez votre *numéro WhatsApp* :", parse_mode="Markdown")
            return

        # Numéro WhatsApp
        if "phone" not in user_data[user_id]:

            if not is_valid_number(text):
                bot.send_message(
                    message.chat.id,
                    "❌ Numéro invalide.\n\nFormat accepté :\n+2250700000000 ou 0700000000"
                )
                return

            user_data[user_id]["phone"] = text

            # ==========================
            # AFFICHAGE RÉCAPITULATIF
            # ==========================
            data = user_data[user_id]
            platform = data["platform"]

            price = "5 000 F CFA" if platform == "TikTok" else "10 000 F CFA"
            pay_link = PAYMENT_LINK_TIKTOK if platform == "TikTok" else PAYMENT_LINK_FACEBOOK
            group_link = GROUP_TIKTOK if platform == "TikTok" else GROUP_FACEBOOK

            bot.send_message(
                message.chat.id,
                f"🎉 *Informations reçues !*\n\n"
                f"👤 Nom : {data['name']}\n"
                f"🌍 Pays : {data['country']}\n"
                f"📱 WhatsApp : {data['phone']}\n"
                f"🎯 Plateforme : *{platform}*\n"
                f"💵 Prix : *{price}*\n\n"
                "Pour continuer, cliquez sur le lien ci-dessous pour effectuer votre paiement 👇",
                parse_mode="Markdown"
            )

            # Lien Paystack
            bot.send_message(message.chat.id, f"💳 *Lien de paiement :*\n{pay_link}")

            # Message final
            bot.send_message(
                message.chat.id,
                f"🔗 Après paiement, vous serez automatiquement ajouté dans le groupe privé :\n{group_link}"
            )

            # Envoi aux admins
            for admin in ADMINS:
                bot.send_message(
                    admin,
                    f"🆕 NOUVELLE DEMANDE :\n\n"
                    f"Plateforme : {platform}\n"
                    f"Nom : {data['name']}\n"
                    f"Pays : {data['country']}\n"
                    f"WhatsApp : {data['phone']}"
                )

            # Nettoyage de la mémoire
            del user_data[user_id]

            return

# ==========================
# LANCEMENT DU BOT
# ==========================

print("Bot en ligne 24h/24…")
bot.infinity_polling(skip_pending=True)
