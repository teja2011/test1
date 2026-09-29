var currentUser = null;
var users = [];
var messages = [];
var selectedUserId = 0;
var selectedUsername = 'Общий чат';
var currentLoadUserId = null;
var selectedUserForPrivate = null;
var refreshInterval = null;
var onlineInterval = null;
var lastMessagesInterval = null;
var messagesInterval = null;
var selectedFile = null;
var selectedFileData = null;
var selectedFileType = null;
var lastMessagesMap = {};
var currentSearchQuery = '';

var DEVICE_ID_KEY = 'jtesk_device_id';
var currentDeviceId = localStorage.getItem(DEVICE_ID_KEY);
if (!currentDeviceId) {
    currentDeviceId = 'dev_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem(DEVICE_ID_KEY, currentDeviceId);
}
var currentDeviceName = detectDeviceName();

function detectDeviceName() {
    var ua = navigator.userAgent;
    var os = 'Unknown';
    if (ua.indexOf('Windows') !== -1) os = 'Windows';
    else if (ua.indexOf('Mac OS X') !== -1) os = 'macOS';
    else if (ua.indexOf('Android') !== -1) os = 'Android';
    else if (ua.indexOf('iPhone') !== -1 || ua.indexOf('iPad') !== -1) os = 'iOS';
    else if (ua.indexOf('Linux') !== -1) os = 'Linux';

    var browser = 'Unknown';
    if (ua.indexOf('Edg/') !== -1) browser = 'Edge';
    else if (ua.indexOf('Chrome/') !== -1) browser = 'Chrome';
    else if (ua.indexOf('Firefox/') !== -1) browser = 'Firefox';
    else if (ua.indexOf('Safari/') !== -1) browser = 'Safari';

    return browser + ' на ' + os;
}

var currentAudio = null;
var currentAudioBtn = null;
var currentAudioId = null;
var isAudioPlaying = false;
var playingMsgId = null;

var messagesDB = null;
var DB_VERSION = 1;
var DB_NAME = 'JeteskMessagesDB';
var STORE_NAME = 'messages';

var peerConnection = null;
var localStream = null;
var callTimer = null;
var callSeconds = 0;
var isInCall = false;
var isCallMuted = false;
var isIncomingCall = false;
var callPollInterval = null;
var currentCallId = null;
var rtcConfig = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
    ]
};

function apiFetch(url, options) {
    options = options || {};
    options.credentials = 'include';
    return fetch(url, options)
        .then(function(response) {
            var ct = response.headers.get('content-type') || '';
            if (ct.indexOf('application/json') === -1) {
                return response.text().then(function(text) {
                    var msg = text.substring(0, 200);
                    msg = msg.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
                    throw new Error('HTTP ' + response.status + ': ' + msg);
                });
            }
            return response;
        });
}

function openMessagesDB() {
    return new Promise(function(resolve, reject) {
        var request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = function(event) {
            var db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
        };
        request.onsuccess = function(event) {
            messagesDB = event.target.result;
            resolve(messagesDB);
        };
        request.onerror = function(event) {
            reject(event.target.error);
        };
    });
}

function saveMessagesToCache(messagesArray, userId) {
    if (!messagesDB) return Promise.resolve();
    return new Promise(function(resolve, reject) {
        try {
            var transaction = messagesDB.transaction([STORE_NAME], 'readwrite');
            var store = transaction.objectStore(STORE_NAME);
            var key = 'user_' + userId + '_' + Date.now();
            var record = { id: key, userId: userId, messages: messagesArray, timestamp: Date.now() };
            var request = store.put(record);
            request.onsuccess = function() { resolve(); };
            request.onerror = function(event) { reject(event.target.error); };
        } catch (err) { reject(err); }
    });
}

function getMessagesFromCache(userId) {
    if (!messagesDB) return Promise.resolve(null);
    return new Promise(function(resolve, reject) {
        var transaction = messagesDB.transaction([STORE_NAME], 'readonly');
        var store = transaction.objectStore(STORE_NAME);
        var request = store.openCursor(null, 'prev');
        var found = false;
        request.onsuccess = function(event) {
            var cursor = event.target.result;
            if (cursor && !found) {
                if (cursor.value.userId == userId) {
                    found = true;
                    resolve(cursor.value.messages);
                    return;
                }
                cursor.continue();
            } else if (!found) { resolve(null); }
        };
        request.onerror = function(event) { reject(event.target.error); };
    });
}

function init() {
    loadTheme();
    openMessagesDB().catch(function(err) { console.error('[IndexedDB]', err); });
    apiFetch('/api/me')
        .then(function(r) { return r.json(); })
        .then(function(user) {
            if (user) {
                currentUser = user;
                showChat();
            }
        });
}

function logout() {
    if (onlineInterval) clearInterval(onlineInterval);
    if (lastMessagesInterval) clearInterval(lastMessagesInterval);
    if (messagesInterval) clearInterval(messagesInterval);
    apiFetch('/api/logout').then(function() { location.reload(); });
}

function loadUsers() {
    apiFetch('/api/users')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            users = data;
            document.getElementById('usersCount').textContent = users.length;
            renderUsers();
            applySearchFilter();
            loadLastMessages();
            updateChatHeader();
        });
}

function loadLastMessages() {
    apiFetch('/api/last-messages')
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(data) {
            lastMessagesMap = {};
            data.forEach(function(msg) { lastMessagesMap[msg.recipient_id || 'general'] = msg; });
            renderUsers();
            applySearchFilter();
        })
        .catch(function(err) { console.error('loadLastMessages:', err); });
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderUsers() {
    var container = document.getElementById('usersList');
    var html = '<div class="user-item ' + (selectedUserId === 0 ? 'active' : '') + '" onclick="selectUser(0, \'Общий чат\')">' +
        '<div class="user-avatar" style="background: #6366f1;">💬</div>' +
        '<div class="user-info-list">' +
        '<div class="user-name">Общий чат</div>' +
        '<div class="user-status">Все пользователи</div>' +
        '</div></div>';
    if (users.length === 0) html += '<div class="empty-contacts-hint">Начни общаться! Вбей в поиске username своего собеседника</div>';
    users.forEach(function(user) {
        var statusHtml = '', lastMessageHtml = '';
        if (user.is_online) statusHtml = '<div class="user-status" style="color: rgb(29, 180, 24);">В сети</div>';
        else if (user.last_seen) statusHtml = '<div class="user-last-seen">Был(а) ' + escapeHtml(user.last_seen) + '</div>';
        else statusHtml = '<div class="user-last-seen">Был(а) недавно</div>';
        if (!user.is_online && lastMessagesMap[user.id]) {
            var lastMsg = lastMessagesMap[user.id], statusIcon = '';
            if (lastMsg.is_mine) statusIcon = lastMsg.status === 'read' || lastMsg.status === 'delivered' ? '✓✓' : lastMsg.status === 'sent' ? '✓' : lastMsg.status === 'sending' ? '⏳' : '';
            var preview = lastMsg.file_type === 'image' ? '📷 Фото' : lastMsg.file_type === 'file' ? '📄 Файл' : escapeHtml(lastMsg.content);
            if (statusIcon) lastMessageHtml = '<div class="user-last-message"><span class="status-icon">' + statusIcon + '</span>' + preview + '</div>';
        }
        var displayName = escapeHtml(user.username);
        if (user.jt_username) displayName += ' <span style="color: var(--text-secondary); font-size: 12px;">@' + escapeHtml(user.jt_username) + '</span>';
        var avatarStyle = 'background: #' + user.avatar_color + ';', avatarContent = user.username.charAt(0).toUpperCase();
        if (user.avatar_url) { avatarStyle = 'background-image: url(' + user.avatar_url + '); background-size: cover; background-position: center;'; avatarContent = ''; }
        html += '<div class="user-item ' + (selectedUserId === user.id ? 'active' : '') + '" onclick="selectUser(' + user.id + ', \'' + user.username.replace(/'/g, "\\'") + '\')"><div class="user-avatar" style="' + avatarStyle + '">' + avatarContent + '</div><div class="user-info-list"><div class="user-name">' + displayName + '</div>' + statusHtml + lastMessageHtml + '</div>' + (user.unread_count > 0 ? '<div class="unread-badge">' + (user.unread_count > 99 ? '99+' : user.unread_count) + '</div>' : '') + '</div>';
    });
    container.innerHTML = html;
}

function filterUsers() {
    var searchInput = document.getElementById('userSearchInput');
    var query = searchInput.value.trim().toLowerCase();
    currentSearchQuery = query;
    var container = document.getElementById('usersList');
    var userItems = container.getElementsByClassName('user-item');
    if (userItems.length > 0) userItems[0].style.display = '';
    for (var i = 1; i < userItems.length; i++) {
        var item = userItems[i];
        var userNameEl = item.querySelector('.user-name');
        var userName = userNameEl ? userNameEl.textContent.toLowerCase() : '';
        var jtUsername = item.textContent.toLowerCase();
        if (query === '' || userName.includes(query) || jtUsername.includes('@' + query)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    }
}

function applySearchFilter() {
    if (currentSearchQuery !== '') {
        var searchInput = document.getElementById('userSearchInput');
        if (searchInput) searchInput.value = currentSearchQuery;
        filterUsers();
    }
}

function selectUser(userId, username) {
    selectedUserId = userId;
    selectedUsername = username;
    currentLoadUserId = null;
    lastKnownMessageCount = 0;
    updateChatHeader();
    renderUsers();
    loadMessages();
    if (userId !== 0) markMessagesAsRead(userId);
    showChatView();
}

function updateChatHeader() {
    var avatarEl = document.getElementById('chatTitleAvatar');
    var statusEl = document.getElementById('chatTitleStatus');
    var nameEl = document.getElementById('chatTitleName');
    if (selectedUserId === 0) {
        if (nameEl) nameEl.textContent = 'Общий чат';
        if (avatarEl) {
            avatarEl.style.background = '#6366f1';
            avatarEl.style.backgroundImage = '';
            avatarEl.textContent = '💬';
            avatarEl.style.fontSize = '20px';
        }
        if (statusEl) {
            statusEl.textContent = 'Все пользователи';
            statusEl.className = 'chat-title-status online';
        }
        return;
    }
    var targetUser = null;
    for (var i = 0; i < users.length; i++) {
        if (users[i].id === selectedUserId) { targetUser = users[i]; break; }
    }
    if (!targetUser) return;
    if (nameEl) nameEl.textContent = targetUser.username || selectedUsername;
    if (avatarEl) {
        if (targetUser.avatar_url) {
            avatarEl.style.backgroundImage = 'url(' + targetUser.avatar_url + ')';
            avatarEl.style.backgroundSize = 'cover';
            avatarEl.style.backgroundPosition = 'center';
            avatarEl.textContent = '';
        } else {
            avatarEl.style.backgroundImage = '';
            avatarEl.style.background = '#' + (targetUser.avatar_color || '6366f1');
            avatarEl.textContent = (targetUser.username || selectedUsername).charAt(0).toUpperCase();
            avatarEl.style.fontSize = '18px';
        }
    }
    if (statusEl) {
        if (targetUser.online || targetUser.is_online) {
            statusEl.textContent = 'В сети';
            statusEl.className = 'chat-title-status online';
        } else if (targetUser.last_seen) {
            statusEl.textContent = 'Был(а) ' + targetUser.last_seen;
            statusEl.className = 'chat-title-status';
        } else {
            statusEl.textContent = 'Не в сети';
            statusEl.className = 'chat-title-status';
        }
    }
}

function showChatView() {
    var usersPanel = document.getElementById('usersPanel');
    var contactsPanel = document.getElementById('contactsPanel');
    var settingsPanel = document.getElementById('settingsPanel');
    var backBtn = document.getElementById('backToChatsBtn');
    var chatInputArea = document.querySelector('.chat-input-area');
    var usersFooter = document.getElementById('usersFooter');

    if (usersPanel) usersPanel.classList.add('hidden');
    if (contactsPanel) contactsPanel.classList.remove('show');
    if (settingsPanel) settingsPanel.classList.remove('show');
    if (backBtn) backBtn.style.display = 'flex';

    if (chatInputArea) {
        chatInputArea.classList.remove('hidden');
        chatInputArea.classList.add('visible');
    }
    if (usersFooter && window.innerWidth <= 900) {
        usersFooter.classList.add('chat-hidden');
    }
}

function showUsersList() {
    var usersPanel = document.getElementById('usersPanel');
    var backBtn = document.getElementById('backToChatsBtn');
    var chatInputArea = document.querySelector('.chat-input-area');
    var usersFooter = document.getElementById('usersFooter');
    if (usersPanel) usersPanel.classList.remove('hidden');
    if (backBtn) backBtn.style.display = 'none';
    if (chatInputArea) {
        chatInputArea.classList.add('hidden');
        chatInputArea.classList.remove('visible');
    }
    if (usersFooter && window.innerWidth <= 900) usersFooter.classList.remove('chat-hidden');
    showFooter();
}

function initTabs() {
    var chatsTabBtn = document.getElementById('chatsTabBtn');
    var contactsTabBtn = document.getElementById('contactsTabBtn');
    var settingsTabBtn = document.getElementById('settingsTabBtn');
    if (chatsTabBtn) chatsTabBtn.classList.add('active');
    if (contactsTabBtn) contactsTabBtn.classList.remove('active');
    if (settingsTabBtn) settingsTabBtn.classList.remove('active');
}

function showChatsTab() {
    var usersPanel = document.getElementById('usersPanel');
    var contactsPanel = document.getElementById('contactsPanel');
    var settingsPanel = document.getElementById('settingsPanel');
    var chatsTabBtn = document.getElementById('chatsTabBtn');
    var contactsTabBtn = document.getElementById('contactsTabBtn');
    var settingsTabBtn = document.getElementById('settingsTabBtn');
    var backBtn = document.getElementById('backToChatsBtn');
    var chatInputArea = document.querySelector('.chat-input-area');
    var usersFooter = document.getElementById('usersFooter');

    if (usersPanel) {
        usersPanel.classList.remove('hidden');
        if (window.innerWidth > 900) usersPanel.style.display = 'flex';
    }
    if (contactsPanel) contactsPanel.classList.remove('show');
    if (settingsPanel) settingsPanel.classList.remove('show');

    if (chatsTabBtn) chatsTabBtn.classList.add('active');
    if (contactsTabBtn) contactsTabBtn.classList.remove('active');
    if (settingsTabBtn) settingsTabBtn.classList.remove('active');

    if (backBtn) backBtn.style.display = 'none';
    if (chatInputArea) {
        chatInputArea.classList.add('hidden');
        chatInputArea.classList.remove('visible');
    }
    if (usersFooter && window.innerWidth <= 900) {
        usersFooter.classList.remove('chat-hidden');
    }
    showFooter();
}

function showSettingsTab() {
    var usersPanel = document.getElementById('usersPanel');
    var contactsPanel = document.getElementById('contactsPanel');
    var settingsPanel = document.getElementById('settingsPanel');
    var chatsTabBtn = document.getElementById('chatsTabBtn');
    var contactsTabBtn = document.getElementById('contactsTabBtn');
    var settingsTabBtn = document.getElementById('settingsTabBtn');
    var chatInputArea = document.querySelector('.chat-input-area');
    var usersFooter = document.getElementById('usersFooter');

    if (usersPanel) {
        usersPanel.classList.add('hidden');
        if (window.innerWidth > 900) usersPanel.style.display = 'none';
    }
    if (contactsPanel) contactsPanel.classList.remove('show');
    if (settingsPanel) settingsPanel.classList.add('show');

    if (chatsTabBtn) chatsTabBtn.classList.remove('active');
    if (contactsTabBtn) contactsTabBtn.classList.remove('active');
    if (settingsTabBtn) settingsTabBtn.classList.add('active');

    if (chatInputArea) {
        chatInputArea.classList.add('hidden');
        chatInputArea.classList.remove('visible');
    }
    if (usersFooter && window.innerWidth <= 900) {
        usersFooter.classList.add('chat-hidden');
    }
    hideFooter();
    renderSettingsContent();
}

function hideFooter() { var f = document.getElementById('usersFooter'); if (f) f.classList.add('hidden'); }
function showFooter() { var f = document.getElementById('usersFooter'); if (f) f.classList.remove('hidden'); }

var contacts = [];

function loadContacts() {
    apiFetch('/api/contacts')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            contacts = Array.isArray(data) ? data : [];
            var el = document.getElementById('contactsCount');
            if (el) el.textContent = contacts.length;
            renderContacts();
        })
        .catch(function(err) { console.error('loadContacts:', err); });
}

