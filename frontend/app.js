// Controlador Frontend de ApexRIP Studio Pro (Desktop & Web Workstation)

const APP_STATE = {
  activeQueueId: 'queue_a',
  activeChannel: 'composite',
  uploadedImageDataUrl: null,
  lastRipResponse: null,
  queues: [],
  masterQueue: [],
  printers: [],
  profiles: [],
  spotColors: [],
  devices: [],
};

document.addEventListener('DOMContentLoaded', async () => {
  bindNavigationTabs();
  bindControls();
  await loadInitialConfig();
  await runRipPipeline();
  await runColorAtlas();
  await runNestingCalc();
  await runTilingCalc();
  await runVdpGenerator();
});

function bindNavigationTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabs.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const targetId = btn.getAttribute('data-tab');
      document.querySelectorAll('.tab-view').forEach((view) => {
        view.classList.toggle('active', view.id === targetId);
      });
    });
  });

  // Botones de selección de canal (Compuesto, C, M, Y, K)
  document.querySelectorAll('.ch-btn').forEach((chBtn) => {
    chBtn.addEventListener('click', () => {
      document.querySelectorAll('.ch-btn').forEach((b) => b.classList.remove('active'));
      chBtn.classList.add('active');
      APP_STATE.activeChannel = chBtn.getAttribute('data-ch');
      updateDisplayedChannelImage();
    });
  });
}

function bindControls() {
  // Sliders de calibración por canal y TIL
  const tilInput = document.getElementById('til-input');
  tilInput.addEventListener('input', () => {
    document.getElementById('til-val-lbl').textContent = `${tilInput.value}%`;
  });
  tilInput.addEventListener('change', runRipPipeline);

  ['c', 'm', 'y', 'k'].forEach((ch) => {
    const el = document.getElementById(`gain-${ch}-input`);
    const lbl = document.getElementById(`gain-${ch}-lbl`);
    el.addEventListener('input', () => {
      lbl.textContent = `${Math.round(parseFloat(el.value) * 100)}%`;
    });
    el.addEventListener('change', runRipPipeline);
  });

  // Botones de acción de Ripeo
  document.getElementById('btn-run-rip-left').addEventListener('click', runRipPipeline);
  document.getElementById('btn-rip-main').addEventListener('click', runRipPipeline);
  document.getElementById('preset-artwork-select').addEventListener('change', () => {
    APP_STATE.uploadedImageDataUrl = null;
    runRipPipeline();
  });

  [
    'printer-select',
    'profile-select',
    'resolution-select',
    'passes-select',
    'head-dir-select',
    'halftone-select',
    'chk-autocut',
    'chk-printline',
    'chk-cropmarks',
    'chk-colorbar',
    'chk-mirror',
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', runRipPipeline);
  });

  // Subida de archivo de usuario
  const fileInput = document.getElementById('file-upload-input');
  fileInput.addEventListener('change', (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      APP_STATE.uploadedImageDataUrl = e.target.result;
      runRipPipeline();
    };
    reader.readAsDataURL(file);
  });

  // Atlas de Color e Importador CIE Lab / PANTONE
  document.getElementById('btn-generate-atlas').addEventListener('click', runColorAtlas);
  document.getElementById('btn-import-spot').addEventListener('click', importSpotColor);

  // Composición (Nesting) y Panelación (Tiling)
  document.getElementById('btn-calc-nesting').addEventListener('click', runNestingCalc);
  document.getElementById('btn-calc-tiling').addEventListener('click', runTilingCalc);

  // Datos Variables (VDP)
  document.getElementById('btn-generate-vdp').addEventListener('click', runVdpGenerator);

  // Spooler e Impresión Directa
  document.getElementById('btn-send-printer-top').addEventListener('click', async () => {
    document.getElementById('tab-btn-queues').click();
    await executeSpoolSend();
  });
  document.getElementById('btn-execute-spool').addEventListener('click', executeSpoolSend);
}

