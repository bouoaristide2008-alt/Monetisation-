# -*- coding: utf-8 -*-
"""
Bot Telegram Monétisation – Version finale complète
Auteur : Aristide
Fonctionne 24h/24 sur Render (Flask + Threading)
"""

import telebot
from telebot import types
import re
from flask import Flask
import threading

# ==========================
# CONFIGURATION
# ==========================

BOT_TOKEN = "8351407177:AAERierzxpvTwSb5WwlJf_TncwbXhE6xCA0"   # <-- Ton token ici
ADMINS = [6357925694]            # <-- Ton ID admin

# Liens Paystack
PAYMENT_LINK_TIKTOK = "https://paystack.shop/pay/9-9a5jxmgd"
PAYMENT_LINK_FACEBOOK = "https://paystack.shop/pay/21xb9p3kbn"

# Groupes privés
GROUP_TIKTOK ="https://paystack.shop/pay/21xb9p3kbn"
GROUP_FACEBOOK = "https://paystack.shop/pay/9-9a5jxmgd"

# Support WhatsApp
SUPPORT_WHATSAPP = "https://wa.me/2250503651426"

bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}

# ==========================
# SERVEUR FLASK (Render)
# ==========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Telegram fonctionnel."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

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
# VALIDATION NUMÉRO
# ==========================

def is_valid_number(number):
    return re.fullmatch(r"\+?\d{8,15}", number) is not None


# ==========================
# START
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
# SECTIONS
# ==========================

@bot.message_handler(func=lambda m: m.text == "Comment ça marche")
def how_it_works(message):
    bot.send_message(
        message.chat.id,
        "📌 *COMMENT FONCTIONNE LA MONÉTISATION ?*\n\n"
        "Voici tout ce que tu dois savoir avant de commencer :\n\n"
        "1️⃣ *La monétisation TikTok / Facebook est simple, rapide et sécurisée.*\n"
        "Nous t’accompagnons étape par étape pour obtenir un compte monétisé.\n\n"
        "2️⃣ *Tu choisis la plateforme :*\n"
        "- TikTok (5 000 F)\n"
        "- Facebook (10 000 F)\n\n"
        "3️⃣ *Tu fournis :*\n"
        "- Ton nom complet\n"
        "- Ton pays\n"
        "- Ton numéro WhatsApp\n\n"
        "4️⃣ *Tu valides ton paiement via Paystack (100% sécurisé).* 🔒\n\n"
        "5️⃣ *Après paiement, tu es automatiquement redirigé vers un groupe privé Telegram :*\n"
        "✔️ Vidéo tutorielle\n"
        "✔️ Guide complet\n"
        "✔️ Assistant pour t’aider jusqu’à la fin\n\n"
        "6️⃣ *En moins de 30 minutes, ton compte est prêt et monétisé.*\n\n"
        "🎯 Notre objectif : rendre la monétisation accessible à tous.\n"
        "Tu n’as rien à craindre — *on t’accompagne du début jusqu’à la fin.*",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "Support")
def support(message):
    support_btn = types.InlineKeyboardMarkup()
    support_btn.add(types.InlineKeyboardButton("📞 Contacter le support WhatsApp", url=SUPPORT_WHATSAPP))

    bot.send_message(
        message.chat.id,
        "📞 *Support officiel*\nClique ci-dessous pour nous écrire directement sur WhatsApp 👇",
        parse_mode="Markdown",
        reply_markup=support_btn
    )


# ==========================
# MONÉTISATION
# ==========================

@bot.message_handler(func=lambda m: m.text == "Monétisation")
def monetisation(message):
    bot.send_message(
        message.chat.id,
        "Choisis la plateforme que tu veux monétiser 👇",
        reply_markup=monetization_menu()
    )

@bot.message_handler(func=lambda m: m.text in ["TikTok", "Facebook"])
def choose_platform(message):
    user_id = message.from_user.id
    user_data[user_id] = {"platform": message.text}

    bot.send_message(message.chat.id, "Quel est ton nom complet ?")
    bot.register_next_step_handler(message, get_name)

