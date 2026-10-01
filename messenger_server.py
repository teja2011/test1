# pyright: reportGeneralTypeIssues=none, reportArgumentType=none, reportAssignmentType=none, reportAttributeAccessIssue=none, reportOptionalMemberAccess=none
from flask import Flask, render_template_string, request, jsonify, redirect, make_response, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, or_, and_, text, UniqueConstraint
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
import json
import pymysql

def _generate_vapid_keys():
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        private_key = v.private_key
        public_key = v.public_key
        priv_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')
        pub_numbers = public_key.public_numbers()
        x = pub_numbers.x.to_bytes(32, byteorder='big')
        pub_point = b'\x04' + x + pub_numbers.y.to_bytes(32, byteorder='big')
        priv_b64 = base64.urlsafe_b64encode(priv_bytes).decode('utf-8').rstrip('=')
        pub_b64 = base64.urlsafe_b64encode(pub_point).decode('utf-8').rstrip('=')
        return priv_b64, pub_b64
    except Exception:
        return '', ''

VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')

if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
    VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = _generate_vapid_keys()

VAPID_CLAIMS = {'sub': 'mailto:admin@jetesk.com'}

if not os.environ.get('VERCEL'):
    load_dotenv()

def to_msk(dt):
    if dt is None:
        return None
    return dt + timedelta(hours=3)

def utc_now():
    return datetime.utcnow()

KEEPALIVE_INTERVAL = int(os.environ.get('KEEPALIVE_INTERVAL', 300))
KEEPALIVE_URL = os.environ.get('KEEPALIVE_URL', '')

def keepalive_worker():
    if not KEEPALIVE_URL:
        return
    while True:
        try:
            requests.get(KEEPALIVE_URL, timeout=10)
        except Exception:
            pass
        time.sleep(KEEPALIVE_INTERVAL)

if KEEPALIVE_URL:
    threading.Thread(target=keepalive_worker, daemon=True).start()

DATABASE_URL = os.environ.get('DATABASE_URL')

# Авто-фикс: принудительно PyMySQL
if DATABASE_URL and DATABASE_URL.startswith('mysql://'):
    DATABASE_URL = DATABASE_URL.replace('mysql://', 'mysql+pymysql://', 1)
    print("[DB] Auto-fixed URL: mysql:// -> mysql+pymysql://")

if DATABASE_URL:
    connect_args = {
        'charset': 'utf8mb4',
        'use_unicode': True,
        'client_flag': pymysql.constants.CLIENT.MULTI_STATEMENTS,
    }
    
    if 'ssl_ca=' in DATABASE_URL:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        
        parsed = urlparse(DATABASE_URL)
        params = parse_qs(parsed.query)
        ssl_ca = params.pop('ssl_ca', [None])[0]
        
        new_query = urlencode({k: v[0] for k, v in params.items()})
        DATABASE_URL = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
        
        if ssl_ca:
            connect_args['ssl_ca'] = ssl_ca
            print(f"[DB] SSL CA: {ssl_ca}")
    
        if DATABASE_URL:
            connect_args = {
                'charset': 'utf8mb4',
                'use_unicode': True,
         }
            if 'ssl_ca=' in DATABASE_URL:
             connect_args['ssl'] = {'ca': '/etc/ssl/certs/ca-certificates.crt'}
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=280,  
        pool_size=1,       
        max_overflow=0,    
        connect_args=connect_args
    )
    print(f"[DB] Using TiDB: {DATABASE_URL[:60]}...")
else:
    engine = create_engine('sqlite:///messenger.db', echo=False, connect_args={'check_same_thread': False})
    print("[DB] Using SQLite (fallback)")


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
except Exception:
    pass

SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)
Base = declarative_base()

_db_initialized = False
_tables_initialized = False

def check_and_create_tables():
    Base.metadata.create_all(engine, checkfirst=True)
    _migrate_fk_to_cascade()

def _migrate_fk_to_cascade():
    if not DATABASE_URL:
        return
    try:
        fk_migrations = [
            ("push_subscriptions", "user_id",      "users"),
            ("devices",            "user_id",      "users"),
            ("calls",              "caller_id",    "users"),
            ("calls",              "callee_id",    "users"),
            ("notifications",      "user_id",      "users"),
            ("notifications",      "sender_id",    "users"),
            ("messages",           "sender_id",    "users"),
            ("messages",           "recipient_id", "users"),
        ]
        with engine.connect() as conn:
            for table, col, ref_table in fk_migrations:
                try:
                    res = conn.execute(text("""
                        SELECT CONSTRAINT_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = :table
                          AND COLUMN_NAME = :col
                          AND REFERENCED_TABLE_NAME = :ref
                    """), {"table": table, "col": col, "ref": ref_table})
                    for (fk_name,) in res.fetchall():
                        try:
                            conn.execute(text(f"ALTER TABLE {table} DROP FOREIGN KEY {fk_name}"))
                            conn.commit()
                        except Exception:
                            pass
                    on_delete = "SET NULL" if (table == "messages" and col == "recipient_id") else "CASCADE"
                    new_fk_name = f"{table}_{col}_fkey"
                    conn.execute(text(f"""
                        ALTER TABLE {table}
                        ADD CONSTRAINT {new_fk_name}
                        FOREIGN KEY ({col}) REFERENCES {ref_table}(id)
                        ON DELETE {on_delete}
                    """))
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        pass

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    avatar_color = Column(String(20), default='6366f1')
    avatar_url = Column(String(500), nullable=True)
    jt_username = Column(String(50), unique=True, nullable=True)
    bio = Column(String(150), nullable=True, default='')
    last_seen = Column(DateTime, nullable=True)

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    file_type = Column(String(20), nullable=True)
    status = Column(String(20), default='sent')
    duration = Column(String(20), nullable=True)

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    message = Column(String(500), nullable=False)
    type = Column(String(20), default='message')
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