function renderContacts() {
    var container = document.getElementById('contactsContent');
    if (!container) return;
    if (!contacts.length) {
        container.innerHTML = '<div class="empty-contacts-hint">Пока нет контактов.<br><br>Откройте профиль пользователя в чате<br>и нажмите «Добавить контакт».</div>';
        return;
    }
    var searchInput = document.getElementById('contactSearchInput');
    var query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    var html = '';
    var shown = 0;
    contacts.forEach(function(user) {
        var name = (user.username || '').toLowerCase();
        var jt = (user.jt_username || '').toLowerCase();
        if (query && name.indexOf(query) === -1 && jt.indexOf(query.replace('@','')) === -1) return;
        shown++;
        var statusHtml;
        if (user.is_online) statusHtml = '<div class="user-status" style="color: rgb(29, 180, 24);">В сети</div>';
        else if (user.last_seen) statusHtml = '<div class="user-last-seen">Был(а) ' + escapeHtml(user.last_seen) + '</div>';
        else statusHtml = '<div class="user-last-seen">Был(а) недавно</div>';
        var displayName = escapeHtml(user.username);
        if (user.jt_username) displayName += ' <span style="color: var(--text-secondary); font-size: 12px;">@' + escapeHtml(user.jt_username) + '</span>';
        var avatarStyle = 'background: #' + (user.avatar_color || '6366f1') + ';';
        var avatarContent = (user.username || '?').charAt(0).toUpperCase();
        if (user.avatar_url) {
            avatarStyle = 'background-image: url(' + user.avatar_url + '); background-size: cover; background-position: center;';
            avatarContent = '';
        }
        html += '<div class="user-item ' + (selectedUserId === user.id ? 'active' : '') + '" onclick="selectContact(' + user.id + ', \'' + user.username.replace(/'/g, "\\'") + '\')">' +
            '<div class="user-avatar" style="' + avatarStyle + '">' + avatarContent + '</div>' +
            '<div class="user-info-list">' +
                '<div class="user-name">' + displayName + '</div>' +
                statusHtml +
            '</div>' +
            (user.unread_count > 0 ? '<div class="unread-badge">' + (user.unread_count > 99 ? '99+' : user.unread_count) + '</div>' : '') +
            '</div>';
    });
    if (!shown) {
        html = '<div class="empty-contacts-hint">Ничего не найдено</div>';
    }
    container.innerHTML = html;
}

function filterContacts() {
    renderContacts();
}

function selectContact(userId, username) {
    selectUser(userId, username);
}

function showContactsTab() {
    var usersPanel = document.getElementById('usersPanel');
    var contactsPanel = document.getElementById('contactsPanel');
    var settingsPanel = document.getElementById('settingsPanel');
    var chatsTabBtn = document.getElementById('chatsTabBtn');
    var contactsTabBtn = document.getElementById('contactsTabBtn');
    var settingsTabBtn = document.getElementById('settingsTabBtn');
    var backBtn = document.getElementById('backToChatsBtn');
    var chatInputArea = document.querySelector('.chat-input-area');
    var usersFooter = document.getElementById('usersFooter');

    if (usersPanel) {
        usersPanel.classList.add('hidden');
        if (window.innerWidth > 900) usersPanel.style.display = 'none';
    }
    if (settingsPanel) settingsPanel.classList.remove('show');
    if (contactsPanel) contactsPanel.classList.add('show');

    if (chatsTabBtn) chatsTabBtn.classList.remove('active');
    if (contactsTabBtn) contactsTabBtn.classList.add('active');
    if (settingsTabBtn) settingsTabBtn.classList.remove('active');

    if (backBtn) backBtn.style.display = 'none';
    if (chatInputArea) {
        chatInputArea.classList.add('hidden');
        chatInputArea.classList.remove('visible');
    }
    if (usersFooter && window.innerWidth <= 900) {
        usersFooter.classList.remove('chat-hidden');
    }
    showFooter();
    loadContacts();
}

function checkIfContact(userId) {
    return apiFetch('/api/contacts/check/' + userId)
        .then(function(r) { return r.json(); })
        .then(function(d) { return !!(d && d.is_contact); })
        .catch(function() { return false; });
}

function resetAddContactButton() {
    var wrap = document.getElementById('addContactBtnWrap');
    var btn = document.getElementById('addContactBtn');
    if (!wrap || !btn) return;
    wrap.classList.remove('dissolving');
    wrap.style.display = '';
    wrap.style.maxHeight = '100px';
    wrap.style.marginBottom = '16px';
    wrap.style.opacity = '1';
    wrap.style.transform = 'translateY(0) scale(1)';
    btn.disabled = false;
    btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style="vertical-align: middle; margin-right: 8px;"><path d="M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg><span>Добавить контакт</span>';
}

function addContactFromProfile() {
    if (selectedUserId <= 0) return;
    var btn = document.getElementById('addContactBtn');
    var wrap = document.getElementById('addContactBtnWrap');
    if (!btn || !wrap) return;
    btn.disabled = true;
    btn.innerHTML = '<span>⏳ Добавляем...</span>';
    apiFetch('/api/contacts/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({contact_id: selectedUserId})
    })
    .then(function(r) { return r.json(); })
    .then(function(result) {
        if (result.success) {
            wrap.classList.add('dissolving');
            setTimeout(function() { wrap.style.display = 'none'; }, 450);
            loadContacts();
            if (typeof showToast === 'function') showToast('✅ Контакт добавлен');
        } else {
            btn.disabled = false;
            btn.innerHTML = '<span>Добавить контакт</span>';
            alert('Ошибка: ' + (result.message || 'не удалось добавить'));
        }
    })
    .catch(function(err) {
        btn.disabled = false;
        btn.innerHTML = '<span>Добавить контакт</span>';
        alert('Ошибка: ' + err.message);
    });
}

function renderSettingsContent() {
    var content = document.getElementById('settingsContent');
    var displayName = currentUser.username;
    if (currentUser.jt_username) displayName += ' @' + currentUser.jt_username;
    var avatarStyle = 'background: #' + (currentUser.avatar_color || '6366f1') + ';';
    var avatarContent = currentUser.username.charAt(0).toUpperCase();
    if (currentUser.avatar_url) {
        avatarStyle = 'background-image: url(' + currentUser.avatar_url + '); background-size: cover; background-position: center;';
        avatarContent = '';
    }
    content.innerHTML = '\
        <div style="text-align: center; margin-bottom: 24px;">\
            <div style="position: relative; display: inline-block;">\
                <div class="avatar" id="settingsAvatarPreview" style="width: 80px; height: 80px; font-size: 32px; margin: 0 auto 12px; cursor: pointer; ' + avatarStyle + '">' + avatarContent + '</div>\
                <div style="position: absolute; bottom: 0; right: 0; background: var(--primary); border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; cursor: pointer; border: 2px solid var(--surface);" onclick="document.getElementById(\'avatarInput\').click()">📷</div>\
            </div>\
            <input type="file" id="avatarInput" accept="image/*" style="display: none;" onchange="handleAvatarSelect(event)">\
            <h3 style="font-size: 18px; margin-bottom: 4px;">' + escapeHtml(displayName) + '</h3>\
            <p style="font-size: 13px; color: rgb(29, 180, 24);">В сети</p>\
            <p id="avatarUploadStatus" style="font-size: 12px; margin-top: 8px;"></p>\
        </div>\
        <div class="input-group" style="margin-bottom: 20px;">\
            <label style="font-size: 14px; margin-bottom: 8px; display: block; font-weight: 600;">@ Username</label>\
            <div style="display: flex; gap: 8px; align-items: center;">\
                <input type="text" id="settingsJtUsernameInput" placeholder="@username" maxlength="32" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" style="flex: 1; padding: 12px; border: 2px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);" value="' + (currentUser.jt_username ? '@' + currentUser.jt_username : '') + '">\
                <button id="settingsSavejtUsernameBtn" style="padding: 12px 16px; background: var(--primary); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 18px;">💾</button>\
            </div>\
            <p id="settingsJtUsernameStatus" style="font-size: 12px; margin-top: 8px;"></p>\
        </div>\
        <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">\
        <div class="input-group" style="margin-bottom: 16px;">\
            <label style="font-size: 14px; margin-bottom: 8px; display: block; font-weight: 600;">✨ О себе</label>\
            <textarea id="settingsBioInput" placeholder="Расскажите о себе..." maxlength="150" style="width: 100%; padding: 12px; border: 2px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text); resize: vertical; min-height: 80px; font-family: inherit;">' + escapeHtml(currentUser.bio || '') + '</textarea>\
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">\
                <p style="font-size: 12px; color: var(--text-secondary);">Максимум 150 символов</p>\
                <span id="settingsBioCounter" style="font-size: 12px; color: var(--text-secondary);">' + (currentUser.bio ? currentUser.bio.length : 0) + '/150</span>\
            </div>\
            <button id="settingsSaveBioBtn" style="margin-top: 8px; padding: 10px 16px; background: var(--primary); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px;">💾 Сохранить</button>\
        </div>\
        <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">\
        <div class="input-group" style="margin-bottom: 16px;">\
            <label style="font-size: 14px; margin-bottom: 8px; display: block; font-weight: 600;">📝 Сменить ник</label>\
            <input type="text" id="settingsChangeUsernameInput" placeholder="Введите новый ник" maxlength="50" autocomplete="off" style="width: 100%; padding: 12px; border: 2px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);">\
        </div>\
        <button class="btn" id="settingsChangeUsernameBtn" style="background: var(--primary); margin-bottom: 8px;">✏️ Сменить ник</button>\
        <p style="font-size: 12px; color: var(--text-secondary); text-align: center;">Ваш ник изменится для всех пользователей</p>\
        <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">\
        <button class="btn" id="settingsClearMessagesBtn" style="background: #f59e0b; margin-bottom: 12px;">🗑️ Очистить мои сообщения</button>\
        <p style="font-size: 12px; color: var(--text-secondary); text-align: center; margin-bottom: 16px;">Удаляет все сообщения, которые вы отправляли</p>\
        <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">\
        <div class="input-group" style="margin-bottom: 16px;">\
            <label style="font-size: 14px; margin-bottom: 8px; display: block; font-weight: 600;">📱 Мои устройства</label>\
            <div id="devicesList" style="max-height: 200px; overflow-y: auto;"></div>\
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 8px;">Текущее устройство: ' + escapeHtml(currentDeviceName) + '</p>\
        </div>\
        <button class="btn" id="settingsDeleteAccountBtn" style="background: #ef4444; margin-top: 16px;">🔴 Удалить аккаунт</button>\
        <p style="font-size: 12px; color: var(--text-secondary); text-align: center; margin-top: 8px;">Безвозвратно удаляет ваш аккаунт из базы данных</p>\
        <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">\
        <button class="btn" id="settingsLogoutBtn" style="background: var(--surface); border: 1px solid var(--border); margin-top: 8px;">🚪 Выйти из аккаунта</button>\
    ';
    document.getElementById('settingsSavejtUsernameBtn').addEventListener('click', settingsSavejtUsername);
    document.getElementById('settingsSaveBioBtn').addEventListener('click', settingsSaveBio);
    document.getElementById('settingsChangeUsernameBtn').addEventListener('click', settingsChangeUsername);
    document.getElementById('settingsClearMessagesBtn').addEventListener('click', clearMessages);
    document.getElementById('settingsDeleteAccountBtn').addEventListener('click', deleteAccount);
    document.getElementById('settingsLogoutBtn').addEventListener('click', logout);
    var bioInput = document.getElementById('settingsBioInput');
    var bioCounter = document.getElementById('settingsBioCounter');
    if (bioInput && bioCounter) bioInput.addEventListener('input', function() { bioCounter.textContent = bioInput.value.length + '/150'; });
    loadDevicesList();
}

