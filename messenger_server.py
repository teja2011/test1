from flask import Flask, render_template_string, request, jsonify, redirect, make_response, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, or_, and_, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import secrets
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import smtplib

# Настройка БД - Neon PostgreSQL или SQLite
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
else:
    engine = create_engine('sqlite:///messenger.db', echo=False, connect_args={'check_same_thread': False})

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
    created_at = Column(DateTime, default=datetime.now)
    avatar_color = Column(String(20), default='6366f1')
    avatar_url = Column(String(500), nullable=True)  # URL аватарки (хранит путь к файлу)
    jt_username = Column(String(50), unique=True, nullable=True)  # @username как в Telegram
    last_seen = Column(DateTime, nullable=True)  # Время последнего посещения

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    content = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    file_type = Column(String(20), nullable=True)  
    status = Column(String(20), default='sent') 

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    message = Column(String(500), nullable=False)
    type = Column(String(20), default='message') 
    is_read = Column(Integer, default=0)  
    created_at = Column(DateTime, default=datetime.now)

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

# ============================================
# СОЗДАЁМ ТАБЛИЦЫ ПРИ ЗАГРУЗКЕ МОДУЛЯ
# ============================================
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
                    WHERE table_schema = 'public' AND table_name IN ('users', 'messages', 'notifications')
                """))
            else:
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'messages', 'notifications')
                """))
            tables = [row[0] for row in result.fetchall()]
            print(f"Созданы таблицы: {', '.join(tables)}")
            
            if len(tables) < 3:
                raise Exception(f"Не все таблицы созданы! Найдено: {len(tables)}, ожидается: 3")
                
        print("=== БД готова к работе ===")
        return True
    except Exception as e:
        print(f"❌ ОШИБКА создания таблиц: {e}")
        print(f"DATABASE_URL: {DATABASE_URL or 'SQLite (messenger.db)'}")
        return False

# Инициализируем таблицы при загрузке
if not init_tables():
    print("ВНИМАНИЕ: Сервер запущен с ошибками БД. Проверьте подключение!")

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

@app.route('/sw.js')
def serve_sw():
    """Раздача Service Worker"""
    return send_from_directory('.', 'sw.js', mimetype='application/javascript')