async function loadInitialConfig() {
  const res = await fetch('/api/config');
  const data = await res.json();
  APP_STATE.printers = data.printers || [];
  APP_STATE.profiles = data.profiles || [];
  APP_STATE.spotColors = data.spot_colors || [];
  APP_STATE.queues = data.queues || [];
  APP_STATE.masterQueue = data.master_queue || [];
  APP_STATE.devices = data.devices || [];

  // Poblar selector de impresoras
  const pSelect = document.getElementById('printer-select');
  pSelect.innerHTML = APP_STATE.printers
    .map((p) => `<option value="${p.id}">${p.brand} — ${p.model}</option>`)
    .join('');

  // Poblar selector de perfiles ICC
  const profSelect = document.getElementById('profile-select');
  profSelect.innerHTML = APP_STATE.profiles
    .map((pr) => `<option value="${pr.id}">${pr.name} (TIL ${pr.total_ink_limit}%)</option>`)
    .join('');

  renderQueuesSidebar();
  renderSpotColorsTable();
  renderDevicesTable();
  renderMasterQueueTable();
}

function renderQueuesSidebar() {
  const qContainer = document.getElementById('queues-container');
  qContainer.innerHTML = APP_STATE.queues
    .map((q) => {
      const isAct = q.id === APP_STATE.activeQueueId ? 'active' : '';
      return `
        <div class="queue-card ${isAct}" data-qid="${q.id}">
          <div class="queue-card-top">
            <span class="queue-badge">${q.code}</span>
            <span class="queue-status">● ${q.status}</span>
          </div>
          <div class="queue-name">${q.name}</div>
          <div class="queue-meta">Rollo: ${q.roll_width_mm} mm • ${q.jobs.length} trabajo(s)</div>
        </div>
      `;
    })
    .join('');

  qContainer.querySelectorAll('.queue-card').forEach((card) => {
    card.addEventListener('click', () => {
      APP_STATE.activeQueueId = card.getAttribute('data-qid');
      const activeQ = APP_STATE.queues.find((x) => x.id === APP_STATE.activeQueueId);
      if (activeQ) {
        document.getElementById('printer-select').value = activeQ.printer_id;
        document.getElementById('profile-select').value = activeQ.profile_id;
        document.getElementById('chk-mirror').checked = activeQ.id === 'queue_b';
      }
      renderQueuesSidebar();
      runRipPipeline();
      runNestingCalc();
    });
  });

  const activeQueue = APP_STATE.queues.find((x) => x.id === APP_STATE.activeQueueId) || APP_STATE.queues[0];
  const jobsContainer = document.getElementById('queue-jobs-container');
  if (activeQueue && activeQueue.jobs) {
    jobsContainer.innerHTML = activeQueue.jobs
      .map(
        (j) => `
        <div class="job-item">
          <div class="job-item-title">${j.title}</div>
          <div class="job-item-meta">
            <span>${j.width_mm}x${j.height_mm} mm (${j.copies}x)</span>
            <span style="color:var(--accent-hover);">${j.ink_ml} mL</span>
          </div>
        </div>
      `
      )
      .join('');
  }
}

