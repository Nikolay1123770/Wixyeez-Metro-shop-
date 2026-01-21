#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metro Shop Bot - Single File Edition
Для деплоя на Python хостинг
"""

import os
import sqlite3
import logging
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
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

# ============== CONFIGURATION ==============
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '8269807126:AAFN7bjp1094IVasTTkeYL3hkz4SYNgiQCY')
OWNER_ID = int(os.getenv('OWNER_ID', '8473513085'))
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '-1003448809517'))
DB_PATH = os.getenv('DB_PATH', 'metro_shop.db')
SUPPORT_CONTACT = os.getenv('SUPPORT_CONTACT', '@wixyeez')
WEBAPP_URL = os.getenv('WEBAPP_URL', '')  # Если есть MiniApp

ADMIN_IDS = [OWNER_ID]
WORKER_PERCENT = 0.7
REFERRAL_PERCENT = 0.05

# Payment
PAYMENT_CARD = "+79002535363"
PAYMENT_HOLDER = "Николай М"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== DATABASE ==============
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Categories
    cur.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        emoji TEXT DEFAULT '📦',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )''')
    
    # Users
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        pubg_id TEXT,
        balance REAL DEFAULT 0,
        invited_by INTEGER,
        referrals_count INTEGER DEFAULT 0,
        registered_at TEXT
    )''')
    
    # Products
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        old_price REAL,
        photo TEXT,
        stock INTEGER DEFAULT -1,
        is_active INTEGER DEFAULT 1,
        sold_count INTEGER DEFAULT 0,
        created_at TEXT
    )''')
    
    # Cart
    cur.execute('''CREATE TABLE IF NOT EXISTS cart (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        quantity INTEGER DEFAULT 1,
        UNIQUE(user_id, product_id)
    )''')
    
    # Favorites
    cur.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        UNIQUE(user_id, product_id)
    )''')
    
    # Orders
    cur.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE,
        user_id INTEGER,
        items TEXT,
        total REAL,
        balance_used REAL DEFAULT 0,
        status TEXT DEFAULT 'pending',
        payment_screenshot TEXT,
        pubg_id TEXT,
        created_at TEXT
    )''')
    
    # Order Workers
    cur.execute('''CREATE TABLE IF NOT EXISTS order_workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        worker_id INTEGER,
        worker_username TEXT,
        taken_at TEXT
    )''')
    
    # Promocodes
    cur.execute('''CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY,
        discount_percent INTEGER,
        uses_left INTEGER DEFAULT -1,
        is_active INTEGER DEFAULT 1
    )''')
    
    # Default categories
    cur.execute('SELECT COUNT(*) FROM categories')
    if cur.fetchone()[0] == 0:
        cur.executemany('INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)', [
            ('🚀 Буст', '🚀', 1),
            ('💰 Валюта', '💰', 2),
            ('🎁 Предметы', '🎁', 3),
            ('👑 VIP', '👑', 4),
        ])
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

def db_query(query: str, params: tuple = (), fetch: bool = False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, params)
    result = None
    if fetch:
        result = [dict(row) for row in cur.fetchall()]
    else:
        conn.commit()
        result = cur.lastrowid
    conn.close()
    return result

def db_one(query: str, params: tuple = ()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def now_iso():
    return datetime.utcnow().isoformat()

def gen_order_num():
    import random
    return f"MS{datetime.now().strftime('%y%m%d')}{random.randint(1000,9999)}"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS

# ============== KEYBOARDS ==============
def main_menu(user_id: int = None):
    buttons = [
        [KeyboardButton('🛍 Каталог'), KeyboardButton('🛒 Корзина')],
        [KeyboardButton('👤 Профиль'), KeyboardButton('📦 Мои заказы')],
        [KeyboardButton('❤️ Избранное'), KeyboardButton('🎮 PUBG ID')],
        [KeyboardButton('📞 Поддержка')]
    ]
    if user_id and is_admin(user_id):
        buttons.append([KeyboardButton('⚙️ Админка')])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def admin_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton('📊 Статистика'), KeyboardButton('📦 Все заказы')],
        [KeyboardButton('➕ Добавить товар'), KeyboardButton('📁 Категории')],
        [KeyboardButton('🏷 Промокоды'), KeyboardButton('📢 Рассылка')],
        [KeyboardButton('⬅️ Назад')]
    ], resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup([[KeyboardButton('❌ Отмена')]], resize_keyboard=True)

# ============== HANDLERS ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    existing = db_one('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    if not existing:
        referrer_id = None
        if args and args[0].startswith('ref'):
            try:
                ref_tg = int(args[0][3:])
                if ref_tg != user.id:
                    ref = db_one('SELECT id FROM users WHERE tg_id=?', (ref_tg,))
                    if ref:
                        referrer_id = ref['id']
                        db_query('UPDATE users SET referrals_count = referrals_count + 1 WHERE id=?', (referrer_id,))
                        try:
                            await context.bot.send_message(ref_tg, f"🎉 По вашей ссылке зарегистрировался {user.first_name}!")
                        except: pass
            except: pass
        
        db_query('''INSERT INTO users (tg_id, username, first_name, registered_at, invited_by) 
                    VALUES (?, ?, ?, ?, ?)''',
                 (user.id, user.username, user.first_name, now_iso(), referrer_id))
    
    await update.message.reply_text(
        f"🎮 **Добро пожаловать в Metro Shop!**\n\n"
        f"Привет, {user.first_name}! 👋\n\n"
        f"Мы — лучший сервис для Metro Royale:\n"
        f"• 🚀 Буст и прокачка\n"
        f"• 💰 Игровая валюта\n"
        f"• 🎁 Редкие предметы\n\n"
        f"Нажми **🛍 Каталог** для просмотра!",
        parse_mode='Markdown',
        reply_markup=main_menu(user.id)
    )

async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = db_query('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order', fetch=True)
    
    buttons = []
    for cat in categories:
        buttons.append([InlineKeyboardButton(f"{cat['emoji']} {cat['name']}", callback_data=f"cat:{cat['id']}")])
    buttons.append([InlineKeyboardButton('🔥 Все товары', callback_data='cat:all')])
    
    await update.message.reply_text(
        "📦 **Каталог**\n\nВыберите категорию:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cat_id = query.data.split(':')[1]
    
    if cat_id == 'all':
        products = db_query('SELECT * FROM products WHERE is_active=1 ORDER BY sold_count DESC', fetch=True)
        title = "🔥 Все товары"
    else:
        products = db_query('SELECT * FROM products WHERE category_id=? AND is_active=1', (int(cat_id),), fetch=True)
        cat = db_one('SELECT * FROM categories WHERE id=?', (int(cat_id),))
        title = f"{cat['emoji']} {cat['name']}" if cat else "Категория"
    
    if not products:
        await query.message.edit_text(
            f"{title}\n\n❌ Товаров нет",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='catalog')]])
        )
        return
    
    await query.message.edit_text(f"{title}\n\nНайдено: {len(products)} товаров")
    
    for p in products[:10]:
        await send_product_card(query.message, p)

async def send_product_card(message, product: dict):
    price_text = f"💰 **{product['price']}₽**"
    if product.get('old_price') and product['old_price'] > product['price']:
        discount = int((1 - product['price'] / product['old_price']) * 100)
        price_text = f"~~{product['old_price']}₽~~ **{product['price']}₽** (-{discount}%)"
    
    caption = f"🔸 **{product['name']}**\n\n{price_text}\n🛒 Продано: {product['sold_count']}"
    
    buttons = [
        [InlineKeyboardButton('🔍 Подробнее', callback_data=f"prod:{product['id']}")],
        [
            InlineKeyboardButton('🛒 В корзину', callback_data=f"cart_add:{product['id']}"),
            InlineKeyboardButton('❤️', callback_data=f"fav:{product['id']}")
        ]
    ]
    
    if product.get('photo'):
        try:
            await message.reply_photo(product['photo'], caption=caption, parse_mode='Markdown',
                                     reply_markup=InlineKeyboardMarkup(buttons))
            return
        except: pass
    
    await message.reply_text(caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def product_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pid = int(query.data.split(':')[1])
    p = db_one('SELECT * FROM products WHERE id=?', (pid,))
    
    if not p:
        await query.message.reply_text("❌ Товар не найден")
        return
    
    price_text = f"💰 **{p['price']}₽**"
    if p.get('old_price') and p['old_price'] > p['price']:
        discount = int((1 - p['price'] / p['old_price']) * 100)
        price_text = f"~~{p['old_price']}₽~~ **{p['price']}₽** (-{discount}%)"
    
    text = f"""
