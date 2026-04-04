# pyright: reportGeneralTypeIssues=none, reportArgumentType=none, reportAssignmentType=none, reportAttributeAccessIssue=none, reportOptionalMemberAccess=none
from flask import Flask, render_template_string, request, jsonify, redirect, make_response, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, or_, and_, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
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
import base64
import os

def _generate_vapid_keys():
    """Генерируем настоящие VAPID ключи через py_vapid"""
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        private_key = v.private_key
        public_key = v.public_key

        # Конвертируем в URL-safe base64
        priv_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')
        pub_numbers = public_key.public_numbers()
        x = pub_numbers.x.to_bytes(32, byteorder='big')
        pub_point = b'\x04' + x + pub_numbers.y.to_bytes(32, byteorder='big')

        priv_b64 = base64.urlsafe_b64encode(priv_bytes).decode('utf-8').rstrip('=')
        pub_b64 = base64.urlsafe_b64encode(pub_point).decode('utf-8').rstrip('=')
        return priv_b64, pub_b64
    except Exception as e:
        print(f"[VAPID] py_vapid error: {e}, using fallback")
        # Фоллбэк — пустые ключи (push не будет работать, но звонки будут)
        return '', ''

# VAPID ключи — из env или генерируем
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')

if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
    VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = _generate_vapid_keys()
    if VAPID_PUBLIC_KEY:
        print(f"[VAPID] Generated keys (set VAPID_PUBLIC_KEY in env for persistence)")
    else:
        print(f"[VAPID] ⚠️ Could not generate keys — push notifications will NOT work")

VAPID_CLAIMS = {
    'sub': 'mailto:admin@jetesk.com'
}

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

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
else:
    engine = create_engine('sqlite:///messenger.db', echo=False, connect_args={'check_same_thread': False})

# Cloudinary настройка (для хостинга изображений)
CLOUDINARY_CONFIGURED = False
cloudinary = None
cloudinary_uploader = None
try:
    import cloudinary
    import cloudinary.uploader as cloudinary_uploader
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET')
    )
    CLOUDINARY_CONFIGURED = True
    print("[Cloudinary] Configured successfully")
except Exception as e:
    print(f"[Cloudinary] Not configured: {e}")

SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)
Base = declarative_base()

# Флаг для отслеживания инициализации БД
_db_initialized = False

def check_and_create_tables():
    """Проверить существование таблиц и создать их если нет"""
    try:
        # Используем checkfirst=True для безопасного создания
        print("Проверка и создание таблиц...")
        Base.metadata.create_all(engine, checkfirst=True)
        print("Таблицы проверены/созданы: users, messages, notifications")
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")
        raise

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    avatar_color = Column(String(20), default='6366f1')
    avatar_url = Column(String(500), nullable=True)
    jt_username = Column(String(50), unique=True, nullable=True)
    last_seen = Column(DateTime, nullable=True)

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    content = Column(String, nullable=False)  # Text для base64 изображений
    created_at = Column(DateTime, default=utc_now)
    file_type = Column(String(20), nullable=True)
    status = Column(String(20), default='sent')
    duration = Column(String(20), nullable=True)  # Длительность для голосовых сообщений

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    message = Column(String(500), nullable=False)
    type = Column(String(20), default='message')
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

class Call(Base):
    __tablename__ = 'calls'
    id = Column(Integer, primary_key=True)
    call_id = Column(String(100), unique=True, nullable=False, index=True)
    caller_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    callee_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(20), default='ringing')  # ringing, accepted, rejected, ended, missed
    offer_data = Column(String, nullable=True)  # JSON WebRTC offer
    answer_data = Column(String, nullable=True)  # JSON WebRTC answer
    ice_candidates = Column(String, nullable=True)  # JSON array of ICE candidates
    created_at = Column(DateTime, default=utc_now)
    ended_at = Column(DateTime, nullable=True)

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    device_id = Column(String(100), nullable=False, index=True)  # UUID клиента
    device_name = Column(String(200), nullable=True)  # "Chrome on Windows"
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    last_active = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

class PushSubscription(Base):
    __tablename__ = 'push_subscriptions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    device_id = Column(String(100), nullable=True)
    endpoint = Column(String(500), nullable=False, index=True)  # Push endpoint
    p256dh = Column(String(200), nullable=False)  # Public key
    auth = Column(String(100), nullable=False)  # Auth secret
    created_at = Column(DateTime, default=utc_now)
    last_used = Column(DateTime, nullable=True)

def init_db():
    check_and_create_tables()
    print("Database initialized with tables: users, messages, notifications")

def reset_db():
    """Сбросить базу данных (удалить все таблицы и создать заново)"""
    try:
        Base.metadata.drop_all(engine)
        print("Старые таблицы удалены")
    except Exception as e:
        print(f"Ошибка при удалении таблиц: {e}")
    Base.metadata.create_all(engine)
    print("База данных сброшена, таблицы созданы: users, messages, notifications")

def get_db():
    return sessionmaker(bind=engine)()

