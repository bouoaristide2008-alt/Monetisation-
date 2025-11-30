# -*- coding: utf-8 -*-
"""
Bot Telegram Monétisation — Pack complet
- Webhook Flask (Render)
- Bouton "⬅️ Menu" (toujours visible pendant le formulaire)
- Bouton "↩️ Retour" (retour vers l'étape précédente)
- Flow: plateforme -> nom -> pays -> whatsapp -> récap -> paiement
- Admin notifié à chaque demande
- Aucun variable d'environnement requise (tout en dur ci-dessous)
"""

import os
import re
from flask import Flask, request
import telebot
from telebot import types

# ---------------------------
# CONFIGURATION (mettre tes infos ici)
# ---------------------------
BOT_TOKEN = "8351407177:AAERierzxpvTwSb5WwlJf_TncwbXhE6xCA0"
ADMINS = [6357925694]

# Liens Paystack fournis
PAYMENT_LINK_TIKTOK = "https://paystack.shop/pay/9-9a5jxmgd"
PAYMENT_LINK_FACEBOOK = "https://paystack.shop/pay/21xb9p3kbn"

# Numéro support WhatsApp (avec indicatif)
SUPPORT_NUMBER = "2250501436408"
SUPPORT_LINK = f"https://wa.me/{SUPPORT_NUMBER}"

# (optionnel) liens groupes — non envoyés au user; Paystack redirige vers le groupe
GROUP_TIKTOK = "https://t.me/groupe_tiktok"
GROUP_FACEBOOK = "https://t.me/groupe_facebook"

# ---------------------------
# INITIALISATION
# ---------------------------
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Stockage de l'état utilisateur:
# user_state[user_id] = {
#   "step": "platform" | "name" | "country" | "phone" | None,
#   "platform": "TikTok"|"Facebook",
#   "name": str,
#   "country": str,
#   "phone": str
# }
user_state = {}

# ---------------------------
# UTILITAIRES
# ---------------------------
def main_menu_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("Monétisation"),
        types.KeyboardButton("Comment ça marche"),
        types.KeyboardButton("Support")
    )
    return markup

def monetization_menu_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("TikTok"),
        types.KeyboardButton("Facebook"),
        types.KeyboardButton("⬅️ Menu"),      # retour menu toujours visible
        types.KeyboardButton("↩️ Retour")     # retour étape précédente
    )
    return markup

def form_step_markup():
    # boutons à afficher pendant la saisie (retours)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("⬅️ Menu"), types.KeyboardButton("↩️ Retour"))
    return markup

def is_valid_ivory_number(number: str) -> bool:
    """
    Valide formats +225XXXXXXXX (8 chiffres après +225) ou 0XXXXXXXX (8 chiffres).
    Exemples acceptés: +22507123456 -> +225 + 8 digits ; 07123456 -> 0 + 8 digits
    """
    n = re.sub(r"[ \-]", "", number.strip())
    return re.fullmatch(r"(?:\+225\d{8}|0\d{8})", n) is not None

def notify_admins(text: str):
    for a in ADMINS:
        try:
            bot.send_message(a, text)
        except Exception:
            pass

# ---------------------------
# FLASK / WEBHOOK ENDPOINTS
# ---------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot Telegram — webhook ready", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    url = f"https://{request.host}/{BOT_TOKEN}"
    bot.remove_webhook()
    ok = bot.set_webhook(url=url)
    return f"Webhook activé -> {url} (result={ok})"

# ---------------------------
# HANDLERS BOT
# ---------------------------