🎯 **{p['name']}**

📝 {p.get('description') or 'Описание отсутствует'}

{price_text}
📦 Продано: {p['sold_count']}
"""
    
    buttons = [
        [InlineKeyboardButton(f"🛒 Купить за {p['price']}₽", callback_data=f"buy:{pid}")],
        [
            InlineKeyboardButton('➕ В корзину', callback_data=f"cart_add:{pid}"),
            InlineKeyboardButton('❤️ Избранное', callback_data=f"fav:{pid}")
        ],
        [InlineKeyboardButton('⬅️ Назад', callback_data='catalog')]
    ]
    
    if is_admin(query.from_user.id):
        buttons.append([
            InlineKeyboardButton('✏️ Изменить', callback_data=f"edit_prod:{pid}"),
            InlineKeyboardButton('🗑 Удалить', callback_data=f"del_prod:{pid}")
        ])
    
    if p.get('photo'):
        try:
            await query.message.reply_photo(p['photo'], caption=text, parse_mode='Markdown',
                                           reply_markup=InlineKeyboardMarkup(buttons))
            return
        except: pass
    
    await query.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def add_to_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = int(query.data.split(':')[1])
    
    user = db_one('SELECT id FROM users WHERE tg_id=?', (query.from_user.id,))
    if not user:
        await query.answer("❌ Ошибка", show_alert=True)
        return
    
    existing = db_one('SELECT * FROM cart WHERE user_id=? AND product_id=?', (user['id'], pid))
    
    if existing:
        db_query('UPDATE cart SET quantity = quantity + 1 WHERE id=?', (existing['id'],))
    else:
        db_query('INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, 1)', (user['id'], pid))
    
    await query.answer("✅ Добавлено в корзину!")

async def toggle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = int(query.data.split(':')[1])
    
    user = db_one('SELECT id FROM users WHERE tg_id=?', (query.from_user.id,))
    if not user:
        await query.answer("❌ Ошибка", show_alert=True)
        return
    
    existing = db_one('SELECT id FROM favorites WHERE user_id=? AND product_id=?', (user['id'], pid))
    
    if existing:
        db_query('DELETE FROM favorites WHERE id=?', (existing['id'],))
        await query.answer("💔 Удалено из избранного")
    else:
        db_query('INSERT INTO favorites (user_id, product_id) VALUES (?, ?)', (user['id'], pid))
        await query.answer("❤️ Добавлено в избранное!")

async def cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db_one('SELECT * FROM users WHERE tg_id=?', (update.effective_user.id,))
    if not user:
        await update.message.reply_text("❌ Ошибка")
        return
    
    items = db_query('''
        SELECT c.*, p.name, p.price, p.photo 
        FROM cart c JOIN products p ON c.product_id = p.id 
        WHERE c.user_id=?
    ''', (user['id'],), fetch=True)
    
    if not items:
        await update.message.reply_text(
            "🛒 **Корзина пуста**\n\nДобавьте товары из каталога!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🛍 Каталог', callback_data='catalog')]])
        )
        return
    
    total = sum(i['price'] * i['quantity'] for i in items)
    
    text = "🛒 **Ваша корзина:**\n\n"
    buttons = []
    
    for item in items:
        text += f"• {item['name']}\n  {item['quantity']} × {item['price']}₽ = {item['price'] * item['quantity']}₽\n\n"
        buttons.append([
            InlineKeyboardButton("➖", callback_data=f"cart_minus:{item['product_id']}"),
            InlineKeyboardButton(f"{item['quantity']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart_plus:{item['product_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"cart_del:{item['product_id']}")
        ])
    
    text += f"━━━━━━━━━━━━━━\n💰 **Итого: {total}₽**"
    
    if user['balance'] > 0:
        text += f"\n💎 Ваш баланс: {user['balance']}₽"
    
    buttons.append([InlineKeyboardButton('🗑 Очистить', callback_data='cart_clear')])
    buttons.append([InlineKeyboardButton(f'✅ Оформить ({total}₽)', callback_data='checkout')])
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def cart_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    
    user = db_one('SELECT id FROM users WHERE tg_id=?', (query.from_user.id,))
    if not user:
        await query.answer("❌ Ошибка")
        return
    
    if action == 'cart_clear':
        db_query('DELETE FROM cart WHERE user_id=?', (user['id'],))
        await query.answer("🗑 Корзина очищена")
        await query.message.edit_text("🛒 Корзина пуста")
        return
    
    if action.startswith('cart_plus:'):
        pid = int(action.split(':')[1])
        db_query('UPDATE cart SET quantity = quantity + 1 WHERE user_id=? AND product_id=?', (user['id'], pid))
        await query.answer("➕")
    elif action.startswith('cart_minus:'):
        pid = int(action.split(':')[1])
        item = db_one('SELECT quantity FROM cart WHERE user_id=? AND product_id=?', (user['id'], pid))
        if item and item['quantity'] > 1:
            db_query('UPDATE cart SET quantity = quantity - 1 WHERE user_id=? AND product_id=?', (user['id'], pid))
        else:
            db_query('DELETE FROM cart WHERE user_id=? AND product_id=?', (user['id'], pid))
        await query.answer("➖")
    elif action.startswith('cart_del:'):
        pid = int(action.split(':')[1])
        db_query('DELETE FROM cart WHERE user_id=? AND product_id=?', (user['id'], pid))
        await query.answer("🗑 Удалено")
    
    # Refresh cart view
    items = db_query('''
        SELECT c.*, p.name, p.price FROM cart c 
        JOIN products p ON c.product_id = p.id WHERE c.user_id=?
    ''', (user['id'],), fetch=True)
    
    if not items:
        await query.message.edit_text("🛒 Корзина пуста")
        return
    
    total = sum(i['price'] * i['quantity'] for i in items)
    text = "🛒 **Корзина:**\n\n"
    buttons = []
    
    for item in items:
        text += f"• {item['name']} ({item['quantity']}×{item['price']}₽)\n"
        buttons.append([
            InlineKeyboardButton("➖", callback_data=f"cart_minus:{item['product_id']}"),
            InlineKeyboardButton(f"{item['quantity']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart_plus:{item['product_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"cart_del:{item['product_id']}")
        ])
    
    text += f"\n💰 **Итого: {total}₽**"
    buttons.append([InlineKeyboardButton(f'✅ Оформить ({total}₽)', callback_data='checkout')])
    
    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db_one('SELECT * FROM users WHERE tg_id=?', (query.from_user.id,))
    items = db_query('''
        SELECT c.*, p.name, p.price, p.id as product_id 
        FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id=?
    ''', (user['id'],), fetch=True)
    
    if not items:
        await query.message.reply_text("❌ Корзина пуста")
        return
    
    total = sum(i['price'] * i['quantity'] for i in items)
    balance_use = min(user['balance'], total)
    final = total - balance_use
    
    # Create order
    order_num = gen_order_num()
    items_json = json.dumps([{'id': i['product_id'], 'name': i['name'], 'price': i['price'], 'qty': i['quantity']} for i in items])
    
    order_id = db_query('''
        INSERT INTO orders (order_number, user_id, items, total, balance_used, status, pubg_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_num, user['id'], items_json, final, balance_use, 'awaiting_payment', user.get('pubg_id'), now_iso()))
    
    # Deduct balance
    if balance_use > 0:
        db_query('UPDATE users SET balance = balance - ? WHERE id=?', (balance_use, user['id']))
    
    # Clear cart
    db_query('DELETE FROM cart WHERE user_id=?', (user['id'],))
    
    context.user_data['pending_order'] = order_id
    
    text = f"""
