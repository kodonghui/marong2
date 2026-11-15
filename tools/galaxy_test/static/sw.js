// 홈 화면 앱 설치용 최소 서비스 워커. 아무것도 캐시하지 않아요(기능 명세 SPEC-027).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(fetch(event.request));
});