def init_tables():
    """Принудительно создать все таблицы"""
    try:
        print("=== Проверка таблиц БД ===")
        # Проверяем подключение
        with engine.connect() as conn:
            pass
        print("Подключение к БД успешно")
        
        # Создаём таблицы
        Base.metadata.create_all(engine)

        # Проверяем что таблицы созданы
        with engine.connect() as conn:
            if DATABASE_URL:
                result = conn.execute(text("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name IN ('users', 'messages', 'notifications', 'calls', 'devices', 'push_subscriptions')
                """))
            else:
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'messages', 'notifications', 'calls', 'devices', 'push_subscriptions')
                """))
            tables = [row[0] for row in result.fetchall()]
            print(f"Созданы таблицы: {', '.join(tables)}")

            if len(tables) < 6:
                raise Exception(f"Не все таблицы созданы! Найдено: {len(tables)}, ожидается: 6")
                
        print("=== БД готова к работе ===")
        return True
    except Exception as e:
        print(f"❌ ОШИБКА создания таблиц: {e}")
        print(f"DATABASE_URL: {DATABASE_URL or 'SQLite (messenger.db)'}")
        return False

# Инициализируем таблицы при загрузке
_tables_initialized = False
if not init_tables():
    print("ВНИМАНИЕ: Сервер запущен с ошибками БД. Проверьте подключение!")
else:
    _tables_initialized = True

def ensure_tables():
    """Гарантировать что таблицы существуют (для serverless/Supabase)"""
    global _tables_initialized
    if _tables_initialized:
        return True
    try:
        # Проверяем подключение
        with engine.connect() as conn:
            pass
        # Создаём таблицы
        Base.metadata.create_all(engine)
        _tables_initialized = True
        print("[DB] Tables ensured for serverless")
        return True
    except Exception as e:
        print(f"[DB] Error ensuring tables: {e}")
        # Не блокируем запрос - возможно таблицы уже существуют
        return False

def create_notification(db, user_id, message, sender_id=None, notif_type='message'):
    """Создаёт уведомление для пользователя"""
    try:
        notification = Notification(
            user_id=user_id,
            sender_id=sender_id,
            message=message,
            type=notif_type
        )
        db.add(notification)
        db.commit()
        return notification
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
        user = db.query(User).filter_by(id=int(user_id)).first()
        db.close()
        return user
    except Exception as e:
        db.close()
        print(f"Error getting current user: {e}")
        return None

