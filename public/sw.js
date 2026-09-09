// Tinarchy PWA Offline Service Worker (Stale-While-Revalidate App Shell)
const CACHE_NAME = 'tinarchy-app-v1';

const PRECACHE_ASSETS = [
    '/',
    '/settings',
    '/manifest.json',
    '/favicon.svg',
    '/favicon.png',
    '/favicon.ico',
    '/apple-touch-icon.png'
];

// Install: pre-cache critical app shell assets and activate immediately
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS);
        }).then(() => self.skipWaiting())
    );
});

// Activate: purge stale cache versions and take control of all open tabs
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch: Stale-While-Revalidate for app shell & static assets; Network-Only for dynamic APIs
self.addEventListener('fetch', (event) => {
    // Only intercept GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    const url = new URL(event.request.url);

    // Bypass caching for real-time telemetry, live SSE streams, and mutating REST APIs
    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/syncthing/') ||
        url.pathname.startsWith('/syncyomi/') ||
        url.pathname.startsWith('/socket')
    ) {
        return;
    }

    // HTML Navigation requests: Stale-While-Revalidate for 0ms instant startup
    if (event.request.mode === 'navigate' || (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'))) {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                const fetchPromise = fetch(event.request).then((networkResponse) => {
                    if (networkResponse && networkResponse.status === 200) {
                        const responseClone = networkResponse.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
                    }
                    return networkResponse;
                }).catch(() => cachedResponse);

                return cachedResponse || fetchPromise;
            })
        );
        return;
    }

    // Static assets (Icons, CSS, Manifest, Fonts, Images): Cache-First with network fallback
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(event.request).then((networkResponse) => {
                if (networkResponse && networkResponse.status === 200) {
                    const responseClone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
                }
                return networkResponse;
            }).catch(() => {
                return new Response('', { status: 408, statusText: 'Request timed out or offline' });
            });
        })
    );
});
