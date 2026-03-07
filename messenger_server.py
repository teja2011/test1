from flask import Flask, render_template_string, request, jsonify, redirect, make_response
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, or_, and_
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import secrets
import os
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

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

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    return sessionmaker(bind=engine)()

def get_current_user():
    username = request.cookies.get('username')
    if not username:
        return None
    db = get_db()
    user = db.query(User).filter_by(username=username).first()
    db.close()
    return user

def generate_avatar_color():
    import random
    return random.choice(['6366f1', '10b981', 'f59e0b', 'ef4444', '8b5cf6', 'ec4899', '0891b2', '7c3aed'])

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
        return jsonify({'success': False, 'message': 'Username too short'})
    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Password too short'})
    db = get_db()
    try:
        if db.query(User).filter_by(username=username).first():
            return jsonify({'success': False, 'message': 'User exists'})
        user = User(username=username, password_hash=generate_password_hash(password), avatar_color=generate_avatar_color())
        db.add(user)
        db.commit()
        resp = make_response(jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color}}))
        resp.set_cookie('username', username, max_age=60*60*24*30, samesite='lax')
        return resp
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
    db = get_db()
    try:
        user = db.query(User).filter_by(username=username).first()
        if not user:
            user = User(username=username, avatar_color=generate_avatar_color())
            db.add(user)
            db.commit()
        elif password and user.password_hash:
            if not check_password_hash(user.password_hash, password):
                db.close()
                return jsonify({'success': False, 'message': 'Wrong password'})
        resp = make_response(jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'avatar_color': user.avatar_color}}))
        resp.set_cookie('username', username, max_age=60*60*24*30, samesite='lax')
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
            result.append({'id': m.id, 'sender': sender.username if sender else 'Unknown', 'content': m.content, 'created_at': m.created_at.strftime('%H:%M'), 'is_mine': m.sender_id == user.id})
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
        db.add(Message(sender_id=user.id, recipient_id=recipient_id if recipient_id else None, content=content))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@app.route('/api/logout')
def api_logout():
    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('username')
    return resp

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)

HTML_TEMPLATE = open('index.html', 'r', encoding='utf-8').read() if os.path.exists('index.html') else '<h1>index.html not found</h1>'
