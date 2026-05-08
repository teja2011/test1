-- Миграция: добавление колонки duration в таблицу messages
-- Для PostgreSQL (Supabase и другие)

ALTER TABLE messages ADD COLUMN IF NOT EXISTS duration VARCHAR(20);

-- Комментарий к колонке
COMMENT ON COLUMN messages.duration IS 'Длительность голосового сообщения в формате "30s"';
