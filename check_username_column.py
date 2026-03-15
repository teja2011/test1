"""
Скрипт для проверки и добавления колонки jt_username
Запустите один раз для создания колонки
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

def check_and_add_column():
    """Проверить и добавить колонку jt_username"""
    
    with engine.connect() as conn:
        try:
            if DATABASE_URL:
                # PostgreSQL
                print("Проверка в PostgreSQL...")
                
                # Проверяем существование колонки
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
                else:
                    print("Добавление колонки jt_username...")
                    conn.execute(text("""
                        ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);
                    """))
                    conn.commit()
                    print("✅ Колонка jt_username добавлена!")
                
            else:
                # SQLite
                print("Проверка в SQLite...")
                
                # Проверяем существование колонки
                result = conn.execute(text("""
                    SELECT name FROM pragma_table_info('users')
                    WHERE name = 'jt_username';
                """))
                column_exists = result.fetchone() is not None
                
                if column_exists:
                    print("✅ Колонка jt_username уже существует")
                else:
                    print("Добавление колонки jt_username...")
                    conn.execute(text("""
                        ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);
                    """))
                    conn.commit()
                    print("✅ Колонка jt_username добавлена!")
            
            # Проверяем результат
            print("\nПроверка результата...")
            if DATABASE_URL:
                result = conn.execute(text("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = 'users'
                    AND column_name IN ('username', 'jt_username', 'password_hash');
                """))
            else:
                result = conn.execute(text("""
                    SELECT name, type FROM pragma_table_info('users')
                    WHERE name IN ('username', 'jt_username', 'password_hash');
                """))
            
            print("\nКолонки в таблице users:")
            for row in result.fetchall():
                print(f"  - {row[0]} ({row[1]})")
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    print("=== Проверка и добавление колонки jt_username ===\n")
    check_and_add_column()
    print("\n=== Готово ===")