function loadDevicesList() {
    var container = document.getElementById('devicesList');
    if (!container) return;
    apiFetch('/api/devices')
        .then(function(r) { return r.json(); })
        .then(function(devices) {
            if (!devices || devices.length === 0) {
                container.innerHTML = '<p style="font-size:13px;color:var(--text-secondary);padding:8px 0;">Нет сохранённых устройств</p>';
                return;
            }
            var html = '';
            devices.forEach(function(d) {
                var isCurrent = (d.device_id === currentDeviceId);
                html += '<div style="display:flex;align-items:center;gap:10px;padding:10px;background:' + (isCurrent ? 'rgba(99,102,241,0.15)' : 'var(--bg)') + ';border-radius:8px;margin-bottom:6px;">' +
                    '<div style="flex:1;min-width:0;">' +
                    '<div style="font-size:14px;font-weight:600;">' + escapeHtml(d.device_name) + (isCurrent ? ' <span style="color:var(--success);font-size:12px;">(это устройство)</span>' : '') + '</div>' +
                    '<div style="font-size:12px;color:var(--text-secondary);">Активность: ' + escapeHtml(d.last_active) + '</div>' +
                    '</div>' +
                    (isCurrent ? '' : '<button onclick="deleteDevice(' + d.id + ')" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:18px;padding:4px 8px;" title="Удалить устройство">🗑️</button>') +
                    '</div>';
            });
            container.innerHTML = html;
        })
        .catch(function(err) { console.error('loadDevicesList:', err); });
}

function deleteDevice(deviceId) {
    if (!confirm('Удалить это устройство?')) return;
    apiFetch('/api/devices/' + deviceId, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(result) {
            if (result.success) loadDevicesList();
            else alert('Ошибка: ' + (result.message || 'Не удалось удалить'));
        })
        .catch(function(err) { alert('Ошибка: ' + err.message); });
}

var chatProfileMuted = {};

function openChatProfile() {
    if (selectedUserId <= 0) return;
    var targetUser = null;
    for (var i = 0; i < users.length; i++) {
        if (users[i].id === selectedUserId) { targetUser = users[i]; break; }
    }
    if (!targetUser) return;

    var avatarEl = document.getElementById('chatProfileAvatar');
    var avatarImg = document.getElementById('chatProfileAvatarImg');
    var avatarLetter = document.getElementById('chatProfileAvatarLetter');
    if (targetUser.avatar_url) {
        if (avatarImg) { avatarImg.src = targetUser.avatar_url; avatarImg.style.display = 'block'; }
        if (avatarLetter) avatarLetter.style.display = 'none';
        avatarEl.style.background = 'transparent';
    } else {
        if (avatarImg) avatarImg.style.display = 'none';
        if (avatarLetter) {
            avatarLetter.style.display = 'block';
            avatarLetter.textContent = (targetUser.username || '').charAt(0).toUpperCase();
        }
        avatarEl.style.background = '#' + (targetUser.avatar_color || '6366f1');
    }
    document.getElementById('chatProfileName').textContent = targetUser.username || '';
    var statusEl = document.getElementById('chatProfileStatus');
    if (targetUser.online || targetUser.is_online) {
        statusEl.textContent = 'В сети';
        statusEl.style.color = '#22c55e';
    } else if (targetUser.last_seen) {
        statusEl.textContent = 'Был(а) ' + targetUser.last_seen;
        statusEl.style.color = 'var(--text-secondary)';
    } else {
        statusEl.textContent = 'Не в сети';
        statusEl.style.color = 'var(--text-secondary)';
    }
    document.getElementById('chatProfileUsername').innerHTML = '<span>' + (targetUser.jt_username ? '@' + targetUser.jt_username : 'Не указано') + '</span>';
    var bioEl = document.getElementById('chatProfileBio');
    if (targetUser.bio) bioEl.innerHTML = '<span>' + escapeHtml(targetUser.bio) + '</span>';
    else bioEl.innerHTML = '<span>Не указано</span>';
    updateChatProfileMute();
    resetAddContactButton();
    document.getElementById('chatProfileModal').style.display = 'flex';
    checkIfContact(selectedUserId).then(function(isContact) {
        var wrap = document.getElementById('addContactBtnWrap');
        if (!wrap) return;
        if (isContact) wrap.style.display = 'none';
    });
}

function closeChatProfile(e) {
    if (e && e.target !== document.getElementById('chatProfileModal')) return;
    document.getElementById('chatProfileModal').style.display = 'none';
}

function toggleChatProfileMute() {
    if (!selectedUserId || selectedUserId <= 0) return;
    if (chatProfileMuted[selectedUserId]) delete chatProfileMuted[selectedUserId];
    else chatProfileMuted[selectedUserId] = true;
    localStorage.setItem('jetesk_muted', JSON.stringify(chatProfileMuted));
    updateChatProfileMute();
}

function updateChatProfileMute() {
    var isMuted = selectedUserId > 0 && chatProfileMuted[selectedUserId];
    var icon = document.getElementById('chatProfileMuteIcon');
    var label = document.getElementById('chatProfileMuteLabel');
    if (icon) icon.style.opacity = isMuted ? '0.4' : '1';
    if (label) label.textContent = isMuted ? 'без звука' : 'звук';
}

try {
    var savedMuted2 = localStorage.getItem('jetesk_muted');
    if (savedMuted2) chatProfileMuted = JSON.parse(savedMuted2);
} catch(e) {}

function loadMessages() {
    var url = selectedUserId === 0 ? '/api/messages' : '/api/messages/' + selectedUserId;
    var userId = selectedUserId;
    currentLoadUserId = userId;
    var savedTime = 0;
    if (currentAudio && playingMsgId) savedTime = currentAudio.currentTime;
    apiFetch(url)
        .then(function(r) {
            if (currentLoadUserId !== userId) return null;
            if (!r.ok) return r.text().then(function(text) { throw new Error('HTTP ' + r.status + ': ' + text); });
            return r.json();
        })
        .then(function(data) {
            if (data === null) return;
            if (currentLoadUserId !== userId) return;
            messages = data;
            lastKnownMessageCount = data.length;
            renderMessages();
            if (currentAudio && playingMsgId && savedTime > 0) currentAudio.currentTime = savedTime;
            if (data.length > 0) saveMessagesToCache(data, userId).catch(console.error);
        })
        .catch(function(err) {
            if (currentLoadUserId !== userId) return;
            getMessagesFromCache(userId).then(function(cached) {
                if (cached && cached.length > 0) {
                    messages = cached;
                    renderMessages();
                }
            }).catch(console.error);
        });
}

function markMessagesAsRead(senderId) {
    apiFetch('/api/messages/mark-read', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sender_id: senderId})
    })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(result) {
        if (result.success) {
            var messages = document.querySelectorAll('.message.other');
            messages.forEach(function(msg) {
                var timeEl = msg.querySelector('.message-time');
                if (timeEl && !timeEl.textContent.includes('✓✓')) {
                    timeEl.textContent = timeEl.textContent.replace(' ✓', ' ✓✓').replace(/([0-9]{2}:[0-9]{2})$/, '$1 ✓✓');
                }
            });
            loadLastMessages();
            loadUsers();
        }
    })
    .catch(function(err) { console.error('markRead:', err.message || err); });
}

function scrollToBottom() {
    var container = document.getElementById('messagesContainer');
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
    var btn = document.getElementById('scrollToBottomBtn');
    if (btn) btn.style.display = 'none';
}

function renderMessages() {
    var container = document.getElementById('messagesContainer');
    if (messages.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="icon">💭</div><div>Начните общение!</div></div>';
        return;
    }
    var html = '';
    messages.forEach(function(msg) {
        var bubbleContent = '';
        if (msg.file_type === 'image') bubbleContent = '<img src="' + msg.content + '" class="chat-img" onclick="window.open(this.src)">';
        else if (msg.file_type === 'file') bubbleContent = '<a href="' + msg.content + '" download class="file-attachment">📄 Файл</a>';
        else if (msg.file_type === 'voice') bubbleContent = renderVoiceMessage(msg, false);
        else if (msg.file_type === 'call_missed') {
            var callerName = 'Неизвестный';
            if (msg.content && msg.content.indexOf('__CALL_MISSED__:') === 0) callerName = msg.content.replace('__CALL_MISSED__', '');
            bubbleContent = '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="#ef4444" style="display:block;flex-shrink:0;">' +
                '<path d="M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z"/>' +
                '</svg>' +
                '<span style="color:#ef4444;font-weight:600;">Пропущенный вызов</span>' +
                '<span style="color:var(--text-secondary);font-size:13px;">' + escapeHtml(callerName) + '</span>' +
                '</div>';
        }
        else bubbleContent = escapeHtml(msg.content);
        var statusIcon = '';
        if (msg.is_mine) {
            if (msg.status === 'read' || msg.status === 'delivered') statusIcon = ' ✓✓';
            else if (msg.status === 'sent') statusIcon = ' ✓';
            else if (msg.status === 'sending') statusIcon = ' ⏳';
        }
        var moscowTime = msg.created_at;
        if (msg.created_at && typeof msg.created_at === 'string' && msg.created_at.includes(':')) {
            var parts = msg.created_at.split(':');
            var hours = parseInt(parts[0]);
            if (hours >= 24) hours = hours - 24;
            moscowTime = (hours < 10 ? '0' + hours : hours) + ':' + parts[1];
        }
        html += '<div class="message ' + (msg.is_mine ? 'me' : 'other') + '" data-id="' + msg.id + '">' +
            '<div class="message-row">' +
            (msg.is_mine ? '<button class="msg-more-btn" onclick="openMsgMenu(' + msg.id + ', event)" title="Ещё">⋮</button>' : '') +
            '<div class="message-bubble">' + bubbleContent + '</div>' +
            '</div>' +
            '<div class="message-time">' + escapeHtml(msg.sender) + ' • ' + moscowTime + statusIcon + '</div>' +
            '</div>';
    });
    container.innerHTML = html;
    restoreVoicePlaybackState();
    setTimeout(function() {
        var container = document.getElementById('messagesContainer');
        if (!container) return;
        var isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
        if (isAtBottom) {
            container.scrollTop = container.scrollHeight;
            var b = document.getElementById('scrollToBottomBtn');
            if (b) b.style.display = 'none';
        } else {
            var b2 = document.getElementById('scrollToBottomBtn');
            if (b2) b2.style.display = 'flex';
        }
    }, 50);
}