@app.before_request
def before_request():
    """Гарантировать что таблицы существуют перед каждым запросом (для serverless)"""
    ensure_tables()

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
        print(f"[API /me] User: id={user.id}, username={user.username}, avatar_url={user.avatar_url}, jt_username={user.jt_username}")
        return jsonify({'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color or '6366f1', 'avatar_url': user.avatar_url, 'jt_username': user.jt_username})
    print(f"[API /me] No user (cookie: {request.cookies.get('user_id')})")
    return jsonify(None)

@app.route('/api/register', methods=['POST'])
def api_register():
    # Поддержка и JSON, и FormData
    if request.content_type and 'multipart/form-data' in request.content_type:
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        avatar_color = request.form.get('avatar_color', generate_avatar_color())
        avatar_file = request.files.get('avatar_file')
        avatar_data = request.form.get('avatar_data')
    else:
        data = request.json
        name = data.get('name', data.get('username', '')).strip()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        avatar_color = generate_avatar_color()
        avatar_file = None
        avatar_data = None

    print(f"=== РЕГИСТРАЦИЯ ===")
    print(f"Name: {name}, Username: {username}")
    print(f"Password получен: {'да' if password else 'нет'}")
    print(f"Avatar color: {avatar_color}")

    if not name or len(name) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not username or len(username) < 5:
        return jsonify({'success': False, 'message': 'Username должен быть 5-32 символа'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        existing = db.query(User).filter_by(username=username).first()
        if existing:
            return jsonify({'success': False, 'message': 'Username уже занят'})

        password_hash = generate_password_hash(password)

        avatar_url = None
        # Загрузка аватарки через Cloudinary
        if avatar_file and CLOUDINARY_CONFIGURED:
            try:
                import cloudinary.uploader
                result = cloudinary.uploader.upload(
                    avatar_file.stream,
                    folder='jtesk/avatars',
                    resource_type='image'
                )
                avatar_url = result['secure_url']
            except Exception as e:
                print(f"[Register] Avatar upload error: {e}")
        elif avatar_data and CLOUDINARY_CONFIGURED:
            try:
                import cloudinary.uploader
                import base64
                if avatar_data.startswith('data:'):
                    avatar_data = avatar_data.split(',', 1)[1]
                img_bytes = base64.b64decode(avatar_data)
                import io
                result = cloudinary.uploader.upload(
                    io.BytesIO(img_bytes),
                    folder='jtesk/avatars',
                    resource_type='image'
                )
                avatar_url = result['secure_url']
            except Exception as e:
                print(f"[Register] Avatar upload error: {e}")

        user = User(
            username=name,  # Отображаемое имя
            password_hash=password_hash,
            avatar_color=avatar_color,
            avatar_url=avatar_url,
            jt_username=username  # Уникальный username
        )
        db.add(user)
        db.commit()

        print(f"Пользователь создан: id={user.id}, name={user.username}, jt_username={user.jt_username}")

        resp = make_response(jsonify({'success': True, 'user': {
            'id': user.id,
            'username': user.username,
            'avatar_color': user.avatar_color or '6366f1',
            'avatar_url': user.avatar_url,
            'jt_username': user.jt_username
        }}))
        resp.set_cookie('user_id', str(user.id), max_age=60*60*24*30, samesite='lax')
        return resp
    except Exception as e:
        db.rollback()
        print(f"Ошибка регистрации: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', '')

    print(f"=== ВХОД ===")
    print(f"Username: {username}")
    print(f"Password получен: {'да' if password else 'нет'}")
    print(f"Device ID: {device_id}, Name: {device_name}")

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        user = db.query(User).filter_by(username=username).first()

        if not user:
            print(f"Пользователь '{username}' не найден")
            return jsonify({'success': False, 'message': 'Пользователь не найден'})

        print(f"Пользователь найден: id={user.id}")
        print(f"password_hash в БД: {user.password_hash[:50] if user.password_hash else 'NULL'}...")

        if not user.password_hash:
            print("password_hash пуст!")
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        is_valid = check_password_hash(user.password_hash, password)
        print(f"Проверка пароля: {'OK' if is_valid else 'FAIL'}")
        
        if not is_valid:
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        print(f"Вход успешен: {username}")

        # Обновляем last_seen при входе
        from datetime import datetime
        user.last_seen = utc_now()
        db.commit()

        # Сохраняем/обновляем устройство
        device_info = None
        if device_id:
            try:
                existing_device = db.query(Device).filter_by(user_id=user.id, device_id=device_id).first()
                ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
                ua = request.headers.get('User-Agent', '')[:500]

                if existing_device:
                    existing_device.last_active = utc_now()
                    existing_device.ip_address = ip
                    existing_device.user_agent = ua
                    if device_name and not existing_device.device_name:
                        existing_device.device_name = device_name[:200]
                    device_info = existing_device
                else:
                    new_device = Device(
                        user_id=user.id,
                        device_id=device_id,
                        device_name=device_name[:200] if device_name else None,
                        ip_address=ip,
                        user_agent=ua
                    )
                    db.add(new_device)
                    device_info = new_device
                db.commit()
            except Exception as e:
                print(f"[Device] Error saving device: {e}")
                db.rollback()

        # Собираем информацию об устройстве для ответа
        current_device_data = None
        if device_info:
            last_active_msk = to_msk(device_info.last_active)
            current_device_data = {
                'device_id': device_info.device_id,
                'device_name': device_info.device_name,
                'last_active': last_active_msk.strftime('%d.%m.%Y %H:%M') if last_active_msk else None
            }

        resp = make_response(jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'avatar_color': user.avatar_color or '6366f1',
                'avatar_url': user.avatar_url,
                'jt_username': user.jt_username,
                'last_seen': user.last_seen.isoformat() if user.last_seen is not None else None
            },
            'current_device': current_device_data
        }))
        resp.set_cookie('user_id', str(user.id), max_age=60*60*24*30, samesite='lax')
        resp.delete_cookie('username')  # Удаляем старый cookie
        return resp
    except Exception as e:
        db.rollback()
        print(f"Ошибка входа: {e}")
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
        result = []
        for u in users:
            # Определяем онлайн (heartbeat каждые 3 сек, считаем онлайн если < 10 сек)
            # Сравниваем по UTC времени (как хранится в БД)
            is_online = False
            last_seen_str = None
            if u.last_seen is not None:
                time_diff = utc_now() - u.last_seen
                is_online = time_diff.total_seconds() < 10
                # Конвертируем в MSK (+3 часа) для отображения
                last_seen_msk = to_msk(u.last_seen)
                last_seen_str = last_seen_msk.strftime('%d.%m %H:%M') if last_seen_msk else None

            # Считаем непрочитанные сообщения от этого пользователя
            unread_count = db.query(Message).filter(
                Message.sender_id == u.id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            ).count()

            result.append({
                'id': u.id,
                'username': u.username,
                'avatar_color': u.avatar_color or '6366f1',
                'avatar_url': u.avatar_url,
                'jt_username': u.jt_username,
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
            msgs = db.query(Message).filter(
                or_(
                    and_(Message.sender_id == user.id, Message.recipient_id == recipient_id),
                    and_(Message.sender_id == recipient_id, Message.recipient_id == user.id)
                )
            ).order_by(Message.created_at.asc()).all()
        else:
            msgs = db.query(Message).filter(Message.recipient_id.is_(None)).order_by(Message.created_at.asc()).all()
        result = []
        for m in msgs:
            sender = db.query(User).filter_by(id=m.sender_id).first()
            # Получаем статус, если колонка существует
            msg_status = 'sent'
            try:
                msg_status = m.status or 'sent'
            except:
                msg_status = 'sent'

            duration = None
            if m.file_type == 'voice':
                # Получаем длительность из БД или ставим 0:00
                if hasattr(m, 'duration') and m.duration:
                    # Конвертируем из формата "30s" в "0:30"
                    dur_sec = int(m.duration.replace('s', ''))
                    minutes = dur_sec // 60
                    seconds = dur_sec % 60
                    duration = f'{minutes}:{seconds:02d}'
                else:
                    duration = '0:00'

            msg_dict = {
                'id': m.id,
                'sender': sender.username if sender else 'Unknown',
                'content': m.content,
                'created_at': to_msk(m.created_at).strftime('%H:%M'),
                'is_mine': m.sender_id == user.id,
                'file_type': m.file_type,
                'status': msg_status,
                'duration': duration
            }
            result.append(msg_dict)
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
        # Пробуем со статусом
        try:
            msg = Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content, status='sent')
            db.add(msg)
            db.commit()
        except:
            db.rollback()
            msg = Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content)
            db.add(msg)
            db.commit()
        
        msg_id = msg.id

        # Отправляем уведомление получателю
        if recipient_id:
            recipient = db.query(User).filter_by(id=recipient_id).first()
            if recipient:
                create_notification(
                    db=db,
                    user_id=recipient_id,
                    message=f"Новое сообщение от {user.username}: {content[:50]}{'...' if len(content) > 50 else ''}",
                    sender_id=user.id,
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
    # Гарантируем что таблицы существуют
    ensure_tables()

    print(f"[send-file] DATABASE_URL present: {bool(DATABASE_URL)}")
    print(f"[send-file] Tables initialized: {_tables_initialized}")

    user = get_current_user()
    if not user:
        print(f"[send-file] Not authorized")
        return jsonify({'success': False, 'message': 'Not authorized'})

    recipient_id = request.form.get('recipient_id')
    file_data = request.form.get('file_data')  # Base64 данные
    file_type = request.form.get('file_type')  # 'image', 'file', или 'voice'

    print(f"[send-file] User: {user.id}, file_type: {file_type}, recipient: {recipient_id}")
    print(f"[send-file] File data length: {len(file_data) if file_data else 0}")

    db = get_db()
    try:
        content = None
        duration = None

        # Обработка голосовых сообщений через multipart/form-data
        if file_type == 'voice' and 'file' in request.files:
            file = request.files['file']
            if file and file.filename:
                try:
                    # Исправление 1: resource_type='video' для аудио (Cloudinary обрабатывает аудио как видео)
                    # Исправление 2: добавлена обработка ошибок
                    upload_result = cloudinary_uploader.upload(
                        file.stream,
                        folder='jtesk/voice',
                        resource_type='video',  # Исправлено: было 'auto'
                        public_id=f'voice_{user.id}_{int(time.time())}',
                        format='mp3'  # Исправление 3: конвертация в MP3 для совместимости
                    )
                    content = upload_result['secure_url']
                    # Получаем длительность из метаданных Cloudinary
                    if 'duration' in upload_result:
                        duration = str(int(upload_result['duration'])) + 's'
                    print(f"[send-file] Voice uploaded to Cloudinary: {content}")
                except Exception as cloudinary_error:
                    # Исправление 5: Fallback на base64 при ошибке Cloudinary
                    print(f"[send-file] Cloudinary upload failed: {cloudinary_error}")
                    print("[send-file] Using base64 fallback for voice message")
                    
                    # Читаем файл в base64
                    file.seek(0)
                    import base64
                    file_bytes = file.read()
                    file_base64 = base64.b64encode(file_bytes).decode('utf-8')
                    
                    # Определяем MIME-тип
                    mime_type = file.content_type if file.content_type else 'audio/webm'
                    # Для совместимости используем audio/mp4 (поддерживается всеми браузерами)
                    if 'webm' in mime_type:
                        mime_type = 'audio/mp4'
                    
                    content = f'data:{mime_type};base64,{file_base64}'
                    print(f"[send-file] Voice converted to base64, length: {len(content)}")
            else:
                return jsonify({'success': False, 'message': 'No file uploaded'})
        # Обработка base64 данных (изображения и файлы)
        elif file_data:
            if len(file_data) > 10 * 1024 * 1024:
                print(f"[send-file] File too large: {len(file_data)} bytes")
                return jsonify({'success': False, 'message': 'File too large (max 10MB)'})
            if not file_data.startswith('data:'):
                print(f"[send-file] Invalid data URL format")
                return jsonify({'success': False, 'message': 'Invalid file format'})
            content = file_data
        else:
            print(f"[send-file] No file data in request")
            return jsonify({'success': False, 'message': 'No file data'})

        # Пробуем со статусом и duration
        try:
            msg = Message(
                sender_id=user.id,
                recipient_id=recipient_id if recipient_id else None,
                content=content,
                file_type=file_type,
                status='sent',
                duration=duration
            )
            db.add(msg)
            db.commit()
            print(f"[send-file] Message saved with id: {msg.id}")
        except:
            # Если колонки status нет - без статуса
            db.rollback()
            msg = Message(
                sender_id=user.id,
                recipient_id=recipient_id if recipient_id else None,
                content=content,
                file_type=file_type,
                duration=duration
            )
            db.add(msg)
            db.commit()
            print(f"[send-file] Message saved (no status) with id: {msg.id}")

        # Отправляем уведомление получателю
        if recipient_id:
            try:
                recipient = db.query(User).filter_by(id=int(recipient_id)).first()
                if recipient:
                    notif_message = f"Голосовое сообщение от {user.username}" if file_type == 'voice' else f"Новое фото от {user.username}"
                    create_notification(
                        db=db,
                        user_id=int(recipient_id),
                        message=notif_message,
                        sender_id=user.id,
                        notif_type='message'
                    )
                    print(f"[send-file] Notification sent to user {recipient_id}")
            except Exception as notif_err:
                print(f"[send-file] Error sending notification: {notif_err}")

        return jsonify({'success': True, 'id': msg.id, 'status': 'sent'})
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
    from datetime import datetime

    user_id = request.cookies.get('user_id')
    if user_id:
        # Обновляем last_seen при выходе
        db = get_db()
        try:
            user = db.query(User).filter_by(id=int(user_id)).first()
            if user:
                user.last_seen = utc_now()
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

@app.route('/api/delete-message', methods=['POST'])
def api_delete_message():
    """Удаление сообщения"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    
    data = request.json
    message_id = data.get('message_id')
    
    if not message_id:
        return jsonify({'success': False, 'message': 'No message_id'})
    
    db = get_db()
    try:
        msg = db.query(Message).filter_by(id=int(message_id)).first()
        if not msg:
            return jsonify({'success': False, 'message': 'Message not found'})
        
        # Проверяем, что пользователь является автором сообщения
        if msg.sender_id != user.id:
            return jsonify({'success': False, 'message': 'Not your message'})
        
        db.delete(msg)
        db.commit()
        print(f"[delete-message] Message {message_id} deleted by user {user.id}")
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[delete-message] Error: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/settings/clear-messages', methods=['POST'])
def api_clear_messages():
    """Удаляет все сообщения, отправленные текущим пользователем"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        db.query(Message).filter(Message.sender_id == user.id).delete()
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
        db.query(Message).filter(
            or_(Message.sender_id == user.id, Message.recipient_id == user.id)
        ).delete()
        # Удаляем пользователя
        db.query(User).filter(User.id == user.id).delete()
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
        notifications = db.query(Notification).filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(50).all()
        result = []
        for n in notifications:
            sender = db.query(User).filter_by(id=n.sender_id).first() if n.sender_id else None
            result.append({
                'id': n.id,
                'message': n.message,
                'type': n.type,
                'is_read': bool(n.is_read),
                'created_at': to_msk(n.created_at).strftime('%H:%M') if n.created_at else '',
                'sender': {'id': sender.id, 'username': sender.username, 'avatar_color': sender.avatar_color} if sender else None
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
        count = db.query(Notification).filter_by(user_id=user.id, is_read=0).count()
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
        db.query(Notification).filter_by(user_id=user.id, is_read=0).update({'is_read': 1})
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
        notification = db.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if not notification:
            return jsonify({'success': False, 'message': 'Notification not found'})
        notification.is_read = 1
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

    print(f"✅ change-username: текущий пользователь id={user.id}, username={user.username}")

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
        existing = db.query(User).filter_by(username=new_username).first()
        if existing and existing.id != user.id:
            print(f"⚠️ change-username: имя '{new_username}' уже занято пользователем id={existing.id}")
            db.close()
            return jsonify({'success': False, 'message': 'Это имя уже занято'})

        # Обновляем имя в базе данных (id остаётся прежним)
        old_username = user.username
        user.username = new_username
        db.commit()

        print(f"✅ change-username: успешно! id={user.id}, старый ник='{old_username}', новый ник='{new_username}'")
        db.close()

        # Возвращаем новый username и удаляем старый cookie
        resp = make_response(jsonify({'success': True, 'username': new_username, 'id': user.id}))
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
        msgs = db.query(Message).filter(
            or_(
                and_(Message.sender_id == user.id, Message.recipient_id.isnot(None)),
                and_(Message.recipient_id == user.id, Message.sender_id.isnot(None))
            )
        ).order_by(Message.created_at.desc()).all()

        # Группируем по собеседнику и берём последнее сообщение
        last_messages = {}
        for msg in msgs:
            partner_id = msg.recipient_id if msg.sender_id == user.id else msg.sender_id
            if partner_id not in last_messages:
                last_messages[partner_id] = msg

        result = []
        for partner_id, msg in last_messages.items():
            sender = db.query(User).filter_by(id=msg.sender_id).first()
            
            # Считаем непрочитанные сообщения от этого партнера
            unread_count = db.query(Message).filter(
                Message.sender_id == partner_id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            ).count()

            duration = None
            if msg.file_type == 'voice':
                # Получаем длительность из БД или ставим 0:00
                if hasattr(msg, 'duration') and msg.duration:
                    dur_sec = int(msg.duration.replace('s', ''))
                    minutes = dur_sec // 60
                    seconds = dur_sec % 60
                    duration = f'{minutes}:{seconds:02d}'
                else:
                    duration = '0:00'

            result.append({
                'id': msg.id,
                'sender': sender.username if sender else 'Unknown',
                'sender_id': msg.sender_id,
                'recipient_id': msg.recipient_id,
                'content': msg.content,
                'created_at': to_msk(msg.created_at).strftime('%H:%M'),
                'file_type': msg.file_type,
                'status': getattr(msg, 'status', 'sent') or 'sent',
                'unread_count': unread_count,
                'duration': duration
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
    from datetime import datetime

    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False})

    db = get_db()
    try:
        user = db.query(User).filter_by(id=int(user_id)).first()
        if user:
            user.last_seen = utc_now()
            db.commit()

        # Обновляем last_active для текущего устройства
        device_id = request.json.get('device_id', '') if request.is_json else ''
        if device_id and user:
            try:
                device = db.query(Device).filter_by(user_id=user.id, device_id=device_id).first()
                if device:
                    device.last_active = utc_now()
                    db.commit()
            except Exception as e:
                print(f"[Heartbeat] Device update error: {e}")
                db.rollback()

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
        db.query(Message).filter(
            Message.sender_id == sender_id,
            Message.recipient_id == user.id,
            Message.status != 'read'
        ).update({'status': 'read'}, synchronize_session=False)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"Error marking messages as read: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/settings/delete-account', methods=['POST'])
def api_delete_user_account():
    """Удалить аккаунт и все связанные данные"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401

    user_id = user.id
    db = get_db()
    try:
        # Этап 1: Удаляем дочерние записи (до commit)
        db.query(PushSubscription).filter_by(user_id=user_id).delete(synchronize_session=False)
        db.query(Device).filter_by(user_id=user_id).delete(synchronize_session=False)
        db.query(Call).filter(
            (Call.caller_id == user_id) | (Call.callee_id == user_id)
        ).delete(synchronize_session=False)
        db.query(Notification).filter(
            (Notification.user_id == user_id) | (Notification.sender_id == user_id)
        ).delete(synchronize_session=False)
        db.query(Message).filter(
            (Message.sender_id == user_id) | (Message.recipient_id == user_id)
        ).delete(synchronize_session=False)
        db.commit()  # Коммитим удаление дочерних

        # Этап 2: Теперь удаляем пользователя
        db.query(User).filter_by(id=user_id).delete(synchronize_session=False)
        db.commit()

        resp = make_response(jsonify({'success': True}))
        resp.set_cookie('user_id', '', max_age=0)
        return resp
    except Exception as e:
        db.rollback()
        print(f"[Delete account] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
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
        existing = db.query(User).filter_by(username=username).first()
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

    # Создаём сессию СРАЗУ и используем её для всего
    db = get_db()
    try:
        # Получаем пользователя в рамках этой сессии
        user = db.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})

        if not jt_username:
            # Пустой - удаляем
            user.jt_username = None
            db.commit()
            return jsonify({'success': True, 'jt_username': None})

        # Проверка валидности: 5-32 символа, латиница, цифры, точки, подчёркивания
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]{4,31}$', jt_username):
            return jsonify({'success': False, 'message': 'Неверный формат. 5-32 символа, начинается с буквы (a-z), латиница, цифры, точки и подчёркивания'})

        # Проверяем что нет подряд идущих точек или подчёркиваний
        if '..' in jt_username or '__' in jt_username:
            return jsonify({'success': False, 'message': 'Username не может содержать подряд идущие точки или подчёркивания'})

        # Проверяем что не заканчивается на точку или подчёркивание
        if jt_username.endswith('.') or jt_username.endswith('_'):
            return jsonify({'success': False, 'message': 'Username не может заканчиваться на точку или подчёркивание'})

        # Проверяем, не занято ли
        existing = db.query(User).filter_by(jt_username=jt_username).first()
        if existing and existing.id != user.id:
            return jsonify({'success': False, 'message': 'Этот @username уже занят'})

        user.jt_username = jt_username
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

    # Создаём сессию СРАЗУ и используем её для всего
    db = get_db()
    try:
        # Получаем пользователя в рамках этой сессии
        user = db.query(User).filter_by(id=int(user_id)).first()
        if not user:
            print(f"[Avatar] User not found: id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'})

        print(f"[Avatar] Upload request from user {user.id} ({user.username})")

        if 'avatar' not in request.files:
            print(f"[Avatar] No file in request")
            return jsonify({'success': False, 'message': 'No file provided'})

        file = request.files['avatar']
        if file.filename == '':
            print(f"[Avatar] Empty filename")
            return jsonify({'success': False, 'message': 'No file selected'})

        import io
        import uuid
        filename = file.filename if file.filename else 'unknown.png'
        ext = os.path.splitext(filename)[1].lower()
        print(f"[Avatar] File: {file.filename}, ext: {ext}")

        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            return jsonify({'success': False, 'message': 'Неверный формат. Разрешены: jpg, png, gif, webp'})

        # Читаем файл в память
        file_data = file.read()
        file_io = io.BytesIO(file_data)

        avatar_url = None

        if CLOUDINARY_CONFIGURED:
            print(f"[Avatar] Uploading to Cloudinary...")
            try:
                upload_result = cloudinary_uploader.upload(
                    file_io,
                    folder='avatars',
                    public_id=f"user_{user.id}_{uuid.uuid4().hex[:8]}",
                    resource_type='image'
                )
                avatar_url = upload_result['secure_url']
                
                avatar_url = upload_result['secure_url'].replace('/upload/', '/upload/w_200,h_200,c_fill,g_face/', 1)
                print(f"[Avatar] Uploaded to Cloudinary: {avatar_url}")
            except Exception as e:
                print(f"[Avatar] Cloudinary upload error: {e}")
                return jsonify({'success': False, 'message': f'Cloudinary error: {str(e)}'})
        else:

            print(f"[Avatar] Saving locally...")
            filename = f"avatar_{user.id}_{uuid.uuid4().hex[:8]}{ext}"

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

        # Сохраняем путь в БД (в той же сессии!!!!!!!!!!!!!!!!!!!!!)
        print(f"[Avatar] BEFORE UPDATE: user_id={user.id}, current avatar_url={user.avatar_url}")
        print(f"[Avatar] Updating database: user_id={user.id}, new avatar_url={avatar_url}")
        user.avatar_url = avatar_url
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

# ============================================
# === PUSH NOTIFICATIONS ===
# ============================================

def send_push_notification(user_id, title, body, data=None):
    """Отправить push-уведомление пользователю через Web Push API"""
    # Если ключи не настроены — пропускаем push (звонки всё равно работают)
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return {'sent': 0, 'failed': 0}

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {'sent': 0, 'failed': 0}

    import json
    db = get_db()
    try:
        subs = db.query(PushSubscription).filter_by(user_id=user_id).all()
        if not subs:
            return {'sent': 0, 'failed': 0}
    except Exception:
        # Таблица ещё не создана — не критично
        return {'sent': 0, 'failed': 0}

    sent = 0
    failed = 0
    for sub in subs:
        try:
            subscription_info = {
                'endpoint': sub.endpoint,
                'keys': {
                    'p256dh': sub.p256dh,
                    'auth': sub.auth
                }
            }

            payload = json.dumps({
                'title': title,
                'body': body,
                'icon': '/Jetesk.png',
                'badge': '/Jetesk.png',
                'vibrate': [500, 200, 500, 200, 500],
                'tag': data.get('tag', 'jetesk-call') if data else 'jetesk-notification',
                'requireInteraction': True,
                'renotify': True,
                'data': data or {}
            })

            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            sent += 1
        except WebPushException:
            failed += 1
            # Невалидная подписка — удаляем
            try:
                db.delete(sub)
                db.commit()
            except:
                pass
        except Exception:
            failed += 1

    return {'sent': sent, 'failed': failed}

@app.route('/api/push/vapid-public-key', methods=['GET'])
def api_push_vapid_key():
    """Получить VAPID public key для клиента"""
    return jsonify({'public_key': VAPID_PUBLIC_KEY})

@app.route('/api/push/subscribe', methods=['POST'])
def api_push_subscribe():
    """Сохранить push-подписку"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401

    data = request.json
    endpoint = data.get('endpoint', '')
    p256dh = data.get('keys', {}).get('p256dh', '')
    auth = data.get('keys', {}).get('auth', '')
    device_id = data.get('device_id', '')

    if not endpoint or not p256dh or not auth:
        return jsonify({'success': False, 'message': 'Missing subscription data'}), 400

    db = get_db()
    try:
        # Проверяем дубликат по endpoint
        existing = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
        if existing:
            existing.user_id = user.id
            existing.device_id = device_id
            existing.last_used = utc_now()
            db.commit()
            return jsonify({'success': True, 'message': 'Updated'})

        sub = PushSubscription(
            user_id=user.id,
            device_id=device_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth
        )
        db.add(sub)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Push/Subscribe] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/push/unsubscribe', methods=['POST'])
def api_push_unsubscribe():
    """Удалить push-подписку"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401

    data = request.json
    endpoint = data.get('endpoint', '')

    db = get_db()
    try:
        if endpoint:
            db.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).delete()
        else:
            # Удаляем все подписки пользователя
            db.query(PushSubscription).filter_by(user_id=user.id).delete()
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Push/Unsubscribe] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

# ============================================
# === DEVICE MANAGEMENT ===
# ============================================

@app.route('/api/devices', methods=['GET'])
def api_devices():
    """Получить список устройств текущего пользователя"""
    user = get_current_user()
    if not user:
        return jsonify([])
    db = get_db()
    try:
        devices = db.query(Device).filter_by(user_id=user.id).order_by(Device.last_active.desc()).all()
        result = []
        for d in devices:
            last_active_msk = to_msk(d.last_active) if d.last_active else None
            result.append({
                'id': d.id,
                'device_id': d.device_id,
                'device_name': d.device_name or 'Неизвестное устройство',
                'ip_address': d.ip_address or 'Unknown',
                'last_active': last_active_msk.strftime('%d.%m.%Y %H:%M') if last_active_msk else 'Неизвестно',
                'is_current': True  # Все устройства из этого списка - текущие
            })
        return jsonify(result)
    except Exception as e:
        print(f"[Devices] Error: {e}")
        return jsonify([])
    finally:
        db.close()

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def api_device_delete(device_id):
    """Удалить устройство (разлогинить)"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        device = db.query(Device).filter_by(id=device_id, user_id=user.id).first()
        if not device:
            return jsonify({'success': False, 'message': 'Device not found'})
        db.delete(device)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Device delete] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

# ============================================
# === CALL (Audio Call) API ===
# ============================================

@app.route('/api/call/offer', methods=['POST'])
def api_call_offer():
    """Начать звонок — отправляем WebRTC offer"""
    import json
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401

        data = request.get_json()
        call_id = data.get('call_id')
        to_user_id = data.get('to_user_id')
        offer = data.get('offer')

        if not call_id or not to_user_id or not offer:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400

        # Проверяем что пользователь существует
        callee = db.query(User).filter_by(id=int(to_user_id)).first()
        if not callee:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            call = Call(
                call_id=call_id,
                caller_id=int(user_id),
                callee_id=int(to_user_id),
                status='ringing',
                offer_data=json.dumps(offer)
            )
            db.add(call)
        else:
            call.offer_data = json.dumps(offer)
            call.status = 'ringing'

        db.commit()

        # Отправляем push-уведомление получателю
        caller = db.query(User).filter_by(id=int(user_id)).first()
        caller_name = caller.username if caller else 'Неизвестный'
        try:
            send_push_notification(
                user_id=int(to_user_id),
                title='📞 Входящий звонок',
                body=f'{caller_name} звонит вам...',
                data={
                    'type': 'incoming_call',
                    'call_id': call_id,
                    'from_user_id': int(user_id),
                    'from_user_name': caller_name,
                    'tag': f'call-{call_id}'
                }
            )
        except Exception as e:
            print(f"[Call/Offer] Push error: {e}")

        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Call/Offer] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/status/<call_id>', methods=['GET'])
def api_call_status(call_id):
    """Проверить статус звонка (для исходящего)"""
    import json
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'status': 'not_found'}), 404

        result = {'status': call.status}
        # Возвращаем answer как только он появится (при accepted или connected)
        if call.answer_data:
            try:
                result['answer'] = json.loads(call.answer_data)
            except:
                pass

        return jsonify(result)
    except Exception as e:
        print(f"[Call/Status] Error: {e}")
        return jsonify({'status': 'error'}), 500
    finally:
        db.close()