📋 **Заказ #{order_num}**

📦 Товары:
"""
    for i in items:
        text += f"• {i['name']} × {i['quantity']} = {i['price'] * i['quantity']}₽\n"
    
    text += f"\n━━━━━━━━━━━━━━\n"
    if balance_use > 0:
        text += f"💎 Баланс: -{balance_use}₽\n"
    text += f"💰 **К оплате: {final}₽**\n"
    
    if final > 0:
        text += f"""
━━━━━━━━━━━━━━
💳 **Реквизиты:**
Сбербанк: `{PAYMENT_CARD}`
Получатель: {PAYMENT_HOLDER}

📸 **Отправьте скриншот оплаты!**
"""
        await query.message.reply_text(text, parse_mode='Markdown')
    else:
        db_query('UPDATE orders SET status=? WHERE id=?', ('paid', order_id))
        await notify_admins_order(context, order_id)
        text += "\n✅ **Оплачено балансом!**"
        await query.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu(query.from_user.id))

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db_one('SELECT id FROM users WHERE tg_id=?', (update.effective_user.id,))
    if not user:
        return
    
    pending = db_one('''
        SELECT * FROM orders WHERE user_id=? AND status='awaiting_payment' ORDER BY id DESC LIMIT 1
    ''', (user['id'],))
    
    if not pending:
        # Maybe admin adding product photo
        if context.user_data.get('adding_product'):
            context.user_data['adding_product']['photo'] = update.message.photo[-1].file_id
            await finish_add_product(update, context)
        return
    
    file_id = update.message.photo[-1].file_id
    db_query('UPDATE orders SET status=?, payment_screenshot=? WHERE id=?', ('pending', file_id, pending['id']))
    
    await update.message.reply_text(
        "✅ **Скриншот получен!**\n\nОжидайте подтверждения.",
        parse_mode='Markdown',
        reply_markup=main_menu(update.effective_user.id)
    )
    
    await notify_admins_order(context, pending['id'], file_id)

async def notify_admins_order(context, order_id: int, screenshot: str = None):
    order = db_one('SELECT * FROM orders WHERE id=?', (order_id,))
    user = db_one('SELECT * FROM users WHERE id=?', (order['user_id'],))
    
    items = json.loads(order['items'])
    items_text = '\n'.join([f"• {i['name']} × {i['qty']}" for i in items])
    
    text = f"""
