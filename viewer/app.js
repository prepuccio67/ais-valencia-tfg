/* Visor AIS (Fase 4). Pide los datos a la API del Collector con el token y los
   dibuja sobre OpenStreetMap con Leaflet. Todas las horas se muestran en UTC. */
'use strict';

const $ = (id) => document.getElementById(id);
const S = {                       // estado del visor
  token: '', zone: null, zones: {}, first: null, live: true, at: null,
  vessels: [], markers: new Map(), selected: null, route: null,
  coverage: [], zoneGaps: [], sourceGaps: [], zoneLayer: null, loadSeq: 0,
};

// ------------------------------------------------------------------ utilidades
const now = () => Math.floor(Date.now() / 1000);
const toTs = (iso) => (iso ? Math.floor(Date.parse(iso) / 1000) : null);
const pad = (n) => String(n).padStart(2, '0');
function fmtTime(ts) {
  if (ts == null) return '—';
  const d = new Date(ts * 1000);
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ` +
         `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}
const fmtKn = (s) => (s == null ? '— kn' : `${s.toFixed(1)} kn`);
function fmtAgo(s) {
  if (s == null) return '—';
  if (s < 90) return `hace ${s} s`;
  if (s < 5400) return `hace ${Math.round(s / 60)} min`;
  return `hace ${(s / 3600).toFixed(1)} h`;
}
function esc(t) {               // los nombres AIS los escribe cualquiera: nunca HTML sin escapar
  return String(t ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'onclick') e.addEventListener('click', v); else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) e.append(c);
  return e;
}

const NAV = { 0: 'Navegando (motor)', 1: 'Fondeado', 2: 'Sin gobierno', 3: 'Maniobra restringida',
  4: 'Restringido por calado', 5: 'Amarrado', 6: 'Varado', 7: 'Pescando', 8: 'Navegando (vela)',
  15: 'No definido' };
function shipType(t) {
  if (t == null) return 'Desconocido';
  if (t >= 70 && t <= 79) return `Carga (${t})`;
  if (t >= 80 && t <= 89) return `Tanque (${t})`;
  if (t >= 60 && t <= 69) return `Pasaje (${t})`;
  const named = { 30: 'Pesca', 31: 'Remolque', 32: 'Remolque', 35: 'Militar', 36: 'Velero', 37: 'Recreo',
    50: 'Práctico', 51: 'Salvamento', 52: 'Remolcador', 53: 'Auxiliar de puerto', 55: 'Policía' };
  return `${named[t] || 'Otro'} (${t})`;
}
const isCargo = (v) => v.ship_type >= 70 && v.ship_type <= 79 && (v.length_m || 0) >= 100;
function color(sog) {
  if (sog == null || sog < 0.5) return '#6b7280';
  if (sog < 5) return '#f59e0b';
  if (sog < 12) return '#10b981';
  return '#3b82f6';
}

// ------------------------------------------------------------------ token y API
function getToken() {
  const url = new URL(location.href);
  let t = url.searchParams.get('token');
  if (t) {                                       // se guarda y se quita de la barra de direcciones
    try { sessionStorage.setItem('aisToken', t); } catch (e) { /* navegador sin almacenamiento */ }
    url.searchParams.delete('token');
    history.replaceState(null, '', url.pathname + url.search);
  } else {
    try { t = sessionStorage.getItem('aisToken'); } catch (e) { t = null; }
  }
  if (!t) {
    t = (prompt('Token de la API (API_TOKEN del archivo .env del servidor):') || '').trim();
    try { sessionStorage.setItem('aisToken', t); } catch (e) { /* sin almacenamiento */ }
  }
  return t;
}

async function api(path, params = {}, retry = true) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v != null) url.searchParams.set(k, v);
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + S.token } });
  if (r.status === 401 && retry) {
    try { sessionStorage.removeItem('aisToken'); } catch (e) { /* sin almacenamiento */ }
    S.token = getToken();
    return api(path, params, false);
  }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ------------------------------------------------------------------ mapa
const map = L.map('map', { preferCanvas: true }).setView([39.44, -0.31], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);
map.attributionControl.addAttribution(
  'Datos AIS: <a href="https://openseafeed.com">OpenSeaFeed</a> (CC BY 4.0) · <a href="https://aisstream.io">aisstream.io</a>');

