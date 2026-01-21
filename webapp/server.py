#!/usr/bin/env python3
"""
Metro Shop WebApp Server
FastAPI backend for Telegram Mini App
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
import uvicorn

import sys
sys.path.append('..')
from config import *

app = FastAPI(title="Metro Shop WebApp API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp initData"""
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop('hash', '')
        
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
        
        if hmac.compare_digest(calculated_hash, received_hash):
            user_data = json.loads(parsed.get('user', '{}'))
            return user_data
        return None
    except Exception as e:
        print(f"Validation error: {e}")
        return None

async def get_current_user(request: Request):
    """Dependency to get current user from initData"""
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return user

# --- Models ---
class CartItem(BaseModel):
    product_id: int
    quantity: int = 1

class CheckoutRequest(BaseModel):
    promo_code: Optional[str] = None
    use_balance: bool = True
    pubg_id: Optional[str] = None

# --- Routes ---

@app.get("/api/categories")
async def get_categories():
    """Get all active categories"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order')
    categories = [dict(row) for row in cur.fetchall()]
    conn.close()
    return categories

@app.get("/api/products")
async def get_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    sort: str = "popular",
    limit: int = 20,
    offset: int = 0
):
    """Get products with filters"""
    conn = get_db()
    cur = conn.cursor()
    
    query = "SELECT * FROM products WHERE is_active=1"
    params = []
    
    if category_id:
        query += " AND category_id=?"
        params.append(category_id)
    
    if search:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    # Sorting
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
    
    cur.execute(query, params)
    products = [dict(row) for row in cur.fetchall()]
    
    # Parse JSON fields
    for p in products:
        p['photos'] = json.loads(p.get('photos', '[]'))
        p['tags'] = json.loads(p.get('tags', '[]'))
        p['meta'] = json.loads(p.get('meta', '{}'))
    
    conn.close()
    return products

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    """Get single product details"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT * FROM products WHERE id=? AND is_active=1', (product_id,))
    row = cur.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    
    product = dict(row)
    product['photos'] = json.loads(product.get('photos', '[]'))
    product['tags'] = json.loads(product.get('tags', '[]'))
    
    # Get reviews
    cur.execute('''
        SELECT r.*, u.first_name, u.username 
        FROM reviews r 
        JOIN users u ON r.user_id = u.id
        WHERE r.product_id=? AND r.is_visible=1 
        ORDER BY r.created_at DESC LIMIT 5
    ''', (product_id,))
    product['reviews'] = [dict(r) for r in cur.fetchall()]
    
    # Update views
    cur.execute('UPDATE products SET views_count = views_count + 1 WHERE id=?', (product_id,))
    conn.commit()
    conn.close()
    
    return product

@app.get("/api/cart")
async def get_cart(user: dict = Depends(get_current_user)):
    """Get user's cart"""
    conn = get_db()
    cur = conn.cursor()
    
    # Get user id
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    if not user_row:
        return {"items": [], "total": 0}
    
    user_id = user_row['id']
    
    cur.execute('''
        SELECT c.*, p.name, p.price, p.photo, p.stock
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=?
    ''', (user_id,))
    
    items = [dict(row) for row in cur.fetchall()]
    total = sum(item['price'] * item['quantity'] for item in items)
    
    conn.close()
    return {"items": items, "total": total}

@app.post("/api/cart/add")
async def add_to_cart(item: CartItem, user: dict = Depends(get_current_user)):
    """Add item to cart"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_id = user_row['id']
    
    # Check if already in cart
    cur.execute('SELECT id, quantity FROM cart WHERE user_id=? AND product_id=?', 
                (user_id, item.product_id))
    existing = cur.fetchone()
    
    if existing:
        cur.execute('UPDATE cart SET quantity=? WHERE id=?', 
                    (existing['quantity'] + item.quantity, existing['id']))
    else:
        from datetime import datetime
        cur.execute('INSERT INTO cart (user_id, product_id, quantity, added_at) VALUES (?, ?, ?, ?)',
                    (user_id, item.product_id, item.quantity, datetime.utcnow().isoformat()))
    
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/cart/update")
async def update_cart(item: CartItem, user: dict = Depends(get_current_user)):
    """Update cart item quantity"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    user_id = user_row['id']
    
    if item.quantity <= 0:
        cur.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', 
                    (user_id, item.product_id))
    else:
        cur.execute('UPDATE cart SET quantity=? WHERE user_id=? AND product_id=?',
                    (item.quantity, user_id, item.product_id))
    
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/cart/{product_id}")
async def remove_from_cart(product_id: int, user: dict = Depends(get_current_user)):
    """Remove item from cart"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    
    cur.execute('DELETE FROM cart WHERE user_id=? AND product_id=?',
                (user_row['id'], product_id))
    
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/user/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """Get user profile"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT * FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile = dict(user_row)
    
    # Get order stats
    cur.execute('SELECT COUNT(*) as count FROM orders WHERE user_id=?', (profile['id'],))
    profile['orders_count'] = cur.fetchone()['count']
    
    conn.close()
    return profile

@app.get("/api/favorites")
async def get_favorites(user: dict = Depends(get_current_user)):
    """Get user's favorites"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_row = cur.fetchone()
    
    cur.execute('''
        SELECT p.* FROM favorites f
        JOIN products p ON f.product_id = p.id
        WHERE f.user_id=? AND p.is_active=1
    ''', (user_row['id'],))
    
    favorites = [dict(row) for row in cur.fetchall()]
    conn.close()
    return favorites

@app.post("/api/favorites/{product_id}")
async def toggle_favorite(product_id: int, user: dict = Depends(get_current_user)):
    """Toggle product in favorites"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id FROM users WHERE tg_id=?', (user['id'],))
    user_id = cur.fetchone()['id']
    
    cur.execute('SELECT id FROM favorites WHERE user_id=? AND product_id=?',
                (user_id, product_id))
    existing = cur.fetchone()
    
    if existing:
        cur.execute('DELETE FROM favorites WHERE id=?', (existing['id'],))
        is_favorite = False
    else:
        from datetime import datetime
        cur.execute('INSERT INTO favorites (user_id, product_id, added_at) VALUES (?, ?, ?)',
                    (user_id, product_id, datetime.utcnow().isoformat()))
        is_favorite = True
    
    conn.commit()
    conn.close()
    return {"is_favorite": is_favorite}

# Serve static files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host=WEBAPP_HOST, port=WEBAPP_PORT)
