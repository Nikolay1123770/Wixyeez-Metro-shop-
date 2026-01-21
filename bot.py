#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metro Shop Telegram Bot - Ultimate Edition with MiniApp
"""

import os
import sqlite3
import logging
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import parse_qsl

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    MenuButtonWebApp,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

from config import *

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Database Module ---
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def execute(self, query: str, params: tuple = (), fetch: bool = False):
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        data = None
        if fetch:
            data = cur.fetchall()
        else:
            conn.commit()
            data = cur.lastrowid
        conn.close()
        return data
    
    def fetchone(self, query: str, params: tuple = ()):
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def fetchall(self, query: str, params: tuple = ()):
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def init_db(self):
        conn = self.get_connection()
        cur = conn.cursor()
        
        # Categories
        cur.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📦',
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        ''')
        
        # Users
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            pubg_id TEXT,
            phone TEXT,
            registered_at TEXT,
            last_active TEXT,
            balance REAL DEFAULT 0,
            total_spent REAL DEFAULT 0,
            invited_by INTEGER,
            referrals_count INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            vip_until TEXT,
            preferences TEXT DEFAULT '{}'
        )
        ''')
        
        # Products (Enhanced)
        cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            name TEXT NOT NULL,
            short_description TEXT,
            description TEXT,
            price REAL NOT NULL,
            old_price REAL,
            photo TEXT,
            photos TEXT DEFAULT '[]',
            stock INTEGER DEFAULT -1,
            is_active INTEGER DEFAULT 1,
            is_featured INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            sold_count INTEGER DEFAULT 0,
            views_count INTEGER DEFAULT 0,
            rating REAL DEFAULT 0,
            reviews_count INTEGER DEFAULT 0,
            tags TEXT DEFAULT '[]',
            meta TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        )
        ''')
        
        # Cart
        cur.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            added_at TEXT,
            UNIQUE(user_id, product_id)
        )
        ''')
        
        # Favorites
        cur.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            added_at TEXT,
            UNIQUE(user_id, product_id)
        )
        ''')
        
        # Orders (Enhanced)
        cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE,
            user_id INTEGER,
            items TEXT NOT NULL,
            subtotal REAL,
            discount_amount REAL DEFAULT 0,
            balance_used REAL DEFAULT 0,
            total REAL,
            status TEXT DEFAULT 'pending',
            payment_method TEXT,
            payment_screenshot TEXT,
            pubg_id TEXT,
            notes TEXT,
            admin_notes TEXT,
            promo_code TEXT,
            created_at TEXT,
            paid_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            cancelled_at TEXT,
            cancel_reason TEXT
        )
        ''')
        
        # Order Workers
        cur.execute('''
        CREATE TABLE IF NOT EXISTS order_workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            worker_id INTEGER,
            worker_username TEXT,
            status TEXT DEFAULT 'active',
            taken_at TEXT,
            completed_at TEXT,
            earnings REAL DEFAULT 0
        )
        ''')
        
        # Reviews (Enhanced)
        cur.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            product_id INTEGER,
            user_id INTEGER,
            worker_id INTEGER,
            rating INTEGER,
            text TEXT,
            photos TEXT DEFAULT '[]',
            is_verified INTEGER DEFAULT 0,
            is_visible INTEGER DEFAULT 1,
            admin_reply TEXT,
            created_at TEXT
        )
        ''')
        
        # Promocodes (Enhanced)
        cur.execute('''
        CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            type TEXT DEFAULT 'percent',
            value REAL,
            min_order REAL DEFAULT 0,
            max_discount REAL,
            uses_total INTEGER DEFAULT -1,
            uses_per_user INTEGER DEFAULT 1,
            uses_count INTEGER DEFAULT 0,
            valid_from TEXT,
            valid_until TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        ''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS promocode_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER,
            user_id INTEGER,
            order_id INTEGER,
            discount_amount REAL,
            used_at TEXT
        )
        ''')
        
        # Notifications
        cur.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            title TEXT,
            message TEXT,
            data TEXT DEFAULT '{}',
            is_read INTEGER DEFAULT 0,
            created_at TEXT
        )
        ''')
        
        # Analytics
        cur.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            user_id INTEGER,
            data TEXT DEFAULT '{}',
            created_at TEXT
        )
        ''')
        
        # Worker Payouts
        cur.execute('''
        CREATE TABLE IF NOT EXISTS worker_payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER,
            order_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            paid_at TEXT,
            created_at TEXT
        )
        ''')
        
        # Insert default category if empty
        cur.execute('SELECT COUNT(*) FROM categories')
        if cur.fetchone()[0] == 0:
            cur.execute('''
                INSERT INTO categories (name, emoji, description, sort_order, created_at)
                VALUES 
                ('Буст', '🚀', 'Услуги по прокачке', 1, ?),
                ('Валюта', '💰', 'Игровая валюта', 2, ?),
                ('Предметы', '🎁', 'Игровые предметы', 3, ?),
                ('VIP', '👑', 'VIP услуги', 4, ?)
            ''', (now_iso(), now_iso(), now_iso(), now_iso()))
        
        conn.commit()
        conn.close()

# Initialize DB
db = Database(DB_PATH)

def now_iso() -> str:
    return datetime.utcnow().isoformat()

def generate_order_number() -> str:
    import random
    return f"MS{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS

def validate_webapp_data(init_data: str) -> Optional[Dict]:
    """Validate Telegram WebApp initData"""
    try:
        parsed = dict(parse_qsl(init_data))
        check_hash = parsed.pop('hash', '')
        
        data_check_string = '\n'.join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        
        secret_key = hmac.new(
            b'WebAppData',
            TG_BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if calculated_hash == check_hash:
            return json.loads(parsed.get('user', '{}'))
        return None
    except Exception as e:
        logger.error(f"WebApp validation error: {e}")
        return None

# --- Keyboards ---
def get_main_menu(user_id: int = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton('🛍 Каталог', web_app=WebAppInfo(url=f"{WEBAPP_URL}/catalog")),
         KeyboardButton('🛒 Корзина')],
        [KeyboardButton('👤 Профиль'), KeyboardButton('📦 Мои заказы')],
        [KeyboardButton('💝 Избранное'), KeyboardButton('🎮 PUBG ID')],
        [KeyboardButton('📞 Поддержка'), KeyboardButton('📄 Документы')]
    ]
    
    if user_id and is_admin(user_id):
        keyboard.append([KeyboardButton('⚙️ Админ-панель')])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton('📊 Статистика'), KeyboardButton('📦 Все заказы')],
        [KeyboardButton('➕ Добавить товар'), KeyboardButton('📁 Категории')],
        [KeyboardButton('🏷 Промокоды'), KeyboardButton('📢 Рассылка')],
        [KeyboardButton('👥 Пользователи'), KeyboardButton('💰 Выплаты')],
        [KeyboardButton('⬅️ Главное меню')]
    ], resize_keyboard=True)

def get_catalog_inline_keyboard(category_id: int = None) -> InlineKeyboardMarkup:
    categories = db.fetchall('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order')
    
    buttons = []
    for cat in categories:
        emoji = cat['emoji'] or '📦'
        is_selected = '✓ ' if category_id == cat['id'] else ''
        buttons.append([InlineKeyboardButton(
            f"{is_selected}{emoji} {cat['name']}",
            callback_data=f"cat:{cat['id']}"
        )])
    
    buttons.append([
        InlineKeyboardButton('🔍 Поиск', callback_data='search'),
        InlineKeyboardButton('🔥 Популярное', callback_data='popular')
    ])
    
    return InlineKeyboardMarkup(buttons)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args
    
    # Check/Register user
    existing = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    if not existing:
        referrer_id = None
        if args and args[0].startswith('ref'):
            try:
                ref_tg_id = int(args[0][3:])
                if ref_tg_id != user.id:
                    referrer = db.fetchone('SELECT id FROM users WHERE tg_id=?', (ref_tg_id,))
                    if referrer:
                        referrer_id = referrer['id']
                        db.execute('UPDATE users SET referrals_count = referrals_count + 1 WHERE id=?', (referrer_id,))
                        try:
                            await context.bot.send_message(
                                ref_tg_id,
                                f"🎉 По вашей ссылке зарегистрировался {user.first_name}!\n"
                                f"Вы получите {int(REFERRAL_PERCENT*100)}% от его покупок."
                            )
                        except: pass
            except: pass
        
        db.execute('''
            INSERT INTO users (tg_id, username, first_name, last_name, registered_at, last_active, invited_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name, now_iso(), now_iso(), referrer_id))
        
        # Log analytics
        db.execute('INSERT INTO analytics (event_type, user_id, data, created_at) VALUES (?, ?, ?, ?)',
                   ('registration', user.id, json.dumps({'referrer': referrer_id}), now_iso()))
    else:
        db.execute('UPDATE users SET last_active=?, username=? WHERE tg_id=?', 
                   (now_iso(), user.username, user.id))
    
    # Welcome message
    welcome_text = f"""