🆕 **Заказ #{order['order_number']}**

👤 @{user.get('username') or 'NoUsername'} (ID: {user['tg_id']})
🎮 PUBG: {order.get('pubg_id') or 'Не указан'}

📦 **Товары:**
{items_text}

💰 **К оплате: {order['total']}₽**
"""
    if order['balance_used'] > 0:
        text += f"💎 Баланс: -{order['balance_used']}₽\n"
    
    buttons = [
        [
            InlineKeyboardButton('✅ Подтвердить', callback_data=f"adm_ok:{order_id}"),
            InlineKeyboardButton('❌ Отклонить', callback_data=f"adm_no:{order_id}")
        ],
        [InlineKeyboardButton('📞 Связаться', url=f"tg://user?id={user['tg_id']}")]
    ]
    kb = InlineKeyboardMarkup(buttons)
    
    if screenshot:
        await context.bot.send_photo(ADMIN_CHAT_ID, screenshot, caption=text, parse_mode='Markdown', reply_markup=kb)
    else:
        await context.bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown', reply_markup=kb)

async def admin_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, oid = query.data.split(':')
    oid = int(oid)
    
    order = db_one('SELECT * FROM orders WHERE id=?', (oid,))
    user = db_one('SELECT * FROM users WHERE id=?', (order['user_id'],))
    
    if action == 'adm_ok':
        db_query('UPDATE orders SET status=? WHERE id=?', ('paid', oid))
        
        # Referral bonus
        if user.get('invited_by') and order['total'] > 0:
            bonus = order['total'] * REFERRAL_PERCENT
            db_query('UPDATE users SET balance = balance + ? WHERE id=?', (bonus, user['invited_by']))
            ref = db_one('SELECT tg_id FROM users WHERE id=?', (user['invited_by'],))
            if ref:
                try:
                    await context.bot.send_message(ref['tg_id'], f"💰 +{bonus:.0f}₽ за покупку реферала!")
                except: pass
        
        # Update sold count
        items = json.loads(order['items'])
        for i in items:
            db_query('UPDATE products SET sold_count = sold_count + ? WHERE id=?', (i['qty'], i['id']))
        
        try:
            await context.bot.send_message(user['tg_id'], f"✅ Заказ #{order['order_number']} подтвержден!")
        except: pass
        
        # Worker buttons
        work_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('🟢 Взять', callback_data=f"work_take:{oid}")],
            [
                InlineKeyboardButton('▶️ В работе', callback_data=f"status_prog:{oid}"),
                InlineKeyboardButton('📦 Выдача', callback_data=f"status_del:{oid}"),
                InlineKeyboardButton('✅ Готово', callback_data=f"status_done:{oid}")
            ]
        ])
        
        new_caption = query.message.caption + "\n\n✅ **ОПЛАТА ПОДТВЕРЖДЕНА**"
        try:
            await query.message.edit_caption(caption=new_caption, parse_mode='Markdown', reply_markup=work_kb)
        except:
            await query.message.edit_text(query.message.text + "\n\n✅ ПОДТВЕРЖДЕНО", reply_markup=work_kb)
    
    elif action == 'adm_no':
        if order['balance_used'] > 0:
            db_query('UPDATE users SET balance = balance + ? WHERE id=?', (order['balance_used'], user['id']))
        
        db_query('UPDATE orders SET status=? WHERE id=?', ('cancelled', oid))
        
        try:
            await context.bot.send_message(user['tg_id'], f"❌ Заказ #{order['order_number']} отклонен.")
        except: pass
        
        try:
            await query.message.edit_caption(caption=query.message.caption + "\n\n❌ ОТКЛОНЕНО", parse_mode='Markdown')
        except:
            await query.message.edit_text(query.message.text + "\n\n❌ ОТКЛОНЕНО")

async def worker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, oid = query.data.split(':')
    oid = int(oid)
    
    if action == 'work_take':
        existing = db_one('SELECT * FROM order_workers WHERE order_id=? AND worker_id=?', (oid, query.from_user.id))
        if existing:
            await query.answer("Вы уже взяли заказ")
            return
        
        db_query('INSERT INTO order_workers (order_id, worker_id, worker_username, taken_at) VALUES (?, ?, ?, ?)',
                 (oid, query.from_user.id, query.from_user.username, now_iso()))
        await query.answer("✅ Вы взяли заказ!")
    
    elif action in ('status_prog', 'status_del', 'status_done'):
        status_map = {'status_prog': 'in_progress', 'status_del': 'delivering', 'status_done': 'completed'}
        new_status = status_map[action]
        db_query('UPDATE orders SET status=? WHERE id=?', (new_status, oid))
        
        order = db_one('SELECT * FROM orders WHERE id=?', (oid,))
        user = db_one('SELECT tg_id FROM users WHERE id=?', (order['user_id'],))
        
        msg_map = {'in_progress': '▶️ Заказ выполняется', 'delivering': '📦 Выдача товара', 'completed': '✅ Заказ выполнен!'}
        
        try:
            kb = None
            if new_status == 'completed':
                kb = InlineKeyboardMarkup([[InlineKeyboardButton('⭐ Оценить', callback_data=f"review:{oid}")]])
            await context.bot.send_message(user['tg_id'], msg_map[new_status], reply_markup=kb)
        except: pass
        
        await query.answer(f"Статус: {new_status}")

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db_one('SELECT * FROM users WHERE tg_id=?', (update.effective_user.id,))
    if not user:
        return
    
    orders = db_query('SELECT COUNT(*) as cnt FROM orders WHERE user_id=?', (user['id'],), fetch=True)[0]['cnt']
    ref_link = f"https://t.me/{context.bot.username}?start=ref{update.effective_user.id}"
    
    text = f"""
