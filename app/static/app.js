// ── File upload handlers ──────────────────────────────────────────────────

function setupDrop(dropId, inputId, uploadFn) {
  const drop = document.getElementById(dropId);
  const input = document.getElementById(inputId);
  if (!drop || !input) return;

  drop.addEventListener('click', () => input.click());
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('drag-over');
    uploadFn(e.dataTransfer.files);
  });
  input.addEventListener('change', () => uploadFn(input.files));
}

async function uploadBrief(files) {
  const fd = new FormData();
  fd.append('brief', files[0]);
  const r = await fetch('/upload/brief', { method: 'POST', body: fd });
  const data = await r.json();
  if (data.status === 'ok') {
    showStatus('brief-drop', `Uploaded: ${data.filename}`);
    document.getElementById('parse-brief-btn').disabled = false;
  }
}

async function uploadAssets(files) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const r = await fetch('/upload/assets', { method: 'POST', body: fd });
  const data = await r.json();
  if (data.status === 'ok') {
    showStatus('asset-drop', `Uploaded ${data.count} files`);
  }
}

function showStatus(dropId, msg) {
  const drop = document.getElementById(dropId);
  if (!drop) return;
  drop.innerHTML = `<p style="color:var(--ok)">${msg}</p>`;
}

// ── SSE progress ─────────────────────────────────────────────────────────────

function startProgress(run_id) {
  const section = document.getElementById('progress-section');
  const log = document.getElementById('progress-log');
  if (section) section.hidden = false;
  if (log) log.innerHTML = '';

  const src = new EventSource(`/run/${run_id}/stream`);
  src.onmessage = e => {
    if (e.data === '__done__') {
      src.close();
      appendLog(log, '── Done ──');
      return;
    }
    appendLog(log, e.data);
  };
  src.onerror = () => src.close();
}

function appendLog(log, text) {
  if (!log) return;
  const p = document.createElement('p');
  p.textContent = text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}

// ── Button wiring ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupDrop('brief-drop', 'brief-file', uploadBrief);
  setupDrop('asset-drop', 'asset-file', uploadAssets);

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

  btn('parse-brief-btn', '/run/parse');
  btn('preview-btn',     '/run/preview');
  btn('batch-btn',       '/run/batch');
  btn('rerender-btn',    '/run/rerender');

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

  // ── Output destination panel toggle ─────────────────────────────────────────
  document.querySelectorAll('input[name="dest-type"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.querySelectorAll('.dest-panel').forEach(p => p.hidden = true);
      const panel = document.getElementById(`dest-${radio.value}`);
      if (panel) panel.hidden = false;
    });
  });

  // ── Save project settings ────────────────────────────────────────────────────
  const saveProject = document.getElementById('save-project-btn');
  if (saveProject) {
    saveProject.addEventListener('click', async () => {
      const destType = document.querySelector('input[name="dest-type"]:checked')?.value || 'local';
      const payload = {
        project_name: document.getElementById('project-name')?.value || '',
        output_destination: {
          type: destType,
          local_path: document.getElementById('local-path')?.value || './output',
          gcs_bucket: document.getElementById('gcs-bucket')?.value || '',
          gcs_prefix: document.getElementById('gcs-prefix')?.value || 'renders',
        },
      };
      const r = await fetch('/config/project', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if ((await r.json()).status === 'ok') {
        saveProject.textContent = 'Saved ✓';
        setTimeout(() => { saveProject.textContent = 'Save Project Settings'; }, 2000);
      }
    });
  }
});