🎮 **Добро пожаловать в Metro Shop!**

Привет, {user.first_name}! 👋

Мы — лучший сервис для Metro Royale:
• 🚀 Буст и прокачка
• 💰 Игровая валюта
• 🎁 Редкие предметы
• 👑 VIP-услуги

**Нажми кнопку «🛍 Каталог» для просмотра товаров!**
    """
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu(user.id)
    )

async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show catalog with categories"""
    text = """
📦 **Каталог товаров**

Выберите категорию или воспользуйтесь поиском:
    """
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=get_catalog_inline_keyboard()
    )

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show products in category"""
    query = update.callback_query
    await query.answer()
    
    cat_id = int(query.data.split(':')[1])
    
    category = db.fetchone('SELECT * FROM categories WHERE id=?', (cat_id,))
    if not category:
        await query.message.reply_text("Категория не найдена.")
        return
    
    products = db.fetchall('''
        SELECT * FROM products 
        WHERE category_id=? AND is_active=1 
        ORDER BY is_featured DESC, sort_order, sold_count DESC
    ''', (cat_id,))
    
    if not products:
        await query.message.edit_text(
            f"{category['emoji']} **{category['name']}**\n\nВ этой категории пока нет товаров.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('⬅️ Назад', callback_data='catalog')
            ]])
        )
        return
    
    # Send products
    await query.message.edit_text(
        f"{category['emoji']} **{category['name']}**\n\n{category['description'] or ''}\n\n"
        f"Найдено товаров: {len(products)}",
        parse_mode='Markdown'
    )
    
    for product in products[:10]:  # Limit to 10
        await send_product_card(query.message, product, context)

async def send_product_card(message, product: Dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a product card"""
    price_text = f"💰 {product['price']}₽"
    if product['old_price'] and product['old_price'] > product['price']:
        discount = int((1 - product['price'] / product['old_price']) * 100)
        price_text = f"💰 ~~{product['old_price']}₽~~ **{product['price']}₽** (-{discount}%)"
    
    stock_text = ""
    if product['stock'] == 0:
        stock_text = "\n❌ Нет в наличии"
    elif product['stock'] > 0:
        stock_text = f"\n📦 В наличии: {product['stock']} шт."
    
    rating_text = ""
    if product['reviews_count'] > 0:
        stars = '⭐' * int(product['rating'])
        rating_text = f"\n{stars} ({product['rating']:.1f}) • {product['reviews_count']} отзывов"
    
    caption = f"""
🔸 **{product['name']}**

{product['short_description'] or ''}

{price_text}{stock_text}{rating_text}
🛒 Продано: {product['sold_count']}
    """
    
    buttons = [
        [InlineKeyboardButton('🔍 Подробнее', callback_data=f"product:{product['id']}")],
        [
            InlineKeyboardButton('🛒 В корзину', callback_data=f"add_cart:{product['id']}"),
            InlineKeyboardButton('❤️', callback_data=f"toggle_fav:{product['id']}")
        ]
    ]
    
    if product['stock'] == 0:
        buttons = [[InlineKeyboardButton('🔔 Уведомить о поступлении', callback_data=f"notify_stock:{product['id']}")]]
    
    kb = InlineKeyboardMarkup(buttons)
    
    if product['photo']:
        try:
            await message.reply_photo(
                photo=product['photo'],
                caption=caption,
                parse_mode='Markdown',
                reply_markup=kb
            )
        except:
            await message.reply_text(caption, parse_mode='Markdown', reply_markup=kb)
    else:
        await message.reply_text(caption, parse_mode='Markdown', reply_markup=kb)

