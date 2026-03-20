"""
Vercel Serverless Function для миграции БД
Вызывается один раз после деплоя
"""

import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL не найден")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

def run_migration():
    print("=== Миграция БД для Vercel ===\n")
    
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
            print("4. Создаём индексы...")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON email_verifications(email)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_email_verifications_code ON email_verifications(code)
            """))
            conn.commit()
            print("   ✅ Индексы созданы\n")
            
            print("=== ✅ Миграция успешно завершена ===")
            return {"success": True, "message": "Миграция выполнена"}
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Ошибка: {e}")
            return {"success": False, "message": str(e)}

# Для вызова через API
def handler(event, context):
    result = run_migration()
    return {
        'statusCode': 200 if result['success'] else 500,
        'body': result
    }

if __name__ == '__main__':
    run_migration()
