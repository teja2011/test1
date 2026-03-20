# 📷 Настройка аватарок для Vercel

## Проблема
Vercel использует **только для чтения** файловую систему. Нельзя сохранять файлы напрямую.

## Решение: Cloudinary (бесплатно)

Cloudinary — облачное хранилище изображений с CDN.

### Шаг 1: Регистрация

1. Перейдите на https://cloudinary.com
2. Нажмите **Sign Up** (войдите через GitHub)
3. Подтвердите email

### Шаг 2: Получите учётные данные

После входа:
1. Скопируйте **Cloud Name** (например, `dxxx1234`)
2. Перейдите в **Settings** → **API Keys**
3. Скопируйте **API Key** и **API Secret**

### Шаг 3: Добавьте переменные окружения в Vercel

1. Откройте проект на https://vercel.com/dashboard
2. **Settings** → **Environment Variables**
3. Добавьте 3 переменные:

| Name | Value | Environment |
|------|-------|-------------|
| `CLOUDINARY_CLOUD_NAME` | `dxxx1234` | ✅ Production, Preview, Development |
| `CLOUDINARY_API_KEY` | `123456789012345` | ✅ Production, Preview, Development |
| `CLOUDINARY_API_SECRET` | `abcdef123456...` | ✅ Production, Preview, Development |

4. Нажмите **Save**

### Шаг 4: Задеплойте заново

```bash
cd "c:\Users\admin\Desktop\messenger jetesk"
vercel --prod
```

### Шаг 5: Проверьте

1. Откройте сайт
2. Зайдите в настройки
3. Нажмите 📷 на аватарке
4. Выберите изображение
5. Аватарка должна обновиться!

---

## 🔧 Локальная разработка

Локально аватарки сохраняются в папку `product/avatars/`.

**Cloudinary не нужен** для локальной разработки — используйте его только для деплоя на Vercel.

---

## ⚠️ Важно

- **Никогда не коммитьте** API ключи в Git
- Cloudinary бесплатный тариф: 25 кредитов/месяц (~25 ГБ хранилища)
- Аватарки автоматически оптимизируются и обрезаются до квадрата

---

## 📁 Структура URL

Cloudinary возвращает URL вида:
```
https://res.cloudinary.com/dxxx1234/image/upload/w_200,h_200,c_fill,g_face/avatars/user_1_abc12345.png
```

- `w_200,h_200,c_fill,g_face` — автоматическая обрезка до квадрата с фокусом на лице
- `avatars/` — папка в Cloudinary
- `user_1_abc12345.png` — уникальное имя файла