function generateWaveformBars(durationSec, barCount) {
    var bars = [];
    var baseHeight = 8;
    var maxHeight = 32;
    var seed = durationSec * 100;
    for (var i = 0; i < barCount; i++) {
        seed = (seed * 9301 + 49297) % 233280;
        var normalized = seed / 233280;
        var height = baseHeight + (normalized * (maxHeight - baseHeight));
        bars.push(Math.round(height));
    }
    return bars;
}

function renderVoiceMessage(msg, isMe) {
    var audioSrc = msg.content || '';
    var duration = msg.duration || '0:00';
    var durationSec = 30;
    if (duration && typeof duration === 'string') {
        var parts = duration.split(':');
        if (parts.length === 2) durationSec = parseInt(parts[0]) * 60 + parseInt(parts[1]);
    }
    var bars = generateWaveformBars(durationSec, 30);
    var barsHtml = '';
    for (var i = 0; i < bars.length; i++) {
        barsHtml += '<div class="voice-waveform-bar" style="height: ' + bars[i] + 'px;" data-index="' + i + '"></div>';
    }
    return '<div class="voice-message ' + (isMe ? 'me' : 'other') + '" data-msg-id="' + msg.id + '">' +
        '<button class="voice-play-btn" data-msg-id="' + msg.id + '" onclick="toggleVoicePlayback(' + msg.id + ', this, \'' + audioSrc.replace(/'/g, "\\'") + '\')">' +
            '<div class="voice-play-icon"></div>' +
            '<div class="voice-pause-icon"></div>' +
        '</button>' +
        '<div class="voice-waveform">' + barsHtml + '</div>' +
        '<span class="voice-time">' + duration + '</span>' +
        '</div>';
}

function toggleVoicePlayback(msgId, btn, audioSrc) {
    if (currentAudioId === msgId && currentAudio) {
        if (currentAudio.paused) {
            currentAudio.play();
            btn.classList.add('playing');
            isAudioPlaying = true;
        } else {
            currentAudio.pause();
            btn.classList.remove('playing');
            isAudioPlaying = false;
        }
        return;
    }
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        if (currentAudioBtn) currentAudioBtn.classList.remove('playing');
    }
    currentAudio = new Audio(audioSrc);
    currentAudioBtn = btn;
    currentAudioId = msgId;
    playingMsgId = msgId;
    isAudioPlaying = true;
    currentAudio.addEventListener('ended', function() {
        if (currentAudioBtn) currentAudioBtn.classList.remove('playing');
        currentAudio = null; currentAudioBtn = null; currentAudioId = null;
        playingMsgId = null; isAudioPlaying = false;
    });
    currentAudio.addEventListener('pause', function() {
        if (currentAudioBtn) currentAudioBtn.classList.remove('playing');
        isAudioPlaying = false;
    });
    currentAudio.addEventListener('play', function() {
        if (currentAudioBtn) currentAudioBtn.classList.add('playing');
        isAudioPlaying = true;
    });
    currentAudio.addEventListener('error', function(err) {
        console.error('Audio error:', err);
        if (currentAudioBtn) currentAudioBtn.classList.remove('playing');
        isAudioPlaying = false;
    });
    currentAudio.play().catch(function(err) {
        console.error('Error playing voice:', err);
        if (btn) btn.classList.remove('playing');
        isAudioPlaying = false;
    });
}

function restoreVoicePlaybackState() {
    if (!playingMsgId || !isAudioPlaying) return;
    var btn = document.querySelector('.voice-play-btn[data-msg-id="' + playingMsgId + '"]');
    if (btn && currentAudio && !currentAudio.paused) {
        btn.classList.add('playing');
        currentAudioBtn = btn;
    } else if (btn && currentAudio && currentAudio.paused) {
        btn.classList.remove('playing');
        isAudioPlaying = false;
    }
}

function sendMessage() {
    var input = document.getElementById('messageInput');
    var content = input.value.trim();
    if (selectedFileData) {
        var formData = new FormData();
        var fileToSend = selectedFile;
        if (!fileToSend && selectedFileData) {
            try {
                var byteString = atob(selectedFileData.split(',')[1]);
                var mimeString = selectedFileData.split(',')[0].split(':')[1].split(';')[0];
                var ab = new ArrayBuffer(byteString.length);
                var ia = new Uint8Array(ab);
                for (var i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
                fileToSend = new Blob([ab], { type: mimeString });
            } catch(e) { alert('Ошибка подготовки файла'); return; }
        }
        formData.append('file', fileToSend, selectedFileType === 'image' ? 'image.jpg' : 'file');
        formData.append('recipient_id', selectedUserId === 0 ? null : selectedUserId);
        formData.append('file_type', selectedFileType);
        var btn = document.getElementById('sendBtn');
        btn.disabled = true;
        var tempId = 'temp_' + Date.now();
        addMessageToDOM({
            id: tempId, sender: currentUser.username,
            content: (selectedFile ? selectedFile.name : 'файл'),
            created_at: new Date().toLocaleTimeString('ru-RU', {hour: '2-digit', minute:'2-digit'}),
            is_mine: true, file_type: selectedFileType, status: 'sending'
        });
        apiFetch('/api/send-file', { method: 'POST', body: formData })
        .then(function(r) { if (!r.ok) throw new Error('Ошибка: ' + r.status); return r.json(); })
        .then(function(result) {
            if (result.success) { clearFilePreview(); loadMessages(); loadLastMessages(); }
            else alert('Ошибка: ' + (result.message || 'Неизвестная ошибка'));
            btn.disabled = false;
        })
        .catch(function(err) { alert('Ошибка: ' + err.message); btn.disabled = false; });
        return;
    }
    if (!content) return;
    var btn = document.getElementById('sendBtn');
    btn.disabled = true;
    input.value = '';
    var tempId = 'temp_' + Date.now();
    addMessageToDOM({
        id: tempId, sender: currentUser.username, content: content,
        created_at: new Date().toLocaleTimeString('ru-RU', {hour: '2-digit', minute:'2-digit'}),
        is_mine: true, file_type: null, status: 'sending'
    });
    var payload = { recipient_id: selectedUserId === 0 ? null : selectedUserId, content: content };
    apiFetch('/api/send', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) })
    .then(function(r) {
        if (!r.ok) return r.text().then(function(text) { throw new Error('HTTP ' + r.status + ': ' + text); });
        return r.json();
    })
    .then(function(result) {
        if (result.success) { loadMessages(); loadLastMessages(); }
        else alert('Ошибка: ' + (result.message || 'Неизвестная ошибка'));
        btn.disabled = false;
    })
    .catch(function(err) { console.error('Send error:', err); alert('Ошибка: ' + err.message); btn.disabled = false; });
}

function sendVoiceOrText() {
    if (isRecording && audioChunks.length > 0) {
        stopRecording();
        setTimeout(function() {
            var voiceBlob = new Blob(audioChunks, { type: 'audio/webm' });
            var formData = new FormData();
            formData.append('file', voiceBlob, 'voice_' + Date.now() + '.webm');
            formData.append('recipient_id', selectedUserId === 0 ? null : selectedUserId);
            formData.append('file_type', 'voice');
            apiFetch('/api/send-file', { method: 'POST', body: formData })
                .then(function(r) { return r.json(); })
                .then(function(result) { if (result.success) { loadMessages(); loadLastMessages(); } });
            audioChunks = [];
            isRecording = false;
            var sendBtn = document.getElementById('sendBtn');
            if (sendBtn) sendBtn.disabled = true;
        }, 100);
        return;
    }
    sendMessage();
}

var activeMsgMenu = null;

function openMsgMenu(msgId, event) {
    event.stopPropagation();
    event.preventDefault();
    closeMsgMenu();
    var btn = event.currentTarget;
    var menu = document.createElement('div');
    menu.className = 'message-context-menu';
    menu.innerHTML = '<button class="delete-btn" onclick="deleteMsg(' + msgId + ')">' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>' +
        'Удалить</button>';
    document.body.appendChild(menu);
    activeMsgMenu = menu;
    var rect = btn.getBoundingClientRect();
    menu.style.top = (rect.bottom + 4) + 'px';
    menu.style.right = (window.innerWidth - rect.right) + 'px';
    menu.style.left = 'auto';
    setTimeout(function() { document.addEventListener('click', closeMsgMenu); }, 10);
}

function closeMsgMenu() {
    document.removeEventListener('click', closeMsgMenu);
    if (activeMsgMenu) { activeMsgMenu.remove(); activeMsgMenu = null; }
}

function deleteMsg(msgId) {
    closeMsgMenu();
    if (!confirm('Удалить сообщение?')) return;
    apiFetch('/api/messages/' + msgId, { method: 'DELETE' })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(result) {
            if (result.success) { loadMessages(); loadLastMessages(); }
            else alert('Ошибка: ' + (result.message || 'Не удалось удалить'));
        })
        .catch(function(err) { console.error('Delete error:', err); alert('Ошибка: ' + err.message); });
}

var mediaRecorder = null;
var audioChunks = [];
var recordingInterval = null;
var recordingStartTime = null;
var isRecording = false;
var isRecordingActive = false;
var voiceRecordingLocked = false;
var audioContext = null;
var analyser = null;
var microphone = null;
var animationFrame = null;
var pendingStream = null;

function startRecording(e) {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Ваш браузер не поддерживает запись голоса');
        return;
    }
    if (isRecording) return;
    isRecording = true;
    pendingStream = null;
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(function(stream) {
            pendingStream = stream;
            if (!isRecording) {
                stream.getTracks().forEach(function(track) { track.stop(); });
                return;
            }
            var mimeType = 'audio/webm';
            if (MediaRecorder.isTypeSupported('audio/mp4')) mimeType = 'audio/mp4';
            else if (MediaRecorder.isTypeSupported('audio/ogg')) mimeType = 'audio/ogg';
            mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });
            audioChunks = [];
            isRecordingActive = true;
            voiceRecordingLocked = false;
            var sendBtn = document.getElementById('sendBtn');
            if (sendBtn) sendBtn.disabled = false;
            var lockBtnReset = document.getElementById('lockButton');
            if (lockBtnReset) {
                lockBtnReset.style.background = 'var(--primary)';
                lockBtnReset.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M12 17c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6z"/></svg>';
            }
            mediaRecorder.addEventListener('dataavailable', function(event) { if (event.data.size > 0) audioChunks.push(event.data); });
            mediaRecorder.addEventListener('stop', function() {
                if (pendingStream) {
                    pendingStream.getTracks().forEach(function(track) { track.stop(); });
                    pendingStream = null;
                }
                if (audioChunks.length === 0) {
                    isRecording = false; isRecordingActive = false; voiceRecordingLocked = false;
                    return;
                }
                if (recordingInterval) { clearInterval(recordingInterval); recordingInterval = null; }
                if (animationFrame) cancelAnimationFrame(animationFrame);
                if (audioContext) { audioContext.close(); audioContext = null; }
                var recordBtn = document.getElementById('voiceRecordBtn');
                if (recordBtn) recordBtn.classList.remove('recording');
                isRecording = false;
                isRecordingActive = false;
            });
            mediaRecorder.start(100);
            recordingStartTime = new Date();
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 64;
            microphone = audioContext.createMediaStreamSource(stream);
            microphone.connect(analyser);
            var preview = document.getElementById('voiceRecordPreview');
            var inputContainer = document.getElementById('messageInput').parentElement;
            if (preview) { preview.style.display = 'flex'; preview.style.marginTop = '56px'; }
            if (inputContainer) inputContainer.style.display = 'none';
            var lockBtn = document.getElementById('lockButton');
            if (lockBtn) {
                lockBtn.style.display = 'flex';
                lockBtn.style.opacity = '0';
                lockBtn.style.transition = 'opacity 0.3s ease';
                setTimeout(function() { lockBtn.style.opacity = '1'; }, 50);
            }
            recordingInterval = setInterval(updateRecordingTime, 100);
            createWaveform();
            updateWaveform();
            var recordBtn2 = document.getElementById('voiceRecordBtn');
            if (recordBtn2) recordBtn2.classList.add('recording');
        })
        .catch(function(err) {
            alert('Ошибка доступа к микрофону: ' + err.message);
            isRecording = false;
            isRecordingActive = false;
        });
}

