/**
 * v4.3.5 — subtitle text-box controls + per-user preferences (headless).
 *
 * Two things are checked here:
 *
 *  1. UX — the text-box controls now live INSIDE the Live Preview card, right
 *     under the video, instead of only in the step-3 card on the other side of
 *     the page ("Videos အပေါ် တတ်နေတာ နဲ့ subtitles tab နဲ့ ဝေးနေတယ်").
 *     Both places must stay in sync, whichever one the user touches.
 *
 *  2. Persistence — changing a control debounces a POST to /api/me/settings so
 *     the value is stored against the account (SQLite user_settings), and on
 *     boot the stored values are applied.
 *
 *   npm install jsdom          # once
 *   node tests/test_ui_subbox.mjs
 */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = 'http://127.0.0.1:8000';

let checks = 0; const failures = [];
const check = (label, ok, detail = '') => {
  checks += 1;
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ' — ' + detail : ''}`);
  if (!ok) failures.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const waitFor = async (fn, ms = 4000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(50); }
  return false;
};

const html = fs.readFileSync(`${ROOT}/static/index.html`, 'utf8');
const appjs = fs.readFileSync(`${ROOT}/static/app.js`, 'utf8');
const css = fs.readFileSync(`${ROOT}/static/styles.css`, 'utf8');

/* ── 0. static structure (no browser needed) ────────────────────────────── */
console.log('=== 0. markup / stylesheet ===');
const previewCard = html.slice(html.indexOf('id="preview-card"'), html.indexOf('id="job-card"'));
check('text-box controls live inside the Live Preview card',
  previewCard.includes('id="subbox"') && previewCard.includes('id="sub-pos"'));
check('the vertical position slider is there', /id="sub-pos"[^>]*type="range"|type="range"[^>]*id="sub-pos"/.test(previewCard.replace(/\n/g, ' ')));
check('a quick font-size slider is there', previewCard.includes('id="sub-font-quick"'));
check('preset buttons exist', (previewCard.match(/data-subpos=/g) || []).length >= 3,
  `${(previewCard.match(/data-subpos=/g) || []).length} presets`);
check('the save-state chip exists', previewCard.includes('id="subbox-saved"'));
check('the box is styled', /\.subbox\s*\{/.test(css) && /\.subbox-head\s*\{/.test(css));
check('the step-3 card still has the original font control', html.includes('id="sub-font"'));

/* ── jsdom boot with a stubbed API ──────────────────────────────────────── */
const vc = new VirtualConsole();
const jsErrors = [];
vc.on('jsdomError', (e) => jsErrors.push(String((e && e.message) || e)));

const dom = new JSDOM(html, {
  url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc,
});
const { window } = dom;
const doc = window.document;
const $ = (id) => doc.getElementById(id);

// what the "server" has stored for this account
const SERVER_PREFS = { sub_v_pos_percent: 61, sub_font_size: 56, sub_color_hex: '#ffd60a',
                       fill_mode: 'dialogue' };
const posts = [];        // every POST /api/me/settings body
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' }
});

window.fetch = async (input, opts = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url, BASE);
  const p = url.pathname;
  if (p === '/api/auth/me') {
    return json({ mode: 'open', required: false, authenticated: true, has_users: true, user: null });
  }
  if (p === '/api/system') {
    return json({ app_version: '4.3.5', ffmpeg: true, voices: { my: [{ id: 'thiha', label: 'မင်းသန့်' }] },
                  models: ['gemini-2.5-flash'], default_model: 'gemini-2.5-flash', api_keys: { keys: [] } });
  }
  if (p === '/api/me/settings') {
    if ((opts.method || 'GET').toUpperCase() === 'POST') {
      posts.push(JSON.parse(opts.body || '{}'));
      return json({ status: 'ok', settings: JSON.parse(opts.body || '{}') });
    }
    return json({ status: 'ok', settings: SERVER_PREFS, keys: Object.keys(SERVER_PREFS) });
  }
  if (p === '/api/tasks' && (opts.method || '').toUpperCase() === 'POST') {
    posts.push({ __task: true, ...JSON.parse(opts.body || '{}') });
    return json({ status: 'ok', task_id: 't1', queue: { busy: false } });
  }
  if (p === '/api/asset') return new Response('', { status: 200 });
  if (p === '/api/jobs') return json({ jobs: [] });
  if (p === '/api/config') return json({ access_ok: true, api_keys: { keys: [] } });
  return json({});
};
window.alert = () => {}; window.confirm = () => true;
window.URL.createObjectURL = () => 'blob:stub';
window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));

window.localStorage.setItem('rs_video', JSON.stringify({
  path: 'workspace/demo.mp4', name: 'demo.mp4', duration: 120, size: 10485760,
  width: 1920, height: 1080, previewUrl: '/api/asset?path=workspace/demo.mp4'
}));

const BOX_H = 520;
$('preview-wrap') && Object.defineProperty(window.HTMLElement.prototype, 'getBoundingClientRect', {
  configurable: true,
  value() {
    if (this.id === 'preview-wrap') {
      const [w, h] = ($('preview-frame').textContent.match(/(\d+)×(\d+)/) || [0, 9, 16]).slice(1);
      const height = BOX_H; const width = Math.round(height * (Number(w) / Number(h)));
      return { width, height, top: 0, left: 0, right: width, bottom: height, x: 0, y: 0 };
    }
    return { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0 };
  }
});

console.log('\n=== 1. boot applies the account settings from the server ===');
window.eval(appjs);
await sleep(400);

check('the app booted without a JS error', jsErrors.length === 0, jsErrors[0] || '');
check('slider shows the stored 61%', $('sub-pos').value === '61', `value=${$('sub-pos').value}`);
check('the preview caption actually moved to 61%',
  $('overlay-sub').style.bottom === '61%', `bottom=${$('overlay-sub').style.bottom}`);
check('the old readout agrees', $('lbl-sub-pos').textContent === '61', $('lbl-sub-pos').textContent);
check('the new readout agrees', $('lbl-sub-pos-v').textContent === '61', $('lbl-sub-pos-v').textContent);
check('font size applied from the server (56px)', $('sub-font').value === '56', $('sub-font').value);
check('the quick font slider mirrors it', $('sub-font-quick').value === '56', $('sub-font-quick').value);
check('the step-3 font label updated', $('lbl-font').textContent === '56', $('lbl-font').textContent);
check('dubbing mode applied from the server', $('fill-mode').value === 'dialogue', $('fill-mode').value);

console.log('\n=== 2. slider → preview (two-way sync) ===');
posts.length = 0;
$('sub-pos').value = '40';
$('sub-pos').dispatchEvent(new window.Event('input'));
await sleep(60);
check('dragging the slider moves the caption', $('overlay-sub').style.bottom === '40%',
  $('overlay-sub').style.bottom);
check('the step-3 readout follows the slider', $('lbl-sub-pos').textContent === '40',
  $('lbl-sub-pos').textContent);
check('the new readout follows too', $('lbl-sub-pos-v').textContent === '40');

console.log('\n=== 3. preset buttons ===');
const low = doc.querySelector('[data-subpos="12"]');
low.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await sleep(60);
check('"အောက်နီး" preset sets 12%', $('overlay-sub').style.bottom === '12%'
  && $('sub-pos').value === '12', `bottom=${$('overlay-sub').style.bottom} slider=${$('sub-pos').value}`);
doc.querySelector('[data-subpos="22"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await sleep(60);
check('"အလယ်" preset sets 22%', $('overlay-sub').style.bottom === '22%');

console.log('\n=== 4. font size stays in sync both ways ===');
$('sub-font-quick').value = '64';
$('sub-font-quick').dispatchEvent(new window.Event('input'));
await sleep(60);
check('quick slider updates the step-3 control', $('sub-font').value === '64', $('sub-font').value);
check('the label follows', $('lbl-font').textContent === '64', $('lbl-font').textContent);
$('sub-font').value = '30';
$('sub-font').dispatchEvent(new window.Event('input'));
await sleep(60);
check('step-3 control updates the quick slider', $('sub-font-quick').value === '30',
  $('sub-font-quick').value);

console.log('\n=== 5. debounced save to /api/me/settings ===');
const saved = await waitFor(() => posts.some((p) => !p.__task && typeof p.sub_v_pos_percent === 'number'), 3000);
check('a preference POST was sent', saved, `${posts.length} posts`);
const lastPrefs = [...posts].reverse().find((p) => !p.__task);
check('it carries the text-box position', lastPrefs && lastPrefs.sub_v_pos_percent === 22,
  JSON.stringify(lastPrefs && lastPrefs.sub_v_pos_percent));
check('it carries the font size', lastPrefs && lastPrefs.sub_font_size === 30,
  JSON.stringify(lastPrefs && lastPrefs.sub_font_size));
check('it carries the mode', lastPrefs && lastPrefs.fill_mode === 'dialogue');
check('the save chip says saved', $('subbox-saved').textContent === 'သိမ်းပြီး',
  $('subbox-saved').textContent);

console.log('\n=== 6. the job payload uses the same values ===');
posts.length = 0;
$('btn-start').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await waitFor(() => posts.some((p) => p.__task), 3000);
const task = posts.find((p) => p.__task);
check('the job payload carries the slider position',
  task && task.sub_v_pos_percent === 22, JSON.stringify(task && task.sub_v_pos_percent));
check('the job payload carries the font size', task && task.sub_font_size === 30,
  JSON.stringify(task && task.sub_font_size));

console.log('\n' + '='.repeat(58));
console.log(failures.length ? `${checks - failures.length}/${checks} checks passed`
                            : `${checks}/${checks} checks passed`);
if (failures.length) { console.log('FAILED: ' + failures.join(' | ')); process.exit(1); }
console.log('all good');
// jsdom keeps timers/polling alive, so without this the runner hangs until it
// is killed (and reports a timeout instead of a pass).
process.exit(0);