@bot.message_handler(commands=["start"])
def handle_start(message):
    user_id = message.chat.id
    # reset context
    if user_id in user_state:
        del user_state[user_id]
    bot.send_message(
        user_id,
        f"👋 Bonjour {message.from_user.first_name} !\n\nBienvenue dans notre service de monétisation.",
        reply_markup=main_menu_markup()
    )

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    user_id = message.chat.id
    text = (message.text or "").strip()

    # ----- Bouton Retour au MENU global
    if text == "⬅️ Menu":
        if user_id in user_state:
            del user_state[user_id]
        bot.send_message(user_id, "Retour au menu principal :", reply_markup=main_menu_markup())
        return

    # ----- Bouton Retour étape précédente
    if text == "↩️ Retour":
        if user_id not in user_state:
            bot.send_message(user_id, "Rien à revenir. Voilà le menu :", reply_markup=main_menu_markup())
            return
        # déterminer étape précédente
        step = user_state[user_id].get("step")
        # mapping previous
        if step == "name":
            # previous = platform choice -> show monetization menu
            user_state.pop(user_id, None)
            bot.send_message(user_id, "Choisis la plateforme :", reply_markup=monetization_menu_markup())
            return
        elif step == "country":
            # go back to asking name
            user_state[user_id]["step"] = "name"
            bot.send_message(user_id, "Reviens en arrière — Entre à nouveau ton *nom complet* :", parse_mode="Markdown", reply_markup=form_step_markup())
            return
        elif step == "phone":
            user_state[user_id]["step"] = "country"
            bot.send_message(user_id, "Reviens en arrière — Entre ton *pays* :", parse_mode="Markdown", reply_markup=form_step_markup())
            return
        else:
            bot.send_message(user_id, "Impossible de revenir plus loin. Menu principal :", reply_markup=main_menu_markup())
            return

    # ----- MENU PRINCIPAL buttons
    if text == "Monétisation":
        bot.send_message(user_id, "Choisis la plateforme :", reply_markup=monetization_menu_markup())
        return

    if text == "Comment ça marche":
        bot.send_message(
            user_id,
            "📌 *COMMENT FONCTIONNE LA MONÉTISATION ?*\n\n"
            "1️⃣ Choisis TikTok (5 000 F) ou Facebook (10 000 F)\n"
            "2️⃣ Fournis ton nom, ton pays et ton WhatsApp\n"
            "3️⃣ Valide le paiement via Paystack (100% sécurisé)\n"
            "4️⃣ Paystack redirige automatiquement vers le groupe privé\n"
            "5️⃣ Dans le groupe : vidéo tutorielle + assistance\n\n"
            "🎯 Résultat : ton compte est prêt en ~30 minutes.",
            parse_mode="Markdown",
            reply_markup=main_menu_markup()
        )
        return

    if text == "Support":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Contacter le support WhatsApp", url=SUPPORT_LINK))
        bot.send_message(user_id, "📞 Support 24h/24 — clique ci-dessous :", reply_markup=kb)
        return

    # ----- Choix plateforme (démarre le formulaire)
    if text in ("TikTok", "Facebook"):
        user_state[user_id] = {"platform": text, "step": "name"}
        bot.send_message(user_id, "🎤 Très bien. Entre ton *nom complet* :", parse_mode="Markdown", reply_markup=form_step_markup())
        return

    # ----- Si l'utilisateur est dans un formulaire, gèrer les étapes
    if user_id in user_state:
        ctx = user_state[user_id]
        step = ctx.get("step")

        # Étape : nom attendu
        if step == "name":
            ctx["name"] = text
            ctx["step"] = "country"
            bot.send_message(user_id, "🌍 Très bien. Maintenant entre ton *pays* :", parse_mode="Markdown", reply_markup=form_step_markup())
            return

        # Étape : pays attendu
        if step == "country":
            ctx["country"] = text
            ctx["step"] = "phone"
            bot.send_message(user_id, "📱 Ok. Maintenant entre ton *numéro WhatsApp* (ex : +22507123456 ou 07123456) :", parse_mode="Markdown", reply_markup=form_step_markup())
            return

        # Étape : numéro attendu
        if step == "phone":
            phone_raw = text.replace(" ", "").replace("-", "")
            if not is_valid_ivory_number(phone_raw):
                bot.send_message(user_id, "❌ Numéro invalide. Format accepté : +225XXXXXXXX ou 0XXXXXXXX. Réessayez.", reply_markup=form_step_markup())
                return
            ctx["phone"] = phone_raw

            # Récap & paiement
            platform = ctx.get("platform")
            name = ctx.get("name")
            country = ctx.get("country")
            phone = ctx.get("phone")
            price = "5 000 F CFA" if platform == "TikTok" else "10 000 F CFA"
            pay_link = PAYMENT_LINK_TIKTOK if platform == "TikTok" else PAYMENT_LINK_FACEBOOK

            recap_text = (
                f"🎉 *Récapitulatif*\n\n"
                f"👤 Nom : {name}\n"
                f"🌍 Pays : {country}\n"
                f"📱 WhatsApp : {phone}\n"
                f"🎯 Plateforme : *{platform}*\n"
                f"💵 Prix : *{price}*\n\n"
                "💳 *Étape finale : Validez votre paiement via Paystack.*\n"
                "👉 Après paiement, Paystack redirigera automatiquement vers le groupe privé Telegram où tu trouveras la vidéo et l'assistance."
            )

            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("💳 Payer maintenant", url=pay_link))

            bot.send_message(user_id, recap_text, parse_mode="Markdown", reply_markup=kb)

            # Notifier admins
            admin_msg = (
                f"🆕 NOUVELLE DEMANDE\n"
                f"Plateforme: {platform}\nNom: {name}\nPays: {country}\nWhatsApp: {phone}"
            )
            notify_admins(admin_msg)

            # Nettoyage contexte
            del user_state[user_id]
            # envoyer menu principal
            bot.send_message(user_id, "Merci ! Retour au menu principal :", reply_markup=main_menu_markup())
            return

    # ----- sinon : aide / menu
    bot.send_message(user_id, "Je n'ai pas compris. Utilise le menu ci-dessous :", reply_markup=main_menu_markup())

# ---------------------------
# RUN (Render: PORT fourni via env)
# ---------------------------
if __name__ == "__main__":
    # Gunicorn lira bot:app, ce block est pour exécution locale
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
