// ── File upload handlers ──────────────────────────────────────────────────

// Recursively collect all files from a dropped FileSystemEntry, preserving paths.
async function _readEntryRecursive(entry, prefix) {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    return new Promise(resolve => {
      entry.file(f => resolve([new File([f], path, { type: f.type })]));
    });
  }
  // Directory: readEntries may batch results, must loop until empty
  const reader = entry.createReader();
  const children = [];
  let batch;
  do {
    batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    children.push(...batch);
  } while (batch.length);
  const nested = await Promise.all(children.map(c => _readEntryRecursive(c, path)));
  return nested.flat();
}

function setupDrop(dropId, inputId, uploadFn) {
  const drop = document.getElementById(dropId);
  const input = document.getElementById(inputId);
  if (!drop || !input) return;

  drop.addEventListener('click', e => { if (!e.target.closest('label')) input.click(); });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop.addEventListener('drop', async e => {
    e.preventDefault();
    drop.classList.remove('drag-over');
    // Use File System API for recursive subfolder support when available
    const items = [...(e.dataTransfer.items || [])];
    if (items.length && typeof items[0].webkitGetAsEntry === 'function') {
      const entries = items.map(i => i.webkitGetAsEntry()).filter(Boolean);
      const files = (await Promise.all(entries.map(ent => _readEntryRecursive(ent, '')))).flat();
      uploadFn(files);
    } else {
      uploadFn(e.dataTransfer.files);
    }
  });
  input.addEventListener('change', () => uploadFn(input.files));
}

async function uploadBrief(files) {
  if (!files || files.length === 0) return;
  showStatus('brief-drop', 'Uploading…');
  const fd = new FormData();
  fd.append('brief', files[0]);
  try {
    const r = await fetch('/upload/brief', { method: 'POST', body: fd });
    const data = await r.json();
    if (data.status === 'ok') {
      showStatus('brief-drop', `Uploaded: ${data.filename} ✓`, true);
      _briefReady = true;
      _updateRunButtons();
    } else {
      showStatus('brief-drop', `Upload error: ${JSON.stringify(data)}`);
    }
  } catch (e) {
    showStatus('brief-drop', `Upload failed: ${e.message}`);
  }
}

async function uploadAssets(files) {
  if (!files || files.length === 0) {
    showStatus('asset-drop', 'No files selected — try the browse button.');
    return;
  }
  showStatus('asset-drop', `Uploading ${files.length} file(s)…`);
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  try {
    const r = await fetch('/upload/assets', { method: 'POST', body: fd });
    const data = await r.json();
    if (data.status === 'ok') {
      showStatus('asset-drop', `Uploaded ${data.count} file(s) ✓`, true);
      _assetsReady = true;
      _updateRunButtons();
    } else {
      showStatus('asset-drop', `Upload error: ${JSON.stringify(data)}`);
    }
  } catch (e) {
    showStatus('asset-drop', `Upload failed: ${e.message}`);
  }
}


function showStatus(dropId, msg, success) {
  const drop = document.getElementById(dropId);
  if (!drop) return;
  drop.innerHTML = `<p style="color:var(--ok)">${msg}</p>`;
  if (success) {
    const card = drop.closest('.card');
    if (card) card.classList.add('done');
  }
}

// ── SSE progress ─────────────────────────────────────────────────────────────

const _LOG_MAX_LINES = 500; // keep only the last N lines so the DOM never grows unbounded