👤 **Профиль**

🆔 ID: `{update.effective_user.id}`
🎮 PUBG ID: {user.get('pubg_id') or 'Не указан'}

💰 **Баланс: {user['balance']}₽**
📦 Заказов: {orders}

👥 **Рефералы:**
Приглашено: {user['referrals_count']}
Ссылка: `{ref_link}`

_Получайте {int(REFERRAL_PERCENT*100)}% от покупок друзей!_
"""
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu(update.effective_user.id))

async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db_one('SELECT id FROM users WHERE tg_id=?', (update.effective_user.id,))
    
    favs = db_query('''
        SELECT p.* FROM favorites f JOIN products p ON f.product_id = p.id 
        WHERE f.user_id=? AND p.is_active=1
    ''', (user['id'],), fetch=True)
    
    if not favs:
        await update.message.reply_text("❤️ **Избранное пусто**", parse_mode='Markdown')
        return
    
    await update.message.reply_text(f"❤️ **Избранное** ({len(favs)}):", parse_mode='Markdown')
    for p in favs:
        await send_product_card(update.message, p)

async def orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db_one('SELECT id FROM users WHERE tg_id=?', (update.effective_user.id,))
    orders = db_query('SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10', (user['id'],), fetch=True)
    
    if not orders:
        await update.message.reply_text("📦 Заказов нет")
        return
    
    status_emoji = {'awaiting_payment': '⏳', 'pending': '🔄', 'paid': '✅', 'in_progress': '🔨', 'delivering': '📦', 'completed': '✅', 'cancelled': '❌'}
    
    text = "📦 **Ваши заказы:**\n\n"
    for o in orders:
        emoji = status_emoji.get(o['status'], '❓')
        text += f"{emoji} #{o['order_number']} — {o['total']}₽\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def pubg_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['awaiting_pubg'] = True
    await update.message.reply_text("🎮 Введите ваш PUBG ID:", reply_markup=cancel_kb())

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📞 **Поддержка**\n\nНаписать: {SUPPORT_CONTACT}", parse_mode='Markdown')

# ============== ADMIN HANDLERS ==============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("⚙️ **Админ-панель**", parse_mode='Markdown', reply_markup=admin_menu())

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    users = db_query('SELECT COUNT(*) as cnt FROM users', fetch=True)[0]['cnt']
    orders = db_query('SELECT COUNT(*) as cnt FROM orders', fetch=True)[0]['cnt']
    revenue = db_query('SELECT SUM(total) as total FROM orders WHERE status="completed"', fetch=True)[0]['total'] or 0
    
    text = f"""