function stopRecording(e) {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    if (!isRecording) return;
    if (!isRecordingActive) {
        isRecording = false;
        voiceRecordingLocked = false;
        if (pendingStream) {
            pendingStream.getTracks().forEach(function(track) { track.stop(); });
            pendingStream = null;
        }
        var preview = document.getElementById('voiceRecordPreview');
        var inputContainer = document.getElementById('messageInput').parentElement;
        if (preview) { preview.style.display = 'none'; preview.style.marginTop = '0'; }
        if (inputContainer) inputContainer.style.display = 'flex';
        var waveform = document.getElementById('waveform');
        if (waveform) waveform.innerHTML = '';
        var lockBtn = document.getElementById('lockButton');
        if (lockBtn) lockBtn.style.display = 'none';
        var sendBtn = document.getElementById('sendBtn');
        if (sendBtn) sendBtn.disabled = true;
        audioChunks = [];
        return;
    }
    if (!voiceRecordingLocked) { sendVoiceRecording(); return; }
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
}

function sendVoiceRecording() {
    if (!audioChunks || audioChunks.length === 0) { console.error('[Voice] No data'); return; }
    var mimeType = audioChunks[0].type || 'audio/webm';
    var voiceBlob = new Blob(audioChunks, { type: mimeType });
    var formData = new FormData();
    formData.append('file', voiceBlob, 'voice_' + Date.now() + '.' + (mimeType.split('/')[1] || 'webm'));
    formData.append('recipient_id', selectedUserId === 0 ? null : selectedUserId);
    formData.append('file_type', 'voice');
    apiFetch('/api/send-file', { method: 'POST', body: formData })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(result) {
            if (result.success) { loadMessages(); loadLastMessages(); }
            else alert('Ошибка отправки: ' + (result.message || 'Неизвестная ошибка'));
        })
        .catch(function(err) { console.error('[Voice] Network error:', err); alert('Ошибка сети: ' + err.message); });
    var preview = document.getElementById('voiceRecordPreview');
    var inputContainer = document.getElementById('messageInput').parentElement;
    if (preview) { preview.style.display = 'none'; preview.style.marginTop = '0'; }
    if (inputContainer) inputContainer.style.display = 'flex';
    var waveform = document.getElementById('waveform');
    if (waveform) waveform.innerHTML = '';
    var lockBtn = document.getElementById('lockButton');
    if (lockBtn) lockBtn.style.display = 'none';
    audioChunks = [];
    voiceRecordingLocked = false;
}

function cancelVoiceRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
    if (pendingStream) {
        pendingStream.getTracks().forEach(function(track) { track.stop(); });
        pendingStream = null;
    }
    if (recordingInterval) { clearInterval(recordingInterval); recordingInterval = null; }
    if (animationFrame) cancelAnimationFrame(animationFrame);
    if (audioContext) { audioContext.close(); audioContext = null; }
    audioChunks = [];
    isRecording = false;
    isRecordingActive = false;
    voiceRecordingLocked = false;
    var recordBtn = document.getElementById('voiceRecordBtn');
    if (recordBtn) recordBtn.classList.remove('recording');
    var preview = document.getElementById('voiceRecordPreview');
    if (preview) { preview.style.display = 'none'; preview.style.marginTop = '0'; }
    var lockBtn = document.getElementById('lockButton');
    if (lockBtn) lockBtn.style.display = 'none';
    var inputContainer = document.getElementById('messageInput').parentElement;
    if (inputContainer) inputContainer.style.display = 'flex';
    var waveform = document.getElementById('waveform');
    if (waveform) waveform.innerHTML = '';
}

function updateRecordingTime() {
    if (!recordingStartTime) return;
    var diff = Math.floor((new Date() - recordingStartTime) / 1000);
    var minutes = Math.floor(diff / 60);
    var seconds = diff % 60;
    var timeEl = document.getElementById('recordingTime');
    if (timeEl) timeEl.textContent = minutes + ':' + (seconds < 10 ? '0' : '') + seconds;
}

var lockSwipeStartY = 0, lockSwipeStartX = 0, lockIsSwiping = false;

function initLockSwipe() {
    var lockBtn = document.getElementById('lockButton');
    if (!lockBtn) return;
    lockBtn.addEventListener('touchstart', function(e) {
        lockSwipeStartY = e.touches[0].clientY;
        lockSwipeStartX = e.touches[0].clientX;
        lockIsSwiping = true;
    }, { passive: true });
    lockBtn.addEventListener('touchmove', function(e) {
        if (!lockIsSwiping) return;
        var deltaY = lockSwipeStartY - e.touches[0].clientY;
        var deltaX = Math.abs(e.touches[0].clientX - lockSwipeStartX);
        if (deltaY > 30 && deltaY > deltaX) { lockVoiceRecording(); lockIsSwiping = false; }
    }, { passive: true });
    lockBtn.addEventListener('touchend', function() { lockIsSwiping = false; });
    lockBtn.addEventListener('mousedown', function(e) {
        lockSwipeStartY = e.clientY;
        lockSwipeStartX = e.clientX;
        lockIsSwiping = true;
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!lockIsSwiping) return;
        var deltaY = lockSwipeStartY - e.clientY;
        var deltaX = Math.abs(e.clientX - lockSwipeStartX);
        if (deltaY > 30 && deltaY > deltaX) { lockVoiceRecording(); lockIsSwiping = false; }
    });
    document.addEventListener('mouseup', function() { lockIsSwiping = false; });
}

function lockVoiceRecording() {
    voiceRecordingLocked = true;
    var lockBtn = document.getElementById('lockButton');
    if (lockBtn) {
        lockBtn.style.transition = 'all 0.3s ease';
        lockBtn.style.background = '#22c55e';
        lockBtn.style.transform = 'translateX(-50%) scale(1.1)';
        setTimeout(function() { lockBtn.style.transform = 'translateX(-50%) scale(1)'; }, 200);
        lockBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM12 17c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM15.1 8H8.9V6c0-1.71 1.39-3.1 3.1-3.1s3.1 1.39 3.1 3.1v2z"/></svg>';
        lockBtn.title = 'Запись закреплена - отпустите палец';
    }
}

setTimeout(function() { initLockSwipe(); }, 500);

function createWaveform() {
    var waveform = document.getElementById('waveform');
    if (!waveform) return;
    waveform.innerHTML = '';
    for (var i = 0; i < 40; i++) {
        var bar = document.createElement('div');
        bar.className = 'waveform-bar';
        bar.style.width = '3px';
        bar.style.height = '8px';
        bar.style.background = 'var(--primary)';
        bar.style.borderRadius = '2px';
        bar.style.transition = 'height 0.05s ease';
        waveform.appendChild(bar);
    }
}

function updateWaveform() {
    if (!analyser || !isRecording) return;
    var bufferLength = analyser.frequencyBinCount;
    var dataArray = new Uint8Array(bufferLength);
    analyser.getByteFrequencyData(dataArray);
    var bars = document.querySelectorAll('.waveform-bar');
    for (var i = 0; i < bars.length && i < bufferLength; i++) {
        var volume = dataArray[i];
        var minHeight = 8;
        var maxHeight = 35;
        bars[i].style.height = (minHeight + (volume / 255) * (maxHeight - minHeight)) + 'px';
    }
    animationFrame = requestAnimationFrame(updateWaveform);
}

function addMessageToDOM(msg) {
    var container = document.getElementById('messagesContainer');
    if (!container) return;
    var emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    var statusIcon = ' ⏳';
    if (msg.status === 'sent') statusIcon = ' ✓';
    else if (msg.status === 'delivered' || msg.status === 'read') statusIcon = ' ✓✓';
    var bubbleContent = '';
    if (msg.file_type === 'image') bubbleContent = '<img src="' + msg.content + '" class="chat-img" onclick="window.open(this.src)">';
    else if (msg.file_type === 'file') bubbleContent = '<a href="' + msg.content + '" download class="file-attachment">📄 Файл</a>';
    else if (msg.file_type === 'voice') bubbleContent = renderVoiceMessage(msg, false);
    else bubbleContent = escapeHtml(msg.content);
    var moscowTime = msg.created_at;
    if (msg.created_at && typeof msg.created_at === 'string' && msg.created_at.includes(':')) {
        var parts = msg.created_at.split(':');
        var hours = parseInt(parts[0]) + 3;
        var minutes = parts[1];
        if (hours >= 24) hours = hours - 24;
        moscowTime = (hours < 10 ? '0' + hours : hours) + ':' + minutes;
    }
    var html = '<div class="message ' + (msg.is_mine ? 'me' : 'other') + '" data-id="' + msg.id + '" style="position: relative;">' +
        '<button class="message-menu-btn" onclick="openMsgMenu(' + msg.id + ', event)" title="Ещё" style="left: 4px; right: auto;">' +
        '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>' +
        '</button>' +
        '<div class="message-bubble" style="padding-right: 36px;">' + bubbleContent + '</div>' +
        '<div class="message-time">' + escapeHtml(msg.sender) + ' • ' + moscowTime + statusIcon + '</div>' +
        '</div>';
    container.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
}

function handleFileSelect(event) {
    var file = event.target.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
        alert('Файл слишком большой! Максимум 10MB');
        event.target.value = '';
        return;
    }
    selectedFileType = file.type.startsWith('image/') ? 'image' : 'file';
    if (selectedFileType === 'image') {
        var img = new Image();
        var reader = new FileReader();
        reader.onload = function(e) { img.src = e.target.result; };
        reader.onerror = function() { fallbackToFile(); };
        img.onload = function() {
            var canvas = document.createElement('canvas');
            var ctx = canvas.getContext('2d');
            canvas.width = img.width;
            canvas.height = img.height;
            ctx.drawImage(img, 0, 0);
            selectedFileData = canvas.toDataURL('image/jpeg', 0.8);
            canvas.toBlob(function(blob) {
                selectedFile = new File([blob], 'image.jpg', { type: 'image/jpeg' });
                showFilePreview('image.jpg', selectedFileType);
            }, 'image/jpeg', 0.8);
        };
        img.onerror = function() { fallbackToFile(); };
        reader.readAsDataURL(file);
    } else {
        fallbackToFile();
    }
    function fallbackToFile() {
        selectedFile = file;
        var reader = new FileReader();
        reader.onload = function(e) {
            selectedFileData = e.target.result;
            showFilePreview(file.name, selectedFileType);
        };
        reader.onerror = function() { alert('Ошибка чтения файла'); };
        reader.readAsDataURL(file);
    }
}

function showFilePreview(fileName, fileType) {
    var container = document.getElementById('filePreviewContainer');
    var icon = fileType === 'image' ? '🖼️' : '📄';
    container.innerHTML = '<div class="file-preview">' +
        '<span style="font-size: 20px;">' + icon + '</span>' +
        '<span class="file-preview-name">' + escapeHtml(fileName) + '</span>' +
        '<button class="file-preview-remove" onclick="clearFilePreview()">×</button>' +
        '</div>';
    container.style.display = 'flex';
}

function clearFilePreview() {
    selectedFile = null;
    selectedFileData = null;
    selectedFileType = null;
    document.getElementById('filePreviewContainer').style.display = 'none';
    document.getElementById('fileInput').value = '';
}

function handleAvatarSelect(event) {
    var file = event.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
        document.getElementById('avatarUploadStatus').textContent = '❌ Файл слишком большой (макс 5MB)';
        document.getElementById('avatarUploadStatus').style.color = 'var(--error)';
        return;
    }
    if (!file.type.startsWith('image/')) {
        document.getElementById('avatarUploadStatus').textContent = '❌ Выберите изображение';
        document.getElementById('avatarUploadStatus').style.color = 'var(--error)';
        return;
    }
    var formData = new FormData();
    formData.append('avatar', file);
    document.getElementById('avatarUploadStatus').textContent = '⏳ Загрузка...';
    document.getElementById('avatarUploadStatus').style.color = 'var(--text-secondary)';
    apiFetch('/api/upload-avatar', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(result) {
        if (result.success) {
            document.getElementById('avatarUploadStatus').textContent = '✅ Аватарка обновлена!';
            document.getElementById('avatarUploadStatus').style.color = 'var(--success)';
            var avatarPreview = document.getElementById('settingsAvatarPreview');
            if (avatarPreview) {
                avatarPreview.style.backgroundImage = 'url(' + result.avatar_url + ')';
                avatarPreview.style.backgroundSize = 'cover';
                avatarPreview.style.backgroundPosition = 'center';
                avatarPreview.textContent = '';
            }
            currentUser.avatar_url = result.avatar_url;
            updateHeaderAvatar();
            setTimeout(function() { document.getElementById('avatarUploadStatus').textContent = ''; }, 3000);
        } else {
            document.getElementById('avatarUploadStatus').textContent = '❌ Ошибка: ' + result.message;
            document.getElementById('avatarUploadStatus').style.color = 'var(--error)';
        }
    })
    .catch(function(err) {
        document.getElementById('avatarUploadStatus').textContent = '❌ Ошибка загрузки';
        document.getElementById('avatarUploadStatus').style.color = 'var(--error)';
        console.error('Avatar upload error:', err);
    });
}

function updateHeaderAvatar() {
    var headerAvatar = document.getElementById('userAvatar');
    if (headerAvatar && currentUser.avatar_url) {
        headerAvatar.style.backgroundImage = 'url(' + currentUser.avatar_url + ')';
        headerAvatar.style.backgroundSize = 'cover';
        headerAvatar.style.backgroundPosition = 'center';
        headerAvatar.textContent = '';
    }
}

