# Déploiement & règles essentielles

## Règles commerciales (à afficher aux clients)
- Vous devez **payer avant** d'accéder au tutoriel.
- **Aucun remboursement.**
- Le bot **n'est pas responsable** si vous ne suivez pas correctement les étapes.

## Admins
- Les admins (liste ADMIN_IDS) sont **exemptés du paiement** et peuvent recevoir le tutoriel sans payer.
- Pour envoyer manuellement le tutoriel : `/sendtutorial <telegram_id>` (commandes réservées aux admins).

## Paystack (Automatique)
- IMPORTANT : Lors de la génération d'un paiement, inclure dans la transaction :
  `metadata: {"telegram_id": "<user_telegram_id>"}` 
  afin que le webhook puisse envoyer automatiquement le tutoriel.
- Configurer le webhook Paystack vers :
  `https://<ton-service>.onrender.com/paystack/webhook`
- Mettre `PAYSTACK_SECRET` dans les variables d'environnement (Render).

## Liens / variables à remplir
- TELEGRAM_TOKEN
- GROUP_CHAT_ID
- ADMIN_IDS (ex: 123456789,987654321)
- PAYSTACK_TIKTOK (lien pour 5000 FCFA)
- PAYSTACK_FACEBOOK (lien pour 8000 FCFA)
- TUTORIAL_LINK
- SUPPORT_LINK
- PAYSTACK_SECRET
