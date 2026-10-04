/* ==========================================================================
   Recap Studio MM — front-end controller (v4.1)
   Sections: state · api · toasts · uploads · overlays · job runner ·
             timeline · tools (thumbnail/splitter/jobs) · settings · init

   What changed in 4.1 (the "web crash / stuck engine check" round)
   ---------------------------------------------------------------
   * The page renders immediately from a built-in catalog and then upgrades
     itself from /api/system — a slow or failed diagnostics call can no longer
     leave the top bar at "Engine စစ်ဆေးနေသည်…" with empty voice/model lists.
   * Every request has a timeout + retry, and polling survives transient
     errors (before, one failed poll silently stopped progress updates).
   * Uploads resume (already-received chunks are skipped) and never block the
     UI thread.
   * Up to three Gemini keys with a "remember on this device" mirror.
   * The splitter runs as a background job with real progress + cancel.
   ========================================================================== */
(() => {
  'use strict';

  // ── state ────────────────────────────────────────────────────────────
  const state = {
    system: null,
    catalog: null,            // last known /api/system payload (may be null)
    serverOk: null,           // null = unknown, true/false after a probe
    video: null,              // studio upload  {path, duration, …, previewUrl, name}
    splitVideo: null,         // shorts splitter upload
    thumbVideo: null,         // thumbnail tab upload
    logo: null,
    job: null,                // current job object from the API
    poll: null,
    pollErrors: 0,
    lastJobId: localStorage.getItem('rs_last_job') || null,
    splitJobId: null,
    logoPos: { x: 82, y: 4 },
    subPosPercent: 22,
    accessOk: true,
    auth: null,              // /api/auth/me payload
    authReady: false,
    users: []
  };

  // Fallback catalog so the Studio is usable while /api/system is loading
  // (or even when it fails) — the server payload replaces it when it arrives.
  const FALLBACK = {
    models: ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro', 'gemini-2.0-flash'],
    default_model: 'gemini-2.5-flash',
    voices: {
      my: {
        thiha: { name: 'မင်းသန့် (Action Narrator)' },
        nilar: { name: 'မေသူ (Drama & Expressive)' }
      },
      en: {
        christopher: { name: 'Christopher (Cinematic Male)' },
        jenny: { name: 'Jenny (Energetic Female)' },
        guy: { name: 'Guy (Documentary Male)' },
        aria: { name: 'Aria (Calm Narrator)' }
      }
    }
  };

  const $ = (id) => document.getElementById(id);
  const LS = {
    get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
    del: (k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } },
    json: (k, d) => {
      try { const raw = localStorage.getItem(k); return raw ? JSON.parse(raw) : d; }
      catch { return d; }
    },
    setJson: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } }
  };

  // ── api helper ───────────────────────────────────────────────────────
  function accessKey() { return LS.get('rs_access', '') || ''; }

  // CSRF: the server sets a readable `recap_csrf` cookie next to the
  // HttpOnly session cookie; every unsafe request must echo it back.
  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)recap_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function authHeaders(method = 'GET') {
    const headers = {};
    if (accessKey()) headers['X-Access-Key'] = accessKey();
    const token = csrfToken();
    if (token && !['GET', 'HEAD', 'OPTIONS'].includes(String(method).toUpperCase())) {
      headers['X-CSRF-Token'] = token;
    }
    return headers;
  }

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function api(path, { method = 'GET', body, form, signal, timeout = 30000, retries = 0 } = {}) {
    const headers = authHeaders(method);
    let payload = form;
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    let attempt = 0;
    for (;;) {
      const ctrl = new AbortController();
      const onAbort = () => ctrl.abort();
      if (signal) {
        if (signal.aborted) throw new ApiError('aborted', 0);
        signal.addEventListener('abort', onAbort, { once: true });
      }
      const timer = setTimeout(() => ctrl.abort(), timeout);
      try {
        const res = await fetch(path, {
          method, headers, body: payload, signal: ctrl.signal, credentials: 'same-origin'
        });
        const text = await res.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { data = null; }
        if (!res.ok) {
          const detail = (data && (data.detail || data.message)) || text || `HTTP ${res.status}`;
          // session expired / signed out elsewhere → back to the login screen
          if (res.status === 401 && state.authReady && !path.startsWith('/api/auth/')) {
            onSessionLost();
          }
          throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status);
        }
        return data;
      } catch (err) {
        const status = err instanceof ApiError ? err.status : 0;
        const retryable = status === 0 || status === 502 || status === 503 || status === 504;
        if (attempt < retries && retryable) {
          attempt += 1;
          await new Promise((r) => setTimeout(r, 700 * attempt));
          continue;
        }
        if (err instanceof ApiError) throw err;
        if (err.name === 'AbortError') throw new ApiError('အချိန် ကျော်လွန်သွားပါသည် (timeout)', 0);
        throw new ApiError(err.message || String(err), 0);
      } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', onAbort);
      }
    }
  }

  // ── toasts ───────────────────────────────────────────────────────────
  function toast(message, kind = 'info', ms = 6000) {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = `<span>${kind === 'ok' ? '✅' : kind === 'err' ? '⛔' : kind === 'warn' ? '⚠️' : 'ℹ️'}</span>
                    <span>${escapeHtml(message)}</span><span class="close">✕</span>`;
    el.querySelector('.close').onclick = () => el.remove();
    $('toasts').appendChild(el);
    if (ms) setTimeout(() => el.remove(), ms);
    return el;
  }
  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtTime = (s) => {
    s = Math.max(0, Math.round(Number(s) || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h}h ${String(m).padStart(2, '0')}m` : m ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`;
  };
  const fmtBytes = (b) => {
    b = Number(b) || 0;
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(i ? 1 : 0)}${u[i]}`;
  };

  // ── tabs ─────────────────────────────────────────────────────────────
  document.querySelectorAll('#tabs button').forEach((btn) => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });
  function switchTab(name) {
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.add('hidden'));
    $('tab-' + name).classList.remove('hidden');
    document.querySelectorAll('#tabs button').forEach((b) =>
      b.classList.toggle('active', b.dataset.tab === name));
    if (name === 'jobs') loadJobs();
    if (name === 'settings') refreshSystem();
  }

  /* ══════════════════════════ UPLOADS ═══════════════════════════════ */
  let uploadAbort = false;
  let activeUpload = null;

  function setUploadUi(show, text = '', percent = 0, warn = false,
                       ids = ['video-upload-status', 'video-upload-text', 'video-meter', 'video-meter-fill']) {
    const box = $(ids[0]);
    if (!box) return;
    box.classList.toggle('show', show);
    if (!show) return;
    if (ids[1] && $(ids[1])) $(ids[1]).textContent = text;
    if (ids[3] && $(ids[3])) $(ids[3]).style.width = `${percent}%`;
    if (ids[2] && $(ids[2])) $(ids[2]).classList.toggle('amber', !!warn);
  }

  function setFilePill(target, meta, thumbSrc) {
    if (target === 'split') {
      $('split-pill').classList.remove('hidden');
      $('split-pill-name').textContent = meta.name;
      $('split-pill-info').textContent = meta.info;
      if (thumbSrc) $('split-pill-thumb').src = thumbSrc;
      renderPreviewMeta();
      return;
    }
    $('video-pill').classList.remove('hidden');
    $('video-pill-name').textContent = meta.name;
    $('video-pill-info').textContent = meta.info;
    if (thumbSrc) $('video-pill-thumb').src = thumbSrc;
    $('step1-badge').textContent = '✓ အဆင်သင့်';
    renderPreviewMeta();
  }

  /** Small chips under the preview: what is loaded right now. */
  function renderPreviewMeta() {
    const box = $('preview-meta');
    if (!box) return;
    const src = state.splitVideo || state.video;
    if (!src) { box.innerHTML = '<span class="chip muted">ဗီဒီယို မတင်ရသေးပါ</span>'; return; }
    box.innerHTML = [
      `<span class="chip violet">🎞️ ${escapeHtml(String(src.name || 'video')).slice(0, 42)}</span>`,
      src.duration ? `<span class="chip">⏱️ ${fmtTime(src.duration)}</span>` : '',
      (src.width && src.height) ? `<span class="chip muted">${src.width}×${src.height}</span>` : '',
      src.size ? `<span class="chip muted">${fmtBytes(src.size)}</span>` : '',
      state.splitVideo ? '<span class="chip ok">Studio + Splitter နှစ်ခုလုံး အဆင်သင့်</span>' : ''
    ].filter(Boolean).join('');
  }

  function makeVideoEntry(data, file) {
    return {
      path: data.video_path || data.path,
      duration: data.duration || 0,
      width: data.width, height: data.height,
      size: data.size || (file ? file.size : 0),
      previewUrl: data.preview_url || null,
      name: (file && file.name) || data.filename || 'video'
    };
  }

  function applyVideoResult(data, file) {
    state.video = makeVideoEntry(data, file);
    LS.setJson('rs_video', {
      path: state.video.path, duration: state.video.duration, name: state.video.name,
      size: state.video.size, width: state.video.width, height: state.video.height,
      previewUrl: state.video.previewUrl
    });
    const localThumb = file ? URL.createObjectURL(file) : (state.video.previewUrl || '');
    setFilePill('studio', {
      name: state.video.name,
      info: `${fmtTime(state.video.duration)} · ${state.video.width || '?'}×${state.video.height || '?'} · ${fmtBytes(state.video.size)}`
    }, localThumb);
    if (localThumb) $('preview-video').src = localThumb;
    $('parts-estimate').style.display = 'none';
    estimateSplitParts();
  }

  /** Chunked upload with resume, per-chunk retry and progress. */
  async function uploadFile(file, { kind = 'video', onProgress, signal } = {}) {
    const init = await api('/api/upload/init', {
      method: 'POST', body: { filename: file.name, size: file.size, kind }, timeout: 60000
    });
    const chunkSize = init.chunk_size || 8 * 1024 * 1024;
    const total = Math.max(1, Math.ceil(file.size / chunkSize));
    // resume: the server may already hold some chunks (page reload / retry)
    const have = new Set(init.received_chunks || []);
    if (have.size) {
      toast(`ဖိုင်၏ အပိုင်း ${have.size}/${total} ကို server တွင် ရှိပြီးသား — ကျန်သည်ကို ဆက်တင်ပါမည်`, 'info', 5000);
    }
    let lastProgress = have.size ? (have.size / total) * 99 : 0;
    onProgress && onProgress(lastProgress, 'တင်နေသည်…');

    for (let index = 0; index < total; index++) {
      if (uploadAbort) throw new ApiError('UPLOAD_CANCELLED', 0);
      if (have.has(index)) continue;
      const start = index * chunkSize;
      const blob = file.slice(start, Math.min(file.size, start + chunkSize));
      let attempt = 0, lastErr = null;
      while (attempt < 4) {
        try {
          await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            activeUpload = xhr;
            xhr.open('POST', '/api/upload/chunk');
            xhr.timeout = 180000;
            xhr.withCredentials = true;
            Object.entries(authHeaders('POST')).forEach(([k, v]) => xhr.setRequestHeader(k, v));
            if (signal) signal.addEventListener('abort', () => { try { xhr.abort(); } catch { /* ignore */ } }, { once: true });
            xhr.upload.onprogress = (e) => {
              if (!onProgress) return;
              const sent = start + (e.loaded || 0);
              lastProgress = Math.min(99, (sent / file.size) * 100);
              onProgress(lastProgress,
                `တင်နေသည်… ${fmtBytes(sent)} / ${fmtBytes(file.size)} (အပိုင်း ${index + 1}/${total})`);
            };
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) resolve();
              else {
                let msg = `HTTP ${xhr.status}`;
                try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* ignore */ }
                reject(new ApiError(msg, xhr.status));
              }
            };
            xhr.onerror = () => reject(new ApiError('ကွန်ယက် ပြတ်တောက်သွားပါသည်', 0));
            xhr.ontimeout = () => reject(new ApiError('Chunk timeout — ပြန်စမ်းပါမည်', 0));
            const fd = new FormData();
            fd.append('upload_id', init.upload_id);
            fd.append('index', String(index));
            fd.append('chunk', blob, `part_${index}`);
            xhr.send(fd);
          });
          break;
        } catch (err) {
          lastErr = err;
          attempt++;
          if (String(err.message).includes('UPLOAD_CANCELLED')) throw err;
          if (attempt < 4) {
            onProgress && onProgress(lastProgress,
              `⚠️ အပိုင်း ${index + 1} ပြန်စမ်းနေသည် (${attempt}/4)…`, true);
            await new Promise((r) => setTimeout(r, 800 * attempt * attempt));
          }
        }
      }
      if (attempt >= 4 && lastErr) throw lastErr;
    }
    onProgress && onProgress(99.5, 'ဖိုင် စစ်ဆေးနေပါသည်…');
    return api('/api/upload/complete', { method: 'POST', body: { upload_id: init.upload_id }, timeout: 600000 });
  }

  async function handleVideoFile(file, { target = 'studio' } = {}) {
    if (!file) return;
    if (!file.type.startsWith('video/') && !/\.(mp4|mov|mkv|webm|avi|m4v|ts|flv|wmv|3gp)$/i.test(file.name)) {
      toast('ဗီဒီယိုဖိုင် မဟုတ်ပါ (MP4/MOV/MKV/WEBM ဖြစ်ရပါမည်)', 'err');
      return;
    }
    uploadAbort = false;
    const isSplit = target === 'split';
    const ids = isSplit
      ? ['split-upload-status', 'split-upload-text', 'split-meter', 'split-meter-fill']
      : ['video-upload-status', 'video-upload-text', 'video-meter', 'video-meter-fill'];
    setUploadUi(true, 'တင်နေသည်…', 0, false, ids);
    const btn = $('btn-start'); if (btn) btn.disabled = true;
    try {
      const data = await uploadFile(file, {
        kind: 'video',
        onProgress: (pct, text, warn) => setUploadUi(true, text, pct, warn, ids)
      });
      if (isSplit) {
        state.splitVideo = makeVideoEntry(data, file);
        LS.setJson('rs_split_video', state.splitVideo);
        setFilePill('split', {
          name: state.splitVideo.name,
          info: `${fmtTime(state.splitVideo.duration)} · ${fmtBytes(state.splitVideo.size)}`
        }, URL.createObjectURL(file));
        estimateSplitParts();
      } else if (target === 'thumb') {
        state.thumbVideo = makeVideoEntry(data, file);
        toast('Thumbnail အတွက် ဗီဒီယို အဆင်သင့်', 'ok');
      } else {
        applyVideoResult(data, file);
        toast(`ဗီဒီယို အဆင်သင့် — ${fmtTime(state.video.duration)}`, 'ok');
      }
    } catch (err) {
      if (String(err.message).includes('UPLOAD_CANCELLED')) toast('တင်ခြင်းကို ရပ်လိုက်ပါပြီ', 'warn');
      else toast('Upload မအောင်မြင်ပါ: ' + err.message, 'err', 12000);
    } finally {
      setUploadUi(false, '', 0, false, ids);
      if (btn) btn.disabled = false;
      activeUpload = null;
    }
  }

  /** Generic dropzone ↔ hidden <input type=file> wiring (drag, click, drop). */
  function wireDropzone(zoneId, inputId, onFile) {
    const zone = $(zoneId);
    const input = $(inputId);
    if (!zone || !input) return;
    zone.onclick = (e) => {
      if (e.target.closest('button, a, input')) return;
      input.value = '';
      input.click();
    };
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) onFile(file);
    });
    input.addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = '';
      if (file) onFile(file);
    });
  }

  // studio dropzone
  const dropzone = $('dropzone');
  const videoInput = $('video-file');
  dropzone.onclick = (e) => {
    if (e.target.closest('button, a, input')) return;
    videoInput.value = '';
    videoInput.click();
  };
  const pickVideo = $('btn-pick-video');
  if (pickVideo) pickVideo.onclick = () => { videoInput.value = ''; videoInput.click(); };
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault(); dropzone.classList.remove('dragover');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleVideoFile(file);
  });
  videoInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    handleVideoFile(file);
  });
  $('btn-cancel-upload').onclick = () => {
    uploadAbort = true;
    if (activeUpload) { try { activeUpload.abort(); } catch { /* ignore */ } }
    setUploadUi(false);
    toast('တင်ခြင်းကို ရပ်လိုက်ပါပြီ', 'warn');
  };
  $('btn-clear-video').onclick = () => {
    state.video = null;
    LS.del('rs_video');
    $('video-pill').classList.add('hidden');
    $('preview-video').removeAttribute('src');
    $('step1-badge').textContent = '';
  };

  // logo (single request, validated server side, always returns a usable file)
  const logoInput = $('logo-file');
  logoInput.parentElement.onclick = (e) => { if (e.target === e.currentTarget) logoInput.click(); };
  logoInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const fd = new FormData();
    fd.append('logo', file);
    try {
      toast('Logo တင်နေသည်…', 'info', 2000);
      const data = await api('/api/upload-logo', { method: 'POST', form: fd, timeout: 120000 });
      state.logo = { path: data.logo_path, previewUrl: data.logo_preview_url };
      $('overlay-logo-img').src = data.logo_preview_url || URL.createObjectURL(file);
      $('overlay-logo').classList.remove('hidden');
      setLogoPos(state.logoPos.x, state.logoPos.y);
      toast(data.logo_warning || 'Logo အဆင်သင့် — Preview ပေါ်တွင် ဆွဲ၍ နေရာချပါ', data.logo_warning ? 'warn' : 'ok');
    } catch (err) {
      toast('Logo တင်၍ မရပါ: ' + err.message, 'err');
    }
  });
  $('btn-remove-logo').onclick = () => {
    state.logo = null;
    $('overlay-logo').classList.add('hidden');
    $('lbl-logo-pos').textContent = 'မထည့်ရသေးပါ';
    toast('Logo ဖျက်လိုက်ပါပြီ', 'info', 2500);
  };
  document.querySelectorAll('#logo-presets [data-logo-pos]').forEach((b) => {
    b.onclick = () => { const [x, y] = b.dataset.logoPos.split(',').map(Number); setLogoPos(x, y); };
  });

  // URL import
  $('btn-import-url').onclick = async () => {
    const url = $('url-input').value.trim();
    if (!url) return toast('Link ထည့်ပါ', 'err');
    const btn = $('btn-import-url');
    btn.disabled = true; btn.textContent = '⬇ တင်နေသည်…';
    try {
      const data = await api('/api/download-url', { method: 'POST', body: { url }, timeout: 1800000 });
      applyVideoResult({ ...data, video_path: data.video_path }, null);
      if (data.preview_url) $('preview-video').src = data.preview_url;
      toast(`Link မှ Import ပြီးပါပြီ — ${fmtTime(data.duration)}`, 'ok');
    } catch (err) {
      toast('Import မအောင်မြင်ပါ: ' + err.message, 'err', 15000);
    } finally {
      btn.disabled = false; btn.textContent = '⬇ Import';
    }
  };

  /* ══════════════════ PREVIEW OVERLAYS (drag) ═══════════════════════ */
  function styleSubtitleOverlay() {
    const el = $('overlay-sub');
    const size = Number($('sub-font').value);
    const color = $('sub-color').value;
    const bg = $('sub-bg').value;
    $('lbl-font').textContent = size;
    el.style.color = color;
    el.style.fontSize = Math.max(10, Math.round(size * 0.5)) + 'px';
    if (bg === 'Outline Only') {
      el.style.background = 'transparent';
      el.style.textShadow = '0 0 6px #000, 0 0 6px #000';
    } else {
      el.style.textShadow = 'none';
      el.style.background = bg === 'Solid Box' ? 'rgba(0,0,0,.78)' : 'rgba(0,0,0,.35)';
    }
  }

  function updateHookOverlay() {
    const h1 = $('hook1').value.trim(), h2 = $('hook2').value.trim();
    $('overlay-hook').innerHTML = h1 || h2
      ? `${escapeHtml(h1)}<small>${escapeHtml(h2)}</small>` : '';
  }

  function setSubPos(percent) {
    state.subPosPercent = Math.max(3, Math.min(92, Math.round(percent)));
    $('overlay-sub').style.bottom = state.subPosPercent + '%';
    $('lbl-sub-pos').textContent = state.subPosPercent;
  }

  function setLogoPos(x, y) {
    state.logoPos = {
      x: Math.max(0, Math.min(88, Math.round(x))),
      y: Math.max(0, Math.min(88, Math.round(y)))
    };
    const el = $('overlay-logo');
    el.style.left = state.logoPos.x + '%';
    el.style.top = state.logoPos.y + '%';
    $('lbl-logo-pos').textContent = `x:${state.logoPos.x}% y:${state.logoPos.y}%`;
  }

  function bindDrag(el, handler) {
    const wrap = $('preview-wrap');
    let dragging = false;
    const start = (e) => { dragging = true; e.preventDefault(); e.stopPropagation(); };
    const move = (e) => {
      if (!dragging) return;
      const rect = wrap.getBoundingClientRect();
      const point = e.touches ? e.touches[0] : e;
      const xPct = ((point.clientX - rect.left) / rect.width) * 100;
      const yPct = ((point.clientY - rect.top) / rect.height) * 100;
      handler(Math.max(0, Math.min(100, xPct)), Math.max(0, Math.min(100, yPct)));
      e.preventDefault();
    };
    const end = () => { dragging = false; };
    el.addEventListener('mousedown', start);
    el.addEventListener('touchstart', start, { passive: false });
    window.addEventListener('mousemove', move, { passive: false });
    window.addEventListener('touchmove', move, { passive: false });
    window.addEventListener('mouseup', end);
    window.addEventListener('touchend', end);
  }
  bindDrag($('overlay-sub'), (x, y) => setSubPos(100 - y));
  bindDrag($('overlay-logo'), (x, y) => setLogoPos(x, y));
  setSubPos(22);

  /* ══════════════════════ VOICES / SETTINGS ════════════════════════ */
  function voiceCatalog() {
    return (state.catalog && state.catalog.voices) || FALLBACK.voices;
  }
  function modelCatalog() {
    return (state.catalog && state.catalog.models) || FALLBACK.models;
  }

  function renderVoices() {
    const lang = $('lang').value;
    const voices = voiceCatalog();
    const list = voices[lang] || voices.my || {};
    const current = $('voice').value;
    $('voice').innerHTML = Object.entries(list)
      .map(([key, v]) => `<option value="${key}">${escapeHtml(v.name || key)}</option>`).join('');
    const preferred = LS.get('rs_voice_' + lang, '') || current;
    if (preferred && list[preferred]) $('voice').value = preferred;
  }

  function renderModels() {
    const models = modelCatalog();
    const options = models.map((m) => `<option value="${m}">${m}</option>`).join('');
    $('model').innerHTML = options;
    $('cfg-model').innerHTML = options;
    const saved = LS.get('rs_model', '') ||
      (state.catalog && state.catalog.default_model) || FALLBACK.default_model;
    if (saved && models.includes(saved)) { $('model').value = saved; $('cfg-model').value = saved; }
  }

  function persistUiState() {
    LS.set('rs_voice_' + $('lang').value, $('voice').value);
    LS.set('rs_model', $('model').value);
    ['lang', 'mode', 'fill-mode', 'quality', 'sub-font', 'sub-color', 'sub-bg', 'aspect',
     'reframe', 'hook1', 'hook2', 'hook-seconds', 'thumb-sec'].forEach((id) => {
      const el = $(id);
      if (el) LS.set('rs_' + id, el.value);
    });
  }

  function restoreUiState() {
    ['lang', 'mode', 'fill-mode', 'quality', 'sub-font', 'sub-color', 'sub-bg', 'aspect',
     'reframe', 'hook-seconds'].forEach((id) => {
      const saved = LS.get('rs_' + id, null);
      const el = $(id);
      if (saved !== null && el && [...el.options].some((o) => o.value === saved)) el.value = saved;
      else if (saved !== null && el && el.type === 'range') el.value = saved;
    });
    $('hook1').value = LS.get('rs_hook1', '');
    $('hook2').value = LS.get('rs_hook2', '');
  }

  /* ═══════════════════════════ JOB RUNNER ══════════════════════════ */
  function collectPayload() {
    return {
      input_video: state.video ? state.video.path : '',
      api_key: '',                                  // resolved server-side from the key ring
      model: $('model').value || FALLBACK.default_model,
      mode: $('mode').value,
      fill_mode: $('fill-mode').value,
      lang: $('lang').value,
      voice: $('voice').value,
      quality: $('quality').value,
      output_aspect: $('aspect').value,
      reframe_mode: $('reframe').value,
      mute_original: $('mute-original').checked,
      original_level: Number($('original-level').value) / 100,
      narration_gain: Number($('narration-gain').value) / 100,
      enable_subtitles: $('enable-subs').checked,
      sub_font_size: Number($('sub-font').value),
      sub_color_hex: $('sub-color').value,
      sub_bg_style: $('sub-bg').value,
      sub_v_pos_percent: state.subPosPercent,
      logo_path: state.logo ? state.logo.path : null,
      logo_pos_x: state.logo ? state.logoPos.x : null,
      logo_pos_y: state.logo ? state.logoPos.y : null,
      hook_line1: $('hook1').value.trim(),
      hook_line2: $('hook2').value.trim(),
      hook_seconds: Number($('hook-seconds').value)
    };
  }

  $('btn-start').onclick = async () => {
    if (!state.video) return toast('ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်တင်ပါ', 'err');
    const btn = $('btn-start');
    btn.disabled = true;
    try {
      const data = await api('/api/tasks', { method: 'POST', body: collectPayload(), timeout: 60000 });
      state.lastJobId = data.task_id;
      LS.set('rs_last_job', data.task_id);
      toast('အလုပ် စတင်ပါပြီ — AI မှ ခွဲခြမ်းစိတ်ဖြာနေပါသည်', 'ok');
      switchTab('studio');
      startPolling(data.task_id);
    } catch (err) {
      toast('စတင်၍ မရပါ: ' + err.message, 'err', 12000);
    } finally {
      btn.disabled = false;
    }
  };

  function renderStages(stages = {}) {
    const defs = [
      ['prepare', 'ဗီဒီယို စစ်ဆေးခြင်း'], ['analyze', 'AI ခွဲခြမ်းစိတ်ဖြာခြင်း'],
      ['coverage', 'လွတ်နေရာ ဖြည့်ခြင်း'], ['voice', 'အသံသွင်းခြင်း (TTS)'],
      ['mix', 'အသံ ပေါင်းစပ်ခြင်း'], ['subtitles', 'စာတန်းထိုး'],
      ['render', 'Final Render'], ['finalize', 'သိမ်းဆည်းခြင်း']
    ];
    const items = defs.map(([key, label]) => {
      const st = stages[key] || 'pending';
      const icon = st === 'done' ? '✓' : st === 'running' ? '●' : st === 'failed' ? '✕' : '';
      return `<div class="stage ${st}"><span class="dot">${icon}</span><span>${label}</span></div>`;
    });
    // split jobs use their own short stage list
    if (stages.split || stages.finalize === 'running') {
      const splitDefs = [['prepare', 'ဗီဒီယို စစ်ဆေးခြင်း'], ['split', 'အပိုင်းများ ခွဲထုတ်ခြင်း'],
                         ['finalize', 'သိမ်းဆည်းခြင်း']];
      if (stages.split) {
        $('job-stages').innerHTML = splitDefs.map(([key, label]) => {
          const st = stages[key] || 'pending';
          const icon = st === 'done' ? '✓' : st === 'running' ? '●' : st === 'failed' ? '✕' : '';
          return `<div class="stage ${st}"><span class="dot">${icon}</span><span>${label}</span></div>`;
        }).join('');
        return;
      }
    }
    $('job-stages').innerHTML = items.join('');
  }

  const STATUS_LABEL = {
    queued: ['muted', 'အလှည့်စောင့်'], running: ['', 'လုပ်ဆောင်နေသည်'],
    completed: ['ok', 'ပြီးစီး'], failed: ['bad', 'မအောင်မြင်'], cancelled: ['warn', 'ရပ်ထား']
  };

  function setJobCardLive(live) {
    const card = $('job-card');
    card.classList.toggle('is-live', !!live);
  }

  function renderJob(job) {
    state.job = job;
    $('job-idle-msg').classList.add('hidden');
    $('job-live').classList.remove('hidden');
    $('job-percent').textContent = `${Math.round(job.progress || 0)}%`;
    $('job-meter-fill').style.width = `${job.progress || 0}%`;
    $('job-message').textContent = job.message || '…';
    const chip = $('job-status-chip');
    const [cls, label] = STATUS_LABEL[job.status] || ['muted', job.status];
    chip.className = `chip ${cls}`;
    chip.textContent = job.cancelling ? 'ရပ်နေသည်…' : label;
    chip.style.marginLeft = 'auto';
    if (job.eta_seconds) $('job-eta').textContent = `ခန့်မှန်း ကျန်ချိန် ≈ ${fmtTime(job.eta_seconds)} · လုပ်ဆောင်ချိန် ${fmtTime(job.elapsed_seconds)}`;
    else $('job-eta').textContent = job.elapsed_seconds ? `လုပ်ဆောင်ချိန် ${fmtTime(job.elapsed_seconds)}` : '—';
    renderStages(job.stages || {});
    if (job.logs) {
      const box = $('job-logs');
      box.textContent = job.logs.join('\n');
      box.scrollTop = box.scrollHeight;
    }
    $('btn-cancel-job').disabled = job.cancelling || ['completed', 'failed', 'cancelled'].includes(job.status);
    $('cancel-hint').textContent = job.cancelling
      ? 'ရပ်တန့်ရန် တောင်းဆိုထားပါသည် — ffmpeg ရပ်ပြီး status ပြောင်းသည်အထိ ခဏစောင့်ပါ။'
      : 'ရပ်လိုက်ပါက ffmpeg ကို ချက်ချင်း ရပ်ပါမည် (အလုပ်ပြီးဆုံးရန် မစောင့်ရပါ)။';

    const isSplit = job.kind === 'split';
    if (job.status === 'completed') {
      stopPolling();
      setJobCardLive(false);
      if (isSplit) { renderSplitResult(job); return; }
      $('job-result').classList.remove('hidden');
      $('btn-download').href = job.download_url || '#';
      const links = [['btn-srt', 'srt_url'], ['btn-ass', 'ass_url'], ['btn-mp3', 'audio_url']];
      links.forEach(([id, key]) => {
        const el = $(id);
        if (job[key]) { el.href = job[key]; el.classList.remove('hidden'); } else el.classList.add('hidden');
      });
      const out = (job.stats && job.stats.output) || {};
      const cov = job.coverage || {};
      const voice = (job.stats && job.stats.voice) || {};
      $('job-stats').innerHTML = [
        ['ဖိုင် အရွယ်', fmtBytes(out.size || 0)],
        ['စကားပြောလိုင်း', job.dialogues ? job.dialogues.length : voice.lines || 0],
        ['Coverage', (cov.coverage_percent ?? '—') + '%'],
        ['တိတ်ဆိတ်ချိန်', `${voice.silent_seconds ?? '—'}s`],
        ['ကြာချိန်', fmtTime(out.duration || job.duration)]
      ].map(([k, v]) => `<div class="stat"><b>${escapeHtml(String(v))}</b><span>${k}</span></div>`).join('');
      if (job.preview_url) $('preview-video').src = job.preview_url;
      renderTimeline(job);
      renderCoverage(job);
      const warnings = (job.stats && job.stats.warnings) || [];
      warnings.slice(0, 4).forEach((w) => toast(w, 'warn', 9000));
      toast('🎉 ဗီဒီယို ပြီးပါပြီ — ဒေါင်းလုဒ် လုပ်နိုင်ပါပြီ', 'ok', 9000);
      loadJobs();
    } else if (job.status === 'failed') {
      stopPolling();
      setJobCardLive(false);
      toast('အလုပ် မအောင်မြင်ပါ: ' + (job.error || job.message), 'err', 20000);
    } else if (job.status === 'cancelled') {
      stopPolling();
      setJobCardLive(false);
      toast('အလုပ် ရပ်လိုက်ပါပြီ', 'warn');
    } else {
      setJobCardLive(true);
    }
  }

  function startPolling(taskId) {
    stopPolling();
    state.pollErrors = 0;
    state.lastJobId = taskId;
    LS.set('rs_last_job', taskId);
    $('job-result').classList.add('hidden');
    const tick = async () => {
      try {
        const job = await api(`/api/tasks/${taskId}`, { timeout: 20000 });
        state.pollErrors = 0;
        renderJob(job);
      } catch (err) {
        state.pollErrors += 1;
        if (err.status === 404) {
          stopPolling();
          toast('Job ရှာမတွေ့ပါ — Jobs tab မှ ပြန်ကြည့်ပါ', 'warn');
          return;
        }
        // Keep polling: one dropped request (mobile network, server GC pause)
        // used to stop all progress updates with no way to get them back.
        if (state.pollErrors <= 6) {
          $('job-message').textContent =
            `⚠️ Server နှင့် ချိတ်ဆက်မှု ပြတ်နေပါသည် — ပြန်စမ်းနေသည် (${state.pollErrors}/6)…`;
        } else {
          stopPolling();
          toast('Job အခြေအနေ ရယူ၍ မရပါ: ' + err.message, 'err', 12000);
        }
      }
    };
    tick();
    state.poll = setInterval(tick, 2000);
  }
  function stopPolling() { if (state.poll) { clearInterval(state.poll); state.poll = null; } }

  $('btn-cancel-job').onclick = async () => {
    const jobId = (state.job && state.job.id) || state.lastJobId;
    if (!jobId) return toast('ရပ်တန့်ရန် အလုပ် မရှိပါ', 'err');
    if (!confirm('အလုပ်ကို ရပ်မှာ သေချာပါသလား? (ffmpeg ချက်ချင်း ရပ်ပါမည်)')) return;
    $('btn-cancel-job').disabled = true;
    try {
      await api(`/api/tasks/${jobId}/cancel`, { method: 'POST', body: {}, timeout: 30000 });
      if (state.job) { state.job.cancelling = true; renderJob(state.job); }
      toast('ရပ်တန့်ရန် တောင်းဆိုလိုက်ပါပြီ — ffmpeg ရပ်နေပါသည်…', 'warn');
      if (!state.poll) startPolling(jobId);
    } catch (err) {
      toast('ရပ်၍ မရပါ: ' + err.message, 'err', 10000);
      $('btn-cancel-job').disabled = false;
    }
  };
  $('btn-goto-timeline').onclick = () => switchTab('timeline');

  /* ═════════════════════════ TIMELINE EDITOR ═══════════════════════ */
  function renderTimeline(job) {
    const list = $('tl-list');
    if (!job || !job.dialogues || !job.dialogues.length) {
      $('tl-summary').textContent = 'Timeline မရှိသေးပါ — Job တစ်ခု ပြီးဆုံးပါက ဒီနေရာတွင် ပေါ်လာပါမည်။';
      list.innerHTML = '';
      $('tl-strip').innerHTML = '';
      return;
    }
    $('tl-hook1').value = job.hook_line1 || '';
    $('tl-hook2').value = job.hook_line2 || '';
    const lines = job.dialogues;
    $('tl-summary').innerHTML = `စုစုပေါင်း <b>${lines.length}</b> လိုင်း · ဗီဒီယို <b>${fmtTime(job.duration)}</b>
      · Coverage <b>${(job.coverage || {}).coverage_percent ?? '—'}%</b>`;
    list.innerHTML = lines.map((d, i) => `
      <div class="tl-row" data-index="${i}">
        <span class="idx">#${i + 1}</span>
        <input type="number" step="0.1" class="tl-start" value="${Number(d.start).toFixed(2)}">
        <input type="number" step="0.1" class="tl-end" value="${Number(d.end).toFixed(2)}">
        <input type="text" class="tl-text" value="${escapeHtml(d.text || '')}">
        <button class="del" title="ဖျက်မည်">✕</button>
      </div>`).join('');
    list.querySelectorAll('.tl-row').forEach((row) => {
      row.querySelector('.del').onclick = () => {
        const idx = Number(row.dataset.index);
        state.job.dialogues.splice(idx, 1);
        renderTimeline(state.job);
        renderTimelineStrip(state.job);
      };
    });
    renderTimelineStrip(job);
  }

  function renderTimelineStrip(job) {
    const strip = $('tl-strip');
    const duration = (state.video && state.video.duration) || (job && job.duration) || 0;
    if (!duration || !job || !job.dialogues) { strip.innerHTML = ''; return; }
    const bars = job.dialogues.map((d) => {
      const left = (d.start / duration) * 100;
      const width = Math.max(0.4, ((d.end - d.start) / duration) * 100);
      return `<div class="bar" style="left:${left}%;width:${width}%" title="${Number(d.start).toFixed(1)}s"></div>`;
    }).join('');
    let ticks = '';
    const step = duration > 600 ? 300 : duration > 120 ? 60 : 15;
    for (let t = 0; t < duration; t += step) {
      ticks += `<div class="tick" style="left:${(t / duration) * 100}%"></div>`;
    }
    strip.innerHTML = bars + ticks;
  }

  function renderCoverage(job) {
    const cov = job.coverage;
    const voice = (job.stats && job.stats.voice) || {};
    if (!cov || !cov.lines) { $('coverage-card').style.display = 'none'; return; }
    $('coverage-card').style.display = '';
    const filled = cov.gaps_filled || 0;
    const silent = voice.silent_seconds ?? 0;
    const maxSilence = voice.max_silence_seconds ?? 0;
    $('coverage-stats').innerHTML = [
      ['Coverage', `${cov.coverage_percent}%`],
      ['စကားပြော စုစုပေါင်း', fmtTime(cov.spoken_seconds)],
      ['အရှည်ဆုံး လွတ်ကွက်', `${cov.longest_gap_seconds}s`],
      ['AI ဖြည့်လိုက်သည့် ကွက်', filled],
      ['အသံ တိတ်ဆိတ်ချိန်', `${silent}s`],
      ['အရှည်ဆုံး တိတ်ဆိတ်ချိန်', `${maxSilence}s`]
    ].map(([k, v]) => `<div class="stat"><b>${escapeHtml(String(v))}</b><span>${k}</span></div>`).join('');
    const chip = $('coverage-chip');
    if (maxSilence <= (state.catalog ? state.catalog.limits.max_narration_gap : 5)) {
      chip.className = 'chip ok';
      chip.textContent = '✅ အစအဆုံး အသံ ပါဝင်သည်';
      $('coverage-note').textContent = 'ဗီဒီယို အစအဆုံး အသံ ထွက်ရှိပါသည် — လိုအပ်ပါက Timeline Editor မှ ပြင်နိုင်ပါသည်။';
    } else {
      chip.className = 'chip warn';
      chip.textContent = `⚠️ တိတ်ဆိတ်ချိန် ${maxSilence}s ရှိနေပါသည်`;
      $('coverage-note').innerHTML = 'အသံ မပါသော နေရာ ရှိနေပါသည် — <span class="tag">Timeline Editor</span> မှ လိုင်းထည့်ပြီး 🚀 ပြန် Render လုပ်ပါ။';
    }
    const strip = $('coverage-strip');
    const duration = job.duration || 1;
    const bars = (job.dialogues || []).map((d) =>
      `<div class="bar" style="left:${(d.start / duration) * 100}%;width:${Math.max(0.3, ((d.end - d.start) / duration) * 100)}%"></div>`).join('');
    const gaps = ((job.stats || {}).silent_windows || []).map((g) =>
      `<div class="gap" style="left:${(g.start / duration) * 100}%;width:${Math.max(0.2, ((g.end - g.start) / duration) * 100)}%"></div>`).join('');
    strip.innerHTML = bars + gaps;
  }

  $('btn-tl-add').onclick = () => {
    if (!state.job) state.job = { dialogues: [], duration: (state.video && state.video.duration) || 0 };
    if (!state.job.dialogues) state.job.dialogues = [];
    const last = state.job.dialogues[state.job.dialogues.length - 1];
    const start = last ? Number(last.end) + 0.6 : 0.5;
    state.job.dialogues.push({ start, end: start + 3, text: '', speaker: 'Recap' });
    renderTimeline(state.job);
  };

  $('btn-tl-fix').onclick = () => {
    if (!state.job || !state.job.dialogues) return toast('Timeline မရှိသေးပါ', 'err');
    const lines = state.job.dialogues
      .map((d) => ({ ...d, start: Math.max(0, Number(d.start) || 0), end: Math.max(0, Number(d.end) || 0) }))
      .sort((a, b) => a.start - b.start);
    let fixed = 0;
    for (let i = 0; i < lines.length - 1; i++) {
      if (lines[i].end > lines[i + 1].start) { lines[i].end = lines[i + 1].start; fixed++; }
      if (lines[i].end <= lines[i].start) lines[i].end = lines[i].start + 0.8;
    }
    const gaps = [];
    let cursor = 0;
    lines.forEach((l) => { if (l.start - cursor > 6) gaps.push([cursor, l.start]); cursor = Math.max(cursor, l.end); });
    state.job.dialogues = lines;
    renderTimeline(state.job);
    toast(`Overlap ${fixed} ခု ပြင်လိုက်ပါပြီ${gaps.length ? ` · လွတ်ကွက် ${gaps.length} ခု ရှိပါသည်` : ''}`, 'ok');
  };

  $('btn-tl-render').onclick = async () => {
    if (!state.job || !state.job.id) return toast('Job တစ်ခု အရင်လုပ်ပါ', 'err');
    const dialogues = [];
    $('tl-list').querySelectorAll('.tl-row').forEach((row) => {
      const text = row.querySelector('.tl-text').value.trim();
      if (!text) return;
      dialogues.push({
        start: Number(row.querySelector('.tl-start').value) || 0,
        end: Number(row.querySelector('.tl-end').value) || 0,
        text
      });
    });
    if (!dialogues.length) return toast('Timeline တွင် စာသား မရှိပါ', 'err');
    const payload = { ...collectPayload(), dialogues, enable_subtitles: $('enable-subs').checked };
    payload.hook_line1 = $('tl-hook1').value;
    payload.hook_line2 = $('tl-hook2').value;
    toast('ပြင်ဆင်ထားသော Timeline ဖြင့် ပြန် Render လုပ်နေပါသည်…', 'info');
    try {
      await api(`/api/tasks/${state.job.id}/rerender`, { method: 'POST', body: payload, timeout: 60000 });
      switchTab('studio');
      startPolling(state.job.id);
    } catch (err) { toast('Re-render မအောင်မြင်ပါ: ' + err.message, 'err'); }
  };

  $('btn-tl-preview').onclick = async () => {
    const v = $('preview-video');
    if (!v.getAttribute('src')) return toast('Preview အတွက် ဗီဒီယိုဖိုင် မရှိပါ', 'err');
    switchTab('studio');
    try { await v.play(); } catch { /* autoplay may be blocked */ }
    toast('Preview ကို ဖွင့်လိုက်ပါပြီ', 'info', 3500);
  };

  /* ═════════════════ THUMBNAIL / SPLITTER / JOBS ═══════════════════ */
  wireDropzone('thumb-dropzone', 'thumb-file', (file) => handleVideoFile(file, { target: 'thumb' }));

  $('btn-thumb').onclick = async () => {
    const source = state.thumbVideo || state.video;
    if (!source) return toast('ဗီဒီယိုဖိုင် အရင်တင်ပါ', 'err');
    const btn = $('btn-thumb');
    btn.disabled = true;
    try {
      const res = await fetch('/api/thumbnail', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...authHeaders('POST') },
        body: JSON.stringify({
          video_path: source.path,
          timestamp: Number($('thumb-sec').value) || 2.5,
          hook_line1: $('thumb-h1').value,
          hook_line2: $('thumb-h2').value,
          style: $('thumb-style').value
        })
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      $('thumb-img').src = url;
      $('thumb-dl').href = url;
      $('thumb-empty').classList.add('hidden');
      $('thumb-result').classList.remove('hidden');
      toast('Thumbnail အဆင်သင့်', 'ok');
    } catch (err) { toast('Thumbnail မရပါ: ' + err.message, 'err'); }
    finally { btn.disabled = false; }
  };

  // ── shorts splitter (own upload slot + background job) ───────────────
  wireDropzone('split-dropzone', 'split-file', (file) => handleVideoFile(file, { target: 'split' }));
  $('btn-clear-split').onclick = () => {
    state.splitVideo = null;
    LS.del('rs_split_video');
    $('split-pill').classList.add('hidden');
    $('split-results').innerHTML = '';
    $('parts-estimate').style.display = 'none';
  };
  $('btn-cancel-split-upload').onclick = () => {
    uploadAbort = true;
    if (activeUpload) { try { activeUpload.abort(); } catch { /* ignore */ } }
    setUploadUi(false, '', 0, false,
      ['split-upload-status', 'split-upload-text', 'split-meter', 'split-meter-fill']);
  };

  function splitProgress(show, text = '', percent = 0, warn = false) {
    setUploadUi(show, text, percent, warn,
      ['split-progress', 'split-progress-text', 'split-progress-meter', 'split-progress-fill']);
  }

  async function estimateSplitParts() {
    const source = state.splitVideo || state.video;
    if (!source || !source.duration) {
      const field = $('split-estimate');
      if (field) field.value = '—';
      return;
    }
    try {
      const data = await api('/api/estimate-parts', {
        method: 'POST',
        body: { duration: source.duration, slice_sec: Number($('split-slice').value) }
      });
      const el = $('parts-estimate');
      el.style.display = '';
      el.textContent = `✂️ စုစုပေါင်း ${data.total_parts} ပိုင်း ထွက်ပါမည် (${fmtTime(data.duration)})`;
      const field = $('split-estimate');
      if (field) field.value = `${data.total_parts} ပိုင်း · ${fmtTime(data.duration)}`;
    } catch { /* ignore */ }
  }
  $('split-slice').addEventListener('change', estimateSplitParts);

  $('btn-split').onclick = async () => {
    const source = state.splitVideo || state.video;
    if (!source) return toast('ဗီဒီယိုဖိုင် အရင်တင်ပါ (Studio တွင် တင်ထားသည်ကိုလည်း သုံးနိုင်သည်)', 'err');
    const btn = $('btn-split');
    btn.disabled = true; btn.textContent = '✂ ခွဲထုတ်နေသည်…';
    $('split-results').innerHTML = '';
    splitProgress(true, 'ခွဲထုတ်ရန် စတင်နေပါသည်…', 2);
    try {
      const data = await api('/api/split-video', {
        method: 'POST',
        body: {
          video_path: source.path,
          slice_sec: Number($('split-slice').value),
          aspect: $('split-aspect').value,
          async: true
        },
        timeout: 60000
      });
      if (data.task_id) {
        state.splitJobId = data.task_id;
        startSplitPolling(data.task_id);
      } else {
        renderSplitParts(data.parts || []);
        splitProgress(false);
      }
    } catch (err) {
      splitProgress(false);
      toast('Splitter Error: ' + err.message, 'err', 12000);
    } finally {
      btn.disabled = false; btn.textContent = '✂ အပိုင်းများ ခွဲထုတ်မည်';
    }
  };

  function startSplitPolling(taskId) {
    $('btn-cancel-split').onclick = async () => {
      try {
        await api(`/api/tasks/${taskId}/cancel`, { method: 'POST', body: {} });
        toast('ရပ်တန့်ရန် တောင်းဆိုလိုက်ပါပြီ', 'warn');
      } catch (err) { toast(err.message, 'err'); }
    };
    const timer = setInterval(async () => {
      try {
        const job = await api(`/api/tasks/${taskId}`, { timeout: 20000 });
        splitProgress(true, job.message || 'ခွဲထုတ်နေသည်…', job.progress || 0,
          job.status === 'failed');
        if (job.status === 'completed') {
          clearInterval(timer);
          splitProgress(false);
          renderSplitResult(job);
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          clearInterval(timer);
          splitProgress(false);
          if (job.status === 'failed') toast('Splitter မအောင်မြင်ပါ: ' + (job.error || job.message), 'err', 15000);
          else toast('ခွဲထုတ်ခြင်းကို ရပ်လိုက်ပါပြီ', 'warn');
        }
      } catch (err) {
        // keep trying — a single failed poll must not hide the running job
      }
    }, 1500);
  }

  function renderSplitResult(job) {
    const parts = ((job.stats || {}).split || {}).parts || [];
    renderSplitParts(parts);
    if (parts.length) toast(`အပိုင်း ${parts.length} ခု ခွဲထုတ်ပြီးပါပြီ`, 'ok');
  }

  function renderSplitParts(parts) {
    $('split-results').innerHTML = (parts || []).map((p) => `
      <div class="card" style="padding:12px">
        <b>Part ${p.part}</b>
        <p class="sub">${p.duration}s · ${fmtBytes(p.size)}</p>
        <div class="btn-row">
          <a class="btn small success" href="${p.url}" download>📥 ဒေါင်းလုဒ်</a>
          <a class="btn small ghost" href="${p.preview_url || p.url}" target="_blank" rel="noopener">▶ ကြည့်</a>
        </div>
      </div>`).join('') || '<p class="empty">အပိုင်း မထွက်ပါ</p>';
    if (parts && parts.length) {
      const bar = document.createElement('div');
      bar.className = 'btn-row';
      bar.style.marginTop = '12px';
      bar.innerHTML = `<button class="btn small primary" id="btn-download-all">⬇️ အားလုံး ဒေါင်းလုဒ် (${parts.length})</button>`;
      $('split-results').appendChild(bar);
      $('btn-download-all').onclick = () => {
        parts.forEach((p, i) => setTimeout(() => {
          const a = document.createElement('a');
          a.href = p.url; a.download = p.filename || `part_${p.part}.mp4`;
          document.body.appendChild(a); a.click(); a.remove();
        }, i * 800));
        toast('ဒေါင်းလုဒ် စတင်ပါပြီ — browser မှ ဖိုင် သိမ်းခွင့် ပြုပါ', 'info', 6000);
      };
    }
  }

  async function loadJobs() {
    try {
      const data = await api('/api/tasks', { timeout: 20000, retries: 1 });
      const rows = (data.tasks || []);
      $('jobs-body').innerHTML = rows.length ? rows.map((j) => `
        <tr>
          <td>${new Date(j.created_at * 1000).toLocaleString()}</td>
          <td><span class="chip ${j.status === 'completed' ? 'ok' : j.status === 'failed' ? 'bad' : 'muted'}">${j.status}</span>
              ${j.kind === 'split' ? '<span class="tag">split</span>' : ''}</td>
          <td>${fmtTime(j.duration)}</td>
          <td>${j.output_video ? escapeHtml(j.output_video.split('/').pop()) : (j.kind === 'split' ? 'parts' : '—')}</td>
          <td>
            ${j.download_url ? `<a class="btn small success" href="${j.download_url}" download>📥</a>` : ''}
            ${j.status === 'running' || j.status === 'queued' ? `<button class="btn small warn" data-watch="${j.id}">👁</button>` : ''}
            ${j.status === 'completed' ? `<button class="btn small ghost" data-open="${j.id}">⏱️</button>` : ''}
            <button class="btn small danger" data-del="${j.id}">🗑</button>
          </td>
        </tr>`).join('') : '<tr><td colspan="5" class="empty">Job မရှိသေးပါ။</td></tr>';
      $('jobs-body').querySelectorAll('[data-watch]').forEach((b) => {
        b.onclick = () => { switchTab('studio'); startPolling(b.dataset.watch); };
      });
      $('jobs-body').querySelectorAll('[data-open]').forEach((b) => {
        b.onclick = async () => {
          const job = await api(`/api/tasks/${b.dataset.open}`);
          renderJob(job);
          renderTimeline(job);
          switchTab('timeline');
        };
      });
      $('jobs-body').querySelectorAll('[data-del]').forEach((b) => {
        b.onclick = async () => {
          if (!confirm('ဒီ Job နှင့် ဖိုင်များကို ဖျက်မှာ သေချာပါသလား?')) return;
          try { await api(`/api/tasks/${b.dataset.del}`, { method: 'DELETE' }); loadJobs(); toast('ဖျက်လိုက်ပါပြီ', 'ok'); }
          catch (err) { toast(err.message, 'err'); }
        };
      });
    } catch (err) { toast('Job list ရယူ၍ မရပါ: ' + err.message, 'err'); }
  }
  $('btn-refresh-jobs').onclick = loadJobs;

  /* ══════════════════════════ SETTINGS ═════════════════════════════ */
  function setConnBanner(show, text) {
    const el = $('conn-banner');
    el.classList.toggle('hidden', !show);
    if (text) $('conn-banner-text').textContent = text;
  }

  function renderStatusChips(info) {
    const chips = $('status-chips');
    if (!info) {
      chips.innerHTML = `<span class="chip warn">⚠️ Server ချိတ်ဆက်မှု မရပါ</span>
                         <span class="chip muted">v?</span>`;
      return;
    }
    const ff = info.ffmpeg && info.ffmpeg.available && info.ffmpeg.ffprobe;
    const keys = info.api_keys || {};
    const setKeys = (keys.keys || []).filter((k) => k.set).length;
    chips.innerHTML = `
      <span class="chip ${ff ? 'ok' : 'bad'}">${ff ? '⚙️ FFmpeg Ready' : '⛔ FFmpeg Missing'}</span>
      <span class="chip ${info.fonts && info.fonts.ok ? 'ok' : 'warn'}">${info.fonts && info.fonts.ok ? '🔤 Myanmar Font OK' : '⚠️ Font Missing'}</span>
      <span class="chip ${(info.disk.free > 2 * 1024 ** 3) ? 'violet' : 'warn'}">💾 ${escapeHtml(info.disk.free_human)} free</span>
      <span class="chip ${setKeys ? 'ok' : 'bad'}">🔑 Key ${setKeys}/${info.limits.max_api_keys || 3}${keys.active_slot ? ` · #${keys.active_slot}` : ''}</span>
      <span class="chip muted">v${escapeHtml(info.version)}</span>
      ${info.demo_mode ? '<span class="chip warn">🧪 Demo Mode</span>' : ''}`;
    const hint = $('upload-limit-hint');
    if (hint && info.limits) {
      hint.textContent =
        `အများဆုံး ${fmtBytes(info.limits.max_upload_bytes)} · အပိုင်းတစ်ပိုင်း ` +
        `${fmtBytes(info.limits.upload_chunk_bytes || 0)} — ရပ်သွားလျှင် ဆက်တင်နိုင်သည်။`;
    }
  }

  async function refreshSystem() {
    const btn = $('btn-refresh-system');
    if (btn) btn.disabled = true;
    try {
      const info = await api('/api/system', { timeout: 15000, retries: 1 });
      state.catalog = info;
      state.serverOk = true;
      if (info.version && $('app-version')) $('app-version').textContent = `v${info.version}`;
      state.accessOk = info.access_ok !== false;
      renderStatusChips(info);
      setConnBanner(false);
      $('access-banner').classList.toggle('hidden', state.accessOk || !info.access_required);
      $('sys-stats').innerHTML = [
        ['FFmpeg', info.ffmpeg.available ? '✅' : '⛔'],
        ['Myanmar Font', info.fonts.ok ? '✅' : '⚠️'],
        ['Free Disk', info.disk.free_human],
        ['App Data', info.disk.used_by_app_human || fmtBytes(info.disk.used_by_app || 0)],
        ['Max Upload', fmtBytes(info.limits.max_upload_bytes)],
        ['Temp', `${info.limits.max_chunk_seconds}s`]
      ].map(([k, v]) => `<div class="stat"><b>${escapeHtml(String(v))}</b><span>${k}</span></div>`).join('');
      const rt = info.jobs_runtime || {};
      $('sys-detail').textContent =
        `${info.ffmpeg.version}\nfont: ${(info.fonts && info.fonts.regular) || 'missing'}` +
        `\nchunk: ${info.limits.max_chunk_seconds}s\njobs: ${rt.workers || '?'} worker, ` +
        `${rt.active || 0} active, ${rt.ffmpeg_running || 0} ffmpeg` +
        `\ndata: ${info.disk.data_dir || '(hidden)'}`;
      renderModels();
      renderVoices();
      if (info.api_keys && state.accessOk) applyKeyRing(info.api_keys);
    } catch (err) {
      state.serverOk = false;
      renderStatusChips(null);
      if (err.status === 401) {
        state.accessOk = false;
        $('access-banner').classList.remove('hidden');
        setConnBanner(false);
      } else {
        setConnBanner(true, `⚠️ Server ချိတ်ဆက်မှု မရပါ (${err.message}) — ပြန်စမ်းနေပါသည်…`);
      }
      // the Studio must stay usable: fall back to the built-in catalog
      renderModels();
      renderVoices();
    } finally {
      if (btn) btn.disabled = false;
    }
    try {
      const cfg = await api('/api/config', { timeout: 15000 });
      const ring = cfg.api_keys || {};
      const setCount = (ring.keys || []).filter((k) => k.set).length;
      $('cfg-key-state').className = `chip ${setCount ? 'ok' : 'warn'}`;
      $('cfg-key-state').textContent = setCount
        ? `✅ Key ${setCount} ခု သိမ်းထားသည်${ring.active_slot ? ` · အသုံးပြုနေသည် #${ring.active_slot}` : ''}`
        : '⚠️ API Key မရှိသေးပါ';
      if (cfg.model && [...$('cfg-model').options].some((o) => o.value === cfg.model)) {
        $('cfg-model').value = cfg.model;
      }
      if (cfg.access_ok !== false) applyKeyRing(ring);
      $('cfg-access').value = accessKey();
    } catch (err) {
      $('cfg-key-state').className = 'chip warn';
      $('cfg-key-state').textContent = '⚠️ Settings ရယူ၍ မရပါ';
    }
  }
  $('btn-refresh-system').onclick = refreshSystem;
  $('btn-retry-conn').onclick = refreshSystem;

  // ── key ring UI ──────────────────────────────────────────────────────
  function applyKeyRing(ring) {
    if (!ring || !ring.keys) return;
    ring.keys.forEach((slot) => {
      const row = document.querySelector(`.key-row[data-slot="${slot.slot}"]`);
      if (!row) return;
      const input = $(`cfg-key-${slot.slot}`);
      row.classList.toggle('active', ring.active_slot === slot.slot);
      const radio = row.querySelector('input[type=radio]');
      radio.checked = ring.active_slot === slot.slot;
      radio.disabled = !slot.set;
      if (input) {
        input.placeholder = slot.set
          ? `${slot.masked}${slot.read_only ? ' • .env မှ (ပြင်၍ မရ)' : ' • အသစ်ထည့်လျှင် အစားထိုးမည်'}`
          : (slot.slot === 1 ? 'AIzaSy… Key #1 (အဓိက)'
            : `Key #${slot.slot} (${slot.slot === 2 ? 'quota ဖြည့်' : 'အပို'})`);
        input.disabled = !!slot.read_only;
      }
      let stateEl = row.querySelector('.state');
      if (!stateEl) {
        stateEl = document.createElement('span');
        stateEl.className = 'state';
        row.appendChild(stateEl);
      }
      if (slot.cooldown_seconds > 0) {
        stateEl.className = 'state bad';
        stateEl.textContent = `⏳ ${slot.cooldown_seconds}s အနားယူနေသည် — ${slot.last_error || 'error'}`;
      } else {
        stateEl.className = slot.set ? 'state ok' : 'state';
        stateEl.textContent = slot.set ? '✅ အလုပ်လုပ်နိုင်သည်' : 'Key မထည့်ရသေးပါ';
      }
    });
    $('cfg-failover').checked = ring.failover !== false;
    const setCount = (ring.keys || []).filter((k) => k.set).length;
    $('cfg-key-detail').textContent = setCount
      ? `Key ${setCount} ခု ရှိပါသည် — quota error တက်လျှင် အလိုအလျောက် နောက် key သို့ ပြောင်းပါမည်။`
      : 'Key တစ်ခုမှ မထည့်ရသေးပါ။ https://aistudio.google.com/apikey မှ ရယူပါ။';
  }

  async function saveSettings() {
    LS.set('rs_access', $('cfg-access').value.trim());
    const remember = $('cfg-remember').checked;
    const keys = [];
    for (let slot = 1; slot <= 3; slot++) {
      const input = $(`cfg-key-${slot}`);
      if (!input) continue;
      const value = input.value.trim();
      if (value) keys.push({ slot, key: value });
    }
    const activeRadio = document.querySelector('input[name=active-key]:checked');
    const body = { model: $('cfg-model').value, failover: $('cfg-failover').checked };
    try {
      await api('/api/config', { method: 'POST', body });   // model + defaults
      let ring = null;
      if (keys.length) ring = await api('/api/keys', { method: 'POST', body: { keys } });
      const active = activeRadio && !activeRadio.disabled ? Number(activeRadio.value) : 0;
      if (active) ring = await api('/api/keys', { method: 'POST', body: { active_slot: active } });
      for (let slot = 1; slot <= 3; slot++) { const el = $(`cfg-key-${slot}`); if (el && !el.disabled) el.value = ''; }
      // remember per browser so a refresh never asks for the key again
      if (remember) {
        const existing = LS.json('rs_keys', {});
        keys.forEach((k) => { existing[k.slot] = k.key; });
        LS.setJson('rs_keys', existing);
      } else {
        LS.del('rs_keys');
      }
      toast('Settings သိမ်းပြီးပါပြီ' + (keys.length ? ` (Key ${keys.length} ခု)` : ''), 'ok');
      refreshSystem();
    } catch (err) { toast('သိမ်း၍ မရပါ: ' + err.message, 'err', 12000); }
  }
  $('btn-save-settings').onclick = saveSettings;

  $('btn-test-keys').onclick = async () => {
    const btn = $('btn-test-keys');
    btn.disabled = true; btn.textContent = '🧪 စစ်ဆေးနေသည်…';
    try {
      // test whatever is typed in the boxes first (so a new key can be checked
      // before saving), otherwise test the stored slots
      const staged = [];
      for (let slot = 1; slot <= 3; slot++) {
        const el = $(`cfg-key-${slot}`);
        if (el && !el.disabled && el.value.trim()) staged.push({ slot, key: el.value.trim() });
      }
      const results = [];
      for (const item of staged) {
        const r = await api('/api/keys/test', { method: 'POST', body: item, timeout: 40000 });
        results.push(...(r.results || []));
      }
      if (!staged.length) {
        const r = await api('/api/keys/test', { method: 'POST', body: {}, timeout: 90000 });
        results.push(...(r.results || []));
      }
      results.forEach((r) => toast(`Key #${r.slot}: ${r.message}`, r.ok ? 'ok' : 'err', 9000));
      if (!results.length) toast('စစ်ဆေးရန် Key မရှိပါ', 'warn');
      refreshSystem();
    } catch (err) { toast('Key စစ်ဆေး၍ မရပါ: ' + err.message, 'err'); }
    finally { btn.disabled = false; btn.textContent = '🧪 Key အားလုံး စစ်မည်'; }
  };

  // Mirror whatever is typed into a slot immediately (debounced). Before this,
  // a key typed but never saved with the button vanished on refresh — which is
  // exactly the "refresh လုပ်ရင် API key ပျောက်" complaint.
  let mirrorTimer = null;
  function mirrorKeysSoon() {
    clearTimeout(mirrorTimer);
    mirrorTimer = setTimeout(() => {
      if (!$('cfg-remember').checked) return;
      const existing = LS.json('rs_keys', {}) || {};
      for (let slot = 1; slot <= 3; slot++) {
        const el = $(`cfg-key-${slot}`);
        if (!el || el.disabled) continue;
        const value = el.value.trim();
        if (value) existing[slot] = value;
      }
      if (Object.keys(existing).length) LS.setJson('rs_keys', existing);
    }, 400);
  }
  for (let slot = 1; slot <= 3; slot++) {
    const el = $(`cfg-key-${slot}`);
    if (el) el.addEventListener('input', mirrorKeysSoon);
  }
  $('cfg-remember').addEventListener('change', () => {
    if (!$('cfg-remember').checked) LS.del('rs_keys');
    else mirrorKeysSoon();
  });

  document.querySelectorAll('#key-ring input[type=radio]').forEach((radio) => {
    radio.addEventListener('change', async () => {
      const slot = Number(radio.value);
      try {
        const ring = await api('/api/keys', { method: 'POST', body: { active_slot: slot } });
        applyKeyRing(ring);
        toast(`Key #${slot} ကို အသုံးပြုမည်`, 'ok');
      } catch (err) { toast(err.message, 'err'); refreshSystem(); }
    });
  });

  $('btn-quick-access').onclick = async () => {
    LS.set('rs_access', $('quick-access-key').value.trim());
    $('cfg-access').value = accessKey();
    await refreshSystem();
    if (state.accessOk) {
      $('access-banner').classList.add('hidden');
      toast('Access Key ချိတ်ဆက်ပြီးပါပြီ', 'ok');
    } else {
      toast('Access Key မမှန်ကန်ပါ', 'err');
    }
  };

  /* ═══════════════════════════ INIT ════════════════════════════════ */
  function bindUiSync() {
    $('lang').addEventListener('change', () => { renderVoices(); persistUiState(); });
    $('voice').addEventListener('change', persistUiState);
    ['mode', 'fill-mode', 'quality', 'aspect', 'reframe'].forEach((id) =>
      $(id).addEventListener('change', persistUiState));
    $('model').addEventListener('change', () => { LS.set('rs_model', $('model').value); });
    ['sub-font', 'sub-color', 'sub-bg'].forEach((id) => {
      $(id).addEventListener('input', () => { styleSubtitleOverlay(); persistUiState(); });
    });
    ['hook1', 'hook2'].forEach((id) => $(id).addEventListener('input', () => {
      updateHookOverlay(); persistUiState();
    }));
    $('hook-seconds').addEventListener('change', persistUiState);
    $('mute-original').addEventListener('change', () => {
      $('original-audio-row').classList.toggle('hidden', $('mute-original').checked);
    });
    $('enable-subs').addEventListener('change', () => {
      $('overlay-sub').classList.toggle('hidden', !$('enable-subs').checked);
    });
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); $('btn-start').click(); }
    });
    // A tab that was in the background misses nothing: re-sync immediately and
    // restart a poll that died while the page was hidden.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      if (state.lastJobId && !state.poll) {
        api(`/api/tasks/${state.lastJobId}`, { timeout: 15000 })
          .then((job) => {
            renderJob(job);
            if (job.status === 'running' || job.status === 'queued') startPolling(job.id);
          })
          .catch(() => { /* handled by refreshSystem below */ });
      }
      refreshSystem();
    });
  }

  /** Re-attach to a running job after a refresh (even without localStorage). */
  async function restoreActiveJob() {
    try {
      const data = await api('/api/tasks/active', { timeout: 15000 });
      if (data.task) {
        state.lastJobId = data.task.id;
        LS.set('rs_last_job', data.task.id);
        if (data.task.kind === 'split') {
          switchTab('split');
          startSplitPolling(data.task.id);
        } else {
          renderJob(data.task);
          renderTimeline(data.task);
          renderCoverage(data.task);
          startPolling(data.task.id);
          toast('လုပ်ဆောင်နေသော Job ကို ပြန်ချိတ်လိုက်ပါသည်', 'info');
          return true;
        }
      }
    } catch { /* offline: ignore */ }
    return false;
  }

  /** Restore the last uploaded video so a refresh does not need a re-upload. */
  async function restoreVideos() {
    const saved = LS.json('rs_video', null);
    if (saved && saved.path) {
      try {
        const res = await fetch(`/api/asset?path=${encodeURIComponent(saved.path)}`, {
          method: 'HEAD', credentials: 'same-origin', headers: authHeaders('HEAD')
        });
        if (res.ok) {
          state.video = saved;
          setFilePill('studio', {
            name: saved.name || 'video',
            info: `${fmtTime(saved.duration)} · ${saved.width || '?'}×${saved.height || '?'} · ${fmtBytes(saved.size)}`
          }, saved.previewUrl);
          if (saved.previewUrl) $('preview-video').src = saved.previewUrl;
          estimateSplitParts();
        } else {
          LS.del('rs_video');
        }
      } catch { /* server offline - keep the stored entry for later */ }
    }
    const savedSplit = LS.json('rs_split_video', null);
    if (savedSplit && savedSplit.path) {
      state.splitVideo = savedSplit;
      setFilePill('split', {
        name: savedSplit.name || 'video',
        info: `${fmtTime(savedSplit.duration)} · ${fmtBytes(savedSplit.size)}`
      }, savedSplit.previewUrl);
      estimateSplitParts();
    }
  }

  /** Push keys remembered in this browser if the server has none (or fewer). */
  async function restoreKeys() {
    const local = LS.json('rs_keys', null);
    if (!local) return;
    try {
      const cfg = await api('/api/config', { timeout: 15000 });
      if (cfg.access_ok === false) return;
      const serverSet = new Set((cfg.api_keys.keys || []).filter((k) => k.set).map((k) => k.slot));
      const toSend = Object.entries(local)
        .filter(([slot, key]) => key && !serverSet.has(Number(slot)))
        .map(([slot, key]) => ({ slot: Number(slot), key }));
      if (toSend.length) {
        await api('/api/keys', { method: 'POST', body: { keys: toSend } });
        toast(`သိမ်းထားသော API Key ${toSend.length} ခုကို server သို့ ပြန်လည် ဖြည့်လိုက်ပါသည်`, 'ok', 6000);
        refreshSystem();
      } else {
        applyKeyRing(cfg.api_keys);
      }
    } catch { /* offline: the key stays in the browser and is retried later */ }
  }

  // ══════════════════════════════════════════════════════════════════
  // Authentication (Phase 2) — login gate, account chip, admin panel
  // ══════════════════════════════════════════════════════════════════
  let authMode = 'open';
  let signupView = false;

  function showAuthError(message) {
    const box = $('auth-error');
    if (!box) return;
    if (!message) { box.classList.add('hidden'); box.textContent = ''; return; }
    box.textContent = message;
    box.classList.remove('hidden');
  }

  function renderAuthForm() {
    const state_ = state.auth || {};
    const legacy = state_.mode === 'legacy';
    const firstRun = state_.mode === 'users' && !state_.has_users;
    const canSignup = Boolean(state_.signup_enabled) || firstRun;
    signupView = firstRun ? true : signupView;

    $('auth-access-row').classList.toggle('hidden', !legacy);
    $('auth-username').closest('.field').classList.toggle('hidden', legacy);
    $('auth-password').closest('.field').classList.toggle('hidden', legacy);
    $('auth-confirm-row').classList.toggle('hidden', legacy || !signupView);
    $('auth-invite-row').classList.toggle('hidden',
      legacy || !signupView || firstRun || !state_.signup_code_required);
    $('auth-toggle').classList.toggle('hidden', legacy || !canSignup || firstRun);
    $('auth-toggle').textContent = signupView
      ? '← ရှိပြီးသား အကောင့်ဖြင့် ဝင်မည်' : 'အကောင့် အသစ် ဖွင့်မည်';

    if (legacy) {
      $('auth-subtitle').textContent = 'ဤ server တွင် Access Key လိုအပ်ပါသည်';
      $('auth-submit').textContent = '🔓 ချိတ်ဆက်မည်';
      $('auth-hint').textContent = 'Server ၏ .env ထဲက RECAP_ACCESS_PASSWORD ကို ထည့်ပါ။';
    } else if (firstRun) {
      $('auth-subtitle').textContent = 'ပထမဆုံး အကောင့် (admin) ကို ဖန်တီးပါ';
      $('auth-submit').textContent = '🚀 Admin အကောင့် ဖန်တီးမည်';
      $('auth-hint').textContent =
        'ဤ server တွင် အကောင့် မရှိသေးပါ — ယခု ဖန်တီးသူသည် admin ဖြစ်ပါမည်။';
    } else if (signupView) {
      $('auth-subtitle').textContent = 'အကောင့် အသစ် ဖွင့်ရန်';
      $('auth-submit').textContent = '➕ အကောင့် ဖွင့်မည်';
      $('auth-hint').textContent =
        `စကားဝှက် အနည်းဆုံး ${state_.password_min_length || 10} လုံး — စာလုံးနှင့် ဂဏန်း ရောပါရမည်။`;
    } else {
      $('auth-subtitle').textContent = 'ဆက်လက် အသုံးပြုရန် အကောင့်ဖြင့် ဝင်ပါ';
      $('auth-submit').textContent = '🔓 ဝင်မည် (Sign in)';
      $('auth-hint').textContent = 'အကောင့် မရှိသေးပါက server admin ထံ တောင်းဆိုပါ။';
    }
  }

  function showAuthOverlay(show) {
    const overlay = $('auth-overlay');
    if (!overlay) return;
    overlay.classList.toggle('hidden', !show);
    document.body.style.overflow = show ? 'hidden' : '';
    if (show) {
      renderAuthForm();
      setTimeout(() => {
        const field = (state.auth && state.auth.mode === 'legacy')
          ? $('auth-access') : $('auth-username');
        field && field.focus();
      }, 60);
    }
  }

  function renderAccountChip() {
    const box = $('account-box');
    const chip = $('chip-account');
    const user = state.auth && state.auth.user;
    if (!box || !chip) return;
    const openBanner = $('open-banner');
    if (openBanner) {
      openBanner.classList.toggle('hidden',
        !(authMode === 'open' && state.auth && state.auth.has_users === false));
    }
    if (!user || authMode === 'open') { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    const role = user.role === 'admin' ? ' · admin' : '';
    chip.textContent = `👤 ${user.username}${role}`;
    $('account-card') && $('account-card').classList.toggle('hidden', authMode !== 'users');
    $('acct-role') && ($('acct-role').textContent = user.role || '—');
    const isAdmin = Boolean(user.is_admin) && authMode === 'users';
    $('admin-card') && $('admin-card').classList.toggle('hidden', !isAdmin);
    if (isAdmin) loadUsers();
  }

  function onSessionLost() {
    state.auth = { ...(state.auth || {}), authenticated: false, user: null };
    stopPolling();
    renderAccountChip();
    showAuthOverlay(true);
    showAuthError('Session ကုန်ဆုံးသွားပါပြီ — ပြန်လည် ဝင်ပေးပါ။');
  }

  async function refreshAuth() {
    try {
      const me = await api('/api/auth/me', { timeout: 15000, retries: 1 });
      state.auth = me;
      authMode = me.mode || 'open';
      state.authReady = true;
      renderAccountChip();
      return me;
    } catch (err) {
      state.auth = { mode: 'open', required: false, authenticated: true };
      authMode = 'open';
      state.authReady = true;
      return state.auth;
    }
  }

  async function submitAuth(event) {
    event && event.preventDefault();
    showAuthError('');
    const btn = $('auth-submit');
    btn.disabled = true;
    try {
      if (authMode === 'legacy') {
        const key = $('auth-access').value.trim();
        LS.set('rs_access', key);
        await api('/api/auth/login', { body: { access_key: key }, method: 'POST' });
      } else {
        const username = $('auth-username').value.trim();
        const password = $('auth-password').value;
        if (signupView) {
          if (password !== $('auth-password2').value) {
            throw new ApiError('စကားဝှက် နှစ်ခု မတူညီပါ', 400);
          }
          await api('/api/auth/register', {
            method: 'POST',
            body: { username, password, invite_code: $('auth-invite').value.trim() }
          });
        } else {
          await api('/api/auth/login', { method: 'POST', body: { username, password } });
        }
      }
      $('auth-password').value = '';
      $('auth-password2').value = '';
      await refreshAuth();
      showAuthOverlay(false);
      toast(`မင်္ဂလာပါ ${state.auth.user ? state.auth.user.username : ''} 👋`, 'ok', 4000);
      await bootApp();
    } catch (err) {
      showAuthError(err.message || 'ဝင်၍ မရပါ');
    } finally {
      btn.disabled = false;
    }
  }

  async function doLogout() {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* ignore */ }
    LS.del('rs_access');
    stopPolling();
    state.auth = { ...(state.auth || {}), authenticated: false, user: null };
    renderAccountChip();
    showAuthOverlay(true);
    toast('ထွက်ပြီးပါပြီ', 'ok', 3000);
  }

  async function changePassword() {
    const current = $('pw-current').value;
    const next = $('pw-new').value;
    if (next !== $('pw-new2').value) { toast('စကားဝှက် အသစ် နှစ်ခု မတူညီပါ', 'err'); return; }
    try {
      const res = await api('/api/auth/password', {
        method: 'POST', body: { current_password: current, new_password: next }
      });
      toast(res.message || 'စကားဝှက် ပြောင်းပြီးပါပြီ', 'ok');
      ['pw-current', 'pw-new', 'pw-new2'].forEach((id) => { $(id).value = ''; });
      setTimeout(() => { onSessionLost(); }, 800);
    } catch (err) { toast(err.message, 'err'); }
  }

  async function revokeSessions() {
    try {
      await api('/api/auth/sessions/revoke', { method: 'POST' });
      toast('Device အားလုံးမှ ထွက်ပြီးပါပြီ', 'ok');
      setTimeout(() => onSessionLost(), 600);
    } catch (err) { toast(err.message, 'err'); }
  }

  // ── admin panel ────────────────────────────────────────────────────
  function userRow(user) {
    const row = document.createElement('div');
    row.className = `user-row${user.status === 'disabled' ? ' is-disabled' : ''}`;
    const last = user.last_login_at
      ? new Date(user.last_login_at * 1000).toLocaleString() : 'မဝင်ဖူးသေးပါ';
    row.innerHTML = `
      <span class="uname">${escapeHtml(user.username)}</span>
      <span class="badge ${user.role === 'admin' ? 'admin' : ''}">${escapeHtml(user.role)}</span>
      <span class="umeta">နောက်ဆုံးဝင်: ${escapeHtml(last)} · job/24h: ${user.jobs_today || 0}
        · disk: ${fmtBytes(user.disk_used || 0)}</span>
      <span class="spacer"></span>`;
    const mk = (label, title, handler) => {
      const btn = document.createElement('button');
      btn.className = 'btn small ghost';
      btn.textContent = label;
      btn.title = title;
      btn.onclick = handler;
      row.appendChild(btn);
      return btn;
    };
    mk('🔑', 'စကားဝှက် reset', async () => {
      const pw = prompt(`'${user.username}' အတွက် စကားဝှက် အသစ် (အနည်းဆုံး 10 လုံး):`);
      if (!pw) return;
      try {
        await api(`/api/admin/users/${user.id}`, { method: 'PATCH', body: { password: pw } });
        toast('စကားဝှက် ပြောင်းပြီးပါပြီ', 'ok');
        loadUsers();
      } catch (err) { toast(err.message, 'err'); }
    });
    mk(user.status === 'active' ? '🚫' : '✅',
       user.status === 'active' ? 'အကောင့် ပိတ်မည်' : 'ပြန်ဖွင့်မည်', async () => {
      try {
        await api(`/api/admin/users/${user.id}`, {
          method: 'PATCH',
          body: { status: user.status === 'active' ? 'disabled' : 'active' }
        });
        loadUsers();
      } catch (err) { toast(err.message, 'err'); }
    });
    mk(user.role === 'admin' ? '⬇️' : '⬆️',
       user.role === 'admin' ? 'admin ဖြုတ်မည်' : 'admin ပေးမည်', async () => {
      try {
        await api(`/api/admin/users/${user.id}`, {
          method: 'PATCH', body: { role: user.role === 'admin' ? 'user' : 'admin' }
        });
        loadUsers();
      } catch (err) { toast(err.message, 'err'); }
    });
    mk('🗑️', 'အကောင့် ဖျက်မည်', async () => {
      if (!confirm(`'${user.username}' ကို ဖျက်မည် — သေချာပါသလား?`)) return;
      try {
        await api(`/api/admin/users/${user.id}`, { method: 'DELETE' });
        toast('ဖျက်ပြီးပါပြီ', 'ok');
        loadUsers();
      } catch (err) { toast(err.message, 'err'); }
    });
    return row;
  }

  async function loadUsers() {
    const host = $('user-table');
    if (!host) return;
    try {
      const data = await api('/api/admin/users', { timeout: 20000 });
      state.users = data.users || [];
      host.innerHTML = '';
      if (!state.users.length) {
        host.innerHTML = '<p class="help">အကောင့် မရှိသေးပါ။</p>';
      } else {
        state.users.forEach((user) => host.appendChild(userRow(user)));
      }
      const audit = await api('/api/admin/audit?limit=40', { timeout: 20000 });
      $('audit-log').textContent = (audit.entries || []).map((e) => {
        const when = new Date(e.created_at * 1000).toLocaleString();
        return `${when}  ${e.action}  ${e.username || '-'}  ${e.target || ''} ${e.detail || ''}`
          .trim();
      }).join('\n') || 'မှတ်တမ်း မရှိသေးပါ';
    } catch (err) {
      host.innerHTML = `<p class="help">အသုံးပြုသူစာရင်း မရယူနိုင်ပါ — ${escapeHtml(err.message)}</p>`;
    }
  }

  async function createUser() {
    const username = $('new-username').value.trim();
    const password = $('new-password').value;
    try {
      await api('/api/admin/users', {
        method: 'POST',
        body: { username, password, admin: $('new-admin').checked, must_change_password: false }
      });
      toast(`'${username}' အကောင့် ဖန်တီးပြီးပါပြီ`, 'ok');
      $('new-username').value = '';
      $('new-password').value = '';
      $('new-admin').checked = false;
      loadUsers();
    } catch (err) { toast(err.message, 'err'); }
  }

  function randomPassword() {
    const chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*-_';
    const bytes = new Uint32Array(18);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    const pw = Array.from(bytes, (b) => chars[b % chars.length]).join('');
    $('new-password').value = pw;
    $('new-password').type = 'text';
    toast('စကားဝှက် ကျပန်း ထုတ်ပြီးပါပြီ — မှတ်သားထားပါ', 'warn', 9000);
  }

  function bindAuthUi() {
    $('auth-form') && ($('auth-form').onsubmit = submitAuth);
    $('auth-toggle') && ($('auth-toggle').onclick = () => {
      signupView = !signupView;
      showAuthError('');
      renderAuthForm();
    });
    $('btn-logout') && ($('btn-logout').onclick = doLogout);
    $('btn-change-pw') && ($('btn-change-pw').onclick = changePassword);
    $('btn-revoke-sessions') && ($('btn-revoke-sessions').onclick = revokeSessions);
    $('btn-refresh-users') && ($('btn-refresh-users').onclick = loadUsers);
    $('btn-create-user') && ($('btn-create-user').onclick = createUser);
    $('btn-random-pw') && ($('btn-random-pw').onclick = randomPassword);
  }

  let initDone = false;
  let appBooted = false;

  async function bootApp() {
    if (appBooted) return;
    appBooted = true;
    // 2) … then upgrade from the server (never blocks the page)
    refreshSystem();
    restoreKeys();
    restoreVideos();

    // 3) re-attach to whatever is already running
    const attached = await restoreActiveJob();
    if (!attached && state.lastJobId) {
      try {
        const job = await api(`/api/tasks/${state.lastJobId}`, { timeout: 15000 });
        renderJob(job);
        renderTimeline(job);
        renderCoverage(job);
        if (job.status === 'running' || job.status === 'queued') startPolling(job.id);
      } catch { /* stale id */ }
    }
    setInterval(refreshSystem, 120000);   // keep the top bar (key/disk) fresh
  }

  async function init() {
    if (initDone) return;           // DOMContentLoaded + readyState race guard
    initDone = true;
    restoreUiState();
    bindUiSync();
    bindAuthUi();
    styleSubtitleOverlay();
    updateHookOverlay();
    renderPreviewMeta();
    $('original-audio-row').classList.toggle('hidden', $('mute-original').checked);

    // 1) paint the UI immediately from the built-in catalog …
    renderModels();
    renderVoices();

    // 2) is a sign-in required on this deployment?
    const me = await refreshAuth();
    if (me.required && !me.authenticated) {
      showAuthOverlay(true);
      return;                       // the rest boots after a successful login
    }
    showAuthOverlay(false);
    await bootApp();
  }

  window.addEventListener('beforeunload', stopPolling);
  window.addEventListener('online', () => { setConnBanner(false); refreshSystem(); });
  window.addEventListener('offline', () => setConnBanner(true, '⚠️ အင်တာနက် ပြတ်နေပါသည်…'));
  document.addEventListener('DOMContentLoaded', init);
  if (document.readyState !== 'loading') init();
})();
