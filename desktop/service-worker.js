// Replaced with a content fingerprint while the image is built. Each waiting
// worker therefore stages a private cache and cannot overwrite the active
// session's assets before the user accepts the update.
const CACHE_VERSION = 'vibestack-desktop-__VIBESTACK_SHELL_CACHE_VERSION__';
// This is the complete static ES-module graph imported by noVNC 1.7.0's
// public RFB entry point. Keep it in lockstep with the pinned archive hash.
const NOVNC_ASSETS = [
  '/novnc/core/base64.js',
  '/novnc/core/crypto/aes.js',
  '/novnc/core/crypto/bigint.js',
  '/novnc/core/crypto/crypto.js',
  '/novnc/core/crypto/des.js',
  '/novnc/core/crypto/dh.js',
  '/novnc/core/crypto/md5.js',
  '/novnc/core/crypto/rsa.js',
  '/novnc/core/decoders/copyrect.js',
  '/novnc/core/decoders/h264.js',
  '/novnc/core/decoders/hextile.js',
  '/novnc/core/decoders/jpeg.js',
  '/novnc/core/decoders/raw.js',
  '/novnc/core/decoders/rre.js',
  '/novnc/core/decoders/tight.js',
  '/novnc/core/decoders/tightpng.js',
  '/novnc/core/decoders/zlib.js',
  '/novnc/core/decoders/zrle.js',
  '/novnc/core/deflator.js',
  '/novnc/core/display.js',
  '/novnc/core/encodings.js',
  '/novnc/core/inflator.js',
  '/novnc/core/input/domkeytable.js',
  '/novnc/core/input/fixedkeys.js',
  '/novnc/core/input/gesturehandler.js',
  '/novnc/core/input/keyboard.js',
  '/novnc/core/input/keysym.js',
  '/novnc/core/input/keysymdef.js',
  '/novnc/core/input/util.js',
  '/novnc/core/input/vkeys.js',
  '/novnc/core/input/xtscancodes.js',
  '/novnc/core/ra2.js',
  '/novnc/core/rfb.js',
  '/novnc/core/util/browser.js',
  '/novnc/core/util/cursor.js',
  '/novnc/core/util/element.js',
  '/novnc/core/util/events.js',
  '/novnc/core/util/eventtarget.js',
  '/novnc/core/util/int.js',
  '/novnc/core/util/logging.js',
  '/novnc/core/util/strings.js',
  '/novnc/core/websock.js',
  '/novnc/vendor/pako/lib/utils/common.js',
  '/novnc/vendor/pako/lib/zlib/adler32.js',
  '/novnc/vendor/pako/lib/zlib/crc32.js',
  '/novnc/vendor/pako/lib/zlib/deflate.js',
  '/novnc/vendor/pako/lib/zlib/inffast.js',
  '/novnc/vendor/pako/lib/zlib/inflate.js',
  '/novnc/vendor/pako/lib/zlib/inftrees.js',
  '/novnc/vendor/pako/lib/zlib/messages.js',
  '/novnc/vendor/pako/lib/zlib/trees.js',
  '/novnc/vendor/pako/lib/zlib/zstream.js',
];
const SHELL_ASSETS = [
  '/',
  '/vnc/',
  '/vnc/index.html',
  '/vnc/app.css',
  '/vnc/app.js',
  '/vnc/walkthrough.js',
  '/vnc/navigation.js',
  '/launcher.css',
  '/launcher.js',
  '/launcher.js?v=desktop-default-1',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-maskable.svg',
  '/icons/icon-180.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
  ...NOVNC_ASSETS,
];

const NEVER_CACHE_PREFIXES = [
  '/api/',
  '/terminal/',
  '/setup/',
];

function isForbidden(url) {
  return url.pathname === '/vnc/websockify'
    || NEVER_CACHE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
}

function isShellAsset(url) {
  return url.pathname === '/'
    || url.pathname === '/launcher.css'
    || url.pathname === '/launcher.js'
    || url.pathname.startsWith('/vnc/')
    || url.pathname.startsWith('/novnc/core/')
    || url.pathname.startsWith('/novnc/vendor/')
    || url.pathname.startsWith('/icons/')
    || url.pathname === '/manifest.webmanifest';
}

function canStore(response) {
  return response && response.ok && (response.type === 'basic' || response.type === 'default');
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    await cache.addAll(SHELL_ASSETS.map((path) => new Request(path, { cache: 'reload' })));
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith('vibestack-desktop-') && name !== CACHE_VERSION).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const response = await fetch(request);
    if (canStore(response)) await cache.put(request, response.clone());
    return response;
  } catch (_error) {
    return (await cache.match(request))
      || (await cache.match('/vnc/'))
      || new Response('VibeStack Desktop is offline. Reconnect to reach the remote desktop.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (canStore(response)) await cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || isForbidden(url)) return;

  if (request.mode === 'navigate') {
    if (url.pathname === '/' || url.pathname === '/vnc' || url.pathname.startsWith('/vnc/')) event.respondWith(networkFirst(request));
    return;
  }
  if (url.pathname.startsWith('/vnc/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith(networkFirst(request));
  } else if (isShellAsset(url)) {
    event.respondWith(cacheFirst(request));
  }
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
