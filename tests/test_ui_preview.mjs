/**
 * Headless front-end check for the v4.3 preview + responsive pass.
 *
 * static/index.html + static/app.js ကို jsdom ထဲတင်ပြီး
 *   · Live Preview box သည် ထွက်မည့် ဖရိမ် (9:16 / 1:1 / 16:9 / မူရင်း) အတိုင်း
 *     အချိုးအစား ပြောင်းသလား
 *   · စာတန်း / hook စာလုံးအရွယ် သည် ffmpeg (ASS PlayRes) တွက်ချက်မှုနှင့် ကိုက်သလား
 *   · Logo နေရာချမှု သည် overlay=(W-w)·p နှင့် ကိုက်သလား
 *   · Shorts Splitter အပိုင်းကို "Studio သို့ ပို့မည်" နှိပ်လျှင် Studio သို့
 *     တကယ် ရောက်သလား
 * ကို server မလိုဘဲ (fetch ကို stub လုပ်၍) စစ်ဆေးသည်။
 *
 *   npm install jsdom          # တစ်ကြိမ်သာ
 *   node tests/test_ui_preview.mjs
 *
 * exit code 0 = အားလုံး အောင်မြင် (31 checks)
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

/* ── 0. CSS regression guards (no browser needed) ───────────────────────── */
console.log('=== 0. stylesheet ===');
const previewBlock = css.slice(css.indexOf('.preview-wrap {'), css.indexOf('.preview-wrap video'));
check('.preview-wrap no longer hard-codes 9:16',
  !/aspect-ratio:\s*9\s*\/\s*16\s*;/.test(previewBlock), previewBlock.split('\n')[4] || '');
check('preview width derives from the height budget (ratio can never squash)',
  /max-width:\s*calc\(var\(--preview-max-h\)/.test(previewBlock));
check('--preview-max-h is responsive', (css.match(/--preview-max-h:/g) || []).length >= 4,
  `${(css.match(/--preview-max-h:/g) || []).length} declarations`);
check('phone + tablet + small-phone breakpoints exist',
  /max-width:\s*1024px/.test(css) && /max-width:\s*620px/.test(css) && /max-width:\s*430px/.test(css));
check('touch targets handled (pointer: coarse)', /@media \(pointer: coarse\)/.test(css));
check('landscape phones handled', /orientation: landscape/.test(css));
check('iOS zoom-on-focus prevented (16px controls)',
  /input\[type=text\][^}]*font-size:\s*16px/.test(css));
check('stacked layout re-orders cards (upload → preview → settings)',
  /\.grid\.studio > div \{ display: contents; \}/.test(css)
  && /#preview-card \{ order: 2; \}/.test(css));
check('sticky mobile One-Click bar is phone/tablet only',
  /\.mobile-run-bar \{[^}]*display: none/.test(css)
  && /@media \(max-width: 1200px\) \{ \.mobile-run-bar\.show \{ display: block; \} \}/.test(css));

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

const SPLIT_PARTS = [{
  part: 1, filename: 'clip_part_1.mp4', url: '/api/download/clip_part_1.mp4',
  preview_url: '/api/asset?path=outputs/clip_part_1.mp4',
  path: 'outputs/clip_part_1.mp4', width: 720, height: 1280, duration: 60, size: 4194304
}];

// Node's global Response/Headers (jsdom does not implement fetch itself)
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
    return json({
      app_version: '4.3.0', ffmpeg: true, voices: { my: [{ id: 'thiha', label: 'မင်းသန့်' }] },
      models: ['gemini-2.5-flash'], default_model: 'gemini-2.5-flash', api_keys: { keys: [] }
    });
  }
  if (p === '/api/asset') return new Response('', { status: 200 });
  if (p === '/api/split-video') return json({ parts: SPLIT_PARTS });
  if (p === '/api/jobs') return json({ jobs: [] });
  if (p === '/api/config') return json({ access_ok: true, api_keys: { keys: [] } });
  return json({});
};
window.alert = () => {}; window.confirm = () => true;
window.URL.createObjectURL = () => 'blob:stub';
window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));

