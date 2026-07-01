const metricFormats = {
  co2: (value) => value == null ? '--' : `${Math.round(value)} ppm`,
  temp: (value) => value == null ? '--' : `${value.toFixed(1)} C`,
  humid: (value) => value == null ? '--' : `${value.toFixed(1)} %`,
  pm25: (value) => value == null ? '--' : `${value.toFixed(2)} ug/m3`,
  pm10: (value) => value == null ? '--' : `${value.toFixed(2)} ug/m3`,
  tps: (value) => value == null ? '--' : `${value.toFixed(2)} um`,
};

let selectedHours = 24;

function formatTimestamp(value) {
  if (!value) {
    return '--';
  }
  const date = new Date(value);
  return date.toLocaleString();
}

function renderSummary(summary) {
  const latest = summary.latest_measurement || {};
  document.getElementById('metric-co2').textContent = metricFormats.co2(latest.co2);
  document.getElementById('metric-temp').textContent = metricFormats.temp(latest.temp);
  document.getElementById('metric-humid').textContent = metricFormats.humid(latest.humid);
  document.getElementById('metric-pm25').textContent = metricFormats.pm25(latest.pm25);
  document.getElementById('metric-pm10').textContent = metricFormats.pm10(latest.pm10);
  document.getElementById('metric-tps').textContent = metricFormats.tps(latest.tps);
  document.getElementById('latest-sample-time').textContent = `Sample: ${formatTimestamp(latest.timestamp)}`;

  const collector = summary.collector_status?.value || {};
  document.getElementById('collector-running').textContent = `Collector: ${collector.running ? 'running' : 'stopped'}`;
  document.getElementById('collector-asc').textContent = `ASC: ${collector.scd41_asc_enabled ? 'enabled' : 'disabled'}`;
  document.getElementById('scd41-asc-enabled').checked = !!collector.scd41_asc_enabled;

  const weather = summary.latest_weather?.value || {};
  document.getElementById('weather-updated').textContent = `Updated: ${summary.latest_weather?.updated_at || '--'}`;
  renderWeather(weather);
  renderCommands(summary.recent_commands || []);
}

function renderWeather(weather) {
  const grid = document.getElementById('forecast-grid');
  grid.innerHTML = '';
  const entries = [weather[1], weather[2], weather[3]].filter(Boolean);
  if (!entries.length) {
    grid.innerHTML = '<div class="empty-state">No forecast data yet.</div>';
    return;
  }
  for (const block of entries) {
    const card = document.createElement('article');
    card.className = 'forecast-card';
    const [windowLabel, maxTemp, minTemp, precip, code] = block;
    card.innerHTML = `
      <h3>${windowLabel}</h3>
      <p>Max/Min: ${maxTemp ?? '--'} / ${minTemp ?? '--'}</p>
      <p>Rain: ${precip ?? '--'}%</p>
      <p>WMO: ${code ?? '--'}</p>
    `;
    grid.appendChild(card);
  }
}

function renderCommands(commands) {
  const list = document.getElementById('command-list');
  list.innerHTML = '';
  if (!commands.length) {
    list.innerHTML = '<div class="empty-state">No commands recorded yet.</div>';
    return;
  }
  for (const command of commands) {
    const item = document.createElement('article');
    item.className = 'command-item';
    item.innerHTML = `
      <header>
        <span>${command.command}</span>
        <span class="command-status-${command.status}">${command.status}</span>
      </header>
      <p>Created: ${formatTimestamp(command.created_at)}</p>
      <p>Payload: ${JSON.stringify(command.payload || {})}</p>
      <p>Result: ${JSON.stringify(command.result || {})}</p>
    `;
    list.appendChild(item);
  }
}

