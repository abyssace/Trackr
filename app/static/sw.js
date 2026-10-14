const CACHE_NAME = 'trackr-static-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Nunca cachear respuestas de la API.
  if (event.request.url.startsWith(self.location.origin + '/api/')) {
    return;
  }

  // Para el resto se usa red primero (sin cachear por defecto).
  event.respondWith(fetch(event.request));
});
