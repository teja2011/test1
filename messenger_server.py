from flask import Flask, render_template_string, request, jsonify, redirect, make_response, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import secrets
import os
import uuid
import threading
import time
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import smtplib
from dotenv import load_dotenv
import sqlite3

# Загружаем .env только локально (не на Vercel)
if not os.environ.get('VERCEL'):
    load_dotenv()

def to_msk(dt):
    """Конвертирует datetime в MSK (UTC+3)"""
    if dt is None:
        return None
    return dt + timedelta(hours=3)

def utc_now():
    """Возвращает текущее время в UTC"""
    return datetime.utcnow()

KEEPALIVE_INTERVAL = int(os.environ.get('KEEPALIVE_INTERVAL', 300))
KEEPALIVE_URL = os.environ.get('KEEPALIVE_URL', '')

def keepalive_worker():
    """Фоновый поток для отправки keep-alive запросов"""
    if not KEEPALIVE_URL:
        return
    while True:
        try:
            requests.get(KEEPALIVE_URL, timeout=10)
            print(f"[Keep-Alive] Ping sent to {KEEPALIVE_URL}")
        except Exception as e:
            print(f"[Keep-Alive] Error: {e}")
        time.sleep(KEEPALIVE_INTERVAL)

if KEEPALIVE_URL:
    keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
    keepalive_thread.start()
    print(f"[Keep-Alive] Started with interval {KEEPALIVE_INTERVAL}s")

def get_db_connection():
    """Получить подключение к базе данных"""
    # Используем SQLite для разработки и production
    return sqlite3.connect('messenger.db', check_same_thread=False)

# Cloudinary настройка (для хостинга изображений)
CLOUDINARY_CONFIGURED = False
try:
    import cloudinary  # type: ignore
    import cloudinary.uploader  # type: ignore
    cloudinary.config(  # type: ignore
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET')
    )
    CLOUDINARY_CONFIGURED = True
    print("[Cloudinary] Configured successfully")
except ImportError:
    print("[Cloudinary] Not installed (pip install cloudinary)")
except Exception as e:
    print(f"[Cloudinary] Not configured: {e}")

SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)

# Флаг для отслеживания инициализации БД
_db_initialized = False

def check_and_create_tables():
    """Проверить существование таблиц и создать их если нет"""
    conn = get_db_connection()
    try:
        print("Проверка и создание таблиц...")
        # Создаём таблицу users
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                avatar_color TEXT DEFAULT '6366f1',
                avatar_url TEXT,
                jt_username TEXT UNIQUE,
                last_seen DATETIME
            )
        """)
        # Создаём таблицу messages
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                file_type TEXT,
                status TEXT DEFAULT 'sent'
            )
        """)
        # Создаём таблицу notifications
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sender_id INTEGER,
                message TEXT NOT NULL,
                type TEXT DEFAULT 'message',
                is_read INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        print("Таблицы проверены/созданы: users, messages, notifications")
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")
        raise
    finally:
        conn.close()

def init_db():
    check_and_create_tables()
    print("Database initialized with tables: users, messages, notifications")

def reset_db():
    """Сбросить базу данных (удалить все таблицы и создать заново)"""
    conn = get_db_connection()
    try:
        conn.execute("DROP TABLE IF EXISTS notifications")
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("DROP TABLE IF EXISTS users")
        conn.commit()
        print("Старые таблицы удалены")
    except Exception as e:
        print(f"Ошибка при удалении таблиц: {e}")
    finally:
        conn.close()
    check_and_create_tables()
    print("База данных сброшена, таблицы созданы: users, messages, notifications")

def get_db():
    """Получить подключение к базе данных"""
    return get_db_connection()

def init_tables():
    """Принудительно создать все таблицы"""
    try:
        print("=== Проверка таблиц БД ===")
        conn = get_db_connection()
        # Создаём таблицы
        check_and_create_tables()
        # Проверяем что таблицы созданы
        result = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'messages', 'notifications')")
        tables = [row[0] for row in result.fetchall()]
        print(f"Созданы таблицы: {', '.join(tables)}")
        conn.close()

        if len(tables) < 3:
            raise Exception(f"Не все таблицы созданы! Найдено: {len(tables)}, ожидается: 3")

        print("=== БД готова к работе ===")
        return True
    except Exception as e:
        print(f"❌ ОШИБКА создания таблиц: {e}")
        print(f"DATABASE_URL: SQLite (messenger.db)")
        return False

