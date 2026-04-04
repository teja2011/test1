// Service Worker для PWA - кэширование, offline, push
const CACHE_NAME = 'jetesk-v2';
const STATIC_CACHE = 'jetesk-static-v2';
const DYNAMIC_CACHE = 'jetesk-dynamic-v2';
const API_CACHE = 'jetesk-api-v2';

const STATIC_ASSETS = [
    '/manifest.json',
    '/Jetesk.png'
];

const MAX_CACHE_SIZE = 50;
const MAX_CACHE_AGE = 7 * 24 * 60 * 60 * 1000; // 7 дней

// Установка Service Worker
self.addEventListener('install', (event) => {
    console.log('[SW] Install');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Кэширование статики');
                // Кэшируем только основные файлы, игнорируя ошибки
                return Promise.all(
                    STATIC_ASSETS.map(url => {
                        return fetch(url)
                            .then(response => {
                                if (response.ok) {
                                    return cache.put(url, response);
                                }
                            })
                            .catch(err => {
                                console.log('[SW] Не закэшировано:', url, err);
                            });
                    })
                );
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
                    key !== STATIC_CACHE && key !== DYNAMIC_CACHE && key !== API_CACHE
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

    // Определяем тип уведомления
    const isCall = data.data && data.data.type === 'incoming_call';

    const title = data.title || 'Jetesk Мессенджер';
    const options = {
        body: data.body || 'У вас новое сообщение',
        icon: data.icon || '/Jetesk.png',
        badge: data.badge || '/Jetesk.png',
        vibrate: isCall ? [500, 200, 500, 200, 500, 200, 500] : (data.vibrate || [200, 100, 200]),
        data: data.data || {},
        requireInteraction: data.requireInteraction !== undefined ? data.requireInteraction : isCall,
        actions: isCall ? [
            {
                action: 'answer',
                title: '📞 Ответить',
                icon: '/Jetesk.png'
            },
            {
                action: 'reject',
                title: '✕ Отклонить',
                icon: '/Jetesk.png'
            },
            {
                action: 'open',
                title: 'Открыть чат',
                icon: '/Jetesk.png'
            }
        ] : [
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
        tag: data.data?.call_id ? `call-${data.data.call_id}` : (data.data?.message_id ? `message-${data.data.message_id}` : 'jetesk-notification'),
        renotify: data.renotify !== undefined ? data.renotify : true,
        silent: false
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// Обработка клика по уведомлению
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Клик по уведомлению:', event);

    event.notification.close();

    const callData = event.notification.data;
    const isCall = callData && callData.type === 'incoming_call';

    if (isCall) {
        if (event.action === 'answer') {
            // Открываем чат — приложение обработит входящий
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
            return;
        }

        if (event.action === 'reject') {
            // Отклоняем звонок через API
            if (callData.call_id) {
                event.waitUntil(
                    fetch('/api/call/reject', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ call_id: callData.call_id }),
                        credentials: 'include'
                    })
                );
            }
            return;
        }
    }

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

    // Пропускаем chrome-error:// и другие не-http запросы
    if (!url.protocol.startsWith('http')) {
        return;
    }

    // Навигационные запросы - полностью пропускаем, пусть браузер обрабатывает сам
    // Это решает проблему с редиректами Vercel
    if (request.mode === 'navigate' || request.destination === 'document' || request.headers.get('accept')?.includes('text/html')) {
        return;
    }

    // Пропускаем внешние запросы (кроме Google Analytics)
    if (url.origin !== self.location.origin && !url.hostname.includes('googletagmanager')) {
        return;
    }

    // API запросы - Network First с fallback в кэш
    if (url.pathname.includes('/api/')) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    // Клонируем ответ для кэширования
                    const responseClone = response.clone();
                    caches.open(API_CACHE).then((cache) => {
                        cache.put(request, responseClone);
                    });
                    return response;
                })
                .catch(() => {
                    // Offline - возвращаем из кэша
                    return caches.match(request).then((cached) => {
                        return cached || new Response(JSON.stringify({error: 'offline'}), {
                            status: 200,
                            headers: {'Content-Type': 'application/json'}
                        });
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
        // Пропускаем внешние скрипты (Google Tag Manager и др.)
        if (request.url.includes('googletagmanager') || request.url.includes('google-analytics')) {
            return;
        }

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

    // API запросы - Network First с fallback в кэш
    if (url.pathname.includes('/api/')) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const responseClone = response.clone();
                    caches.open(API_CACHE).then((cache) => {
                        cache.put(request, responseClone);
                    });
                    return response;
                })
                .catch(() => {
                    return caches.match(request).then((cached) => {
                        return cached || new Response(JSON.stringify({error: 'offline'}), {
                            status: 200,
                            headers: {'Content-Type': 'application/json'}
                        });
                    });
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