async function runRipPipeline() {
  const payload = {
    preset_artwork: document.getElementById('preset-artwork-select').value,
    image_data_url: APP_STATE.uploadedImageDataUrl,
    job_title: APP_STATE.uploadedImageDataUrl ? 'Arte_Usuario_Personalizado.tif' : 'Grafica_Gran_Formato_Test.tif',
    queue_id: APP_STATE.activeQueueId,
    printer_id: document.getElementById('printer-select').value,
    profile_id: document.getElementById('profile-select').value,
    halftone_mode: document.getElementById('halftone-select').value,
    channel_gains: {
      C: parseFloat(document.getElementById('gain-c-input').value),
      M: parseFloat(document.getElementById('gain-m-input').value),
      Y: parseFloat(document.getElementById('gain-y-input').value),
      K: parseFloat(document.getElementById('gain-k-input').value),
    },
    total_ink_limit: parseFloat(document.getElementById('til-input').value),
    mirror_horizontal: document.getElementById('chk-mirror').checked,
    width_mm: parseFloat(document.getElementById('job-w-input').value) || 1200,
    height_mm: parseFloat(document.getElementById('job-h-input').value) || 840,
    resolution_dpi: parseInt(document.getElementById('resolution-select').value, 10),
    passes: parseInt(document.getElementById('passes-select').value, 10),
    head_direction: document.getElementById('head-dir-select').value,
    auto_cut: document.getElementById('chk-autocut').checked,
    add_crop_marks: document.getElementById('chk-cropmarks').checked,
    add_printline: document.getElementById('chk-printline').checked,
    add_colorbar: document.getElementById('chk-colorbar').checked,
  };

  const res = await fetch('/api/rip/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  APP_STATE.lastRipResponse = data;

  updateDisplayedChannelImage();

  // Actualizar métricas inferiores y barras CMYK
  const m = data.metrics;
  document.getElementById('metric-area').textContent = `${m.area_m2} m²`;
  document.getElementById('metric-ink-total').textContent = `${m.ink_ml.total} mL`;
  document.getElementById('metric-peak-til').textContent = `${m.coverage_pct.peak_til}%`;
  document.getElementById('metric-head-mode').textContent = `${m.passes} Pasadas ${
    m.head_direction === 'unidirectional' ? 'Unidir' : 'Bidir'
  }`;
  document.getElementById('metric-rip-ms').textContent = `${m.processing_ms} ms`;

  ['C', 'M', 'Y', 'K'].forEach((ch) => {
    const key = ch.toLowerCase();
    const pct = Math.min(100, m.coverage_pct[ch] || 0);
    document.getElementById(`bar-${key}`).style.width = `${pct}%`;
    document.getElementById(`txt-${key}`).textContent = `${m.ink_ml[ch]} mL`;
  });
}

function updateDisplayedChannelImage() {
  if (!APP_STATE.lastRipResponse) return;
  const previews = APP_STATE.lastRipResponse.previews;
  const imgEl = document.getElementById('rip-preview-img');
  imgEl.src = previews[APP_STATE.activeChannel] || previews.composite;
}

async function runColorAtlas() {
  const gridVal = parseInt(document.getElementById('atlas-grid-size').value, 10) || 5;
  const payload = {
    base_hex: document.getElementById('atlas-base-hex').value,
    rows: gridVal,
    cols: gridVal,
    step_pct: parseFloat(document.getElementById('atlas-step-pct').value) || 4.0,
    variation_mode: document.getElementById('atlas-variation-mode').value,
    profile_id: document.getElementById('profile-select').value || 'ecosol_vinyl_gloss',
    include_crop_marks: true,
  };

  const res = await fetch('/api/color/atlas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  document.getElementById('atlas-preview-img').src = data.atlas_image_url;
}

async function importSpotColor() {
  const payload = {
    code: document.getElementById('spot-code-input').value,
    name: document.getElementById('spot-name-input').value,
    L: parseFloat(document.getElementById('spot-l-input').value) || 50.0,
    a: parseFloat(document.getElementById('spot-a-input').value) || 0.0,
    b: parseFloat(document.getElementById('spot-b-input').value) || 0.0,
    profile_id: document.getElementById('profile-select').value || 'ecosol_vinyl_gloss',
  };
  const res = await fetch('/api/color/import-spot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  APP_STATE.spotColors = data.spot_colors || [];
  renderSpotColorsTable();
  if (data.added && data.added.hex) {
    document.getElementById('atlas-base-hex').value = data.added.hex;
    await runColorAtlas();
  }
}

function renderSpotColorsTable() {
  const tbody = document.getElementById('spot-table-body');
  tbody.innerHTML = APP_STATE.spotColors
    .map(
      (sp) => `
      <tr style="cursor:pointer;" data-hex="${sp.hex}">
        <td>
          <span class="swatch-chip" style="background:${sp.hex};"></span>
          <strong>${sp.code}</strong><br/>
          <span style="color:var(--text-muted); font-size:11px;">${sp.name}</span>
        </td>
        <td style="font-family:var(--font-mono); font-size:11px;">
          L:${sp.L} a:${sp.a} b:${sp.b}
        </td>
        <td style="font-family:var(--font-mono); font-size:11px;">
          C:${sp.cmyk.C}% M:${sp.cmyk.M}% Y:${sp.cmyk.Y}% K:${sp.cmyk.K}%
        </td>
        <td style="font-family:var(--font-mono); color:${sp.delta_e < 2.0 ? '#34d399' : '#f59e0b'};">
          ${sp.delta_e}
        </td>
      </tr>
    `
    )
    .join('');

  tbody.querySelectorAll('tr').forEach((row) => {
    row.addEventListener('click', () => {
      const hx = row.getAttribute('data-hex');
      document.getElementById('atlas-base-hex').value = hx;
      runColorAtlas();
    });
  });
}

async function runNestingCalc() {
  const payload = {
    queue_id: APP_STATE.activeQueueId,
    roll_width_mm: parseFloat(document.getElementById('nest-roll-w').value) || 1600,
    margin_mm: 15,
    gap_mm: parseFloat(document.getElementById('nest-gap').value) || 12,
    allow_rotation: true,
  };
  const res = await fetch('/api/workflow/nesting', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  document.getElementById('nesting-summary').textContent =
    `Piezas impuestas: ${data.total_pieces} | Largo requerido: ${data.total_length_m} m | Aprovechamiento de rollo: ${data.efficiency_pct}%`;

  const canvas = document.getElementById('nesting-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const scaleX = (canvas.width - 40) / data.roll_width_mm;
  const maxLen = Math.max(data.total_length_mm, 800);
  const scaleY = (canvas.height - 40) / maxLen;
  const scale = Math.min(scaleX, scaleY);

  const ox = 20;
  const oy = 20;
  const rw = data.roll_width_mm * scale;
  const rh = data.total_length_mm * scale;

  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(ox, oy, rw, rh);

  data.placed_items.forEach((it) => {
    const x = ox + it.x_mm * scale;
    const y = oy + it.y_mm * scale;
    const w = it.width_mm * scale;
    const h = it.height_mm * scale;
    ctx.fillStyle = it.color || '#0ea5e9';
    ctx.globalAlpha = 0.35;
    ctx.fillRect(x, y, w, h);
    ctx.globalAlpha = 1.0;
    ctx.strokeStyle = it.color || '#0ea5e9';
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = '#f8fafc';
    ctx.font = '10px monospace';
    ctx.fillText(`${it.job_id} (#${it.copy_index})`, x + 5, y + 14);
  });
}

async function runTilingCalc() {
  const payload = {
    job_width_mm: parseFloat(document.getElementById('tile-job-w').value) || 4200,
    job_height_mm: parseFloat(document.getElementById('tile-job-h').value) || 2400,
    roll_width_mm: parseFloat(document.getElementById('tile-roll-w').value) || 1600,
    overlap_mm: parseFloat(document.getElementById('tile-overlap').value) || 18,
    alternate_flip: true,
  };
  const res = await fetch('/api/workflow/tiling', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  document.getElementById('tiling-summary').textContent =
    `Total Paneles: ${data.total_tiles} (${data.cols} col x ${data.rows} filas) | Solapamiento: ${data.overlap_mm} mm | Consumo Lineal: ${data.estimated_roll_length_m} m`;

  const canvas = document.getElementById('tiling-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const scale = Math.min((canvas.width - 40) / data.job_width_mm, (canvas.height - 40) / data.job_height_mm);
  const ox = 20;
  const oy = 20;

  data.tiles.forEach((t) => {
    const x = ox + t.x_mm * scale;
    const y = oy + t.y_mm * scale;
    const w = t.width_mm * scale;
    const h = t.height_mm * scale;

    ctx.fillStyle = t.flipped_180 ? 'rgba(236, 0, 140, 0.22)' : 'rgba(14, 165, 233, 0.22)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(x, y, w, h);

    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 11px monospace';
    ctx.fillText(`${t.tile_id} (${t.width_mm}x${t.height_mm}mm)`, x + 6, y + 18);
    ctx.font = '10px monospace';
    ctx.fillStyle = t.flipped_180 ? '#f472b6' : '#38bdf8';
    ctx.fillText(t.flipped_180 ? '↺ GIRO 180° (PAR)' : '↑ NORMAL (IMPAR)', x + 6, y + 34);
  });
}

async function runVdpGenerator() {
  const rawLines = document.getElementById('vdp-textarea').value.trim().split('\n');
  const records = rawLines
    .filter((l) => l.trim().length > 0)
    .map((line, i) => {
      const parts = line.split('|').map((s) => s.trim());
      return {
        id: parts[0] || `SER-${i + 1}`,
        label: parts[1] || `ETIQUETA ${i + 1}`,
        sub: parts[2] || 'LOTE GENERAL',
      };
    });

  const res = await fetch('/api/workflow/vdp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records, queue_id: APP_STATE.activeQueueId }),
  });
  const data = await res.json();
  document.getElementById('vdp-preview-img').src = data.sheet_image_url;
  if (data.queues) {
    APP_STATE.queues = data.queues;
    renderQueuesSidebar();
  }
}

async function executeSpoolSend() {
  const hostPort = document.getElementById('spool-host-input').value.split(':');
  const host = hostPort[0] || '192.168.1.200';
  const port = parseInt(hostPort[1] || '9100', 10);

  const payload = {
    job_title: APP_STATE.uploadedImageDataUrl ? 'Trabajo_Personalizado' : 'Grafica_Gran_Formato',
    printer_id: document.getElementById('printer-select').value,
    profile_id: document.getElementById('profile-select').value,
    connection_mode: document.getElementById('spool-mode-select').value,
    host,
    port,
    resolution_dpi: parseInt(document.getElementById('resolution-select').value, 10),
    passes: parseInt(document.getElementById('passes-select').value, 10),
    head_direction: document.getElementById('head-dir-select').value,
    auto_cut: document.getElementById('chk-autocut').checked,
    roll_width_mm: 1600.0,
  };

  const res = await fetch('/api/spool/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();

  const box = document.getElementById('spool-result-box');
  box.innerHTML = `
    <div>✓ <strong>${data.spool.message}</strong></div>
    <div style="margin-top:6px;">
      <a href="${data.download_url}" download="${data.filename}" class="btn btn-primary" style="text-decoration:none; display:inline-block;">
        Descargar Archivo Binario .PRN (${data.filename})
      </a>
    </div>
  `;

  if (data.master_queue) {
    APP_STATE.masterQueue = data.master_queue;
    renderMasterQueueTable();
  }
}

function renderDevicesTable() {
  const tbody = document.getElementById('devices-table-body');
  tbody.innerHTML = APP_STATE.devices
    .map(
      (d) => `
      <tr>
        <td><strong>${d.type}</strong></td>
        <td style="font-family:var(--font-mono); font-size:11px;">${d.uri}</td>
        <td style="color:#34d399;">${d.status}</td>
      </tr>
    `
    )
    .join('');
}

function renderMasterQueueTable() {
  const tbody = document.getElementById('master-queue-body');
  tbody.innerHTML = APP_STATE.masterQueue
    .map(
      (m) => `
      <tr>
        <td style="font-family:var(--font-mono); color:var(--accent-hover);">${m.id}</td>
        <td><strong>${m.title}</strong></td>
        <td>${m.printer_model}</td>
        <td>${m.profile_name}</td>
        <td style="font-family:var(--font-mono); font-size:11px;">${m.resolution}</td>
        <td style="font-family:var(--font-mono);">${m.ink_ml} mL</td>
        <td>
          ${
            m.prn_file
              ? `<a href="/api/spool/download/${m.prn_file}" download="${m.prn_file}" class="btn" style="text-decoration:none; padding:4px 8px; font-size:11px;">Descargar .PRN</a>`
              : `<button class="btn" style="padding:4px 8px; font-size:11px;" onclick="executeSpoolSend()">Reimprimir Ahora</button>`
          }
        </td>
      </tr>
    `
    )
    .join('');
}