function shipIcon(v, selected) {
  const size = isCargo(v) ? 24 : 15;
  const rot = v.heading != null ? v.heading : v.cog;
  const fill = color(v.sog);
  const stroke = selected ? '#000' : '#fff';
  const sw = selected ? 2.5 : 1.2;
  const shape = rot == null
    ? `<circle cx="12" cy="12" r="6" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`
    : `<path d="M12 2 L19 21 L12 17 L5 21 Z" transform="rotate(${rot} 12 12)" fill="${fill}"
         stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round"/>`;
  const opacity = v.age_s > 900 ? 0.45 : 1;           // posición de hace más de 15 min: atenuada
  return L.divIcon({ className: 'ship-icon', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" style="opacity:${opacity}">${shape}</svg>` });
}

function filtered() {
  const q = $('search').value.trim().toUpperCase();
  const cargo = $('onlyCargo').checked;
  return S.vessels.filter((v) => (!cargo || isCargo(v)) &&
    (!q || (v.name || '').toUpperCase().includes(q) || String(v.mmsi).includes(q)));
}

function render() {
  const vs = filtered();
  const keep = new Set(vs.map((v) => v.mmsi));
  for (const [m, mk] of S.markers) if (!keep.has(m)) { map.removeLayer(mk); S.markers.delete(m); }
  for (const v of vs) {
    let mk = S.markers.get(v.mmsi);
    const icon = shipIcon(v, v.mmsi === S.selected);
    if (!mk) {
      mk = L.marker([v.lat, v.lon], { icon, zIndexOffset: isCargo(v) ? 500 : 0 }).addTo(map);
      mk.on('click', () => select(v.mmsi));
      mk.bindTooltip('', { className: 'ship-tip', direction: 'top', offset: [0, -8] });
      S.markers.set(v.mmsi, mk);
    } else {
      mk.setLatLng([v.lat, v.lon]);
      mk.setIcon(icon);
    }
    mk.setTooltipContent(`${esc(v.name || 'MMSI ' + v.mmsi)} · ${fmtKn(v.sog)}`);
  }
  renderList(vs);
  const cargo = S.vessels.filter(isCargo).length;
  $('counters').replaceChildren(
    el('span', { class: 'pill', text: `${S.vessels.length} buques` }),
    el('span', { class: 'pill', text: `${cargo} de carga ≥ 100 m` }),
    el('span', { class: 'pill', text: `${vs.length} mostrados` }));
}

function renderList(vs) {
  const items = vs.map((v) => el('li', { class: v.mmsi === S.selected ? 'sel' : '', onclick: () => select(v.mmsi) },
    el('span', { class: 'dot', style: `background:${color(v.sog)}` }),
    el('div', {}, el('div', { class: 'name', text: v.name || `MMSI ${v.mmsi}` }),
      el('div', { class: 'meta', text: `${v.mmsi} · ${shipType(v.ship_type)}${v.length_m ? ' · ' + v.length_m + ' m' : ''}` })),
    el('div', { class: 'spd', text: `${fmtKn(v.sog)}\n${v.cog != null ? Math.round(v.cog) + '°' : ''}` })));
  $('list').replaceChildren(...items);
}

// ------------------------------------------------------------------ foto del puerto
async function loadSnapshot() {
  const seq = ++S.loadSeq;
  const at = S.live ? now() : S.at;
  try {
    const data = await api('/api/vessels', { zone: S.zone, at, window: 1200 });
    if (seq !== S.loadSeq) return;               // llegó tarde: ya se pidió otro instante
    S.vessels = data.vessels;
    render();
    if (S.selected) refreshPanelPosition();
  } catch (e) { console.error(e); }
  updateTimeLabel();
}

// ------------------------------------------------------------------ buque seleccionado
async function select(mmsi, pan = true) {
  S.selected = mmsi;
  clearRoute();
  render();
  const v = S.vessels.find((x) => x.mmsi === mmsi);
  if (v && pan) map.panTo([v.lat, v.lon]);
  let info = null;
  try { info = await api(`/api/vessel/${mmsi}`, { zone: S.zone }); } catch (e) { /* sin ficha */ }
  showPanel(v, info);
}

function row(label, value) { return el('tr', {}, el('td', { text: label }), el('td', { text: value ?? '—' })); }

function showPanel(v, info) {
  const i = info || {};
  const last = (i.voyage || []).slice(-1)[0] || {};
  const name = (v && v.name) || i.name || `MMSI ${S.selected}`;
  const panel = $('vesselPanel');
  panel.replaceChildren(
    el('h2', { text: name }),
    el('table', {},
      row('MMSI · IMO', `${S.selected} · ${i.imo ?? '—'}`),
      row('Tipo', shipType(i.ship_type ?? (v && v.ship_type))),
      row('Eslora × manga', i.length_m ? `${i.length_m} × ${i.beam_m ?? '—'} m` : '—'),
      row('Indicativo', i.callsign),
      row('Destino / calado', `${last.destination ?? '—'} / ${last.draught_m != null ? last.draught_m + ' m' : '—'}`),
      row('ETA declarada', last.eta_utc ? fmtTime(toTs(last.eta_utc)) : (last.eta_raw ?? '—')),
      row('Velocidad · rumbo', v ? `${fmtKn(v.sog)} · ${v.cog != null ? Math.round(v.cog) + '°' : '—'}` : '—'),
      row('Estado AIS', v && v.nav_status != null ? NAV[v.nav_status] || v.nav_status : '—'),
      row('Posición', v ? `${fmtTime(toTs(v.ts))} (${fmtAgo(v.age_s)})` : 'sin posición en este instante'),
      row('Visto en la zona', `${i.first_seen ? fmtTime(toTs(i.first_seen)) : '—'} → ${i.last_seen ? fmtTime(toTs(i.last_seen)) : '—'}`)),
    el('div', { class: 'btns' },
      el('button', { class: 'primary', text: 'Ruta 24 h', onclick: () => loadRoute(24) }),
      el('button', { text: 'Ruta 3 días', onclick: () => loadRoute(72) }),
      el('button', { text: 'Ruta 7 días', onclick: () => loadRoute(168) }),
      el('button', { text: 'Cerrar', onclick: closePanel })),
    el('div', { id: 'playBox', class: 'play hidden' },
      el('button', { id: 'playBtn', text: '▶ Reproducir', onclick: togglePlay }),
      el('select', { id: 'playSpeed', title: 'Velocidad de reproducción' },
        el('option', { value: '60', text: 'x60 (1 min/s)' }),
        el('option', { value: '600', text: 'x600 (10 min/s)', selected: '' }),
        el('option', { value: '3600', text: 'x3600 (1 h/s)' })),
      el('span', { id: 'playTime' })));
  panel.classList.remove('hidden');
}

function refreshPanelPosition() {
  if (!S.route) select(S.selected, false);    // actualiza velocidad/posición sin mover el mapa
}

function closePanel() {
  S.selected = null;
  clearRoute();
  $('vesselPanel').classList.add('hidden');
  render();
}

// ------------------------------------------------------------------ rutas y reproducción
function clearRoute() {
  const r = S.route;
  if (!r) return;
  if (r.raf) cancelAnimationFrame(r.raf);
  map.removeLayer(r.layer);
  S.route = null;
}

async function loadRoute(hours) {
  const end = S.live ? now() : S.at;
  const from = end - hours * 3600;
  const tr = await api(`/api/track/${S.selected}`, { zone: S.zone, from, to: end + 60 });
  clearRoute();
  if (!tr.points.length) { alert('No hay posiciones guardadas de este buque en ese periodo.'); return; }
  const pts = tr.points;               // [ts, lat, lon, sog, cog, nav]
  const layer = L.layerGroup().addTo(map);
  L.polyline(pts.map((p) => [p[1], p[2]]), { color: '#0b5cad', weight: 3, opacity: 0.6 }).addTo(layer);
  for (const p of pts) {
    L.circleMarker([p[1], p[2]], { radius: 3, weight: 0, fillOpacity: 0.9, fillColor: color(p[3]) })
      .bindTooltip(`${fmtTime(p[0])} · ${fmtKn(p[3])} · ${NAV[p[5]] || ''}`).addTo(layer);
  }
  const boat = L.circleMarker([pts[0][1], pts[0][2]], { radius: 8, color: '#000', weight: 2,
    fillColor: '#facc15', fillOpacity: 1 }).addTo(layer);
  S.route = { pts, layer, boat, t: pts[0][0], raf: null, last: null };
  map.fitBounds(L.polyline(pts.map((p) => [p[1], p[2]])).getBounds(), { padding: [40, 40], maxZoom: 15 });
  $('playBox').classList.remove('hidden');
  $('playTime').textContent = `${pts.length} posiciones · ${fmtTime(pts[0][0])}`;
}

function interpolate(pts, t) {
  let lo = 0, hi = pts.length - 1;
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2], pts[0][3]];
  if (t >= pts[hi][0]) return [pts[hi][1], pts[hi][2], pts[hi][3]];
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (pts[mid][0] <= t) lo = mid; else hi = mid; }
  const a = pts[lo], b = pts[hi], f = (t - a[0]) / (b[0] - a[0]);
  return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3]];
}