@app.route('/api/call/check/<call_id>', methods=['GET'])
def api_call_check(call_id):
    """Проверить статус звонка для ОБОИХ участников (включая hangup)"""
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'status': 'not_found'}), 404
        return jsonify({'status': call.status})
    except Exception as e:
        print(f"[Call/Check] Error: {e}")
        return jsonify({'status': 'error'}), 500
    finally:
        db.close()

@app.route('/api/call/ice', methods=['POST'])
def api_call_ice():
    """Отправить ICE candidate"""
    import json
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401

        data = request.get_json()
        call_id = data.get('call_id')
        candidate = data.get('candidate')

        if not call_id or not candidate:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400

        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'success': False, 'message': 'Call not found'}), 404

        # Добавляем ICE candidate в список
        candidates = []
        if call.ice_candidates:
            try:
                candidates = json.loads(call.ice_candidates)
            except:
                candidates = []
        candidates.append(candidate)
        call.ice_candidates = json.dumps(candidates)

        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Call/ICE] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/incoming', methods=['GET'])
def api_call_incoming():
    """Проверить входящие звонки"""
    import json
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({}), 200

        # Ищем активные звонки где пользователь — callee
        call = db.query(Call).filter(
            Call.callee_id == int(user_id),
            Call.status == 'ringing'
        ).order_by(Call.created_at.desc()).first()

        if not call:
            return jsonify({}), 200

        caller = db.query(User).filter_by(id=call.caller_id).first()
        return jsonify({
            'call_id': call.call_id,
            'from_user_id': call.caller_id,
            'from_user_name': caller.username if caller else 'Unknown',
            'offer': json.loads(call.offer_data) if call.offer_data else None
        })
    except Exception as e:
        print(f"[Call/Incoming] Error: {e}")
        return jsonify({}), 500
    finally:
        db.close()

