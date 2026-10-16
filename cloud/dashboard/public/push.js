// Web Push on this device. iOS delivers it only to a Home Screen web app.
import {api} from './api.js';

export const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
export const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
export const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

async function deviceId(endpoint) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

function keyBytes(base64url) {
  const text = atob(base64url.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(text, c => c.charCodeAt(0));
}

function sameKey(subscription, publicKey) {
  const current = subscription.options?.applicationServerKey;
  if (!current) return true;
  const a = new Uint8Array(current), b = keyBytes(publicKey);
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

function label() {
  const ua = navigator.userAgent;
  const device = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) || isIOS() ? 'iPad' : /Android/.test(ua) ? 'Android' : /Mac/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : 'Browser';
  const app = standalone() ? 'Home Screen app' : /Firefox/.test(ua) ? 'Firefox' : /Edg\//.test(ua) ? 'Edge' : /Chrome/.test(ua) ? 'Chrome' : 'Safari';
  return `${device}, ${app}`;
}

async function subscription() {
  if (!supported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return registration ? registration.pushManager.getSubscription() : null;
}

/** {available, reason, permission, enabled, id} for this device. */
export async function status(state) {
  if (!state.push?.public_key) return {available: false, reason: 'not_configured'};
  if (!supported()) return {available: false, reason: isIOS() && !standalone() ? 'install' : 'unsupported'};
  const current = await subscription();
  const id = current ? await deviceId(current.endpoint) : '';
  const known = !!id && (state.push.devices || []).some(d => d.id === id);
  return {available: true, permission: Notification.permission, enabled: known && Notification.permission === 'granted', id};
}

export async function enable(state) {
  if (await Notification.requestPermission() !== 'granted') throw Error('Notifications are blocked for this app. Allow them in the system settings.');
  const registration = await navigator.serviceWorker.ready;
  let current = await registration.pushManager.getSubscription();
  if (current && !sameKey(current, state.push.public_key)) { await current.unsubscribe(); current = null; }
  current ??= await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: keyBytes(state.push.public_key)});
  await api('push_subscribe', {subscription: current.toJSON(), label: label()});
}

export async function disable() {
  const current = await subscription();
  if (!current) return;
  await api('push_unsubscribe', {id: await deviceId(current.endpoint)});
  await current.unsubscribe();
}

/** Re-register silently if permission stands but the server lost this device or the key changed. */
export async function sync(state) {
  try {
    if (!state.push?.public_key || !supported() || Notification.permission !== 'granted') return;
    const current = await subscription();
    if (!current) return;
    const id = await deviceId(current.endpoint);
    if (!sameKey(current, state.push.public_key) || !(state.push.devices || []).some(d => d.id === id)) await enable(state);
  } catch { /* The Settings screen shows the state and offers a manual retry. */ }
}
