/**
 * Jetesk Messenger App - Оптимизированная версия
 * С виртуальным скроллингом и ленивой загрузкой
 */

import './virtual-scroll.js';

// === Глобальное состояние ===
const state = {
    currentUser: null,
    users: [],
    messages: [],
    selectedUserId: 0,
    selectedUsername: 'Общий чат',
    selectedUserForPrivate: null,
    refreshInterval: null,
    onlineInterval: null,
    selectedFile: null,
    selectedFileData: null,
    selectedFileType: null,
    lastMessagesMap: {},
    currentSearchQuery: '',
    virtualScroller: null,
    messagesVirtualScroller: null,
    socket: null
};

// === Константы ===
const CONFIG = {
    ITEM_HEIGHT_USERS: 70,
    ITEM_HEIGHT_MESSAGES: 50,
    OVERSCAN: 5,
    POLL_INTERVAL: 5000
};

// === Утилиты ===
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function apiFetch(url, options) {
    options = options || {};
    options.credentials = 'include';
    return fetch(url, options);
}

// === Инициализация ===
function init() {
    registerServiceWorker();
    checkAuth();
    setupEventListeners();
}

// === WebSocket ===
function connectWebSocket() {
    if (state.socket) {
        state.socket.disconnect();
    }
    
    // Подключаемся к Socket.IO серверу
    state.socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000
    });
    
    state.socket.on('connect', () => {
        console.log('[WS] Connected to server');
        // Подписываемся на уведомления
        if (state.currentUser) {
            state.socket.emit('subscribe', { user_id: state.currentUser.id });
        }
    });
    
    state.socket.on('disconnect', () => {
        console.log('[WS] Disconnected from server');
    });
    
    state.socket.on('new_message', (msg) => {
        console.log('[WS] New message received:', msg);
        // Если сообщение для текущего чата - добавляем
        if (state.selectedUserId === 0 || msg.sender_id === state.selectedUserId) {
            state.messages.push(msg);
            if (state.messagesVirtualScroller) {
                state.messagesVirtualScroller.setItems(state.messages);
                state.messagesVirtualScroller.scrollToBottom();
            }
            // Обновляем список чатов
            loadLastMessages();
        }
    });
    
    state.socket.on('file_status', (data) => {
        console.log('[WS] File status update:', data);
        // Обновляем статус файла
        const msg = state.messages.find(m => m.id === data.message_id);
        if (msg) {
            msg.status = data.status;
            if (state.messagesVirtualScroller) {
                state.messagesVirtualScroller.render();
            }
        }
    });
}

// === Service Worker ===
function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => {
                console.log('[PWA] SW зарегистрирован:', reg.scope);
                
                // Проверяем обновления
                reg.addEventListener('updatefound', () => {
                    const newWorker = reg.installing;
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            showUpdateNotification();
                        }
                    });
                });
            })
            .catch(err => console.error('[PWA] Ошибка регистрации SW:', err));
    }
}

