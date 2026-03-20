"""
Скрипт для добавления колонки email и таблицы email_verifications в PostgreSQL
"""

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL не найден в .env файле")
    exit(1)

# Подключаемся к базе
from sqlalchemy import create_engine, text

engine = create_engine(DATABASE_URL)

print("=== Миграция PostgreSQL: Email верификация ===\n")

with engine.connect() as conn:
    try:
        # 1. Добавляем колонку email
        print("1. Добавляем колонку email в users...")
        conn.execute(text("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100)
        """))
        conn.commit()
        print("   ✅ Колонка email добавлена\n")
        
        # 2. Создаём индекс
        print("2. Создаём индекс для email...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """))
        conn.commit()
        print("   ✅ Индекс создан\n")
        
        # 3. Создаём таблицу email_verifications
        print("3. Создаём таблицу email_verifications...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email_verifications (
                id SERIAL PRIMARY KEY,
                email VARCHAR(100) NOT NULL UNIQUE,
                code VARCHAR(6) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_verified INTEGER DEFAULT 0
            )
        """))
        conn.commit()
        print("   ✅ Таблица создана\n")
        
        # 4. Создаём индексы
        print("4. Создаём индексы для email_verifications...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON email_verifications(email)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_email_verifications_code ON email_verifications(code)
        """))
        conn.commit()
        print("   ✅ Индексы созданы\n")
        
        # 5. Проверяем результат
        print("5. Проверка результатов:")
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'email'
        """))
        for row in result:
            print(f"   users.email: {row}")
        
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'email_verifications'
            ORDER BY ordinal_position
        """))
        print("\n   Таблица email_verifications:")
        for row in result:
            print(f"      {row[0]}: {row[1]}")
        
        print("\n=== ✅ Миграция успешно завершена ===")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Ошибка миграции: {e}")
        raise
