"""
Миграция для добавления:
1. Колонки email в таблицу users
2. Таблицы email_verifications
"""

import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base
from datetime import datetime, timedelta
import os

# Загружаем переменные окружения
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False)
else:
    engine = create_engine('sqlite:///messenger.db', echo=False)

Base = declarative_base()

class EmailVerification(Base):
    __tablename__ = 'email_verifications'
    id = Column(Integer, primary_key=True)
    email = Column(String(100), nullable=False, unique=True)
    code = Column(String(6), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_verified = Column(Integer, default=0)

def run_migration():
    print("=== Миграция: Добавление email верификации ===\n")
    
    with engine.connect() as conn:
        # Проверяем, существует ли колонка email в users
        print("Проверка колонки email в users...")
        if DATABASE_URL:
            result = conn.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'email'
            """))
        else:
            result = conn.execute(text("""
                PRAGMA table_info(users)
            """))
        
        email_exists = any(row[0] == 'email' for row in result.fetchall())
        
        if not email_exists:
            print("Добавление колонки email в users...")
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(100)"))
                conn.commit()
                print("✅ Колонка email добавлена")
            except Exception as e:
                print(f"⚠️ Ошибка добавления email: {e}")
        else:
            print("✅ Колонка email уже существует")
        
        # Создаём таблицу email_verifications
        print("\nСоздание таблицы email_verifications...")
        try:
            Base.metadata.create_all(engine)
            print("✅ Таблица email_verifications создана")
        except Exception as e:
            print(f"⚠️ Ошибка создания таблицы: {e}")
        
        print("\n=== Миграция завершена ===")

if __name__ == '__main__':
    run_migration()