// a video is already loaded in this browser (restoreVideos path)
window.localStorage.setItem('rs_video', JSON.stringify({
  path: 'workspace/demo.mp4', name: 'demo.mp4', duration: 120, size: 10485760,
  width: 1920, height: 1080, previewUrl: '/api/asset?path=workspace/demo.mp4'
}));

/* jsdom has no layout: give the preview box a realistic rect that follows the
   aspect ratio the app writes, exactly like a real browser would. */
const BOX_H = 520;
const stubRect = () => {
  const wrap = $('preview-wrap');
  wrap.getBoundingClientRect = () => {
    const ar = (wrap.style.aspectRatio || '9 / 16').split('/').map(Number);
    const ratio = (ar[0] || 9) / (ar[1] || 16);
    const h = BOX_H; const w = h * ratio;
    return { x: 0, y: 0, top: 0, left: 0, right: w, bottom: h, width: w, height: h };
  };
};

console.log('\n=== 1. boot ===');
try { window.eval(appjs); } catch (err) { check('app.js evaluates', false, String(err)); }
stubRect();
doc.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor(() => !$('auth-overlay') || $('auth-overlay').classList.contains('hidden'), 4000);
check('app.js runs without errors', jsErrors.length === 0, jsErrors.slice(0, 2).join(' | '));

const wrap = $('preview-wrap');
const aspectOf = () => (wrap.style.aspectRatio || '').replace(/\s+/g, '');
const num = (v) => Math.round(parseFloat(v));
const setAspect = async (value) => {
  $('aspect').value = value;
  $('aspect').dispatchEvent(new window.Event('change'));
  await sleep(30);
};

/* ── 2. the box is the real output frame ────────────────────────────────── */
console.log('\n=== 2. preview frame follows the export ===');
check('default 9:16 box = 720×1280', aspectOf() === '720/1280', aspectOf());
check('frame chip shows the output size',
  ($('preview-frame').textContent || '').includes('720×1280'), $('preview-frame').textContent);

await setAspect('16:9');
check('16:9 reshapes the box to 1280×720', aspectOf() === '1280/720', aspectOf());
check('--frame-ar-num follows the frame',
  Math.abs(parseFloat(wrap.style.getPropertyValue('--frame-ar-num')) - 16 / 9) < 0.001,
  wrap.style.getPropertyValue('--frame-ar-num'));

await setAspect('1:1');
check('1:1 reshapes the box to 1080×1080', aspectOf() === '1080/1080', aspectOf());

await setAspect('original');
check('"မူရင်း" uses the source size (1920×1080)', aspectOf() === '1920/1080', aspectOf());

/* ── 3. overlay text matches the ASS render math ────────────────────────── */
console.log('\n=== 3. subtitle / hook accuracy ===');
await setAspect('9:16');
$('sub-font').value = '42';
$('sub-font').dispatchEvent(new window.Event('input'));
await sleep(30);
const scale = BOX_H / 1280;                       // box height ÷ output height
check('subtitle px = Fontsize × scale',
  num($('overlay-sub').style.fontSize) === Math.round(42 * scale),
  `${$('overlay-sub').style.fontSize} vs ${Math.round(42 * scale)}px`);
check('subtitle width = 90% (ASS MarginL/R 5%)', $('overlay-sub').style.maxWidth === '90%');

$('hook1').value = 'ဒီဇာတ်လမ်းက မထင်မှတ်ဘဲ လှည့်သွားတယ်';
$('hook1').dispatchEvent(new window.Event('input'));
await sleep(30);
check('hook px = 0.058 × frame width × scale',
  num($('overlay-hook').style.fontSize) === Math.round(0.058 * 720 * scale),
  `${$('overlay-hook').style.fontSize} vs ${Math.round(0.058 * 720 * scale)}px`);
check('hook sits at the ASS margin (top 6%)', $('overlay-hook').style.top === '6%');

