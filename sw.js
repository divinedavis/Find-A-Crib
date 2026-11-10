// findacrib.com's service worker (owner, 2026-11-10: "implement repeat visits
// cache"). Four jobs, and nothing else is touched:
//
//   1. The map pages (/, /la/, /sf/, /dc/, /westchester/, /casa/): asked from
//      the network first; when it is down or takes over 3 s, the copy kept
//      from the last visit opens, so the site opens offline.
//   2. Same-origin scripts and styles, and the building data files (*.json at
//      the top of the site and under a city): served from the device at once
//      and refreshed in the background for the next visit, so a repeat visit
//      doesn't wait on 1-2 MB of buildings.
//   3. config.js (rotating keys): always the network when there is one.
//   4. Notifications: shows a push and opens its link when tapped.
//
// Never: /api/, /auth/, /dashboard, /report/, anything not a GET, and other
// sites (map tiles, Supabase, ads). Change VERSION to drop every cache.
const VERSION = "v1";
const PAGES = `fac-pages-${VERSION}`;
const FILES = `fac-files-${VERSION}`;
const KEEP = new Set([PAGES, FILES]);
const APP_PAGES = new Set(["/", "/la/", "/sf/", "/dc/", "/westchester/", "/casa/"]);
const PAGE_WAIT_MS = 3000;
const FILE_DAYS = 30;
const NEVER = /^\/(api|auth|dashboard|report|rent-stabilized)(\/|$)/;
const DATA = /^\/([a-z]{2,12}\/)?[a-z0-9_.-]+\.json$/i;
const CODE = /\.(js|css)$/i;

const pageKey = (url) => (url.pathname.endsWith("/index.html") ? url.pathname.slice(0, -10) : url.pathname);

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const response = await fetch("/", { cache: "no-cache" });
    if (response.ok) await (await caches.open(PAGES)).put("/", response);
    await self.skipWaiting();
  })().catch(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith("fac-") && !KEEP.has(name)) await caches.delete(name);
    // Files no page has asked for in a month (an old ?v= of a script).
    const files = await caches.open(FILES), cutoff = Date.now() - FILE_DAYS * 86_400_000;
    for (const request of await files.keys()) {
      const kept = await files.match(request);
      if (Number(kept?.headers.get("x-fac-used") || 0) < cutoff) await files.delete(request);
    }
    await self.registration.navigationPreload?.enable().catch(() => {});
    await self.clients.claim();
  })());
});

async function page(event, url) {
  const key = pageKey(url);
  const timeout = new Promise((resolve) => setTimeout(resolve, PAGE_WAIT_MS, null));
  const network = (async () => {
    const response = (await event.preloadResponse) || (await fetch(event.request));
    if (response.ok && response.type === "basic") event.waitUntil(caches.open(PAGES).then((c) => c.put(key, response.clone())).catch(() => {}));
    return response.status >= 500 ? null : response;
  })().catch(() => null);
  const first = await Promise.race([network, timeout]);
  if (first) return first;
  const kept = await (await caches.open(PAGES)).match(key);
  return kept || (await network) || Response.error();
}

/// A copy stamped with when it was last used, so stale ones can be pruned.
const stamped = async (response) => new Response(await response.blob(), {
  status: response.status, statusText: response.statusText,
  headers: (() => { const h = new Headers(response.headers); h.set("x-fac-used", String(Date.now())); return h; })(),
});

async function deviceThenRefresh(event) {
  const cache = await caches.open(FILES);
  const kept = await cache.match(event.request);
  const fresh = fetch(event.request).then(async (response) => {
    if (response.ok && response.type === "basic") await cache.put(event.request, await stamped(response.clone()));
    return response;
  });
  if (!kept) return fresh;
  event.waitUntil(fresh.catch(() => {}));
  return kept;
}

async function networkThenDevice(event) {
  const cache = await caches.open(FILES);
  try {
    const response = await fetch(event.request);
    if (response.ok && response.type === "basic") event.waitUntil(stamped(response.clone()).then((r) => cache.put(event.request, r)).catch(() => {}));
    return response;
  } catch (e) {
    return (await cache.match(event.request)) || Promise.reject(e);
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || NEVER.test(url.pathname) || url.pathname === "/sw.js") return;
  if (request.mode === "navigate") {
    if (APP_PAGES.has(pageKey(url))) event.respondWith(page(event, url));
    return;
  }
  if (url.pathname === "/config.js") return event.respondWith(networkThenDevice(event));
  if (DATA.test(url.pathname) || (CODE.test(url.pathname) && url.pathname.startsWith("/static/"))) event.respondWith(deviceThenRefresh(event));
});

// A notification the server sent (webpush.py): { title, body, url, tag }.
self.addEventListener("push", (event) => {
  let note = {};
  try {
    note = event.data?.json() || {};
  } catch {
    note = { body: event.data?.text() };
  }
  event.waitUntil(self.registration.showNotification(String(note.title || "Find A Crib").slice(0, 120), {
    body: String(note.body || "").slice(0, 300),
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: note.tag ? String(note.tag).slice(0, 80) : undefined,
    // This site's page, or the https page the alert is about (a lottery's
    // official listing, as the email links it): webpush.note() decides.
    data: { url: typeof note.url === "string" && ((note.url.startsWith("/") && !note.url.startsWith("//")) || note.url.startsWith("https://")) ? note.url : "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    // Another site's page opens in a new window; ours reuses an open tab.
    if (new URL(url).origin !== self.location.origin) return self.clients.openWindow(url);
    for (const client of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
      if ("focus" in client) {
        await client.focus();
        if ("navigate" in client) await client.navigate(url).catch(() => {});
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