async def product_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed product info"""
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.split(':')[1])
    product = db.fetchone('SELECT * FROM products WHERE id=?', (product_id,))
    
    if not product:
        await query.message.reply_text("Товар не найден.")
        return
    
    # Update views
    db.execute('UPDATE products SET views_count = views_count + 1 WHERE id=?', (product_id,))
    
    # Get reviews
    reviews = db.fetchall('''
        SELECT r.*, u.username, u.first_name 
        FROM reviews r 
        JOIN users u ON r.user_id = u.tg_id 
        WHERE r.product_id=? AND r.is_visible=1 
        ORDER BY r.created_at DESC LIMIT 3
    ''', (product_id,))
    
    price_text = f"💰 {product['price']}₽"
    if product['old_price'] and product['old_price'] > product['price']:
        discount = int((1 - product['price'] / product['old_price']) * 100)
        price_text = f"💰 ~~{product['old_price']}₽~~ **{product['price']}₽** (-{discount}%)"
    
    caption = f"""
🎯 **{product['name']}**

📝 {product['description'] or product['short_description'] or 'Описание отсутствует'}

{price_text}
📊 Просмотров: {product['views_count']} | Продано: {product['sold_count']}
    """
    
    if reviews:
        caption += "\n\n**Последние отзывы:**\n"
        for r in reviews:
            stars = '⭐' * r['rating']
            name = r['first_name'] or r['username'] or 'Аноним'
            caption += f"{stars} {name}: {r['text'][:50]}...\n"
    
    user = query.from_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    is_fav = db.fetchone('SELECT 1 FROM favorites WHERE user_id=? AND product_id=?', 
                         (user_db['id'], product_id)) if user_db else False
    
    fav_text = '💔 Убрать' if is_fav else '❤️ В избранное'
    
    buttons = [
        [InlineKeyboardButton(f'🛒 Купить за {product["price"]}₽', callback_data=f"buy:{product_id}")],
        [
            InlineKeyboardButton('➕ В корзину', callback_data=f"add_cart:{product_id}"),
            InlineKeyboardButton(fav_text, callback_data=f"toggle_fav:{product_id}")
        ],
        [
            InlineKeyboardButton('📝 Отзывы', callback_data=f"reviews:{product_id}"),
            InlineKeyboardButton('⬅️ Назад', callback_data=f"cat:{product['category_id']}")
        ]
    ]
    
    if is_admin(user.id):
        buttons.append([
            InlineKeyboardButton('✏️ Редактировать', callback_data=f"edit_product:{product_id}"),
            InlineKeyboardButton('🗑 Удалить', callback_data=f"delete_product:{product_id}")
        ])
    
    kb = InlineKeyboardMarkup(buttons)
    
    # Send with all photos if available
    photos = json.loads(product['photos'] or '[]')
    if product['photo']:
        photos.insert(0, product['photo'])
    
    if len(photos) > 1:
        media = [InputMediaPhoto(photos[0], caption=caption, parse_mode='Markdown')]
        for p in photos[1:4]:
            media.append(InputMediaPhoto(p))
        await query.message.reply_media_group(media)
        await query.message.reply_text('Выберите действие:', reply_markup=kb)
    elif photos:
        await query.message.reply_photo(photos[0], caption=caption, parse_mode='Markdown', reply_markup=kb)
    else:
        await query.message.reply_text(caption, parse_mode='Markdown', reply_markup=kb)

async def add_to_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add product to cart"""
    query = update.callback_query
    product_id = int(query.data.split(':')[1])
    
    user = query.from_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await query.answer("Ошибка. Напишите /start", show_alert=True)
        return
    
    product = db.fetchone('SELECT * FROM products WHERE id=? AND is_active=1', (product_id,))
    if not product:
        await query.answer("Товар недоступен", show_alert=True)
        return
    
    if product['stock'] == 0:
        await query.answer("Товар закончился", show_alert=True)
        return
    
    # Check if already in cart
    existing = db.fetchone('SELECT * FROM cart WHERE user_id=? AND product_id=?', 
                           (user_db['id'], product_id))
    
    if existing:
        db.execute('UPDATE cart SET quantity = quantity + 1 WHERE id=?', (existing['id'],))
        await query.answer("✅ Количество увеличено!")
    else:
        db.execute('INSERT INTO cart (user_id, product_id, quantity, added_at) VALUES (?, ?, 1, ?)',
                   (user_db['id'], product_id, now_iso()))
        await query.answer("✅ Добавлено в корзину!")

