/* Precisión de la ETA declarada (7c.1, eta-v1, D-20). Usa las utilidades de escalas.js
   ($, api, fetchApi, esc, fmtT, nameOf, S). Si la API falla, el resto del cuadro sigue funcionando. */
'use strict';

const ETA = { data: null, def: 'ZONA_ESPERA', term: 'TOTAL', variant: 'base' };
const ETA_DEFS = { ZONA_ESPERA: 'llegada a la zona de espera', RECINTO: 'entrada en el recinto', ATRAQUE: 'atraque' };
const ETA_STATUS = {
  USABLE: 'utilizable', LLEGADA_NO_VISTA: 'llegada no vista', ANTES_CAPTURA: 'antes de la captura',
  SIN_COBERTURA: 'buque no visto en las 2 h anteriores', SIN_ETA: 'sin ETA', DESTINO_OTRO: 'destino: otro puerto',
  DESTINO_DUDOSO: 'destino dudoso', ESCALA_ANTERIOR: 'ETA de la escala anterior', ETA_CADUCADA: 'ETA caducada', ETA_IMPOSIBLE: 'ETA imposible (> 30 días)',
  ESCALA_EXCLUIDA: 'escala excluida',
};
const num = (v, d = 1) => (v == null ? '—' : v.toFixed(d).replace('.', ','));
const hLabel = (h) => (h === 'ULTIMA' ? 'última ETA' : `${h} h antes`);
const bandKey = (b) => `pct_${String(b).replace('.', '_')}h`;

async function loadEta() {
  try {
    ETA.data = await api('/api/eta_accuracy', { zone: S.zone, variante: ETA.variant });
  } catch (e) {
    $('etaBody').innerHTML = `<p class="hint">No se pudo cargar la precisión de la ETA: ${esc(e.message)}</p>`;
    return;
  }
  renderEta();
}

// Tabla principal: mediana y % en cada banda como cifras principales; sesgo, MAE y RMSE en segundo plano.
function mainTable(d) {
  const bands = d.params.bandas_h;
  const rows = d.stats.filter((s) => s.definition === ETA.def && s.terminal_id === ETA.term);
  const head = '<tr><th>Horizonte</th><th>n</th><th>Mediana</th>' +
    bands.map((b) => `<th>±${num(b, b % 1 ? 1 : 0)} h</th>`).join('') +
    '<th>P10 a P90</th><th>Antelación</th><th>ETA de atraque</th><th class="sec">Sesgo</th><th class="sec">MAE</th><th class="sec">RMSE</th></tr>';
  const body = rows.map((s) => {
    if (!s.n) {
      return `<tr><td>${hLabel(s.horizon)}</td><td>0</td><td colspan="${8 + bands.length}" class="q">sin casos utilizables</td></tr>`;
    }
    const few = s.pocos_datos ? ` class="few" title="Pocos datos: menos de ${d.params.min_n} escalas"` : '';
    return `<tr${few}><td>${hLabel(s.horizon)}</td><td>${s.n}</td><td><b>${num(s.mediana_h)} h</b></td>` +
      bands.map((b) => `<td><b>${num(s[bandKey(b)], 0)} %</b></td>`).join('') +
      `<td>${num(s.p10_h)} a ${num(s.p90_h)} h</td>` +
      `<td>${s.antelacion_mediana_h != null ? num(s.antelacion_mediana_h) + ' h' : ''}</td>` +
      `<td>${s.n_eta_atraque ? s.n_eta_atraque + ' (' + num(s.pct_eta_atraque, 0) + ' %)' : ''}</td>` +
      `<td class="sec">${num(s.sesgo_h)} h</td><td class="sec">${num(s.mae_h)} h</td><td class="sec">${num(s.rmse_h)} h</td></tr>`;
  }).join('');
  return head + body;
}

// Análisis de sensibilidad: regla principal / regla alternativa, para la última ETA y los horizontes de 0 y 1 h.
function sensTable(d) {
  const pick = (st, h) => st.find((x) => x.definition === ETA.def && x.terminal_id === ETA.term && x.horizon === h) || {};
  const cell = (x, k, u) => (x.n ? `${num(x[k], k.startsWith('pct') ? 0 : 1)}${u}` : '—');
  return '<tr><th>Horizonte</th><th>n</th><th>Mediana</th><th>±1 h</th><th>MAE</th></tr>' +
    ['ULTIMA', '0', '1'].map((h) => {
      const a = pick(d.stats, h), b = pick(d.sensitivity.stats, h);
      return `<tr><td>${hLabel(h)}</td><td>${a.n ?? 0} / ${b.n ?? 0}</td>` +
        `<td>${cell(a, 'mediana_h', ' h')} / ${cell(b, 'mediana_h', ' h')}</td>` +
        `<td>${cell(a, 'pct_1h', ' %')} / ${cell(b, 'pct_1h', ' %')}</td>` +
        `<td>${cell(a, 'mae_h', ' h')} / ${cell(b, 'mae_h', ' h')}</td></tr>`;
    }).join('');
}