function updateSettingsJtUsernameStatus(message, isError) {
    var statusEl = document.getElementById('settingsJtUsernameStatus');
    if (statusEl) {
        statusEl.textContent = message;
        statusEl.style.color = isError ? 'var(--error)' : 'var(--success)';
    }
}

function settingsSavejtUsername() {
    var input = document.getElementById('settingsJtUsernameInput');
    var username = input.value.trim().replace('@', '');
    if (!username) {
        setjtUsername('').then(function(result) {
            if (result.success) {
                updateSettingsJtUsernameStatus('Username удалён', false);
                currentUser.jt_username = null;
                renderSettingsContent();
            } else updateSettingsJtUsernameStatus(result.message || 'Ошибка', true);
        }).catch(function(err) { updateSettingsJtUsernameStatus('Ошибка: ' + err.message, true); });
        return;
    }
    if (username.length < 5) { updateSettingsJtUsernameStatus('Username должен быть не менее 5 символов', true); return; }
    if (username.length > 32) { updateSettingsJtUsernameStatus('Username не более 32 символов', true); return; }
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(username)) { updateSettingsJtUsernameStatus('Латиница, цифры, _', true); return; }
    if (username.includes('__')) { updateSettingsJtUsernameStatus('Не может содержать "__"', true); return; }
    if (username.endsWith('_')) { updateSettingsJtUsernameStatus('Не может заканчиваться на "_"', true); return; }
    updateSettingsJtUsernameStatus('Проверка...', false);
    checkUsernameAvailability(username).then(function(result) {
        if (!result.available) { updateSettingsJtUsernameStatus(result.message || 'Занято', true); return; }
        setjtUsername(username).then(function(setResult) {
            if (setResult.success) {
                updateSettingsJtUsernameStatus('Username @' + username + ' установлен!', false);
                currentUser.jt_username = username;
                renderSettingsContent();
            } else updateSettingsJtUsernameStatus(setResult.message || 'Ошибка', true);
        }).catch(function(err) { updateSettingsJtUsernameStatus('Ошибка: ' + err.message, true); });
    }).catch(function(err) { updateSettingsJtUsernameStatus('Ошибка: ' + err.message, true); });
}

function settingsSaveBio() {
    var input = document.getElementById('settingsBioInput');
    var btn = document.getElementById('settingsSaveBioBtn');
    if (!input || !btn) return;
    var newBio = input.value.trim();
    if (newBio.length > 150) { alert('Описание слишком длинное (максимум 150 символов)'); return; }
    btn.disabled = true;
    btn.textContent = '⏳';
    apiFetch('/api/settings/change-bio', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({bio: newBio})
    })
    .then(function(r) {
        var ct = r.headers.get('content-type') || '';
        if (ct.indexOf('application/json') === -1) {
            return r.text().then(function(text) { throw new Error('Server returned non-JSON: ' + text.substring(0, 200)); });
        }
        if (!r.ok) return r.json().then(function(e){ throw new Error(e.message || 'HTTP '+r.status); });
        return r.json();
    })
    .then(function(result) {
        if (result.success) {
            if (currentUser) currentUser.bio = result.bio;
            btn.textContent = '✅';
            loadUsers();
            setTimeout(function(){ btn.textContent = '💾 Сохранить'; btn.disabled = false; }, 1500);
        } else throw new Error(result.message);
    })
    .catch(function(err) {
        alert('Ошибка: ' + err.message);
        btn.textContent = '💾 Сохранить';
        btn.disabled = false;
    });
}

function settingsChangeUsername() {
    var input = document.getElementById('settingsChangeUsernameInput');
    var newUsername = input.value.trim();
    if (!newUsername) { alert('Введите ник'); return; }
    if (newUsername.length < 2) { alert('Имя должно быть не менее 2 символов'); return; }
    apiFetch('/api/settings/change-username', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: newUsername})
    })
    .then(function(r) {
        var contentType = r.headers.get('content-type');
        if (contentType && contentType.indexOf('application/json') !== -1) return r.json();
        throw new Error('Сервер вернул не JSON: ' + r.status);
    })
    .then(function(result) {
        if (result.success) {
            document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
            alert('Ник изменён на: ' + result.username);
            location.reload();
        } else alert('Ошибка: ' + (result.message || 'Неизвестная ошибка'));
    })
    .catch(function(err) {
        if (err.name === 'AbortError') return;
        console.error('changeUsername:', err);
        alert('Ошибка: ' + err.message);
    });
}

function clearMessages() {
    if (!confirm('Вы уверены, что хотите удалить все свои сообщения? Это действие нельзя отменить.')) return;
    apiFetch('/api/settings/clear-messages', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(result) {
            if (result.success) {
                alert('Все ваши сообщения удалены.');
                loadMessages();
            } else alert('Ошибка: ' + (result.message || 'Неизвестная ошибка'));
        })
        .catch(function(err) { console.error('clearMessages:', err); alert('Ошибка: ' + err.message); });
}

function deleteAccount() {
    if (!confirm('ВНИМАНИЕ: Вы уверены, что хотите удалить свой аккаунт? Это действие нельзя отменить.')) return;
    apiFetch('/api/settings/delete-account', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(result) {
            if (result.success) { alert('Ваш аккаунт удалён.'); location.reload(); }
            else alert('Ошибка: ' + (result.message || 'Неизвестная ошибка'));
        })
        .catch(function(err) { console.error('deleteAccount:', err); alert('Ошибка: ' + err.message); });
}

function checkUsernameAvailability(username) {
    username = username.replace('@', '');
    return apiFetch('/api/username/check', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: username})
    })
    .then(function(r) { return r.json(); });
}

function setjtUsername(username) {
    return apiFetch('/api/username/set', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({jt_username: username})
    })
    .then(function(r) { return r.json(); });
}

function updateOnlineStatus() {
    apiFetch('/api/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: currentDeviceId })
    })
    .then(function(r) {
        if (r.ok) {
            var headerStatus = document.querySelector('.header .user-info span');
            if (headerStatus) {
                headerStatus.textContent = ' В сети';
                headerStatus.style.color = 'rgb(29, 180, 24)';
            }
            updateChatHeader();
        }
    })
    .catch(function(err) {
        console.error('updateOnlineStatus:', err);
        var headerStatus = document.querySelector('.header .user-info span');
        if (headerStatus) {
            headerStatus.textContent = ' Не в сети';
            headerStatus.style.color = 'var(--text-secondary)';
        }
    });
}

var loadingPhrases = [
    'Вспоминаем, что ты там писал...',
    'Поднимаем всю твою переписку...',
    'Показываем твою переписку ФСБ...',
    'Смеемся вместе с ФСБ от того что ты отправлял...',
    'Загружаем сообщения...',
    'Ищем, твои секреты...',
    'Проверяем, не удалил ли ты чаты...',
    'Восстанавливаем историю великих диалогов...',
    'Стараемся ускорить процесс...',
    'Ага, получилось...',
    'Решаем ничего с этим не делать...'
];
var loadingInterval = null;
var messagesLoaded = false;

function showChat() {
    document.getElementById('loginPage').style.display = 'none';
    document.getElementById('loadingScreen').style.display = 'flex';
    document.getElementById('chatPage').style.display = 'none';
    startLoadingPhrases();
    preloadAllMessages().then(function() {
        messagesLoaded = true;
        setTimeout(function() {
            stopLoadingPhrases();
            document.getElementById('loadingScreen').style.display = 'none';
            document.getElementById('chatPage').style.display = 'flex';
            finishShowChat();
        }, 2000);
    }).catch(function(err) {
        console.error('Preload error:', err);
        messagesLoaded = true;
        setTimeout(function() {
            stopLoadingPhrases();
            document.getElementById('loadingScreen').style.display = 'none';
            document.getElementById('chatPage').style.display = 'flex';
            finishShowChat();
        }, 2000);
    });
}

function startLoadingPhrases() {
    var loadingTextEl = document.getElementById('loadingText');
    loadingTextEl.className = 'loading-text';
    loadingInterval = setInterval(function() {
        var randomIndex = Math.floor(Math.random() * loadingPhrases.length);
        loadingTextEl.style.opacity = '0';
        setTimeout(function() {
            loadingTextEl.textContent = loadingPhrases[randomIndex];
            loadingTextEl.style.opacity = '1';
        }, 200);
    }, 1500);
}

function stopLoadingPhrases() {
    if (loadingInterval) { clearInterval(loadingInterval); loadingInterval = null; }
}

function preloadAllMessages() {
    return new Promise(function(resolve) {
        apiFetch('/api/users')
            .then(function(r) { return r.json(); })
            .then(function(usersList) {
                var promises = [];
                promises.push(
                    apiFetch('/api/messages')
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data && data.length > 0) saveMessagesToCache(data, 0).catch(console.error);
                        })
                        .catch(console.error)
                );
                usersList.forEach(function(user) {
                    if (user.id && user.id !== currentUser.id) {
                        promises.push(
                            apiFetch('/api/messages/' + user.id)
                                .then(function(r) { return r.json(); })
                                .then(function(data) {
                                    if (data && data.length > 0) saveMessagesToCache(data, user.id).catch(console.error);
                                })
                                .catch(console.error)
                        );
                    }
                });
                Promise.all(promises).then(function() { resolve(); });
            })
            .catch(function(err) { console.error('Preload error:', err); resolve(); });
    });
}

function finishShowChat() {
    var headerAvatar = document.getElementById('userAvatar');
    if (currentUser.avatar_url) {
        headerAvatar.style.backgroundImage = 'url(' + currentUser.avatar_url + ')';
        headerAvatar.style.backgroundSize = 'cover';
        headerAvatar.style.backgroundPosition = 'center';
        headerAvatar.textContent = '';
    } else {
        headerAvatar.style.backgroundImage = '';
        headerAvatar.style.background = '#6366f1';
        headerAvatar.textContent = currentUser.username.charAt(0).toUpperCase();
    }
    var displayName = currentUser.username;
    if (currentUser.jt_username) displayName += ' @' + currentUser.jt_username;
    document.getElementById('headerUsername').textContent = displayName;
    loadUsers();
    loadMessages();
    updateOnlineStatus();
    setTimeout(function() {
        lastKnownMessageCount = messages.length;
        currentLoadUserId = selectedUserId;
    }, 500);
    setTimeout(function() { scrollToBottom(); }, 100);
    if (onlineInterval) clearInterval(onlineInterval);
    if (lastMessagesInterval) clearInterval(lastMessagesInterval);
    if (messagesInterval) clearInterval(messagesInterval);
    onlineInterval = setInterval(function() {
        updateOnlineStatus();
        loadUsers();
    }, 2000);
    lastMessagesInterval = setInterval(function() { loadLastMessages(); }, 3000);
    messagesInterval = setInterval(function() {
        if (currentLoadUserId !== null && currentLoadUserId === selectedUserId) checkNewMessages();
    }, 5000);
    initTabs();
    showFooter();
    showChatsTab();
}

var resizeTimeout;
window.addEventListener('resize', function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function() { scrollToBottom(); }, 300);
});

var lastKnownMessageCount = 0;
var notifiedMsgIds = {};

function checkNewMessages() {
    var url = selectedUserId === 0 ? '/api/messages' : '/api/messages/' + selectedUserId;
    apiFetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!Array.isArray(data)) return;
            for (var i = 0; i < data.length; i++) {
                var m = data[i];
                if (!m.is_mine && !notifiedMsgIds[m.id]) {
                    notifiedMsgIds[m.id] = true;
                    if (!document.hasFocus() || selectedUserId === 0) showSystemNotification(m.sender, m.content, m.file_type);
                }
            }
            lastKnownMessageCount = data.length;
        })
        .catch(function() {});
}

function checkUnreadNotifications() {
    apiFetch('/api/users')
        .then(function(r) { return r.json(); })
        .then(function(ul) {
            var totalUnread = 0;
            for (var i = 0; i < ul.length; i++) totalUnread += (ul[i].unread_count || 0);
            if (totalUnread > lastUnreadCount && totalUnread > 0) {
                for (var j = 0; j < ul.length; j++) {
                    if (ul[j].unread_count > 0 && ul[j].id !== selectedUserId) {
                        showSystemNotification(ul[j].username, 'Новое сообщение', null);
                        break;
                    }
                }
            }
            lastUnreadCount = totalUnread;
        })
        .catch(function() {});
}

var lastUnreadCount = 0;

function showSystemNotification(from, content, fileType) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (document.hasFocus() && selectedUserId > 0) return;
    var body = fileType === 'voice' ? '🎤 Голосовое сообщение' :
               fileType === 'image' ? '📷 Фото' :
               (content ? content.substring(0, 80) : 'Новое сообщение');
    try {
        var n = new Notification('💬 ' + from, {
            body: body, icon: '/Jetesk.png', badge: '/Jetesk.png',
            tag: 'jetesk-' + Date.now(), requireInteraction: false, silent: false
        });
        n.onclick = function() { window.focus(); n.close(); };
        if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    } catch(e) {}
}

