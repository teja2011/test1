#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Скрипт для создания базы данных"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'messenger.db')

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    try:
        # Таблица пользователей
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
        
        # Таблица сообщений
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
        
        # Таблица уведомлений
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
        
        # Индексы
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_jt_username ON users(jt_username)")
        
        conn.commit()
        
        # Проверка
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✅ Созданы таблицы: {', '.join(tables)}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    print("=== Создание базы данных ===")
    create_tables()
    print("=== Готово ===")