class Call(Base):
    __tablename__ = 'calls'
    id = Column(Integer, primary_key=True)
    call_id = Column(String(100), unique=True, nullable=False, index=True)
    caller_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    callee_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(20), default='ringing')
    offer_data = Column(Text, nullable=True)
    answer_data = Column(Text, nullable=True)
    ice_candidates = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    ended_at = Column(DateTime, nullable=True)

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    device_id = Column(String(100), nullable=False, index=True)
    device_name = Column(String(200), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    last_active = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

class PushSubscription(Base):
    __tablename__ = 'push_subscriptions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    device_id = Column(String(100), nullable=True)
    endpoint = Column(String(191), nullable=False, index=True)
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=utc_now)
    last_used = Column(DateTime, nullable=True)

class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)
    __table_args__ = (UniqueConstraint('user_id', 'contact_id', name='uq_user_contact'),)

def init_db():
    check_and_create_tables()

def reset_db():
    try:
        Base.metadata.drop_all(engine)
    except Exception:
        pass
    Base.metadata.create_all(engine)

def get_db():
    return sessionmaker(bind=engine)()

def init_tables():
    print(f"[DB] init_tables() start")
    print(f"[DB] DATABASE_URL = {(DATABASE_URL or 'NOT SET')[:80]}")
    try:
        with engine.connect() as conn:
            pass
        print("[DB] Connection OK")

        Base.metadata.create_all(engine)
        print("[DB] create_all done")

        with engine.connect() as conn:
            if DATABASE_URL:
                result = conn.execute(text("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name IN ('users', 'messages', 'notifications',
                                         'calls', 'devices', 'push_subscriptions', 'contacts')
                """))
            else:
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master WHERE type='table' AND name IN
                    ('users', 'messages', 'notifications', 'calls', 'devices', 'push_subscriptions', 'contacts')
                """))
            tables = [row[0] for row in result.fetchall()]
            print(f"[DB] Tables found: {tables}")
            if len(tables) < 7:
                print(f"[DB] Only {len(tables)} tables found, expected 7")
                return False
        print("[DB] All tables OK")
        return True
    except Exception as e:
        import traceback
        print(f"[DB] init_tables ERROR: {e}")
        traceback.print_exc()
        return False

def ensure_tables():
    global _tables_initialized
    if _tables_initialized:
        return True
    try:
        with engine.connect() as conn:
            pass
        Base.metadata.create_all(engine)
        _tables_initialized = True
        return True
    except Exception:
        return False

def create_notification(db, user_id, message, sender_id=None, notif_type='message'):
    try:
        notification = Notification(user_id=user_id, sender_id=sender_id, message=message, type=notif_type)
        db.add(notification)
        db.commit()
        return notification
    except Exception:
        db.rollback()
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
    except Exception:
        db.close()
        return None

@app.before_request
def before_request():
    ensure_tables()

@app.errorhandler(Exception)
def handle_exception(e):
    if request.path.startswith('/api/'):
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Server error: ' + str(e)}), 500
    raise e

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'Endpoint not found'}), 404
    raise e

@app.errorhandler(400)
def handle_400(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'Bad request: ' + str(e.description)}), 400
    raise e

def generate_avatar_color():
    import random
    return random.choice(['6366f1', '10b981', 'f59e0b', 'ef4444', '8b5cf6', 'ec4899', '0891b2', '7c3aed'])

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

@app.route('/api/debug-cloudinary')
def api_debug_cloudinary():
    cn = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
    ak = os.environ.get('CLOUDINARY_API_KEY', '')
    asec = os.environ.get('CLOUDINARY_API_SECRET', '')
    return jsonify({
        'cloud_name_set': bool(cn),
        'cloud_name_len': len(cn),
        'cloud_name_last': cn[-4:] if cn else '',
        'api_key_set': bool(ak),
        'api_key_len': len(ak),
        'api_key_last': ak[-4:] if ak else '',
        'api_secret_set': bool(asec),
        'api_secret_len': len(asec),
        'api_secret_last': asec[-4:] if asec else '',
        'is_vercel': bool(os.environ.get('VERCEL')),
        'all_env_keys_with_cloudinary': [k for k in os.environ.keys() if 'CLOUDINARY' in k.upper()]
    })

@app.route('/api/me')
def api_me():
    user = get_current_user()
    if user:
        return jsonify({
            'id': user.id, 'username': user.username,
            'avatar_color': user.avatar_color or '6366f1',
            'avatar_url': user.avatar_url,
            'jt_username': user.jt_username,
            'bio': user.bio or ''
        })
    return jsonify(None)

