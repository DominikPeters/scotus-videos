// Server calls, passkeys and private preview images.
let csrf = '';
export const setCsrf = value => { csrf = value; };

export async function api(action, data = {}, get = false) {
  const response = await fetch(`api.php?action=${action}`, get ? {credentials: 'same-origin'} : {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(data),
  });
  let body;
  try { body = await response.json(); } catch { body = {error: 'The server returned an unexpected response'}; }
  if (!response.ok || !body.ok) {
    const error = Error(body.error || 'Request failed');
    error.status = response.status;
    throw error;
  }
  return body.result;
}

const bytes = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
const encoded = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export async function passkey(register) {
  const options = await api(register ? 'register_options' : 'login_options');
  options.publicKey.challenge = bytes(options.publicKey.challenge);
  if (register) {
    options.publicKey.user.id = bytes(options.publicKey.user.id);
    for (const credential of options.publicKey.excludeCredentials || []) credential.id = bytes(credential.id);
  } else {
    for (const credential of options.publicKey.allowCredentials || []) credential.id = bytes(credential.id);
  }
  const credential = await navigator.credentials[register ? 'create' : 'get'](options);
  const response = credential.response;
  const payload = {id: credential.id, clientDataJSON: encoded(response.clientDataJSON)};
  if (register) payload.attestationObject = encoded(response.attestationObject);
  else Object.assign(payload, {authenticatorData: encoded(response.authenticatorData), signature: encoded(response.signature)});
  const result = await api(register ? 'register' : 'login', payload);
  setCsrf(result.csrf);
}

// Private binary previews can use the browser's HTTP cache across page reloads.
// Four requests and a few cards of lookahead keep scrolling ahead of the network.
const urls = new Map(), pending = new Map(), queue = [];
let active = 0;

async function slot(task) {
  if (active >= 4) await new Promise(resolve => queue.push(resolve)); else active++;
  try { return await task(); } finally { const next = queue.shift(); if (next) next(); else active--; }
}

async function fetchPreview(request, key) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key));
  const query = new URLSearchParams({action: 'asset_image', ...request, version: encoded(digest)});
  const fetchImage = async () => {
    const response = await fetch(`api.php?${query}`, {credentials: 'same-origin'});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = Error(body.error || 'Preview unavailable'); error.status = response.status; throw error;
    }
    return response.blob();
  };
  try { return await fetchImage(); } catch (error) {
    if (error.status !== 503) throw error;
    await new Promise(resolve => setTimeout(resolve, 600));
    return fetchImage();
  }
}

/** request: {job, kind, person?, candidate?, variant?}; uri identifies the immutable object. */
export function previewKey(request, uri) {
  return [request.job, request.kind, request.person, request.candidate, request.variant, uri].join(':');
}

export const cachedPreview = key => urls.get(key);

export function loadPreview(key, request) {
  if (urls.has(key)) return Promise.resolve(urls.get(key));
  if (!pending.has(key)) {
    pending.set(key, slot(async () => {
      const blob = await fetchPreview(request, key);
      urls.set(key, URL.createObjectURL(blob));
      return urls.get(key);
    }).finally(() => pending.delete(key)));
  }
  return pending.get(key);
}

/** Downscale before upload; only a small portrait travels over the metered connection. */
export async function smallImage(file) {
  if (!file || !file.size) throw Error('Choose an image.');
  const bitmap = await createImageBitmap(file), canvas = document.createElement('canvas');
  const scale = Math.min(1, 1024 / Math.max(bitmap.width, bitmap.height));
  canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
  const context = canvas.getContext('2d');
  context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close();
  for (const quality of [.9, .8, .65, .5]) {
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (blob.size <= 131072) {
      const value = new Uint8Array(await blob.arrayBuffer()), parts = [];
      for (let i = 0; i < value.length; i += 32768) parts.push(String.fromCharCode(...value.subarray(i, i + 32768)));
      return btoa(parts.join(''));
    }
  }
  throw Error('The resized image is too large. Choose a smaller image.');
}
