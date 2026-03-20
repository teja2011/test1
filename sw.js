// Service Worker для PWA - кэширование статики и offline поддержка
const CACHE_NAME = 'jetesk-v2';
const STATIC_CACHE = 'jetesk-static-v2';

const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/manifest.json',
    '/Jetesk.png'
];

const MAX_CACHE_AGE = 7 * 24 * 60 * 60 * 1000; // 7 дней

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
                    key !== STATIC_CACHE
                );
                return Promise.all([
                    ...oldCaches.map((key) => caches.delete(key)),
                    self.clients.claim()
                ]);
            })
    );
});

// Проверка возраста кэша
function isCacheFresh(response, maxAge) {
    if (!response) return false;
    const cachedTime = new Date(response.headers.get('sw-fetched-time') || Date.now()).getTime();
    return Date.now() - cachedTime < maxAge;
}

// Перехват запросов
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Пропускаем не-GET запросы (POST, PUT, DELETE и т.д.)
    if (request.method !== 'GET') {
        return;
    }

    // Внешние запросы - пропускаем (не кэшируем)
    if (url.origin !== self.location.origin) {
        return;
    }

    // API запросы - всегда сеть (для актуальных данных)
    if (url.pathname.includes('/api/')) {
        event.respondWith(
            fetch(request)
                .catch((err) => {
                    console.log('[SW] Offline API запрос:', request.url);
                    return new Response(JSON.stringify({error: 'offline'}), {
                        status: 503,
                        headers: {'Content-Type': 'application/json'}
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
                            if (response && response.ok) {
                                const headers = new Headers(response.headers);
                                headers.set('sw-fetched-time', new Date().toUTCString());
                                const newResponse = new Response(response.body, {
                                    status: response.status,
                                    statusText: response.statusText,
                                    headers: headers
                                });
                                caches.open(STATIC_CACHE).then((cache) => {
                                    cache.put(request, newResponse);
                                });
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

    // HTML страницы - Network First с fallback в кэш
    if (request.destination === 'document' || request.headers.get('accept')?.includes('text/html')) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response && response.ok) {
                        caches.open(STATIC_CACHE).then((cache) => {
                            cache.put(request, response.clone());
                        });
                    }
                    return response;
                })
                .catch(() => {
                    return caches.match(request);
                })
        );
        return;
    }

    // Остальное - Network First
    event.respondWith(
        fetch(request)
            .catch(() => {
                return caches.match(request);
            })
    );
});