@app.route('/api/register', methods=['POST'])
def api_register():
    if request.content_type and 'multipart/form-data' in request.content_type:
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        avatar_color = request.form.get('avatar_color', generate_avatar_color())
        avatar_file = request.files.get('avatar_file')
        avatar_data = request.form.get('avatar_data')
    else:
        data = None
        try:
            raw = request.get_data()
            if raw:
                raw_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
                if raw_str.strip():
                    data = json.loads(raw_str)
        except Exception:
            pass
        if not data:
            data = request.get_json(silent=True)
        if not data:
            data = request.get_json(force=True, silent=True)
        if not data:
            data = {}
        name = data.get('name', data.get('username', '')).strip()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        avatar_color = generate_avatar_color()
        avatar_file = None
        avatar_data = None

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
        if avatar_file and CLOUDINARY_CONFIGURED:
            try:
                result = cloudinary_uploader.upload(avatar_file.stream, folder='jtesk/avatars', resource_type='image')
                avatar_url = result['secure_url']
            except Exception:
                pass
        elif avatar_data and CLOUDINARY_CONFIGURED:
            try:
                if avatar_data.startswith('data:'):
                    avatar_data = avatar_data.split(',', 1)[1]
                img_bytes = base64.b64decode(avatar_data)
                import io
                result = cloudinary_uploader.upload(io.BytesIO(img_bytes), folder='jtesk/avatars', resource_type='image')
                avatar_url = result['secure_url']
            except Exception:
                pass
        user = User(
            username=name, password_hash=password_hash,
            avatar_color=avatar_color, avatar_url=avatar_url, jt_username=username
        )
        db.add(user)
        db.commit()
        resp = make_response(jsonify({'success': True, 'user': {
            'id': user.id, 'username': user.username,
            'avatar_color': user.avatar_color or '6366f1',
            'avatar_url': user.avatar_url, 'jt_username': user.jt_username
        }}))
        resp.set_cookie('user_id', str(user.id), max_age=60*60*24*30, samesite='lax')
        return resp
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/login', methods=['POST'])
def api_login():
    data = None
    try:
        raw = request.get_data()
        if raw:
            raw_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            if raw_str.strip():
                data = json.loads(raw_str)
    except Exception:
        pass
    if not data:
        data = request.get_json(silent=True)
    if not data:
        data = request.get_json(force=True, silent=True)
    if not data:
        data = {}

    username = data.get('username', '').strip()
    password = data.get('password', '')
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', '')

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        user = db.query(User).filter_by(username=username).first()
        if not user:
            return jsonify({'success': False, 'message': 'Пользователь не найден'})
        if not user.password_hash:
            return jsonify({'success': False, 'message': 'Неверный пароль'})
        if not check_password_hash(user.password_hash, password):
            return jsonify({'success': False, 'message': 'Неверный пароль'})
        user.last_seen = utc_now()
        db.commit()

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
                        user_id=user.id, device_id=device_id,
                        device_name=device_name[:200] if device_name else None,
                        ip_address=ip, user_agent=ua
                    )
                    db.add(new_device)
                    device_info = new_device
                db.commit()
            except Exception:
                db.rollback()

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
                'id': user.id, 'username': user.username,
                'avatar_color': user.avatar_color or '6366f1',
                'avatar_url': user.avatar_url, 'jt_username': user.jt_username,
                'last_seen': user.last_seen.isoformat() if user.last_seen else None
            },
            'current_device': current_device_data
        }))
        resp.set_cookie('user_id', str(user.id), max_age=60*60*24*30, samesite='lax')
        resp.delete_cookie('username')
        return resp
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
        result = []
        for u in users:
            is_online = False
            last_seen_str = None
            if u.last_seen is not None:
                time_diff = utc_now() - u.last_seen
                is_online = time_diff.total_seconds() < 10
                last_seen_msk = to_msk(u.last_seen)
                last_seen_str = last_seen_msk.strftime('%d.%m %H:%M') if last_seen_msk else None
            unread_count = db.query(Message).filter(
                Message.sender_id == u.id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            ).count()
            result.append({
                'id': u.id, 'username': u.username,
                'avatar_color': u.avatar_color or '6366f1',
                'avatar_url': u.avatar_url, 'jt_username': u.jt_username,
                'bio': u.bio or '',
                'is_online': is_online, 'last_seen': last_seen_str,
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
            msg_status = getattr(m, 'status', 'sent') or 'sent'
            duration = None
            if m.file_type == 'voice':
                if hasattr(m, 'duration') and m.duration:
                    try:
                        dur_sec = int(str(m.duration).replace('s', ''))
                        minutes = dur_sec // 60
                        seconds = dur_sec % 60
                        duration = f'{minutes}:{seconds:02d}'
                    except Exception:
                        duration = '0:00'
                else:
                    duration = '0:00'
            result.append({
                'id': m.id,
                'sender': sender.username if sender else 'Unknown',
                'content': m.content,
                'created_at': to_msk(m.created_at).strftime('%H:%M') if m.created_at else '',
                'is_mine': m.sender_id == user.id,
                'file_type': m.file_type,
                'status': msg_status,
                'duration': duration
            })
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/send', methods=['POST'])
def api_send():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    data = None
    try:
        raw = request.get_data()
        if raw:
            raw_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            if raw_str.strip():
                data = json.loads(raw_str)
    except Exception:
        pass
    if not data:
        data = request.get_json(silent=True)
    if not data:
        data = request.get_json(force=True, silent=True)
    if not data:
        data = {'content': request.form.get('content', ''), 'recipient_id': request.form.get('recipient_id')}
    if not data or not data.get('content', '').strip():
        return jsonify({'success': False, 'message': 'Invalid request format'}), 400
    content = data.get('content', '').strip()
    recipient_id = data.get('recipient_id')
    if not content:
        return jsonify({'success': False, 'message': 'Empty message'})
    db = get_db()
    try:
        msg = Message(
            sender_id=user.id,
            recipient_id=recipient_id if recipient_id else None,
            content=content, status='sent'
        )
        db.add(msg)
        db.commit()
        msg_id = msg.id
        if recipient_id:
            recipient = db.query(User).filter_by(id=recipient_id).first()
            if recipient:
                create_notification(
                    db=db, user_id=recipient_id,
                    message=f"Новое сообщение от {user.username}: {content[:50]}{'...' if len(content) > 50 else ''}",
                    sender_id=user.id, notif_type='message'
                )
                try:
                    send_push_notification(
                        user_id=recipient_id,
                        title=f'💬 {user.username}',
                        body=content[:100],
                        data={'type': 'message', 'message_id': msg_id, 'sender_id': user.id, 'tag': f'msg-{msg_id}'}
                    )
                except Exception:
                    pass
        return jsonify({'success': True, 'id': msg_id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/send-file', methods=['POST'])
def api_send_file():
    ensure_tables()
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    recipient_id = request.form.get('recipient_id')
    file_data = request.form.get('file_data')
    file_type = request.form.get('file_type')
    db = get_db()
    try:
        content = None
        duration = None
        if file_type == 'voice' and 'file' in request.files:
            file = request.files['file']
            if file and file.filename:
                if CLOUDINARY_CONFIGURED:
                    try:
                        upload_result = cloudinary_uploader.upload(
                            file.stream, folder='jtesk/voice',
                            resource_type='video',
                            public_id=f'voice_{user.id}_{int(time.time())}',
                            format='mp3'
                        )
                        content = upload_result['secure_url']
                        if 'duration' in upload_result:
                            duration = str(int(upload_result['duration'])) + 's'
                    except Exception:
                        file.seek(0)
                        file_bytes = file.read()
                        file_base64 = base64.b64encode(file_bytes).decode('utf-8')
                        mime_type = file.content_type if file.content_type else 'audio/webm'
                        if 'webm' in mime_type:
                            mime_type = 'audio/mp4'
                        content = f'data:{mime_type};base64,{file_base64}'
                else:
                    file_bytes = file.read()
                    file_base64 = base64.b64encode(file_bytes).decode('utf-8')
                    mime_type = file.content_type if file.content_type else 'audio/webm'
                    content = f'data:{mime_type};base64,{file_base64}'
            else:
                return jsonify({'success': False, 'message': 'No file uploaded'})
        elif file_data:
            if len(file_data) > 20 * 1024 * 1024:
                return jsonify({'success': False, 'message': 'File too large (max 20MB)'})
            if not file_data.startswith('data:'):
                return jsonify({'success': False, 'message': 'Invalid file format'})
            content = file_data
        else:
            return jsonify({'success': False, 'message': 'No file data'})
        msg = Message(
            sender_id=user.id,
            recipient_id=recipient_id if recipient_id else None,
            content=content, file_type=file_type,
            status='sent', duration=duration
        )
        db.add(msg)
        db.commit()
        if recipient_id:
            try:
                recipient = db.query(User).filter_by(id=int(recipient_id)).first()
                if recipient:
                    notif_message = f"Голосовое сообщение от {user.username}" if file_type == 'voice' else f"Новое фото от {user.username}"
                    create_notification(db=db, user_id=int(recipient_id), message=notif_message, sender_id=user.id, notif_type='message')
            except Exception:
                pass
        return jsonify({'success': True, 'id': msg.id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/logout')
def api_logout():
    user_id = request.cookies.get('user_id')
    if user_id:
        db = get_db()
        try:
            user = db.query(User).filter_by(id=int(user_id)).first()
            if user:
                user.last_seen = utc_now()
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('user_id')
    resp.delete_cookie('username')
    return resp

@app.route('/api/keepalive')
def api_keepalive():
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/api/delete-message', methods=['POST'])
@app.route('/api/messages/<int:message_id>', methods=['DELETE'])
def api_delete_message(message_id=None):
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401
        if message_id is None:
            raw_data = request.get_data(as_text=True)
            try:
                data = json.loads(raw_data) if raw_data else {}
            except json.JSONDecodeError:
                data = {}
            message_id = data.get('message_id')
        if not message_id:
            return jsonify({'success': False, 'message': 'No message_id'}), 400
        db = get_db()
        try:
            msg = db.query(Message).filter_by(id=int(message_id)).first()
            if not msg:
                return jsonify({'success': False, 'message': 'Message not found'}), 404
            if msg.sender_id != user.id:
                return jsonify({'success': False, 'message': 'Not your message'}), 403
            db.delete(msg)
            db.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500
        finally:
            db.close()
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings/clear-messages', methods=['POST'])
def api_clear_messages():
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

@app.route('/api/notifications')
def api_notifications():
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
                'id': n.id, 'message': n.message, 'type': n.type,
                'is_read': bool(n.is_read),
                'created_at': to_msk(n.created_at).strftime('%H:%M') if n.created_at else '',
                'sender': {'id': sender.id, 'username': sender.username, 'avatar_color': sender.avatar_color} if sender else None
            })
        return jsonify(result)
    except Exception:
        return jsonify([])
    finally:
        db.close()

@app.route('/api/notifications/unread')
def api_notifications_unread():
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

@app.route('/api/settings/change-bio', methods=['POST'])
def api_change_bio():
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401
        data = None
        try:
            raw = request.get_data()
            if raw:
                raw_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
                if raw_str.strip():
                    data = json.loads(raw_str)
        except Exception:
            pass
        if not data:
            try:
                data = request.get_json(force=True)
            except Exception:
                pass
        if not data:
            data = request.get_json(silent=True)
        if not data:
            bio_val = request.form.get('bio', request.form.get('text', ''))
            if bio_val is not None:
                data = {'bio': bio_val}
        if not data:
            return jsonify({'success': False, 'message': 'No data received.'}), 400
        bio = str(data.get('bio') or data.get('text', '')).strip()[:150]
        db = get_db()
        try:
            db.execute(text("UPDATE users SET bio = :bio WHERE id = :uid"), {'bio': bio, 'uid': user.id})
            db.commit()
        except Exception as col_err:
            db.rollback()
            if 'bio' in str(col_err).lower() or 'column' in str(col_err).lower():
                db.execute(text("ALTER TABLE users ADD COLUMN bio VARCHAR(150) NULL DEFAULT NULL"))
                db.commit()
                db.execute(text("UPDATE users SET bio = :bio WHERE id = :uid"), {'bio': bio, 'uid': user.id})
                db.commit()
            else:
                raise
        db.close()
        return jsonify({'success': True, 'bio': bio})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings/change-username', methods=['POST'])
def api_change_username():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    data = request.json
    new_username = data.get('username', '').strip()
    if not new_username or len(new_username) < 2:
        return jsonify({'success': False, 'message': 'Имя должно быть не менее 2 символов'})
    if len(new_username) > 50:
        return jsonify({'success': False, 'message': 'Имя слишком длинное'})
    db = get_db()
    try:
        existing = db.query(User).filter_by(username=new_username).first()
        if existing and existing.id != user.id:
            db.close()
            return jsonify({'success': False, 'message': 'Это имя уже занято'})
        user.username = new_username
        db.commit()
        db.close()
        resp = make_response(jsonify({'success': True, 'username': new_username, 'id': user.id}))
        resp.delete_cookie('username')
        return resp
    except Exception as e:
        db.rollback()
        db.close()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/last-messages')
def api_last_messages():
    user = get_current_user()
    if not user:
        return jsonify([])
    db = get_db()
    try:
        msgs = db.query(Message).filter(
            or_(
                and_(Message.sender_id == user.id, Message.recipient_id.isnot(None)),
                and_(Message.recipient_id == user.id, Message.sender_id.isnot(None))
            )
        ).order_by(Message.created_at.desc()).all()
        last_messages = {}
        for msg in msgs:
            partner_id = msg.recipient_id if msg.sender_id == user.id else msg.sender_id
            if partner_id not in last_messages:
                last_messages[partner_id] = msg
        result = []
        for partner_id, msg in last_messages.items():
            sender = db.query(User).filter_by(id=msg.sender_id).first()
            unread_count = db.query(Message).filter(
                Message.sender_id == partner_id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            ).count()
            duration = None
            if msg.file_type == 'voice':
                if hasattr(msg, 'duration') and msg.duration:
                    try:
                        dur_sec = int(str(msg.duration).replace('s', ''))
                        minutes = dur_sec // 60
                        seconds = dur_sec % 60
                        duration = f'{minutes}:{seconds:02d}'
                    except Exception:
                        duration = '0:00'
                else:
                    duration = '0:00'
            result.append({
                'id': msg.id, 'sender': sender.username if sender else 'Unknown',
                'sender_id': msg.sender_id, 'recipient_id': msg.recipient_id,
                'content': msg.content,
                'created_at': to_msk(msg.created_at).strftime('%H:%M') if msg.created_at else '',
                'file_type': msg.file_type,
                'status': getattr(msg, 'status', 'sent') or 'sent',
                'unread_count': unread_count, 'duration': duration
            })
        return jsonify(result)
    except Exception:
        return jsonify([])
    finally:
        db.close()

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False})
    db = get_db()
    try:
        user = db.query(User).filter_by(id=int(user_id)).first()
        if user:
            user.last_seen = utc_now()
            db.commit()
        device_id = request.json.get('device_id', '') if request.is_json else ''
        if device_id and user:
            try:
                device = db.query(Device).filter_by(user_id=user.id, device_id=device_id).first()
                if device:
                    device.last_active = utc_now()
                    db.commit()
            except Exception:
                db.rollback()
        return jsonify({'success': True, 'user_id': user_id})
    except Exception:
        db.rollback()
        return jsonify({'success': False})
    finally:
        db.close()

@app.route('/api/messages/mark-read', methods=['POST'])
def api_mark_read():
    user = get_current_user()
    if not user:
        return jsonify({'success': False})
    data = request.json
    sender_id = data.get('sender_id')
    if not sender_id:
        return jsonify({'success': False, 'message': 'No sender_id'})
    db = get_db()
    try:
        db.query(Message).filter(
            Message.sender_id == sender_id,
            Message.recipient_id == user.id,
            Message.status != 'read'
        ).update({'status': 'read'}, synchronize_session=False)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/settings/delete-account', methods=['POST'])
def api_delete_account():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401
    user_id = user.id
    try:
        conn = engine.connect()
        try:
            if DATABASE_URL:
                fk_list = conn.execute(text("""
                    SELECT CONSTRAINT_NAME, TABLE_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE REFERENCED_TABLE_SCHEMA = DATABASE()
                      AND REFERENCED_TABLE_NAME = 'users'
                """)).fetchall()
                for fk_name, tbl in fk_list:
                    try:
                        conn.execute(text(f"ALTER TABLE `{tbl}` DROP FOREIGN KEY `{fk_name}`"))
                        conn.commit()
                    except Exception:
                        pass
            for sql in [
                "DELETE FROM contacts           WHERE user_id = :uid OR contact_id = :uid",
                "DELETE FROM push_subscriptions WHERE user_id = :uid",
                "DELETE FROM devices            WHERE user_id = :uid",
                "DELETE FROM calls              WHERE caller_id = :uid OR callee_id = :uid",
                "DELETE FROM notifications      WHERE user_id = :uid OR sender_id = :uid",
                "DELETE FROM messages           WHERE sender_id = :uid OR recipient_id = :uid",
                "DELETE FROM users              WHERE id = :uid",
            ]:
                conn.execute(text(sql), {"uid": user_id})
                conn.commit()
        finally:
            conn.close()
        resp = make_response(jsonify({'success': True}))
        resp.set_cookie('user_id', '', max_age=0)
        return resp
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/username/check', methods=['POST'])
def api_username_check():
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
        return jsonify({'available': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/username/set', methods=['POST'])
def api_username_set():
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Not authorized'})
    data = request.json
    jt_username = data.get('jt_username', '').strip()
    if jt_username.startswith('@'):
        jt_username = jt_username[1:]
    db = get_db()
    try:
        user = db.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})
        if not jt_username:
            user.jt_username = None
            db.commit()
            return jsonify({'success': True, 'jt_username': None})
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]{4,31}$', jt_username):
            return jsonify({'success': False, 'message': 'Неверный формат'})
        if '..' in jt_username or '__' in jt_username:
            return jsonify({'success': False, 'message': 'Не может содержать подряд идущие точки/подчёркивания'})
        if jt_username.endswith('.') or jt_username.endswith('_'):
            return jsonify({'success': False, 'message': 'Не может заканчиваться на точку/подчёркивание'})
        existing = db.query(User).filter_by(jt_username=jt_username).first()
        if existing and existing.id != user.id:
            return jsonify({'success': False, 'message': 'Этот @username уже занят'})
        user.jt_username = jt_username
        db.commit()
        return jsonify({'success': True, 'jt_username': jt_username})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/upload-avatar', methods=['POST'])
def api_upload_avatar():
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        user = db.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})
        if 'avatar' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'})
        file = request.files['avatar']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'})
        filename = file.filename if file.filename else 'unknown.png'
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            return jsonify({'success': False, 'message': 'Неверный формат'})

        file_data = file.read()
        avatar_url = None
        cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
        upload_preset = os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'avatars_unsigned')

        if cloud_name:
            try:
                upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
                files = {'file': ('avatar' + ext, file_data)}
                data = {
                    'upload_preset': upload_preset,
                    'folder': 'avatars',
                    'public_id': f"user_{user.id}_{uuid.uuid4().hex[:8]}"
                }
                resp = requests.post(upload_url, files=files, data=data, timeout=30)
                if resp.status_code == 200:
                    result = resp.json()
                    avatar_url = result.get('secure_url', '')
                    if avatar_url:
                        avatar_url = avatar_url.replace('/upload/', '/upload/w_200,h_200,c_fill,g_face/', 1)
                else:
                    print(f"[Cloudinary] Upload failed: {resp.status_code} {resp.text[:300]}")
                    return jsonify({'success': False, 'message': f'Cloudinary: {resp.text[:200]}'})
            except Exception as e:
                print(f"[Cloudinary] Exception: {e}")
                return jsonify({'success': False, 'message': f'Cloudinary error: {str(e)}'})
        else:
            filename_save = f"avatar_{user.id}_{uuid.uuid4().hex[:8]}{ext}"
            upload_dir = os.path.join(os.path.dirname(__file__), 'avatars')
            try:
                os.makedirs(upload_dir, exist_ok=True)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Error creating dir: {str(e)}'})
            avatar_path = os.path.join(upload_dir, filename_save)
            with open(avatar_path, 'wb') as f:
                f.write(file_data)
            avatar_url = f"/avatars/{filename_save}"

        user.avatar_url = avatar_url
        db.commit()
        return jsonify({'success': True, 'avatar_url': avatar_url})
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/avatars/<filename>')
def serve_avatar(filename):
    avatar_dir = os.path.join(os.path.dirname(__file__), 'avatars')
    return send_from_directory(avatar_dir, filename, mimetype='image')

