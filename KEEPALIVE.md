# Keep-Alive для сервера

## Проблема
Серверы на бесплатных тарифах (Vercel, Heroku, Railway) засыпают после периода бездействия.

## Решение

### 1. Внутренний Keep-Alive (автоматически)
Сервер отправляет запросы сам себе каждые 5 минут через `/api/keepalive`.

**Настройка в `.env`:**
```
KEEPALIVE_URL=https://your-app.vercel.app/api/keepalive
KEEPALIVE_INTERVAL=300
```

### 2. Внешний Keep-Alive (рекомендуется)
Используйте бесплатные сервисы для периодических запросов:

#### UptimeRobot (https://uptimerobot.com/)
- Бесплатно: 50 мониторов, интервал 5 минут
- Создайте новый монитор типа "HTTP(s)"
- URL: `https://your-app.vercel.app/api/keepalive`

#### Cron-Job.org (https://cron-job.org/)
- Бесплатно: неограниченно, интервал 1 минута
- Создайте новый cron job
- URL: `https://your-app.vercel.app/api/keepalive`

#### GitHub Actions (бесплатно)
Создайте файл `.github/workflows/keepalive.yml`:

```yaml
name: Keep-Alive

on:
  schedule:
    - cron: '*/5 * * * *'  # Каждые 5 минут
  workflow_dispatch:

jobs:
  keepalive:
    runs-on: ubuntu-latest
    steps:
      - name: Ping server
        run: curl https://your-app.vercel.app/api/keepalive
```

### 3. Vercel специфика
Vercel serverless функции не засыпают, но имеют timeout 10 секунд.
Для Vercel keep-alive не нужен - функции активируются по запросу.

**Если используете Vercel:**
- Удалите `KEEPALIVE_URL` из `.env`
- Keep-alive механизм автоматически отключится

### Проверка
```bash
curl https://your-app.vercel.app/api/keepalive
```

Ответ:
```json
{"status": "ok", "timestamp": "2026-03-18T12:00:00.000000"}
```
