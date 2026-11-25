'use strict';

const NOTICE_HASH = /^#notice=[A-Za-z0-9_-]{48,768}$/;
const NOTICE_TAG = /^[A-Za-z0-9_-]{24}$/;
const APPROVED_BODY = new Set(['새 답변이 있어.', '새 선톡이 있어.', '일정 알림이 있어.', '약속 전화 알림이 있어.']);
const DEDUP_MS = 3 * 60 * 60 * 1000;

function noticeURL(value) {
  if (typeof value !== 'string' || value.length > 1024) return null;
  try {
    const url = new URL(value);
    if (url.origin === self.location.origin && url.pathname === '/chat/' && !url.search &&
        !url.username && !url.password && NOTICE_HASH.test(url.hash)) return url;
  } catch { /* malformed or relative URL */ }
  return null;
}

function notification(payload) {
  const n = payload?.notification;
  if (payload?.web_push !== 8030 || !n || n.title !== '마롱이' || n.lang !== 'ko' ||
      n.renotify !== false || !APPROVED_BODY.has(n.body) || !NOTICE_TAG.test(n.tag)) return null;
  const url = noticeURL(n.navigate);
  return url && {title: n.title, body: n.body, lang: n.lang, tag: n.tag, navigate: url.href};
}

function openTags() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('marong-notification-tags', 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('tags', {keyPath: 'tag'}).createIndex('expires', 'expires');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function changeTag(tag, release = false) {
  const db = await openTags();
  try {
    return await new Promise((resolve, reject) => {
      const now = Date.now();
      const tx = db.transaction('tags', 'readwrite');
      const store = tx.objectStore('tags');
      let claimed = false;
      tx.oncomplete = () => resolve(claimed);
      tx.onabort = tx.onerror = () => reject(tx.error);
      const cursor = store.index('expires').openCursor(IDBKeyRange.upperBound(now));
      cursor.onsuccess = () => {
        const expired = cursor.result;
        if (expired) { expired.delete(); expired.continue(); }
      };
      if (release) {
        store.delete(tag);
      } else {
        const read = store.get(tag);
        read.onsuccess = () => {
          if (read.result?.expires > now) return;
          claimed = true;
          store.put({tag, expires: now + DEDUP_MS});
        };
      }
    });
  } finally {
    db.close();
  }
}

self.addEventListener('push', event => {
  event.waitUntil((async () => {
    let content;
    try { content = notification(event.data?.json()); } catch { return; }
    if (!content) return;
    let claimed;
    try { claimed = await changeTag(content.tag); } catch { return; }
    if (!claimed) return;
    try {
      await self.registration.showNotification(content.title, {
        body: content.body, lang: content.lang, tag: content.tag, renotify: false,
        data: {navigate: content.navigate},
      });
    } catch (error) {
      await changeTag(content.tag, true);
      throw error;
    }
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const url = noticeURL(event.notification.data?.navigate);
    if (!url) return;
    const current = (await self.clients.matchAll({type: 'window', includeUncontrolled: false}))
      .find(client => new URL(client.url).origin === url.origin && new URL(client.url).pathname === '/chat/');
    if (current) {
      const navigated = await current.navigate(url.href);
      if (navigated) { await navigated.focus(); return; }
    }
    await self.clients.openWindow(url.href);
  })());
});

self.addEventListener('pushsubscriptionchange', event => {
  event.waitUntil((async () => {
    for (const client of await self.clients.matchAll({type: 'window', includeUncontrolled: false})) {
      client.postMessage({type: 'marong-web-push-subscription-changed'});
    }
  })());
});