function showToast(msg) {
    var t = document.createElement('div');
    t.textContent = msg;
    Object.assign(t.style, {
        position: 'fixed', bottom: '20px', left: '50%', transform: 'translateX(-50%)',
        background: '#1e293b', color: '#f1f5f9', padding: '12px 18px', borderRadius: '12px',
        zIndex: '9999', fontSize: '14px', textAlign: 'center', maxWidth: '90%',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)', whiteSpace: 'pre-wrap', lineHeight: '1.4'
    });
    document.body.appendChild(t);
    setTimeout(function(){ t.remove(); }, 6000);
}

var THEME_KEY = 'jtesk_theme';

function loadTheme() {
    var savedTheme = localStorage.getItem(THEME_KEY);
    if (savedTheme === 'light') {
        document.documentElement.classList.add('light-theme');
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', '#4f46e5');
    }
}

function saveTheme(isLight) {
    localStorage.setItem(THEME_KEY, isLight ? 'light' : 'dark');
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', isLight ? '#4f46e5' : '#0f172a');
}

function toggleTheme() {
    var isLight = document.documentElement.classList.toggle('light-theme');
    saveTheme(isLight);
}

function showAuthChoice() {
    hideAllAuthCards();
    document.getElementById('authChoiceCard').style.display = 'block';
    document.getElementById('authSubtitle').textContent = 'Выберите действие';
}
function showLoginForm() {
    hideAllAuthCards();
    document.getElementById('loginFormCard').style.display = 'block';
    document.getElementById('authSubtitle').textContent = 'Вход в аккаунт';
    document.getElementById('loginNameInput').focus();
}
function showRegisterForm() {
    hideAllAuthCards();
    document.getElementById('registerFormCard').style.display = 'block';
    document.getElementById('authSubtitle').textContent = 'Регистрация';
    document.getElementById('regNameInput').focus();
}
function showAvatarSetup() {
    hideAllAuthCards();
    document.getElementById('avatarSetupCard').style.display = 'block';
    document.getElementById('authSubtitle').textContent = 'Настройка профиля';
    updateAvatarPreview();
}
function hideAllAuthCards() {
    ['authChoiceCard','loginFormCard','registerFormCard','avatarSetupCard'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}

var selectedAvatarFile = null;
var selectedAvatarData = null;
var selectedAvatarColor = '#6366f1';
var pendingRegistration = null;

function updateAvatarPreview() {
    var letter = document.getElementById('avatarPreviewLetter');
    var img = document.getElementById('avatarPreviewImg');
    var preview = document.getElementById('avatarPreview');
    if (selectedAvatarData) {
        img.src = selectedAvatarData;
        img.style.display = 'block';
        letter.style.display = 'none';
    } else if (pendingRegistration && pendingRegistration.name) {
        letter.textContent = pendingRegistration.name.charAt(0).toUpperCase();
        letter.style.display = 'block';
        img.style.display = 'none';
    }
    preview.style.background = selectedAvatarData ? 'transparent' : selectedAvatarColor;
}

function handleAvatarSetup(event) {
    var file = event.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
        document.getElementById('avatarSetupStatus').textContent = '❌ Файл слишком большой (макс 5MB)';
        document.getElementById('avatarSetupStatus').style.color = 'var(--error)';
        return;
    }
    var reader = new FileReader();
    reader.onload = function(e) {
        selectedAvatarData = e.target.result;
        selectedAvatarFile = file;
        updateAvatarPreview();
        document.getElementById('avatarSetupStatus').textContent = '✅ Фото загружено!';
        document.getElementById('avatarSetupStatus').style.color = 'var(--success)';
    };
    reader.readAsDataURL(file);
}

function selectAvatarColor(color, event) {
    selectedAvatarColor = color;
    if (!selectedAvatarData) updateAvatarPreview();
    document.querySelectorAll('.avatar-color-btn').forEach(function(el) { el.style.border = '3px solid transparent'; });
    if (event && event.target) event.target.style.border = '3px solid white';
}

function loginWithPassword() {
    var name = document.getElementById('loginNameInput').value.trim();
    var password = document.getElementById('loginPasswordInput').value;
    var errorEl = document.getElementById('loginError');
    var btn = document.getElementById('loginBtn');
    if (!name) { errorEl.textContent = 'Введите имя'; return; }
    if (name.length < 2) { errorEl.textContent = 'Имя должно быть не менее 2 символов'; return; }
    if (!password) { errorEl.textContent = 'Введите пароль'; return; }
    if (password.length < 6) { errorEl.textContent = 'Пароль должен быть не менее 6 символов'; return; }
    if (btn) { btn.disabled = true; btn.textContent = 'Вход...'; }
    apiFetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ username: name, password: password, device_id: currentDeviceId, device_name: currentDeviceName })
    })
    .then(function(r) {
        if (!r.ok) return r.json().then(function(e){ throw new Error(e.message || 'HTTP '+r.status); });
        return r.json();
    })
    .then(function(result) {
        if (result.success) {
            currentUser = result.user;
            if (result.current_device) currentUser.current_device = result.current_device;
            showChat();
            setTimeout(function() { subscribeToPush(); }, 3000);
            setTimeout(function() { showIosPwaModal(); }, 5000);
        } else errorEl.textContent = result.message || 'Неверный логин или пароль';
    })
    .catch(function(err) { errorEl.textContent = 'Ошибка: ' + err.message; })
    .finally(function() { if (btn) { btn.disabled = false; btn.textContent = 'Войти'; } });
}

function startRegistration() {
    var name = document.getElementById('regNameInput').value.trim();
    var username = document.getElementById('regUsernameInput').value.trim().replace('@', '');
    var password = document.getElementById('regPasswordInput').value;
    var errorEl = document.getElementById('registerError');
    if (!name || name.length < 2) { errorEl.textContent = 'Имя должно быть не менее 2 символов'; return; }
    if (!username || username.length < 4) { errorEl.textContent = 'Username должен быть 4-32 символа'; return; }
    if (username.length > 32) { errorEl.textContent = 'Username слишком длинный'; return; }
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(username)) { errorEl.textContent = 'Username: латиница, цифры, _ (начинается с буквы)'; return; }
    if (!password || password.length < 6) { errorEl.textContent = 'Пароль должен быть не менее 6 символов'; return; }
    pendingRegistration = { name: name, username: username, password: password };
    selectedAvatarData = null;
    selectedAvatarFile = null;
    errorEl.textContent = '';
    showAvatarSetup();
}

function finishRegistration() {
    if (!pendingRegistration) return;
    var statusEl = document.getElementById('avatarSetupStatus');
    statusEl.textContent = '⏳ Регистрация...';
    statusEl.style.color = 'var(--text-secondary)';
    var formData = new FormData();
    formData.append('name', pendingRegistration.name);
    formData.append('username', pendingRegistration.username);
    formData.append('password', pendingRegistration.password);
    formData.append('avatar_color', selectedAvatarColor);
    if (selectedAvatarFile) formData.append('avatar_file', selectedAvatarFile);
    apiFetch('/api/register', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(result) {
        if (result.success) {
            currentUser = result.user;
            showChat();
        } else {
            statusEl.textContent = '❌ ' + (result.message || 'Ошибка регистрации');
            statusEl.style.color = 'var(--error)';
        }
    })
    .catch(function(err) {
        statusEl.textContent = '❌ Ошибка: ' + err.message;
        statusEl.style.color = 'var(--error)';
    });
}


function subscribeToPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    navigator.serviceWorker.ready.then(function(reg) {
        return apiFetch('/api/push/vapid-public-key')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var publicKey = data.public_key;
                if (!publicKey) return;
                var applicationServerKey = urlBase64ToUint8Array(publicKey);
                return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: applicationServerKey });
            })
            .then(function(subscription) {
                if (!subscription) return;
                return apiFetch('/api/push/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: subscription.endpoint, keys: subscription.toJSON().keys, device_id: currentDeviceId })
                });
            })
            .catch(function(err) { console.error('[Push] Subscribe error:', err); });
    }).catch(function(err) { console.error('[Push] SW not ready:', err); });
}

function urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
}


function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}
function isPWA() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}
function showIosPwaModal() {
    if (!isIOS() || isPWA()) return;
    if (localStorage.getItem('jetesk_ios_pwa_shown')) return;
    var modal = document.getElementById('iosPwaModal');
    if (modal) modal.style.display = 'flex';
}
function closeIosPwaModal() {
    var modal = document.getElementById('iosPwaModal');
    if (modal) modal.style.display = 'none';
    localStorage.setItem('jetesk_ios_pwa_shown', '1');
}

var ringtoneAudio = null;
var wakeLock = null;
var callNotification = null;

function updateCallBtnVisibility() {
    var btn = document.getElementById('callBtn');
    if (!btn) return;
    if (selectedUserId > 0) btn.classList.add('visible');
    else btn.classList.remove('visible');
}

function startCall() {
    if (selectedUserId <= 0 || isInCall) return;
    requestNotificationPermission();
    isInCall = true;
    isIncomingCall = false;
    currentCallId = 'call_' + Date.now();
    showCallUI(selectedUserId, selectedUsername);
    document.getElementById('callStatus').textContent = 'Вызов...';
    document.getElementById('callControls').style.display = 'flex';
    document.getElementById('incomingControls').style.display = 'none';
    document.getElementById('incomingLabel').style.display = 'none';
    document.getElementById('callTimer').classList.remove('active');
    requestWakeLock();
    getLocalAudio().then(function() {
        createPeerConnection();
        return peerConnection.createOffer();
    }).then(function(offer) {
        return peerConnection.setLocalDescription(offer);
    }).then(function() {
        return apiFetch('/api/call/offer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ call_id: currentCallId, to_user_id: selectedUserId, offer: peerConnection.localDescription })
        });
    }).then(function(r) {
        if (!r.ok) throw new Error('Не удалось отправить вызов');
        return r.json();
    }).then(function() {
        document.getElementById('callStatus').textContent = 'Ожидание ответа...';
        startCallPolling();
    }).catch(function(err) {
        console.error('[Call] Ошибка:', err);
        endCall();
    });
}

function getLocalAudio() {
    return navigator.mediaDevices.getUserMedia({ audio: true, video: false })
        .then(function(stream) { localStream = stream; return stream; });
}

function createPeerConnection() {
    peerConnection = new RTCPeerConnection(rtcConfig);
    if (localStream) localStream.getTracks().forEach(function(track) { peerConnection.addTrack(track, localStream); });
    peerConnection.addEventListener('track', function(e) {
        var remoteAudio = document.getElementById('remoteAudio');
        remoteAudio.srcObject = e.streams[0];
        remoteAudio.play().catch(function(){});
    });
    peerConnection.addEventListener('icecandidate', function(e) {
        if (e.candidate && currentCallId) {
            apiFetch('/api/call/ice', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ call_id: currentCallId, to_user_id: selectedUserId, candidate: e.candidate })
            }).catch(function(err) { console.error('[Call] ICE error:', err); });
        }
    });
    peerConnection.addEventListener('connectionstatechange', function() {
        if (peerConnection.connectionState === 'connected') {
            document.getElementById('callStatus').textContent = 'Разговор';
            startCallTimer();
        } else if (peerConnection.connectionState === 'disconnected' || peerConnection.connectionState === 'failed') {
            endCall();
        }
    });
}

function startCallPolling() {
    if (callPollInterval) clearInterval(callPollInterval);
    callPollInterval = setInterval(function() {
        if (!isInCall || isIncomingCall) return;
        apiFetch('/api/call/status/' + currentCallId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.status) return;
                if (data.status === 'rejected' || data.status === 'ended' || data.status === 'missed') {
                    document.getElementById('callStatus').textContent = 'Звонок завершён';
                    stopCallPolling();
                    setTimeout(function() { endCall(); }, 1000);
                    return;
                }
                if (data.answer) {
                    stopCallPolling();
                    return peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer))
                        .then(function() {
                            document.getElementById('callStatus').textContent = 'Подключение...';
                            exchangeIceCandidates();
                            startCallHealthCheck();
                        });
                }
            })
            .catch(function(err) { console.error('[Call] Poll error:', err); });
    }, 1000);
}

function exchangeIceCandidates() {
    if (callPollInterval) clearInterval(callPollInterval);
    var iceExchangeInterval = setInterval(function() {
        if (!isInCall) { clearInterval(iceExchangeInterval); return; }
        apiFetch('/api/call/ice/' + currentCallId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data && data.candidates && peerConnection) {
                    data.candidates.forEach(function(c) {
                        peerConnection.addIceCandidate(new RTCIceCandidate(c)).catch(function(){});
                    });
                }
            })
            .catch(function(){});
    }, 1000);
    setTimeout(function() {
        clearInterval(iceExchangeInterval);
        if (isInCall) startCallHealthCheck();
    }, 15000);
}

