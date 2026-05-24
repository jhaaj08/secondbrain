const CACHE = 'second-brain-v1';

// Cache only the app shell on install
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.add('/')));
  self.skipWaiting();
});

// Remove old caches on activate
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first for all API calls, cache-first for the app shell
self.addEventListener('fetch', e => {
  // Ignore non-HTTP requests (chrome-extension://, blob:, etc.)
  if (!e.request.url.startsWith('http')) return;

  const { pathname } = new URL(e.request.url);
  const isApi = ['/cards', '/quiz', '/stats', '/health', '/admin']
    .some(p => pathname.startsWith(p));

  if (isApi || e.request.method !== 'GET') {
    e.respondWith(
      fetch(e.request.clone()).catch(() => new Response('Offline', { status: 503 }))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
