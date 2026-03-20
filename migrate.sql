-- Миграция для Neon PostgreSQL
-- Выполните этот SQL в панели управления Neon (Console) или через psql

-- Изменяем тип поля content с VARCHAR(1000) на TEXT
ALTER TABLE messages 
ALTER COLUMN content TYPE TEXT;

-- Проверка результата
-- \d messages  (в psql)
-- или
SELECT column_name, data_type, character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'messages' AND column_name = 'content';