function startCallHealthCheck() {
    if (callPollInterval) clearInterval(callPollInterval);
    callPollInterval = setInterval(function() {
        if (!isInCall) return;
        apiFetch('/api/call/check/' + currentCallId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.status) return;
                if (data.status === 'ended' || data.status === 'rejected') {
                    document.getElementById('callStatus').textContent = 'Звонок завершён';
                    stopCallPolling();
                    setTimeout(function() { endCall(); }, 1000);
                }
            })
            .catch(function(){});
    }, 1500);
}

function stopCallPolling() {
    if (callPollInterval) { clearInterval(callPollInterval); callPollInterval = null; }
}

function checkIncomingCalls() {
    if (isInCall) return;
    apiFetch('/api/call/incoming')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data || !data.call_id) return;
            isInCall = true;
            isIncomingCall = true;
            currentCallId = data.call_id;
            selectedUserId = data.from_user_id;
            selectedUsername = data.from_user_name || 'Пользователь';
            showCallUI(selectedUserId, selectedUsername);
            document.getElementById('callStatus').textContent = 'Входящий звонок...';
            document.getElementById('callControls').style.display = 'none';
            document.getElementById('incomingControls').style.display = 'flex';
            document.getElementById('incomingLabel').style.display = 'block';
            document.getElementById('callTimer').classList.remove('active');
            requestNotificationPermission();
            playCallRingtone();
            vibratePhone();
            showCallNotification();
            requestWakeLock();
            startIncomingHealthCheck();
        })
        .catch(function(){});
}

function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
}

function playCallRingtone() {
    stopCallRingtone();
    try {
        ringtoneAudio = new Audio('/rington.mp3');
        ringtoneAudio.loop = true;
        ringtoneAudio.volume = 1.0;
        ringtoneAudio.play().catch(function(e) {
            document.addEventListener('click', function unblockRingtone() {
                if (ringtoneAudio && isIncomingCall) ringtoneAudio.play().catch(function(){});
                document.removeEventListener('click', unblockRingtone);
            });
        });
    } catch(e) { console.error('[Call] Ringtone error:', e); }
}

function stopCallRingtone() {
    if (ringtoneAudio) {
        try { ringtoneAudio.pause(); ringtoneAudio.src = ''; } catch(e) {}
        ringtoneAudio = null;
    }
}

function stopIncomingRingtone() { stopCallRingtone(); }

function vibratePhone() {
    if ('vibrate' in navigator) {
        function vibrateLoop() {
            if (!isIncomingCall) return;
            navigator.vibrate([1000, 500, 1000, 500, 1000]);
            setTimeout(function() { if (isIncomingCall) vibrateLoop(); }, 4000);
        }
        vibrateLoop();
    }
}

function showCallNotification() {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    var name = selectedUsername || 'Неизвестный';
    callNotification = new Notification('📞 Входящий звонок', {
        body: name + ' звонит вам...',
        icon: '/Jetesk.png',
        tag: 'incoming-call-' + currentCallId,
        requireInteraction: true,
        silent: false
    });
    callNotification.onclick = function() { window.focus(); this.close(); };
}

function closeCallNotification() {
    if (callNotification) { callNotification.close(); callNotification = null; }
}

function requestWakeLock() {
    if ('wakeLock' in navigator) {
        navigator.wakeLock.request('screen').then(function(lock) { wakeLock = lock; }).catch(function(e) {});
    }
}
function releaseWakeLock() {
    if (wakeLock) { wakeLock.release(); wakeLock = null; }
}

document.addEventListener('visibilitychange', function() {
    if (!document.hidden && isIncomingCall && currentCallId) showCallUI(selectedUserId, selectedUsername);
});

function startIncomingHealthCheck() {
    if (callPollInterval) clearInterval(callPollInterval);
    callPollInterval = setInterval(function() {
        if (!isInCall || !isIncomingCall) return;
        apiFetch('/api/call/check/' + currentCallId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.status) return;
                if (data.status === 'ended' || data.status === 'rejected') {
                    stopIncomingRingtone();
                    stopCallPolling();
                    document.getElementById('callStatus').textContent = 'Звонок отменён';
                    setTimeout(function() { endCall(); }, 1500);
                }
            })
            .catch(function(){});
    }, 1500);
}

function acceptCall() {
    if (!currentCallId) return;
    stopCallRingtone();
    stopIncomingRingtone();
    stopCallPolling();
    closeCallNotification();
    releaseWakeLock();
    getLocalAudio().then(function() {
        createPeerConnection();
        return apiFetch('/api/call/accept', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ call_id: currentCallId })
        });
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        document.getElementById('incomingControls').style.display = 'none';
        document.getElementById('incomingLabel').style.display = 'none';
        document.getElementById('callControls').style.display = 'flex';
        if (data && data.offer) {
            return peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer))
                .then(function() { return peerConnection.createAnswer(); })
                .then(function(answer) { return peerConnection.setLocalDescription(answer); })
                .then(function() {
                    return apiFetch('/api/call/answer', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ call_id: currentCallId, answer: peerConnection.localDescription })
                    });
                });
        }
    })
    .then(function() {
        document.getElementById('callStatus').textContent = 'Подключение...';
        exchangeIceCandidates();
    })
    .catch(function(err) { console.error('[Call] Accept error:', err); endCall(); });
}

function rejectCall() {
    if (!currentCallId) return;
    stopCallRingtone();
    stopIncomingRingtone();
    stopCallPolling();
    closeCallNotification();
    releaseWakeLock();
    apiFetch('/api/call/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ call_id: currentCallId })
    }).catch(function(){});
    endCall();
}

function endCall() {
    isInCall = false;
    isIncomingCall = false;
    stopCallTimer();
    stopCallPolling();
    stopCallRingtone();
    stopIncomingRingtone();
    closeCallNotification();
    releaseWakeLock();
    if (peerConnection) { peerConnection.close(); peerConnection = null; }
    if (localStream) { localStream.getTracks().forEach(function(track) { track.stop(); }); localStream = null; }
    if (currentCallId) {
        apiFetch('/api/call/end', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ call_id: currentCallId })
        }).catch(function(){});
        currentCallId = null;
    }
    hideCallUI();
}

function toggleCallMute() {
    if (!localStream) return;
    isCallMuted = !isCallMuted;
    localStream.getAudioTracks().forEach(function(track) { track.enabled = !isCallMuted; });
    var btn = document.getElementById('callMuteBtn');
    if (isCallMuted) {
        btn.classList.add('muted');
        btn.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-2.31.31l-1.63-1.63C14.42 8.63 13.31 8 12 8c-1.61 0-2.98.89-3.64 2.2l2.06 2.06C10.15 12.09 10 11.56 10 11c0-.51.13-.99.37-1.4l6.32 6.32V19h2v-3.17l1.96 1.96c.15-.32.24-.67.24-1.04 0-.28-.06-.55-.17-.79l-2.03-2.03zM12 14c.51 0 .99-.13 1.41-.37l-1.04-1.04c-.12.03-.24.04-.37.04-.72 0-1.37-.29-1.84-.77L8.58 10.29C7.8 10.82 7.2 11.59 6.91 12.5L12 17.59V14zM4.41 2.86L3 4.27l6 6V11c0 1.66 1.34 3 3 3 .23 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.77-.45 2.55-.9l4.18 4.18 1.41-1.41L4.41 2.86z"/></svg>';
    } else {
        btn.classList.remove('muted');
        btn.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>';
    }
}

function startCallTimer() {
    callSeconds = 0;
    document.getElementById('callTimer').classList.add('active');
    callTimer = setInterval(function() {
        callSeconds++;
        var m = Math.floor(callSeconds / 60);
        var s = callSeconds % 60;
        document.getElementById('callTimer').textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }, 1000);
}

function stopCallTimer() {
    if (callTimer) { clearInterval(callTimer); callTimer = null; }
    callSeconds = 0;
    var t = document.getElementById('callTimer');
    if (t) { t.classList.remove('active'); t.textContent = '00:00'; }
}

function showCallUI(userId, username) {
    var overlay = document.getElementById('callModal');
    var avatarEl = document.getElementById('callAvatar');
    var nameEl = document.getElementById('callName');
    nameEl.textContent = username;
    var targetUser = null;
    for (var i = 0; i < users.length; i++) { if (users[i].id === userId) { targetUser = users[i]; break; } }
    if (targetUser && targetUser.avatar_url) {
        avatarEl.style.backgroundImage = 'url(' + targetUser.avatar_url + ')';
        avatarEl.style.backgroundSize = 'cover';
        avatarEl.style.backgroundPosition = 'center';
        avatarEl.textContent = '';
    } else {
        avatarEl.style.backgroundImage = '';
        avatarEl.style.background = '#' + (targetUser ? targetUser.avatar_color || '6366f1' : '6366f1');
        avatarEl.textContent = (username || '?').charAt(0).toUpperCase();
    }
    overlay.classList.add('show');
}

function hideCallUI() {
    document.getElementById('callModal').classList.remove('show');
    document.getElementById('callStatus').textContent = '';
    document.getElementById('callControls').style.display = 'none';
    document.getElementById('incomingControls').style.display = 'none';
    document.getElementById('incomingLabel').style.display = 'none';
    var mb = document.getElementById('callMuteBtn');
    if (mb) {
        mb.classList.remove('muted');
        mb.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>';
    }
}

setInterval(function() { if (!isInCall && currentUser) checkIncomingCalls(); }, 2000);

function openSettingsModal() {
    showSettingsTab();
}

function closeSettingsModal() {
    showChatsTab();
}

document.addEventListener('DOMContentLoaded', function() {
    var messagesContainer = document.getElementById('messagesContainer');
    if (messagesContainer) {
        messagesContainer.addEventListener('scroll', function() {
            var btn = document.getElementById('scrollToBottomBtn');
            var isAtBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < 50;
            if (!isAtBottom) btn.style.display = 'flex';
            else btn.style.display = 'none';
        });
    }
    var messageInput = document.getElementById('messageInput');
    if (messageInput) {
        messageInput.addEventListener('input', function() {
            var btn = document.getElementById('sendBtn');
            btn.disabled = !messageInput.value.trim();
        });
        messageInput.addEventListener('keypress', function(e) { if (e.key === 'Enter') sendMessage(); });
    }
    var loginBtn = document.getElementById('loginBtn');
    if (loginBtn) loginBtn.addEventListener('click', loginWithPassword);
    var loginPass = document.getElementById('loginPasswordInput');
    if (loginPass) loginPass.addEventListener('keypress', function(e) { if (e.key === 'Enter') loginWithPassword(); });
    var registerBtn = document.getElementById('registerBtn');
    if (registerBtn) registerBtn.addEventListener('click', startRegistration);
    var regPass = document.getElementById('regPasswordInput');
    if (regPass) regPass.addEventListener('keypress', function(e) { if (e.key === 'Enter') startRegistration(); });
    var pushToggleBtn = document.getElementById('pushToggleBtn');
    if (pushToggleBtn) {
        pushToggleBtn.addEventListener('click', function() {
            if (!('Notification' in window)) {
                document.getElementById('pushStatus').textContent = 'Уведомления не поддерживаются ❌';
                return;
            }
            if (Notification.permission === 'granted') {
                document.getElementById('pushStatus').textContent = '✅ Уведомления уже включены';
                pushToggleBtn.textContent = '✅ Уведомления включены';
                pushToggleBtn.disabled = true;
            } else {
                Notification.requestPermission().then(function(perm) {
                    if (perm === 'granted') {
                        document.getElementById('pushStatus').textContent = '✅ Уведомления включены';
                        pushToggleBtn.textContent = '✅ Уведомления включены';
                        pushToggleBtn.disabled = true;
                    } else {
                        document.getElementById('pushStatus').textContent = '❌ Разрешение не получено';
                    }
                });
            }
        });
    }
    var settingsCloseBtn = document.getElementById('settingsCloseBtn');
    if (settingsCloseBtn) settingsCloseBtn.addEventListener('click', closeSettingsModal);
});


if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(function(reg) {
            reg.addEventListener('updatefound', function() {
                var newWorker = reg.installing;
                newWorker.addEventListener('statechange', function() {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        showUpdateNotification();
                    }
                });
            });
        })
        .catch(function(err) { console.error('[PWA] SW error:', err); });
}

function showUpdateNotification() {
    var notification = document.createElement('div');
    notification.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--primary,#6366f1);color:white;padding:16px 24px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.3);z-index:10000;cursor:pointer;';
    notification.innerHTML = '🔄 Доступна новая версия! Нажмите для обновления';
    notification.onclick = function() { location.reload(); };
    document.body.appendChild(notification);
    setTimeout(function() { notification.remove(); }, 10000);
}


if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}