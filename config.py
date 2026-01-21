# config.py
import os

# Bot Settings
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '8269807126:AAFLKT39qdkKR81df5nEYuCFIk3z8kdZbSo')
OWNER_ID = int(os.getenv('OWNER_ID', '8473513085'))
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '-1003448809517'))
DB_PATH = os.getenv('DB_PATH', 'metro_shop.db')

# WebApp Settings
WEBAPP_HOST = os.getenv('WEBAPP_HOST', '0.0.0.0')
WEBAPP_PORT = int(os.getenv('WEBAPP_PORT', '1111'))
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://wixyeezmetroshop.bothost.ru')  # Ваш домен с HTTPS

# Support
SUPPORT_CONTACT_USER = os.getenv('SUPPORT_CONTACT', '@wixyeez')

# Admin IDs
ADMIN_IDS = [OWNER_ID]
if os.getenv('ADMIN_IDS'):
    ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS').split(',') if x.strip()]

# Business Settings
MAX_WORKERS_PER_ORDER = int(os.getenv('MAX_WORKERS_PER_ORDER', '3'))
WORKER_PERCENT = float(os.getenv('WORKER_PERCENT', '0.7'))
REFERRAL_PERCENT = float(os.getenv('REFERRAL_PERCENT', '0.05'))

# Payment Details
PAYMENT_CARD = "+79002535363"
PAYMENT_HOLDER = "Николай М"
PAYMENT_BANK = "Сбербанк"