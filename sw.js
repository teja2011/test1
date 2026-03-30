// Service Worker для PWA - кэширование, offline
const CACHE_NAME = 'jetesk-v3';
const STATIC_CACHE = 'jetesk-static-v3';
const DYNAMIC_CACHE = 'jetesk-dynamic-v3';
const API_CACHE = 'jetesk-api-v3';

const STATIC_ASSETS = [
    '/',
    '/index.html',
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

// Перехват запросов - умное кэширование
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Пропускаем не-GET запросы
    if (request.method !== 'GET') {
        return;
    }

    // Пропускаем ВСЕ внешние запросы (Google Tag Manager, аналитика, и т.д.)
    if (url.origin !== self.location.origin) {
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
                .catch((err) => {
                    console.log('[SW] API offline:', url.pathname, err);
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
        
        event.respondWith(
            caches.match(request)
                .then((cached) => {
                    if (cached) {
                        const cachedTime = new Date(cached.headers.get('sw-fetched-time') || Date.now()).getTime();
                        if (Date.now() - cachedTime < MAX_CACHE_AGE) {
                            return cached;
                        }
                    }
                    return fetch(request).then((response) => {
                        const responseClone = response.clone();
                        caches.open(STATIC_CACHE).then((cache) => {
                            const headers = new Headers(responseClone.headers);
                            headers.set('sw-fetched-time', new Date().toUTCString());
                            cache.put(request, responseClone);
                        });
                        return response;
                    }).catch((err) => {
                        console.log('[SW] Ошибка загрузки статики:', url.pathname, err);
                        return new Response('', {status: 404});
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
                    const fetchPromise = fetch(request).then((response) => {
                        const responseClone = response.clone();
                        caches.open(DYNAMIC_CACHE).then((cache) => {
                            cache.put(request, responseClone);
                        });
                        return response;
                    }).catch((err) => {
                        console.log('[SW] Ошибка загрузки HTML:', url.pathname, err);
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
                }).catch((err) => {
                    console.log('[SW] Ошибка fetch:', url.pathname, err);
                });
                return cached || fetchPromise;
            })
            .catch(() => {
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
