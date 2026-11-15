/* Precisión de la ETA declarada (7c.1, eta-v1, D-20). Usa las utilidades de escalas.js
   ($, api, fetchApi, esc, S). Si la API falla, el resto del cuadro sigue funcionando. */
'use strict';

const ETA = { data: null, def: 'ZONA_ESPERA', term: 'TOTAL', variant: 'base' };
const ETA_DEFS = { ZONA_ESPERA: 'llegada a la zona de espera', RECINTO: 'entrada en el recinto', ATRAQUE: 'atraque' };
const ETA_STATUS = {
  USABLE: 'utilizable', LLEGADA_NO_VISTA: 'llegada no vista', ANTES_CAPTURA: 'antes de la captura',
  SIN_COBERTURA: 'buque no visto en las 2 h anteriores', SIN_ETA: 'sin ETA', DESTINO_OTRO: 'destino: otro puerto',
  DESTINO_DUDOSO: 'destino dudoso', ETA_CADUCADA: 'ETA caducada', ETA_IMPOSIBLE: 'ETA imposible (> 30 días)',
  ESCALA_EXCLUIDA: 'escala excluida',
};
const num = (v, d = 1) => (v == null ? '—' : v.toFixed(d).replace('.', ','));
const hLabel = (h) => (h === 'ULTIMA' ? 'última ETA' : `${h} h antes`);

async function loadEta() {
  try {
    ETA.data = await api('/api/eta_accuracy', { zone: S.zone, variante: ETA.variant });
  } catch (e) {
    $('etaBody').innerHTML = `<p class="hint">No se pudo cargar la precisión de la ETA: ${esc(e.message)}</p>`;
    return;
  }
  renderEta();
}

function renderEta() {
  const d = ETA.data;
  const bands = d.params.bandas_h;
  const bandKey = (b) => `pct_${String(b).replace('.', '_')}h`;
  const rows = d.stats.filter((s) => s.definition === ETA.def && s.terminal_id === ETA.term);
  const head = '<tr><th>Horizonte</th><th>n</th><th>Mediana</th><th>Sesgo</th><th>MAE</th><th>RMSE</th>' +
    bands.map((b) => `<th>±${num(b, b % 1 ? 1 : 0)} h</th>`).join('') + '<th>P10 a P90</th><th>Antelación</th></tr>';
  const body = rows.map((s) => {
    if (!s.n) return `<tr><td>${hLabel(s.horizon)}</td><td>0</td><td colspan="${7 + bands.length}" class="q">sin casos utilizables</td></tr>`;
    const few = s.pocos_datos ? ' class="few" title="Pocos datos: menos de ' + d.params.min_n + ' escalas"' : '';
    return `<tr${few}><td>${hLabel(s.horizon)}</td><td>${s.n}</td><td>${num(s.mediana_h)} h</td>` +
      `<td>${num(s.sesgo_h)} h</td><td>${num(s.mae_h)} h</td><td>${num(s.rmse_h)} h</td>` +
      bands.map((b) => `<td>${num(s[bandKey(b)], 0)} %</td>`).join('') +
      `<td>${num(s.p10_h)} a ${num(s.p90_h)} h</td>` +
      `<td>${s.antelacion_mediana_h != null ? num(s.antelacion_mediana_h) + ' h' : ''}</td></tr>`;
  }).join('');
  // descartes por motivo (todas las terminales)
  const hs = ['ULTIMA', ...d.params.horizontes_h.map(String)];
  const used = d.statuses.filter((st) => hs.some((h) => (d.counts[`${ETA.def}|${h}`] || {})[st]));
  const disc = '<tr><th>Estado</th>' + hs.map((h) => `<th>${h === 'ULTIMA' ? 'última' : h + ' h'}</th>`).join('') + '</tr>' +
    used.map((st) => `<tr><td>${ETA_STATUS[st] || st}</td>` +
      hs.map((h) => `<td>${(d.counts[`${ETA.def}|${h}`] || {})[st] || ''}</td>`).join('') + '</tr>').join('');
  $('etaBody').innerHTML =
    `<p class="notice">${esc(d.aviso)} Las filas en gris tienen menos de ${d.params.min_n} escalas: no las cites.</p>` +
    `<table class="stats eta">${head}${body}</table>` +
    `<h3>Casos y descartes por motivo <span class="hint">${ETA_DEFS[ETA.def]}, todas las terminales</span></h3>` +
    `<table class="stats eta">${disc}</table>` +
    `<p class="method">Método ${esc(d.params.version)} (escalas ${esc(d.escalas_method || '')}). ` +
    'Error = ETA declarada − llegada real: positivo = el buque llegó antes de lo que declaraba. ' +
    'Sesgo = error medio; MAE = error medio sin signo; RMSE = como el MAE, pero castiga más los errores grandes. ' +
    '«Última ETA» = la última ETA válida antes de llegar, con su antelación mediana. ' +
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
  $('etaCsv').addEventListener('click', async (ev) => {
    ev.preventDefault();
    try {
      const r = await fetchApi('/api/eta_accuracy', { zone: S.zone, format: 'csv', tabla: 'indicadores', variante: ETA.variant });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await r.blob());
      a.download = (r.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'eta.csv';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) {
      alert('No se pudo descargar: ' + e.message);
    }
  });
}