function startProgress(run_id) {
  const section = document.getElementById('progress-section');
  const log = document.getElementById('progress-log');
  const status = document.getElementById('run-status');
  const statusText = document.getElementById('run-status-text');
  const spinner = document.getElementById('run-spinner');

  if (section) { section.hidden = false; section.classList.add('done'); }
  if (log) log.innerHTML = '';
  if (status) status.classList.add('visible');
  if (spinner) spinner.classList.remove('done');
  if (statusText) statusText.textContent = 'Starting…';

  // Buffer incoming lines and flush on rAF to avoid freezing on bursts of output
  let _pending = [];
  let _rafId = null;
  let _lastStatus = '';

  function _flush() {
    _rafId = null;
    if (!_pending.length) return;
    const fragment = document.createDocumentFragment();
    for (const line of _pending) {
      const p = document.createElement('p');
      p.textContent = line;
      fragment.appendChild(p);
    }
    _pending = [];
    log.appendChild(fragment);
    // Trim to max lines
    while (log.childElementCount > _LOG_MAX_LINES) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
    if (_lastStatus && statusText) statusText.textContent = _lastStatus;
  }

  const src = new EventSource(`/run/${run_id}/stream`);
  src.onmessage = e => {
    if (e.data === '__done__') {
      src.close();
      _pending.push('── Done ──');
      _flush();
      if (statusText) statusText.textContent = 'Complete';
      if (spinner) spinner.classList.add('done');
      setTimeout(() => { if (status) status.classList.remove('visible'); }, 3000);
      return;
    }
    _pending.push(e.data);
    if (e.data.trim()) _lastStatus = e.data.trim();
    if (!_rafId) _rafId = requestAnimationFrame(_flush);
  };
  src.onerror = () => {
    src.close();
    if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
    if (statusText) statusText.textContent = 'Connection lost — check the log above.';
    if (spinner) spinner.classList.add('done');
  };
}

// ── Run-ready state (updated dynamically after uploads) ──────────────────────

let _briefReady = false;
let _assetsReady = false;
let _locationReady = false;
let _nameReady = false;

function _updateRunButtons() {
  const ready = _briefReady && _assetsReady;
  ['preview-btn', 'batch-btn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !ready;
  });
  const note = document.querySelector('.run-note');
  if (note && ready) note.textContent = 'Parses brief, generates backgrounds, and renders every variant across all enabled sizes.';

  const allReady = _briefReady && _assetsReady && _locationReady && _nameReady;
  const runCard = document.querySelector('#progress-section')?.previousElementSibling;
  // find the Run section card by its step badge text
  const runSection = Array.from(document.querySelectorAll('.card')).find(
    c => c.querySelector('.step')?.textContent.trim() === '6'
  );
  if (runSection) {
    if (allReady) runSection.classList.add('done');
    else runSection.classList.remove('done');
  }
}