# Инициализируем таблицы при загрузке
_tables_initialized = False
if not init_tables():
    print("ВНИМАНИЕ: Сервер запущен с ошибками БД. Проверьте подключение!")
else:
    _tables_initialized = True

@app.before_request
def before_request():
    """Гарантировать что таблицы существуют перед каждым запросом (для serverless)"""
    if not _tables_initialized:
        init_tables()

def create_notification(db, user_id, message, sender_id=None, notif_type='message'):
    """Создаёт уведомление для пользователя"""
    try:
        db.execute("""
            INSERT INTO notifications (user_id, sender_id, message, type, is_read, created_at)
            VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        """, (user_id, sender_id, message, notif_type))
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error creating notification: {e}")
        return None

def get_current_user():
    user_id = request.cookies.get('user_id')
    if not user_id:
        return None
    db = get_db()
    try:
        cursor = db.execute("SELECT * FROM users WHERE id = ?", (int(user_id),))
        row = cursor.fetchone()
        db.close()
        if row:
            return {
                'id': row[0],
                'username': row[1],
                'password_hash': row[2],
                'created_at': row[3],
                'avatar_color': row[4],
                'avatar_url': row[5],
                'jt_username': row[6],
                'last_seen': row[7]
            }
        return None
    except Exception as e:
        db.close()
        print(f"Error getting current user: {e}")
        return None

def generate_avatar_color():
    import random
    return random.choice(['6366f1', '10b981', 'f59e0b', 'ef4444', '8b5cf6', 'ec4899', '0891b2', '7c3aed'])

