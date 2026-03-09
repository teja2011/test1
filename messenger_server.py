from flask import Flask, render_template_string, request, jsonify, redirect, make_response
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, or_, and_, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import secrets
import os
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
        with engine.connect() as conn:
            # Проверяем существование таблицы users
            if DATABASE_URL:
                # PostgreSQL
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'messages'
                    );
                """))
            else:
                # SQLite
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='messages';
                """))

            tables_exist = result.fetchone()
            tables_found = False

            if tables_exist:
                if isinstance(tables_exist[0], bool):
                    tables_found = tables_exist[0]
                elif isinstance(tables_exist[0], str):
                    tables_found = len(tables_exist[0]) > 0
                elif isinstance(tables_exist[0], int):
                    tables_found = tables_exist[0] > 0

            if not tables_found:
                print("Таблицы не найдены. Создаю...")
                Base.metadata.create_all(engine)
                print("Таблицы созданы: users, messages, notifications")
            else:
                print("Таблицы существуют")
                
            # Проверяем и добавляем колонку status в messages
            if DATABASE_URL:
                # PostgreSQL - проверяем наличие колонки status
                col_check = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = 'messages'
                        AND column_name = 'status'
                    );
                """)).fetchone()
                
                if not (isinstance(col_check[0], bool) and col_check[0]):
                    print("Добавляю колонку status в messages...")
                    conn.execute(text("ALTER TABLE messages ADD COLUMN status VARCHAR(20) DEFAULT 'sent'"))
                    conn.commit()
                    print("Колонка status добавлена")
            else:
                # SQLite - проверяем наличие колонки status
                col_check = conn.execute(text("PRAGMA table_info(messages)")).fetchall()
                has_status = any(col[1] == 'status' for col in col_check)
                
                if not has_status:
                    print("Добавляю колонку status в messages...")
                    conn.execute(text("ALTER TABLE messages ADD COLUMN status VARCHAR(20) DEFAULT 'sent'"))
                    conn.commit()
                    print("Колонка status добавлена")
                    
    except Exception as e:
        print(f"Ошибка проверки таблиц: {e}")
        print("Пытаюсь создать таблицы...")
        try:
            Base.metadata.create_all(engine)
            print("Таблицы созданы")
        except Exception as create_error:
            print(f"Не удалось создать таблицы: {create_error}")
            raise

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    avatar_color = Column(String(20), default='6366f1')

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    content = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    file_type = Column(String(20), nullable=True)  # 'image', 'file', или None для текста
    status = Column(String(20), default='sent')  # 'sending', 'sent', 'delivered', 'read'

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    message = Column(String(500), nullable=False)
    type = Column(String(20), default='message')  # 'message', 'system', 'mention'
    is_read = Column(Integer, default=0)  # 0 = не прочитано, 1 = прочитано
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
            result.append({
                'id': m.id,
                'sender': sender.username if sender else 'Unknown',
                'content': m.content,
                'created_at': m.created_at.strftime('%H:%M'),
                'is_mine': m.sender_id == user.id,
                'file_type': m.file_type,
                'status': m.status or 'sent'
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
        msg = Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content, status='sent')
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
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/messages/mark-read', methods=['POST'])
def api_messages_mark_read():
    """Отметить сообщения как прочитанные"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    
    data = request.json
    sender_id = data.get('sender_id')  # ID отправителя, чьи сообщения читаем
    
    if not sender_id:
        return jsonify({'success': False, 'message': 'No sender_id'})
    
    db = get_db()
    try:
        # Обновляем все сообщения от этого пользователя этому пользователю
        db.query(Message).filter(
            and_(
                Message.sender_id == sender_id,
                Message.recipient_id == user.id,
                Message.status != 'read'
            )
        ).update({'status': 'read'})
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
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
        # Сохраняем файл в сообщении как base64
        msg = Message(
            sender_id=user.id,
            recipient_id=recipient_id if recipient_id else None,
            content=file_data,
            file_type=file_type,
            status='sent'
        )
        db.add(msg)
        db.commit()
        return jsonify({'success': True, 'id': msg.id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
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
        resp.delete_cookie('username')  # На всякий случай
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