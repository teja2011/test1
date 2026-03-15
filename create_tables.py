#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для создания таблиц в базе данных Neon
Запускать локально: python create_tables.py
"""

from dotenv import load_dotenv
import os

# Загружаем переменные окружения из .env
load_dotenv()

import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

print("Connecting to database...")
print(f"URL: {DATABASE_URL[:50]}...")

try:
    # Подключаемся напрямую через psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    print("Connected successfully!")
    
    # Создаём таблицу users
    print("\nCreating users table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(256),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            avatar_color VARCHAR(20) DEFAULT '6366f1',
            avatar_url VARCHAR(500),
            jt_username VARCHAR(50) UNIQUE,
            last_seen TIMESTAMP
        )
    """)
    print("OK: users table created")
    
    # Создаём таблицу messages
    print("Creating messages table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            content VARCHAR(1000) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_type VARCHAR(20),
            status VARCHAR(20) DEFAULT 'sent'
        )
    """)
    print("OK: messages table created")
    
    # Создаём таблицу notifications
    print("Creating notifications table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            sender_id INTEGER REFERENCES users(id),
            message VARCHAR(500) NOT NULL,
            type VARCHAR(20) DEFAULT 'message',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("OK: notifications table created")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print("\nSUCCESS: All tables created!")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
