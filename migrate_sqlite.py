#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Миграция SQLite: изменяет поле content в таблице messages на TEXT
"""

import sqlite3

conn = sqlite3.connect('messenger.db')
cursor = conn.cursor()

try:
    # Проверяем текущую структуру
    cursor.execute("PRAGMA table_info(messages)")
    columns = cursor.fetchall()
    print("Текущая структура таблицы messages:")
    for col in columns:
        print(f"  {col}")
    
    # Создаём новую таблицу с правильным типом
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages_new (
            id INTEGER PRIMARY KEY,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER,
            content TEXT NOT NULL,
            created_at DATETIME,
            file_type VARCHAR(20),
            status VARCHAR(20) DEFAULT 'sent'
        )
    """)
    
    # Копируем данные
    cursor.execute("""
        INSERT INTO messages_new 
        SELECT id, sender_id, recipient_id, content, created_at, file_type, status 
        FROM messages
    """)
    
    # Удаляем старую таблицу
    cursor.execute("DROP TABLE messages")
    
    # Переименовываем новую
    cursor.execute("ALTER TABLE messages_new RENAME TO messages")
    
    conn.commit()
    
    # Проверяем новую структуру
    cursor.execute("PRAGMA table_info(messages)")
    columns = cursor.fetchall()
    print("\nНовая структура таблицы messages:")
    for col in columns:
        print(f"  {col}")
    
    print("\n✅ Миграция SQLite успешно завершена!")
    
except Exception as e:
    conn.rollback()
    print(f"\n❌ Ошибка миграции: {e}")
    raise
finally:
    conn.close()