// Casos con error de más de revision_umbral_h, para revisarlos a mano.
function reviewTable(d) {
  if (!d.review.length) return '<tr><td class="q">Ningún caso supera el umbral.</td></tr>';
  return '<tr><th>Buque</th><th>Terminal</th><th>ETA declarada</th><th>Llegada</th><th>ETA emitida</th>' +
    '<th>Error</th><th>Horizontes</th></tr>' +
    d.review.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(nameOf(x.terminal_id))}</td><td>${fmtT(x.eta_utc)}</td>` +
      `<td>${fmtT(x.t_arrival)}</td><td>${fmtT(x.eta_ts)}</td><td>${num(x.error_h)} h</td>` +
      `<td class="q">${esc(x.horizons)}</td></tr>`).join('');
}

// Descartes por motivo (todas las terminales).
function statusTable(d) {
  const hs = ['ULTIMA', ...d.params.horizontes_h.map(String)];
  const used = d.statuses.filter((st) => hs.some((h) => (d.counts[`${ETA.def}|${h}`] || {})[st]));
  return '<tr><th>Estado</th>' + hs.map((h) => `<th>${h === 'ULTIMA' ? 'última' : h + ' h'}</th>`).join('') + '</tr>' +
    used.map((st) => `<tr><td>${ETA_STATUS[st] || st}</td>` +
      hs.map((h) => `<td>${(d.counts[`${ETA.def}|${h}`] || {})[st] || ''}</td>`).join('') + '</tr>').join('');
}

function renderEta() {
  const d = ETA.data;
  $('etaBody').innerHTML =
    `<p class="notice">${esc(d.aviso)} Las filas en gris tienen menos de ${d.params.min_n} escalas: no las cites.</p>` +
    `<table class="stats eta">${mainTable(d)}</table>` +
    `<h3>Análisis de sensibilidad <span class="hint">regla principal «${esc(d.params.caducada_referencia)}» / ` +
    `regla «${esc(d.sensitivity.rule)}», que además excluye las ETA ya pasadas en el momento de mirar (y con ello los ` +
    'retrasos de más de 1 h)</span></h3>' +
    `<table class="stats eta">${sensTable(d)}</table>` +
    `<h3>Para revisar a mano <span class="hint">errores de más de ${num(d.params.revision_umbral_h, 0)} h: ¿retraso real ` +
    'o ETA olvidada? El botón «⬇ Revisión» descarga la lista con columnas para anotar</span></h3>' +
    `<table class="stats eta">${reviewTable(d)}</table>` +
    `<h3>Casos y descartes por motivo <span class="hint">${ETA_DEFS[ETA.def]}, todas las terminales</span></h3>` +
    `<table class="stats eta">${statusTable(d)}</table>` +
    `<p class="method">Método ${esc(d.params.version)} (escalas ${esc(d.escalas_method || '')}). ` +
    'Error = ETA declarada − llegada real: positivo = el buque llegó antes de lo que declaraba. ' +
    'Cifras principales: mediana y % dentro de cada banda. En segundo plano: sesgo = error medio; MAE = error ' +
    'medio sin signo; RMSE = como el MAE, pero castiga más los errores grandes. ' +
    '«Última ETA» = la última ETA válida antes de llegar, con su antelación mediana. ' +
    'ETA caducada (regla principal) = ya había pasado más de 1 h cuando el buque la emitió. ' +
    '«ETA de atraque» = la ETA está más cerca del atraque que de la llegada (escalas con 3 h o más de espera): se cuenta, no se descarta. ' +
    'Las ETA emitidas durante la escala anterior del mismo buque no se usan. ' +
    `Calculado ${fmtT(d.computed_utc)} UTC.</p>`;
}

function setupEta() {
  const pick = (id, key) => $(id).addEventListener('change', (ev) => {
    ETA[key] = ev.target.value;
    if (key === 'variant') loadEta(); else if (ETA.data) renderEta();
  });
  pick('etaDef', 'def');
  pick('etaTerm', 'term');
  pick('etaVariant', 'variant');
  const download = (tabla) => async (ev) => {
    ev.preventDefault();
    try {
      const r = await fetchApi('/api/eta_accuracy', { zone: S.zone, format: 'csv', tabla, variante: ETA.variant });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await r.blob());
      a.download = (r.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'eta.csv';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) {
      alert('No se pudo descargar: ' + e.message);
    }
  };
  $('etaCsv').addEventListener('click', download('indicadores'));
  $('etaReview').addEventListener('click', download('revision'));
}