def get_name(message):
    user_id = message.from_user.id
    user_data[user_id]["name"] = message.text

    bot.send_message(message.chat.id, "Ton pays :")
    bot.register_next_step_handler(message, get_country)

def get_country(message):
    user_id = message.from_user.id
    user_data[user_id]["country"] = message.text

    bot.send_message(message.chat.id, "Entre ton numéro WhatsApp (ex : +22507000000)")
    bot.register_next_step_handler(message, get_whatsapp)

def get_whatsapp(message):
    number = message.text
    user_id = message.from_user.id

    if not is_valid_number(number):
        bot.send_message(message.chat.id, "❌ Numéro invalide. Réessaye.")
        return bot.register_next_step_handler(message, get_whatsapp)

    user_data[user_id]["whatsapp"] = number

    platform = user_data[user_id]["platform"]
    name = user_data[user_id]["name"]
    country = user_data[user_id]["country"]

    link = PAYMENT_LINK_TIKTOK if platform == "TikTok" else PAYMENT_LINK_FACEBOOK

    group = GROUP_TIKTOK if platform == "TikTok" else GROUP_FACEBOOK

    # Résumé
    bot.send_message(
        message.chat.id,
        f"✅ *Récapitulatif :*\n\n"
        f"👤 Nom : {name}\n"
        f"🌍 Pays : {country}\n"
        f"📱 WhatsApp : {number}\n"
        f"🎯 Plateforme : {platform}\n\n"
        f"💳 *Pour finaliser, clique sur le lien ci-dessous et valide le paiement :*\n{link}\n\n"
        "Après ton paiement :\n"
        "➡️ Tu seras automatiquement redirigé dans un groupe privé.\n"
        "➡️ Tu verras une vidéo qui explique comment obtenir ton compte monétisé.\n"
        "➡️ Un assistant t’aidera jusqu’à la création complète de ton compte.\n\n"
        "⏳ *Ton compte sera prêt en moins de 30 minutes.*",
        parse_mode="Markdown"
    )


# ==========================
# BOT RUN
# ==========================

def run_bot():
    bot.polling(none_stop=True)

threading.Thread(target=run_bot).start()# -*- coding: utf-8 -*-
"""
Bot Telegram Monétisation – Version finale complète
Auteur : Aristide
Fonctionne 24h/24 sur Render (Flask + Threading)
"""

import telebot
from telebot import types
import re
from flask import Flask
import threading

# ==========================
# CONFIGURATION
# ==========================

BOT_TOKEN = "VOTRE_TOKEN_ICI"   # <-- Ton token ici
ADMINS = [123456789]            # <-- Ton ID admin

# Liens Paystack
PAYMENT_LINK_TIKTOK = "https://paystack.com/tiktok_5000"
PAYMENT_LINK_FACEBOOK = "https://paystack.com/facebook_10000"

# Groupes privés
GROUP_TIKTOK = "https://t.me/groupe_tiktok"
GROUP_FACEBOOK = "https://t.me/groupe_facebook"

# Support WhatsApp
SUPPORT_WHATSAPP = "https://wa.me/225XXXXXXXX"

bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}

# ==========================
# SERVEUR FLASK (Render)
# ==========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Telegram fonctionnel."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

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
# VALIDATION NUMÉRO
# ==========================

def is_valid_number(number):
    return re.fullmatch(r"\+?\d{8,15}", number) is not None


# ==========================
# START
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
# SECTIONS
# ==========================