@app.route('/api/call/accept', methods=['POST'])
def api_call_accept():
    """Принять звонок"""
    db = get_db()
    try:
        data = request.get_json()
        call_id = data.get('call_id')

        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'success': False, 'message': 'Call not found'}), 404

        call.status = 'accepted'
        db.commit()

        # Возвращаем offer чтобы callee мог создать answer
        import json
        return jsonify({
            'success': True,
            'offer': json.loads(call.offer_data) if call.offer_data else None
        })
    except Exception as e:
        db.rollback()
        print(f"[Call/Accept] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/answer', methods=['POST'])
def api_call_answer():
    """Отправить WebRTC answer"""
    import json
    db = get_db()
    try:
        data = request.get_json()
        call_id = data.get('call_id')
        answer = data.get('answer')

        if not call_id or not answer:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400

        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'success': False, 'message': 'Call not found'}), 404

        call.answer_data = json.dumps(answer)
        call.status = 'connected'
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Call/Answer] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/reject', methods=['POST'])
def api_call_reject():
    """Отклонить звонок"""
    from datetime import datetime
    import json
    db = get_db()
    try:
        data = request.get_json()
        call_id = data.get('call_id')

        call = db.query(Call).filter_by(call_id=call_id).first()
        if call:
            call.status = 'rejected'
            call.ended_at = utc_now()
            db.commit()

            # Отправляем сообщение "Пропущенный вызов" звонившему
            try:
                caller = db.query(User).filter_by(id=call.caller_id).first()
                if caller:
                    callee = db.query(User).filter_by(id=call.callee_id).first()
                    callee_name = callee.username if callee else 'Неизвестный'
                    msg = Message(
                        sender_id=int(call.callee_id),
                        recipient_id=int(call.caller_id),
                        content=f'__CALL_MISSED__:{callee_name}',
                        created_at=utc_now(),
                        file_type='call_missed',
                        status='read'
                    )
                    db.add(msg)
                    db.commit()
            except Exception as e:
                print(f"[Call/Missed msg] Error: {e}")

        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Call/Reject] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/ice/<call_id>', methods=['GET'])
