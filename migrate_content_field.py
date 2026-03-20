#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Миграция: изменяет поле content в таблице messages с VARCHAR(1000) на TEXT
"""

import os
from sqlalchemy import create_engine, text

# Загружаем переменные окружения
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    engine = create_engine(DATABASE_URL)
    print("Подключение к PostgreSQL (Neon)...")
else:
    engine = create_engine('sqlite:///messenger.db')
    print("Подключение к SQLite (messenger.db)...")

def migrate():
    with engine.connect() as conn:
        try:
            # Проверяем тип базы данных
            if DATABASE_URL:
                # PostgreSQL
                print("Выполнение миграции для PostgreSQL...")
                conn.execute(text("""
                    ALTER TABLE messages 
                    ALTER COLUMN content TYPE TEXT
                """))
                print("✓ Поле content изменено на TEXT")
            else:
                # SQLite
                print("Выполнение миграции для SQLite...")
                # В SQLite нужно пересоздать таблицу
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS messages_new (
                        id INTEGER PRIMARY KEY,
                        sender_id INTEGER NOT NULL,
                        recipient_id INTEGER,
                        content TEXT NOT NULL,
                        created_at DATETIME,
                        file_type VARCHAR(20),
                        status VARCHAR(20) DEFAULT 'sent'
                    )
                """))
                conn.execute(text("""
                    INSERT INTO messages_new SELECT * FROM messages
                """))
                conn.execute(text("DROP TABLE messages"))
                conn.execute(text("ALTER TABLE messages_new RENAME TO messages"))
                print("✓ Поле content изменено на TEXT (SQLite)")
            
            conn.commit()
            print("\n✅ Миграция успешно завершена!")
            
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Ошибка миграции: {e}")
            raise

if __name__ == '__main__':
    migrate()
