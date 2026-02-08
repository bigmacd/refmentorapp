/**
 * Service Worker for Referee Mentor System PWA
 * Caches static assets for offline availability
 * Includes OneSignal for push notifications
 *
 * IMPORTANT: Navigation requests (/, /login, etc.) use network-first to avoid
 * serving stale redirects that cause auth loops. Static assets use cache-first.
 */

importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");

const CACHE_NAME = 'ref-mentor-v3';

// Static assets to pre-cache on install (exclude / and /login - they must always be fresh)
const PRECACHE_URLS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/favicon-32x32.png',
  '/static/icons/favicon-16x16.png',
  '/static/icons/apple-touch-icon.png'
];

// Install: pre-cache static assets only
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
      .catch((err) => console.warn('Service worker pre-cache failed:', err))
  );
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: network-first for navigation, cache-first for static assets
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  if (!event.request.url.startsWith('http')) return;

  const url = new URL(event.request.url);
  const isNavigation = event.request.mode === 'navigate';

  // Navigation requests: always try network first to get correct auth state
  if (isNavigation) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache the response for offline fallback (clone since we consume the body)
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => {
          // Offline: serve cached page or fallback
          return caches.match(event.request).then((cached) =>
            cached || new Response(
              '<h1>Offline</h1><p>Please check your connection and try again.</p>',
              { headers: { 'Content-Type': 'text/html' } }
            )
          );
        })
    );
    return;
  }

  // Static assets: cache-first
  event.respondWith(
    caches.match(event.request)
      .then((cached) => cached || fetch(event.request))
      .catch(() => { throw new Error('Offline'); })
  );
});
