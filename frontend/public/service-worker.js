/* Service Worker for Web Push notifications in Obsidian AI Hub */

self.addEventListener('push', (event) => {
  if (!event.data) {
    return;
  }

  let payload = {};
  try {
    payload = event.data.json();
  } catch (err) {
    payload = {
      title: 'Obsidian AI Hub',
      body: event.data.text(),
      relative_link: '/',
    };
  }

  const title = payload.title || 'Obsidian AI Hub';
  const options = {
    body: payload.body || '',
    data: {
      relative_link: payload.relative_link || '/',
    },
    tag: payload.target_id || undefined,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const relativeLink = (event.notification.data && event.notification.data.relative_link) || '/';
  const targetUrl = new URL(relativeLink, self.location.origin).href;

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }
      for (const client of clientList) {
        if ('focus' in client && 'navigate' in client) {
          return client.focus().then(() => client.navigate(targetUrl));
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