@bot.message_handler(func=lambda m: m.text == "Comment ça marche")
def how_it_works(message):
    bot.send_message(
        message.chat.id,
        "📌 *COMMENT FONCTIONNE LA MONÉTISATION ?*\n\n"
        "Voici tout ce que tu dois savoir avant de commencer :\n\n"
        "1️⃣ *La monétisation TikTok / Facebook est simple, rapide et sécurisée.*\n"
        "Nous t’accompagnons étape par étape pour obtenir un compte monétisé.\n\n"
        "2️⃣ *Tu choisis la plateforme :*\n"
        "- TikTok (5 000 F)\n"
        "- Facebook (10 000 F)\n\n"
        "3️⃣ *Tu fournis :*\n"
        "- Ton nom complet\n"
        "- Ton pays\n"
        "- Ton numéro WhatsApp\n\n"
        "4️⃣ *Tu valides ton paiement via Paystack (100% sécurisé).* 🔒\n\n"
        "5️⃣ *Après paiement, tu es automatiquement redirigé vers un groupe privé Telegram :*\n"
        "✔️ Vidéo tutorielle\n"
        "✔️ Guide complet\n"
        "✔️ Assistant pour t’aider jusqu’à la fin\n\n"
        "6️⃣ *En moins de 30 minutes, ton compte est prêt et monétisé.*\n\n"
        "🎯 Notre objectif : rendre la monétisation accessible à tous.\n"
        "Tu n’as rien à craindre — *on t’accompagne du début jusqu’à la fin.*",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "Support")
def support(message):
    support_btn = types.InlineKeyboardMarkup()
    support_btn.add(types.InlineKeyboardButton("📞 Contacter le support WhatsApp", url=SUPPORT_WHATSAPP))

    bot.send_message(
        message.chat.id,
        "📞 *Support officiel*\nClique ci-dessous pour nous écrire directement sur WhatsApp 👇",
        parse_mode="Markdown",
        reply_markup=support_btn
    )


# ==========================
# MONÉTISATION
# ==========================

@bot.message_handler(func=lambda m: m.text == "Monétisation")
def monetisation(message):
    bot.send_message(
        message.chat.id,
        "Choisis la plateforme que tu veux monétiser 👇",
        reply_markup=monetization_menu()
    )

@bot.message_handler(func=lambda m: m.text in ["TikTok", "Facebook"])
def choose_platform(message):
    user_id = message.from_user.id
    user_data[user_id] = {"platform": message.text}

    bot.send_message(message.chat.id, "Quel est ton nom complet ?")
    bot.register_next_step_handler(message, get_name)

def get_name(message):
    user_id = message.from_user.id
    user_data[user_id]["name"] = message.text

    bot.send_message(message.chat.id, "Ton pays :")
    bot.register_next_step_handler(message, get_country)

def get_country(message):
    user_id = message.from_user.id
    user_data[user_id]["country"] = message.text

    bot.send_message(message.chat.id, "Entre ton numéro WhatsApp (ex : +22507000000)")
    bot.register_next_step_handler(message, get_whatsapp)

def get_whatsapp(message):
    number = message.text
    user_id = message.from_user.id

    if not is_valid_number(number):
        bot.send_message(message.chat.id, "❌ Numéro invalide. Réessaye.")
        return bot.register_next_step_handler(message, get_whatsapp)

    user_data[user_id]["whatsapp"] = number

    platform = user_data[user_id]["platform"]
    name = user_data[user_id]["name"]
    country = user_data[user_id]["country"]

    link = PAYMENT_LINK_TIKTOK if platform == "TikTok" else PAYMENT_LINK_FACEBOOK

    group = GROUP_TIKTOK if platform == "TikTok" else GROUP_FACEBOOK

    # Résumé
    bot.send_message(
        message.chat.id,
        f"✅ *Récapitulatif :*\n\n"
        f"👤 Nom : {name}\n"
        f"🌍 Pays : {country}\n"
        f"📱 WhatsApp : {number}\n"
        f"🎯 Plateforme : {platform}\n\n"
        f"💳 *Pour finaliser, clique sur le lien ci-dessous et valide le paiement :*\n{link}\n\n"
        "Après ton paiement :\n"
        "➡️ Tu seras automatiquement redirigé dans un groupe privé.\n"
        "➡️ Tu verras une vidéo qui explique comment obtenir ton compte monétisé.\n"
        "➡️ Un assistant t’aidera jusqu’à la création complète de ton compte.\n\n"
        "⏳ *Ton compte sera prêt en moins de 30 minutes.*",
        parse_mode="Markdown"
    )


# ==========================
# BOT RUN
# ==========================

def run_bot():
    bot.polling(none_stop=True)

threading.Thread(target=run_bot).start()