function showUpdateNotification() {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: var(--primary, #6366f1);
        color: white;
        padding: 16px 24px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 10000;
        cursor: pointer;
        animation: slideIn 0.3s ease;
    `;
    notification.innerHTML = '🔄 Доступна новая версия! Нажмите для обновления';
    notification.onclick = () => location.reload();
    document.body.appendChild(notification);
    
    setTimeout(() => notification.remove(), 10000);
}

// === Аутентификация ===
function checkAuth() {
    apiFetch('/api/me')
        .then(r => r.json())
        .then(user => {
            if (user) {
                state.currentUser = user;
                showChat();
            }
        })
        .catch(console.error);
}

function login() {
    const username = document.getElementById('usernameInput').value.trim();
    const password = document.getElementById('passwordInput').value;
    const jtUsername = document.getElementById('jtUsernameInput').value.trim();
    const errorEl = document.getElementById('loginError');

    if (!username) {
        errorEl.textContent = 'Введите имя или @username';
        return;
    }
    if (username.length < 2) {
        errorEl.textContent = 'Имя должно быть не менее 2 символов';
        return;
    }
    if (!password) {
        errorEl.textContent = 'Введите пароль';
        return;
    }
    if (password.length < 6) {
        errorEl.textContent = 'Пароль должен быть не менее 6 символов';
        return;
    }

    apiFetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password})
    })
    .then(r => {
        if (!r.ok) throw new Error('Ошибка сервера: ' + r.status);
        return r.json();
    })
    .then(result => {
        if (result.success) {
            state.currentUser = result.user;
            showChat();
        } else if (result.message?.includes('не найден')) {
            if (confirm('Пользователь не найден. Зарегистрироваться?')) {
                register(username, password, jtUsername);
            } else {
                errorEl.textContent = result.message;
            }
        } else {
            errorEl.textContent = result.message;
        }
    })
    .catch(err => {
        console.error('Ошибка входа:', err);
        errorEl.textContent = 'Ошибка: ' + err.message;
    });
}

function register(username, password, jtUsername) {
    const errorEl = document.getElementById('loginError');

    apiFetch('/api/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password, jt_username: jtUsername})
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            state.currentUser = result.user;
            showChat();
        } else {
            errorEl.textContent = 'Регистрация: ' + (result.message || 'Неизвестная ошибка');
        }
    })
    .catch(err => {
        console.error('Ошибка регистрации:', err);
        errorEl.textContent = 'Ошибка: ' + err.message;
    });
}

function logout() {
    apiFetch('/api/logout').then(() => location.reload());
}

// === Пользователи с виртуальным скроллингом ===
function loadUsers() {
    apiFetch('/api/users')
        .then(r => r.json())
        .then(data => {
            state.users = data;
            document.getElementById('usersCount').textContent = state.users.length;
            initUsersVirtualScroller();
            loadLastMessages();
        })
        .catch(console.error);
}

function initUsersVirtualScroller() {
    const container = document.getElementById('usersList');
    if (!container) return;

    if (state.virtualScroller) {
        state.virtualScroller.destroy();
    }

    state.virtualScroller = new VirtualScroll(container, {
        itemHeight: CONFIG.ITEM_HEIGHT_USERS,
        overscan: CONFIG.OVERSCAN,
        renderItem: renderUserItem
    });

    updateUsersList();
}

function updateUsersList() {
    if (!state.virtualScroller) return;

    const items = [
        {id: 0, username: 'Общий чат', isGeneral: true},
        ...state.users
    ];

    state.virtualScroller.setItems(items);
}

function renderUserItem(item, index) {
    const div = document.createElement('div');
    div.className = 'user-item' + (state.selectedUserId === item.id ? ' active' : '');
    div.style.cssText = 'display: flex; align-items: center; padding: 12px; cursor: pointer;';
    div.onclick = () => selectUser(item.id, item.username);

    if (item.isGeneral) {
        div.innerHTML = `
            <div class="user-avatar" style="background: #6366f1; width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px; margin-right: 12px;">💬</div>
            <div class="user-info-list">
                <div class="user-name" style="font-weight: 600;">Общий чат</div>
                <div class="user-status" style="color: var(--text-secondary); font-size: 12px;">Все пользователи</div>
            </div>
        `;
    } else {
        const statusHtml = item.is_online 
            ? '<div style="color: rgb(29, 180, 24); font-size: 12px;">В сети</div>'
            : item.last_seen 
                ? `<div style="color: var(--text-secondary); font-size: 12px;">Был(а) ${escapeHtml(item.last_seen)}</div>`
                : '<div style="color: var(--text-secondary); font-size: 12px;">Был(а) недавно</div>';

        const avatarStyle = item.avatar_url 
            ? `background-image: url(${item.avatar_url}); background-size: cover; background-position: center;`
            : `background: #${item.avatar_color || '6366f1'};`;
        const avatarContent = item.avatar_url ? '' : item.username.charAt(0).toUpperCase();

        div.innerHTML = `
            <div class="user-avatar" style="${avatarStyle} width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 18px; margin-right: 12px; color: white; font-weight: 600;">${avatarContent}</div>
            <div class="user-info-list" style="flex: 1; min-width: 0;">
                <div class="user-name" style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(item.username)}</div>
                ${statusHtml}
            </div>
            ${item.unread_count > 0 ? `<div class="unread-badge" style="background: var(--primary); color: white; border-radius: 12px; padding: 2px 8px; font-size: 12px; font-weight: 600;">${item.unread_count > 99 ? '99+' : item.unread_count}</div>` : ''}
        `;
    }

    return div;
}