async def cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's cart"""
    user = update.effective_user
    user_db = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await update.message.reply_text("Ошибка. Напишите /start")
        return
    
    cart_items = db.fetchall('''
        SELECT c.*, p.name, p.price, p.photo 
        FROM cart c 
        JOIN products p ON c.product_id = p.id 
        WHERE c.user_id=?
    ''', (user_db['id'],))
    
    if not cart_items:
        await update.message.reply_text(
            "🛒 **Ваша корзина пуста**\n\nДобавьте товары из каталога!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('🛍 Открыть каталог', callback_data='catalog')
            ]])
        )
        return
    
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    
    text = "🛒 **Ваша корзина:**\n\n"
    buttons = []
    
    for item in cart_items:
        subtotal = item['price'] * item['quantity']
        text += f"• {item['name']}\n"
        text += f"  {item['quantity']} × {item['price']}₽ = {subtotal}₽\n\n"
        buttons.append([
            InlineKeyboardButton(f"➖", callback_data=f"cart_minus:{item['product_id']}"),
            InlineKeyboardButton(f"{item['quantity']}", callback_data="noop"),
            InlineKeyboardButton(f"➕", callback_data=f"cart_plus:{item['product_id']}"),
            InlineKeyboardButton(f"🗑", callback_data=f"cart_remove:{item['product_id']}")
        ])
    
    text += f"━━━━━━━━━━━━━━━\n💰 **Итого: {total}₽**"
    
    if user_db['balance'] > 0:
        text += f"\n💎 Ваш баланс: {user_db['balance']}₽"
    
    buttons.append([InlineKeyboardButton('🗑 Очистить корзину', callback_data='cart_clear')])
    buttons.append([InlineKeyboardButton(f'✅ Оформить заказ на {total}₽', callback_data='checkout')])
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start checkout process"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_db = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    cart_items = db.fetchall('''
        SELECT c.*, p.name, p.price, p.id as product_id
        FROM cart c 
        JOIN products p ON c.product_id = p.id 
        WHERE c.user_id=?
    ''', (user_db['id'],))
    
    if not cart_items:
        await query.message.reply_text("Корзина пуста!")
        return
    
    # Calculate totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
    
    # Apply promo if exists
    discount = 0
    promo_code = context.user_data.get('promo_code')
    if promo_code:
        promo = db.fetchone('SELECT * FROM promocodes WHERE code=? AND is_active=1', (promo_code,))
        if promo:
            if promo['type'] == 'percent':
                discount = subtotal * (promo['value'] / 100)
                if promo['max_discount']:
                    discount = min(discount, promo['max_discount'])
            else:
                discount = promo['value']
    
    # Apply balance
    balance_use = min(user_db['balance'], subtotal - discount)
    
    total = subtotal - discount - balance_use
    
    # Create order
    order_number = generate_order_number()
    items_json = json.dumps([{
        'product_id': item['product_id'],
        'name': item['name'],
        'price': item['price'],
        'quantity': item['quantity']
    } for item in cart_items])
    
    order_id = db.execute('''
        INSERT INTO orders (order_number, user_id, items, subtotal, discount_amount, 
                           balance_used, total, status, pubg_id, promo_code, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, user_db['id'], items_json, subtotal, discount, 
          balance_use, total, 'awaiting_payment', user_db['pubg_id'], promo_code, now_iso()))
    
    # Deduct balance
    if balance_use > 0:
        db.execute('UPDATE users SET balance = balance - ? WHERE id=?', (balance_use, user_db['id']))
    
    # Clear cart
    db.execute('DELETE FROM cart WHERE user_id=?', (user_db['id'],))
    
    # Store order in context
    context.user_data['pending_order_id'] = order_id
    context.user_data.pop('promo_code', None)
    
    # Payment message
    text = f"""
📋 **Заказ #{order_number}**

📦 Товары:
"""
    for item in cart_items:
        text += f"• {item['name']} × {item['quantity']} = {item['price'] * item['quantity']}₽\n"
    
    text += f"\n━━━━━━━━━━━━━━━\n"
    text += f"Подытог: {subtotal}₽\n"
    if discount > 0:
        text += f"🏷 Скидка: -{discount}₽\n"
    if balance_use > 0:
        text += f"💎 Баланс: -{balance_use}₽\n"
    text += f"\n💰 **К оплате: {total}₽**\n"
    
    if total > 0:
        text += f"""
━━━━━━━━━━━━━━━
💳 **Реквизиты для оплаты:**

**{PAYMENT_BANK}:** `{PAYMENT_CARD}`
**Получатель:** {PAYMENT_HOLDER}

📸 После оплаты отправьте скриншот сюда!
"""
        await query.message.reply_text(text, parse_mode='Markdown')
    else:
        # Fully paid by balance
        db.execute('UPDATE orders SET status=?, paid_at=? WHERE id=?', 
                   ('paid', now_iso(), order_id))
        await notify_admins_new_order(context, order_id)
        text += "\n✅ **Заказ оплачен балансом!**\nОжидайте выполнения."
        await query.message.reply_text(text, parse_mode='Markdown')

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user profile"""
    user = update.effective_user
    user_db = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await update.message.reply_text("Напишите /start для регистрации")
        return
    
    # Get stats
    orders_count = db.fetchone('SELECT COUNT(*) as cnt FROM orders WHERE user_id=?', (user_db['id'],))['cnt']
    total_spent = db.fetchone('SELECT SUM(total) as total FROM orders WHERE user_id=? AND status="completed"', 
                              (user_db['id'],))['total'] or 0
    
    ref_link = f"https://t.me/{context.bot.username}?start=ref{user.id}"
    
    text = f"""
