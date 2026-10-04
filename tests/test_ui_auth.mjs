/**
 * Headless front-end check for the v4.2 auth UI (Phase 2).
 *
 * static/index.html + static/app.js ကို jsdom ထဲ တင်ပြီး တကယ့် server နှင့်
 * login → admin panel → logout အထိ စမ်းသပ်သည် (browser မလိုပါ)။
 *
 *   npm install jsdom            # တစ်ကြိမ်သာ
 *   RECAP_DATA_DIR=/tmp/uidemo uvicorn app:app --port 8000 &
 *   python -m recapstudio.useradmin create demo --admin --password 'Night-Market-42'
 *   node tests/test_ui_auth.mjs http://127.0.0.1:8000 demo 'Night-Market-42'
 *
 * exit code 0 = အားလုံး အောင်မြင် (17 checks)
 */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = (process.argv[2] || process.env.RECAP_BASE_URL || 'http://127.0.0.1:8000')
  .replace(/\/$/, '');
const USERNAME = process.argv[3] || process.env.RECAP_USERNAME || 'kyaw';
const PASSWORD = process.argv[4] || process.env.RECAP_PASSWORD || '';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (!PASSWORD) {
  console.error('usage: node tests/test_ui_auth.mjs <base-url> <username> <password>');
  process.exit(2);
}
let checks = 0; const failures = [];
const check = (label, ok, detail = '') => {
  checks += 1;
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ' — ' + detail : ''}`);
  if (!ok) failures.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const waitFor = async (fn, ms = 6000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(100); }
  return false;
};

const html = fs.readFileSync(`${ROOT}/static/index.html`, 'utf8');
const appjs = fs.readFileSync(`${ROOT}/static/app.js`, 'utf8');

const vc = new VirtualConsole();
const jsErrors = [];
vc.on('jsdomError', (e) => jsErrors.push(String(e && e.message || e)));
vc.on('error', (...a) => jsErrors.push(a.map(String).join(' ')));

const dom = new JSDOM(html, {
  url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc,
});
const { window } = dom;
const doc = window.document;

// cookie jar shim (jsdom cannot talk to the network itself)
const jar = new Map();
window.fetch = async (input, opts = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url, BASE);
  const headers = new Headers(opts.headers || {});
  if (jar.size) headers.set('cookie', [...jar].map(([k, v]) => `${k}=${v}`).join('; '));
  const res = await fetch(url, { ...opts, headers, signal: opts.signal });
  const setCookies = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
  for (const raw of setCookies) {
    const kv = raw.split(';')[0];
    const i = kv.indexOf('=');
    const name = kv.slice(0, i).trim(); const value = kv.slice(i + 1);
    const dead = value === '' || value === '""' || /max-age=0/i.test(raw)
      || /expires=Thu, 01 Jan 1970/i.test(raw);
    if (dead) jar.delete(name);
    else jar.set(name, value);
    if (!/httponly/i.test(raw)) doc.cookie = dead ? `${name}=; Max-Age=0` : kv;
  }
  return res;
};
window.alert = () => {}; window.confirm = () => true; window.prompt = () => 'Brand-New-Pass-99';
window.URL.createObjectURL = () => 'blob:stub';
window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));

console.log('=== loading app.js in jsdom ===');
try {
  window.eval(appjs);
} catch (err) {
  check('app.js evaluates without throwing', false, String(err));
}
doc.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => doc.getElementById(id);
const visible = (el) => Boolean(el) && !el.classList.contains('hidden');

// ── 1. login gate ──────────────────────────────────────────────────────────
console.log('\n=== 1. sign-in gate ===');
check('app.js evaluated', jsErrors.length === 0, jsErrors.slice(0, 2).join(' | '));
const overlayShown = await waitFor(() => visible($('auth-overlay')));
check('login overlay appears for an anonymous visitor', overlayShown);
check('account chip hidden before login', !visible($('account-box')));
check('login form renders username + password',
  Boolean($('auth-username')) && Boolean($('auth-password')));

// wrong password first
$('auth-username').value = USERNAME;
$('auth-password').value = 'definitely-wrong-123';
$('auth-form').dispatchEvent(new window.Event('submit'));
const sawError = await waitFor(() => ($('auth-error').textContent || '').trim().length > 0, 8000);
check('wrong password shows an error, stays on the overlay',
  sawError && visible($('auth-overlay')), ($('auth-error').textContent || '').slice(0, 60));

// ── 2. real login ──────────────────────────────────────────────────────────
console.log('\n=== 2. login ===');
$('auth-username').value = USERNAME;
$('auth-password').value = PASSWORD;
$('auth-form').dispatchEvent(new window.Event('submit'));
const loggedIn = await waitFor(() => !visible($('auth-overlay')), 10000);
check('overlay closes after a correct password', loggedIn,
  ($('auth-error').textContent || '').slice(0, 80));
check('CSRF cookie is readable by the page', doc.cookie.includes('recap_csrf'));
check('account chip shows the username',
  visible($('account-box')) && ($('chip-account').textContent || '').includes(USERNAME),
  ($('chip-account').textContent || '').trim());
check('account settings card is visible', visible($('account-card')));
check('admin panel is visible for an admin', visible($('admin-card')));

// ── 3. admin panel ─────────────────────────────────────────────────────────
console.log('\n=== 3. admin panel ===');
const rowsLoaded = await waitFor(() => $('user-table').querySelectorAll('.user-row').length > 0, 8000);
check('user table lists accounts', rowsLoaded,
  `${$('user-table').querySelectorAll('.user-row').length} rows`);
const auditLoaded = await waitFor(
  () => ($('audit-log').textContent || '').includes('login'), 8000);
check('audit log populated', auditLoaded,
  ($('audit-log').textContent || '').split('\n')[0] || '');

$('new-username').value = 'uitest';
$('btn-random-pw').click();
check('random password button fills the field', ($('new-password').value || '').length >= 16);
$('btn-create-user').click();
const created = await waitFor(
  () => [...$('user-table').querySelectorAll('.user-row .uname')].some((n) => n.textContent === 'uitest'),
  8000);
check('admin can create a user from the UI', created);

// delete it again (first button group: 🔑 🚫 ⬆️ 🗑️)
const row = [...$('user-table').querySelectorAll('.user-row')]
  .find((r) => r.querySelector('.uname').textContent === 'uitest');
if (row) {
  const buttons = row.querySelectorAll('button');
  buttons[buttons.length - 1].click();
  const gone = await waitFor(
    () => ![...$('user-table').querySelectorAll('.user-row .uname')].some((n) => n.textContent === 'uitest'),
    8000);
  check('admin can delete a user from the UI', gone);
}

// ── 4. logout ──────────────────────────────────────────────────────────────
console.log('\n=== 4. logout ===');
$('btn-logout').click();
const loggedOut = await waitFor(() => visible($('auth-overlay')), 8000);
check('logout returns to the login overlay', loggedOut);
check('session cookie cleared', !jar.has('recap_session'), [...jar.keys()].join(','));

console.log('\n' + '='.repeat(58));
console.log(`${checks - failures.length}/${checks} checks passed`);
if (failures.length) console.log('FAILED: ' + failures.join(', '));
if (jsErrors.length) console.log('JS errors: ' + jsErrors.slice(0, 5).join(' | '));
process.exit(failures.length ? 1 : 0);
