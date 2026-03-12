from flask import Flask, render_template_string, request, jsonify, redirect, make_response, send_from_directory
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, or_, and_, text, Index
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timedelta, timezone
import secrets
import os
import time
import hashlib
import json
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import smtplib
from threading import Lock
from collections import OrderedDict

# Получаем директорию текущего файла
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Настройка БД - Neon PostgreSQL или SQLite
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20)
else:
    engine = create_engine('sqlite:///messenger.db', echo=False, connect_args={'check_same_thread': False})

SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app = Flask(__name__, static_folder=CURRENT_DIR, static_url_path='')
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)
Base = declarative_base()

# Флаг для отслеживания инициализации БД
_db_initialized = False

# ============================================
# СИСТЕМА КЭШИРОВАНИЯ (In-Memory LRU Cache)
# ============================================

class LRUCache:
    """Простой LRU кэш для хранения данных в памяти"""
    
    def __init__(self, max_size=100, default_ttl=300):
        self.cache = OrderedDict()
        self.timestamps = {}
        self.ttls = {}
        self.max_size = max_size
        self.default_ttl = default_ttl  # TTL по умолчанию (5 минут)
        self.lock = Lock()
    
    def _generate_key(self, prefix, key):
        """Генерирует уникальный ключ кэша"""
        key_str = f"{prefix}:{key}" if key else prefix
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def get(self, prefix, key=None):
        """Получение данных из кэша"""
        cache_key = self._generate_key(prefix, key)
        
        with self.lock:
            if cache_key not in self.cache:
                return None
            
            # Проверка TTL
            if time.time() > self.ttls.get(cache_key, 0):
                self._delete_unlocked(cache_key)
                return None
            
            # Перемещаем в конец (LRU)
            self.cache.move_to_end(cache_key)
            return self.cache[cache_key]
    
    def set(self, prefix, value, key=None, ttl=None):
        """Сохранение данных в кэш"""
        cache_key = self._generate_key(prefix, key)
        ttl = ttl if ttl is not None else self.default_ttl
        
        with self.lock:
            # Удаляем старый ключ если есть
            if cache_key in self.cache:
                del self.cache[cache_key]
            
            # Добавляем новый
            self.cache[cache_key] = value
            self.timestamps[cache_key] = time.time()
            self.ttls[cache_key] = time.time() + ttl
            
            # Удаляем oldest если превышен лимит
            while len(self.cache) > self.max_size:
                oldest_key = next(iter(self.cache))
                self._delete_unlocked(oldest_key)
    
    def _delete_unlocked(self, cache_key):
        """Удаление ключа (без блокировки)"""
        if cache_key in self.cache:
            del self.cache[cache_key]
        if cache_key in self.timestamps:
            del self.timestamps[cache_key]
        if cache_key in self.ttls:
            del self.ttls[cache_key]
    
    def delete(self, prefix, key=None):
        """Удаление ключа из кэша"""
        cache_key = self._generate_key(prefix, key)
        with self.lock:
            self._delete_unlocked(cache_key)
    
    def delete_prefix(self, prefix):
        """Удаление всех ключей с префиксом"""
        with self.lock:
            keys_to_delete = [k for k in self.cache.keys() if k.startswith(hashlib.md5(prefix.encode()).hexdigest()[:16])]
            for key in keys_to_delete:
                self._delete_unlocked(key)
    
    def clear(self):
        """Очистка всего кэша"""
        with self.lock:
            self.cache.clear()
            self.timestamps.clear()
            self.ttls.clear()
    
    def stats(self):
        """Статистика кэша"""
        with self.lock:
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'keys': list(self.cache.keys())[:10]  # Первые 10 ключей
            }

# Глобальный кэш
cache = LRUCache(max_size=500, default_ttl=300)  # 500 элементов, 5 минут TTL

# Кэш для конкретных данных
USER_CACHE_TTL = 60  # 1 минута
MESSAGES_CACHE_TTL = 30  # 30 секунд
USERS_LIST_CACHE_TTL = 10  # 10 секунд для списка пользователей

