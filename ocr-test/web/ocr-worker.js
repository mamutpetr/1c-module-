// Мовні моделі опубліковані як base64-текст (*.traineddata.gz.b64.txt),
// бо хостинг не віддає .gz. Підміняємо fetch лише для них і запускаємо звичайний воркер.
const nativeFetch = self.fetch.bind(self);
self.fetch = async (url, opts) => {
  const u = String(url);
  if (!u.endsWith('.traineddata.gz')) return nativeFetch(url, opts);
  const resp = await nativeFetch(u + '.b64.txt', opts);
  if (!resp.ok) return resp;
  const bin = atob((await resp.text()).trim());
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Response(bytes);
};
importScripts('worker.min.js');