function togglePlay() {
  const r = S.route;
  if (!r) return;
  if (r.raf) { cancelAnimationFrame(r.raf); r.raf = null; $('playBtn').textContent = '▶ Reproducir'; return; }
  if (r.t >= r.pts[r.pts.length - 1][0]) r.t = r.pts[0][0];       // al final: empezar de nuevo
  r.last = performance.now();
  $('playBtn').textContent = '⏸ Pausa';
  const step = (ms) => {
    const speed = Number($('playSpeed').value);
    r.t += ((ms - r.last) / 1000) * speed;
    r.last = ms;
    const end = r.pts[r.pts.length - 1][0];
    const [lat, lon, sog] = interpolate(r.pts, Math.min(r.t, end));
    r.boat.setLatLng([lat, lon]);
    $('playTime').textContent = `${fmtTime(Math.floor(r.t))} · ${fmtKn(sog)}`;
    if (r.t >= end) { r.raf = null; $('playBtn').textContent = '▶ Repetir'; return; }
    r.raf = requestAnimationFrame(step);
  };
  r.raf = requestAnimationFrame(step);
}

// ------------------------------------------------------------------ línea temporal, cobertura y huecos
function updateTimeLabel() {
  const t = S.live ? now() : S.at;
  $('timeLabel').textContent = (S.live ? 'Ahora · ' : '') + fmtTime(t);
  $('live').classList.toggle('on', S.live);
}

