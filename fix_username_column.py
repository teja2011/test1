"""
Скрипт для проверки и добавления колонки jt_username
"""

import os
from sqlalchemy import create_engine, text

# Путь к БД в папке product
DB_PATH = os.path.join(os.path.dirname(__file__), 'product', 'messenger.db')
print(f"Путь к БД: {DB_PATH}")

engine = create_engine(f'sqlite:///{DB_PATH}', echo=True)

def check_and_add_column():
    with engine.connect() as conn:
        try:
            print("Проверка в SQLite...")
            
            # Проверяем существование колонки
            result = conn.execute(text("""
                SELECT name FROM pragma_table_info('users')
                WHERE name = 'jt_username';
            """))
            column_exists = result.fetchone() is not None
            
            if column_exists:
                print("OK: Колонка jt_username уже существует")
            else:
                print("Добавление колонки jt_username...")
                conn.execute(text("ALTER TABLE users ADD COLUMN jt_username VARCHAR(50);"))
                conn.commit()
                print("OK: Колонка jt_username добавлена!")
            
            # Проверяем результат
            print("\nКолонки в таблице users:")
            result = conn.execute(text("""
                SELECT name, type FROM pragma_table_info('users')
                WHERE name IN ('username', 'jt_username', 'password_hash', 'id');
            """))
            for row in result.fetchall():
                print(f"  - {row[0]} ({row[1]})")
                
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == '__main__':
    print("=== Проверка и добавление колонки jt_username ===\n")
    check_and_add_column()
    print("\n=== Готово ===")
