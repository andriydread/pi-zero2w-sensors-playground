const metricFormats = {
  co2: (value) => value == null ? '--' : `${Math.round(value)} ppm`,
  temp: (value) => value == null ? '--' : `${value.toFixed(1)} C`,
  humid: (value) => value == null ? '--' : `${value.toFixed(1)} %`,
  pm25: (value) => value == null ? '--' : `${value.toFixed(2)} ug/m3`,
  pm10: (value) => value == null ? '--' : `${value.toFixed(2)} ug/m3`,
  tps: (value) => value == null ? '--' : `${value.toFixed(2)} um`,
};

const chartState = new Map();
const weatherIconMap = {
  0: 'sun.png',
  1: 'sun.png',
  2: 'partly_cloudy.png',
  3: 'cloud.png',
  45: 'fog.png',
  48: 'fog.png',
  51: 'rain.png',
  53: 'rain.png',
  55: 'rain.png',
  56: 'rain.png',
  57: 'rain.png',
  61: 'rain.png',
  63: 'rain.png',
  65: 'rain.png',
  66: 'rain.png',
  67: 'rain.png',
  71: 'snow.png',
  73: 'snow.png',
  75: 'snow.png',
  77: 'snow.png',
  80: 'rain.png',
  81: 'rain.png',
  82: 'rain.png',
  85: 'snow.png',
  86: 'snow.png',
  95: 'storm.png',
  96: 'storm.png',
  99: 'storm.png',
};
let selectedHours = 24;

function formatTimestamp(value) {
  if (!value) {
    return '--';
  }
  const date = new Date(value);
  const two = (n) => String(n).padStart(2, '0');
  return `${two(date.getHours())}:${two(date.getMinutes())} ${two(date.getDate())}-${two(date.getMonth() + 1)}-${date.getFullYear()}`;
}

function calculateAqi(pm25, pm10) {
  if (pm25 == null || pm10 == null) {
    return null;
  }

  function linear(aqiHigh, aqiLow, concHigh, concLow, conc) {
    return Math.round(((aqiHigh - aqiLow) / (concHigh - concLow)) * (conc - concLow) + aqiLow);
  }

  function aqiPm25(value) {
    const c = Math.max(0, value);
    if (c <= 12.0) return linear(50, 0, 12.0, 0, c);
    if (c <= 35.4) return linear(100, 51, 35.4, 12.1, c);
    if (c <= 55.4) return linear(150, 101, 55.4, 35.5, c);
    if (c <= 150.4) return linear(200, 151, 150.4, 55.5, c);
    if (c <= 250.4) return linear(300, 201, 250.4, 150.5, c);
    if (c <= 350.4) return linear(400, 301, 350.4, 250.5, c);
    if (c <= 500.4) return linear(500, 401, 500.4, 350.5, c);
    return 500;
  }

  function aqiPm10(value) {
    const c = Math.max(0, value);
    if (c <= 54) return linear(50, 0, 54, 0, c);
    if (c <= 154) return linear(100, 51, 154, 55, c);
    if (c <= 254) return linear(150, 101, 254, 155, c);
    if (c <= 354) return linear(200, 151, 354, 255, c);
    if (c <= 424) return linear(300, 201, 424, 355, c);
    if (c <= 504) return linear(400, 301, 504, 425, c);
    if (c <= 604) return linear(500, 401, 604, 505, c);
    return 500;
  }

  return Math.max(aqiPm25(pm25), aqiPm10(pm10));
}

function aqiCategory(value) {
  if (value == null) return '--';
  if (value <= 50) return 'Good';
  if (value <= 100) return 'Moderate';
  if (value <= 175) return 'Unhealthy';
  if (value <= 300) return 'Very Unhealthy';
  return 'Hazardous';
}

function co2Category(value) {
  if (value == null) return '--';
  if (value < 1000) return 'Good';
  if (value < 1500) return 'Moderate';
  return 'Unhealthy';
}

function getLiveMetrics(summary) {
  return summary.latest_measurement || {};
}

function renderSummary(summary) {
  const metrics = getLiveMetrics(summary);
  const aqi = calculateAqi(metrics.pm25, metrics.pm10);

  document.getElementById('metric-co2').textContent = metricFormats.co2(metrics.co2);
  document.getElementById('metric-temp').textContent = metricFormats.temp(metrics.temp);
  document.getElementById('metric-humid').textContent = metricFormats.humid(metrics.humid);
  document.getElementById('metric-pm25').textContent = metricFormats.pm25(metrics.pm25);
  document.getElementById('metric-pm10').textContent = metricFormats.pm10(metrics.pm10);
  document.getElementById('metric-tps').textContent = metricFormats.tps(metrics.tps);
  document.getElementById('metric-aqi').textContent = aqi == null ? '--' : String(aqi);
  document.getElementById('metric-aqi-label').textContent = aqiCategory(aqi);
  document.getElementById('metric-co2-label').textContent = co2Category(metrics.co2);
  document.getElementById('latest-sample-time').textContent = `Dashboard sample: ${formatTimestamp(metrics.timestamp)}`;

  const collector = summary.collector_status?.value || {};
  document.getElementById('collector-running').textContent = `Collector: ${collector.running ? 'running' : 'stopped'}`;
  document.getElementById('collector-asc').textContent = `ASC: ${collector.scd41_asc_enabled ? 'enabled' : 'disabled'}`;
  document.getElementById('scd41-asc-enabled').checked = !!collector.scd41_asc_enabled;

  const weather = summary.latest_weather?.value || {};
  document.getElementById('weather-updated').textContent = `Updated: ${formatTimestamp(summary.latest_weather?.updated_at)}`;
  renderWeather(weather);
  renderCommands(summary.recent_commands || []);
}