// ── Button wiring ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupDrop('brief-drop', 'brief-file', uploadBrief);
  setupDrop('asset-drop', 'asset-file', uploadAssets);

  // ── Simple POST buttons ──────────────────────────────────────────────────────
  const btn = (id, endpoint) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('click', async () => {
      el.disabled = true;
      const r = await fetch(endpoint, { method: 'POST' });
      const { run_id } = await r.json();
      startProgress(run_id);
      el.disabled = false;
    });
  };

  btn('batch-btn',       '/run/batch');
  btn('rerender-btn',    '/run/rerender');

  // (reset button wired below, outside DOMContentLoaded)

  // ── Preview run (needs asset_id from dropdown) ───────────────────────────────
  const previewBtn = document.getElementById('preview-btn');
  if (previewBtn) {
    previewBtn.addEventListener('click', async () => {
      previewBtn.disabled = true;
      const sel = document.getElementById('preview-asset-select');
      const assetId = sel ? sel.value : null;
      const r = await fetch('/run/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_id: assetId }),
      });
      const { run_id } = await r.json();
      startProgress(run_id);
      previewBtn.disabled = false;
    });
  }

  // ── Browse folder button ─────────────────────────────────────────────────────
  const browseBtn = document.getElementById('browse-btn');
  if (browseBtn) {
    browseBtn.addEventListener('click', async () => {
      const res = await fetch('/pick-folder');
      const { path } = await res.json();
      if (path) {
        document.getElementById('local-path').value = path;
        const display = document.getElementById('dest-path-display');
        if (display) { display.textContent = path; display.title = path; }
        await _saveDest();
        const card = browseBtn.closest('.card');
        if (card) card.classList.add('done');
        _locationReady = true;
        _updateRunButtons();
      }
    });
  }

  // ── Auto-save helpers ────────────────────────────────────────────────────────
  async function _saveDest() {
    const type = document.querySelector('input[name="dest-type"]:checked')?.value || 'local';
    const localPath = document.getElementById('local-path')?.value || './output';
    await fetch('/config/destination', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, local_path: localPath }),
    });
  }

  // Auto-save project name on change (debounced)
  const projectNameInput = document.getElementById('project-name');
  if (projectNameInput) {
    let _nameTimer = null;
    projectNameInput.addEventListener('input', () => {
      clearTimeout(_nameTimer);
      _nameTimer = setTimeout(async () => {
        await fetch('/config/project', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_name: projectNameInput.value }),
        });
      }, 600);
    });
  }

  // Auto-save destination on radio change
  document.querySelectorAll('input[name="dest-type"]').forEach(radio => {
    radio.addEventListener('change', async () => {
      document.getElementById('dest-local').style.display = radio.value === 'local' ? '' : 'none';
      document.getElementById('dest-drive').style.display = radio.value === 'drive' ? '' : 'none';
      await _saveDest();
      if (radio.value === 'drive') refreshDriveStatus();
    });
  });

  // ── Google Drive status ──────────────────────────────────────────────────────
  const _drivePanel = document.getElementById('dest-drive');
  if (_drivePanel && !_drivePanel.hidden) refreshDriveStatus();

  // Mark Output Location card done on load if a local path is already configured
  const _existingPath = document.getElementById('local-path')?.value;
  if (_existingPath && _existingPath !== './output') {
    const _destCard = document.getElementById('dest-local')?.closest('.card');
    if (_destCard) _destCard.classList.add('done');
    _locationReady = true;
  }

  // Project name — track readiness
  const _nameInput = document.getElementById('project-name');
  if (_nameInput) {
    _nameReady = _nameInput.value.trim().length > 0;
    _nameInput.addEventListener('input', () => {
      _nameReady = _nameInput.value.trim().length > 0;
      _updateRunButtons();
    });
  }

  // Brief/assets may already be ready from server-side state
  if (document.querySelector('.card.done #brief-drop')) _briefReady = true;
  if (document.querySelector('.card.done #asset-drop')) _assetsReady = true;
  _updateRunButtons();

  // ── Model toggles (advanced mode) ───────────────────────────────────────────
  const saveModels = document.getElementById('save-models-btn');
  if (saveModels) {
    saveModels.addEventListener('click', async () => {
      const stage1 = [...document.querySelectorAll('input[name="stage1"]:checked')].map(el => el.value);
      const stage2 = [...document.querySelectorAll('input[name="stage2"]:checked')].map(el => el.value);
      await fetch('/config/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage1_enabled: stage1, stage2_enabled: stage2 }),
      });
      saveModels.textContent = 'Saved ✓';
      setTimeout(() => { saveModels.textContent = 'Save Model Selection'; }, 2000);
    });
  }

  // ── Sizes: toggle enable/disable ─────────────────────────────────────────────
  document.querySelectorAll('.size-toggle-cb').forEach(cb => {
    cb.addEventListener('change', async () => {
      await fetch('/config/sizes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'toggle', id: cb.dataset.id, enabled: cb.checked }),
      });
      cb.closest('.model-toggle').classList.toggle('size-on', cb.checked);
    });
  });

  // ── Sizes: remove ────────────────────────────────────────────────────────────
  document.querySelectorAll('.remove-size-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(`Remove size ${btn.dataset.id}?`)) return;
      const r = await fetch('/config/sizes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'remove', id: btn.dataset.id }),
      });
      if ((await r.json()).status === 'ok') btn.closest('.size-row').remove();
    });
  });

  // ── Sizes: add new ───────────────────────────────────────────────────────────
  const addSizeBtn = document.getElementById('add-size-btn');
  if (addSizeBtn) {
    addSizeBtn.addEventListener('click', async () => {
      const w = document.getElementById('new-size-w')?.value;
      const h = document.getElementById('new-size-h')?.value;
      const label = document.getElementById('new-size-label')?.value || `${w}×${h}`;
      if (!w || !h) { alert('Enter width and height.'); return; }
      const r = await fetch('/config/sizes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'add', width: w, height: h, label }),
      });
      const data = await r.json();
      if (data.status === 'ok') window.location.reload();
    });
  }
});