@app.route('/Jetesk.png')
def serve_jetesk():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'Jetesk.png', mimetype='image/png')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'manifest.json', mimetype='application/json')

@app.route('/styles.css')
def serve_styles():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'styles.css', mimetype='text/css')

@app.route('/main.js')
def serve_main_js():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'main.js', mimetype='application/javascript')

@app.route('/rington.mp3')
def serve_rington():
    return send_from_directory(os.path.abspath(os.path.dirname(__file__)), 'rington.mp3', mimetype='audio/mpeg')

def send_push_notification(user_id, title, body, data=None):
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return {'sent': 0, 'failed': 0}
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {'sent': 0, 'failed': 0}
    db = get_db()
    try:
        subs = db.query(PushSubscription).filter_by(user_id=user_id).all()
        if not subs:
            return {'sent': 0, 'failed': 0}
    except Exception:
        return {'sent': 0, 'failed': 0}
    sent = 0
    failed = 0
    for sub in subs:
        try:
            subscription_info = {
                'endpoint': sub.endpoint,
                'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}
            }
            payload = json.dumps({
                'title': title, 'body': body,
                'icon': '/Jetesk.png', 'badge': '/Jetesk.png',
                'vibrate': [500, 200, 500, 200, 500],
                'tag': data.get('tag', 'jetesk-call') if data else 'jetesk-notification',
                'requireInteraction': True, 'renotify': True, 'data': data or {}
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
            try:
                db.delete(sub)
                db.commit()
            except Exception:
                pass
        except Exception:
            failed += 1
    return {'sent': sent, 'failed': failed}

@app.route('/api/push/vapid-public-key', methods=['GET'])
def api_push_vapid_key():
    return jsonify({'public_key': VAPID_PUBLIC_KEY})

@app.route('/api/push/subscribe', methods=['POST'])
def api_push_subscribe():
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
        existing = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
        if existing:
            existing.user_id = user.id
            existing.device_id = device_id
            existing.last_used = utc_now()
            db.commit()
            return jsonify({'success': True, 'message': 'Updated'})
        sub = PushSubscription(
            user_id=user.id, device_id=device_id,
            endpoint=endpoint, p256dh=p256dh, auth=auth
        )
        db.add(sub)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/push/unsubscribe', methods=['POST'])
def api_push_unsubscribe():
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
            db.query(PushSubscription).filter_by(user_id=user.id).delete()
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/contacts')
def api_contacts():
    user = get_current_user()
    if not user:
        return jsonify([])
    db = get_db()
    try:
        contact_rows = db.query(Contact).filter_by(user_id=user.id).all()
        result = []
        for c in contact_rows:
            u = db.query(User).filter_by(id=c.contact_id).first()
            if not u:
                continue
            is_online = False
            last_seen_str = None
            if u.last_seen is not None:
                is_online = (utc_now() - u.last_seen).total_seconds() < 10
                last_seen_msk = to_msk(u.last_seen)
                last_seen_str = last_seen_msk.strftime('%d.%m %H:%M') if last_seen_msk else None
            unread_count = db.query(Message).filter(
                Message.sender_id == u.id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            ).count()
            result.append({
                'id': u.id, 'username': u.username,
                'avatar_color': u.avatar_color or '6366f1',
                'avatar_url': u.avatar_url, 'jt_username': u.jt_username,
                'bio': u.bio or '',
                'is_online': is_online, 'last_seen': last_seen_str,
                'unread_count': unread_count
            })
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/contacts/add', methods=['POST'])
def api_contacts_add():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401
    data = request.json or {}
    contact_id = data.get('contact_id')
    if not contact_id or int(contact_id) == user.id:
        return jsonify({'success': False, 'message': 'Invalid contact_id'})
    db = get_db()
    try:
        existing = db.query(Contact).filter_by(user_id=user.id, contact_id=int(contact_id)).first()
        if existing:
            return jsonify({'success': True, 'already': True})
        c = Contact(user_id=user.id, contact_id=int(contact_id))
        db.add(c)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
def api_contacts_delete(contact_id):
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'}), 401
    db = get_db()
    try:
        db.query(Contact).filter_by(user_id=user.id, contact_id=contact_id).delete()
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/contacts/check/<int:contact_id>')
def api_contacts_check(contact_id):
    user = get_current_user()
    if not user:
        return jsonify({'is_contact': False})
    db = get_db()
    try:
        exists = db.query(Contact).filter_by(user_id=user.id, contact_id=contact_id).first()
        return jsonify({'is_contact': bool(exists)})
    finally:
        db.close()

@app.route('/api/devices', methods=['GET'])
def api_devices():
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
                'id': d.id, 'device_id': d.device_id,
                'device_name': d.device_name or 'Неизвестное устройство',
                'ip_address': d.ip_address or 'Unknown',
                'last_active': last_active_msk.strftime('%d.%m.%Y %H:%M') if last_active_msk else 'Неизвестно',
                'is_current': True
            })
        return jsonify(result)
    except Exception:
        return jsonify([])
    finally:
        db.close()

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def api_device_delete(device_id):
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
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/offer', methods=['POST'])
def api_call_offer():
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        call_id = data.get('call_id')
        to_user_id = data.get('to_user_id')
        offer = data.get('offer')
        if not call_id or not to_user_id or not offer:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400
        callee = db.query(User).filter_by(id=int(to_user_id)).first()
        if not callee:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            call = Call(
                call_id=call_id, caller_id=int(user_id), callee_id=int(to_user_id),
                status='ringing', offer_data=json.dumps(offer)
            )
            db.add(call)
        else:
            call.offer_data = json.dumps(offer)
            call.status = 'ringing'
        db.commit()
        caller = db.query(User).filter_by(id=int(user_id)).first()
        caller_name = caller.username if caller else 'Неизвестный'
        try:
            send_push_notification(
                user_id=int(to_user_id),
                title='📞 Входящий звонок',
                body=f'{caller_name} звонит вам...',
                data={
                    'type': 'incoming_call', 'call_id': call_id,
                    'from_user_id': int(user_id), 'from_user_name': caller_name,
                    'tag': f'call-{call_id}'
                }
            )
        except Exception:
            pass
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/status/<call_id>', methods=['GET'])
def api_call_status(call_id):
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'status': 'not_found'}), 404
        result = {'status': call.status}
        if call.answer_data:
            try:
                result['answer'] = json.loads(call.answer_data)
            except Exception:
                pass
        return jsonify(result)
    except Exception:
        return jsonify({'status': 'error'}), 500
    finally:
        db.close()

