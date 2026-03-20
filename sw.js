// Service Worker для PWA - кэширование, offline, push
const CACHE_NAME = 'jetesk-v2';
const STATIC_CACHE = 'jetesk-static-v2';
const DYNAMIC_CACHE = 'jetesk-dynamic-v2';
const API_CACHE = 'jetesk-api-v2';
const MESSAGES_CACHE = 'jetesk-messages-v2';

const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/manifest.json',
    '/Jetesk.png'
];

const MAX_CACHE_SIZE = 50;
const MAX_CACHE_AGE = 7 * 24 * 60 * 60 * 1000; // 7 дней
const MESSAGES_CACHE_AGE = 24 * 60 * 60 * 1000; // 24 часа для сообщений

// Установка Service Worker
self.addEventListener('install', (event) => {
    console.log('[SW] Install');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Кэширование статики');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
            .catch((err) => {
                console.log('[SW] Ошибка кэширования:', err);
            })
    );
});

// Активация Service Worker
self.addEventListener('activate', (event) => {
    console.log('[SW] Activate');
    event.waitUntil(
        caches.keys()
            .then((keys) => {
                const oldCaches = keys.filter((key) =>
                    key !== STATIC_CACHE && key !== DYNAMIC_CACHE && key !== API_CACHE && key !== MESSAGES_CACHE
                );
                return Promise.all([
                    ...oldCaches.map((key) => caches.delete(key)),
                    self.clients.claim()
                ]);
            })
    );
});

// Обработка push-событий
self.addEventListener('push', (event) => {
    console.log('[SW] Push получен:', event);

    let data = {};
    
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            console.log('[SW] Ошибка парсинга данных push:', e);
            data = {
                title: 'Jetesk',
                body: 'Новое уведомление',
                icon: '/Jetesk.png',
                badge: '/Jetesk.png'
            };
        }
    }

    const title = data.title || 'Jetesk Мессенджер';
    const options = {
        body: data.body || 'У вас новое сообщение',
        icon: data.icon || '/Jetesk.png',
        badge: data.badge || '/Jetesk.png',
        vibrate: data.vibrate || [200, 100, 200],
        data: data.data || {},
        requireInteraction: data.requireInteraction || false,
        actions: [
            {
                action: 'open',
                title: 'Открыть',
                icon: '/Jetesk.png'
            },
            {
                action: 'close',
                title: 'Закрыть',
                icon: '/Jetesk.png'
            }
        ],
        tag: data.data?.message_id ? `message-${data.data.message_id}` : 'jetesk-notification',
        renotify: true
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// Обработка клика по уведомлению
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Клик по уведомлению:', event);
    
    event.notification.close();

    if (event.action === 'close') {
        return;
    }

    // Открываем приложение или фокусируем существующую вкладку
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((windowClients) => {
                // Ищем вкладку с нашим приложением
                const jeteskWindow = windowClients.find(
                    (client) => client.url.includes('/chat') || client.url === '/'
                );

                if (jeteskWindow && jeteskWindow.focus) {
                    return jeteskWindow.focus();
                }

                // Если нет открытой вкладки, открываем новую
                if (clients.openWindow) {
                    return clients.openWindow('/chat');
                }
            })
    );
});

// Обработка фоновой синхронизации (если поддерживается)
self.addEventListener('sync', (event) => {
    console.log('[SW] Sync событие:', event.tag);
    
    if (event.tag === 'send-message') {
        event.waitUntil(
            // Логика отправки сообщений при восстановлении соединения
            Promise.resolve()
        );
    }
});

