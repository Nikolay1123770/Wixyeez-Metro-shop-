#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metro Shop Telegram Bot + WebApp Server - All-in-One
Полностью рабочая версия с админ-панелью
"""

import os
import sqlite3
import logging
import json
import hashlib
import hmac
import threading
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import parse_qsl

# ============== CONFIGURATION ==============
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '8269807126:AAFN7bjp1094IVasTTkeYL3hkz4SYNgiQCY')
OWNER_ID = int(os.getenv('OWNER_ID', '8473513085'))
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '-1002289612690'))
DB_PATH = os.getenv('DB_PATH', 'metro_shop.db')

WEBAPP_HOST = os.getenv('WEBAPP_HOST', '0.0.0.0')
WEBAPP_PORT = int(os.getenv('WEBAPP_PORT', '1111'))
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://wixyeezmetroshop.bothost.ru')

SUPPORT_CONTACT_USER = os.getenv('SUPPORT_CONTACT', '@wixyeez')

ADMIN_IDS = [OWNER_ID]
if os.getenv('ADMIN_IDS'):
    ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS').split(',') if x.strip()]

MAX_WORKERS_PER_ORDER = int(os.getenv('MAX_WORKERS_PER_ORDER', '3'))
WORKER_PERCENT = float(os.getenv('WORKER_PERCENT', '0.7'))
REFERRAL_PERCENT = float(os.getenv('REFERRAL_PERCENT', '0.05'))

PAYMENT_CARD = "+79002535363"
PAYMENT_HOLDER = "Николай М"
PAYMENT_BANK = "Сбербанк"

# ============== LOGGING ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============== HELPER FUNCTIONS ==============
def now_iso() -> str:
    return datetime.utcnow().isoformat()

def generate_order_number() -> str:
    import random
    return f"MS{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS

def validate_webapp_data(init_data: str) -> Optional[Dict]:
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop('hash', '')
        data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b'WebAppData', TG_BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated_hash, received_hash):
            return json.loads(parsed.get('user', '{}'))
        return None
    except Exception as e:
        logger.error(f"WebApp validation error: {e}")
        return None

# ============== DATABASE ==============
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📦',
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )''')
        
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
        )''')
        
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
        )''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            added_at TEXT,
            UNIQUE(user_id, product_id)
        )''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            added_at TEXT,
            UNIQUE(user_id, product_id)
        )''')
        
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
        )''')
        
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
        )''')
        
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
        )''')
        
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
        )''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS promocode_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER,
            user_id INTEGER,
            order_id INTEGER,
            discount_amount REAL,
            used_at TEXT
        )''')
        
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
        )''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            user_id INTEGER,
            data TEXT DEFAULT '{}',
            created_at TEXT
        )''')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS worker_payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER,
            order_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            paid_at TEXT,
            created_at TEXT
        )''')
        
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

db = Database(DB_PATH)

# ============== WEBAPP STATIC FILES ==============

INDEX_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Metro Shop</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
:root {
    --tg-theme-bg-color: #ffffff;
    --tg-theme-text-color: #000000;
    --tg-theme-hint-color: #999999;
    --tg-theme-link-color: #2481cc;
    --tg-theme-button-color: #2481cc;
    --tg-theme-button-text-color: #ffffff;
    --tg-theme-secondary-bg-color: #f1f1f1;
    --primary: #6c5ce7;
    --primary-dark: #5f4dd0;
    --success: #00b894;
    --danger: #e74c3c;
    --warning: #f39c12;
    --card-shadow: 0 2px 8px rgba(0,0,0,0.1);
    --radius: 12px;
    --radius-lg: 16px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--tg-theme-bg-color);
    color: var(--tg-theme-text-color);
    min-height: 100vh;
    padding-bottom: 80px;
}

.header {
    position: sticky;
    top: 0;
    background: var(--tg-theme-bg-color);
    border-bottom: 1px solid var(--tg-theme-secondary-bg-color);
    z-index: 100;
    padding: 12px 16px;
}

.header-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.logo {
    font-size: 20px;
    font-weight: 700;
    background: linear-gradient(135deg, var(--primary), #a29bfe);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.header-actions { display: flex; gap: 8px; }

.icon-btn {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: none;
    background: var(--tg-theme-secondary-bg-color);
    color: var(--tg-theme-text-color);
    font-size: 18px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    transition: all 0.2s;
}

.icon-btn:active { transform: scale(0.95); }

.cart-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    background: var(--danger);
    color: white;
    font-size: 10px;
    font-weight: 600;
    min-width: 18px;
    height: 18px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
}

.cart-badge:empty, .cart-badge[data-count="0"] { display: none; }

.categories-section {
    padding: 12px 0;
    border-bottom: 1px solid var(--tg-theme-secondary-bg-color);
}

.categories-scroll {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 0 16px;
    scrollbar-width: none;
}

.categories-scroll::-webkit-scrollbar { display: none; }

.category-chip {
    flex-shrink: 0;
    padding: 8px 16px;
    border-radius: 20px;
    border: none;
    background: var(--tg-theme-secondary-bg-color);
    color: var(--tg-theme-text-color);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.category-chip.active {
    background: var(--primary);
    color: white;
}

.category-chip:active { transform: scale(0.95); }

.filter-section {
    padding: 12px 16px;
    display: flex;
    justify-content: flex-end;
}

.filter-section select {
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid var(--tg-theme-secondary-bg-color);
    background: var(--tg-theme-bg-color);
    color: var(--tg-theme-text-color);
    font-size: 14px;
}

.products-section { padding: 0 12px; }

.products-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
}

.product-card {
    background: var(--tg-theme-bg-color);
    border-radius: var(--radius);
    box-shadow: var(--card-shadow);
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.2s;
}

.product-card:active { transform: scale(0.98); }

.product-image {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    background: var(--tg-theme-secondary-bg-color);
}

.product-info { padding: 10px; }

.product-name {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 4px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.product-price {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.current-price {
    font-size: 16px;
    font-weight: 700;
    color: var(--primary);
}

.old-price {
    font-size: 12px;
    color: var(--tg-theme-hint-color);
    text-decoration: line-through;
}

.discount-badge {
    background: var(--danger);
    color: white;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
}

.product-meta {
    display: flex;
    gap: 8px;
    margin-top: 6px;
    font-size: 11px;
    color: var(--tg-theme-hint-color);
}

.product-rating {
    display: flex;
    align-items: center;
    gap: 2px;
}

.product-rating i {
    color: #f1c40f;
    font-size: 10px;
}

.product-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
}

.btn-cart, .btn-fav {
    flex: 1;
    padding: 8px;
    border-radius: 8px;
    border: none;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    transition: all 0.2s;
}

.btn-cart {
    background: var(--primary);
    color: white;
}

.btn-cart:active { background: var(--primary-dark); }

.btn-fav {
    background: var(--tg-theme-secondary-bg-color);
    color: var(--tg-theme-text-color);
    width: 36px;
    flex: none;
}

.btn-fav.active { color: var(--danger); }

.loading {
    display: none;
    justify-content: center;
    padding: 20px;
}

.loading.active { display: flex; }

.spinner {
    width: 30px;
    height: 30px;
    border: 3px solid var(--tg-theme-secondary-bg-color);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: var(--tg-theme-bg-color);
    border-top: 1px solid var(--tg-theme-secondary-bg-color);
    display: flex;
    justify-content: space-around;
    padding: 8px 0 calc(8px + env(safe-area-inset-bottom));
    z-index: 100;
}

.nav-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 8px 16px;
    border: none;
    background: none;
    color: var(--tg-theme-hint-color);
    font-size: 10px;
    cursor: pointer;
    transition: all 0.2s;
}

.nav-item i { font-size: 20px; }
.nav-item.active { color: var(--primary); }

.modal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 200;
    align-items: flex-end;
}

.modal.open {
    display: flex;
    animation: fadeIn 0.2s;
}

.modal-content {
    background: var(--tg-theme-bg-color);
    width: 100%;
    max-height: 90vh;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    overflow-y: auto;
    animation: slideUp 0.3s;
}

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    border-bottom: 1px solid var(--tg-theme-secondary-bg-color);
    position: sticky;
    top: 0;
    background: var(--tg-theme-bg-color);
}

.modal-header h2 { font-size: 18px; }

.modal-header button {
    background: none;
    border: none;
    font-size: 20px;
    color: var(--tg-theme-hint-color);
    cursor: pointer;
}

.product-modal { padding-bottom: calc(80px + env(safe-area-inset-bottom)); }

.close-btn {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: rgba(0, 0, 0, 0.5);
    color: white;
    font-size: 16px;
    z-index: 10;
    cursor: pointer;
}

.product-gallery { position: relative; }
.product-gallery img { width: 100%; aspect-ratio: 1; object-fit: cover; }

.detail-content { padding: 16px; }
.detail-content h1 { font-size: 20px; margin-bottom: 8px; }

.detail-price {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}

.detail-price .current-price { font-size: 24px; }

.detail-description {
    color: var(--tg-theme-hint-color);
    font-size: 14px;
    line-height: 1.5;
    margin-bottom: 16px;
}

.detail-stats {
    display: flex;
    gap: 16px;
    padding: 12px;
    background: var(--tg-theme-secondary-bg-color);
    border-radius: var(--radius);
    margin-bottom: 16px;
}

.stat-item { text-align: center; }
.stat-value { font-size: 18px; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 11px; color: var(--tg-theme-hint-color); }

.detail-actions {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
    background: var(--tg-theme-bg-color);
    border-top: 1px solid var(--tg-theme-secondary-bg-color);
    display: flex;
    gap: 12px;
}

.btn-buy {
    flex: 1;
    padding: 14px;
    border-radius: var(--radius);
    border: none;
    background: var(--primary);
    color: white;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
}

.btn-buy:active { background: var(--primary-dark); }

.cart-content { padding: 16px; }

.cart-item {
    display: flex;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--tg-theme-secondary-bg-color);
}

.cart-item-image {
    width: 60px;
    height: 60px;
    border-radius: 8px;
    object-fit: cover;
}

.cart-item-info { flex: 1; }
.cart-item-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; }
.cart-item-price { font-size: 14px; font-weight: 600; color: var(--primary); }

.quantity-control {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
}

.quantity-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: none;
    background: var(--tg-theme-secondary-bg-color);
    font-size: 14px;
    cursor: pointer;
}

.quantity-value {
    font-size: 14px;
    font-weight: 600;
    min-width: 20px;
    text-align: center;
}

.cart-total {
    padding: 16px;
    border-top: 2px solid var(--tg-theme-secondary-bg-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 18px;
    font-weight: 700;
}

.cart-checkout { padding: 16px; }

.btn-checkout {
    width: 100%;
    padding: 14px;
    border-radius: var(--radius);
    border: none;
    background: var(--success);
    color: white;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
}

.search-modal {
    border-radius: 0;
    max-height: 100vh;
    height: 100vh;
}

.search-header {
    display: flex;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--tg-theme-secondary-bg-color);
}

.search-header input {
    flex: 1;
    padding: 12px;
    border-radius: var(--radius);
    border: 1px solid var(--tg-theme-secondary-bg-color);
    font-size: 16px;
    background: var(--tg-theme-bg-color);
    color: var(--tg-theme-text-color);
}

.search-header button {
    padding: 12px;
    border: none;
    background: none;
    font-size: 18px;
    color: var(--tg-theme-hint-color);
    cursor: pointer;
}

.search-results { padding: 16px; }

.empty-state {
    text-align: center;
    padding: 40px 20px;
}

.empty-state i {
    font-size: 48px;
    color: var(--tg-theme-hint-color);
    margin-bottom: 16px;
}

.empty-state h3 { font-size: 18px; margin-bottom: 8px; }
.empty-state p { color: var(--tg-theme-hint-color); font-size: 14px; }

@media (min-width: 480px) {
    .products-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (min-width: 768px) {
    .products-grid { grid-template-columns: repeat(4, 1fr); }
}
    </style>
</head>
<body>
    <div id="app">
        <header class="header">
            <div class="header-content">
                <h1 class="logo">🎮 Metro Shop</h1>
                <div class="header-actions">
                    <button class="icon-btn" onclick="openSearch()">
                        <i class="fas fa-search"></i>
                    </button>
                    <button class="icon-btn cart-btn" onclick="openCart()">
                        <i class="fas fa-shopping-cart"></i>
                        <span class="cart-badge" id="cartBadge">0</span>
                    </button>
                </div>
            </div>
        </header>

        <div id="searchModal" class="modal">
            <div class="modal-content search-modal">
                <div class="search-header">
                    <input type="text" id="searchInput" placeholder="Поиск товаров..." autofocus>
                    <button onclick="closeSearch()"><i class="fas fa-times"></i></button>
                </div>
                <div id="searchResults" class="search-results"></div>
            </div>
        </div>

        <main class="main-content">
            <section class="categories-section">
                <div class="categories-scroll" id="categoriesContainer">
                    <button class="category-chip active" data-id="all" onclick="selectCategory('all')">
                        🔥 Все
                    </button>
                </div>
            </section>

            <section class="filter-section">
                <select id="sortSelect" onchange="sortProducts()">
                    <option value="popular">🔥 Популярные</option>
                    <option value="new">🆕 Новинки</option>
                    <option value="price_asc">💰 Сначала дешевые</option>
                    <option value="price_desc">💎 Сначала дорогие</option>
                    <option value="rating">⭐ По рейтингу</option>
                </select>
            </section>

            <section class="products-section">
                <div class="products-grid" id="productsGrid"></div>
                <div class="loading" id="loadingIndicator">
                    <div class="spinner"></div>
                </div>
            </section>
        </main>

        <div id="productModal" class="modal">
            <div class="modal-content product-modal">
                <button class="close-btn" onclick="closeProductModal()">
                    <i class="fas fa-times"></i>
                </button>
                <div id="productDetail"></div>
            </div>
        </div>

        <div id="cartModal" class="modal">
            <div class="modal-content cart-modal">
                <div class="modal-header">
                    <h2>🛒 Корзина</h2>
                    <button onclick="closeCart()"><i class="fas fa-times"></i></button>
                </div>
                <div id="cartContent"></div>
            </div>
        </div>

        <nav class="bottom-nav">
            <button class="nav-item active" onclick="showCatalog()">
                <i class="fas fa-store"></i>
                <span>Каталог</span>
            </button>
            <button class="nav-item" onclick="showFavorites()">
                <i class="fas fa-heart"></i>
                <span>Избранное</span>
            </button>
            <button class="nav-item" onclick="openCart()">
                <i class="fas fa-shopping-cart"></i>
                <span>Корзина</span>
            </button>
            <button class="nav-item" onclick="showProfile()">
                <i class="fas fa-user"></i>
                <span>Профиль</span>
            </button>
        </nav>
    </div>

    <script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

document.documentElement.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#ffffff');
document.documentElement.style.setProperty('--tg-theme-text-color', tg.themeParams.text_color || '#000000');
document.documentElement.style.setProperty('--tg-theme-hint-color', tg.themeParams.hint_color || '#999999');
document.documentElement.style.setProperty('--tg-theme-link-color', tg.themeParams.link_color || '#2481cc');
document.documentElement.style.setProperty('--tg-theme-button-color', tg.themeParams.button_color || '#2481cc');
document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', tg.themeParams.secondary_bg_color || '#f1f1f1');

let currentCategory = 'all';
let currentSort = 'popular';
let products = [];
let cart = [];
let favorites = [];

const API_URL = '/api';

async function api(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-Telegram-Init-Data': tg.initData
        }
    };
    const response = await fetch(`${API_URL}${endpoint}`, { ...defaultOptions, ...options });
    if (!response.ok) throw new Error(`API Error: ${response.status}`);
    return response.json();
}

document.addEventListener('DOMContentLoaded', async () => {
    await loadCategories();
    await loadProducts();
    await loadCart();
    await loadFavorites();
});

async function loadCategories() {
    try {
        const categories = await api('/categories');
        const container = document.getElementById('categoriesContainer');
        categories.forEach(cat => {
            const chip = document.createElement('button');
            chip.className = 'category-chip';
            chip.dataset.id = cat.id;
            chip.onclick = () => selectCategory(cat.id);
            chip.innerHTML = `${cat.emoji || '📦'} ${cat.name}`;
            container.appendChild(chip);
        });
    } catch (error) {
        console.error('Failed to load categories:', error);
    }
}

async function selectCategory(categoryId) {
    currentCategory = categoryId;
    document.querySelectorAll('.category-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.id == categoryId);
    });
    await loadProducts();
}

async function loadProducts() {
    const loading = document.getElementById('loadingIndicator');
    const grid = document.getElementById('productsGrid');
    loading.classList.add('active');
    grid.innerHTML = '';
    
    try {
        let endpoint = `/products?sort=${currentSort}`;
        if (currentCategory !== 'all') endpoint += `&category_id=${currentCategory}`;
        products = await api(endpoint);
        renderProducts(products);
    } catch (error) {
        console.error('Failed to load products:', error);
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1"><i class="fas fa-exclamation-circle"></i><h3>Ошибка загрузки</h3></div>`;
    } finally {
        loading.classList.remove('active');
    }
}

function renderProducts(products) {
    const grid = document.getElementById('productsGrid');
    if (products.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1"><i class="fas fa-box-open"></i><h3>Товаров не найдено</h3></div>`;
        return;
    }
    grid.innerHTML = products.map(product => {
        const isFav = favorites.includes(product.id);
        const hasDiscount = product.old_price && product.old_price > product.price;
        const discount = hasDiscount ? Math.round((1 - product.price / product.old_price) * 100) : 0;
        return `
            <div class="product-card" onclick="openProduct(${product.id})">
                <img class="product-image" src="${product.photo || 'https://via.placeholder.com/200x200?text=No+Image'}" alt="${product.name}" onerror="this.src='https://via.placeholder.com/200x200?text=No+Image'">
                <div class="product-info">
                    <div class="product-name">${escapeHtml(product.name)}</div>
                    <div class="product-price">
                        <span class="current-price">${product.price}₽</span>
                        ${hasDiscount ? `<span class="old-price">${product.old_price}₽</span><span class="discount-badge">-${discount}%</span>` : ''}
                    </div>
                    <div class="product-meta">
                        ${product.rating > 0 ? `<span class="product-rating"><i class="fas fa-star"></i> ${product.rating.toFixed(1)}</span>` : ''}
                        <span>🛒 ${product.sold_count}</span>
                    </div>
                    <div class="product-actions" onclick="event.stopPropagation()">
                        <button class="btn-cart" onclick="addToCart(${product.id})"><i class="fas fa-cart-plus"></i> В корзину</button>
                        <button class="btn-fav ${isFav ? 'active' : ''}" onclick="toggleFavorite(${product.id})"><i class="fas fa-heart"></i></button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function sortProducts() {
    currentSort = document.getElementById('sortSelect').value;
    await loadProducts();
}

async function openProduct(productId) {
    const modal = document.getElementById('productModal');
    const detail = document.getElementById('productDetail');
    modal.classList.add('open');
    detail.innerHTML = '<div class="loading active"><div class="spinner"></div></div>';
    
    try {
        const product = await api(`/products/${productId}`);
        const isFav = favorites.includes(product.id);
        const hasDiscount = product.old_price && product.old_price > product.price;
        const discount = hasDiscount ? Math.round((1 - product.price / product.old_price) * 100) : 0;
        
        detail.innerHTML = `
            <div class="product-gallery">
                <img src="${product.photo || 'https://via.placeholder.com/400x400?text=No+Image'}" alt="${product.name}">
            </div>
            <div class="detail-content">
                <h1>${escapeHtml(product.name)}</h1>
                <div class="detail-price">
                    <span class="current-price">${product.price}₽</span>
                    ${hasDiscount ? `<span class="old-price">${product.old_price}₽</span><span class="discount-badge">-${discount}%</span>` : ''}
                </div>
                <div class="detail-stats">
                    <div class="stat-item"><div class="stat-value">${product.sold_count}</div><div class="stat-label">Продано</div></div>
                    <div class="stat-item"><div class="stat-value">${product.views_count}</div><div class="stat-label">Просмотров</div></div>
                    ${product.rating > 0 ? `<div class="stat-item"><div class="stat-value">⭐ ${product.rating.toFixed(1)}</div><div class="stat-label">${product.reviews_count} отзывов</div></div>` : ''}
                </div>
                <div class="detail-description">${escapeHtml(product.description || product.short_description || 'Описание отсутствует')}</div>
            </div>
            <div class="detail-actions">
                <button class="btn-fav ${isFav ? 'active' : ''}" style="width: 48px; height: 48px;" onclick="toggleFavorite(${product.id})">
                    <i class="fas fa-heart" style="font-size: 20px;"></i>
                </button>
                <button class="btn-buy" onclick="addToCart(${product.id}); closeProductModal();">
                    <i class="fas fa-cart-plus"></i> Добавить в корзину
                </button>
            </div>
        `;
    } catch (error) {
        detail.innerHTML = '<p>Ошибка загрузки товара</p>';
    }
}

function closeProductModal() {
    document.getElementById('productModal').classList.remove('open');
}

async function loadCart() {
    try {
        const data = await api('/cart');
        cart = data.items;
        updateCartBadge();
    } catch (error) {
        console.error('Failed to load cart:', error);
    }
}

function updateCartBadge() {
    const badge = document.getElementById('cartBadge');
    const count = cart.reduce((sum, item) => sum + item.quantity, 0);
    badge.textContent = count;
    badge.dataset.count = count;
}

async function addToCart(productId) {
    try {
        await api('/cart/add', {
            method: 'POST',
            body: JSON.stringify({ product_id: productId, quantity: 1 })
        });
        tg.HapticFeedback.impactOccurred('light');
        tg.showPopup({ title: 'Добавлено!', message: 'Товар добавлен в корзину', buttons: [{ type: 'ok' }] });
        await loadCart();
    } catch (error) {
        tg.showAlert('Ошибка добавления в корзину');
    }
}

async function updateCartItem(productId, quantity) {
    try {
        if (quantity <= 0) {
            await api(`/cart/${productId}`, { method: 'DELETE' });
        } else {
            await api('/cart/update', {
                method: 'POST',
                body: JSON.stringify({ product_id: productId, quantity })
            });
        }
        await loadCart();
        renderCart();
    } catch (error) {
        console.error('Failed to update cart:', error);
    }
}

function openCart() {
    document.getElementById('cartModal').classList.add('open');
    renderCart();
}

function closeCart() {
    document.getElementById('cartModal').classList.remove('open');
}

function renderCart() {
    const content = document.getElementById('cartContent');
    if (cart.length === 0) {
        content.innerHTML = `<div class="empty-state"><i class="fas fa-shopping-cart"></i><h3>Корзина пуста</h3><p>Добавьте товары из каталога</p></div>`;
        return;
    }
    const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
    content.innerHTML = `
        <div class="cart-content">
            ${cart.map(item => `
                <div class="cart-item">
                    <img class="cart-item-image" src="${item.photo || 'https://via.placeholder.com/60x60?text=No+Image'}" alt="${item.name}">
                    <div class="cart-item-info">
                        <div class="cart-item-name">${escapeHtml(item.name)}</div>
                        <div class="cart-item-price">${item.price}₽</div>
                        <div class="quantity-control">
                            <button class="quantity-btn" onclick="updateCartItem(${item.product_id}, ${item.quantity - 1})">−</button>
                            <span class="quantity-value">${item.quantity}</span>
                            <button class="quantity-btn" onclick="updateCartItem(${item.product_id}, ${item.quantity + 1})">+</button>
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
        <div class="cart-total"><span>Итого:</span><span>${total}₽</span></div>
        <div class="cart-checkout"><button class="btn-checkout" onclick="checkout()">Оформить заказ на ${total}₽</button></div>
    `;
}

async function checkout() {
    tg.MainButton.showProgress();
    try {
        tg.sendData(JSON.stringify({ action: 'checkout', cart: cart }));
        closeCart();
    } catch (error) {
        tg.showAlert('Ошибка оформления заказа');
    } finally {
        tg.MainButton.hideProgress();
    }
}

async function loadFavorites() {
    try {
        const data = await api('/favorites');
        favorites = data.map(p => p.id);
    } catch (error) {
        console.error('Failed to load favorites:', error);
    }
}

async function toggleFavorite(productId) {
    try {
        const result = await api(`/favorites/${productId}`, { method: 'POST' });
        if (result.is_favorite) {
            favorites.push(productId);
            tg.HapticFeedback.impactOccurred('light');
        } else {
            favorites = favorites.filter(id => id !== productId);
        }
    } catch (error) {
        console.error('Failed to toggle favorite:', error);
    }
}

function openSearch() {
    document.getElementById('searchModal').classList.add('open');
    document.getElementById('searchInput').focus();
}

function closeSearch() {
    document.getElementById('searchModal').classList.remove('open');
}

document.getElementById('searchInput')?.addEventListener('input', debounce(async (e) => {
    const query = e.target.value.trim();
    const results = document.getElementById('searchResults');
    if (query.length < 2) {
        results.innerHTML = '<p style="color: var(--tg-theme-hint-color)">Введите минимум 2 символа</p>';
        return;
    }
    try {
        const products = await api(`/products?search=${encodeURIComponent(query)}`);
        if (products.length === 0) {
            results.innerHTML = '<p>Ничего не найдено</p>';
            return;
        }
        results.innerHTML = products.map(p => `
            <div class="cart-item" onclick="closeSearch(); openProduct(${p.id})">
                <img class="cart-item-image" src="${p.photo || 'https://via.placeholder.com/60'}" alt="">
                <div class="cart-item-info">
                    <div class="cart-item-name">${escapeHtml(p.name)}</div>
                    <div class="cart-item-price">${p.price}₽</div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        results.innerHTML = '<p>Ошибка поиска</p>';
    }
}, 300));

function showCatalog() { setActiveNav(0); }
function showFavorites() { setActiveNav(1); tg.showAlert('Избранное в разработке'); }
function showProfile() { setActiveNav(3); tg.showAlert('Профиль в разработке'); }

function setActiveNav(index) {
    document.querySelectorAll('.nav-item').forEach((item, i) => {
        item.classList.toggle('active', i === index);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

tg.BackButton.onClick(() => {
    const productModal = document.getElementById('productModal');
    const cartModal = document.getElementById('cartModal');
    const searchModal = document.getElementById('searchModal');
    if (searchModal.classList.contains('open')) closeSearch();
    else if (cartModal.classList.contains('open')) closeCart();
    else if (productModal.classList.contains('open')) closeProductModal();
    else tg.close();
});

const observer = new MutationObserver(() => {
    const anyModalOpen = document.querySelector('.modal.open');
    if (anyModalOpen) tg.BackButton.show();
    else tg.BackButton.hide();
});
observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] });
    </script>
</body>
</html>'''

# ============== FASTAPI SERVER ==============
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

webapp = FastAPI(title="Metro Shop WebApp API")

webapp.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CartItem(BaseModel):
    product_id: int
    quantity: int = 1

async def get_current_user(request: Request):
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    user = validate_webapp_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return user

@webapp.get("/", response_class=HTMLResponse)
@webapp.get("/catalog", response_class=HTMLResponse)
async def serve_webapp():
    return HTMLResponse(content=INDEX_HTML)

@webapp.get("/api/categories")
async def get_categories():
    return db.fetchall('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order')

@webapp.get("/api/products")
async def get_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    sort: str = "popular",
    limit: int = 20,
    offset: int = 0
):
    query = "SELECT * FROM products WHERE is_active=1"
    params = []
    
    if category_id:
        query += " AND category_id=?"
        params.append(category_id)
    
    if search:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    if sort == "popular":
        query += " ORDER BY sold_count DESC, is_featured DESC"
    elif sort == "price_asc":
        query += " ORDER BY price ASC"
    elif sort == "price_desc":
        query += " ORDER BY price DESC"
    elif sort == "new":
        query += " ORDER BY created_at DESC"
    elif sort == "rating":
        query += " ORDER BY rating DESC"
    
    query += f" LIMIT {limit} OFFSET {offset}"
    
    products = db.fetchall(query, tuple(params))
    for p in products:
        p['photos'] = json.loads(p.get('photos') or '[]')
        p['tags'] = json.loads(p.get('tags') or '[]')
        p['meta'] = json.loads(p.get('meta') or '{}')
    
    return products

@webapp.get("/api/products/{product_id}")
async def get_product(product_id: int):
    product = db.fetchone('SELECT * FROM products WHERE id=? AND is_active=1', (product_id,))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    product['photos'] = json.loads(product.get('photos') or '[]')
    product['tags'] = json.loads(product.get('tags') or '[]')
    
    reviews = db.fetchall('''
        SELECT r.*, u.first_name, u.username 
        FROM reviews r 
        JOIN users u ON r.user_id = u.id
        WHERE r.product_id=? AND r.is_visible=1 
        ORDER BY r.created_at DESC LIMIT 5
    ''', (product_id,))
    product['reviews'] = reviews
    
    db.execute('UPDATE products SET views_count = views_count + 1 WHERE id=?', (product_id,))
    return product

@webapp.get("/api/cart")
async def get_cart(user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    if not user_row:
        return {"items": [], "total": 0}
    
    items = db.fetchall('''
        SELECT c.*, p.name, p.price, p.photo, p.stock
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=?
    ''', (user_row['id'],))
    
    total = sum(item['price'] * item['quantity'] for item in items)
    return {"items": items, "total": total}

@webapp.post("/api/cart/add")
async def add_to_cart(item: CartItem, user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    
    existing = db.fetchone('SELECT id, quantity FROM cart WHERE user_id=? AND product_id=?', 
                           (user_row['id'], item.product_id))
    
    if existing:
        db.execute('UPDATE cart SET quantity=? WHERE id=?', 
                   (existing['quantity'] + item.quantity, existing['id']))
    else:
        db.execute('INSERT INTO cart (user_id, product_id, quantity, added_at) VALUES (?, ?, ?, ?)',
                   (user_row['id'], item.product_id, item.quantity, now_iso()))
    
    return {"success": True}

@webapp.post("/api/cart/update")
async def update_cart(item: CartItem, user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    
    if item.quantity <= 0:
        db.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', 
                   (user_row['id'], item.product_id))
    else:
        db.execute('UPDATE cart SET quantity=? WHERE user_id=? AND product_id=?',
                   (item.quantity, user_row['id'], item.product_id))
    
    return {"success": True}

@webapp.delete("/api/cart/{product_id}")
async def remove_from_cart(product_id: int, user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    db.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', (user_row['id'], product_id))
    return {"success": True}

@webapp.get("/api/user/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    profile = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user['id'],))
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    
    orders_count = db.fetchone('SELECT COUNT(*) as count FROM orders WHERE user_id=?', (profile['id'],))
    profile['orders_count'] = orders_count['count'] if orders_count else 0
    return profile

@webapp.get("/api/favorites")
async def get_favorites(user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    if not user_row:
        return []
    
    return db.fetchall('''
        SELECT p.* FROM favorites f
        JOIN products p ON f.product_id = p.id
        WHERE f.user_id=? AND p.is_active=1
    ''', (user_row['id'],))

@webapp.post("/api/favorites/{product_id}")
async def toggle_favorite(product_id: int, user: dict = Depends(get_current_user)):
    user_row = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    
    existing = db.fetchone('SELECT id FROM favorites WHERE user_id=? AND product_id=?',
                           (user_row['id'], product_id))
    
    if existing:
        db.execute('DELETE FROM favorites WHERE id=?', (existing['id'],))
        return {"is_favorite": False}
    else:
        db.execute('INSERT INTO favorites (user_id, product_id, added_at) VALUES (?, ?, ?)',
                   (user_row['id'], product_id, now_iso()))
        return {"is_favorite": True}

# ============== TELEGRAM BOT ==============
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InputMediaPhoto,
    Update,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Состояния диалогов
ADD_PRODUCT_NAME, ADD_PRODUCT_PRICE, ADD_PRODUCT_CATEGORY, ADD_PRODUCT_PHOTO, ADD_PRODUCT_DESC = range(5)
ADD_CATEGORY_NAME, ADD_CATEGORY_EMOJI = range(2)
BROADCAST_MSG, BROADCAST_CONFIRM = range(2)
ADD_PROMO_CODE, ADD_PROMO_VALUE, ADD_PROMO_TYPE = range(3)

def get_main_menu(user_id: int = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton('🛍 Каталог', web_app=WebAppInfo(url=f"{WEBAPP_URL}")),
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
        buttons.append([InlineKeyboardButton(f"{is_selected}{emoji} {cat['name']}", callback_data=f"cat:{cat['id']}")])
    buttons.append([
        InlineKeyboardButton('🔍 Поиск', callback_data='search'),
        InlineKeyboardButton('🔥 Популярное', callback_data='popular')
    ])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args
    
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
                        except:
                            pass
            except:
                pass
        
        db.execute('''
            INSERT INTO users (tg_id, username, first_name, last_name, registered_at, last_active, invited_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name, now_iso(), now_iso(), referrer_id))
        
        db.execute('INSERT INTO analytics (event_type, user_id, data, created_at) VALUES (?, ?, ?, ?)',
                   ('registration', user.id, json.dumps({'referrer': referrer_id}), now_iso()))
    else:
        db.execute('UPDATE users SET last_active=?, username=? WHERE tg_id=?', 
                   (now_iso(), user.username, user.id))
    
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
    text = "📦 **Каталог товаров**\n\nВыберите категорию:"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_catalog_inline_keyboard())

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='catalog')]])
        )
        return
    
    await query.message.edit_text(
        f"{category['emoji']} **{category['name']}**\n\n{category['description'] or ''}\n\nНайдено товаров: {len(products)}",
        parse_mode='Markdown'
    )
    
    for product in products[:10]:
        await send_product_card(query.message, product, context)

async def send_product_card(message, product: Dict, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            await message.reply_photo(photo=product['photo'], caption=caption, parse_mode='Markdown', reply_markup=kb)
        except:
            await message.reply_text(caption, parse_mode='Markdown', reply_markup=kb)
    else:
        await message.reply_text(caption, parse_mode='Markdown', reply_markup=kb)

async def product_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.split(':')[1])
    product = db.fetchone('SELECT * FROM products WHERE id=?', (product_id,))
    
    if not product:
        await query.message.reply_text("Товар не найден.")
        return
    
    db.execute('UPDATE products SET views_count = views_count + 1 WHERE id=?', (product_id,))
    
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
            text_preview = (r['text'][:50] + '...') if r['text'] and len(r['text']) > 50 else (r['text'] or '')
            caption += f"{stars} {name}: {text_preview}\n"
    
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🛍 Открыть каталог', callback_data='catalog')]])
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
            InlineKeyboardButton("➖", callback_data=f"cart_minus:{item['product_id']}"),
            InlineKeyboardButton(f"{item['quantity']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart_plus:{item['product_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"cart_remove:{item['product_id']}")
        ])

    text += f"━━━━━━━━━━━━━━━\n💰 **Итого: {total}₽**"

    if user_db['balance'] > 0:
        text += f"\n💎 Ваш баланс: {user_db['balance']}₽"

    buttons.append([InlineKeyboardButton('🗑 Очистить корзину', callback_data='cart_clear')])
    buttons.append([InlineKeyboardButton(f'✅ Оформить заказ на {total}₽', callback_data='checkout')])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))


# === Обработка нажатий на кнопки: ➕➖🗑 и Очистить ===
async def cart_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    user = query.from_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    if not user_db:
        return

    if data.startswith("cart_minus:"):
        product_id = int(data.split(":")[1])
        item = db.fetchone('SELECT quantity FROM cart WHERE user_id=? AND product_id=?', (user_db['id'], product_id))
        if item:
            if item['quantity'] <= 1:
                db.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', (user_db['id'], product_id))
            else:
                db.execute('UPDATE cart SET quantity=quantity-1 WHERE user_id=? AND product_id=?', (user_db['id'], product_id))
        await cart_handler(update, context)

    elif data.startswith("cart_plus:"):
        product_id = int(data.split(":")[1])
        db.execute('UPDATE cart SET quantity=quantity+1 WHERE user_id=? AND product_id=?', (user_db['id'], product_id))
        await cart_handler(update, context)

    elif data.startswith("cart_remove:"):
        product_id = int(data.split(":")[1])
        db.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', (user_db['id'], product_id))
        await cart_handler(update, context)

    elif data == "cart_clear":
        db.execute('DELETE FROM cart WHERE user_id=?', (user_db['id'],))
        await query.message.edit_text("🗑 Корзина очищена!")

    elif data == "noop":
        pass  # ничего не делаем


# === Хендлер на callback "checkout" (оформление заказа) ===
async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("✅ Для оформления заказа перейдите в WebApp и нажмите «Оформить заказ» внутри корзины.", reply_markup=get_main_menu(query.from_user.id))


# === РЕГИСТРАЦИЯ ВСЕХ ХЕНДЛЕРОВ В ПРИЛОЖЕНИИ ===
def build_bot_app():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))

    app.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r"^product:"))
    app.add_handler(CallbackQueryHandler(add_to_cart_callback, pattern=r"^add_cart:"))
    app.add_handler(CallbackQueryHandler(checkout_callback, pattern=r"^checkout$"))

    app.add_handler(CallbackQueryHandler(cart_update_callback, pattern=r"^cart_(minus|plus|remove):"))
    app.add_handler(CallbackQueryHandler(cart_update_callback, pattern=r"^cart_clear$"))
    app.add_handler(CallbackQueryHandler(cart_update_callback, pattern=r"^noop$"))


    return app


# === ЗАПУСК ВЕБ-СЕРВЕРА И БОТА ===
def run_webapp():
    import uvicorn
    uvicorn.run(webapp, host=WEBAPP_HOST, port=WEBAPP_PORT, log_level="info")

def run_bot():
    application = build_bot_app()
    logger.info("🤖 Bot polling started...")
    application.run_polling()


# === ТОЧКА ВХОДА — ТОЛЬКО ОТКРЫТЬ ФАЙЛ И ЗАПУСТИТЬ ===
if __name__ == "__main__":
    print("🚀 Запуск Metro Shop: Telegram Bot + WebApp")
    print(f"📱 WebApp URL: {WEBAPP_URL}")
    print(f"🌐 Web Server: http://{WEBAPP_HOST}:{WEBAPP_PORT}")

    # Запускаем WebApp сервер в фоне
    web_thread = threading.Thread(target=run_webapp, daemon=True)
    web_thread.start()

    # Запускаем бота в основном потоке
    run_bot()