👤 **Ваш профиль**

🆔 ID: `{user.id}`
📝 Имя: {user.first_name} {user.last_name or ''}
📅 В сервисе с: {user_db['registered_at'][:10]}

💰 **Баланс: {user_db['balance']}₽**
📦 Заказов: {orders_count}
💸 Потрачено: {total_spent}₽

👥 **Реферальная программа:**
Приглашено: {user_db['referrals_count']} друзей
Ваша ссылка: `{ref_link}`

_Приглашайте друзей и получайте {int(REFERRAL_PERCENT*100)}% от их покупок!_
"""
    
    buttons = [
        [InlineKeyboardButton('🎮 Изменить PUBG ID', callback_data='edit_pubg')],
        [InlineKeyboardButton('📊 История баланса', callback_data='balance_history')],
        [InlineKeyboardButton('🔗 Поделиться ссылкой', switch_inline_query=ref_link)]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user favorites"""
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    favorites = db.fetchall('''
        SELECT p.* FROM favorites f 
        JOIN products p ON f.product_id = p.id 
        WHERE f.user_id=? AND p.is_active=1
        ORDER BY f.added_at DESC
    ''', (user_db['id'],))
    
    if not favorites:
        await update.message.reply_text(
            "💝 **Избранное пусто**\n\nДобавляйте товары в избранное, нажимая ❤️",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(f"💝 **Избранное** ({len(favorites)} товаров):", parse_mode='Markdown')
    
    for product in favorites:
        await send_product_card(update.message, product, context)

async def toggle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle product in favorites"""
    query = update.callback_query
    product_id = int(query.data.split(':')[1])
    
    user = query.from_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    existing = db.fetchone('SELECT id FROM favorites WHERE user_id=? AND product_id=?',
                           (user_db['id'], product_id))
    
    if existing:
        db.execute('DELETE FROM favorites WHERE id=?', (existing['id'],))
        await query.answer("💔 Удалено из избранного")
    else:
        db.execute('INSERT INTO favorites (user_id, product_id, added_at) VALUES (?, ?, ?)',
                   (user_db['id'], product_id, now_iso()))
        await query.answer("❤️ Добавлено в избранное!")

async def my_orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's orders"""
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    orders = db.fetchall('''
        SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10
    ''', (user_db['id'],))
    
    if not orders:
        await update.message.reply_text("📦 У вас пока нет заказов")
        return
    
    status_emoji = {
        'awaiting_payment': '⏳',
        'pending': '🔄',
        'paid': '✅',
        'in_progress': '🔨',
        'delivering': '📦',
        'completed': '✅',
        'cancelled': '❌'
    }
    
    text = "📦 **Ваши заказы:**\n\n"
    buttons = []
    
    for order in orders:
        emoji = status_emoji.get(order['status'], '❓')
        items = json.loads(order['items'])
        items_text = ', '.join([i['name'] for i in items[:2]])
        if len(items) > 2:
            items_text += f" +{len(items)-2}"
        
        text += f"{emoji} **#{order['order_number']}**\n"
        text += f"   {items_text}\n"
        text += f"   💰 {order['total']}₽ • {order['created_at'][:10]}\n\n"
        
        buttons.append([InlineKeyboardButton(
            f"#{order['order_number']}", 
            callback_data=f"order_detail:{order['id']}"
        )])
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle payment screenshots"""
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        return
    
    # Find pending order
    pending_order = db.fetchone('''
        SELECT * FROM orders 
        WHERE user_id=? AND status='awaiting_payment' 
        ORDER BY created_at DESC LIMIT 1
    ''', (user_db['id'],))
    
    if not pending_order:
        return
    
    file_id = update.message.photo[-1].file_id
    
    db.execute('''
        UPDATE orders SET status=?, payment_screenshot=? WHERE id=?
    ''', ('pending', file_id, pending_order['id']))
    
    await update.message.reply_text(
        "✅ **Скриншот получен!**\n\n"
        "Ожидайте подтверждения оплаты администратором.",
        parse_mode='Markdown',
        reply_markup=get_main_menu(user.id)
    )
    
    # Notify admins
    await notify_admins_new_order(context, pending_order['id'], file_id)

async def notify_admins_new_order(context: ContextTypes.DEFAULT_TYPE, order_id: int, screenshot: str = None) -> None:
    """Notify admins about new order"""
    order = db.fetchone('SELECT * FROM orders WHERE id=?', (order_id,))
    user = db.fetchone('SELECT * FROM users WHERE id=?', (order['user_id'],))
    
    items = json.loads(order['items'])
    items_text = '\n'.join([f"• {i['name']} × {i['quantity']} = {i['price'] * i['quantity']}₽" for i in items])
    
    text = f"""
🆕 **Новый заказ #{order['order_number']}**

👤 Покупатель: @{user['username'] or 'Нет username'} ({user['tg_id']})
🎮 PUBG ID: {order['pubg_id'] or 'Не указан'}

📦 **Товары:**
{items_text}

💰 Подытог: {order['subtotal']}₽
"""
    if order['discount_amount'] > 0:
        text += f"🏷 Скидка: -{order['discount_amount']}₽\n"
    if order['balance_used'] > 0:
        text += f"💎 Баланс: -{order['balance_used']}₽\n"
    text += f"\n**К оплате: {order['total']}₽**"
    
    buttons = [
        [
            InlineKeyboardButton('✅ Подтвердить', callback_data=f"admin_confirm:{order_id}"),
            InlineKeyboardButton('❌ Отклонить', callback_data=f"admin_reject:{order_id}")
        ],
        [InlineKeyboardButton('📞 Связаться', url=f"tg://user?id={user['tg_id']}")]
    ]
    kb = InlineKeyboardMarkup(buttons)
    
    if screenshot:
        await context.bot.send_photo(ADMIN_CHAT_ID, screenshot, caption=text, 
                                     parse_mode='Markdown', reply_markup=kb)
    else:
        await context.bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown', reply_markup=kb)

async def admin_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin order actions"""
    query = update.callback_query
    await query.answer()
    
    action, order_id = query.data.split(':')
    order_id = int(order_id)
    
    order = db.fetchone('SELECT * FROM orders WHERE id=?', (order_id,))
    user = db.fetchone('SELECT * FROM users WHERE id=?', (order['user_id'],))
    
    if action == 'admin_confirm':
        db.execute('UPDATE orders SET status=?, paid_at=? WHERE id=?', ('paid', now_iso(), order_id))
        
        # Handle referral bonus
        if user['invited_by'] and order['total'] > 0:
            bonus = order['total'] * REFERRAL_PERCENT
            db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (bonus, user['invited_by']))
            referrer = db.fetchone('SELECT tg_id FROM users WHERE id=?', (user['invited_by'],))
            if referrer:
                try:
                    await context.bot.send_message(
                        referrer['tg_id'],
                        f"💰 Вам начислено +{bonus:.2f}₽ за покупку реферала!"
                    )
                except: pass
        
        # Notify user
        try:
            await context.bot.send_message(
                user['tg_id'],
                f"✅ **Оплата подтверждена!**\n\nЗаказ #{order['order_number']} принят в работу.",
                parse_mode='Markdown'
            )
        except: pass
        
        await query.message.edit_caption(
            caption=query.message.caption + "\n\n✅ **ОПЛАТА ПОДТВЕРЖДЕНА**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🟢 Взять', callback_data=f"worker_take:{order_id}")],
                [
                    InlineKeyboardButton('▶️ В работе', callback_data=f"status_progress:{order_id}"),
                    InlineKeyboardButton('📦 Выдача', callback_data=f"status_deliver:{order_id}"),
                    InlineKeyboardButton('✅ Готово', callback_data=f"status_done:{order_id}")
                ]
            ])
        )
        
    elif action == 'admin_reject':
        # Refund balance
        if order['balance_used'] > 0:
            db.execute('UPDATE users SET balance = balance + ? WHERE id=?', 
                       (order['balance_used'], user['id']))
        
        db.execute('UPDATE orders SET status=?, cancelled_at=?, cancel_reason=? WHERE id=?',
                   ('cancelled', now_iso(), 'Payment rejected', order_id))
        
        try:
            await context.bot.send_message(
                user['tg_id'],
                f"❌ Заказ #{order['order_number']} отклонен.\n"
                f"Баланс возвращен." if order['balance_used'] > 0 else ""
            )
        except: pass
        
        await query.message.edit_caption(
            caption=query.message.caption + "\n\n❌ **ОТКЛОНЕНО**",
            parse_mode='Markdown'
        )