@app.route('/api/call/check/<call_id>', methods=['GET'])
def api_call_check(call_id):
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'status': 'not_found'}), 404
        return jsonify({'status': call.status})
    except Exception:
        return jsonify({'status': 'error'}), 500
    finally:
        db.close()

@app.route('/api/call/ice', methods=['POST'])
def api_call_ice():
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authorized'}), 401
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        call_id = data.get('call_id')
        candidate = data.get('candidate')
        if not call_id or not candidate:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'success': False, 'message': 'Call not found'}), 404
        candidates = []
        if call.ice_candidates:
            try:
                candidates = json.loads(call.ice_candidates)
            except Exception:
                candidates = []
        candidates.append(candidate)
        call.ice_candidates = json.dumps(candidates)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/incoming', methods=['GET'])
def api_call_incoming():
    db = get_db()
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({}), 200
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
    except Exception:
        return jsonify({}), 500
    finally:
        db.close()

@app.route('/api/call/accept', methods=['POST'])
def api_call_accept():
    db = get_db()
    try:
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        call_id = data.get('call_id')
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'success': False, 'message': 'Call not found'}), 404
        call.status = 'accepted'
        db.commit()
        return jsonify({
            'success': True,
            'offer': json.loads(call.offer_data) if call.offer_data else None
        })
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/answer', methods=['POST'])
def api_call_answer():
    db = get_db()
    try:
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
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
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/reject', methods=['POST'])
def api_call_reject():
    db = get_db()
    try:
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        call_id = data.get('call_id')
        call = db.query(Call).filter_by(call_id=call_id).first()
        if call:
            call.status = 'rejected'
            call.ended_at = utc_now()
            db.commit()
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
                        file_type='call_missed', status='read'
                    )
                    db.add(msg)
                    db.commit()
            except Exception:
                pass
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/call/ice/<call_id>', methods=['GET'])
def api_call_ice_poll(call_id):
    db = get_db()
    try:
        call = db.query(Call).filter_by(call_id=call_id).first()
        if not call:
            return jsonify({'candidates': []}), 200
        candidates = []
        if call.ice_candidates:
            try:
                candidates = json.loads(call.ice_candidates)
            except Exception:
                candidates = []
        return jsonify({'candidates': candidates})
    except Exception:
        return jsonify({'candidates': []}), 500
    finally:
        db.close()

@app.route('/api/call/end', methods=['POST'])
def api_call_end():
    db = get_db()
    try:
        data = request.get_json(silent=True)
        if not data:
            try:
                raw = request.get_data()
                if raw:
                    data = json.loads(raw.decode('utf-8'))
            except Exception:
                pass
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        call_id = data.get('call_id')
        call = db.query(Call).filter_by(call_id=call_id).first()
        if call:
            was_ringing = call.status == 'ringing'
            if was_ringing:
                try:
                    caller = db.query(User).filter_by(id=call.caller_id).first()
                    caller_name = caller.username if caller else 'Неизвестный'
                    msg = Message(
                        sender_id=int(call.caller_id),
                        recipient_id=int(call.callee_id),
                        content=f'__CALL_MISSED__:{caller_name}',
                        created_at=utc_now(),
                        file_type='call_missed', status='read'
                    )
                    db.add(msg)
                except Exception:
                    pass
            call.status = 'ended'
            call.ended_at = utc_now()
            db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--reset-db':
        reset_db()
        sys.exit(0)
    app.run(host='0.0.0.0', port=5000, debug=True)