def invalidate_user_cache(user_id=None):
    """Инвалидация кэша пользователя"""
    if user_id:
        cache.delete('user', user_id)
        cache.delete('user_by_jt', None)  # Сброс поиска по username
    cache.delete_prefix('users_list')

def invalidate_messages_cache(sender_id=None, recipient_id=None):
    """Инвалидация кэша сообщений"""
    cache.delete('messages', f'{sender_id}_{recipient_id}')
    cache.delete('messages', f'{recipient_id}_{sender_id}')
    cache.delete('messages', f'all_{recipient_id}')

def add_jt_username_column_if_not_exists():
    """Добавить колонку jt_username если её нет (вызывать ДО любых запросов к users)"""
    try:
        with engine.connect() as conn:
            if DATABASE_URL:
                # PostgreSQL
                table_check = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'users'
                    );
                """)).fetchone()
                table_exists = table_check[0] if table_check else False

                if table_exists:
                    col_check = conn.execute(text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns
                            WHERE table_schema = 'public'
                            AND table_name = 'users'
                            AND column_name = 'jt_username'
                        );
                    """)).fetchone()
                    if not col_check[0]:
                        print("Добавляю колонку jt_username в PostgreSQL...")
                        conn.execute(text("ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);"))
                        conn.commit()
                        print("Колонка jt_username добавлена")
            else:
                # SQLite
                table_check = conn.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users';
                """)).fetchone()
                table_exists = bool(table_check)

                if table_exists:
                    col_check = conn.execute(text("""
                        SELECT name FROM pragma_table_info('users')
                        WHERE name = 'jt_username';
                    """)).fetchone()
                    if not col_check:
                        print("Добавляю колонку jt_username в SQLite...")
                        conn.execute(text("ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);"))
                        conn.commit()
                        print("Колонка jt_username добавлена")
    except Exception as e:
        print(f"Ошибка при добавлении колонки jt_username: {e}")

def add_last_seen_column_if_not_exists():
    """Добавить колонку last_seen если её нет (вызывать ДО любых запросов к users)"""
    try:
        with engine.connect() as conn:
            # Сначала проверяем существует ли таблица users
            if DATABASE_URL:
                # PostgreSQL
                table_check = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'users'
                    );
                """)).fetchone()
                table_exists = table_check[0] if table_check else False
                
                if table_exists:
                    col_check = conn.execute(text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns
                            WHERE table_schema = 'public'
                            AND table_name = 'users'
                            AND column_name = 'last_seen'
                        );
                    """)).fetchone()
                    if not col_check[0]:
                        print("Добавляю колонку last_seen в PostgreSQL...")
                        conn.execute(text("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
                        conn.commit()
                        print("Колонка last_seen добавлена")
            else:
                # SQLite
                table_check = conn.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users';
                """)).fetchone()
                table_exists = bool(table_check)
                
                if table_exists:
                    col_check = conn.execute(text("""
                        SELECT name FROM pragma_table_info('users')
                        WHERE name = 'last_seen';
                    """)).fetchone()
                    if not col_check:
                        print("Добавляю колонку last_seen в SQLite...")
                        conn.execute(text("ALTER TABLE users ADD COLUMN last_seen DATETIME DEFAULT CURRENT_TIMESTAMP;"))
                        conn.commit()
                        print("Колонка last_seen добавлена")
    except Exception as e:
        print(f"Ошибка при добавлении колонки last_seen: {e}")

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
                        AND table_name = 'users'
                    );
                """))
            else:
                # SQLite
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users';
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
    username = Column(String(50), unique=True, nullable=False)  # Отображаемое имя
    password_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    avatar_color = Column(String(20), default='6366f1')
    last_seen = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    jt_username = Column(String(50), unique=True, nullable=True)  # @username как в Telegram
    
    # Индексы для ускорения поиска
    __table_args__ = (
        Index('ix_users_jt_username', 'jt_username'),
        Index('ix_users_last_seen', 'last_seen'),
        Index('ix_users_username', 'username'),
    )

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    content = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    file_type = Column(String(20), nullable=True)  # 'image', 'file', или None для текста
    status = Column(String(20), default='sent')  # 'sending', 'sent', 'delivered', 'read'
    
    # Индексы для ускорения поиска сообщений
    __table_args__ = (
        Index('ix_messages_sender_recipient', 'sender_id', 'recipient_id'),
        Index('ix_messages_recipient_created', 'recipient_id', 'created_at'),
        Index('ix_messages_created_at', 'created_at'),
    )

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

        # Добавляем колонку last_seen если её нет (после создания таблиц)
        add_last_seen_column_if_not_exists()
        
        # Добавляем колонку jt_username если её нет (после создания таблиц)
        add_jt_username_column_if_not_exists()

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
    """Получить текущего пользователя из cookie"""
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

# Путь к HTML шаблону
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
        # Обновляем last_seen при загрузке страницы (UTC время)
        db = get_db()
        try:
            user.last_seen = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            print(f"Ошибка обновления last_seen: {e}")
            db.rollback()
        finally:
            db.close()
        return jsonify({
            'id': user.id, 
            'username': user.username, 
            'jt_username': user.jt_username,
            'avatar_color': user.avatar_color or '6366f1'
        })
    return jsonify(None)

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    jt_username = data.get('jt_username', '').strip()  # Опциональный @username

    print(f"=== РЕГИСТРАЦИЯ ===")
    print(f"Username: {username}")
    print(f"JT Username: {jt_username or 'не указан'}")
    print(f"Password получен: {'да' if password else 'нет'}")
    print(f"Длина пароля: {len(password) if password else 0}")

    if not username or len(username) < 2:
        return jsonify({'success': False, 'message': 'Имя слишком короткое'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Пароль должен быть не менее 6 символов'})

    db = get_db()
    try:
        # Проверяем, не занято ли обычное имя
        existing_by_username = db.query(User).filter_by(username=username).first()
        if existing_by_username:
            return jsonify({'success': False, 'message': 'Пользователь с таким именем уже существует'})

        # Если указан jt_username, проверяем его
        if jt_username:
            # Убираем @ если есть
            if jt_username.startswith('@'):
                jt_username = jt_username[1:]
            
            # Валидация
            is_valid, message = validate_jt_username(jt_username)
            if not is_valid:
                return jsonify({'success': False, 'message': f'Неверный username: {message}'})
            
            # Проверка на занятость
            existing_by_jt = db.query(User).filter(
                User.jt_username.ilike(jt_username)
            ).first()
            if existing_by_jt:
                return jsonify({'success': False, 'message': 'Этот username уже занят'})

        password_hash = generate_password_hash(password)
        print(f"password_hash сгенерирован: {password_hash[:50]}...")

        user = User(
            username=username, 
            password_hash=password_hash, 
            avatar_color=generate_avatar_color(),
            jt_username=jt_username.lower() if jt_username else None
        )
        db.add(user)
        db.commit()

        print(f"Пользователь создан: id={user.id}, username={user.username}, jt_username={user.jt_username}")
        print(f"password_hash в БД: {user.password_hash[:50] if user.password_hash else 'NULL'}...")

        # Инвалидация кэша пользователей
        invalidate_user_cache()

        resp = make_response(jsonify({
            'success': True, 
            'user': {
                'id': user.id, 
                'username': user.username, 
                'jt_username': user.jt_username,
                'avatar_color': user.avatar_color
            }
        }))
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
        # Пробуем найти пользователя по username или jt_username
        user = None
        
        # Если начинается с @, ищем по jt_username
        if username.startswith('@'):
            search_username = username[1:]  # Убираем @
            user = db.query(User).filter(
                User.jt_username.ilike(search_username)
            ).first()
            print(f"Поиск по @username: {search_username}")
        else:
            # Сначала ищем по обычному username
            user = db.query(User).filter_by(username=username).first()
            print(f"Поиск по username: {username}")
            
            # Если не найдено, пробуем по jt_username
            if not user:
                user = db.query(User).filter(
                    User.jt_username.ilike(username)
                ).first()
                if user:
                    print(f"Найден по jt_username: {user.jt_username}")

        if not user:
            print(f"Пользователь '{username}' не найден")
            return jsonify({'success': False, 'message': 'Пользователь не найден'})

        print(f"Пользователь найден: id={user.id}, username={user.username}, jt_username={user.jt_username}")
        print(f"password_hash в БД: {user.password_hash[:50] if user.password_hash else 'NULL'}...")

        if not user.password_hash:
            print("password_hash пуст!")
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        is_valid = check_password_hash(user.password_hash, password)
        print(f"Проверка пароля: {'OK' if is_valid else 'FAIL'}")

        if not is_valid:
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        print(f"Вход успешен: {user.username}")
        # Обновляем last_seen при входе (UTC время)
        user.last_seen = datetime.now(timezone.utc)
        db.commit()

        resp = make_response(jsonify({
            'success': True, 
            'user': {
                'id': user.id, 
                'username': user.username, 
                'jt_username': user.jt_username,
                'avatar_color': user.avatar_color
            }
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
    
    # Проверяем кэш
    cache_key = f'user_{user.id}'
    cached_data = cache.get('users_list', cache_key)
    if cached_data:
        return jsonify(cached_data)
    
    db = get_db()
    try:
        users = db.query(User).filter(User.id != user.id).all()
        result = []
        now = datetime.now(timezone.utc)
        for u in users:
            # Считаем онлайн если last_seen был в последние 30 секунд
            is_online = False
            last_seen_str = None
            last_seen_full = None
            if u.last_seen:
                # Конвертируем UTC время в Московское (UTC+3)
                last_seen_utc = u.last_seen
                # Если время без timezone, считаем что это UTC
                if last_seen_utc.tzinfo is None:
                    last_seen_utc = last_seen_utc.replace(tzinfo=timezone.utc)
                # Добавляем 3 часа для Москвы
                last_seen_moscow = last_seen_utc + timedelta(hours=3)
                last_seen_str = last_seen_moscow.strftime('%H:%M')
                # Полная дата и время для отображения
                today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                last_seen_date = last_seen_moscow.replace(tzinfo=None)
                if last_seen_date >= today:
                    # Сегодня
                    last_seen_full = 'сегодня в ' + last_seen_moscow.strftime('%H:%M')
                else:
                    # Не сегодня - показываем дату
                    last_seen_full = last_seen_moscow.strftime('%d.%m.%Y в %H:%M')
                diff = (now - last_seen_utc).total_seconds()
                is_online = diff < 30  # Онлайн если активен в последние 30 секунд
            result.append({
                'id': u.id,
                'username': u.username,
                'jt_username': u.jt_username,
                'avatar_color': u.avatar_color or '6366f1',
                'last_seen': last_seen_str,
                'last_seen_full': last_seen_full,
                'is_online': is_online
            })

        # Сохраняем в кэш
        cache.set('users_list', result, cache_key, ttl=USERS_LIST_CACHE_TTL)
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/messages')
@app.route('/api/messages/<int:recipient_id>')
def api_messages(recipient_id=None):
    user = get_current_user()
    if not user:
        return jsonify([])
    
    # Проверяем кэш
    cache_key = f'{user.id}_{recipient_id or "all"}'
    cached_data = cache.get('messages', cache_key)
    if cached_data:
        return jsonify(cached_data)
    
    db = get_db()
    try:
        if recipient_id:
            # Получаем только 9 последних сообщений для личного чата
            msgs = db.query(Message).filter(
                or_(
                    and_(Message.sender_id == user.id, Message.recipient_id == recipient_id),
                    and_(Message.sender_id == recipient_id, Message.recipient_id == user.id)
                )
            ).order_by(Message.created_at.desc()).limit(9).all()
            # Переворачиваем чтобы новые были внизу
            msgs = list(reversed(msgs))
        else:
            # Получаем только 9 последних сообщений для общего чата
            msgs = db.query(Message).filter(Message.recipient_id.is_(None)).order_by(Message.created_at.desc()).limit(9).all()
            msgs = list(reversed(msgs))
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
        
        # Сохраняем в кэш
        cache.set('messages', result, cache_key, ttl=MESSAGES_CACHE_TTL)
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
            # Если колонки status нет - без статуса
            db.rollback()
            msg = Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content)
            db.add(msg)
            db.commit()

        msg_id = msg.id

        # Инвалидация кэша сообщений
        invalidate_messages_cache(sender_id=user.id, recipient_id=recipient_id)

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
            # Инвалидация кэша пользователей (для last_seen)
            invalidate_user_cache(recipient_id)

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

        # Инвалидация кэша сообщений
        invalidate_messages_cache(sender_id=user.id, recipient_id=recipient_id)

        return jsonify({'success': True, 'id': msg.id, 'status': 'sent'})
    except Exception as e:
        db.rollback()
        print(f"Ошибка отправки файла: {e}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/messages/mark-read', methods=['POST'])
def api_mark_messages_read():
    """Отметить сообщения как прочитанные"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    
    data = request.json
    sender_id = data.get('sender_id') if data else None
    
    if not sender_id:
        return jsonify({'success': False, 'message': 'No sender_id'})
    
    db = get_db()
    try:
        # Просто обновляем last_seen при чтении сообщений (UTC время)
        user.last_seen = datetime.now(timezone.utc)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """Обновляет last_seen текущего пользователя"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Not authorized'})
    db = get_db()
    try:
        user.last_seen = datetime.now(timezone.utc)
        db.commit()
        
        # Инвалидация кэша пользователей (для обновления статуса онлайн)
        invalidate_user_cache()
        
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/logout')
def api_logout():
    # Обновляем last_seen перед выходом чтобы показать что пользователь офлайн
    user = get_current_user()
    if user:
        db = get_db()
        try:
            # Устанавливаем last_seen в прошлое (1 час назад) чтобы показать офлайн
            from datetime import timedelta
            user.last_seen = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
        except Exception as e:
            print(f"Ошибка при выходе: {e}")
            db.rollback()
        finally:
            db.close()
    
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

        # Инвалидация кэша пользователей
        invalidate_user_cache(user.id)

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

import re

def validate_jt_username(username):
    """
    Проверка username на валидность (правила как в Telegram)
    - 5-32 символа
    - Только латинские буквы, цифры и подчёркивания
    - Не может начинаться с цифры
    - Не может содержать подряд несколько подчёркиваний
    """
    if not username:
        return False, "Username не может быть пустым"
    
    if len(username) < 5:
        return False, "Username должен быть не менее 5 символов"
    
    if len(username) > 32:
        return False, "Username должен быть не более 32 символов"
    
    # Только латиница, цифры и подчёркивания, начинается с буквы
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', username):
        return False, "Username должен начинаться с буквы и содержать только латинские буквы, цифры и подчёркивания"
    
    # Не может содержать подряд несколько подчёркиваний
    if '__' in username:
        return False, "Username не может содержать подряд несколько подчёркиваний"
    
    # Не может заканчиваться на подчёркивание
    if username.endswith('_'):
        return False, "Username не может заканчиваться на подчёркивание"
    
    return True, "OK"

@app.route('/api/username/check', methods=['POST'])
def api_check_username():
    """
    Проверка доступности username
    POST /api/username/check
    Body: {"username": "example"}
    """
    data = request.json
    username = data.get('username', '').strip()
    
    # Убираем @ если есть
    if username.startswith('@'):
        username = username[1:]
    
    # Валидация формата
    is_valid, message = validate_jt_username(username)
    if not is_valid:
        return jsonify({
            'available': False,
            'valid': False,
            'message': message
        })
    
    # Проверка на занятость
    db = get_db()
    try:
        existing = db.query(User).filter(
            User.jt_username.ilike(username)
        ).first()
        
        if existing:
            return jsonify({
                'available': False,
                'valid': True,
                'message': 'Этот username уже занят'
            })
        
        return jsonify({
            'available': True,
            'valid': True,
            'message': 'Username доступен'
        })
    finally:
        db.close()

@app.route('/api/username/set', methods=['POST'])
def api_set_username():
    """
    Установка/изменение username
    POST /api/username/set
    Body: {"username": "example"}
    """
    user_id = request.cookies.get('user_id')
    if not user_id:
        return jsonify({
            'success': False,
            'message': 'Требуется авторизация'
        })

    data = request.json
    username = data.get('username', '').strip()

    # Убираем @ если есть
    if username.startswith('@'):
        username = username[1:]

    db = get_db()
    try:
        # Получаем пользователя в текущей сессии
        user = db.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return jsonify({
                'success': False,
                'message': 'Пользователь не найден'
            })

        # Если пустой - удаляем username
        if not username:
            user.jt_username = None
            db.commit()
            return jsonify({
                'success': True,
                'username': None,
                'message': 'Username удалён'
            })

        # Валидация
        is_valid, message = validate_jt_username(username)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': message
            })

        # Проверяем не занят ли username (кроме текущего пользователя)
        existing = db.query(User).filter(
            User.jt_username.ilike(username),
            User.id != user.id
        ).first()

        if existing:
            return jsonify({
                'success': False,
                'message': 'Этот username уже занят'
            })

        # Устанавливаем username
        user.jt_username = username.lower()
        db.commit()

        # Инвалидация кэша пользователей
        invalidate_user_cache(user.id)

        return jsonify({
            'success': True,
            'username': user.jt_username,
            'message': f'Username @{user.jt_username} установлен'
        })
    except Exception as e:
        db.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        })
    finally:
        db.close()

@app.route('/api/username/search')
def api_search_username():
    """
    Поиск пользователей по username
    GET /api/username/search?q=exam
    """
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify([])
    
    # Убираем @ если есть
    if query.startswith('@'):
        query = query[1:]
    
    if len(query) < 2:
        return jsonify([])
    
    db = get_db()
    try:
        # Ищем по началу username (case-insensitive)
        users = db.query(User).filter(
            User.jt_username.ilike(f'{query}%')
        ).limit(10).all()
        
        result = []
        for u in users:
            result.append({
                'id': u.id,
                'username': u.username,
                'jt_username': u.jt_username,
                'avatar_color': u.avatar_color or '6366f1'
            })
        
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/username/resolve')
def api_resolve_username():
    """
    Получение пользователя по точному username
    GET /api/username/resolve?username=example
    """
    username = request.args.get('username', '').strip()
    
    if not username:
        return jsonify({'error': 'Username не указан'})
    
    # Убираем @ если есть
    if username.startswith('@'):
        username = username[1:]
    
    db = get_db()
    try:
        user = db.query(User).filter(
            User.jt_username.ilike(username)
        ).first()
        
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        return jsonify({
            'id': user.id,
            'username': user.username,
            'jt_username': user.jt_username,
            'avatar_color': user.avatar_color or '6366f1'
        })
    finally:
        db.close()

@app.route('/api/cache/stats')
def api_cache_stats():
    """Статистика кэша (для отладки производительности)"""
    return jsonify(cache.stats())

@app.route('/api/cache/clear', methods=['POST'])
def api_cache_clear():
    """Очистка кэша (для отладки)"""
    cache.clear()
    return jsonify({'success': True, 'message': 'Кэш очищен'})

# Маршрут для раздачи статических файлов (должен быть после всех API маршрутов)
@app.route('/<path:filename>')
def serve_static_file(filename):
    """Раздача статических файлов (изображения, CSS и т.д.)"""
    # Не обслуживаем API пути
    if filename.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    
    filepath = os.path.join(CURRENT_DIR, filename)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        # Определяем MIME-тип
        mime_type = 'application/octet-stream'
        if filename.endswith('.png'):
            mime_type = 'image/png'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            mime_type = 'image/jpeg'
        elif filename.endswith('.gif'):
            mime_type = 'image/gif'
        elif filename.endswith('.svg'):
            mime_type = 'image/svg+xml'
        elif filename.endswith('.css'):
            mime_type = 'text/css'
        elif filename.endswith('.js'):
            mime_type = 'application/javascript'
        elif filename.endswith('.html'):
            mime_type = 'text/html'
        elif filename.endswith('.json'):
            mime_type = 'application/json'
        
        return send_from_directory(CURRENT_DIR, filename, mimetype=mime_type)
    return jsonify({'error': 'File not found'}), 404

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