@app.route('/api/me')
def api_me():
    user = get_current_user()
    if user:
        print(f"[API /me] User: {user.id}, {user.username}, avatar_url: {user.avatar_url}")
        return jsonify({'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color or '6366f1', 'avatar_url': user.avatar_url, 'jt_username': user.jt_username})
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
        existing = db.query(User).filter_by(username=username).first()
        if existing:
            return jsonify({'success': False, 'message': 'Пользователь уже существует'})
        
        password_hash = generate_password_hash(password)
        print(f"password_hash сгенерирован: {password_hash[:50]}...")
        
        user = User(username=username, password_hash=password_hash, avatar_color=generate_avatar_color())
        db.add(user)
        db.commit()
        
        print(f"Пользователь создан: id={user.id}, username={user.username}")
        print(f"password_hash в БД: {user.password_hash[:50] if user.password_hash else 'NULL'}...")

        resp = make_response(jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color}}))
        resp.set_cookie('user_id', str(user.id), max_age=60*60*24*30, samesite='lax')
        resp.delete_cookie('username')  # Удаляем старый cookie
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

    print(f"=== ВХОД ===")
    print(f"Username: {username}")
    print(f"Password получен: {'да' if password else 'нет'}")

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
        resp = make_response(jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color}}))
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
        return jsonify([{'id': u.id, 'username': u.username, 'avatar_color': u.avatar_color or '6366f1'} for u in users])
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
            result.append({
                'id': m.id,
                'sender': sender.username if sender else 'Unknown',
                'content': m.content,
                'created_at': m.created_at.strftime('%H:%M'),
                'is_mine': m.sender_id == user.id,
                'file_type': m.file_type,
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
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})

    recipient_id = request.form.get('recipient_id')
    file_data = request.form.get('file_data')  # Base64 данные
    file_type = request.form.get('file_type')  # 'image' или 'file'

    if not file_data:
        return jsonify({'success': False, 'message': 'No file data'})

    db = get_db()
    try:
        # Пробуем со статусом
        try:
            msg = Message(
                sender_id=user.id,
                recipient_id=recipient_id if recipient_id else None,
                content=file_data,
                file_type=file_type,
                status='sent'
            )
            db.add(msg)
            db.commit()
        except:
            # Если колонки status нет - без статуса
            db.rollback()
            msg = Message(
                sender_id=user.id,
                recipient_id=recipient_id if recipient_id else None,
                content=file_data,
                file_type=file_type
            )
            db.add(msg)
            db.commit()
        
        return jsonify({'success': True, 'id': msg.id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        print(f"Ошибка отправки файла: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/logout')
def api_logout():
    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('user_id')
    resp.delete_cookie('username')  # На всякий случай
    return resp

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
                'created_at': n.created_at.strftime('%H:%M'),
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
            result.append({
                'id': msg.id,
                'sender': sender.username if sender else 'Unknown',
                'sender_id': msg.sender_id,
                'recipient_id': msg.recipient_id,
                'content': msg.content,
                'created_at': msg.created_at.strftime('%H:%M'),
                'file_type': msg.file_type,
                'status': getattr(msg, 'status', 'sent') or 'sent'
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
    user = get_current_user()
    if not user:
        return jsonify({'success': False})
    return jsonify({'success': True, 'user_id': user.id})

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
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    
    data = request.json
    jt_username = data.get('jt_username', '').strip()
    
    # Удаляем @ в начале если есть
    if jt_username.startswith('@'):
        jt_username = jt_username[1:]
    
    if not jt_username:
        # Пустой - удаляем
        db = get_db()
        try:
            user.jt_username = None
            db.commit()
            return jsonify({'success': True, 'jt_username': None})
        except Exception as e:
            db.rollback()
            return jsonify({'success': False, 'message': str(e)})
        finally:
            db.close()
    
    # Проверка валидности: 5-32 символа, латиница, цифры, _
    import re
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', jt_username):
        return jsonify({'success': False, 'message': 'Неверный формат. 5-32 символа, начинается с буквы (a-z), цифры и _'})
    
    db = get_db()
    try:
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
    
    user = get_current_user()
    if not user:
        print(f"[Avatar] User not authorized (user_id={request.cookies.get('user_id')})")
        return jsonify({'success': False, 'message': 'Not authorized'})

    print(f"[Avatar] Upload request from user {user.id} ({user.username})")
    
    if 'avatar' not in request.files:
        print(f"[Avatar] No file in request")
        return jsonify({'success': False, 'message': 'No file provided'})

    file = request.files['avatar']
    if file.filename == '':
        print(f"[Avatar] Empty filename")
        return jsonify({'success': False, 'message': 'No file selected'})

    # Генерируем уникальное имя файла
    import os
    import uuid
    ext = os.path.splitext(file.filename)[1].lower()
    print(f"[Avatar] File: {file.filename}, ext: {ext}")
    
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        return jsonify({'success': False, 'message': 'Неверный формат. Разрешены: jpg, png, gif, webp'})

    filename = f"avatar_{user.id}_{uuid.uuid4().hex[:8]}{ext}"

    # Сохраняем файл
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
        file.save(avatar_path)
        print(f"[Avatar] File saved successfully")
    except Exception as e:
        print(f"[Avatar] Error saving file: {e}")
        return jsonify({'success': False, 'message': f'Error saving file: {str(e)}'})
    
    avatar_url = f"/avatars/{filename}"

    # Сохраняем путь в БД
    db = get_db()
    try:
        print(f"[Avatar] Updating database: user_id={user.id}, avatar_url={avatar_url}")
        user.avatar_url = avatar_url
        db.commit()
        print(f"[Avatar] Success! Avatar URL: {avatar_url}")
        return jsonify({'success': True, 'avatar_url': avatar_url})
    except Exception as e:
        db.rollback()
        print(f"[Avatar] Error saving to DB: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/avatars/<filename>')
def serve_avatar(filename):
    """Раздача аватарок"""
    import os
    avatar_dir = os.path.join(os.path.dirname(__file__), 'avatars')
    return send_from_directory(avatar_dir, filename, mimetype='image')

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