// === Сообщения с виртуальным скроллингом ===
function loadMessages() {
    const url = state.selectedUserId === 0
        ? '/api/messages'
        : '/api/messages/' + state.selectedUserId;

    // Показываем индикатор загрузки
    const container = document.getElementById('messagesContainer');
    if (container) {
        container.style.opacity = '0.5';
    }

    apiFetch(url)
        .then(r => r.json())
        .then(data => {
            console.log('Загружено сообщений:', data.length);
            state.messages = data;
            
            // Инициализируем виртуальный скроллер
            initMessagesVirtualScroller();

            // Снимаем индикатор загрузки
            if (container) {
                container.style.opacity = '1';
            }

            // Сразу инициализируем lazy loading
            setTimeout(() => initLazyLoading(), 50);

            // Отмечаем сообщения как прочитанные (для личных чатов)
            if (state.selectedUserId !== 0) {
                markMessagesAsRead(state.selectedUserId);
            }
        })
        .catch(err => {
            console.error('Ошибка загрузки сообщений:', err);
            if (container) {
                container.style.opacity = '1';
            }
        });
}

function initMessagesVirtualScroller() {
    const container = document.getElementById('messagesContainer');
    if (!container) return;

    if (state.messagesVirtualScroller) {
        state.messagesVirtualScroller.destroy();
    }

    state.messagesVirtualScroller = new VirtualScroll(container, {
        itemHeight: CONFIG.ITEM_HEIGHT_MESSAGES,
        overscan: CONFIG.OVERSCAN,
        renderItem: renderMessageItem,
        onScroll: () => {
            const btn = document.getElementById('scrollToBottomBtn');
            if (btn) {
                const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;
                btn.style.display = isAtBottom ? 'none' : 'flex';
            }
        }
    });

    state.messagesVirtualScroller.setItems(state.messages);

    // Мгновенный скролл вниз без задержки
    requestAnimationFrame(() => {
        state.messagesVirtualScroller.scrollToBottom();
    });
}

function renderMessageItem(msg, index) {
    const div = document.createElement('div');
    div.className = 'message ' + (msg.is_mine ? 'me' : 'other');
    div.style.cssText = 'padding: 8px 16px; display: flex; ' + (msg.is_mine ? 'justify-content: flex-end;' : 'justify-content: flex-start;');

    let bubbleContent = '';
    if (msg.file_type === 'image') {
        // Lazy loading + placeholder для изображений
        const placeholderColor = generatePlaceholderColor(msg.id || msg.content);
        bubbleContent = `<div class="chat-img-placeholder" style="background: ${placeholderColor};" data-src="${msg.content}" data-src-placeholder="${placeholderColor}"></div>`;
    } else if (msg.file_type === 'video') {
        // Прогрессивная загрузка видео через streaming endpoint
        const videoUrl = '/api/video/' + msg.id;
        bubbleContent = `
            <video controls preload="metadata" style="max-width: 320px; border-radius: 8px; background: #000;" 
                   onclick="event.stopPropagation();">
                <source src="${videoUrl}" type="video/mp4">
                Ваш браузер не поддерживает видео
            </video>`;
    } else if (msg.file_type === 'file') {
        bubbleContent = `<a href="${msg.content}" download class="file-attachment" style="color: var(--primary);">📄 Файл</a>`;
    } else {
        bubbleContent = escapeHtml(msg.content);
    }

    const statusIcon = msg.is_mine
        ? (msg.status === 'read' || msg.status === 'delivered' ? ' ✓✓' : msg.status === 'sent' ? ' ✓' : msg.status === 'sending' ? ' ⏳' : '')
        : '';

    // Время уже в МСК с сервера
    const moscowTime = msg.created_at;

    div.innerHTML = `
        <div class="message-bubble" style="
            background: ${msg.is_mine ? 'var(--primary)' : 'var(--surface)'};
            color: ${msg.is_mine ? 'white' : 'var(--text)'};
            padding: 10px 14px;
            border-radius: 16px;
            max-width: 70%;
            word-wrap: break-word;
        ">${bubbleContent}</div>
        <div class="message-time" style="
            font-size: 11px;
            color: var(--text-secondary);
            margin-left: 8px;
            align-self: flex-end;
            white-space: nowrap;
        ">${escapeHtml(msg.sender)} • ${moscowTime}${statusIcon}</div>
    `;

    return div;
}

