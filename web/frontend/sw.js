const CACHE='agrovision-static-v4';
const FILES=['/static/css/style.css','/static/js/app.js','/static/assets/icon.svg','/static/assets/icon-192.png','/static/assets/icon-512.png','/static/assets/hero-tomatoes.jpg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==self.location.origin)return;if(u.pathname.startsWith('/apiv2/')||u.pathname.startsWith('/media/')||u.pathname.startsWith('/samples/'))return;if(u.pathname.startsWith('/static/'))e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
