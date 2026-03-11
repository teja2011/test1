"""
Скрипт для добавления колонки jt_username в таблицу users
Запустите один раз для добавления поддержки @username
"""

import os
from sqlalchemy import create_engine, text

# Настройка подключения
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    print("Используется PostgreSQL (Neon)")
    engine = create_engine(DATABASE_URL, echo=True)
else:
    print("Используется SQLite (messenger.db)")
    engine = create_engine('sqlite:///messenger.db', echo=True)

def add_jt_username_column():
    """Добавить колонку jt_username если её нет"""
    
    with engine.connect() as conn:
        try:
            # Проверяем существует ли таблица users
            if DATABASE_URL:
                # PostgreSQL
                print("Проверка таблицы в PostgreSQL...")
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'users'
                    );
                """))
                table_exists = result.fetchone()[0]
                
                if not table_exists:
                    print("❌ Таблица users не найдена!")
                    return False
                
                # Проверяем существует ли колонка jt_username
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = 'users'
                        AND column_name = 'jt_username'
                    );
                """))
                column_exists = result.fetchone()[0]
                
                if column_exists:
                    print("✅ Колонка jt_username уже существует")
                    return True
                
                # Добавляем колонку
                print("Добавление колонки jt_username...")
                conn.execute(text("""
                    ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);
                """))
                conn.commit()
                print("✅ Колонка jt_username успешно добавлена!")
                return True
                
            else:
                # SQLite
                print("Проверка таблицы в SQLite...")
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users';
                """))
                table_exists = result.fetchone() is not None
                
                if not table_exists:
                    print("❌ Таблица users не найдена!")
                    return False
                
                # Проверяем существует ли колонка jt_username
                result = conn.execute(text("""
                    SELECT name FROM pragma_table_info('users')
                    WHERE name = 'jt_username';
                """))
                column_exists = result.fetchone() is not None
                
                if column_exists:
                    print("✅ Колонка jt_username уже существует")
                    return True
                
                # Добавляем колонку
                print("Добавление колонки jt_username...")
                conn.execute(text("""
                    ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);
                """))
                conn.commit()
                print("✅ Колонка jt_username успешно добавлена!")
                return True
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False

if __name__ == '__main__':
    print("=== Миграция: добавление колонки jt_username ===\n")
    success = add_jt_username_column()
    
    if success:
        print("\n=== Миграция завершена успешно! ===")
    else:
        print("\n=== Ошибка миграции ===")