function renderLineChart(svgId, rows, key, color) {
  const svg = document.getElementById(svgId);
  if (!rows.length || rows.every((row) => row[key] == null)) {
    svg.innerHTML = '<text x="24" y="40" fill="#59636e" font-size="16">No data yet</text>';
    return;
  }

  const width = 640;
  const height = 220;
  const padding = { top: 18, right: 18, bottom: 28, left: 44 };
  const points = rows.filter((row) => row[key] != null);
  const values = points.map((row) => row[key]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xStep = points.length > 1 ? (width - padding.left - padding.right) / (points.length - 1) : 0;

  const coordinates = points.map((row, index) => {
    const x = padding.left + index * xStep;
    const y = padding.top + (height - padding.top - padding.bottom) * (1 - ((row[key] - min) / range));
    return { x, y, row };
  });

  const polyline = coordinates.map((point) => `${point.x},${point.y}`).join(' ');
  const grid = [];
  for (let i = 0; i < 4; i += 1) {
    const y = padding.top + ((height - padding.top - padding.bottom) / 3) * i;
    grid.push(`<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#d7d1c3" stroke-dasharray="4 4" />`);
  }

  const labels = [
    `<text x="${padding.left}" y="${height - 8}" fill="#59636e" font-size="12">${new Date(points[0].timestamp).toLocaleTimeString()}</text>`,
    `<text x="${width - padding.right - 88}" y="${height - 8}" fill="#59636e" font-size="12">${new Date(points[points.length - 1].timestamp).toLocaleTimeString()}</text>`,
    `<text x="6" y="${padding.top + 6}" fill="#59636e" font-size="12">${max.toFixed(1)}</text>`,
    `<text x="6" y="${height - padding.bottom + 6}" fill="#59636e" font-size="12">${min.toFixed(1)}</text>`,
  ];

  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
    ${grid.join('')}
    <polyline fill="none" stroke="${color}" stroke-width="3" points="${polyline}"></polyline>
    ${labels.join('')}
  `;
}

async function fetchSummary() {
  const response = await fetch('/api/summary');
  const data = await response.json();
  renderSummary(data);
}

async function fetchHistory() {
  const response = await fetch(`/api/history?hours=${selectedHours}`);
  const data = await response.json();
  const rows = data.rows || [];
  renderLineChart('chart-co2', rows, 'co2', '#1f5c4a');
  renderLineChart('chart-temp', rows, 'temp', '#b85c38');
  renderLineChart('chart-humid', rows, 'humid', '#2b6f9e');
  renderLineChart('chart-pm25', rows, 'pm25', '#5b4b8a');
}

async function submitCommand(command, payload = {}) {
  const response = await fetch('/api/commands', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, payload }),
  });
  const data = await response.json();
  const status = response.ok ? `Queued command #${data.id}` : (data.error || 'Command failed');
  document.getElementById('command-status').textContent = status;
  await fetchSummary();
}

function installActions() {
  document.querySelectorAll('[data-command]').forEach((button) => {
    button.addEventListener('click', async () => {
      await submitCommand(button.dataset.command);
    });
  });

  document.querySelectorAll('.range-switch button').forEach((button) => {
    button.addEventListener('click', async () => {
      selectedHours = Number(button.dataset.hours);
      document.querySelectorAll('.range-switch button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      await fetchHistory();
    });
  });

  document.getElementById('sps30-auto-clean-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const seconds = Number(document.getElementById('auto-clean-seconds').value);
    await submitCommand('sps30_set_auto_cleaning_interval', { seconds });
  });

  document.getElementById('scd41-calibration-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const target_co2 = Number(document.getElementById('target-co2').value);
    await submitCommand('scd41_force_calibration', { target_co2 });
  });

  document.getElementById('scd41-asc-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const enabled = document.getElementById('scd41-asc-enabled').checked;
    const persist = document.getElementById('scd41-asc-persist').checked;
    await submitCommand('scd41_set_asc', { enabled, persist });
  });

  document.getElementById('scd41-altitude-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const altitude = Number(document.getElementById('scd41-altitude').value);
    const persist = document.getElementById('scd41-altitude-persist').checked;
    await submitCommand('scd41_set_altitude', { altitude, persist });
  });
}

async function refreshAll() {
  await Promise.all([fetchSummary(), fetchHistory()]);
}

installActions();
refreshAll();
setInterval(fetchSummary, 15000);