// ── Google Drive status ───────────────────────────────────────────────────────

function connectDrivePopup() {
  const w = 520, h = 640;
  const left = Math.round((screen.width - w) / 2);
  const top  = Math.round((screen.height - h) / 2);
  window.open('/drive/connect', 'drive_auth',
    `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no,location=no`);
}

window.addEventListener('message', e => {
  if (e.data === 'drive_connected') refreshDriveStatus();
  else if (e.data && e.data.drive_error) alert('Drive error: ' + e.data.drive_error);
});

async function refreshDriveStatus() {
  try {
    const r = await fetch('/drive/status');
    const { connected, folder_url } = await r.json();
    const badge       = document.getElementById('drive-badge');
    const connectBtn  = document.getElementById('drive-connect-btn');
    const disconnectBtn = document.getElementById('drive-disconnect-btn');
    const folderLink  = document.getElementById('drive-folder-link');
    if (!badge) return;
    if (connected) {
      badge.className = 'drive-badge connected';
      badge.textContent = 'Connected';
      if (connectBtn)     connectBtn.style.display  = 'none';
      if (disconnectBtn)  disconnectBtn.style.display = '';
      if (folderLink) {
        folderLink.href = folder_url || '#';
        folderLink.style.display = folder_url ? '' : 'none';
      }
      const card = badge.closest('.card');
      if (card) card.classList.add('done');
      _locationReady = true;
      _updateRunButtons();
    } else {
      badge.className = 'drive-badge disconnected';
      badge.textContent = 'Not connected';
      if (connectBtn)     connectBtn.style.display  = '';
      if (disconnectBtn)  disconnectBtn.style.display = 'none';
      if (folderLink)     folderLink.style.display   = 'none';
      const card = badge.closest('.card');
      if (card) card.classList.remove('done');
      _locationReady = false;
      _updateRunButtons();
    }
  } catch (_) { /* non-fatal — server may be starting */ }
}

async function disconnectDrive() {
  if (!confirm('Remove Google Drive credentials? You will need to reconnect before uploading.')) return;
  await fetch('/drive/token', { method: 'DELETE' });
  refreshDriveStatus();
}

// ── Reset button — wired outside DOMContentLoaded so it always runs ──────────
// (script tag is at bottom of <body>, so DOM is already fully parsed here)
(function () {
  var resetBtn = document.getElementById('reset-btn');
  if (!resetBtn) return;

  var armed = false;
  var armTimer = null;

  resetBtn.onclick = function () {
    if (!armed) {
      armed = true;
      resetBtn.textContent = 'Sure? Click again';
      resetBtn.style.opacity = '1';
      resetBtn.style.color = '#e05252';
      armTimer = setTimeout(function () {
        armed = false;
        resetBtn.textContent = 'Reset';
        resetBtn.style.opacity = '.6';
        resetBtn.style.color = '';
      }, 3000);
      return;
    }

    clearTimeout(armTimer);
    resetBtn.disabled = true;
    resetBtn.textContent = 'Resetting…';

    fetch('/reset', { method: 'POST' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        window.location.href = '/';
      })
      .catch(function (err) {
        console.error('Reset failed:', err);
        resetBtn.textContent = 'Error — see console';
        setTimeout(function () {
          resetBtn.disabled = false;
          resetBtn.textContent = 'Reset';
          resetBtn.style.opacity = '.6';
          resetBtn.style.color = '';
          armed = false;
        }, 3000);
      });
  };
}());

// ── Display title: scale to fill full viewport width ──────────────────────
(function () {
  var title = document.querySelector('.display-title');
  if (!title) return;

  function fitTitle() {
    title.style.fontSize = '100px';
    var containerW = document.documentElement.clientWidth;
    var textW = title.scrollWidth;
    if (textW > 0 && containerW > 0) {
      title.style.fontSize = Math.floor(100 * containerW / textW) + 'px';
    }
  }

  fitTitle();
  window.addEventListener('resize', fitTitle);
}());
