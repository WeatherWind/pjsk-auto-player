// PJSK Auto Player — Service Worker (PWA)
// 缓存控制面板，支持离线使用和快速加载

const CACHE_NAME = 'pjsk-ap-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/manifest.json',
  '/status',
  '/stats',
];

// 安装：缓存静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// 网络优先策略 (API 数据不缓存)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 请求: 网络优先，失败则返回离线提示
  if (url.pathname.startsWith('/status') ||
      url.pathname.startsWith('/stats') ||
      url.pathname.startsWith('/screenshot') ||
      url.pathname.startsWith('/log') ||
      url.pathname.startsWith('/config') ||
      url.pathname.startsWith('/command') ||
      url.pathname.startsWith('/events')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ error: 'offline', message: '设备离线' }),
          { headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // 静态资源: 缓存优先
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        // 缓存成功的 GET 请求
        if (event.request.method === 'GET' && response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, clone);
          });
        }
        return response;
      });
    })
  );
});