check('subtitle starts at the ASS MarginV default (22%)',
  $('overlay-sub').style.bottom === '22%', $('overlay-sub').style.bottom);

/* dragging the subtitle writes the same percentage ffmpeg will use */
const rect = wrap.getBoundingClientRect();
const drag = (el, clientX, clientY) => {
  el.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }));
  window.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX, clientY }));
  window.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true }));
};
drag($('overlay-sub'), rect.width / 2, rect.height * 0.5);
check('dragging the subtitle sets bottom % (= ASS MarginV)',
  $('overlay-sub').style.bottom === '50%' && $('lbl-sub-pos').textContent === '50',
  `${$('overlay-sub').style.bottom} / ${$('lbl-sub-pos').textContent}`);

/* logo: ffmpeg uses overlay=(main_w-overlay_w)·p — left:p% + translate(-p%) */
check('logo badge is 16% wide, like render.py',
  /\.overlay-logo \{[^}]*width:\s*16%/.test(css));
$('overlay-logo').classList.remove('hidden');
drag($('overlay-logo'), rect.width, rect.height);        // to the bottom-right corner
check('logo maps to ffmpeg overlay=(W-w)·p — 100% sits flush, not off-screen',
  $('overlay-logo').style.left === '100%'
  && $('overlay-logo').style.transform.replace(/\s+/g, '') === 'translate(-100%,-100%)',
  `${$('overlay-logo').style.left} ${$('overlay-logo').style.transform}`);

/* ── 4. reframe mode mirrors the ffmpeg filter ──────────────────────────── */
console.log('\n=== 4. reframe mode ===');
const reframe = $('reframe');
const cropOption = [...reframe.options].find((o) => /crop/i.test(o.value));
if (cropOption) {
  reframe.value = cropOption.value;
  reframe.dispatchEvent(new window.Event('change'));
  await sleep(30);
  check('Center Crop previews as a filled frame (object-fit: cover)',
    $('preview-video').style.objectFit === 'cover', $('preview-video').style.objectFit);
  const other = [...reframe.options].find((o) => !/crop/i.test(o.value));
  if (other) {
    reframe.value = other.value;
    reframe.dispatchEvent(new window.Event('change'));
    await sleep(30);
    check('other modes letterbox (object-fit: contain)',
      $('preview-video').style.objectFit === 'contain', $('preview-video').style.objectFit);
  }
}

/* ── 5. Shorts Splitter → Studio hand-off ───────────────────────────────── */
console.log('\n=== 5. splitter → studio ===');
const restored = await waitFor(() => !$('video-pill').classList.contains('hidden'), 4000);
check('saved video restored into the Studio', restored, $('video-pill-name').textContent);

$('btn-split').click();
const rendered = await waitFor(() => $('split-results').querySelector('[data-to-studio]') !== null, 6000);
check('each clip offers "Studio သို့ ပို့မည်"', rendered,
  ($('split-results').textContent || '').trim().slice(0, 40));

if (rendered) {
  $('split-results').querySelector('[data-to-studio]').click();
  const moved = await waitFor(
    () => ($('video-pill-name').textContent || '').includes('clip_part_1'), 4000);
  check('clicking it loads the clip into the Studio', moved, $('video-pill-name').textContent);
  check('the Studio tab is brought to the front',
    !$('tab-studio').classList.contains('hidden')
    && doc.querySelector('#tabs button[data-tab="studio"]').classList.contains('active'));
  check('the preview plays the clip, not the old source',
    ($('preview-video').getAttribute('src') || '').includes('clip_part_1'),
    $('preview-video').getAttribute('src') || '');
}

console.log('\n' + '='.repeat(58));
console.log(`${checks - failures.length}/${checks} checks passed`);
if (failures.length) console.log('FAILED: ' + failures.join(', '));
if (jsErrors.length) console.log('JS errors: ' + jsErrors.slice(0, 5).join(' | '));
process.exit(failures.length ? 1 : 0);