def api_call_ice_poll(call_id):
    """Получить ICE candidates"""
    import json
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'candidates': []}), 200

        candidates = []
        if call.ice_candidates:
            try:
                candidates = json.loads(call.ice_candidates)
            except:
                candidates = []

        return jsonify({'candidates': candidates})
    except Exception as e:
        print(f"[Call/ICE poll] Error: {e}")
        return jsonify({'candidates': []}), 500
    finally:
        db.close()

@app.route('/api/call/end', methods=['POST'])
def api_call_end():
    """Завершить звонок"""
    from datetime import datetime
    db = get_db()
    try:
        data = request.get_json()
        call_id = data.get('call_id')

        call = db.query(Call).filter_by(call_id=call_id).first()
        if call:
            was_connected = call.status == 'connected'
            was_ringing = call.status == 'ringing'
            caller_name = None

            # Если звонок был ringing (не отвечен) — отправляем пропущенный
            if was_ringing:
                try:
                    caller = db.query(User).filter_by(id=call.caller_id).first()
                    callee = db.query(User).filter_by(id=call.callee_id).first()
                    caller_name = caller.username if caller else 'Неизвестный'
                    callee_name = callee.username if callee else 'Неизвестный'

                    msg = Message(
                        sender_id=int(call.caller_id),
                        recipient_id=int(call.callee_id),
                        content=f'__CALL_MISSED__:{caller_name}',
                        created_at=utc_now(),
                        file_type='call_missed',
                        status='read'
                    )
                    db.add(msg)
                except Exception as e:
                    print(f"[Call/Missed msg on end] Error: {e}")

            call.status = 'ended'
            call.ended_at = utc_now()
            db.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"[Call/End] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

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
