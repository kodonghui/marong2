const CACHE = 'marong-pet-shell-v3';
const SHELL = '/';
const FILES = ['/static/pet.css', '/static/pet.js', '/static/home.js', '/static/creation.js',
  '/static/member.js', '/static/diary.js', '/static/report.js', '/static/pet.webmanifest', '/static/pet-icon.png', '/static/pet-welcome.webp'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll([SHELL, ...FILES])));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('marong-pet-shell-') && key !== CACHE).map(key => caches.delete(key)),
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const {request} = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/internal/')) return;
  if (request.mode === 'navigate' && !url.pathname.startsWith('/static/')) {
    event.respondWith(fetch(request).catch(() => caches.match(SHELL)));
  } else if (FILES.includes(url.pathname)) {
    event.respondWith(fetch(request).catch(() => caches.match(url.pathname)));
  }
});

function safePath(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/';
  try {
    const url = new URL(value, self.location.origin);
    if (url.origin === self.location.origin && !/^\/(api|internal)\//.test(url.pathname)) return url.pathname + url.search + url.hash;
  } catch {}
  return '/';
}

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() ?? {}; } catch {}
  if (typeof data.title !== 'string' || typeof data.body !== 'string') return;
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, data: {url: safePath(data.url)}, icon: '/static/pet-icon.png',
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(safePath(event.notification.data?.url)));
});