function renderWeather(weather) {
  const grid = document.getElementById('forecast-grid');
  grid.innerHTML = '';
  const entries = [weather[1], weather[2], weather[3], weather['1'], weather['2'], weather['3']].filter(Boolean).slice(0, 3);
  if (!entries.length) {
    grid.innerHTML = '<div class="empty-state">No forecast data yet.</div>';
    return;
  }
  for (const block of entries) {
    const card = document.createElement('article');
    card.className = 'forecast-card';
    const [windowLabel, maxTemp, minTemp, precip, code] = block;
    const icon = weatherIconMap[code] || 'sun.png';
    const tempText = (maxTemp != null && minTemp != null) ? `${maxTemp} / ${minTemp} C` : '-- / -- C';
    const rainText = precip != null ? `${precip}%` : '--%';
    card.innerHTML = `
      <p class="forecast-window">${windowLabel}</p>
      <div class="forecast-body">
        <img class="forecast-icon" src="/assets/icons/${icon}" alt="forecast icon">
        <div class="forecast-stats">
          <p class="forecast-temp">${tempText}</p>
          <p class="forecast-rain">Rain: ${rainText}</p>
        </div>
      </div>
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

function renderLineChart(svgId, rows, key, color, formatValue) {
  const svg = document.getElementById(svgId);
  const tooltip = document.getElementById(`tooltip-${svgId}`);
  if (!rows.length || rows.every((row) => row[key] == null)) {
    svg.innerHTML = '<text x="24" y="40" fill="#59636e" font-size="16">No data yet</text>';
    tooltip.style.opacity = '0';
    chartState.delete(svgId);
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
    <line id="crosshair-${svgId}" x1="0" y1="${padding.top}" x2="0" y2="${height - padding.bottom}" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 4" opacity="0"></line>
    <circle id="focus-${svgId}" cx="0" cy="0" r="5" fill="${color}" stroke="#fffdf7" stroke-width="2" opacity="0"></circle>
    <polyline fill="none" stroke="${color}" stroke-width="3" points="${polyline}"></polyline>
    ${labels.join('')}
  `;

  chartState.set(svgId, { coordinates, formatValue, color, width, height });
}

function installChartHover(svgId) {
  const svg = document.getElementById(svgId);
  const tooltip = document.getElementById(`tooltip-${svgId}`);

  svg.addEventListener('mousemove', (event) => {
    const state = chartState.get(svgId);
    if (!state || !state.coordinates.length) {
      return;
    }
    const rect = svg.getBoundingClientRect();
    const scaleX = state.width / rect.width;
    const cursorX = (event.clientX - rect.left) * scaleX;
    let nearest = state.coordinates[0];
    for (const point of state.coordinates) {
      if (Math.abs(point.x - cursorX) < Math.abs(nearest.x - cursorX)) {
        nearest = point;
      }
    }

    const crosshair = document.getElementById(`crosshair-${svgId}`);
    const focus = document.getElementById(`focus-${svgId}`);
    crosshair.setAttribute('x1', nearest.x);
    crosshair.setAttribute('x2', nearest.x);
    crosshair.setAttribute('opacity', '1');
    focus.setAttribute('cx', nearest.x);
    focus.setAttribute('cy', nearest.y);
    focus.setAttribute('opacity', '1');

    tooltip.innerHTML = `<strong>${state.formatValue(nearest.row)}</strong><br>${formatTimestamp(nearest.row.timestamp)}`;
    tooltip.style.opacity = '1';
    tooltip.style.left = `${(nearest.x / state.width) * rect.width}px`;
    tooltip.style.top = `${(nearest.y / state.height) * rect.height - 10}px`;
  });

  svg.addEventListener('mouseleave', () => {
    const crosshair = document.getElementById(`crosshair-${svgId}`);
    const focus = document.getElementById(`focus-${svgId}`);
    if (crosshair) crosshair.setAttribute('opacity', '0');
    if (focus) focus.setAttribute('opacity', '0');
    tooltip.style.opacity = '0';
  });
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
  const aqiRows = rows.map((row) => ({ ...row, aqi: calculateAqi(row.pm25, row.pm10) }));
  renderLineChart('chart-temp', rows, 'temp', '#b85c38', (row) => `${row.temp.toFixed(1)} C`);
  renderLineChart('chart-humid', rows, 'humid', '#2b6f9e', (row) => `${row.humid.toFixed(1)} %`);
  renderLineChart('chart-co2', rows, 'co2', '#1f5c4a', (row) => `${Math.round(row.co2)} ppm`);
  renderLineChart('chart-aqi', aqiRows, 'aqi', '#9e6f00', (row) => `${Math.round(row.aqi)}`);
  renderLineChart('chart-pm25', rows, 'pm25', '#5b4b8a', (row) => `${row.pm25.toFixed(2)} ug/m3`);
  renderLineChart('chart-pm10', rows, 'pm10', '#6f4a2a', (row) => `${row.pm10.toFixed(2)} ug/m3`);
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
  await refreshAll();
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
    const value = Number(document.getElementById('auto-clean-value').value);
    const unit = document.getElementById('auto-clean-unit').value;
    const multipliers = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };
    const seconds = Math.round(value * multipliers[unit]);
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

  ['chart-temp', 'chart-humid', 'chart-co2', 'chart-aqi', 'chart-pm25', 'chart-pm10'].forEach(installChartHover);
}

async function refreshAll() {
  await Promise.all([fetchSummary(), fetchHistory()]);
}

installActions();
refreshAll();
setInterval(refreshAll, 15000);