# Получаем директорию текущего файла для корректной работы на Vercel
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_TEMPLATE_PATH = os.path.join(CURRENT_DIR, 'index.html')
HTML_TEMPLATE = open(HTML_TEMPLATE_PATH, 'r', encoding='utf-8').read() if os.path.exists(HTML_TEMPLATE_PATH) else '<h1>index.html not found</h1>'

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
        print(f"[API /me] User: id={user['id']}, username={user['username']}, avatar_url={user['avatar_url']}, jt_username={user['jt_username']}")
        return jsonify({'id': user['id'], 'username': user['username'], 'avatar_color': user['avatar_color'] or '6366f1', 'avatar_url': user['avatar_url'], 'jt_username': user['jt_username']})
    print(f"[API /me] No user (cookie: {request.cookies.get('user_id')})")
    return jsonify(None)

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    print(f"=== РЕГИСТРАЦИЯ ===")
    print(f"Username: {username}")
    print(f"Password получен: {'да' if password else 'нет'}")
    print(f"Длина пароля: {len(password) if password else 0}")

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            db.close()
            return jsonify({'success': False, 'message': 'Имя уже занято'})

        password_hash = generate_password_hash(password)
        avatar_color = generate_avatar_color()
        
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, avatar_color, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (username, password_hash, avatar_color)
        )
        db.commit()
        user_id = cursor.lastrowid
        db.close()

        response = jsonify({'success': True})
        response.set_cookie('user_id', str(user_id), max_age=60*60*24*365, httponly=True)
        return response
    except Exception as e:
        db.close()
        print(f"Error registering user: {e}")
        return jsonify({'success': False, 'message': 'Ошибка регистрации'})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    print(f"=== ВХОД ===")
    print(f"Username: {username}")
    print(f"Password получен: {'да' if password else 'нет'}")

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        cursor = db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()

        if not row:
            print(f"Пользователь '{username}' не найден")
            db.close()
            return jsonify({'success': False, 'message': 'Пользователь не найден'})

        user = {
            'id': row[0],
            'username': row[1],
            'password_hash': row[2],
            'created_at': row[3],
            'avatar_color': row[4],
            'avatar_url': row[5],
            'jt_username': row[6],
            'last_seen': row[7]
        }

        print(f"Пользователь найден: id={user['id']}")
        print(f"password_hash в БД: {user['password_hash'][:50] if user['password_hash'] else 'NULL'}...")

        if not user['password_hash']:
            print("password_hash пуст!")
            db.close()
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        is_valid = check_password_hash(user['password_hash'], password)
        print(f"Проверка пароля: {'OK' if is_valid else 'FAIL'}")

        if not is_valid:
            db.close()
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        print(f"Вход успешен: {username}")

        # Обновляем last_seen при входе
        db.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
        db.commit()
        db.close()

        resp = make_response(jsonify({'success': True, 'user': {
            'id': user['id'],
            'username': user['username'],
            'avatar_color': user['avatar_color'] or '6366f1',
            'avatar_url': user['avatar_url'],
            'jt_username': user['jt_username'],
            'last_seen': user['last_seen'].isoformat() if user['last_seen'] else None
        }}))
        resp.set_cookie('user_id', str(user['id']), max_age=60*60*24*30, samesite='lax')
        resp.delete_cookie('username')  # Удаляем старый cookie
        return resp
    except Exception as e:
        db.close()
        print(f"Ошибка входа: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/users')
def api_users():
    user = get_current_user()
    if not user:
        return jsonify([])
    db = get_db()
    try:
        cursor = db.execute("SELECT * FROM users WHERE id != ?", (user['id'],))
        rows = cursor.fetchall()
        result = []
        for row in rows:
            u = {
                'id': row[0],
                'username': row[1],
                'password_hash': row[2],
                'created_at': row[3],
                'avatar_color': row[4],
                'avatar_url': row[5],
                'jt_username': row[6],
                'last_seen': row[7]
            }
            # Определяем онлайн (heartbeat каждые 3 сек, считаем онлайн если < 10 сек)
            is_online = False
            last_seen_str = None
            if u['last_seen']:
                # Парсим last_seen если это строка
                last_seen_dt = u['last_seen']
                if isinstance(last_seen_dt, str):
                    try:
                        last_seen_dt = datetime.fromisoformat(last_seen_dt.replace(' ', 'T'))
                    except:
                        last_seen_dt = None
                if last_seen_dt:
                    time_diff = utc_now() - last_seen_dt
                    is_online = time_diff.total_seconds() < 10
                    last_seen_msk = to_msk(last_seen_dt)
                    last_seen_str = last_seen_msk.strftime('%d.%m %H:%M') if last_seen_msk else ''

            # Считаем непрочитанные сообщения от этого пользователя
            cursor = db.execute("""
                SELECT COUNT(*) FROM messages
                WHERE sender_id = ? AND recipient_id = ? AND status != 'read'
            """, (u['id'], user['id']))
            unread_count = cursor.fetchone()[0]

            result.append({
                'id': u['id'],
                'username': u['username'],
                'avatar_color': u['avatar_color'] or '6366f1',
                'avatar_url': u['avatar_url'],
                'jt_username': u['jt_username'],
                'is_online': is_online,
                'last_seen': last_seen_str,
                'unread_count': unread_count
            })
        return jsonify(result)
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
            cursor = db.execute("""
                SELECT * FROM messages 
                WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)
                ORDER BY created_at ASC
            """, (user['id'], recipient_id, recipient_id, user['id']))
        else:
            cursor = db.execute("""
                SELECT * FROM messages 
                WHERE recipient_id IS NULL
                ORDER BY created_at ASC
            """)
        rows = cursor.fetchall()
        result = []
        for row in rows:
            m = {
                'id': row[0],
                'sender_id': row[1],
                'recipient_id': row[2],
                'content': row[3],
                'created_at': row[4],
                'file_type': row[5],
                'status': row[6]
            }
            # Получаем имя отправителя
            cursor = db.execute("SELECT username FROM users WHERE id = ?", (m['sender_id'],))
            sender_row = cursor.fetchone()
            sender = sender_row[0] if sender_row else 'Unknown'
            # Получаем статус
            msg_status = m['status'] or 'sent'
            result.append({
                'id': m['id'],
                'sender': sender,
                'content': m['content'],
                'created_at': to_msk(m['created_at']).strftime('%H:%M') if m['created_at'] and to_msk(m['created_at']) else '',
                'is_mine': m['sender_id'] == user['id'],
                'file_type': m['file_type'],
                'status': msg_status
            })
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/send', methods=['POST'])
def api_send():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    data = request.json
    content = data.get('content', '').strip()
    recipient_id = data.get('recipient_id')
    if not content:
        return jsonify({'success': False, 'message': 'Empty message'})
    db = get_db()
    try:
        db.execute("""
            INSERT INTO messages (sender_id, recipient_id, content, file_type, status, created_at)
            VALUES (?, ?, ?, NULL, 'sent', CURRENT_TIMESTAMP)
        """, (user['id'], recipient_id if recipient_id else None, content))
        db.commit()
        cursor = db.execute("SELECT last_insert_rowid()")
        msg_id = cursor.fetchone()[0]

        # Отправляем уведомление получателю
        if recipient_id:
            cursor = db.execute("SELECT username FROM users WHERE id = ?", (recipient_id,))
            recipient_row = cursor.fetchone()
            recipient = recipient_row[0] if recipient_row else None
            if recipient:
                create_notification(
                    db=db,
                    user_id=recipient_id,
                    message=f"Новое сообщение от {user['username']}: {content[:50]}{'...' if len(content) > 50 else ''}",
                    sender_id=user['id'],
                    notif_type='message'
                )

        return jsonify({'success': True, 'id': msg_id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        print(f"Ошибка отправки: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/send-file', methods=['POST'])
def api_send_file():
    """Отправка файла (изображения или другого файла)"""
    print(f"[send-file] Tables initialized: {_tables_initialized}")

    user = get_current_user()
    if not user:
        print(f"[send-file] Not authorized")
        return jsonify({'success': False, 'message': 'Not authorized'})

    recipient_id = request.form.get('recipient_id')
    file_data = request.form.get('file_data')  # Base64 данные
    file_type = request.form.get('file_type')  # 'image' или 'file'

    print(f"[send-file] User: {user['id']}, file_type: {file_type}, recipient: {recipient_id}")
    print(f"[send-file] File data length: {len(file_data) if file_data else 0}")

    if not file_data:
        print(f"[send-file] No file data in request")
        return jsonify({'success': False, 'message': 'No file data'})

    # Проверяем размер данных (макс 10MB base64)
    if len(file_data) > 10 * 1024 * 1024:
        print(f"[send-file] File too large: {len(file_data)} bytes")
        return jsonify({'success': False, 'message': 'File too large (max 10MB)'})

    db = get_db()
    try:
        # Проверяем, что данные начинаются с data: URL
        if not file_data.startswith('data:'):
            print(f"[send-file] Invalid data URL format")
            return jsonify({'success': False, 'message': 'Invalid file format'})

        # Вставляем сообщение
        cursor = db.execute("""
            INSERT INTO messages (sender_id, recipient_id, content, file_type, status, created_at)
            VALUES (?, ?, ?, ?, 'sent', CURRENT_TIMESTAMP)
        """, (user['id'], recipient_id if recipient_id else None, file_data, file_type))
        db.commit()
        msg_id = cursor.lastrowid
        print(f"[send-file] Message saved with id: {msg_id}")

        # Отправляем уведомление получателю
        if recipient_id:
            try:
                cursor = db.execute("SELECT username FROM users WHERE id = ?", (int(recipient_id),))
                recipient_row = cursor.fetchone()
                if recipient_row:
                    create_notification(
                        db=db,
                        user_id=int(recipient_id),
                        message=f"Новое фото от {user['username']}",
                        sender_id=user['id'],
                        notif_type='message'
                    )
                    print(f"[send-file] Notification sent to user {recipient_id}")
            except Exception as notif_err:
                print(f"[send-file] Error sending notification: {notif_err}")

        return jsonify({'success': True, 'id': msg_id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        print(f"[send-file] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/logout')
def api_logout():
    """Выход пользователя из аккаунта"""
    user_id = request.cookies.get('user_id')
    if user_id:
        # Обновляем last_seen при выходе
        db = get_db()
        try:
            db.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (int(user_id),))
            db.commit()
            print(f"[Logout] User {user_id} logged out, last_seen updated")
        except Exception as e:
            db.rollback()
            print(f"[Logout] Error updating last_seen: {e}")
        finally:
            db.close()

    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('user_id')
    resp.delete_cookie('username')  # На всякий случай
    return resp

@app.route('/api/keepalive')
def api_keepalive():
    """Keep-Alive эндпоинт для предотвращения засыпания сервера"""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/api/settings/clear-messages', methods=['POST'])
def api_clear_messages():
    """Удаляет все сообщения, отправленные текущим пользователем"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        db.execute("DELETE FROM messages WHERE sender_id = ?", (user['id'],))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/settings/delete-account', methods=['POST'])
def api_delete_account():
    """Удаляет аккаунт текущего пользователя и все его сообщения"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        # Удаляем все сообщения пользователя (как отправленные, так и полученные)
        db.execute("DELETE FROM messages WHERE sender_id = ? OR recipient_id = ?", (user['id'], user['id']))
        # Удаляем пользователя
        db.execute("DELETE FROM users WHERE id = ?", (user['id'],))
        db.commit()
        resp = make_response(jsonify({'success': True}))
        resp.delete_cookie('user_id')
        resp.delete_cookie('username')  # На всякий
        return resp
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/notifications')
def api_notifications():
    """Получение списка уведомлений текущего пользователя"""
    user = get_current_user()
    if not user:
        return jsonify([])
    db = get_db()
    try:
        cursor = db.execute("""
            SELECT id, sender_id, message, type, is_read, created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (user['id'],))
        notifications = cursor.fetchall()
        result = []
        for n in notifications:
            sender = None
            if n[1]:  # sender_id
                sender_cursor = db.execute("SELECT id, username, avatar_color FROM users WHERE id = ?", (n[1],))
                sender_row = sender_cursor.fetchone()
                if sender_row:
                    sender = {'id': sender_row[0], 'username': sender_row[1], 'avatar_color': sender_row[2]}
            result.append({
                'id': n[0],
                'message': n[2],
                'type': n[3],
                'is_read': bool(n[4]),
                'created_at': to_msk(n[5]).strftime('%H:%M') if n[5] and to_msk(n[5]) else '',
                'sender': sender
            })
        return jsonify(result)
    except Exception as e:
        print(f"Error loading notifications: {e}")
        return jsonify([])
    finally:
        db.close()

@app.route('/api/notifications/unread')
def api_notifications_unread():
    """Получение количества непрочитанных уведомлений"""
    user = get_current_user()
    if not user:
        return jsonify({'count': 0})
    db = get_db()
    try:
        cursor = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user['id'],))
        count = cursor.fetchone()[0]
        return jsonify({'count': count})
    finally:
        db.close()

@app.route('/api/notifications/mark-read', methods=['POST'])
def api_notifications_mark_read():
    """Отметить все уведомления как прочитанные"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user['id'],))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/notifications/<int:notification_id>/mark-read', methods=['POST'])
def api_notifications_mark_single_read(notification_id):
    """Отметить конкретное уведомление как прочитанное"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        cursor = db.execute("SELECT id FROM notifications WHERE id = ? AND user_id = ?", (notification_id, user['id']))
        notification = cursor.fetchone()
        if not notification:
            return jsonify({'success': False, 'message': 'Notification not found'})
        db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/settings/change-username', methods=['POST'])
def api_change_username():
    """Сменить ник текущего пользователя"""
    user = get_current_user()
    if not user:
        print(f"❌ change-username: пользователь не найден (cookie user_id={request.cookies.get('user_id')})")
        return jsonify({'success': False, 'message': 'Not authorized'})

    print(f"✅ change-username: текущий пользователь id={user['id']}, username={user['username']}")

    data = request.json
    new_username = data.get('username', '').strip()

    print(f"📝 change-username: новый ник={new_username}")

    if not new_username or len(new_username) < 2:
        return jsonify({'success': False, 'message': 'Имя должно быть не менее 2 символов'})

    if len(new_username) > 50:
        return jsonify({'success': False, 'message': 'Имя слишком длинное'})

    db = get_db()
    try:
        # Проверяем, не занято ли имя другим пользователем
        cursor = db.execute("SELECT id FROM users WHERE username = ?", (new_username,))
        existing = cursor.fetchone()
        if existing and existing[0] != user['id']:
            print(f"⚠️ change-username: имя '{new_username}' уже занято пользователем id={existing[0]}")
            db.close()
            return jsonify({'success': False, 'message': 'Это имя уже занято'})

        # Обновляем имя в базе данных (id остаётся прежним)
        old_username = user['username']
        db.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user['id']))
        db.commit()

        print(f"✅ change-username: успешно! id={user['id']}, старый ник='{old_username}', новый ник='{new_username}'")
        db.close()

        # Возвращаем новый username и удаляем старый cookie
        resp = make_response(jsonify({'success': True, 'username': new_username, 'id': user['id']}))
        resp.delete_cookie('username')
        return resp
    except Exception as e:
        db.rollback()
        print(f"❌ change-username: ошибка базы данных: {e}")
        db.close()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/last-messages')
def api_last_messages():
    """Получение последних сообщений для каждого пользователя"""
    user = get_current_user()
    if not user:
        return jsonify([])

    db = get_db()
    try:
        # Получаем все сообщения между текущим пользователем и другими
        cursor = db.execute("""
            SELECT id, sender_id, recipient_id, content, created_at, file_type, status
            FROM messages
            WHERE (sender_id = ? AND recipient_id IS NOT NULL)
               OR (recipient_id = ? AND sender_id IS NOT NULL)
            ORDER BY created_at DESC
        """, (user['id'], user['id']))
        msgs = cursor.fetchall()

        # Группируем по собеседнику и берём последнее сообщение
        last_messages = {}
        for msg in msgs:
            partner_id = msg[2] if msg[1] == user['id'] else msg[1]  # recipient_id или sender_id
            if partner_id not in last_messages:
                last_messages[partner_id] = msg

        result = []
        for partner_id, msg in last_messages.items():
            sender_cursor = db.execute("SELECT username FROM users WHERE id = ?", (msg[1],))
            sender_row = sender_cursor.fetchone()

            # Считаем непрочитанные сообщения от этого партнера
            cursor = db.execute("""
                SELECT COUNT(*) FROM messages
                WHERE sender_id = ? AND recipient_id = ? AND status != 'read'
            """, (partner_id, user['id']))
            unread_count = cursor.fetchone()[0]

            result.append({
                'id': msg[0],
                'sender': sender_row[0] if sender_row else 'Unknown',
                'sender_id': msg[1],
                'recipient_id': msg[2],
                'content': msg[3],
                'created_at': to_msk(msg[4]).strftime('%H:%M') if msg[4] and to_msk(msg[4]) else '',
                'file_type': msg[5],
                'status': msg[6] if msg[6] else 'sent',
                'unread_count': unread_count
            })

        return jsonify(result)
    except Exception as e:
        print(f"Error loading last messages: {e}")
        return jsonify([])
    finally:
        db.close()

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """Heartbeat для проверки активности пользователя"""
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False})

    # Обновляем last_seen
    db = get_db()
    try:
        db.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (int(user_id),))
        db.commit()
        return jsonify({'success': True, 'user_id': user_id})
    except Exception as e:
        db.rollback()
        print(f"Heartbeat error: {e}")
        return jsonify({'success': False})
    finally:
        db.close()

@app.route('/api/messages/mark-read', methods=['POST'])
def api_mark_read():
    """Отметить сообщения как прочитанные"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False})

    data = request.json
    sender_id = data.get('sender_id')

    if not sender_id:
        return jsonify({'success': False, 'message': 'No sender_id'})

    db = get_db()
    try:
        # Помечаем сообщения как прочитанные (обновляем статус)
        db.execute("""
            UPDATE messages SET status = 'read'
            WHERE sender_id = ? AND recipient_id = ? AND status != 'read'
        """, (sender_id, user['id']))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"Error marking messages as read: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/username/check', methods=['POST'])
def api_username_check():
    """Проверка доступности username"""
    data = request.json
    username = data.get('username', '').strip()

    if not username:
        return jsonify({'available': False, 'message': 'Введите username'})

    db = get_db()
    try:
        cursor = db.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({'available': False, 'message': 'Это имя уже занято'})
        return jsonify({'available': True})
    except Exception as e:
        print(f"Error checking username: {e}")
        return jsonify({'available': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/username/set', methods=['POST'])
def api_username_set():
    """Установка @username для пользователя"""
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Not authorized'})

    data = request.json
    jt_username = data.get('jt_username', '').strip()

    # Удаляем @ в начале если есть
    if jt_username.startswith('@'):
        jt_username = jt_username[1:]

    db = get_db()
    try:
        cursor = db.execute("SELECT id FROM users WHERE id = ?", (int(user_id),))
        user_row = cursor.fetchone()
        if not user_row:
            return jsonify({'success': False, 'message': 'User not found'})

        if not jt_username:
            db.execute("UPDATE users SET jt_username = NULL WHERE id = ?", (int(user_id),))
            db.commit()
            return jsonify({'success': True, 'jt_username': None})

        # Проверка валидности (5-32 символа, латиница, цифры, точки, подчёркивания, нет подряд идущих точек или подчёркиваний, не заканчивается на точку или подчёркивание, не занято ли)
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]{4,31}$', jt_username):
            return jsonify({'success': False, 'message': 'Неверный формат. 5-32 символа, начинается с буквы (a-z), латиница, цифры, точки и подчёркивания'})

        if '..' in jt_username or '__' in jt_username:
            return jsonify({'success': False, 'message': 'Username не может содержать подряд идущие точки или подчёркивания'})

        if jt_username.endswith('.') or jt_username.endswith('_'):
            return jsonify({'success': False, 'message': 'Username не может заканчиваться на точку или подчёркивание'})

        cursor = db.execute("SELECT id FROM users WHERE jt_username = ? AND id != ?", (jt_username, int(user_id)))
        existing = cursor.fetchone()
        if existing:
            return jsonify({'success': False, 'message': 'Этот @username уже занят'})

        db.execute("UPDATE users SET jt_username = ? WHERE id = ?", (jt_username, int(user_id)))
        db.commit()
        return jsonify({'success': True, 'jt_username': jt_username})
    except Exception as e:
        db.rollback()
        print(f"Error setting username: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/upload-avatar', methods=['POST'])
def api_upload_avatar():
    """Загрузка аватарки пользователя"""
    print(f"[Avatar] === Upload request started ===")
    print(f"[Avatar] Cookies: {request.cookies}")
    print(f"[Avatar] user_id cookie: {request.cookies.get('user_id')}")

    # Получаем user_id из cookie
    user_id = request.cookies.get('user_id')
    if not user_id:
        print(f"[Avatar] User not authorized (user_id={request.cookies.get('user_id')})")
        return jsonify({'success': False, 'message': 'Not authorized'})

    db = get_db()
    try:
        # Получаем пользователя
        cursor = db.execute("SELECT id, username, avatar_url FROM users WHERE id = ?", (int(user_id),))
        user_row = cursor.fetchone()
        if not user_row:
            print(f"[Avatar] User not found: id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'})

        print(f"[Avatar] Upload request from user {user_row[0]} ({user_row[1]})")

        if 'avatar' not in request.files:
            print(f"[Avatar] No file in request")
            return jsonify({'success': False, 'message': 'No file provided'})

        file = request.files['avatar']
        if file.filename == '':
            print(f"[Avatar] Empty filename")
            return jsonify({'success': False, 'message': 'No file selected'})

        import io
        import uuid
        # Исправление для splitext - проверяем на None
        filename = file.filename if file.filename else ''
        ext = os.path.splitext(filename)[1].lower() if filename else ''
        print(f"[Avatar] File: {filename}, ext: {ext}")

        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            return jsonify({'success': False, 'message': 'Неверный формат. Разрешены: jpg, png, gif, webp'})

        # Читаем файл в память
        file_data = file.read()
        file_io = io.BytesIO(file_data)

        avatar_url = None

        if CLOUDINARY_CONFIGURED:
            print(f"[Avatar] Uploading to Cloudinary...")
            try:
                import cloudinary.uploader  # type: ignore
                upload_result = cloudinary.uploader.upload(  # type: ignore
                    file_io,
                    folder='avatars',
                    public_id=f"user_{user_row[0]}_{uuid.uuid4().hex[:8]}",
                    resource_type='image'
                )
                avatar_url = upload_result['secure_url']

                avatar_url = upload_result['secure_url'].replace('/upload/', '/upload/w_200,h_200,c_fill,g_face/', 1)
                print(f"[Avatar] Uploaded to Cloudinary: {avatar_url}")
            except Exception as e:
                print(f"[Avatar] Cloudinary upload error: {e}")
                return jsonify({'success': False, 'message': f'Cloudinary error: {str(e)}'})
        else:
            # Локально сохраняем в папку
            print(f"[Avatar] Saving locally...")
            filename = f"avatar_{user_row[0]}_{uuid.uuid4().hex[:8]}{ext}"

            # В serverless-среде используем /tmp, иначе - локальную папку
            if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
                upload_dir = '/tmp/avatars'
                print(f"[Avatar] Using /tmp for serverless environment")
            else:
                upload_dir = os.path.join(os.path.dirname(__file__), 'avatars')

            print(f"[Avatar] Upload dir: {upload_dir}")

            try:
                os.makedirs(upload_dir, exist_ok=True)
            except Exception as e:
                print(f"[Avatar] Error creating directory: {e}")
                return jsonify({'success': False, 'message': f'Error creating directory: {str(e)}'})

            avatar_path = os.path.join(upload_dir, filename)
            print(f"[Avatar] Saving to: {avatar_path}")

            try:
                with open(avatar_path, 'wb') as f:
                    f.write(file_data)
                print(f"[Avatar] File saved successfully")
            except Exception as e:
                print(f"[Avatar] Error saving file: {e}")
                return jsonify({'success': False, 'message': f'Error saving file: {str(e)}'})

            avatar_url = f"/avatars/{filename}"

        # Сохраняем путь в БД
        print(f"[Avatar] BEFORE UPDATE: user_id={user_row[0]}, current avatar_url={user_row[2]}")
        print(f"[Avatar] Updating database: user_id={user_row[0]}, new avatar_url={avatar_url}")
        db.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, int(user_id)))
        db.commit()
        print(f"[Avatar] Success! Avatar URL: {avatar_url}")
        return jsonify({'success': True, 'avatar_url': avatar_url})
    except Exception as e:
        db.rollback()
        print(f"[Avatar] Error saving to DB: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/avatars/<filename>')
def serve_avatar(filename):
    """Раздача аватарок"""
    import os
    if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
        avatar_dir = '/tmp/avatars'
    else:
        avatar_dir = os.path.join(os.path.dirname(__file__), 'avatars')
    return send_from_directory(avatar_dir, filename, mimetype='image')

@app.route('/Jetesk.png')
def serve_jetesk():
    """Раздача логотипа"""
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'Jetesk.png', mimetype='image/png')

@app.route('/sw.js')
def serve_sw():
    """Service Worker"""
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def serve_manifest():
    """PWA manifest"""
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'manifest.json', mimetype='application/json')

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--reset-db':
        print("=== Сброс базы данных ===")
        reset_db()
        print("\nБаза данных сброшена. Запускайте сервер.")
        sys.exit(0)
    
    print("\n=== Сервер запущен ===")
    print("Откройте в браузере: http://localhost:5000")
    print("Для остановки нажмите Ctrl+C\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
