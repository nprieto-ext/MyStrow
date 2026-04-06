'use strict';
const CACHE = 'mystrow-v1';
const PRECACHE = ['/', '/manifest.json', '/icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = e.request.url;
  // SSE et API : toujours réseau (pas de cache)
  if (url.includes('/stream') || url.includes('/api/') || url.includes('/ping')) {
    e.respondWith(fetch(e.request));
    return;
  }
  // Reste : réseau d'abord, cache en fallback
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