# --- Text Router ---
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text messages"""
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    user = update.effective_user
    
    # Menu buttons
    if text == '🛒 Корзина':
        await cart_handler(update, context)
    elif text == '👤 Профиль':
        await profile_handler(update, context)
    elif text == '📦 Мои заказы':
        await my_orders_handler(update, context)
    elif text == '💝 Избранное':
        await favorites_handler(update, context)
    elif text == '🎮 PUBG ID':
        context.user_data['awaiting_pubg'] = True
        await update.message.reply_text(
            "🎮 Введите ваш PUBG ID:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton('⬅️ Отмена')]], resize_keyboard=True)
        )
    elif text == '📞 Поддержка':
        await update.message.reply_text(
            f"📞 **Поддержка**\n\nНаписать: {SUPPORT_CONTACT_USER}",
            parse_mode='Markdown'
        )
    elif text == '📄 Документы':
        await update.message.reply_text(
            "📄 **Документы**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📜 Пользовательское соглашение', callback_data='doc_terms')],
                [InlineKeyboardButton('🔒 Политика конфиденциальности', callback_data='doc_privacy')]
            ])
        )
    elif text == '⚙️ Админ-панель' and is_admin(user.id):
        await update.message.reply_text("⚙️ Админ-панель:", reply_markup=get_admin_keyboard())
    elif text == '⬅️ Главное меню' or text == '⬅️ Отмена':
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_menu(user.id))
    elif context.user_data.get('awaiting_pubg'):
        db.execute('UPDATE users SET pubg_id=? WHERE tg_id=?', (text, user.id))
        context.user_data.pop('awaiting_pubg')
        await update.message.reply_text(
            f"✅ PUBG ID сохранен: `{text}`",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user.id)
        )
    else:
        await update.message.reply_text("Используйте меню для навигации", reply_markup=get_main_menu(user.id))

# --- Build App ---
def build_app():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler('start', start))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r'^cat:'))
    app.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r'^product:'))
    app.add_handler(CallbackQueryHandler(add_to_cart_callback, pattern=r'^add_cart:'))
    app.add_handler(CallbackQueryHandler(toggle_favorite_callback, pattern=r'^toggle_fav:'))
    app.add_handler(CallbackQueryHandler(checkout_callback, pattern=r'^checkout'))
    app.add_handler(CallbackQueryHandler(admin_order_action, pattern=r'^admin_'))
    app.add_handler(CallbackQueryHandler(leave_review_callback, pattern=r'^leave_review:'))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    return app

async def leave_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # Implement review system

if __name__ == "__main__":
    print("🚀 Starting Metro Shop Bot...")
    application = build_app()
    application.run_polling()