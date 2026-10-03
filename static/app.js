/* ==========================================================================
   Recap Studio MM — front-end controller
   Sections: state · api · toasts · uploads · overlays · job runner ·
             timeline · tools (thumbnail/splitter/jobs) · settings · init
   ========================================================================== */
(() => {
  'use strict';

  // ── state ────────────────────────────────────────────────────────────
  const state = {
    system: null,
    video: null,          // {path, duration, width, height, size, previewUrl, name}
    logo: null,           // {path, previewUrl}
    job: null,            // current job object from the API
    poll: null,
    lastJobId: localStorage.getItem('rs_last_job') || null,
    logoPos: { x: 82, y: 4 },
    subPosPercent: 22
  };

  const $ = (id) => document.getElementById(id);
  const LS = {
    get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
  };

  // ── api helper ───────────────────────────────────────────────────────
  function accessKey() { return LS.get('rs_access', '') || ''; }

  async function api(path, { method = 'GET', body, form, signal } = {}) {
    const headers = {};
    if (accessKey()) headers['X-Access-Key'] = accessKey();
    let payload = form;
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const res = await fetch(path, { method, headers, body: payload, signal });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || text || `HTTP ${res.status}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
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
  // The old UI never reset input.value, so selecting the *same file twice*
  // fired no change event and the user had to "upload twice". Every handler
  // below resets the input first and uploads through one shared code path.
  let uploadAbort = false;
  let activeUpload = null;

  function setUploadUi(show, text = '', percent = 0, warn = false) {
    const box = $('video-upload-status');
    box.classList.toggle('show', show);
    if (!show) return;
    $('video-upload-text').textContent = text;
    $('video-meter-fill').style.width = `${percent}%`;
    $('video-meter').classList.toggle('amber', !!warn);
  }

  function setFilePill(name, info, thumbSrc) {
    $('video-pill').classList.remove('hidden');
    $('video-pill-name').textContent = name;
    $('video-pill-info').textContent = info;
    if (thumbSrc) $('video-pill-thumb').src = thumbSrc;
    $('step1-badge').textContent = '✓ အဆင်သင့်';
  }

  function applyVideoResult(data, file) {
    state.video = {
      path: data.video_path || data.path,
      duration: data.duration || 0,
      width: data.width, height: data.height,
      size: data.size || (file ? file.size : 0),
      previewUrl: data.preview_url || null,
      name: (file && file.name) || data.filename || 'video'
    };
    const localThumb = file ? URL.createObjectURL(file) : (state.video.previewUrl || '');
    setFilePill(state.video.name,
      `${fmtTime(state.video.duration)} · ${state.video.width || '?'}×${state.video.height || '?'} · ${fmtBytes(state.video.size)}`,
      localThumb);
    if (localThumb) $('preview-video').src = localThumb;
    $('parts-estimate').style.display = 'none';
    estimateParts();
  }

  async function uploadFile(file, { kind = 'video', onProgress } = {}) {
    // 1) negotiate a resumable session
    const init = await api('/api/upload/init', { method: 'POST', body: { filename: file.name, size: file.size, kind } });
    const chunkSize = init.chunk_size || 8 * 1024 * 1024;
    const total = Math.max(1, Math.ceil(file.size / chunkSize));
    const done = new Set();

    for (let index = 0; index < total; index++) {
      if (uploadAbort) throw new Error('UPLOAD_CANCELLED');
      const start = index * chunkSize;
      const blob = file.slice(start, Math.min(file.size, start + chunkSize));
      let attempt = 0, lastErr = null;
      while (attempt < 3) {
        try {
          await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            activeUpload = xhr;
            xhr.open('POST', '/api/upload/chunk');
            if (accessKey()) xhr.setRequestHeader('X-Access-Key', accessKey());
            xhr.upload.onprogress = (e) => {
              if (!onProgress) return;
              const sent = start + (e.loaded || 0);
              onProgress(Math.min(99, (sent / file.size) * 100),
                `တင်နေသည်… ${fmtBytes(sent)} / ${fmtBytes(file.size)} (အပိုင်း ${index + 1}/${total})`);
            };
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) { done.add(index); resolve(); }
              else {
                let msg = `HTTP ${xhr.status}`;
                try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* ignore */ }
                reject(new Error(msg));
              }
            };
            xhr.onerror = () => reject(new Error('ကွန်ယက် ပြတ်တောက်သွားပါသည် (chunk ပြန်စမ်းပါမည်)'));
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
          if (attempt < 3) {
            onProgress && onProgress(((start / file.size) * 100),
              `⚠️ Chunk ${index + 1} ပြန်စမ်းနေသည် (${attempt}/3)…`, true);
            await new Promise((r) => setTimeout(r, 900 * attempt));
          }
        }
      }
      if (attempt >= 3 && lastErr) throw lastErr;
    }
    onProgress && onProgress(99.5, 'ဖိုင် စစ်ဆေးနေပါသည်…');
    return api('/api/upload/complete', { method: 'POST', body: { upload_id: init.upload_id } });
  }

  async function handleVideoFile(file) {
    if (!file) return;
    if (!file.type.startsWith('video/') && !/\.(mp4|mov|mkv|webm|avi|m4v|ts|flv|wmv|3gp)$/i.test(file.name)) {
      toast('ဗီဒီယိုဖိုင် မဟုတ်ပါ (MP4/MOV/MKV/WEBM ဖြစ်ရပါမည်)', 'err');
      return;
    }
    uploadAbort = false;
    setUploadUi(true, 'တင်နေသည်…', 0);
    const btn = $('btn-start'); btn.disabled = true;
    try {
      const data = await uploadFile(file, {
        kind: 'video',
        onProgress: (pct, text, warn) => setUploadUi(true, text, pct, warn)
      });
      applyVideoResult(data, file);
      setUploadUi(false);
      toast(`ဗီဒီယို အဆင်သင့် — ${fmtTime(state.video.duration)}`, 'ok');
    } catch (err) {
      setUploadUi(false);
      if (String(err.message).includes('UPLOAD_CANCELLED')) toast('တင်ခြင်းကို ရပ်လိုက်ပါပြီ', 'warn');
      else toast('Upload မအောင်မြင်ပါ: ' + err.message, 'err', 12000);
    } finally {
      btn.disabled = false;
      activeUpload = null;
    }
  }

  // wire the dropzone + input + buttons
  const dropzone = $('dropzone');
  const videoInput = $('video-file');
  dropzone.onclick = () => { videoInput.value = ''; videoInput.click(); };  // reset => same file works again
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault(); dropzone.classList.remove('dragover');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleVideoFile(file);
  });
  videoInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    handleVideoFile(file);
    e.target.value = '';   // critical: allows re-selecting the same file
  });
  $('btn-cancel-upload').onclick = () => {
    uploadAbort = true;
    if (activeUpload) { try { activeUpload.abort(); } catch { /* ignore */ } }
    setUploadUi(false);
    toast('တင်ခြင်းကို ရပ်လိုက်ပါပြီ', 'warn');
  };
  $('btn-clear-video').onclick = () => {
    state.video = null;
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
      const data = await api('/api/upload-logo', { method: 'POST', form: fd });
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
      const data = await api('/api/download-url', { method: 'POST', body: { url } });
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
  function renderVoices() {
    const lang = $('lang').value;
    const voices = (state.system && state.system.voices) || {};
    const list = voices[lang] || {};
    $('voice').innerHTML = Object.entries(list)
      .map(([key, v]) => `<option value="${key}">${escapeHtml(v.name)}</option>`).join('');
    const preferred = LS.get('rs_voice_' + lang, '');
    if (preferred && list[preferred]) $('voice').value = preferred;
  }

  function renderModels() {
    const models = (state.system && state.system.models) || ['gemini-2.5-flash'];
    const options = models.map((m) => `<option value="${m}">${m}</option>`).join('');
    $('model').innerHTML = options;
    $('cfg-model').innerHTML = options;
    const saved = LS.get('rs_model', '');
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
      input_video: state.video.path,
      api_key: '',                                  // resolved server-side from settings
      model: $('model').value,
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
    const payload = collectPayload();
    try {
      const data = await api('/api/tasks', { method: 'POST', body: payload });
      state.lastJobId = data.task_id;
      LS.set('rs_last_job', data.task_id);
      toast('အလုပ် စတင်ပါပြီ — AI မှ ခွဲခြမ်းစိတ်ဖြာနေပါသည်', 'ok');
      startPolling(data.task_id);
      switchTab('studio');
    } catch (err) {
      toast('စတင်၍ မရပါ: ' + err.message, 'err', 12000);
    }
  };

  function renderStages(stages = {}) {
    const defs = [
      ['prepare', 'ဗီဒီယို စစ်ဆေးခြင်း'], ['analyze', 'AI ခွဲခြမ်းစိတ်ဖြာခြင်း'],
      ['coverage', 'လွတ်နေရာ ဖြည့်ခြင်း'], ['voice', 'အသံသွင်းခြင်း (TTS)'],
      ['mix', 'အသံ ပေါင်းစပ်ခြင်း'], ['subtitles', 'စာတန်းထိုး'],
      ['render', 'Final Render'], ['finalize', 'သိမ်းဆည်းခြင်း']
    ];
    $('job-stages').innerHTML = defs.map(([key, label]) => {
      const st = stages[key] || 'pending';
      const icon = st === 'done' ? '✓' : st === 'running' ? '●' : st === 'failed' ? '✕' : '';
      return `<div class="stage ${st}"><span class="dot">${icon}</span><span>${label}</span></div>`;
    }).join('');
  }

  function renderJob(job) {
    state.job = job;
    $('job-idle-msg').classList.add('hidden');
    $('job-live').classList.remove('hidden');
    $('job-percent').textContent = `${Math.round(job.progress || 0)}%`;
    $('job-meter-fill').style.width = `${job.progress || 0}%`;
    $('job-message').textContent = job.message || '…';
    const chip = $('job-status-chip');
    const map = { queued: ['muted', 'queued'], running: ['', 'running'], completed: ['ok', 'ပြီးစီး'],
                  failed: ['bad', 'မအောင်မြင်'], cancelled: ['warn', 'ရပ်ထား'] };
    const [cls, label] = map[job.status] || ['muted', job.status];
    chip.className = `chip ${cls}`;
    chip.textContent = label;
    chip.style.marginLeft = 'auto';
    if (job.eta_seconds) $('job-eta').textContent = `ခန့်မှန်း ကျန်ချိန် ≈ ${fmtTime(job.eta_seconds)} · လုပ်ဆောင်ချိန် ${fmtTime(job.elapsed_seconds)}`;
    else $('job-eta').textContent = job.elapsed_seconds ? `လုပ်ဆောင်ချိန် ${fmtTime(job.elapsed_seconds)}` : '—';
    renderStages(job.stages || {});
    if (job.logs) {
      const box = $('job-logs');
      box.textContent = job.logs.join('\n');
      box.scrollTop = box.scrollHeight;
    }

    if (job.status === 'completed') {
      stopPolling();
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
      toast('အလုပ် မအောင်မြင်ပါ: ' + (job.error || job.message), 'err', 20000);
    } else if (job.status === 'cancelled') {
      stopPolling();
      toast('အလုပ် ရပ်လိုက်ပါပြီ', 'warn');
    }
  }

  function startPolling(taskId) {
    stopPolling();
    $('job-result').classList.add('hidden');
    const tick = async () => {
      try {
        const job = await api(`/api/tasks/${taskId}`);
        renderJob(job);
      } catch (err) {
        stopPolling();
        toast('Job အခြေအနေ ရယူ၍ မရပါ: ' + err.message, 'err');
      }
    };
    tick();
    state.poll = setInterval(tick, 1600);
  }
  function stopPolling() { if (state.poll) { clearInterval(state.poll); state.poll = null; } }

  $('btn-cancel-job').onclick = async () => {
    if (!state.job) return;
    try {
      await api(`/api/tasks/${state.job.id}/cancel`, { method: 'POST', body: {} });
      toast('ရပ်တန့်ရန် တောင်းဆိုလိုက်ပါပြီ…', 'warn');
    } catch (err) { toast(err.message, 'err'); }
  };
  $('btn-goto-timeline').onclick = () => switchTab('timeline');

  /* ═════════════════════════ TIMELINE EDITOR ═══════════════════════ */
  function currentDialogues() {
    return (state.job && state.job.dialogues) ? state.job.dialogues : [];
  }

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
    const trimmed = new Set(((job.stats || {}).voice || {}).warnings ? [] : []);
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
    if (!cov || !cov.lines) { $('coverage-card').style.display = 'none'; return; }
    $('coverage-card').style.display = '';
    const filled = cov.gaps_filled || 0;
    $('coverage-stats').innerHTML = [
      ['Coverage', `${cov.coverage_percent}%`],
      ['စကားပြော စုစုပေါင်း', fmtTime(cov.spoken_seconds)],
      ['အများဆုံး လွတ်ကွက်', `${cov.longest_gap_seconds}s`],
      ['AI ဖြည့်လိုက်သည့် ကွက်', filled]
    ].map(([k, v]) => `<div class="stat"><b>${escapeHtml(String(v))}</b><span>${k}</span></div>`).join('');
    const strip = $('coverage-strip');
    const duration = job.duration || 1;
    const bars = (job.dialogues || []).map((d) =>
      `<div class="bar" style="left:${(d.start / duration) * 100}%;width:${Math.max(0.3, ((d.end - d.start) / duration) * 100)}%"></div>`).join('');
    strip.innerHTML = bars;
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
      await api(`/api/tasks/${state.job.id}/rerender`, { method: 'POST', body: payload });
      switchTab('studio');
      startPolling(state.job.id);
    } catch (err) { toast('Re-render မအောင်မြင်ပါ: ' + err.message, 'err'); }
  };

  $('btn-tl-preview').onclick = async () => {
    if (!state.video || !state.video.previewUrl) return toast('Preview အတွက် ဗီဒီယိုဖိုင် မရှိပါ', 'err');
    const v = $('preview-video');
    try { await v.play(); } catch { /* autoplay may be blocked */ }
    toast('Preview ကို ဖွင့်လိုက်ပါပြီ (အသံအတွက် Master MP4 ကို နားထောင်ပါ)', 'info', 3500);
  };

  /* ═════════════════ THUMBNAIL / SPLITTER / JOBS ═══════════════════ */
  $('thumb-file').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const data = await uploadFile(file, { kind: 'video', onProgress: (p, t) => toast(t, 'info', 1500) });
      state.video = { path: data.video_path, duration: data.duration, previewUrl: data.preview_url, name: file.name,
                      width: data.width, height: data.height, size: data.size };
      toast('Thumbnail အတွက် ဗီဒီယို အဆင်သင့်', 'ok');
    } catch (err) { toast('Upload မအောင်မြင်ပါ: ' + err.message, 'err'); }
  });

  $('btn-thumb').onclick = async () => {
    if (!state.video) return toast('ဗီဒီယိုဖိုင် အရင်တင်ပါ', 'err');
    const btn = $('btn-thumb'); btn.disabled = true;
    try {
      const res = await fetch('/api/thumbnail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(accessKey() ? { 'X-Access-Key': accessKey() } : {}) },
        body: JSON.stringify({
          video_path: state.video.path,
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

  $('split-file').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const data = await uploadFile(file, { kind: 'video', onProgress: (p, t) => toast(t, 'info', 1500) });
      state.video = { path: data.video_path, duration: data.duration, previewUrl: data.preview_url,
                      name: file.name, width: data.width, height: data.height, size: data.size };
      estimateParts();
      toast('Splitter အတွက် ဗီဒီယို အဆင်သင့်', 'ok');
    } catch (err) { toast('Upload မအောင်မြင်ပါ: ' + err.message, 'err'); }
  });

  async function estimateParts() {
    if (!state.video || !state.video.duration) return;
    try {
      const data = await api('/api/estimate-parts', {
        method: 'POST',
        body: { duration: state.video.duration, slice_sec: Number($('split-slice').value) }
      });
      const el = $('parts-estimate');
      el.style.display = '';
      el.textContent = `✂️ စုစုပေါင်း ${data.total_parts} ပိုင်း ထွက်ပါမည်`;
    } catch { /* ignore */ }
  }
  $('split-slice').addEventListener('change', estimateParts);

  $('btn-split').onclick = async () => {
    if (!state.video) return toast('ဗီဒီယိုဖိုင် အရင်တင်ပါ', 'err');
    const btn = $('btn-split'); btn.disabled = true; btn.textContent = '✂ ခွဲထုတ်နေသည်…';
    try {
      const data = await api('/api/split-video', {
        method: 'POST',
        body: { video_path: state.video.path, slice_sec: Number($('split-slice').value), aspect: $('split-aspect').value }
      });
      $('split-results').innerHTML = (data.parts || []).map((p) => `
        <div class="card" style="padding:12px">
          <b>Part ${p.part}</b>
          <p class="sub">${p.duration}s · ${fmtBytes(p.size)}</p>
          <a class="btn small success" href="${p.url}" download>📥 ဒေါင်းလုဒ်</a>
        </div>`).join('') || '<p class="empty">အပိုင်း မထွက်ပါ</p>';
      toast(`အပိုင်း ${(data.parts || []).length} ခု ခွဲထုတ်ပြီးပါပြီ`, 'ok');
    } catch (err) { toast('Splitter Error: ' + err.message, 'err'); }
    finally { btn.disabled = false; btn.textContent = '✂ အပိုင်းများ ခွဲထုတ်မည်'; }
  };

  async function loadJobs() {
    try {
      const data = await api('/api/tasks');
      const rows = (data.tasks || []);
      $('jobs-body').innerHTML = rows.length ? rows.map((j) => `
        <tr>
          <td>${new Date(j.created_at * 1000).toLocaleString()}</td>
          <td><span class="chip ${j.status === 'completed' ? 'ok' : j.status === 'failed' ? 'bad' : 'muted'}">${j.status}</span></td>
          <td>${fmtTime(j.duration)}</td>
          <td>${j.output_video ? escapeHtml(j.output_video.split('/').pop()) : '—'}</td>
          <td>
            ${j.download_url ? `<a class="btn small success" href="${j.download_url}" download>📥</a>` : ''}
            ${j.status === 'completed' ? `<button class="btn small ghost" data-open="${j.id}">⏱️</button>` : ''}
            <button class="btn small danger" data-del="${j.id}">🗑</button>
          </td>
        </tr>`).join('') : '<tr><td colspan="5" class="empty">Job မရှိသေးပါ။</td></tr>';
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
  async function refreshSystem() {
    try {
      const info = await api('/api/system');
      state.system = info;
      const chips = $('status-chips');
      const ff = info.ffmpeg.available && info.ffmpeg.ffprobe;
      chips.innerHTML = `
        <span class="chip ${ff ? 'ok' : 'bad'}">${ff ? '⚙️ FFmpeg Ready' : '⛔ FFmpeg Missing'}</span>
        <span class="chip ${info.fonts.ok ? 'ok' : 'warn'}">${info.fonts.ok ? '🔤 Myanmar Font OK' : '⚠️ Font Missing'}</span>
        <span class="chip ${info.disk.free > 2 * 1024 ** 3 ? 'violet' : 'warn'}">💾 ${escapeHtml(info.disk.free_human)} free</span>
        <span class="chip muted">v${escapeHtml(info.version)}</span>
        ${info.demo_mode ? '<span class="chip warn">🧪 Demo Mode</span>' : ''}
        ${!info.demo_mode && !info.has_api_key ? '<span class="chip bad">🔑 API Key မရှိသေးပါ</span>' : ''}`;

      $('sys-stats').innerHTML = [
        ['FFmpeg', info.ffmpeg.available ? '✅' : '⛔'],
        ['Myanmar Font', info.fonts.ok ? '✅' : '⚠️'],
        ['Free Disk', info.disk.free_human],
        ['Data Dir', escapeHtml(String(info.disk.data_dir).split('/').slice(-1)[0] || '/')],
        ['Max Upload', fmtBytes(info.limits.max_upload_bytes)],
        ['Concurrent Jobs', info.limits.max_concurrent_jobs]
      ].map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
      $('sys-detail').textContent =
        `${info.ffmpeg.version}\nfont: ${info.fonts.regular || 'missing'}\nchunk: ${info.limits.max_chunk_seconds}s`,
      renderModels();
      renderVoices();
    } catch (err) {
      $('status-chips').innerHTML = `<span class="chip bad">⚠️ Server ချိတ်ဆက်၍ မရပါ</span>`;
      toast('System info ရယူ၍ မရပါ: ' + err.message, 'err');
    }
    try {
      const cfg = await api('/api/config');
      $('cfg-key-state').textContent = cfg.gemini_api_key_set
        ? `✅ API Key သိမ်းထားပါသည် (${cfg.gemini_api_key_masked})`
        : '⚠️ API Key မရှိသေးပါ — ထည့်ပါ (Demo mode တွင် အလုပ်လုပ်ပါမည်)';
      if (cfg.model && [...$('cfg-model').options].some((o) => o.value === cfg.model)) $('cfg-model').value = cfg.model;
      $('cfg-access').value = accessKey();
    } catch (err) { /* access key missing - already surfaced */ }
  }
  $('btn-refresh-system').onclick = refreshSystem;

  $('btn-save-settings').onclick = async () => {
    LS.set('rs_access', $('cfg-access').value.trim());
    const body = { model: $('cfg-model').value };
    const key = $('cfg-key').value.trim();
    if (key) body.gemini_api_key = key;
    try {
      await api('/api/config', { method: 'POST', body });
      $('cfg-key').value = '';
      toast('Settings သိမ်းပြီးပါပြီ', 'ok');
      refreshSystem();
    } catch (err) { toast('သိမ်း၍ မရပါ: ' + err.message, 'err'); }
  };

  /* ═══════════════════════════ INIT ════════════════════════════════ */
  function bindUiSync() {
    $('lang').addEventListener('change', () => { renderVoices(); persistUiState(); });
    $('voice').addEventListener('change', persistUiState);
    $('mode').addEventListener('change', persistUiState);
    $('fill-mode').addEventListener('change', persistUiState);
    $('quality').addEventListener('change', persistUiState);
    $('aspect').addEventListener('change', persistUiState);
    $('reframe').addEventListener('change', persistUiState);
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
  }

  async function init() {
    if ('serviceWorker' in navigator) { /* no SW: keeps previews simple */ }
    restoreUiState();
    bindUiSync();
    styleSubtitleOverlay();
    updateHookOverlay();
    $('original-audio-row').classList.toggle('hidden', $('mute-original').checked);
    await refreshSystem();
    renderModels();
    renderVoices();
    if (state.lastJobId) {
      try {
        const job = await api(`/api/tasks/${state.lastJobId}`);
        renderJob(job);
        renderTimeline(job);
        renderCoverage(job);
        if (job.input_video) {
          state.video = {
            path: job.input_video,
            duration: job.duration || 0,
            previewUrl: job.preview_url || null,
            name: (job.input_video.split('/').pop() || 'video'),
            width: (job.stats && job.stats.input && job.stats.input.width) || 0,
            height: (job.stats && job.stats.input && job.stats.input.height) || 0,
            size: (job.stats && job.stats.input && job.stats.input.size) || 0
          };
          setFilePill(state.video.name, `${fmtTime(state.video.duration)} · ${fmtBytes(state.video.size)}`,
            job.preview_url || null);
          if (job.preview_url && job.status === 'completed') $('preview-video').src = job.preview_url;
        }
        if (job.status === 'running' || job.status === 'queued') startPolling(job.id);
      } catch { /* ignore stale job id */ }
    }
  }

  window.addEventListener('beforeunload', stopPolling);
  document.addEventListener('DOMContentLoaded', init);
  if (document.readyState !== 'loading') init();
})();
