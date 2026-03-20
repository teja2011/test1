-- Миграция для добавления email верификации
-- Выполните этот SQL в вашей PostgreSQL базе данных

-- 1. Добавляем колонку email в таблицу users (если не существует)
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100);

-- 2. Создаём индекс для email (для быстрого поиска)
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 3. Создаём таблицу для хранения кодов подтверждения email
CREATE TABLE IF NOT EXISTS email_verifications (
    id SERIAL PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(6) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_verified INTEGER DEFAULT 0
);

-- 4. Создаём индекс для поиска по email и коду
CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON email_verifications(email);
CREATE INDEX IF NOT EXISTS idx_email_verifications_code ON email_verifications(code);

-- 5. Добавляем комментарий к таблицам
COMMENT ON TABLE email_verifications IS 'Коды подтверждения email для регистрации';
COMMENT ON COLUMN email_verifications.code IS '6-значный код подтверждения';
COMMENT ON COLUMN email_verifications.is_verified IS '1 = email подтверждён, 0 = не подтверждён';

-- 6. Проверяем создание таблиц
SELECT table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('users', 'email_verifications') 
ORDER BY table_name, ordinal_position;