function drawCoverage() {
  const cv = $('coverage');
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * devicePixelRatio; cv.height = h * devicePixelRatio;
  const ctx = cv.getContext('2d');
  ctx.scale(devicePixelRatio, devicePixelRatio);
  ctx.clearRect(0, 0, w, h);
  const a = S.first, b = now();
  if (a == null || b <= a) return;
  const x = (t) => ((t - a) / (b - a)) * w;
  const max = Math.max(1, ...S.coverage.map((c) => c.n));
  ctx.fillStyle = '#9fb7d3';
  for (const c of S.coverage) {
    const bh = Math.max(1, (c.n / max) * (h - 4));
    ctx.fillRect(x(c.t), h - bh, Math.max(1, x(c.t + 3600) - x(c.t) - 0.5), bh);
  }
  ctx.fillStyle = 'rgba(192,57,43,0.85)';
  for (const g of S.zoneGaps) ctx.fillRect(x(g.a), 0, Math.max(2, x(g.b) - x(g.a)), h);
}

async function loadTimeline() {
  const b = await api('/api/bounds', { zone: S.zone });
  S.first = b.first || now() - 3600;
  const slider = $('slider');
  slider.min = S.first;
  slider.max = now();
  if (S.live) slider.value = slider.max;
  try {
    const cov = await api('/api/coverage', { zone: S.zone, from: S.first, to: now() + 60, bucket: 'hour' });
    S.coverage = cov.rows.map((r) => ({ t: toTs(r.t),
      n: Object.values(r.sources).reduce((s, x) => s + x.msgs, 0) }));
    const gaps = await api('/api/gaps', { zone: S.zone, from: S.first, to: now() + 60 });
    S.zoneGaps = gaps.zone_gaps.map((g) => ({ a: toTs(g.start), b: g.end ? toTs(g.end) : now(), min: g.minutes }));
    S.sourceGaps = gaps.source_gaps;
  } catch (e) { console.error(e); }
  drawCoverage();
  renderGapsBadge();
}

