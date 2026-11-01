/* Cuadro de mando de escalas y tiempos de espera (Fase 7). Pide los datos a /api/port_calls con el
   mismo token que el visor (se comparte dentro de la pestaña). Todas las horas en UTC. */
'use strict';

const $ = (id) => document.getElementById(id);
const S = { token: '', zone: null, days: 30, data: null, subzones: null, map: null, layers: null };
// Colores fijos por terminal (paleta validada para daltonismo); «otros muelles» en gris neutro
const COLORS = { 'T-MSC': '#2a78d6', 'T-CSP': '#eb6834', 'T-APM': '#1baf7a', OTRO: '#5f5e5a' };
const EXTRA = ['#e87ba4', '#6250d6', '#eda100'];          // por si se dibujan más terminales
const QUEUE_COLOR = '#2a78d6';

// ------------------------------------------------------------------ utilidades
const pad = (n) => String(n).padStart(2, '0');
const toMs = (iso) => (iso ? Date.parse(iso) : null);
function fmtT(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
function fmtH(h) {
  if (h == null) return '—';
  if (h < 1) return `${Math.round(h * 60)} min`;
  return `${h.toFixed(1).replace('.', ',')} h`;
}
function esc(t) {               // los nombres AIS los escribe cualquiera: nunca HTML sin escapar
  return String(t ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function terminals() {          // [{key, label, color}] en el orden del archivo de subzonas, «otros» al final
  const t = (S.data?.summary.terminals || []).map((x, i) => ({
    key: x.terminal_id, label: x.name, color: COLORS[x.terminal_id] || EXTRA[i % EXTRA.length] }));
  return t;
}
const colorOf = (id) => (terminals().find((t) => t.key === id) || {}).color || '#5f5e5a';
const nameOf = (id) => (terminals().find((t) => t.key === id) || {}).label || id || '—';

// ------------------------------------------------------------------ token y API (igual que el visor)
function getToken() {
  const url = new URL(location.href);
  let t = url.searchParams.get('token');
  if (t) {
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

async function fetchApi(path, params = {}, retry = true) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v != null) url.searchParams.set(k, v);
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + S.token } });
  if (r.status === 401 && retry) {
    try { sessionStorage.removeItem('aisToken'); } catch (e) { /* sin almacenamiento */ }
    S.token = getToken();
    return fetchApi(path, params, false);
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r;
}
const api = async (path, params) => (await fetchApi(path, params)).json();
const period = () => ({ zone: S.zone, from: Math.floor(Date.now() / 1000) - S.days * 86400 });

// ------------------------------------------------------------------ carga
async function load() {
  $('computed').textContent = 'Calculando…';
  try {
    const [data, sub] = await Promise.all([api('/api/port_calls', period()), api('/api/subzones', { zone: S.zone })]);
    S.data = data;
    S.subzones = sub;
  } catch (e) {
    $('computed').textContent = 'Error: ' + e.message;
    return;
  }
  $('computed').textContent = `Calculado ${fmtT(S.data.computed_utc)} UTC · datos desde ${fmtT(S.data.data_from)}`;
  renderAll();
}

function renderAll() {
  renderNotice(); renderKpis(); renderQueue(); renderTerminals(); renderNow();
  renderHist(); renderDaily(); renderMap(); renderTable();
}

function renderNotice() {
  const days = (Date.now() - toMs(S.data.data_from)) / 86400000;
  const n = $('notice');
  n.classList.toggle('hidden', days >= 14);
  n.innerHTML = `<b>Solo hay ${days.toFixed(1).replace('.', ',')} días de datos.</b> Las esperas más largas todavía ` +
    'no han terminado y por eso aún no entran en las medianas (ver «Ahora mismo»): con pocos días las cifras ' +
    'salen más bajas de lo real. Las estadísticas usan solo las escalas OK (vistas completas).';
}

function kpi(value, label, sub) {
  return `<div class="kpi"><div class="v">${value}</div><div class="l">${label}</div>` +
    (sub ? `<div class="s">${sub}</div>` : '') + '</div>';
}

function renderKpis() {
  const s = S.data.summary, c = s.containers, q = s.quality;
  $('kpis').innerHTML = [
    kpi(s.waiting_now.length, 'esperando fuera ahora', 'buques de carga ≥ 100 m'),
    kpi(s.berthed_now.length, 'atracados ahora'),
    kpi(c.calls, 'escalas completas en terminales de contenedores',
      `${q.OK || 0} OK · ${q.DUDOSA || 0} dudosas · ${q['EN CURSO'] || 0} en curso · ${q.EXCLUIDA || 0} excluidas`),
    kpi(fmtH(c.wait_median_h), 'espera mediana (contenedores)', `p90 ${fmtH(c.wait_p90_h)} · media ${fmtH(c.wait_mean_h)}`),
    kpi(fmtH(c.stay_median_h), 'estancia mediana atracado', `p90 ${fmtH(c.stay_p90_h)}`),
  ].join('');
}

function renderQueue() {
  const qd = S.data.summary.queue;
  const short = qd.hours.length < 6 * 24;                  // menos de 6 días: también la hora en el eje
  Charts.line($('queue'), {
    xs: qd.hours.map(toMs), ys: qd.waiting, color: QUEUE_COLOR,
    fmtX: (x) => fmtT(new Date(x).toISOString()).slice(0, short ? 11 : 5),
    fmtTip: (i) => `<b>${fmtT(qd.hours[i])} UTC</b><br>${qd.waiting[i]} buques esperando fuera`,
  });
}

function renderTerminals() {
  const rows = S.data.summary.terminals;
  Charts.hbars($('byTerminal'), rows.map((t) => ({
    label: t.name, value: t.wait_median_h, mark: t.calls >= 3 ? t.wait_p90_h : null, color: colorOf(t.terminal_id),
    tip: `<b>${esc(t.name)}</b><br>${t.calls} escalas OK · ${t.with_wait} con espera<br>` +
      `mediana ${fmtH(t.wait_median_h)} · p75 ${fmtH(t.wait_p75_h)} · p90 ${fmtH(t.wait_p90_h)}<br>` +
      `media ${fmtH(t.wait_mean_h)} · máxima ${fmtH(t.wait_max_h)}`,
  })), { fmt: fmtH });
  $('statsTable').innerHTML = '<tr><th>Terminal</th><th>Escalas OK</th><th>Esperaron</th><th>Espera mediana</th>' +
    '<th>p90</th><th>Estancia mediana</th></tr>' + rows.map((t) =>
    `<tr><td>${esc(t.name)}</td><td>${t.calls}</td><td>${t.with_wait}</td><td>${fmtH(t.wait_median_h)}</td>` +
    `<td>${fmtH(t.wait_p90_h)}</td><td>${fmtH(t.stay_median_h)}</td></tr>`).join('');
}

function nowItem(v, berthed) {
  const since = (Date.now() - toMs(v.since)) / 3600000;
  const where = berthed ? nameOf(v.terminal_id) : (v.wait_location === 'DERIVA' ? 'a la deriva' : 'fondeadero');
  return `<li><span class="sw" style="background:${berthed ? colorOf(v.terminal_id) : '#9aa3ae'}"></span>` +
    `<span><b>${esc(v.name || v.mmsi)}</b> · ${esc(where)}${v.length_m ? ' · ' + v.length_m + ' m' : ''}</span>` +
    `<span class="t">${fmtH(since)}</span></li>`;
}

function renderNow() {
  const s = S.data.summary;
  const w = [...s.waiting_now].sort((a, b) => a.since.localeCompare(b.since));
  $('waitingNow').innerHTML = w.map((v) => nowItem(v, false)).join('') || '<li>Ninguno</li>';
  $('berthedNow').innerHTML = s.berthed_now.map((v) => nowItem(v, true)).join('') || '<li>Ninguno</li>';
}

const BINS = [[0, 1, '< 1 h'], [1, 3, '1–3 h'], [3, 6, '3–6 h'], [6, 12, '6–12 h'], [12, 24, '12–24 h'],
  [24, 48, '1–2 días'], [48, Infinity, '> 2 días']];

function renderHist() {
  const ok = S.data.calls.filter((c) => c.quality === 'OK');
  const count = {};
  for (const c of ok) {
    const b = BINS.find(([a, z]) => c.wait_h >= a && c.wait_h < z)[2];
    count[b] = count[b] || {};
    count[b][c.terminal_id] = (count[b][c.terminal_id] || 0) + 1;
  }
  Charts.stacked($('hist'), {
    cats: BINS.map((b) => b[2]), series: terminals(), value: (cat, k) => (count[cat] || {})[k] || 0,
    fmtCat: (c) => c,
    tipFn: (cat, total) => `<b>Espera ${cat}</b>: ${total} escalas<br>` + terminals()
      .filter((t) => (count[cat] || {})[t.key]).map((t) => `${esc(t.label)}: ${count[cat][t.key]}`).join('<br>'),
  });
}

function renderDaily() {
  const d = S.data.summary.daily_berths;
  const days = Object.keys(d).sort();
  Charts.stacked($('daily'), {
    cats: days, series: terminals(), value: (day, k) => d[day][k] || 0,
    fmtCat: (day) => `${day.slice(8, 10)}/${day.slice(5, 7)}`,
    tipFn: (day, total) => `<b>${day.slice(8, 10)}/${day.slice(5, 7)}</b>: ${total} atraques<br>` + terminals()
      .filter((t) => d[day][t.key]).map((t) => `${esc(t.label)}: ${d[day][t.key]}`).join('<br>'),
  });
}

function renderMap() {
  if (!S.map) {
    S.map = L.map('map', { scrollWheelZoom: false }).setView([39.43, -0.29], 12);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(S.map);
  }
  if (S.layers) S.layers.remove();
  S.layers = L.layerGroup().addTo(S.map);
  for (const f of S.subzones.features) {
    const p = f.properties;
    const style = p.kind === 'TERMINAL' ? { color: colorOf(p.subzone_id), weight: 2, fillOpacity: 0.12 }
      : p.kind === 'ANCHORAGE' ? { color: '#6b7280', weight: 1.5, dashArray: '6 4', fillOpacity: 0.05 }
        : { color: '#10263d', weight: 1, dashArray: '2 4', fill: false };
    L.geoJSON(f, { style }).bindTooltip(`<b>${esc(p.name)}</b><br>${esc(p.notes)}`, { sticky: true }).addTo(S.layers);
  }
  for (const c of S.data.calls) {
    if (c.berth_lat == null) continue;
    L.circleMarker([c.berth_lat, c.berth_lon], { radius: 5, color: '#fff', weight: 1.5,
      fillColor: colorOf(c.terminal_id), fillOpacity: 0.9 })
      .bindTooltip(`<b>${esc(c.name)}</b> · ${esc(nameOf(c.terminal_id))}<br>atraque ${fmtT(c.t_berth)} UTC<br>` +
        `espera ${fmtH(c.wait_h)} · ${esc(c.quality)}`).addTo(S.layers);
  }
}

function renderTable() {
  const f = $('qualityFilter').value;
  const rows = S.data.calls.filter((c) => !f || c.quality.startsWith(f))
    .sort((a, b) => (b.t_berth || b.t_start).localeCompare(a.t_berth || a.t_start));
  $('tableCount').textContent = `${rows.length} escalas`;
  $('calls').innerHTML = '<tr><th>Buque</th><th>Eslora</th><th>Terminal</th><th>Espera en</th>' +
    '<th>Llegada fondeo</th><th>Atraque</th><th>Desatraque</th><th>Espera</th><th>Estancia</th>' +
    '<th>Calado ent.</th><th>Calidad</th></tr>' + rows.map((c) =>
    `<tr><td><b>${esc(c.name || c.mmsi)}</b></td><td class="num">${c.length_m ?? ''} m</td>` +
    `<td><span class="sw" style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;` +
    `background:${c.terminal_id ? colorOf(c.terminal_id) : 'transparent'}"></span>${esc(c.terminal_id ? nameOf(c.terminal_id) : '—')}</td>` +
    `<td>${c.wait_location === 'DERIVA' ? 'a la deriva' : c.wait_location ? 'fondeadero' : '—'}</td>` +
    `<td>${fmtT(c.t_anchor_in)}</td><td>${fmtT(c.t_berth)}</td><td>${fmtT(c.t_unberth)}</td>` +
    `<td class="num">${fmtH(c.wait_h)}</td><td class="num">${fmtH(c.stay_h)}</td>` +
    `<td class="num">${c.draught_in_m != null ? String(c.draught_in_m).replace('.', ',') + ' m' : '—'}</td>` +
    `<td class="q">${esc(c.quality)}</td></tr>`).join('');
  const m = S.data.method;
  $('method').textContent = `Método ${m.version}: atracado = dentro del recinto y ≤ ${m.berth_max_kn} kn; ` +
    `esperando = fuera del recinto y ≤ ${m.anchor_max_kn} kn; buques tipo ${m.ship_types.join('–')} de ` +
    `${m.min_length_m} m o más. Espera = tiempo fondeado o a la deriva hasta arrancar hacia el puerto. ` +
    'Horas en UTC.';
}

async function downloadCsv(ev) {
  ev.preventDefault();
  try {
    const r = await fetchApi('/api/port_calls', { ...period(), format: 'csv' });
    const name = (r.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'escalas.csv';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) {
    alert('No se pudo descargar: ' + e.message);
  }
}

// ------------------------------------------------------------------ arranque
async function start() {
  S.token = getToken();
  const z = await api('/api/zones');
  const sel = $('zone');
  sel.innerHTML = z.zones.map((x) => `<option value="${esc(x.zone_id)}">${esc(x.name)}</option>`).join('');
  S.zone = z.zones[0]?.zone_id;
  sel.addEventListener('change', () => { S.zone = sel.value; load(); });
  $('range').addEventListener('click', (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    S.days = Number(b.dataset.days);
    for (const x of $('range').children) x.classList.toggle('on', x === b);
    load();
  });
  $('qualityFilter').addEventListener('change', renderTable);
  $('csv').addEventListener('click', downloadCsv);
  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => S.data && renderAll(), 200); });
  await load();
  setInterval(load, 10 * 60 * 1000);           // el cálculo se rehace cada 10 min en el servidor
}
start();
