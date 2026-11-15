/* Espera doble (escalas-v3, D-22) y comparación con la APV. Usa las utilidades de escalas.js
   ($, esc, fmtH, fmtT, S). Solo se dibuja si la API trae los campos de escalas-v3. */
'use strict';

const pctf = (v) => (v == null ? '—' : `${String(v).replace('.', ',')} %`);

function waitRow(label, s) {
  if (!s) return '';
  return `<tr><td>${esc(label)}</td><td>${s.wait_calls ?? 0}</td><td><b>${pctf(s.pct_wait)}</b></td><td>${pctf(s.pct_wait_3h)}</td>` +
    `<td><b>${fmtH(s.wait_median_h)}</b></td><td>${fmtH(s.wait_mean_h)}</td><td>${fmtH(s.wait_p90_h)}</td>` +
    `<td>${s.anchor_calls ?? 0}</td><td><b>${pctf(s.pct_anchor)}</b></td><td>${fmtH(s.anchor_mean_h)}</td>` +
    `<td class="sec">${pctf(s.pct_loiter)}</td><td class="sec">${fmtH(s.loiter_mean_h)}</td></tr>`;
}

function renderDoubleWait() {
  const d = S.data;
  const card = $('doubleWait');
  if (!d || !d.summary || d.summary.containers.pct_anchor === undefined) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');
  const s = d.summary;
  const from = s.wait_stats_from ? fmtT(s.wait_stats_from) : null;
  const mw = s.min_wait_h != null ? String(s.min_wait_h).replace('.', ',') : null;
  const head = '<tr><th rowspan="2">Grupo</th><th colspan="6">Espera total en el área de espera' +
    (from ? ` (escalas desde el ${from})` : '') + '</th><th colspan="3">En fondeadero oficial (todo el periodo)</th>' +
    '<th colspan="2" class="sec">Merodeo lento</th></tr>' +
    '<tr><th>Escalas</th><th>Esperan</th><th>≥ 3 h</th><th>Mediana</th><th>Media</th><th>P90</th>' +
    '<th>Escalas</th><th>Fondean</th><th>Media</th><th class="sec">≥ 1 h</th><th class="sec">Media</th></tr>';
  const rows = [waitRow('Todas las terminales de contenedores', s.containers)]
    .concat(s.terminals.filter((t) => t.terminal_id !== 'OTRO').map((t) => waitRow(t.name, t)))
    .concat((s.sizes || []).map((x) => waitRow(`Eslora ${x.band}`, x)));
  const sensRow = (label, x) => `<tr><td>${esc(label)}</td><td>${x.wait_calls ?? 0}</td>` +
    `<td>${pctf(x.pct_wait)}</td><td>${pctf(x.pct_wait_3h)}</td><td>${fmtH(x.wait_median_h)}</td>` +
    `<td>${fmtH(x.wait_mean_h)}</td><td>${fmtH(x.wait_p90_h)}</td></tr>`;
  const sens = (d.sensitivity || []).map((x) => sensRow(`Regla ${x.rule}`, x)).join('');
  const c = s.containers;
  const big = (s.sizes || []).find((x) => x.band.startsWith('≥'));
  const apv = d.apv;
  const apvTable = apv ? '<tr><th>Indicador</th><th>APV ' + esc(apv.periodo) + '</th><th>AIS (este periodo)</th></tr>' +
    `<tr><td>% que fondea</td><td>${pctf(apv.pct_fondeo)}</td><td>${pctf(c.pct_anchor)} (${c.anchor_n ?? 0} de ${c.anchor_calls ?? 0})</td></tr>` +
    `<tr><td>Espera media de los que fondean</td><td>≈ ${fmtH(apv.espera_fondeo_media_h)}</td><td>${fmtH(c.anchor_mean_h)}</td></tr>` +
    `<tr><td>Buques grandes que fondean (APV: ULCS y VLCS; AIS: ≥ 300 m)</td><td>${apv.por_tamano.slice(0, 2).map((x) => pctf(x.pct_fondeo)).join(' y ')}</td>` +
    `<td>${big ? pctf(big.pct_anchor) : '—'}</td></tr>` +
    `<tr><td>Buques pequeños que fondean (APV: feeders &lt; 2.000 TEU; AIS: &lt; 150 m)</td><td>${apv.por_tamano.slice(-2).map((x) => pctf(x.pct_fondeo)).join(' y ')}</td>` +
    `<td>${pctf((s.sizes || [])[0]?.pct_anchor)}</td></tr>` : '';
  card.innerHTML = '<h2>Espera doble y comparación con la APV <span class="hint">escalas-v3 · escalas OK de las terminales de contenedores</span></h2>' +
    `<table class="stats eta">${head}${rows.join('')}</table>` +
    '<p class="method">«Esperan» = espera de ' + (mw ? `${mw} h o más` : 'más de 0 h') +
    ' (una más corta cuenta como «sin espera»). «Espera total» = de la primera parada en el área de espera (< 1 kn o «fondeado») ' +
    'hasta arrancar hacia el puerto, mientras el buque siga en el área a menos de 3,9 kn. «En fondeadero oficial» = tiempo dentro ' +
    'de los fondeaderos norte y sur de la Resolución de la APV de 10/11/2020; no depende de la zona de aproximación y por eso usa todo ' +
    'el periodo. «Merodeo lento» = horas en el área a 1–3,9 kn antes de llegar, sin pararse; es descriptivo y no se suma a la espera.</p>' +
    (sens ? '<h3>Sensibilidad del umbral <span class="hint">espera total, todas las terminales; la principal es la histéresis</span></h3>' +
      '<table class="stats eta"><tr><th>Regla</th><th>Escalas</th><th>Esperan</th><th>≥ 3 h</th><th>Mediana</th><th>Media</th><th>P90</th></tr>' +
      sensRow('Histéresis (principal)', c) + sens + '</table>' : '') +
    (apvTable ? '<h3>Comparación con la APV <span class="hint">' + esc(apv.fuente) + ' · consultado ' + esc(apv.consultado) +
      '</span></h3><table class="stats eta">' + apvTable + '</table><p class="method">' + esc(apv.nota) +
      ' Muchos buques, sobre todo los grandes, esperan a la deriva fuera de la Zona II: esa espera entra en la «espera total» ' +
      'del AIS, pero no en el «fondeo» de la APV. Con pocos días de datos, el AIS no es comparable todavía.</p>' : '');
}
