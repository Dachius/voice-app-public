// Minimal service worker: makes the app installable; network-first, no offline caching of API traffic.
const CACHE = "voice-app-v2";
self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => clients.claim())); });
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && url.pathname.startsWith("/static/")) { const c = r.clone(); caches.open(CACHE).then((k) => k.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