// Перехват запросов - умное кэширование
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Пропускаем не-GET запросы
    if (request.method !== 'GET') {
        return;
    }

    // Пропускаем внешние запросы (кроме Google Analytics)
    if (url.origin !== self.location.origin && !url.hostname.includes('googletagmanager')) {
        return;
    }

    // API сообщений - Cache First с фоновым обновлением (24 часа)
    if (url.pathname.includes('/api/messages')) {
        event.respondWith(
            cacheFirstWithBackgroundUpdate(request, MESSAGES_CACHE, MESSAGES_CACHE_AGE)
        );
        return;
    }

    // Остальные API - Cache First с фоновым обновлением (7 дней)
    if (url.pathname.includes('/api/')) {
        event.respondWith(
            cacheFirstWithBackgroundUpdate(request, API_CACHE, MAX_CACHE_AGE)
        );
        return;
    }

    // Статические файлы - Cache First
    if (request.destination === 'image' ||
        request.destination === 'script' ||
        request.destination === 'style' ||
        request.destination === 'font') {
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    if (cached) {
                        // Проверяем возраст кэша
                        const cachedTime = new Date(cached.headers.get('sw-fetched-time') || Date.now()).getTime();
                        if (Date.now() - cachedTime < MAX_CACHE_AGE) {
                            console.log('[SW] Из кэша:', request.url);
                            return cached;
                        }
                    }
                    // Загружаем свежую версию
                    return fetch(request).then((response) => {
                        const responseClone = response.clone();
                        caches.open(STATIC_CACHE).then((cache) => {
                            const headers = new Headers(responseClone.headers);
                            headers.set('sw-fetched-time', new Date().toUTCString());
                            cache.put(request, responseClone);
                        });
                        return response;
                    });
                })
                .catch(() => {
                    console.log('[SW] Ошибка fetch:', request.url);
                    return new Response('', {status: 404});
                })
        );
        return;
    }

    // HTML страницы - Stale While Revalidate
    if (request.destination === 'document' || request.headers.get('accept')?.includes('text/html')) {
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    const fetchPromise = fetch(request).then((response) => {
                        const responseClone = response.clone();
                        caches.open(DYNAMIC_CACHE).then((cache) => {
                            cache.put(request, responseClone);
                        });
                        return response;
                    });
                    return cached || fetchPromise;
                })
                .catch(() => {
                    return caches.match('/index.html');
                })
        );
        return;
    }

    // Остальное - Stale While Revalidate
    event.respondWith(
        caches.match(request)
            .then((cached) => {
                const fetchPromise = fetch(request).then((response) => {
                    const responseClone = response.clone();
                    caches.open(DYNAMIC_CACHE).then((cache) => {
                        trimCache(DYNAMIC_CACHE, MAX_CACHE_SIZE);
                        cache.put(request, responseClone);
                    });
                    return response;
                });
                return cached || fetchPromise;
            })
            .catch(() => {
                console.log('[SW] Ошибка fetch:', request.url);
                return new Response('', {status: 404});
            })
    );
});

// Очистка кэша до максимального размера
function trimCache(cacheName, maxItems) {
    caches.open(cacheName).then((cache) => {
        cache.keys().then((keys) => {
            if (keys.length > maxItems) {
                cache.delete(keys[0]).then(() => trimCache(cacheName, maxItems));
            }
        });
    });
}

// Сохранение ответа в кэш с временной меткой
async function cacheResponse(cacheName, request, response) {
    const cache = await caches.open(cacheName);
    const headers = new Headers(response.headers);
    headers.set('sw-fetched-time', new Date().toUTCString());
    const clonedResponse = response.clone();
    await cache.put(request, clonedResponse);
}

// Проверка возраста кэша
function isCacheStale(cachedResponse, maxAge) {
    if (!cachedResponse) return true;
    const cachedTime = cachedResponse.headers.get('sw-fetched-time');
    if (!cachedTime) return true;
    const age = Date.now() - new Date(cachedTime).getTime();
    return age > maxAge;
}

// Cache First с фоновым обновлением
async function cacheFirstWithBackgroundUpdate(request, cacheName, maxAge) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);
    
    if (cached) {
        console.log(`[SW] ${cacheName}: из кэша`, request.url);
        
        // Если кэш ещё актуален, отдаём его
        if (!isCacheStale(cached, maxAge)) {
            // Фоновое обновление, если кэш старше 50% от maxAge
            const cachedTime = new Date(cached.headers.get('sw-fetched-time')).getTime();
            const age = Date.now() - cachedTime;
            if (age > maxAge * 0.5) {
                console.log(`[SW] ${cacheName}: фоновое обновление`, request.url);
                fetchAndCache(request, cacheName);
            }
            return cached;
        }
        
        // Кэш устарел — обновляем в фоне и отдаём старую версию
        console.log(`[SW] ${cacheName}: кэш устарел, обновляем в фоне`, request.url);
        fetchAndCache(request, cacheName);
        return cached;
    }
    
    // Кэша нет — загружаем из сети
    console.log(`[SW] ${cacheName}: загрузка из сети`, request.url);
    return fetchAndCache(request, cacheName);
}

// Загрузка из сети и сохранение в кэш
async function fetchAndCache(request, cacheName) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            await cacheResponse(cacheName, request, response);
        }
        return response;
    } catch (error) {
        console.log(`[SW] ${cacheName}: ошибка сети`, request.url, error);
        return new Response(JSON.stringify({error: 'offline'}), {
            status: 200,
            headers: {'Content-Type': 'application/json'}
        });
    }
}
