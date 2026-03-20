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
            Promise.resolve()
        );
    }
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
    const cloned = response.clone();
    const headers = new Headers(cloned.headers);
    headers.set('sw-fetched-time', new Date().toUTCString());
    return new Response(cloned.body, {
        status: cloned.status,
        statusText: cloned.statusText,
        headers: headers
    });
}

// Безопасное кэширование
function safeCachePut(cacheName, request, response) {
    if (!response || response.type === 'opaque') return Promise.resolve();
    return caches.open(cacheName)
        .then((cache) => {
            try {
                return cache.put(request, response.clone());
            } catch (e) {
                console.log('[SW] Ошибка кэширования:', request.url, e);
            }
        })
        .catch((err) => {
            console.log('[SW] Ошибка кэша:', err);
        });
}

// Фоновое обновление кэша
function backgroundFetch(request, cacheName) {
    // Не кэшируем внешние ресурсы
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }
    
    fetch(request)
        .then((response) => {
            if (response.ok) {
                safeCachePut(cacheName, request, addTimestampToResponse(response));
            }
        })
        .catch((err) => {
            console.log('[SW] Фоновое обновление не удалось:', request.url);
        });
}

// Перехват запросов - умное кэширование
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Пропускаем не-GET запросы
    if (request.method !== 'GET') {
        return;
    }

    // Внешние запросы - пропускаем (не кэшируем)
    if (url.origin !== self.location.origin) {
        return;
    }

    // API сообщений - Cache First с фоновым обновлением (как в Telegram/WhatsApp)
    if (url.pathname.includes('/api/messages')) {
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    if (cached && isCacheFresh(cached, MESSAGES_CACHE_AGE)) {
                        console.log('[SW] Сообщения из кэша:', request.url);
                        // Обновляем в фоне
                        backgroundFetch(request, MESSAGES_CACHE);
                        return cached;
                    }
                    // Если кэша нет или устарел - загружаем из сети
                    return fetch(request)
                        .then((response) => {
                            if (response.ok) {
                                const timestampedResponse = addTimestampToResponse(response);
                                safeCachePut(MESSAGES_CACHE, request, timestampedResponse);
                            }
                            return response;
                        })
                        .catch(() => {
                            // Offline - возвращаем из кэша даже если устарел
                            return caches.match(request);
                        });
                })
        );
        return;
    }

    // API запросы (остальные) - Cache First с фоновым обновлением
    if (url.pathname.includes('/api/')) {
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    if (cached && isCacheFresh(cached, MAX_CACHE_AGE)) {
                        console.log('[SW] API из кэша:', request.url);
                        backgroundFetch(request, API_CACHE);
                        return cached;
                    }
                    return fetch(request)
                        .then((response) => {
                            if (response.ok) {
                                const timestampedResponse = addTimestampToResponse(response);
                                safeCachePut(API_CACHE, request, timestampedResponse);
                            }
                            return response;
                        })
                        .catch(() => {
                            return caches.match(request);
                        });
                })
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
                    if (cached && isCacheFresh(cached, MAX_CACHE_AGE)) {
                        console.log('[SW] Статика из кэша:', request.url);
                        return cached;
                    }
                    return fetch(request)
                        .then((response) => {
                            if (response.ok) {
                                const timestampedResponse = addTimestampToResponse(response);
                                safeCachePut(STATIC_CACHE, request, timestampedResponse);
                            }
                            return response;
                        })
                        .catch(() => {
                            return caches.match(request);
                        });
                })
        );
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
                        });
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
                    });
                return cached || fetchPromise;
            })
            .catch(() => {
                return caches.match(request);
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
