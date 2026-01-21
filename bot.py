#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metro Shop Telegram Bot + WebApp Server - All-in-One
Единый файл для хостинга на bothost.ru
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
        tg.close();
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

function showCatalog() { setActiveNav(0); document.querySelector('.main-content').style.display = 'block'; }
function showFavorites() { setActiveNav(1); }
function showProfile() { setActiveNav(3); }

function setActiveNav(index) {
    document.querySelectorAll('.nav-item').forEach((item, i) => {
        item.classList.toggle('active', i === index);
    });
}

function escapeHtml(text) {
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
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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
                        except: pass
            except: pass
        
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

async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    
    subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
    
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
    
    balance_use = min(user_db['balance'], subtotal - discount)
    total = subtotal - discount - balance_use
    
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
    
    if balance_use > 0:
        db.execute('UPDATE users SET balance = balance - ? WHERE id=?', (balance_use, user_db['id']))
    
    db.execute('DELETE FROM cart WHERE user_id=?', (user_db['id'],))
    
    context.user_data['pending_order_id'] = order_id
    context.user_data.pop('promo_code', None)
    
    text = f"📋 **Заказ #{order_number}**\n\n📦 Товары:\n"
    for item in cart_items:
        text += f"• {item['name']} × {item['quantity']} = {item['price'] * item['quantity']}₽\n"
    
    text += f"\n━━━━━━━━━━━━━━━\nПодытог: {subtotal}₽\n"
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
        db.execute('UPDATE orders SET status=?, paid_at=? WHERE id=?', ('paid', now_iso(), order_id))
        await notify_admins_new_order(context, order_id)
        text += "\n✅ **Заказ оплачен балансом!**\nОжидайте выполнения."
        await query.message.reply_text(text, parse_mode='Markdown')

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_db = db.fetchone('SELECT * FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await update.message.reply_text("Напишите /start для регистрации")
        return
    
    orders_count = db.fetchone('SELECT COUNT(*) as cnt FROM orders WHERE user_id=?', (user_db['id'],))['cnt']
    total_spent_row = db.fetchone('SELECT SUM(total) as total FROM orders WHERE user_id=? AND status="completed"', (user_db['id'],))
    total_spent = total_spent_row['total'] or 0 if total_spent_row else 0
    
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
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await update.message.reply_text("Напишите /start для регистрации")
        return
    
    favorites_list = db.fetchall('''
        SELECT p.* FROM favorites f 
        JOIN products p ON f.product_id = p.id 
        WHERE f.user_id=? AND p.is_active=1
        ORDER BY f.added_at DESC
    ''', (user_db['id'],))
    
    if not favorites_list:
        await update.message.reply_text(
            "💝 **Избранное пусто**\n\nДобавляйте товары в избранное, нажимая ❤️",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(f"💝 **Избранное** ({len(favorites_list)} товаров):", parse_mode='Markdown')
    
    for product in favorites_list:
        await send_product_card(update.message, product, context)

async def toggle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    product_id = int(query.data.split(':')[1])
    
    user = query.from_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await query.answer("Ошибка. Напишите /start", show_alert=True)
        return
    
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
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        await update.message.reply_text("Напишите /start для регистрации")
        return
    
    orders = db.fetchall('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10', (user_db['id'],))
    
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
        
        buttons.append([InlineKeyboardButton(f"#{order['order_number']}", callback_data=f"order_detail:{order['id']}")])
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_db = db.fetchone('SELECT id FROM users WHERE tg_id=?', (user.id,))
    
    if not user_db:
        return
    
    pending_order = db.fetchone('''
        SELECT * FROM orders 
        WHERE user_id=? AND status='awaiting_payment' 
        ORDER BY created_at DESC LIMIT 1
    ''', (user_db['id'],))
    
    if not pending_order:
        return
    
    file_id = update.message.photo[-1].file_id
    
    db.execute('UPDATE orders SET status=?, payment_screenshot=? WHERE id=?', 
               ('pending', file_id, pending_order['id']))
    
    await update.message.reply_text(
        "✅ **Скриншот получен!**\n\nОжидайте подтверждения оплаты администратором.",
        parse_mode='Markdown',
        reply_markup=get_main_menu(user.id)
    )
    
    await notify_admins_new_order(context, pending_order['id'], file_id)

async def notify_admins_new_order(context: ContextTypes.DEFAULT_TYPE, order_id: int, screenshot: str = None) -> None:
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
    
    try:
        if screenshot:
            await context.bot.send_photo(ADMIN_CHAT_ID, screenshot, caption=text, parse_mode='Markdown', reply_markup=kb)
        else:
            await context.bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        logger.error(f"Failed to notify admins: {e}")

async def admin_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    action, order_id = query.data.split(':')
    order_id = int(order_id)
    
    order = db.fetchone('SELECT * FROM orders WHERE id=?', (order_id,))
    user = db.fetchone('SELECT * FROM users WHERE id=?', (order['user_id'],))
    
    if action == 'admin_confirm':
        db.execute('UPDATE orders SET status=?, paid_at=? WHERE id=?', ('paid', now_iso(), order_id))
        
        if user['invited_by'] and order['total'] > 0:
            bonus = order['total'] * REFERRAL_PERCENT
            db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (bonus, user['invited_by']))
            referrer = db.fetchone('SELECT tg_id FROM users WHERE id=?', (user['invited_by'],))
            if referrer:
                try:
                    await context.bot.send_message(referrer['tg_id'], f"💰 Вам начислено +{bonus:.2f}₽ за покупку реферала!")
                except: pass
        
        try:
            await context.bot.send_message(user['tg_id'], f"✅ **Оплата подтверждена!**\n\nЗаказ #{order['order_number']} принят в работу.", parse_mode='Markdown')
        except: pass
        
        try:
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
        except:
            await query.message.edit_text(
                text=query.message.text + "\n\n✅ **ОПЛАТА ПОДТВЕРЖДЕНА**",
                parse_mode='Markdown'
            )
        
    elif action == 'admin_reject':
        if order['balance_used'] > 0:
            db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (order['balance_used'], user['id']))
        
        db.execute('UPDATE orders SET status=?, cancelled_at=?, cancel_reason=? WHERE id=?',
                   ('cancelled', now_iso(), 'Payment rejected', order_id))
        
        try:
            msg = f"❌ Заказ #{order['order_number']} отклонен."
            if order['balance_used'] > 0:
                msg += "\nБаланс возвращен."
            await context.bot.send_message(user['tg_id'], msg)
        except: pass
        
        try:
            await query.message.edit_caption(
                caption=query.message.caption + "\n\n❌ **ОТКЛОНЕНО**",
                parse_mode='Markdown'
            )
        except:
            await query.message.edit_text(
                text=query.message.text + "\n\n❌ **ОТКЛОНЕНО**",
                parse_mode='Markdown'
            )

async def leave_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Функция отзывов в разработке", show_alert=True)

# ============== ADMIN PANEL FUNCTIONS ==============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("У вас нет доступа к этой функции")
        return

    text = """
⚙️ **Админ-панель**

Выберите раздел для управления:
"""
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_admin_keyboard())

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    # Основная статистика
    users_count = db.fetchone('SELECT COUNT(*) as count FROM users')['count']
    active_users = db.fetchone('SELECT COUNT(*) as count FROM users WHERE last_active >= ?',
                              (datetime.utcnow() - timedelta(days=7)).isoformat())['count']

    orders_count = db.fetchone('SELECT COUNT(*) as count FROM orders')['count']
    completed_orders = db.fetchone('SELECT COUNT(*) as count FROM orders WHERE status="completed"')['count']
    revenue = db.fetchone('SELECT SUM(total) as total FROM orders WHERE status="completed"')['total'] or 0

    products_count = db.fetchone('SELECT COUNT(*) as count FROM products WHERE is_active=1')['count']
    categories_count = db.fetchone('SELECT COUNT(*) as count FROM categories WHERE is_active=1')['count']

    text = f"""
📊 **Статистика сервиса**

👥 **Пользователи:**
• Всего: {users_count}
• Активных (7 дней): {active_users}

📦 **Заказы:**
• Всего: {orders_count}
• Завершено: {completed_orders}
• Выручка: {revenue:.2f}₽

🛍 **Товары:**
• Всего товаров: {products_count}
• Категорий: {categories_count}

💰 **Финансы:**
• Баланс системы: {revenue * (1 - WORKER_PERCENT):.2f}₽
• На выплаты: {revenue * WORKER_PERCENT:.2f}₽
"""

    buttons = [
        [InlineKeyboardButton('📈 Подробная аналитика', callback_data='detailed_stats')],
        [InlineKeyboardButton('🔄 Обновить', callback_data='refresh_stats')]
    ]
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    status_filter = context.user_data.get('order_status_filter', 'all')
    page = context.user_data.get('order_page', 1)
    per_page = 5

    query = 'SELECT * FROM orders'
    params = []

    if status_filter != 'all':
        query += ' WHERE status=?'
        params.append(status_filter)

    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([per_page, (page-1)*per_page])

    orders = db.fetchall(query, tuple(params))
    total_orders = db.fetchone('SELECT COUNT(*) as count FROM orders' + (' WHERE status=?' if status_filter != 'all' else ''),
                              (status_filter,) if status_filter != 'all' else ())['count']

    if not orders:
        await update.message.reply_text("Заказов не найдено")
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

    text = f"📦 **Все заказы** (страница {page}/{max(1, (total_orders + per_page - 1) // per_page)})\n\n"
    buttons = []

    for order in orders:
        emoji = status_emoji.get(order['status'], '❓')
        user = db.fetchone('SELECT username, first_name FROM users WHERE id=?', (order['user_id'],))
        username = user['username'] or user['first_name'] or 'Неизвестно'

        items = json.loads(order['items'])
        items_text = ', '.join([i['name'] for i in items[:2]])
        if len(items) > 2:
            items_text += f" +{len(items)-2}"

        text += f"{emoji} **#{order['order_number']}** ({order['status']})\n"
        text += f"   {username} | {order['total']}₽\n"
        text += f"   {items_text}\n\n"

        buttons.append([InlineKeyboardButton(f"#{order['order_number']}", callback_data=f"order_detail:{order['id']}")])

    # Пагинация
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton('⬅️ Назад', callback_data=f"orders_page:{page-1}"))
    if page * per_page < total_orders:
        pagination_buttons.append(InlineKeyboardButton('Вперед ➡️', callback_data=f"orders_page:{page+1}"))

    # Фильтры
    status_buttons = []
    for status in ['all', 'awaiting_payment', 'paid', 'in_progress', 'completed', 'cancelled']:
        emoji = status_emoji.get(status, '❓')
        status_buttons.append(InlineKeyboardButton(f"{emoji} {status.replace('_', ' ').title()}",
                                                  callback_data=f"orders_filter:{status}"))

    buttons.append(status_buttons)
    if pagination_buttons:
        buttons.append(pagination_buttons)

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    page = context.user_data.get('products_page', 1)
    per_page = 5

    products = db.fetchall('''
        SELECT p.*, c.name as category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        ORDER BY p.is_featured DESC, p.sold_count DESC
        LIMIT ? OFFSET ?
    ''', (per_page, (page-1)*per_page))

    total_products = db.fetchone('SELECT COUNT(*) as count FROM products')['count']

    if not products:
        await update.message.reply_text("Товаров не найдено")
        return

    text = f"📦 **Все товары** (страница {page}/{max(1, (total_products + per_page - 1) // per_page)})\n\n"
    buttons = []

    for product in products:
        status = "✅" if product['is_active'] else "❌"
        featured = "🔥" if product['is_featured'] else ""
        text += f"{status} {featured} **{product['name']}**\n"
        text += f"   Категория: {product['category_name'] or 'Без категории'}\n"
        text += f"   Цена: {product['price']}₽ | Продано: {product['sold_count']}\n\n"

        buttons.append([
            InlineKeyboardButton('✏️ Редактировать', callback_data=f"edit_product:{product['id']}"),
            InlineKeyboardButton('🗑 Удалить', callback_data=f"delete_product:{product['id']}")
        ])

    # Пагинация
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton('⬅️ Назад', callback_data=f"products_page:{page-1}"))
    if page * per_page < total_products:
        pagination_buttons.append(InlineKeyboardButton('Вперед ➡️', callback_data=f"products_page:{page+1}"))

    buttons.append([InlineKeyboardButton('➕ Добавить товар', callback_data='add_product')])
    if pagination_buttons:
        buttons.append(pagination_buttons)

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def add_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    context.user_data['adding_product'] = True
    context.user_data['product_data'] = {
        'name': '',
        'category_id': None,
        'price': 0,
        'old_price': 0,
        'description': '',
        'short_description': '',
        'photo': '',
        'stock': -1,
        'is_featured': False
    }

    categories = db.fetchall('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order')
    buttons = [[InlineKeyboardButton(cat['name'], callback_data=f"set_category:{cat['id']}")] for cat in categories]
    buttons.append([InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')])

    await update.message.reply_text(
        "📝 **Добавление нового товара**\n\nВыберите категорию:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def set_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split(':')[1])
    category = db.fetchone('SELECT * FROM categories WHERE id=?', (category_id,))

    context.user_data['product_data']['category_id'] = category_id

    await query.message.edit_text(
        f"📝 **Добавление товара**\n\nКатегория: {category['name']}\n\nВведите название товара:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]])
    )

async def product_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    context.user_data['product_data']['name'] = update.message.text

    await update.message.reply_text(
        "Введите цену товара (в рублях):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]])
    )

async def product_price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    try:
        price = float(update.message.text)
        context.user_data['product_data']['price'] = price

        await update.message.reply_text(
            "Введите старую цену (если есть скидка, иначе 0):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]])
        )
    except ValueError:
        await update.message.reply_text("Некорректная цена. Введите число.")

async def product_old_price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    try:
        old_price = float(update.message.text)
        context.user_data['product_data']['old_price'] = old_price

        await update.message.reply_text(
            "Введите краткое описание (для карточки товара):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]])
        )
    except ValueError:
        await update.message.reply_text("Некорректная цена. Введите число.")

async def product_short_desc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    context.user_data['product_data']['short_description'] = update.message.text

    await update.message.reply_text(
        "Введите полное описание товара:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]])
    )

async def product_desc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    context.user_data['product_data']['description'] = update.message.text

    await update.message.reply_text(
        "Отправьте фото товара (или нажмите 'Пропустить'):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('📎 Пропустить', callback_data='skip_photo')],
            [InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]
        ])
    )

async def product_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_product'):
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['product_data']['photo'] = file_id

    await confirm_product_creation(update, context)

async def skip_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    await confirm_product_creation(update, context)

async def confirm_product_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data['product_data']

    text = f"""
📝 **Подтверждение добавления товара**

Название: {data['name']}
Категория: {db.fetchone('SELECT name FROM categories WHERE id=?', (data['category_id'],))['name']}
Цена: {data['price']}₽
Старая цена: {data['old_price'] or 'Нет'}₽
Краткое описание: {data['short_description'] or 'Нет'}
Описание: {data['description'] or 'Нет'}
Фото: {'Есть' if data['photo'] else 'Нет'}
"""

    buttons = [
        [InlineKeyboardButton('✅ Добавить', callback_data='confirm_add_product')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_product')]
    ]

    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def confirm_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = context.user_data['product_data']

    product_id = db.execute('''
        INSERT INTO products (category_id, name, short_description, description, price, old_price,
                             photo, stock, is_active, is_featured, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
    ''', (
        data['category_id'],
        data['name'],
        data['short_description'],
        data['description'],
        data['price'],
        data['old_price'] if data['old_price'] > 0 else None,
        data['photo'],
        data['stock'],
        data['is_featured'],
        now_iso(),
        now_iso()
    ))

    context.user_data.pop('adding_product', None)
    context.user_data.pop('product_data', None)

    await query.message.edit_text(f"✅ Товар успешно добавлен! ID: {product_id}")

async def edit_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    product_id = int(query.data.split(':')[1])

    product = db.fetchone('SELECT * FROM products WHERE id=?', (product_id,))
    if not product:
        await query.answer("Товар не найден", show_alert=True)
        return

    context.user_data['editing_product'] = product_id
    context.user_data['product_data'] = {
        'name': product['name'],
        'category_id': product['category_id'],
        'price': product['price'],
        'old_price': product['old_price'] or 0,
        'description': product['description'],
        'short_description': product['short_description'],
        'photo': product['photo'],
        'stock': product['stock'],
        'is_featured': bool(product['is_featured']),
        'is_active': bool(product['is_active'])
    }

    categories = db.fetchall('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order')
    buttons = [[InlineKeyboardButton(cat['name'], callback_data=f"edit_set_category:{cat['id']}")] for cat in categories]
    buttons.append([InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')])

    await query.message.edit_text(
        f"📝 **Редактирование товара #{product_id}**\n\nТекущая категория: {db.fetchone('SELECT name FROM categories WHERE id=?', (product['category_id'],))['name']}\n\nВыберите новую категорию (или оставьте текущую):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def edit_set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split(':')[1])
    context.user_data['product_data']['category_id'] = category_id

    data = context.user_data['product_data']

    text = f"""
📝 **Редактирование товара**

Текущие значения:
Название: {data['name']}
Категория: {db.fetchone('SELECT name FROM categories WHERE id=?', (data['category_id'],))['name']}
Цена: {data['price']}₽
Старая цена: {data['old_price'] or 'Нет'}₽
Краткое описание: {data['short_description'] or 'Нет'}
Описание: {data['description'] or 'Нет'}
Фото: {'Есть' if data['photo'] else 'Нет'}
В наличии: {'Да' if data['stock'] != 0 else 'Нет'}
Рекомендуемый: {'Да' if data['is_featured'] else 'Нет'}
Активен: {'Да' if data['is_active'] else 'Нет'}

Выберите поле для редактирования:
"""

    buttons = [
        [InlineKeyboardButton('📛 Название', callback_data='edit_name')],
        [InlineKeyboardButton('💰 Цена', callback_data='edit_price')],
        [InlineKeyboardButton('🏷 Старая цена', callback_data='edit_old_price')],
        [InlineKeyboardButton('✏️ Краткое описание', callback_data='edit_short_desc')],
        [InlineKeyboardButton('📝 Полное описание', callback_data='edit_desc')],
        [InlineKeyboardButton('📷 Фото', callback_data='edit_photo')],
        [InlineKeyboardButton('📦 Наличие', callback_data='edit_stock')],
        [InlineKeyboardButton('🔥 Рекомендуемый', callback_data='edit_featured')],
        [InlineKeyboardButton('✅ Активность', callback_data='edit_active')],
        [InlineKeyboardButton('✅ Сохранить', callback_data='save_product')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]
    ]

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def edit_product_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    field = query.data.split('_')[1]
    data = context.user_data['product_data']

    if field == 'name':
        await query.message.edit_text(
            f"Текущее название: {data['name']}\n\nВведите новое название:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'name'
    elif field == 'price':
        await query.message.edit_text(
            f"Текущая цена: {data['price']}₽\n\nВведите новую цену:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'price'
    elif field == 'old_price':
        await query.message.edit_text(
            f"Текущая старая цена: {data['old_price'] or 0}₽\n\nВведите новую старую цену (или 0 для удаления):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'old_price'
    elif field == 'short_desc':
        await query.message.edit_text(
            f"Текущее краткое описание: {data['short_description'] or 'Нет'}\n\nВведите новое краткое описание:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'short_description'
    elif field == 'desc':
        await query.message.edit_text(
            f"Текущее описание: {data['description'] or 'Нет'}\n\nВведите новое описание:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'description'
    elif field == 'photo':
        await query.message.edit_text(
            "Отправьте новое фото товара (или нажмите 'Удалить'):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🗑 Удалить фото', callback_data='delete_photo')],
                [InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]
            ])
        )
        context.user_data['editing_field'] = 'photo'
    elif field == 'stock':
        await query.message.edit_text(
            f"Текущее количество: {'Неограничено' if data['stock'] == -1 else data['stock']}\n\nВведите новое количество (или -1 для неограниченного):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_product')]])
        )
        context.user_data['editing_field'] = 'stock'
    elif field == 'featured':
        data['is_featured'] = not data['is_featured']
        await edit_product_handler(update, context)
    elif field == 'active':
        data['is_active'] = not data['is_active']
        await edit_product_handler(update, context)

async def save_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    product_id = context.user_data['editing_product']
    data = context.user_data['product_data']

    db.execute('''
        UPDATE products SET
            category_id=?,
            name=?,
            short_description=?,
            description=?,
            price=?,
            old_price=?,
            photo=?,
            stock=?,
            is_featured=?,
            is_active=?,
            updated_at=?
        WHERE id=?
    ''', (
        data['category_id'],
        data['name'],
        data['short_description'],
        data['description'],
        data['price'],
        data['old_price'] if data['old_price'] > 0 else None,
        data['photo'],
        data['stock'],
        data['is_featured'],
        data['is_active'],
        now_iso(),
        product_id
    ))

    context.user_data.pop('editing_product', None)
    context.user_data.pop('product_data', None)

    await query.message.edit_text(f"✅ Товар #{product_id} успешно обновлен!")

async def delete_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    product_id = int(query.data.split(':')[1])

    product = db.fetchone('SELECT * FROM products WHERE id=?', (product_id,))
    if not product:
        await query.answer("Товар не найден", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton('✅ Да, удалить', callback_data=f"confirm_delete:{product_id}")],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_delete')]
    ]

    await query.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить товар **{product['name']}**?\n\nЭто действие нельзя отменить!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def confirm_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    product_id = int(query.data.split(':')[1])

    db.execute('DELETE FROM products WHERE id=?', (product_id,))

    await query.message.edit_text(f"✅ Товар #{product_id} успешно удален!")

async def admin_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    categories = db.fetchall('SELECT * FROM categories ORDER BY sort_order')

    if not categories:
        await update.message.reply_text("Категорий не найдено")
        return

    text = "📁 **Категории товаров**\n\n"
    buttons = []

    for cat in categories:
        status = "✅" if cat['is_active'] else "❌"
        text += f"{status} **{cat['name']}** {cat['emoji'] or ''}\n"
        text += f"   Описание: {cat['description'] or 'Нет'}\n"
        text += f"   Сортировка: {cat['sort_order']}\n\n"

        buttons.append([
            InlineKeyboardButton('✏️ Редактировать', callback_data=f"edit_category:{cat['id']}"),
            InlineKeyboardButton('🗑 Удалить', callback_data=f"delete_category:{cat['id']}")
        ])

    buttons.append([InlineKeyboardButton('➕ Добавить категорию', callback_data='add_category')])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def add_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    context.user_data['adding_category'] = True
    context.user_data['category_data'] = {
        'name': '',
        'emoji': '📦',
        'description': '',
        'sort_order': 0
    }

    await query.message.edit_text(
        "📝 **Добавление новой категории**\n\nВведите название категории:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_category')]])
    )

async def category_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_category'):
        return

    context.user_data['category_data']['name'] = update.message.text

    await update.message.reply_text(
        "Введите эмодзи для категории (например, 📦):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_category')]])
    )

async def category_emoji_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_category'):
        return

    context.user_data['category_data']['emoji'] = update.message.text

    await update.message.reply_text(
        "Введите описание категории:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_category')]])
    )

async def category_desc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_category'):
        return

    context.user_data['category_data']['description'] = update.message.text

    await update.message.reply_text(
        "Введите порядок сортировки (число, чем меньше - тем выше):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_category')]])
    )

async def category_sort_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_category'):
        return

    try:
        sort_order = int(update.message.text)
        context.user_data['category_data']['sort_order'] = sort_order

        await confirm_category_creation(update, context)
    except ValueError:
        await update.message.reply_text("Некорректное число. Введите целое число.")

async def confirm_category_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data['category_data']

    text = f"""
📝 **Подтверждение добавления категории**

Название: {data['name']}
Эмодзи: {data['emoji']}
Описание: {data['description'] or 'Нет'}
Порядок сортировки: {data['sort_order']}
"""

    buttons = [
        [InlineKeyboardButton('✅ Добавить', callback_data='confirm_add_category')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_category')]
    ]

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def confirm_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = context.user_data['category_data']

    category_id = db.execute('''
        INSERT INTO categories (name, emoji, description, sort_order, is_active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
    ''', (data['name'], data['emoji'], data['description'], data['sort_order'], now_iso()))

    context.user_data.pop('adding_category', None)
    context.user_data.pop('category_data', None)

    await query.message.edit_text(f"✅ Категория успешно добавлена! ID: {category_id}")

async def edit_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    category_id = int(query.data.split(':')[1])

    category = db.fetchone('SELECT * FROM categories WHERE id=?', (category_id,))
    if not category:
        await query.answer("Категория не найдена", show_alert=True)
        return

    context.user_data['editing_category'] = category_id
    context.user_data['category_data'] = {
        'name': category['name'],
        'emoji': category['emoji'] or '📦',
        'description': category['description'],
        'sort_order': category['sort_order'],
        'is_active': bool(category['is_active'])
    }

    text = f"""
📝 **Редактирование категории #{category_id}**

Текущие значения:
Название: {category['name']}
Эмодзи: {category['emoji'] or 'Нет'}
Описание: {category['description'] or 'Нет'}
Порядок сортировки: {category['sort_order']}
Активна: {'Да' if category['is_active'] else 'Нет'}

Выберите поле для редактирования:
"""

    buttons = [
        [InlineKeyboardButton('📛 Название', callback_data='edit_cat_name')],
        [InlineKeyboardButton('😊 Эмодзи', callback_data='edit_cat_emoji')],
        [InlineKeyboardButton('✏️ Описание', callback_data='edit_cat_desc')],
        [InlineKeyboardButton('🔢 Порядок', callback_data='edit_cat_sort')],
        [InlineKeyboardButton('✅ Активность', callback_data='edit_cat_active')],
        [InlineKeyboardButton('✅ Сохранить', callback_data='save_category')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_category')]
    ]

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def edit_category_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    field = query.data.split('_')[2]
    data = context.user_data['category_data']

    if field == 'name':
        await query.message.edit_text(
            f"Текущее название: {data['name']}\n\nВведите новое название:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_category')]])
        )
        context.user_data['editing_field'] = 'name'
    elif field == 'emoji':
        await query.message.edit_text(
            f"Текущий эмодзи: {data['emoji']}\n\nВведите новый эмодзи:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_category')]])
        )
        context.user_data['editing_field'] = 'emoji'
    elif field == 'desc':
        await query.message.edit_text(
            f"Текущее описание: {data['description'] or 'Нет'}\n\nВведите новое описание:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_category')]])
        )
        context.user_data['editing_field'] = 'description'
    elif field == 'sort':
        await query.message.edit_text(
            f"Текущий порядок: {data['sort_order']}\n\nВведите новый порядок сортировки:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_category')]])
        )
        context.user_data['editing_field'] = 'sort_order'
    elif field == 'active':
        data['is_active'] = not data['is_active']
        await edit_category_handler(update, context)

async def save_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    category_id = context.user_data['editing_category']
    data = context.user_data['category_data']

    db.execute('''
        UPDATE categories SET
            name=?,
            emoji=?,
            description=?,
            sort_order=?,
            is_active=?
        WHERE id=?
    ''', (data['name'], data['emoji'], data['description'], data['sort_order'], data['is_active'], category_id))

    context.user_data.pop('editing_category', None)
    context.user_data.pop('category_data', None)

    await query.message.edit_text(f"✅ Категория #{category_id} успешно обновлена!")

async def delete_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    category_id = int(query.data.split(':')[1])

    category = db.fetchone('SELECT * FROM categories WHERE id=?', (category_id,))
    if not category:
        await query.answer("Категория не найдена", show_alert=True)
        return

    # Проверяем, есть ли товары в этой категории
    products_count = db.fetchone('SELECT COUNT(*) as count FROM products WHERE category_id=?', (category_id,))['count']

    if products_count > 0:
        await query.answer(f"Нельзя удалить категорию с {products_count} товарами", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton('✅ Да, удалить', callback_data=f"confirm_delete_category:{category_id}")],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_delete_category')]
    ]

    await query.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить категорию **{category['name']}**?\n\nЭто действие нельзя отменить!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def confirm_delete_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    category_id = int(query.data.split(':')[1])

    db.execute('DELETE FROM categories WHERE id=?', (category_id,))

    await query.message.edit_text(f"✅ Категория #{category_id} успешно удалена!")

async def admin_promocodes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    promocodes = db.fetchall('SELECT * FROM promocodes ORDER BY created_at DESC')

    if not promocodes:
        await update.message.reply_text(
            "🏷 **Промокоды**\n\nПромокодов не найдено",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('➕ Добавить промокод', callback_data='add_promocode')]])
        )
        return

    text = "🏷 **Промокоды**\n\n"
    buttons = []

    for promo in promocodes:
        status = "✅" if promo['is_active'] else "❌"
        promo_type = "Процент" if promo['type'] == 'percent' else "Фиксированная сумма"
        text += f"{status} **{promo['code']}**\n"
        text += f"   Тип: {promo_type} | Значение: {promo['value']}{'%' if promo['type'] == 'percent' else '₽'}\n"
        text += f"   Использований: {promo['uses_count']}/{promo['uses_total'] if promo['uses_total'] > 0 else '∞'}\n"
        text += f"   Срок: {promo['valid_from'][:10]} - {promo['valid_until'][:10] if promo['valid_until'] else '∞'}\n\n"

        buttons.append([
            InlineKeyboardButton('✏️ Редактировать', callback_data=f"edit_promocode:{promo['id']}"),
            InlineKeyboardButton('🗑 Удалить', callback_data=f"delete_promocode:{promo['id']}")
        ])

    buttons.append([InlineKeyboardButton('➕ Добавить промокод', callback_data='add_promocode')])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def add_promocode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    context.user_data['adding_promocode'] = True
    context.user_data['promocode_data'] = {
        'code': '',
        'type': 'percent',
        'value': 10,
        'min_order': 0,
        'max_discount': 0,
        'uses_total': -1,
        'uses_per_user': 1,
        'valid_from': datetime.utcnow().isoformat(),
        'valid_until': (datetime.utcnow() + timedelta(days=30)).isoformat()
    }

    buttons = [
        [InlineKeyboardButton('Процент', callback_data='promo_type:percent')],
        [InlineKeyboardButton('Фиксированная сумма', callback_data='promo_type:fixed')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]
    ]

    await query.message.edit_text(
        "📝 **Добавление промокода**\n\nВыберите тип промокода:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def promocode_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    promo_type = query.data.split(':')[1]

    context.user_data['promocode_data']['type'] = promo_type

    await query.message.edit_text(
        f"Введите код промокода (например, SUMMER20):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
    )

async def promocode_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    code = update.message.text.upper()
    existing = db.fetchone('SELECT 1 FROM promocodes WHERE code=?', (code,))

    if existing:
        await update.message.reply_text("Промокод с таким кодом уже существует. Введите другой код:")
        return

    context.user_data['promocode_data']['code'] = code

    data = context.user_data['promocode_data']
    await update.message.reply_text(
        f"Введите значение промокода ({'%' if data['type'] == 'percent' else '₽'}):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
    )

async def promocode_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    try:
        value = float(update.message.text)
        context.user_data['promocode_data']['value'] = value

        await update.message.reply_text(
            "Введите минимальную сумму заказа для применения промокода (0 - без ограничений):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
        )
    except ValueError:
        await update.message.reply_text("Некорректное значение. Введите число.")

async def promocode_min_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    try:
        min_order = float(update.message.text)
        context.user_data['promocode_data']['min_order'] = min_order

        data = context.user_data['promocode_data']
        if data['type'] == 'percent':
            await update.message.reply_text(
                "Введите максимальную сумму скидки (0 - без ограничений):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
            )
        else:
            await update.message.reply_text(
                "Введите максимальное количество использований промокода (-1 - без ограничений):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
            )
    except ValueError:
        await update.message.reply_text("Некорректное значение. Введите число.")

async def promocode_max_discount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    try:
        max_discount = float(update.message.text)
        context.user_data['promocode_data']['max_discount'] = max_discount

        await update.message.reply_text(
            "Введите максимальное количество использований промокода (-1 - без ограничений):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
        )
    except ValueError:
        await update.message.reply_text("Некорректное значение. Введите число.")

async def promocode_uses_total_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    try:
        uses_total = int(update.message.text)
        context.user_data['promocode_data']['uses_total'] = uses_total

        await update.message.reply_text(
            "Введите максимальное количество использований промокода на одного пользователя:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]])
        )
    except ValueError:
        await update.message.reply_text("Некорректное значение. Введите целое число.")

async def promocode_uses_per_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('adding_promocode'):
        return

    try:
        uses_per_user = int(update.message.text)
        context.user_data['promocode_data']['uses_per_user'] = uses_per_user

        await confirm_promocode_creation(update, context)
    except ValueError:
        await update.message.reply_text("Некорректное значение. Введите целое число.")

async def confirm_promocode_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data['promocode_data']

    text = f"""
📝 **Подтверждение добавления промокода**

Код: `{data['code']}`
Тип: {'Процент' if data['type'] == 'percent' else 'Фиксированная сумма'}
Значение: {data['value']}{'%' if data['type'] == 'percent' else '₽'}
Минимальный заказ: {data['min_order']}₽
Макс. скидка: {data['max_discount'] or 'Нет ограничений'}₽
Использований всего: {data['uses_total'] if data['uses_total'] > 0 else '∞'}
Использований на пользователя: {data['uses_per_user']}
Срок действия: {data['valid_from'][:10]} - {data['valid_until'][:10]}
"""

    buttons = [
        [InlineKeyboardButton('✅ Добавить', callback_data='confirm_add_promocode')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_promocode')]
    ]

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def confirm_add_promocode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = context.user_data['promocode_data']

    promo_id = db.execute('''
        INSERT INTO promocodes (code, type, value, min_order, max_discount, uses_total,
                               uses_per_user, valid_from, valid_until, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    ''', (
        data['code'],
        data['type'],
        data['value'],
        data['min_order'],
        data['max_discount'] if data['max_discount'] > 0 else None,
        data['uses_total'],
        data['uses_per_user'],
        data['valid_from'],
        data['valid_until'],
        now_iso()
    ))

    context.user_data.pop('adding_promocode', None)
    context.user_data.pop('promocode_data', None)

    await query.message.edit_text(f"✅ Промокод успешно добавлен! ID: {promo_id}")

async def edit_promocode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    promo_id = int(query.data.split(':')[1])

    promo = db.fetchone('SELECT * FROM promocodes WHERE id=?', (promo_id,))
    if not promo:
        await query.answer("Промокод не найден", show_alert=True)
        return

    context.user_data['editing_promocode'] = promo_id
    context.user_data['promocode_data'] = {
        'code': promo['code'],
        'type': promo['type'],
        'value': promo['value'],
        'min_order': promo['min_order'],
        'max_discount': promo['max_discount'] or 0,
        'uses_total': promo['uses_total'],
        'uses_per_user': promo['uses_per_user'],
        'valid_from': promo['valid_from'],
        'valid_until': promo['valid_until'],
        'is_active': bool(promo['is_active'])
    }

    text = f"""
📝 **Редактирование промокода #{promo_id}**

Текущие значения:
Код: {promo['code']}
Тип: {'Процент' if promo['type'] == 'percent' else 'Фиксированная сумма'}
Значение: {promo['value']}{'%' if promo['type'] == 'percent' else '₽'}
Минимальный заказ: {promo['min_order']}₽
Макс. скидка: {promo['max_discount'] or 'Нет ограничений'}₽
Использований всего: {promo['uses_total'] if promo['uses_total'] > 0 else '∞'}
Использований на пользователя: {promo['uses_per_user']}
Срок действия: {promo['valid_from'][:10]} - {promo['valid_until'][:10] if promo['valid_until'] else '∞'}
Активен: {'Да' if promo['is_active'] else 'Нет'}

Выберите поле для редактирования:
"""

    buttons = [
        [InlineKeyboardButton('📛 Код', callback_data='edit_promo_code')],
        [InlineKeyboardButton('🔄 Тип', callback_data='edit_promo_type')],
        [InlineKeyboardButton('💰 Значение', callback_data='edit_promo_value')],
        [InlineKeyboardButton('📉 Мин. заказ', callback_data='edit_promo_min_order')],
        [InlineKeyboardButton('🏷 Макс. скидка', callback_data='edit_promo_max_discount')],
        [InlineKeyboardButton('🔢 Использований всего', callback_data='edit_promo_uses_total')],
        [InlineKeyboardButton('👥 Использований на пользователя', callback_data='edit_promo_uses_per_user')],
        [InlineKeyboardButton('📅 Срок действия', callback_data='edit_promo_dates')],
        [InlineKeyboardButton('✅ Активность', callback_data='edit_promo_active')],
        [InlineKeyboardButton('✅ Сохранить', callback_data='save_promocode')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]
    ]

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def edit_promocode_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    field = query.data.split('_')[2]
    data = context.user_data['promocode_data']

    if field == 'code':
        await query.message.edit_text(
            f"Текущий код: {data['code']}\n\nВведите новый код:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'code'
    elif field == 'type':
        buttons = [
            [InlineKeyboardButton('Процент', callback_data='set_promo_type:percent')],
            [InlineKeyboardButton('Фиксированная сумма', callback_data='set_promo_type:fixed')],
            [InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]
        ]
        await query.message.edit_text(
            "Выберите новый тип промокода:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    elif field == 'value':
        await query.message.edit_text(
            f"Текущее значение: {data['value']}{'%' if data['type'] == 'percent' else '₽'}\n\nВведите новое значение:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'value'
    elif field == 'min_order':
        await query.message.edit_text(
            f"Текущий минимальный заказ: {data['min_order']}₽\n\nВведите новое значение:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'min_order'
    elif field == 'max_discount':
        await query.message.edit_text(
            f"Текущая максимальная скидка: {data['max_discount'] or 'Нет ограничений'}₽\n\nВведите новое значение (0 - без ограничений):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'max_discount'
    elif field == 'uses_total':
        await query.message.edit_text(
            f"Текущее количество использований всего: {data['uses_total'] if data['uses_total'] > 0 else '∞'}\n\nВведите новое значение (-1 - без ограничений):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'uses_total'
    elif field == 'uses_per_user':
        await query.message.edit_text(
            f"Текущее количество использований на пользователя: {data['uses_per_user']}\n\nВведите новое значение:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'uses_per_user'
    elif field == 'dates':
        await query.message.edit_text(
            f"Текущий срок действия: {data['valid_from'][:10]} - {data['valid_until'][:10] if data['valid_until'] else '∞'}\n\nВведите новую дату окончания (YYYY-MM-DD или оставьте пустым для бессрочного):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_edit_promocode')]])
        )
        context.user_data['editing_field'] = 'valid_until'
    elif field == 'active':
        data['is_active'] = not data['is_active']
        await edit_promocode_handler(update, context)

async def set_promo_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    promo_type = query.data.split(':')[1]

    context.user_data['promocode_data']['type'] = promo_type
    await edit_promocode_handler(update, context)

async def save_promocode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    promo_id = context.user_data['editing_promocode']
    data = context.user_data['promocode_data']

    db.execute('''
        UPDATE promocodes SET
            code=?,
            type=?,
            value=?,
            min_order=?,
            max_discount=?,
            uses_total=?,
            uses_per_user=?,
            valid_from=?,
            valid_until=?,
            is_active=?
        WHERE id=?
    ''', (
        data['code'],
        data['type'],
        data['value'],
        data['min_order'],
        data['max_discount'] if data['max_discount'] > 0 else None,
        data['uses_total'],
        data['uses_per_user'],
        data['valid_from'],
        data['valid_until'],
        data['is_active'],
        promo_id
    ))

    context.user_data.pop('editing_promocode', None)
    context.user_data.pop('promocode_data', None)

    await query.message.edit_text(f"✅ Промокод #{promo_id} успешно обновлен!")

async def delete_promocode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    promo_id = int(query.data.split(':')[1])

    promo = db.fetchone('SELECT * FROM promocodes WHERE id=?', (promo_id,))
    if not promo:
        await query.answer("Промокод не найден", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton('✅ Да, удалить', callback_data=f"confirm_delete_promocode:{promo_id}")],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_delete_promocode')]
    ]

    await query.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить промокод **{promo['code']}**?\n\nЭто действие нельзя отменить!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def confirm_delete_promocode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    promo_id = int(query.data.split(':')[1])

    db.execute('DELETE FROM promocodes WHERE id=?', (promo_id,))

    await query.message.edit_text(f"✅ Промокод #{promo_id} успешно удален!")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    page = context.user_data.get('users_page', 1)
    per_page = 5

    users = db.fetchall('''
        SELECT * FROM users
        ORDER BY last_active DESC
        LIMIT ? OFFSET ?
    ''', (per_page, (page-1)*per_page))

    total_users = db.fetchone('SELECT COUNT(*) as count FROM users')['count']

    if not users:
        await update.message.reply_text("Пользователей не найдено")
        return

    text = f"👥 **Пользователи** (страница {page}/{max(1, (total_users + per_page - 1) // per_page)})\n\n"
    buttons = []

    for u in users:
        status = "🔒" if u['is_banned'] else "✅"
        vip = "👑" if u['vip_until'] and datetime.fromisoformat(u['vip_until']) > datetime.utcnow() else ""
        text += f"{status} {vip} **{u['first_name'] or 'Нет имени'}** (@{u['username'] or 'нет'})\n"
        text += f"   ID: `{u['tg_id']}` | Баланс: {u['balance']}₽\n"
        text += f"   Зарегистрирован: {u['registered_at'][:10]}\n"
        text += f"   Последняя активность: {u['last_active'][:10]}\n\n"

        buttons.append([
            InlineKeyboardButton('📊 Профиль', callback_data=f"user_profile:{u['id']}"),
            InlineKeyboardButton('📦 Заказы', callback_data=f"user_orders:{u['id']}"),
            InlineKeyboardButton('⚙️ Действия', callback_data=f"user_actions:{u['id']}")
        ])

    # Пагинация
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton('⬅️ Назад', callback_data=f"users_page:{page-1}"))
    if page * per_page < total_users:
        pagination_buttons.append(InlineKeyboardButton('Вперед ➡️', callback_data=f"users_page:{page+1}"))

    if pagination_buttons:
        buttons.append(pagination_buttons)

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def user_profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    orders_count = db.fetchone('SELECT COUNT(*) as count FROM orders WHERE user_id=?', (user_id,))['count']
    completed_orders = db.fetchone('SELECT COUNT(*) as count FROM orders WHERE user_id=? AND status="completed"', (user_id,))['count']
    total_spent = db.fetchone('SELECT SUM(total) as total FROM orders WHERE user_id=? AND status="completed"', (user_id,))['total'] or 0

    referrals_count = db.fetchone('SELECT COUNT(*) as count FROM users WHERE invited_by=?', (user_id,))['count']

    text = f"""
👤 **Профиль пользователя**

🆔 ID: `{user['tg_id']}`
📝 Имя: {user['first_name']} {user['last_name'] or ''}
📛 Username: @{user['username'] or 'нет'}
🎮 PUBG ID: {user['pubg_id'] or 'Не указан'}
📞 Телефон: {user['phone'] or 'Не указан'}

📅 В сервисе с: {user['registered_at'][:10]}
🔄 Последняя активность: {user['last_active'][:10]}

💰 **Финансы:**
Баланс: {user['balance']}₽
Потрачено: {total_spent}₽
Заказов: {orders_count} ({completed_orders} завершено)

👥 **Рефералы:**
Приглашено: {referrals_count}
Заработано: {total_spent * REFERRAL_PERCENT:.2f}₽

🔒 Статус: {'Забанен' if user['is_banned'] else 'Активен'}
👑 VIP: {'Да' if user['vip_until'] and datetime.fromisoformat(user['vip_until']) > datetime.utcnow() else 'Нет'}
"""

    buttons = [
        [InlineKeyboardButton('📦 Заказы пользователя', callback_data=f"user_orders:{user_id}")],
        [InlineKeyboardButton('⚙️ Действия', callback_data=f"user_actions:{user_id}")],
        [InlineKeyboardButton('⬅️ Назад', callback_data='admin_users')]
    ]

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def user_orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    orders = db.fetchall('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 5', (user_id,))

    if not orders:
        await query.message.edit_text(f"У пользователя @{user['username'] or user['first_name']} пока нет заказов")
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

    text = f"📦 **Заказы пользователя @{user['username'] or user['first_name']}**\n\n"
    buttons = []

    for order in orders:
        emoji = status_emoji.get(order['status'], '❓')
        items = json.loads(order['items'])
        items_text = ', '.join([i['name'] for i in items[:2]])
        if len(items) > 2:
            items_text += f" +{len(items)-2}"

        text += f"{emoji} **#{order['order_number']}** ({order['status']})\n"
        text += f"   {order['total']}₽ | {order['created_at'][:10]}\n"
        text += f"   {items_text}\n\n"

        buttons.append([InlineKeyboardButton(f"#{order['order_number']}", callback_data=f"order_detail:{order['id']}")])

    buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f"user_profile:{user_id}")])

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def user_actions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    text = f"⚙️ **Действия для пользователя @{user['username'] or user['first_name']}**\n\nВыберите действие:"

    buttons = [
        [InlineKeyboardButton('💰 Пополнить баланс', callback_data=f"add_balance:{user_id}")],
        [InlineKeyboardButton('💸 Вывести средства', callback_data=f"withdraw_balance:{user_id}")],
        [InlineKeyboardButton('👑 Выдать VIP', callback_data=f"grant_vip:{user_id}")],
        [InlineKeyboardButton('🔒 Забанить', callback_data=f"ban_user:{user_id}")],
        [InlineKeyboardButton('📞 Связаться', url=f"tg://user?id={user['tg_id']}")],
        [InlineKeyboardButton('⬅️ Назад', callback_data=f"user_profile:{user_id}")]
    ]

    if user['is_banned']:
        buttons.insert(3, [InlineKeyboardButton('🔓 Разбанить', callback_data=f"unban_user:{user_id}")])

    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def add_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    context.user_data['adding_balance'] = user_id

    await query.message.edit_text(
        "Введите сумму для пополнения баланса пользователя:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_add_balance')]])
    )

async def add_balance_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'adding_balance' not in context.user_data:
        return

    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError

        user_id = context.user_data['adding_balance']
        user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))

        db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (amount, user_id))

        # Логируем транзакцию
        db.execute('''
            INSERT INTO analytics (event_type, user_id, data, created_at)
            VALUES (?, ?, ?, ?)
        ''', ('balance_add', user_id, json.dumps({'amount': amount, 'admin_id': update.effective_user.id}), now_iso()))

        context.user_data.pop('adding_balance', None)

        await update.message.reply_text(
            f"✅ Баланс пользователя @{user['username'] or user['first_name']} пополнен на {amount}₽\n"
            f"Новый баланс: {user['balance'] + amount}₽",
            reply_markup=get_admin_keyboard()
        )

        try:
            await context.bot.send_message(
                user['tg_id'],
                f"💰 Ваш баланс пополнен на {amount}₽!\nНовый баланс: {user['balance'] + amount}₽"
            )
        except:
            pass

    except ValueError:
        await update.message.reply_text("Некорректная сумма. Введите положительное число.")

async def withdraw_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    if user['balance'] <= 0:
        await query.answer("У пользователя нет средств для вывода", show_alert=True)
        return

    context.user_data['withdrawing_balance'] = user_id

    await query.message.edit_text(
        f"Текущий баланс пользователя: {user['balance']}₽\n\nВведите сумму для вывода:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_withdraw_balance')]])
    )

async def withdraw_balance_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'withdrawing_balance' not in context.user_data:
        return

    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError

        user_id = context.user_data['withdrawing_balance']
        user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))

        if user['balance'] < amount:
            await update.message.reply_text("У пользователя недостаточно средств")
            return

        db.execute('UPDATE users SET balance = balance - ? WHERE id=?', (amount, user_id))

        # Логируем транзакцию
        db.execute('''
            INSERT INTO analytics (event_type, user_id, data, created_at)
            VALUES (?, ?, ?, ?)
        ''', ('balance_withdraw', user_id, json.dumps({'amount': amount, 'admin_id': update.effective_user.id}), now_iso()))

        context.user_data.pop('withdrawing_balance', None)

        await update.message.reply_text(
            f"✅ С баланса пользователя @{user['username'] or user['first_name']} списано {amount}₽\n"
            f"Новый баланс: {user['balance'] - amount}₽",
            reply_markup=get_admin_keyboard()
        )

        try:
            await context.bot.send_message(
                user['tg_id'],
                f"💸 С вашего баланса списано {amount}₽\nНовый баланс: {user['balance'] - amount}₽"
            )
        except:
            pass

    except ValueError:
        await update.message.reply_text("Некорректная сумма. Введите положительное число.")

async def grant_vip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    context.user_data['granting_vip'] = user_id

    buttons = [
        [InlineKeyboardButton('1 день', callback_data='vip_duration:1')],
        [InlineKeyboardButton('7 дней', callback_data='vip_duration:7')],
        [InlineKeyboardButton('30 дней', callback_data='vip_duration:30')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_grant_vip')]
    ]

    await query.message.edit_text(
        "Выберите продолжительность VIP-статуса:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def vip_duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    days = int(query.data.split(':')[1])

    user_id = context.user_data['granting_vip']
    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))

    vip_until = datetime.utcnow() + timedelta(days=days)
    db.execute('UPDATE users SET vip_until=? WHERE id=?', (vip_until.isoformat(), user_id))

    context.user_data.pop('granting_vip', None)

    await query.message.edit_text(
        f"✅ Пользователю @{user['username'] or user['first_name']} выдан VIP-статус до {vip_until.strftime('%d.%m.%Y')}",
        reply_markup=get_admin_keyboard()
    )

    try:
        await context.bot.send_message(
            user['tg_id'],
            f"👑 Вам выдан VIP-статус до {vip_until.strftime('%d.%m.%Y')}!\n"
            "Теперь вы можете пользоваться эксклюзивными преимуществами."
        )
    except:
        pass

async def ban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    db.execute('UPDATE users SET is_banned=1 WHERE id=?', (user_id,))

    await query.message.edit_text(
        f"✅ Пользователь @{user['username'] or user['first_name']} забанен",
        reply_markup=get_admin_keyboard()
    )

    try:
        await context.bot.send_message(
            user['tg_id'],
            "⚠️ Ваш аккаунт заблокирован. Обратитесь в поддержку для разблокировки."
        )
    except:
        pass

async def unban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = int(query.data.split(':')[1])

    user = db.fetchone('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    db.execute('UPDATE users SET is_banned=0 WHERE id=?', (user_id,))

    await query.message.edit_text(
        f"✅ Пользователь @{user['username'] or user['first_name']} разбанен",
        reply_markup=get_admin_keyboard()
    )

    try:
        await context.bot.send_message(
            user['tg_id'],
            "🎉 Ваш аккаунт разблокирован! Вы снова можете пользоваться сервисом."
        )
    except:
        pass

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    context.user_data['broadcasting'] = True

    buttons = [
        [InlineKeyboardButton('✅ С фото', callback_data='broadcast_with_photo')],
        [InlineKeyboardButton('📝 Только текст', callback_data='broadcast_text_only')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_broadcast')]
    ]

    await update.message.reply_text(
        "📢 **Рассылка сообщений**\n\nВыберите тип рассылки:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def broadcast_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    broadcast_type = query.data.split('_')[1]

    context.user_data['broadcast_type'] = broadcast_type

    if broadcast_type == 'with_photo':
        await query.message.edit_text(
            "Отправьте фото для рассылки (или нажмите 'Пропустить'):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('📎 Пропустить', callback_data='skip_broadcast_photo')],
                [InlineKeyboardButton('❌ Отмена', callback_data='cancel_broadcast')]
            ])
        )
    else:
        await query.message.edit_text(
            "Введите текст сообщения для рассылки:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_broadcast')]])
        )

async def broadcast_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('broadcasting'):
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['broadcast_photo'] = file_id

    await update.message.reply_text(
        "Введите текст сообщения для рассылки:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ Отмена', callback_data='cancel_broadcast')]])
    )

async def broadcast_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('broadcasting'):
        return

    context.user_data['broadcast_text'] = update.message.text

    await confirm_broadcast(update, context)

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data
    broadcast_type = data.get('broadcast_type', 'text_only')

    text = f"""
📢 **Подтверждение рассылки**

Тип: {'С фото' if broadcast_type == 'with_photo' else 'Только текст'}
Текст: {data['broadcast_text']}
Фото: {'Есть' if data.get('broadcast_photo') else 'Нет'}

⚠️ Сообщение будет отправлено ВСЕМ пользователям!
"""

    buttons = [
        [InlineKeyboardButton('✅ Отправить', callback_data='confirm_send_broadcast')],
        [InlineKeyboardButton('❌ Отмена', callback_data='cancel_broadcast')]
    ]

    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def confirm_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = context.user_data
    broadcast_type = data.get('broadcast_type', 'text_only')
    text = data['broadcast_text']
    photo = data.get('broadcast_photo')

    users = db.fetchall('SELECT tg_id FROM users')
    total_users = len(users)
    success_count = 0

    await query.message.edit_text(f"📢 Начинаем рассылку для {total_users} пользователей...")

    for user in users:
        try:
            if broadcast_type == 'with_photo' and photo:
                await context.bot.send_photo(user['tg_id'], photo, caption=text, parse_mode='Markdown')
            else:
                await context.bot.send_message(user['tg_id'], text, parse_mode='Markdown')
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user['tg_id']}: {e}")

    context.user_data.pop('broadcasting', None)
    context.user_data.pop('broadcast_type', None)
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('broadcast_photo', None)

    await query.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Отправлено: {success_count}/{total_users} пользователям"
    )

async def admin_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    payouts = db.fetchall('''
        SELECT wp.*, u.username, u.first_name, o.order_number
        FROM worker_payouts wp
        LEFT JOIN users u ON wp.worker_id = u.id
        LEFT JOIN orders o ON wp.order_id = o.id
        ORDER BY wp.created_at DESC
        LIMIT 20
    ''')

    if not payouts:
        await update.message.reply_text("Выплат не найдено")
        return

    text = "💰 **Выплаты исполнителям**\n\n"
    buttons = []

    for payout in payouts:
        status = "✅" if payout['status'] == 'paid' else "⏳" if payout['status'] == 'pending' else "❌"
        worker_name = payout['first_name'] or payout['username'] or 'Неизвестно'
        text += f"{status} **{worker_name}**\n"
        text += f"   Сумма: {payout['amount']}₽ | Заказ: #{payout['order_number'] or 'Нет'}\n"
        text += f"   Статус: {payout['status']} | {payout['created_at'][:10]}\n\n"

        if payout['status'] == 'pending':
            buttons.append([
                InlineKeyboardButton('✅ Выплачено', callback_data=f"mark_paid:{payout['id']}"),
                InlineKeyboardButton('❌ Отклонить', callback_data=f"reject_payout:{payout['id']}")
            ])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def mark_payout_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    payout_id = int(query.data.split(':')[1])

    payout = db.fetchone('SELECT * FROM worker_payouts WHERE id=?', (payout_id,))
    if not payout:
        await query.answer("Выплата не найдена", show_alert=True)
        return

    db.execute('UPDATE worker_payouts SET status=?, paid_at=? WHERE id=?', ('paid', now_iso(), payout_id))

    worker = db.fetchone('SELECT * FROM users WHERE id=?', (payout['worker_id'],))
    if worker:
        try:
            await context.bot.send_message(
                worker['tg_id'],
                f"💰 Вам выплачено {payout['amount']}₽ за выполнение заказа!"
            )
        except:
            pass

    await query.message.edit_text(f"✅ Выплата #{payout_id} отмечена как выплаченная")

async def reject_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    payout_id = int(query.data.split(':')[1])

    payout = db.fetchone('SELECT * FROM worker_payouts WHERE id=?', (payout_id,))
    if not payout:
        await query.answer("Выплата не найдена", show_alert=True)
        return

    db.execute('UPDATE worker_payouts SET status=? WHERE id=?', ('rejected', payout_id))

    await query.message.edit_text(f"❌ Выплата #{payout_id} отклонена")

# ============== UPDATE BOT APP WITH ADMIN HANDLERS ==============

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
        
    text = update.message.text.strip()
    user = update.effective_user
    
    if text == '🛍 Каталог' or text.startswith('🛍'):
        await catalog_handler(update, context)
    elif text == '🛒 Корзина':
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
        await update.message.reply_text(f"📞 **Поддержка**\n\nНаписать: {SUPPORT_CONTACT_USER}", parse_mode='Markdown')
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
        await update.message.reply_text(f"✅ PUBG ID сохранен: `{text}`", parse_mode='Markdown', reply_markup=get_main_menu(user.id))
    else:
        await update.message.reply_text("Используйте меню для навигации", reply_markup=get_main_menu(user.id))

        
        

def build_bot_app():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    # Основные хендлеры
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r'^cat:'))
    app.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r'^product:'))
    app.add_handler(CallbackQueryHandler(add_to_cart_callback, pattern=r'^add_cart:'))
    app.add_handler(CallbackQueryHandler(toggle_favorite_callback, pattern=r'^toggle_fav:'))
    app.add_handler(CallbackQueryHandler(checkout_callback, pattern=r'^checkout'))
    app.add_handler(CallbackQueryHandler(admin_order_action, pattern=r'^admin_'))
    app.add_handler(CallbackQueryHandler(leave_review_callback, pattern=r'^leave_review:'))

    # Админ хендлеры
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    # Админ-панель
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^⚙️ Админ-панель$'), admin_panel))

    # Статистика
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📊 Статистика$'), admin_stats))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern=r'^refresh_stats$'))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern=r'^detailed_stats$'))

    # Заказы
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📦 Все заказы$'), admin_orders))
    app.add_handler(CallbackQueryHandler(admin_orders, pattern=r'^orders_page:'))
    app.add_handler(CallbackQueryHandler(admin_orders, pattern=r'^orders_filter:'))

    # Товары
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^➕ Добавить товар$'), admin_products))
    app.add_handler(CallbackQueryHandler(admin_products, pattern=r'^products_page:'))
    app.add_handler(CallbackQueryHandler(add_product_handler, pattern=r'^add_product$'))
    app.add_handler(CallbackQueryHandler(set_product_category, pattern=r'^set_category:'))
    app.add_handler(CallbackQueryHandler(confirm_product_creation, pattern=r'^confirm_add_product$'))
    app.add_handler(CallbackQueryHandler(cancel_add_product, pattern=r'^cancel_add_product$'))
    app.add_handler(CallbackQueryHandler(edit_product_handler, pattern=r'^edit_product:'))
    app.add_handler(CallbackQueryHandler(edit_set_category, pattern=r'^edit_set_category:'))
    app.add_handler(CallbackQueryHandler(save_product_handler, pattern=r'^save_product$'))
    app.add_handler(CallbackQueryHandler(delete_product_handler, pattern=r'^delete_product:'))
    app.add_handler(CallbackQueryHandler(confirm_delete_product, pattern=r'^confirm_delete:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, product_name_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, product_price_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, product_old_price_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, product_short_desc_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, product_desc_handler))
    app.add_handler(MessageHandler(filters.PHOTO, product_photo_handler))
    app.add_handler(CallbackQueryHandler(skip_photo_handler, pattern=r'^skip_photo$'))
    app.add_handler(CallbackQueryHandler(edit_product_field, pattern=r'^edit_'))
    app.add_handler(CallbackQueryHandler(cancel_edit_product, pattern=r'^cancel_edit_product$'))

    # Категории
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📁 Категории$'), admin_categories))
    app.add_handler(CallbackQueryHandler(add_category_handler, pattern=r'^add_category$'))
    app.add_handler(CallbackQueryHandler(confirm_add_category, pattern=r'^confirm_add_category$'))
    app.add_handler(CallbackQueryHandler(cancel_add_category, pattern=r'^cancel_add_category$'))
    app.add_handler(CallbackQueryHandler(edit_category_handler, pattern=r'^edit_category:'))
    app.add_handler(CallbackQueryHandler(edit_category_field, pattern=r'^edit_cat_'))
    app.add_handler(CallbackQueryHandler(save_category_handler, pattern=r'^save_category$'))
    app.add_handler(CallbackQueryHandler(delete_category_handler, pattern=r'^delete_category:'))
    app.add_handler(CallbackQueryHandler(confirm_delete_category, pattern=r'^confirm_delete_category:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, category_name_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, category_emoji_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, category_desc_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, category_sort_order_handler))

    # Промокоды
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🏷 Промокоды$'), admin_promocodes))
    app.add_handler(CallbackQueryHandler(add_promocode_handler, pattern=r'^add_promocode$'))
    app.add_handler(CallbackQueryHandler(promocode_type_handler, pattern=r'^promo_type:'))
    app.add_handler(CallbackQueryHandler(confirm_add_promocode, pattern=r'^confirm_add_promocode$'))
    app.add_handler(CallbackQueryHandler(cancel_add_promocode, pattern=r'^cancel_add_promocode$'))
    app.add_handler(CallbackQueryHandler(edit_promocode_handler, pattern=r'^edit_promocode:'))
    app.add_handler(CallbackQueryHandler(edit_promocode_field, pattern=r'^edit_promo_'))
    app.add_handler(CallbackQueryHandler(set_promo_type, pattern=r'^set_promo_type:'))
    app.add_handler(CallbackQueryHandler(save_promocode_handler, pattern=r'^save_promocode$'))
    app.add_handler(CallbackQueryHandler(delete_promocode_handler, pattern=r'^delete_promocode:'))
    app.add_handler(CallbackQueryHandler(confirm_delete_promocode, pattern=r'^confirm_delete_promocode:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_code_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_value_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_min_order_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_max_discount_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_uses_total_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, promocode_uses_per_user_handler))

    # Пользователи
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^👥 Пользователи$'), admin_users))
    app.add_handler(CallbackQueryHandler(admin_users, pattern=r'^users_page:'))
    app.add_handler(CallbackQueryHandler(user_profile_handler, pattern=r'^user_profile:'))
    app.add_handler(CallbackQueryHandler(user_orders_handler, pattern=r'^user_orders:'))
    app.add_handler(CallbackQueryHandler(user_actions_handler, pattern=r'^user_actions:'))
    app.add_handler(CallbackQueryHandler(add_balance_handler, pattern=r'^add_balance:'))
    app.add_handler(CallbackQueryHandler(withdraw_balance_handler, pattern=r'^withdraw_balance:'))
    app.add_handler(CallbackQueryHandler(grant_vip_handler, pattern=r'^grant_vip:'))
    app.add_handler(CallbackQueryHandler(ban_user_handler, pattern=r'^ban_user:'))
    app.add_handler(CallbackQueryHandler(unban_user_handler, pattern=r'^unban_user:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_balance_amount_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_balance_amount_handler))
    app.add_handler(CallbackQueryHandler(vip_duration_handler, pattern=r'^vip_duration:'))
    app.add_handler(CallbackQueryHandler(cancel_add_balance, pattern=r'^cancel_add_balance$'))
    app.add_handler(CallbackQueryHandler(cancel_withdraw_balance, pattern=r'^cancel_withdraw_balance$'))
    app.add_handler(CallbackQueryHandler(cancel_grant_vip, pattern=r'^cancel_grant_vip$'))

    # Рассылка
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^📢 Рассылка$'), admin_broadcast))
    app.add_handler(CallbackQueryHandler(broadcast_type_handler, pattern=r'^broadcast_'))
    app.add_handler(MessageHandler(filters.PHOTO, broadcast_photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text_handler))
    app.add_handler(CallbackQueryHandler(confirm_send_broadcast, pattern=r'^confirm_send_broadcast$'))
    app.add_handler(CallbackQueryHandler(cancel_broadcast, pattern=r'^cancel_broadcast$'))
    app.add_handler(CallbackQueryHandler(skip_broadcast_photo, pattern=r'^skip_broadcast_photo$'))

    # Выплаты
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💰 Выплаты$'), admin_payouts))
    app.add_handler(CallbackQueryHandler(mark_payout_paid, pattern=r'^mark_paid:'))
    app.add_handler(CallbackQueryHandler(reject_payout, pattern=r'^reject_payout:'))

    # Отмена действий
    app.add_handler(CallbackQueryHandler(cancel_action, pattern=r'^cancel_'))
    
    return app

# ============== MAIN ==============
def run_webapp():
    import uvicorn
    uvicorn.run(webapp, host=WEBAPP_HOST, port=WEBAPP_PORT, log_level="info")

def run_bot():
    application = build_bot_app()
    application.run_polling()

if __name__ == "__main__":
    print("🚀 Starting Metro Shop Bot + WebApp Server...")
    print(f"📱 WebApp URL: {WEBAPP_URL}")
    print(f"🌐 Server: http://{WEBAPP_HOST}:{WEBAPP_PORT}")
    
    # Start webapp in separate thread
    webapp_thread = threading.Thread(target=run_webapp, daemon=True)
    webapp_thread.start()
    
    # Run bot in main thread
    run_bot()
