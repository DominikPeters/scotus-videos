// Service worker: Web Push, notification taps, and an offline copy of the app shell.
const SHELL = 'shell-v9';
const FILES = ['./', 'app.css', 'main.js', 'api.js', 'dom.js', 'model.js', 'ui.js', 'push.js',
  'view-list.js', 'view-clips.js', 'view-case.js', 'view-settings.js', 'brand-icons.svg', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== SHELL).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

// Network first so a deployment shows up at once; the cached shell only covers a bad connection.
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || url.pathname.endsWith('/api.php')) return;
  event.respondWith((async () => {
    const cache = await caches.open(SHELL);
    try {
      const response = await fetch(event.request);
      if (response.ok && FILES.some(file => new URL(file, self.registration.scope).pathname === url.pathname)) {
        cache.put(url.pathname === new URL('./', self.registration.scope).pathname ? './' : event.request, response.clone());
      }
      return response;
    } catch (error) {
      const cached = await cache.match(event.request.mode === 'navigate' ? './' : event.request, {ignoreSearch: true});
      if (cached) return cached;
      throw error;
    }
  })());
});

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {body: event.data?.text()}; }
  const title = data.title || 'Scotus videos';
  const options = {
    body: data.body || 'Open the dashboard for details.',
    tag: data.tag || undefined,
    icon: 'icon-192.png',
    timestamp: data.at ? Date.parse(data.at) : Date.now(),
    data: {hash: data.hash || '#/', job: data.job || ''},
  };
  const badge = Number.isInteger(data.badge) && 'setAppBadge' in self.navigator
    ? (data.badge ? self.navigator.setAppBadge(data.badge) : self.navigator.clearAppBadge()).catch(() => {}) : null;
  event.waitUntil(Promise.all([self.registration.showNotification(title, options), badge]));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const hash = event.notification.data?.hash || '#/';
  const target = new URL('./' + hash, self.registration.scope).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    const open = windows.find(client => client.url.startsWith(self.registration.scope));
    if (open) {
      open.postMessage({type: 'open', hash});
      try { return await open.focus(); } catch { /* fall through and open a window */ }
    }
    return self.clients.openWindow(target);
  })());
});
