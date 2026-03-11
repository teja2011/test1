# 📛 Система @username для мессенджера

Система юзернеймов (псевдонимов) в стиле Telegram для мессенджера Jetesk.

## 🔹 Что такое @username?

**@username** — это уникальный короткий идентификатор пользователя, похожий на Telegram. Например: `@john_doe`, `@messenger_user`.

### Преимущества:
- 🔍 **Поиск**: Пользователей можно найти по username
- 📝 **Упоминания**: Можно упоминать пользователей в сообщениях
- 🔗 **Ссылки**: Короткая ссылка на профиль пользователя
- ✨ **Анонимность**: Можно скрыть реальное имя, используя только username

---

## 🔹 Правила создания username

Username должен соответствовать правилам (как в Telegram):

| Правило | Описание |
|---------|----------|
| **Длина** | 5-32 символа |
| **Символы** | Латинские буквы (a-z), цифры (0-9) и подчёркивания (_) |
| **Начало** | Должен начинаться с буквы |
| **Подчёркивания** | Нельзя использовать подряд (`__`) |
| **Окончание** | Не может заканчиваться на подчёркивание |

### Примеры:
- ✅ `@john_doe` — валидный
- ✅ `@user123` — валидный
- ✅ `@messenger_user` — валидный
- ❌ `@123user` — начинается с цифры
- ❌ `@user__name` — двойное подчёркивание
- ❌ `@user_` — заканчивается на подчёркивание
- ❌ `@ab` — слишком короткий (менее 5 символов)

---

## 🔹 API эндпоинты

### 1. Проверка доступности username

**POST** `/api/username/check`

Проверяет, свободен ли username и соответствует ли правилам.

**Запрос:**
```json
{
  "username": "example"
}
```

**Ответ:**
```json
{
  "available": true,
  "valid": true,
  "message": "Username доступен"
}
```

**Возможные сообщения:**
- `"Username доступен"` — можно использовать
- `"Этот username уже занят"` — уже используется другим пользователем
- `"Username должен быть не менее 5 символов"` — нарушены правила

---

### 2. Установка/изменение username

**POST** `/api/username/set`

Устанавливает или изменяет username текущего пользователя.

**Запрос:**
```json
{
  "username": "example"
}
```

**Ответ (успех):**
```json
{
  "success": true,
  "username": "example",
  "message": "Username @example установлен"
}
```

**Ответ (ошибка):**
```json
{
  "success": false,
  "message": "Этот username уже занят"
}
```

**Удаление username:**
```json
{
  "username": ""
}
```

---

### 3. Поиск пользователей по username

**GET** `/api/username/search?q=exam`

Ищет пользователей по началу username.

**Ответ:**
```json
[
  {
    "id": 1,
    "username": "Иван",
    "tg_username": "example",
    "avatar_color": "6366f1"
  }
]
```

---

### 4. Получение пользователя по точному username

**GET** `/api/username/resolve?username=example`

Получает информацию о пользователе по точному username.

**Ответ (успех):**
```json
{
  "id": 1,
  "username": "Иван",
  "tg_username": "example",
  "avatar_color": "6366f1"
}
```

**Ответ (ошибка):**
```json
{
  "error": "Пользователь не найден"
}
```

---

## 🔹 Использование во фронтенде

### Отображение username

Username отображается в нескольких местах:

1. **В шапке профиля** (после имени):
   ```
   Иван @ivan_doe
   ```

2. **В списке пользователей** (мелким шрифтом):
   ```
   Иван
   @ivan_doe
   ```

3. **В настройках** (поле для редактирования):
   - Поле `@Username` в модальном окне настроек
   - Кнопка сохранения 💾
   - Статус проверки (доступен/занят)

---

### JavaScript функции

```javascript
// Проверка доступности username
checkUsernameAvailability('example')
  .then(function(result) {
    if (result.available) {
      console.log('Username свободен!');
    }
  });

// Установка username
setTgUsername('example')
  .then(function(result) {
    if (result.success) {
      console.log('Username установлен:', result.username);
    }
  });

// Сохранение username из поля ввода
saveTgUsername();
```

---

## 🔹 База данных

### Изменения в таблице `users`

Добавлена новая колонка:

```sql
ALTER TABLE users ADD COLUMN tg_username VARCHAR(50);
```

**Характеристики:**
- Тип: `VARCHAR(50)`
- Уникальность: `UNIQUE` (регистронезависимая проверка)
- Nullable: `YES` (необязательное поле)

**Автоматическая миграция:**
При запуске сервер автоматически добавляет колонку `tg_username`, если её нет.

---

## 🔹 Интеграция с Vercel

Система username работает как с локальной SQLite, так и с PostgreSQL на Neon.

**Переменные окружения:**
- `DATABASE_URL` — подключение к PostgreSQL (для продакшена)
- `SECRET_KEY` — секретный ключ для сессий

**Развёртывание:**
```bash
# Локальный запуск
python product/messenger_server.py

# Деплой на Vercel
vercel --prod
```

---

## 🔹 Примеры использования

### 1. Регистрация и установка username

```python
# Регистрация пользователя
POST /api/register
{
  "username": "Иван",
  "password": "secret123"
}

# Установка username
POST /api/username/set
{
  "username": "ivan_doe"
}
```

### 2. Поиск пользователя

```javascript
// Поиск по началу username
fetch('/api/username/search?q=ivan')
  .then(r => r.json())
  .then(users => {
    users.forEach(user => {
      console.log(`@${user.tg_username} - ${user.username}`);
    });
  });
```

### 3. Проверка перед установкой

```javascript
// Сначала проверяем
fetch('/api/username/check', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({username: 'my_username'})
})
.then(r => r.json())
.then(result => {
  if (result.available) {
    // Устанавливаем
    return fetch('/api/username/set', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: 'my_username'})
    });
  } else {
    alert('Username занят: ' + result.message);
  }
});
```

---

## 🔹 Структура файлов

```
dist/
├── product/
│   ├── messenger_server.py    # Сервер с API username
│   └── index.html             # Фронтенд с формой username
├── api/
│   └── username_api.py        # Отдельный модуль API (опционально)
└── USERNAME_SYSTEM.md         # Эта документация
```

---

## 🔹 Будущие улучшения

- [ ] **@Упоминания** в сообщениях (парсинг @username в тексте)
- [ ] **Ссылки на профиль** (переход к чату по клику на username)
- [ ] **Автодополнение** при вводе @ в сообщении
- [ ] **История username** (аудит изменений)
- [ ] **Резервирование** username при регистрации

---

## 🔹 Поддержка

При возникновении проблем:

1. Проверьте логи сервера (ошибки БД)
2. Убедитесь, что колонка `tg_username` добавлена
3. Проверьте консоль браузера (ошибки JavaScript)

**Контакты:** Разработчик мессенджера Jetesk