function scrollToBottom() {
    if (state.messagesVirtualScroller) {
        state.messagesVirtualScroller.scrollToBottom();
    }
}

// === Остальные функции (заглушки для существующего кода) ===
function showChat() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('chatScreen').style.display = 'flex';
    connectWebSocket(); // Подключаем WebSocket
    loadUsers();
    startPolling();
    
    // Инициализация lazy loading для изображений
    initLazyLoading();
}

// === Lazy Loading (Lozad.js) ===
function initLazyLoading() {
    if (typeof lozad !== 'undefined') {
        const observer = lozad('.chat-img-placeholder', {
            rootMargin: '100px',
            threshold: 0,
            loaded: function(el) {
                // Создаём img элемент
                const img = document.createElement('img');
                img.className = 'chat-img is-loaded';
                img.style.cssText = 'max-width: 200px; border-radius: 12px; cursor: pointer;';
                img.src = el.getAttribute('data-src');
                img.onclick = function() { window.open(this.src); };
                img.onerror = function() {
                    // Если ошибка загрузки - оставляем placeholder
                    el.style.background = '#334155';
                };
                // Заменяем placeholder на изображение
                el.parentNode.replaceChild(img, el);
            }
        });
        observer.observe();
    }
}

// === Генерация цвета placeholder на основе ID ===
function generatePlaceholderColor(seed) {
    if (!seed) return 'linear-gradient(135deg, #1e293b 0%, #334155 100%)';
    
    // Генерируем детерминированный цвет из строки
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
        hash = seed.charCodeAt(i) + ((hash << 5) - hash);
    }
    
    // Создаём приятные градиенты
    const hue = Math.abs(hash % 360);
    const color1 = `hsl(${hue}, 20%, 15%)`;
    const color2 = `hsl(${(hue + 30) % 360}, 25%, 25%)`;
    
    return `linear-gradient(135deg, ${color1} 0%, ${color2} 100%)`;
}

function selectUser(userId, username) {
    state.selectedUserId = userId;
    state.selectedUsername = username;
    document.getElementById('chatTitle').textContent = '💬 ' + username;
    
    if (state.virtualScroller) {
        state.virtualScroller.render();
    }
    
    loadMessages();
    showChatView();
}

function showChatView() {
    const usersPanel = document.getElementById('usersPanel');
    const backBtn = document.getElementById('backToChatsBtn');
    
    if (usersPanel) usersPanel.style.display = 'none';
    if (backBtn) backBtn.style.display = 'flex';
}

function showUsersList() {
    const usersPanel = document.getElementById('usersPanel');
    const backBtn = document.getElementById('backToChatsBtn');
    
    if (usersPanel) usersPanel.style.display = 'flex';
    if (backBtn) backBtn.style.display = 'none';
}

function loadLastMessages() {
    apiFetch('/api/last-messages')
        .then(r => r.json())
        .then(data => {
            state.lastMessagesMap = {};
            data.forEach(msg => {
                state.lastMessagesMap[msg.recipient_id || 'general'] = msg;
            });
            if (state.virtualScroller) {
                updateUsersList();
            }
        })
        .catch(console.error);
}

function markMessagesAsRead(senderId) {
    apiFetch('/api/messages/mark-read', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sender_id: senderId})
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            loadLastMessages();
            loadUsers();
        }
    })
    .catch(console.error);
}

function startPolling() {
    if (state.refreshInterval) clearInterval(state.refreshInterval);
    state.refreshInterval = setInterval(() => {
        if (state.selectedUserId !== 0) {
            loadMessages();
        }
        loadLastMessages();
    }, CONFIG.POLL_INTERVAL);
}

function setupEventListeners() {
    document.addEventListener('DOMContentLoaded', () => {
        // Кнопки входа/регистрации
        const loginBtn = document.getElementById('loginBtn');
        if (loginBtn) loginBtn.addEventListener('click', login);

        // Обработка Enter в поле ввода
        const passwordInput = document.getElementById('passwordInput');
        if (passwordInput) {
            passwordInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') login();
            });
        }
    });
}

// Экспорт глобальных функций
window.app = {
    init,
    login,
    logout,
    selectUser,
    showChatView,
    showUsersList,
    scrollToBottom,
    escapeHtml
};

// Автозапуск
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