📊 **Статистика**

👥 Пользователей: {users}
📦 Заказов: {orders}
💰 Выручка: {revenue}₽
"""
    await update.message.reply_text(text, parse_mode='Markdown')

async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    context.user_data['adding_product'] = {'step': 'name'}
    await update.message.reply_text("📝 Введите название товара:", reply_markup=cancel_kb())

async def finish_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get('adding_product', {})
    
    db_query('''
        INSERT INTO products (category_id, name, description, price, photo, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (data.get('category', 1), data['name'], data.get('desc', ''), data['price'], data.get('photo'), now_iso()))
    
    context.user_data.pop('adding_product', None)
    await update.message.reply_text("✅ Товар добавлен!", reply_markup=admin_menu())

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    context.user_data['broadcast'] = True
    await update.message.reply_text("📢 Введите текст рассылки:", reply_markup=cancel_kb())

async def admin_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    promos = db_query('SELECT * FROM promocodes', fetch=True)
    text = "🏷 **Промокоды:**\n\n"
    
    if promos:
        for p in promos:
            text += f"`{p['code']}` — {p['discount_percent']}%\n"
    else:
        text += "Промокодов нет\n"
    
    text += "\n/addpromo CODE PERCENT — добавить"
    await update.message.reply_text(text, parse_mode='Markdown')

async def add_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /addpromo CODE PERCENT")
        return
    
    code, percent = context.args[0].upper(), int(context.args[1])
    db_query('INSERT OR REPLACE INTO promocodes (code, discount_percent) VALUES (?, ?)', (code, percent))
    await update.message.reply_text(f"✅ Промокод `{code}` создан ({percent}%)", parse_mode='Markdown')

async def admin_orders_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    orders = db_query('SELECT * FROM orders ORDER BY id DESC LIMIT 10', fetch=True)
    
    status_emoji = {'awaiting_payment': '⏳', 'pending': '🔄', 'paid': '✅', 'in_progress': '🔨', 'delivering': '📦', 'completed': '✅', 'cancelled': '❌'}
    
    text = "📦 **Последние заказы:**\n\n"
    for o in orders:
        emoji = status_emoji.get(o['status'], '❓')
        text += f"{emoji} #{o['order_number']} — {o['total']}₽\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ============== TEXT ROUTER ==============

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    user = update.effective_user
    
    # Cancel
    if text == '❌ Отмена':
        context.user_data.clear()
        await update.message.reply_text("Отменено", reply_markup=main_menu(user.id))
        return
    
    # Adding product flow
    if context.user_data.get('adding_product'):
        data = context.user_data['adding_product']
        step = data['step']
        
        if step == 'name':
            data['name'] = text
            data['step'] = 'price'
            await update.message.reply_text("💰 Введите цену:")
        elif step == 'price':
            try:
                data['price'] = float(text)
            except:
                await update.message.reply_text("❌ Введите число")
                return
            data['step'] = 'desc'
            await update.message.reply_text("📝 Введите описание:")
        elif step == 'desc':
            data['desc'] = text
            data['step'] = 'photo'
            await update.message.reply_text("📷 Отправьте фото товара:")
        return
    
    # Broadcast
    if context.user_data.get('broadcast'):
        context.user_data.pop('broadcast')
        users = db_query('SELECT tg_id FROM users', fetch=True)
        count = 0
        for u in users:
            try:
                await context.bot.send_message(u['tg_id'], f"📢 **Рассылка:**\n\n{text}", parse_mode='Markdown')
                count += 1
            except: pass
        await update.message.reply_text(f"✅ Отправлено: {count}", reply_markup=admin_menu())
        return
    
    # PUBG ID
    if context.user_data.get('awaiting_pubg'):
        context.user_data.pop('awaiting_pubg')
        db_query('UPDATE users SET pubg_id=? WHERE tg_id=?', (text, user.id))
        await update.message.reply_text(f"✅ PUBG ID сохранен: `{text}`", parse_mode='Markdown', reply_markup=main_menu(user.id))
        return
    
    # Menu buttons
    if text == '🛍 Каталог':
        await catalog_handler(update, context)
    elif text == '🛒 Корзина':
        await cart_handler(update, context)
    elif text == '👤 Профиль':
        await profile_handler(update, context)
    elif text == '📦 Мои заказы':
        await orders_handler(update, context)
    elif text == '❤️ Избранное':
        await favorites_handler(update, context)
    elif text == '🎮 PUBG ID':
        await pubg_id_handler(update, context)
    elif text == '📞 Поддержка':
        await support_handler(update, context)
    elif text == '⚙️ Админка' and is_admin(user.id):
        await admin_panel(update, context)
    elif text == '📊 Статистика' and is_admin(user.id):
        await admin_stats(update, context)
    elif text == '➕ Добавить товар' and is_admin(user.id):
        await admin_add_product(update, context)
    elif text == '📦 Все заказы' and is_admin(user.id):
        await admin_orders_list(update, context)
    elif text == '🏷 Промокоды' and is_admin(user.id):
        await admin_promo(update, context)
    elif text == '📢 Рассылка' and is_admin(user.id):
        await admin_broadcast(update, context)
    elif text == '⬅️ Назад':
        await update.message.reply_text("Меню:", reply_markup=main_menu(user.id))
    else:
        await update.message.reply_text("Используйте меню", reply_markup=main_menu(user.id))

# ============== MAIN ==============

def main():
    init_db()
    
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('addpromo', add_promo_command))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r'^cat:'))
    app.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r'^prod:'))
    app.add_handler(CallbackQueryHandler(add_to_cart_callback, pattern=r'^cart_add:'))
    app.add_handler(CallbackQueryHandler(toggle_favorite_callback, pattern=r'^fav:'))
    app.add_handler(CallbackQueryHandler(cart_action_callback, pattern=r'^cart_'))
    app.add_handler(CallbackQueryHandler(checkout_callback, pattern=r'^checkout'))
    app.add_handler(CallbackQueryHandler(admin_order_callback, pattern=r'^adm_'))
    app.add_handler(CallbackQueryHandler(worker_callback, pattern=r'^(work_|status_)'))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    logger.info("🚀 Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
