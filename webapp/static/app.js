// Telegram WebApp
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// Apply Telegram theme
document.documentElement.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#ffffff');
document.documentElement.style.setProperty('--tg-theme-text-color', tg.themeParams.text_color || '#000000');
document.documentElement.style.setProperty('--tg-theme-hint-color', tg.themeParams.hint_color || '#999999');
document.documentElement.style.setProperty('--tg-theme-link-color', tg.themeParams.link_color || '#2481cc');
document.documentElement.style.setProperty('--tg-theme-button-color', tg.themeParams.button_color || '#2481cc');
document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', tg.themeParams.secondary_bg_color || '#f1f1f1');

// State
let currentCategory = 'all';
let currentSort = 'popular';
let products = [];
let cart = [];
let favorites = [];

// API Base URL
const API_URL = '/api';

// Helper function for API calls
async function api(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-Telegram-Init-Data': tg.initData
        }
    };
    
    const response = await fetch(`${API_URL}${endpoint}`, { ...defaultOptions, ...options });
    
    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }
    
    return response.json();
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await loadCategories();
    await loadProducts();
    await loadCart();
    await loadFavorites();
});

// Load Categories
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

// Select Category
async function selectCategory(categoryId) {
    currentCategory = categoryId;
    
    // Update UI
    document.querySelectorAll('.category-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.id == categoryId);
    });
    
    await loadProducts();
}

// Load Products
async function loadProducts() {
    const loading = document.getElementById('loadingIndicator');
    const grid = document.getElementById('productsGrid');
    
    loading.classList.add('active');
    grid.innerHTML = '';
    
    try {
        let endpoint = `/products?sort=${currentSort}`;
        if (currentCategory !== 'all') {
            endpoint += `&category_id=${currentCategory}`;
        }
        
        products = await api(endpoint);
        renderProducts(products);
    } catch (error) {
        console.error('Failed to load products:', error);
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1">
                <i class="fas fa-exclamation-circle"></i>
                <h3>Ошибка загрузки</h3>
                <p>Не удалось загрузить товары</p>
            </div>
        `;
    } finally {
        loading.classList.remove('active');
    }
}

// Render Products
function renderProducts(products) {
    const grid = document.getElementById('productsGrid');
    
    if (products.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1">
                <i class="fas fa-box-open"></i>
                <h3>Товаров не найдено</h3>
                <p>Попробуйте выбрать другую категорию</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = products.map(product => {
        const isFav = favorites.includes(product.id);
        const hasDiscount = product.old_price && product.old_price > product.price;
        const discount = hasDiscount ? Math.round((1 - product.price / product.old_price) * 100) : 0;
        
        return `
            <div class="product-card" onclick="openProduct(${product.id})">
                <img class="product-image" 
                     src="${product.photo || 'https://via.placeholder.com/200x200?text=No+Image'}" 
                     alt="${product.name}"
                     onerror="this.src='https://via.placeholder.com/200x200?text=No+Image'">
                <div class="product-info">
                    <div class="product-name">${escapeHtml(product.name)}</div>
                    <div class="product-price">
                        <span class="current-price">${product.price}₽</span>
                        ${hasDiscount ? `
                            <span class="old-price">${product.old_price}₽</span>
                            <span class="discount-badge">-${discount}%</span>
                        ` : ''}
                    </div>
                    <div class="product-meta">
                        ${product.rating > 0 ? `
                            <span class="product-rating">
                                <i class="fas fa-star"></i> ${product.rating.toFixed(1)}
                            </span>
                        ` : ''}
                        <span>🛒 ${product.sold_count}</span>
                    </div>
                    <div class="product-actions" onclick="event.stopPropagation()">
                        <button class="btn-cart" onclick="addToCart(${product.id})">
                            <i class="fas fa-cart-plus"></i> В корзину
                        </button>
                        <button class="btn-fav ${isFav ? 'active' : ''}" onclick="toggleFavorite(${product.id})">
                            <i class="fas fa-heart"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Sort Products
async function sortProducts() {
    currentSort = document.getElementById('sortSelect').value;
    await loadProducts();
}

// Open Product Detail
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
                <img src="${product.photo || 'https://via.placeholder.com/400x400?text=No+Image'}" 
                     alt="${product.name}">
            </div>
            <div class="detail-content">
                <h1>${escapeHtml(product.name)}</h1>
                <div class="detail-price">
                    <span class="current-price">${product.price}₽</span>
                    ${hasDiscount ? `
                        <span class="old-price">${product.old_price}₽</span>
                        <span class="discount-badge">-${discount}%</span>
                    ` : ''}
                </div>
                <div class="detail-stats">
                    <div class="stat-item">
                        <div class="stat-value">${product.sold_count}</div>
                        <div class="stat-label">Продано</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${product.views_count}</div>
                        <div class="stat-label">Просмотров</div>
                    </div>
                    ${product.rating > 0 ? `
                        <div class="stat-item">
                            <div class="stat-value">⭐ ${product.rating.toFixed(1)}</div>
                            <div class="stat-label">${product.reviews_count} отзывов</div>
                        </div>
                    ` : ''}
                </div>
                <div class="detail-description">
                    ${escapeHtml(product.description || product.short_description || 'Описание отсутствует')}
                </div>
                ${product.reviews && product.reviews.length > 0 ? `
                    <h3>Отзывы</h3>
                    ${product.reviews.map(r => `
                        <div style="padding: 12px; background: var(--tg-theme-secondary-bg-color); border-radius: 8px; margin-top: 8px;">
                            <div><strong>${r.first_name || 'Аноним'}</strong> ${'⭐'.repeat(r.rating)}</div>
                            <div style="color: var(--tg-theme-hint-color); font-size: 13px; margin-top: 4px;">${escapeHtml(r.text || '')}</div>
                        </div>
                    `).join('')}
                ` : ''}
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
        console.error('Failed to load product:', error);
        detail.innerHTML = '<p>Ошибка загрузки товара</p>';
    }
}

