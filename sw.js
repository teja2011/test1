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
const MAX_CACHE_AGE = 7 * 24 * 60 * 60 * 1000;
const MESSAGES_CACHE_AGE = 24 * 60 * 60 * 1000;

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
            { action: 'open', title: 'Открыть', icon: '/Jetesk.png' },
            { action: 'close', title: 'Закрыть', icon: '/Jetesk.png' }
        ],
        tag: data.data?.message_id ? `message-${data.data.message_id}` : 'jetesk-notification',
        renotify: true
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

// Обработка клика по уведомлению
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Клик по уведомлению:', event);
    event.notification.close();

    if (event.action === 'close') return;

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((windowClients) => {
                const jeteskWindow = windowClients.find(
                    (client) => client.url.includes('/chat') || client.url === '/'
                );
                if (jeteskWindow && jeteskWindow.focus) {
                    return jeteskWindow.focus();
                }
                if (clients.openWindow) {
                    return clients.openWindow('/chat');
                }
            })
    );
});

// Проверка возраста кэша
function isCacheFresh(response, maxAge) {
    if (!response) return false;
    const cachedTime = new Date(response.headers.get('sw-fetched-time') || Date.now()).getTime();
    return Date.now() - cachedTime < maxAge;
}

// Добавление временной метки к ответу
function addTimestampToResponse(response) {
    if (!response || !response.body) return response;
    try {
        const cloned = response.clone();
        const headers = new Headers(cloned.headers);
        headers.set('sw-fetched-time', new Date().toUTCString());
        return new Response(cloned.body, {
            status: cloned.status,
            statusText: cloned.statusText,
            headers: headers
        });
    } catch (e) {
        return response;
    }
}

// Безопасное кэширование
function safeCachePut(cacheName, request, response) {
    if (!response || response.type === 'opaque' || response.status !== 200) {
        return Promise.resolve();
    }
    return caches.open(cacheName)
        .then((cache) => {
            try {
                return cache.put(request, response.clone());
            } catch (e) {
                // Игнорируем ошибки кэширования
            }
        })
        .catch((err) => {
            // Игнорируем ошибки кэша
        });
}

// Фоновое обновление кэша
function backgroundFetch(request, cacheName) {
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;
    
    fetch(request)
        .then((response) => {
            if (response.ok) {
                safeCachePut(cacheName, request, addTimestampToResponse(response));
            }
        })
        .catch((err) => {
            // Игнорируем ошибки фонового обновления
        });
}

// Обработчик fetch с правильной обработкой ошибок
function handleFetch(request, cacheName, maxAge) {
    return caches.match(request)
        .then((cached) => {
            if (cached && isCacheFresh(cached, maxAge)) {
                console.log('[SW] Из кэша:', request.url);
                backgroundFetch(request, cacheName);
                return cached;
            }
            
            return fetch(request)
                .then((response) => {
                    // Проверяем, что ответ корректный
                    if (!response || response.status !== 200) {
                        return cached || response;
                    }
                    
                    const timestampedResponse = addTimestampToResponse(response);
                    safeCachePut(cacheName, request, timestampedResponse);
                    return response;
                })
                .catch((err) => {
                    // При network error возвращаем кэш
                    console.log('[SW] Network error, возвращаем кэш:', request.url);
                    return cached || new Response(JSON.stringify({error: 'offline'}), {
                        status: 503,
                        headers: {'Content-Type': 'application/json'}
                    });
                });
        })
        .catch((err) => {
            console.log('[SW] Ошибка кэша:', request.url);
            return fetch(request).catch(() => 
                new Response(JSON.stringify({error: 'offline'}), {
                    status: 503,
                    headers: {'Content-Type': 'application/json'}
                })
            );
        });
}

// Перехват запросов
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Пропускаем не-GET запросы
    if (request.method !== 'GET') return;

    // Внешние запросы - пропускаем
    if (url.origin !== self.location.origin) return;

    // API сообщений - Cache First
    if (url.pathname.includes('/api/messages')) {
        event.respondWith(handleFetch(request, MESSAGES_CACHE, MESSAGES_CACHE_AGE));
        return;
    }

    // Остальные API - Cache First
    if (url.pathname.includes('/api/')) {
        event.respondWith(handleFetch(request, API_CACHE, MAX_CACHE_AGE));
        return;
    }

    // Статические файлы - Cache First
    if (request.destination === 'image' ||
        request.destination === 'script' ||
        request.destination === 'style' ||
        request.destination === 'font') {
        event.respondWith(handleFetch(request, STATIC_CACHE, MAX_CACHE_AGE));
        return;
    }

    // HTML страницы - Stale While Revalidate
    if (request.destination === 'document' || request.headers.get('accept')?.includes('text/html')) {
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    const fetchPromise = fetch(request)
                        .then((response) => {
                            if (response && response.ok) {
                                safeCachePut(DYNAMIC_CACHE, request, response.clone());
                            }
                            return response;
                        })
                        .catch(() => cached);
                    return cached || fetchPromise;
                })
        );
        return;
    }

    // Остальное - Stale While Revalidate
    event.respondWith(
        caches.match(request)
            .then((cached) => {
                const fetchPromise = fetch(request)
                    .then((response) => {
                        if (response && response.ok) {
                            safeCachePut(DYNAMIC_CACHE, request, response.clone());
                        }
                        return response;
                    })
                    .catch(() => cached);
                return cached || fetchPromise;
            })
            .catch(() => caches.match(request))
    );
});

// Очистка кэша
function trimCache(cacheName, maxItems) {
    caches.open(cacheName).then((cache) => {
        cache.keys().then((keys) => {
            if (keys.length > maxItems) {
                cache.delete(keys[0]).then(() => trimCache(cacheName, maxItems));
            }
        });
    });
}
