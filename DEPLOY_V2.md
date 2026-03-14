# 🚀 Деплой Jetesk на Vercel с Push-уведомлениями

## 📁 Структура проекта для деплоя

Файлы для деплоя находятся в папке `product/`:
```
product/
├── api/
│   └── index.py          # Entry point для Vercel
├── messenger_server.py   # Основное приложение
├── index.html            # Frontend
├── sw.js                 # Service Worker для push
├── Jetesk.png            # Иконка
├── requirements.txt      # Зависимости
└── vercel.json           # Конфигурация Vercel
```

## 🚀 Пошаговая инструкция

### Шаг 1: Подготовьте файлы

Скопируйте содержимое папки `product/` в корень вашего проекта:
```bash
cd "d:\bootstrap-5.3.8\dist"
xcopy /E /I /Y product\* "c:\Users\admin\Desktop\messenger jetesk\"
```

Или просто используйте папку `product/` как корень проекта.

### Шаг 2: Установите зависимости

```bash
cd product
pip install -r requirements.txt
```

### Шаг 3: Создайте базу данных на Neon

1. Перейдите на https://neon.tech
2. Войдите через GitHub
3. Создайте проект:
   - Name: `messenger-jetest`
   - Database: `messenger`
   - Region: ближайшая к вам

4. Скопируйте **Connection String**

### Шаг 4: Сгенерируйте VAPID ключи (для push-уведомлений)

При первом запуске сервера ключи сгенерируются автоматически. **Сохраните их!**

Или сгенерируйте вручную:
```python
python -c "from messenger_server import get_vapid_keys; print(get_vapid_keys())"
```

### Шаг 5: Добавьте переменные окружения в Vercel

1. https://vercel.com/dashboard → ваш проект
2. **Settings** → **Environment Variables**
3. Добавьте:

| Name | Value | Environment |
|------|-------|-------------|
| `DATABASE_URL` | connection string от Neon | All |
| `VAPID_PUBLIC_KEY` | ваш публичный ключ | All |
| `VAPID_PRIVATE_KEY` | ваш приватный ключ | All |

4. **Save**

### Шаг 6: Задеплойте

```bash
cd product
vercel --prod
```

### Шаг 7: Проверьте

1. Откройте ваш сайт
2. Зарегистрируйтесь
3. Откройте настройки (⚙️)
4. Включите push-уведомления
5. Разрешите уведомления в браузере

---

## 🔧 Локальный запуск

```bash
cd product
python messenger_server.py
```

Откройте: http://localhost:5000

---

## 📦 Зависимости

```txt
flask==3.0.0
sqlalchemy==2.0.23
werkzeug==3.0.1
flask-cors==4.0.0
psycopg2-binary==2.9.9
pywebpush==1.14.0
cryptography==41.0.7
```

---

## ⚠️ Важно

- **VAPID ключи** должны быть постоянными! Сохраните их после первой генерации.
- **HTTPS** обязателен для push-уведомлений (на Vercel уже есть).
- **Не коммитьте** пароли и ключи в Git!
- Без `DATABASE_URL` приложение использует SQLite (для локальной разработки).

---

## 🔔 Push-уведомления

После деплоя:
1. Откройте сайт в браузере
2. Зайдите в настройки
3. Нажмите "Включить уведомления"
4. Разрешите в браузере
5. При новых сообщениях будут приходить push-уведомления

Подробнее см. [PUSH_NOTIFICATIONS.md](PUSH_NOTIFICATIONS.md)

---

## 🐛 Отладка

Если ошибка 500:
1. Проверьте логи в Vercel Dashboard → Functions → logs
2. Убедитесь, что `DATABASE_URL` правильный
3. Проверьте, что все зависимости установлены

Если push не работают:
1. Откройте консоль разработчика (F12)
2. Проверьте логи `[Push]`
3. Убедитесь, что VAPID ключи совпадают на сервере и клиенте