function closeProductModal() {
    document.getElementById('productModal').classList.remove('open');
}

// Cart Functions
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
        
        // Haptic feedback
        tg.HapticFeedback.impactOccurred('light');
        
        // Show notification
        tg.showPopup({
            title: 'Добавлено!',
            message: 'Товар добавлен в корзину',
            buttons: [{ type: 'ok' }]
        });
        
        await loadCart();
    } catch (error) {
        console.error('Failed to add to cart:', error);
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
        content.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-shopping-cart"></i>
                <h3>Корзина пуста</h3>
                <p>Добавьте товары из каталога</p>
            </div>
        `;
        return;
    }
    
    const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
    
    content.innerHTML = `
        <div class="cart-content">
            ${cart.map(item => `
                <div class="cart-item">
                    <img class="cart-item-image" 
                         src="${item.photo || 'https://via.placeholder.com/60x60?text=No+Image'}" 
                         alt="${item.name}">
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
        <div class="cart-total">
            <span>Итого:</span>
            <span>${total}₽</span>
        </div>
        <div class="cart-checkout">
            <button class="btn-checkout" onclick="checkout()">
                Оформить заказ на ${total}₽
            </button>
        </div>
    `;
}

async function checkout() {
    tg.MainButton.showProgress();
    
    try {
        // Send data to bot
        tg.sendData(JSON.stringify({
            action: 'checkout',
            cart: cart
        }));
        
        closeCart();
        tg.close();
    } catch (error) {
        console.error('Checkout error:', error);
        tg.showAlert('Ошибка оформления заказа');
    } finally {
        tg.MainButton.hideProgress();
    }
}

// Favorites
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
        
        // Update UI
        document.querySelectorAll(`.btn-fav`).forEach(btn => {
            if (btn.onclick.toString().includes(productId)) {
                btn.classList.toggle('active', result.is_favorite);
            }
        });
        
    } catch (error) {
        console.error('Failed to toggle favorite:', error);
    }
}

// Search
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

// Navigation
function showCatalog() {
    setActiveNav(0);
    document.querySelector('.main-content').style.display = 'block';
}

function showFavorites() {
    setActiveNav(1);
    // Implement favorites view
}

function showProfile() {
    setActiveNav(3);
    // Implement profile view
}

function setActiveNav(index) {
    document.querySelectorAll('.nav-item').forEach((item, i) => {
        item.classList.toggle('active', i === index);
    });
}

// Utilities
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Handle back button
tg.BackButton.onClick(() => {
    const productModal = document.getElementById('productModal');
    const cartModal = document.getElementById('cartModal');
    const searchModal = document.getElementById('searchModal');
    
    if (searchModal.classList.contains('open')) {
        closeSearch();
    } else if (cartModal.classList.contains('open')) {
        closeCart();
    } else if (productModal.classList.contains('open')) {
        closeProductModal();
    } else {
        tg.close();
    }
});

// Show back button when modals open
const observer = new MutationObserver(() => {
    const anyModalOpen = document.querySelector('.modal.open');
    if (anyModalOpen) {
        tg.BackButton.show();
    } else {
        tg.BackButton.hide();
    }
});

observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] });
