from flask import Flask, render_template_string, request, jsonify, redirect, make_response
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import secrets
import os
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

# ==================== НАСТРОЙКА БД ====================
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # PostgreSQL для Vercel/продакшена
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10
    )
    IS_POSTGRES = True
else:
    # SQLite для локальной разработки
    engine = create_engine(
        'sqlite:///messenger.db',
        echo=False,
        connect_args={'check_same_thread': False}
    )
    IS_POSTGRES = False

SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', 5000))

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
CORS(app, supports_credentials=True, origins=['*'])
Base = declarative_base()

# ==================== МОДЕЛИ ====================
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    avatar_color = Column(String(20), default='6366f1')
    
    messages = relationship('Message', back_populates='sender',
                          foreign_keys='Message.sender_id',
                          cascade='all, delete-orphan')


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    content = Column(String(1000000), nullable=False)  # Увеличено для base64 файлов
    file_type = Column(String(20), nullable=True)  # 'image', 'file', или None для текста
    created_at = Column(DateTime, default=datetime.now, index=True)

    sender = relationship('User', back_populates='messages', foreign_keys=[sender_id])


# ==================== БД ФУНКЦИИ ====================
def init_db():
    """Инициализация БД с автоматической миграцией"""
    Base.metadata.create_all(engine)
    
    # Автоматическая миграция для PostgreSQL (Vercel)
    if DATABASE_URL:
        try:
            conn = engine.connect()
            conn.execute(text("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'messages' AND column_name = 'file_type'
                    ) THEN
                        ALTER TABLE messages ADD COLUMN file_type VARCHAR(20);
                    END IF;
                END $$;
            """))
            conn.execute(text("""
                DO $$ 
                BEGIN 
                    ALTER TABLE messages ALTER COLUMN content TYPE VARCHAR(1000000);
                END $$;
            """))
            conn.commit()
            conn.close()
            print("[OK] Миграция БД выполнена")
        except Exception as e:
            print(f"[WARN] Ошибка миграции: {e}")


def get_db():
    Session = sessionmaker(bind=engine)
    return Session()


def get_current_user():
    username = request.cookies.get('username')
    if not username:
        return None
    db = get_db()
    try:
        user = db.query(User).filter_by(username=username).first()
        return user
    finally:
        db.close()


def generate_avatar_color():
    colors = ['6366f1', '10b981', 'f59e0b', 'ef4444', '8b5cf6', 'ec4899', '0891b2', '7c3aed']
    import random
    return random.choice(colors)


def escape_html(text):
    if not text:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


# ==================== HTML ШАБЛОН ====================
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Мессенджер Jetesk</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg: #0f172a; --surface: #1e293b; --primary: #6366f1;
            --text: #ffffff; --text-secondary: #94a3b8; --border: #334155;
            --message-me: #4f46e5; --message-other: #3f3f5f;
            --success: #10b981; --error: #ef4444;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            min-height: 100vh; overflow: hidden;
        }
        .container { max-width: 1400px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; }
        .login-page { flex: 1; display: flex; align-items: center; justify-content: center; }
        .login-card {
            background: var(--surface); border-radius: 24px; padding: 50px 40px;
            width: 100%; max-width: 420px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); text-align: center;
        }
        .login-icon { font-size: 80px; margin-bottom: 20px; }
        .login-title { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
        .login-subtitle { color: var(--text-secondary); margin-bottom: 30px; }
        .input-group { margin-bottom: 20px; text-align: left; }
        .input-group label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 14px; }
        .input-group input {
            width: 100%; padding: 16px; border: 2px solid var(--border); border-radius: 12px;
            font-size: 16px; background: var(--bg); color: var(--text);
        }
        .input-group input:focus { outline: none; border-color: var(--primary); }
        .btn {
            width: 100%; padding: 16px; background: linear-gradient(135deg, var(--primary), #4f46e5);
            color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer;
        }
        .btn:hover { transform: translateY(-2px); }
        .btn-secondary {
            background: transparent; border: 2px solid var(--border); margin-top: 12px;
        }
        .btn-secondary:hover { border-color: var(--primary); }
        .error-msg { color: var(--error); margin-top: 15px; font-size: 13px; }
        .toggle-link { color: var(--primary); cursor: pointer; text-decoration: underline; margin-top: 15px; display: block; font-size: 14px; }
        .form-section { display: none; }
        .form-section.active { display: block; }
        .chat-page { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .header {
            background: var(--surface); padding: 16px 24px; display: flex;
            justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border);
        }
        .header-left { display: flex; align-items: center; gap: 12px; }
        .avatar {
            width: 44px; height: 44px; border-radius: 50%;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 18px;
        }
        .user-info h2 { font-size: 16px; font-weight: 600; }
        .user-info span { font-size: 13px; color: var(--success); }
        .logout-btn {
            padding: 10px 20px; background: var(--bg); border: 1px solid var(--border);
            border-radius: 8px; color: var(--text); cursor: pointer; font-size: 14px;
        }
        .chat-body { flex: 1; display: flex; overflow: hidden; }
        .users-panel {
            width: 300px; background: var(--surface); border-right: 1px solid var(--border);
            display: flex; flex-direction: column;
        }
        .users-header { padding: 16px 20px; border-bottom: 1px solid var(--border); font-weight: 600; }
        .users-list { flex: 1; overflow-y: auto; padding: 10px; }
        .user-item {
            padding: 12px 16px; border-radius: 8px; cursor: pointer; display: flex;
            align-items: center; gap: 12px; margin-bottom: 4px;
        }
        .user-item:hover { background: var(--bg); }
        .user-item.active { background: rgba(99, 102, 241, 0.3); }
        .user-avatar {
            width: 44px; height: 44px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-weight: 700; font-size: 18px; color: white;
        }
        .user-info-list { flex: 1; }
        .user-name { font-weight: 600; font-size: 14px; }
        .user-status { font-size: 12px; color: var(--success); margin-top: 2px; }
        .chat-panel { flex: 1; display: flex; flex-direction: column; background: var(--bg); }
        .chat-title { padding: 16px 20px; background: var(--surface); border-bottom: 1px solid var(--border); font-weight: 600; }
        .messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
        .message { display: flex; flex-direction: column; max-width: 60%; }
        .message.me { align-self: flex-end; align-items: flex-end; }
        .message.other { align-self: flex-start; align-items: flex-start; }
        .message-bubble { padding: 12px 18px; border-radius: 18px; font-size: 15px; }
        .message.me .message-bubble { background: var(--message-me); border-bottom-right-radius: 4px; }
        .message.other .message-bubble { background: var(--message-other); border-bottom-left-radius: 4px; }
        .message-time { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
        .chat-input-area {
            padding: 16px 20px; background: var(--surface); border-top: 1px solid var(--border);
            display: flex; gap: 12px;
        }
        .chat-input {
            flex: 1; padding: 14px 20px; border: 2px solid var(--border); border-radius: 24px;
            font-size: 15px; background: var(--bg); color: var(--text);
        }
        .chat-input:focus { outline: none; border-color: var(--primary); }
        .send-btn {
            width: 50px; height: 50px; border-radius: 50%; background: var(--primary); color: white;
            border: none; cursor: pointer; font-size: 20px; display: flex; align-items: center; justify-content: center;
        }
        .send-btn:disabled { background: var(--border); cursor: not-allowed; }
        .icon-btn { padding: 8px; background: none; border: none; cursor: pointer; font-size: 24px; color: var(--text-secondary); transition: 0.2s; }
        .icon-btn:hover { color: var(--primary); transform: scale(1.1); }
        .file-preview { display: flex; align-items: center; gap: 10px; background: rgba(99, 102, 241, 0.2); padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; max-width: 300px; }
        .file-preview-name { font-size: 13px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
        .file-preview-remove { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 18px; padding: 0 4px; }
        .file-preview-remove:hover { color: var(--error); }
        .chat-img { max-width: 100%; border-radius: 12px; margin-top: 5px; cursor: pointer; display: block; }
        .file-attachment { display: flex; align-items: center; gap: 10px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 12px; margin-top: 5px; text-decoration: none; color: white; border: 1px solid var(--border); }
        .empty-state { text-align: center; padding: 80px 20px; color: var(--text-secondary); margin: auto; }
        .empty-state .icon { font-size: 64px; margin-bottom: 16px; opacity: 0.5; }
    </style>
</head>
<body>
    <div class="container">
        <div id="loginPage" class="login-page">
            <div class="login-card">
                <div class="login-icon">💬</div>
                <h1 class="login-title">Мессенджер Jetesk</h1>
                <p class="login-subtitle" id="loginSubtitle">Введите имя для входа</p>
                <div id="loginForm" class="form-section active">
                    <div class="input-group">
                        <label>Ваше имя</label>
                        <input type="text" id="loginUsername" placeholder="Как вас называть?" maxlength="20">
                    </div>
                    <div class="input-group">
                        <label>Пароль</label>
                        <input type="password" id="loginPassword" placeholder="Введите пароль" maxlength="50">
                    </div>
                    <button class="btn" onclick="login()">Войти</button>
                    <div id="loginError" class="error-msg"></div>
                    <span class="toggle-link" onclick="showRegister()">Нет аккаунта? Зарегистрироваться</span>
                </div>
                <div id="registerForm" class="form-section">
                    <div class="input-group">
                        <label>Придумайте имя</label>
                        <input type="text" id="regUsername" placeholder="Ваше имя" maxlength="20">
                    </div>
                    <div class="input-group">
                        <label>Пароль</label>
                        <input type="password" id="regPassword" placeholder="Минимум 6 символов" maxlength="50">
                    </div>
                    <div class="input-group">
                        <label>Подтвердите пароль</label>
                        <input type="password" id="regPasswordConfirm" placeholder="Повторите пароль" maxlength="50">
                    </div>
                    <button class="btn" onclick="register()">Зарегистрироваться</button>
                    <div id="registerError" class="error-msg"></div>
                    <span class="toggle-link" onclick="showLogin()">Уже есть аккаунт? Войти</span>
                </div>
            </div>
        </div>
        <div id="chatPage" class="chat-page" style="display: none;">
            <header class="header">
                <div class="header-left">
                    <div class="avatar" id="userAvatar">A</div>
                    <div class="user-info">
                        <h2 id="headerUsername">User</h2>
                        <span>Онлайн</span>
                    </div>
                </div>
                <button class="logout-btn" onclick="logout()">Выход</button>
            </header>
            <div class="chat-body">
                <aside class="users-panel">
                    <div class="users-header">Пользователи (<span id="usersCount">0</span>)</div>
                    <div class="users-list" id="usersList"></div>
                </aside>
                <main class="chat-panel">
                    <div class="chat-title" id="chatTitle">Общий чат</div>
                    <div class="messages" id="messagesContainer">
                        <div class="empty-state"><div class="icon">💭</div><div>Начните общение!</div></div>
                    </div>
                    <div id="filePreviewContainer" style="display:none; padding: 0 20px;"></div>
                    <div class="chat-input-area">
                        <input type="file" id="fileInput" accept="image/*,*/*" style="display:none;" onchange="handleFileSelect(event)">
                        <button class="icon-btn" onclick="document.getElementById('fileInput').click()" title="Прикрепить файл">📎</button>
                        <input type="text" class="chat-input" id="messageInput" placeholder="Введите сообщение..." onkeypress="if(event.key==='Enter')sendMessage()">
                        <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>➤</button>
                    </div>
                </main>
            </div>
        </div>
    </div>
    <script>
        let currentUser = null;
        let users = [];
        let messages = [];
        let selectedUserId = 0;
        let selectedUsername = 'General Chat';
        let refreshInterval = null;
        let selectedFile = null;
        let selectedFileData = null;
        let selectedFileType = null;

        function init() {
            fetch('/api/me')
                .then(r => r.json())
                .then(user => {
                    if (user) {
                        currentUser = user;
                        showChat();
                    }
                });
        }

        function showLogin() {
            document.getElementById('loginForm').classList.add('active');
            document.getElementById('registerForm').classList.remove('active');
            document.getElementById('loginSubtitle').textContent = 'Enter login details';
            document.getElementById('loginError').textContent = '';
        }

        function showRegister() {
            document.getElementById('loginForm').classList.remove('active');
            document.getElementById('registerForm').classList.add('active');
            document.getElementById('loginSubtitle').textContent = 'Create account';
            document.getElementById('registerError').textContent = '';
        }

        function register() {
            const username = document.getElementById('regUsername').value.trim();
            const password = document.getElementById('regPassword').value;
            const passwordConfirm = document.getElementById('regPasswordConfirm').value;
            const errorEl = document.getElementById('registerError');

            if (!username) { errorEl.textContent = 'Enter username'; return; }
            if (username.length < 2) { errorEl.textContent = 'Username must be at least 2 characters'; return; }
            if (!password) { errorEl.textContent = 'Enter password'; return; }
            if (password.length < 6) { errorEl.textContent = 'Password must be at least 6 characters'; return; }
            if (password !== passwordConfirm) { errorEl.textContent = 'Passwords do not match'; return; }

            fetch('/api/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            })
            .then(r => r.json())
            .then(result => {
                if (result.success) {
                    currentUser = result.user;
                    showChat();
                } else {
                    errorEl.textContent = result.message;
                }
            });
        }

        function login() {
            const username = document.getElementById('loginUsername').value.trim();
            const password = document.getElementById('loginPassword').value;
            const errorEl = document.getElementById('loginError');

            if (!username) { errorEl.textContent = 'Enter username'; return; }
            if (!password) { errorEl.textContent = 'Enter password'; return; }

            fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            })
            .then(r => r.json())
            .then(result => {
                if (result.success) {
                    currentUser = result.user;
                    showChat();
                } else {
                    errorEl.textContent = result.message;
                }
            });
        }

        function logout() {
            fetch('/api/logout').then(() => { location.reload(); });
        }

        function showChat() {
            document.getElementById('loginPage').style.display = 'none';
            document.getElementById('chatPage').style.display = 'flex';
            document.getElementById('headerUsername').textContent = currentUser.username;
            document.getElementById('userAvatar').textContent = currentUser.username.charAt(0).toUpperCase();
            loadUsers();
            loadMessages();
            refreshInterval = setInterval(() => { loadUsers(); loadMessages(); }, 3000);
        }

        function loadUsers() {
            fetch('/api/users')
                .then(r => r.json())
                .then(data => {
                    users = data;
                    document.getElementById('usersCount').textContent = users.length;
                    renderUsers();
                });
        }

        function renderUsers() {
            const container = document.getElementById('usersList');
            let html = '<div class="user-item ' + (selectedUserId === 0 ? 'active' : '') + '" onclick="selectUser(0, \'General Chat\')">' +
                '<div class="user-avatar" style="background: #6366f1;">&#128172;</div>' +
                '<div class="user-info-list"><div class="user-name">General Chat</div><div class="user-status">All users</div></div></div>';
            users.forEach(user => {
                html += '<div class="user-item ' + (selectedUserId === user.id ? 'active' : '') + '" ' +
                    'onclick="selectUser(' + user.id + ', \'' + user.username + '\')">' +
                    '<div class="user-avatar" style="background: #' + user.avatar_color + ';">' + user.username.charAt(0).toUpperCase() + '</div>' +
                    '<div class="user-info-list"><div class="user-name">' + escapeHtml(user.username) + '</div>' +
                    '<div class="user-status">Online</div></div></div>';
            });
            container.innerHTML = html;
        }

        function selectUser(userId, username) {
            selectedUserId = userId;
            selectedUsername = username;
            document.getElementById('chatTitle').textContent = username;
            renderUsers();
            loadMessages();
        }

        function loadMessages() {
            const url = selectedUserId === 0 ? '/api/messages' : '/api/messages/' + selectedUserId;
            fetch(url).then(r => r.json()).then(data => {
                messages = data;
                renderMessages();
            });
        }

        function renderMessages() {
            const container = document.getElementById('messagesContainer');
            if (messages.length === 0) {
                container.innerHTML = '<div class="empty-state"><div class="icon">&#128172;</div><div>Начните общение!</div></div>';
                return;
            }
            let html = '';
            messages.forEach(msg => {
                let bubbleContent = '';
                if (msg.file_type === 'image') {
                    bubbleContent = '<img src="' + msg.content + '" class="chat-img" onclick="window.open(this.src)">';
                } else if (msg.file_type === 'file') {
                    bubbleContent = '<a href="' + msg.content + '" download class="file-attachment">📄 Файл</a>';
                } else {
                    bubbleContent = escapeHtml(msg.content);
                }
                html += '<div class="message ' + (msg.is_mine ? 'me' : 'other') + '">' +
                    '<div class="message-bubble">' + bubbleContent + '</div>' +
                    '<div class="message-time">' + escapeHtml(msg.sender) + ' &bull; ' + msg.created_at + '</div></div>';
            });
            container.innerHTML = html;
            container.scrollTop = container.scrollHeight;
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const content = input.value.trim();
            
            // Если есть файл - отправляем его
            if (selectedFileData) {
                const formData = new FormData();
                formData.append('file_data', selectedFileData);
                formData.append('file_type', selectedFileType);
                formData.append('recipient_id', selectedUserId === 0 ? null : selectedUserId);
                
                fetch('/api/send-file', {
                    method: 'POST',
                    body: formData
                })
                .then(r => {
                    console.log('File upload status:', r.status);
                    // Проверяем что это JSON
                    const contentType = r.headers.get('content-type');
                    if (!contentType || !contentType.includes('application/json')) {
                        throw new Error('Сервер вернул HTML вместо JSON. Код: ' + r.status);
                    }
                    return r.json();
                })
                .then(result => {
                    if (result.success) {
                        clearFilePreview();
                        loadMessages();
                    } else {
                        alert('Ошибка загрузки файла: ' + result.message);
                    }
                })
                .catch(err => {
                    console.error('Upload error:', err);
                    alert('Ошибка сети: ' + err.message);
                });
                return;
            }
            
            // Отправка текста
            if (!content) return;
            
            fetch('/api/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    recipient_id: selectedUserId === 0 ? null : selectedUserId,
                    content
                })
            })
            .then(r => {
                const contentType = r.headers.get('content-type');
                if (!contentType || !contentType.includes('application/json')) {
                    throw new Error('Сервер вернул HTML. Код: ' + r.status);
                }
                return r.json();
            })
            .then(result => {
                if (result.success) {
                    input.value = '';
                    document.getElementById('sendBtn').disabled = true;
                    loadMessages();
                } else {
                    alert('Ошибка: ' + result.message);
                }
            })
            .catch(err => {
                console.error('Send error:', err);
                alert('Ошибка отправки: ' + err.message);
            });
        }
        
        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            selectedFile = file;
            selectedFileType = file.type.startsWith('image/') ? 'image' : 'file';
            
            const reader = new FileReader();
            reader.onload = function(e) {
                selectedFileData = e.target.result;
                showFilePreview(file.name, selectedFileType);
            };
            reader.readAsDataURL(file);
        }
        
        function showFilePreview(fileName, fileType) {
            const container = document.getElementById('filePreviewContainer');
            const icon = fileType === 'image' ? '🖼️' : '📄';
            
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

        function escapeHtml(text) {
            if (!text) return '';
            return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        document.getElementById('messageInput').addEventListener('input', function() {
            document.getElementById('sendBtn').disabled = !this.value.trim();
        });

        init();
    </script>
</body>
</html>'''


# ==================== МАРШРУТЫ ====================
@app.route('/')
def index():
    user = get_current_user()
    if user:
        return redirect('/chat')
    return render_template_string(HTML_TEMPLATE)


@app.route('/chat')
def chat():
    user = get_current_user()
    if not user:
        return redirect('/')
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/me')
def api_me():
    user = get_current_user()
    if user:
        return jsonify({'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color or '6366f1'})
    return jsonify(None)


@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Введите имя (минимум 2 символа)'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        existing = db.query(User).filter_by(username=username).first()
        if existing:
            return jsonify({'success': False, 'message': 'Пользователь с таким именем уже существует'})

        password_hash = generate_password_hash(password)
        user = User(username=username, password_hash=password_hash, avatar_color=generate_avatar_color())
        db.add(user)
        db.commit()

        response = make_response(jsonify({
            'success': True,
            'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color or '6366f1'}
        }))
        response.set_cookie('username', username, max_age=60*60*24*30, httponly=False, samesite='lax')
        return response
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Введите имя (минимум 2 символа)'})
    if not password:
        return jsonify({'success': False, 'message': 'Введите пароль'})

    db = get_db()
    try:
        user = db.query(User).filter_by(username=username).first()
        if not user:
            return jsonify({'success': False, 'message': 'Пользователь не найден'})
        if not user.password_hash:
            return jsonify({'success': False, 'message': 'Для этого аккаунта требуется сброс пароля'})
        if not check_password_hash(user.password_hash, password):
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        response = make_response(jsonify({
            'success': True,
            'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color or '6366f1'}
        }))
        response.set_cookie('username', username, max_age=60*60*24*30, httponly=False, samesite='lax')
        return response
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()


@app.route('/api/users')
def api_users():
    user = get_current_user()
    if not user:
        return jsonify([])
    
    db = get_db()
    try:
        users = db.query(User).filter(User.id != user.id).all()
        return jsonify([{
            'id': u.id, 'username': u.username, 'avatar_color': u.avatar_color or '6366f1'
        } for u in users])
    finally:
        db.close()


@app.route('/api/messages')
@app.route('/api/messages/<int:recipient_id>')
def api_messages(recipient_id=None):
    user = get_current_user()
    if not user:
        return jsonify([])
    
    db = get_db()
    try:
        if recipient_id:
            messages = db.query(Message).filter(
                ((Message.sender_id == user.id) & (Message.recipient_id == recipient_id)) |
                ((Message.sender_id == recipient_id) & (Message.recipient_id == user.id))
            ).order_by(Message.created_at.asc()).all()
        else:
            messages = db.query(Message).filter(Message.recipient_id.is_(None)).order_by(Message.created_at.asc()).all()
        
        result = []
        for m in messages:
            sender = db.query(User).filter_by(id=m.sender_id).first()
            result.append({
                'id': m.id,
                'sender': sender.username if sender else 'Unknown',
                'content': m.content,
                'file_type': m.file_type,
                'created_at': m.created_at.strftime('%H:%M'),
                'is_mine': m.sender_id == user.id
            })
        return jsonify(result)
    except Exception as e:
        return jsonify([])
    finally:
        db.close()


@app.route('/api/send', methods=['POST'])
def api_send():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Не авторизован'})

    data = request.json
    content = data.get('content', '').strip()
    recipient_id = data.get('recipient_id')

    if not content:
        return jsonify({'success': False, 'message': 'Пустое сообщение'})
    if len(content) > 1000:
        return jsonify({'success': False, 'message': 'Сообщение слишком длинное'})

    db = get_db()
    try:
        message = Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content)
        db.add(message)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()


@app.route('/api/send-file', methods=['POST'])
def api_send_file():
    """Обработка загрузки файлов с поддержкой Vercel"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': 'Не авторизован'}), 401

        # Поддержка разных способов получения данных (для Vercel)
        file_data = request.form.get('file_data') or request.values.get('file_data')
        file_type = request.form.get('file_type') or request.values.get('file_type', 'file')
        recipient_id = request.form.get('recipient_id') or request.values.get('recipient_id')

        if not file_data:
            return jsonify({'success': False, 'message': 'Нет данных файла'}), 400

        # Проверка размера (base64 строка ~1.3x от оригинала)
        if len(file_data) > 10 * 1024 * 1024:  # 10MB
            return jsonify({'success': False, 'message': 'Файл слишком большой (макс. 10MB)'}), 413

        db = get_db()
        try:
            message = Message(
                sender_id=user.id,
                recipient_id=recipient_id if recipient_id else None,
                content=file_data,
                file_type=file_type
            )
            db.add(message)
            db.commit()
            print(f"[OK] Файл загружен: type={file_type}, size={len(file_data)} bytes")
            return jsonify({'success': True})
        except Exception as e:
            db.rollback()
            print(f"[ERROR] DB error: {e}")
            return jsonify({'success': False, 'message': f'Ошибка БД: {str(e)}'}), 500
        finally:
            db.close()
            
    except Exception as e:
        print(f"[ERROR] Upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Ошибка загрузки: {str(e)}'}), 500


@app.route('/api/logout')
def api_logout():
    response = make_response(jsonify({'success': True}))
    response.delete_cookie('username')
    return response


# ==================== ОБРАБОТЧИКИ ОШИБОК ====================
@app.errorhandler(413)
def request_entity_too_large(error):
    """Обработка ошибки слишком большого файла"""
    return jsonify({'success': False, 'message': 'Файл слишком большой. Максимум 10MB'}), 413


@app.errorhandler(500)
def internal_server_error(error):
    """Обработка внутренних ошибок сервера"""
    print(f"[ERROR] 500: {error}")
    return jsonify({'success': False, 'message': 'Внутренняя ошибка сервера'}), 500


@app.errorhandler(404)
def not_found(error):
    """Обработка ошибки 404"""
    return jsonify({'success': False, 'message': 'Не найдено'}), 404


# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    print("Инициализация базы данных...")
    init_db()
    print("База данных готова!\n")
    print("=" * 60)
    print("  МЕССЕНДЖЕР Jetesk ЗАПУЩЕН!")
    print("=" * 60)
    print(f"\n  ОТКРОЙТЕ: http://localhost:{PORT}\n")
    app.run(host=HOST, port=PORT, debug=False)