function renderGapsBadge() {
  const badge = $('gapsBadge');
  const nz = S.zoneGaps.length, ns = S.sourceGaps.length;
  badge.classList.toggle('hidden', nz + ns === 0);
  badge.style.background = nz ? '#c0392b' : '#b7791f';
  badge.textContent = `⚠ Huecos: ${nz} de zona · ${ns} de fuente`;
  const panel = $('gapsPanel');
  panel.replaceChildren(
    el('h3', { text: 'Huecos de datos' }),
    el('p', { text: 'Zona: periodos sin datos de ninguna fuente. Fuente: una sola fuente sin datos (la otra cubría).' }),
    el('ul', {}, ...S.sourceGaps.slice(-30).reverse().map((g) => el('li', {
      text: `${fmtTime(toTs(g.start))} → ${g.end ? fmtTime(toTs(g.end)) : 'abierto'} · ${g.minutes} min · ${g.source} · ${g.reason}` }))));
}

// ------------------------------------------------------------------ fuentes y zona
async function loadHealth() {
  try {
    const h = await api('/api/health');
    $('sources').replaceChildren(...Object.entries(h.sources).map(([name, s]) => el('span', {
      class: 'pill ' + (s.connected && (s.last_msg_age_s ?? 999) < 120 ? 'ok' : 'bad'),
      text: `${name} ${s.connected ? fmtAgo(s.last_msg_age_s) : 'desconectada'}` })));
  } catch (e) { console.error(e); }
}

async function loadZones() {
  const data = await api('/api/zones');
  const sel = $('zone');
  sel.replaceChildren(...data.zones.map((z) => el('option', { value: z.zone_id,
    text: z.name + (z.active ? '' : ' (inactiva)') })));
  for (const z of data.zones) S.zones[z.zone_id] = z;
  S.zone = data.zones[0] && data.zones[0].zone_id;
  drawZone();
}

function drawZone() {
  if (S.zoneLayer) map.removeLayer(S.zoneLayer);
  const z = S.zones[S.zone];
  if (!z) return;
  const ring = z.geometry.coordinates[0].map(([lon, lat]) => [lat, lon]);
  S.zoneLayer = L.polygon(ring, { color: '#0b5cad', weight: 1.5, dashArray: '6 6', fill: false }).addTo(map);
  map.invalidateSize();          // el mapa debe conocer su tamaño real antes de encuadrar
  map.fitBounds(S.zoneLayer.getBounds(), { padding: [10, 10], maxZoom: 14 });
}

// ------------------------------------------------------------------ eventos
let debounce = null;
$('slider').addEventListener('input', () => {
  S.live = false;
  S.at = Number($('slider').value);
  updateTimeLabel();
  clearTimeout(debounce);
  debounce = setTimeout(loadSnapshot, 250);
});
$('back').addEventListener('click', () => { S.live = false; S.at = Math.max(S.first, (S.at || now()) - 3600);
  $('slider').value = S.at; loadSnapshot(); });
$('fwd').addEventListener('click', () => { const t = (S.at || now()) + 3600;
  if (t >= now()) { $('live').click(); return; } S.live = false; S.at = t; $('slider').value = t; loadSnapshot(); });
$('live').addEventListener('click', () => { S.live = true; S.at = null; $('slider').max = now();
  $('slider').value = $('slider').max; loadSnapshot(); });
$('search').addEventListener('input', render);
$('onlyCargo').addEventListener('change', render);
$('gapsBadge').addEventListener('click', () => $('gapsPanel').classList.toggle('hidden'));
$('zone').addEventListener('change', async () => {
  S.zone = $('zone').value; closePanel(); drawZone(); await loadTimeline(); loadSnapshot();
});
window.addEventListener('resize', drawCoverage);

// ------------------------------------------------------------------ arranque
(async function start() {
  S.token = getToken();
  try {
    await loadZones();
    await Promise.all([loadTimeline(), loadHealth()]);
    await loadSnapshot();
  } catch (e) {
    alert('No se pudo cargar el visor: ' + e.message);
    return;
  }
  setInterval(() => { if (S.live) loadSnapshot(); loadHealth(); updateTimeLabel(); }, 30000);
  setInterval(() => { $('slider').max = now(); if (S.live) $('slider').value = now(); loadTimeline(); }, 300000);
})();
