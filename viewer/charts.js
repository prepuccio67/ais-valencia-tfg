/* Gráficos sencillos en SVG para el cuadro de mando (sin librerías externas).
   Reglas: marcas finas con el extremo redondeado (4 px) y la base recta, 2 px de separación entre
   segmentos apilados, rejilla discreta, una sola escala vertical, leyenda cuando hay varias series y
   etiqueta al pasar el ratón por cada marca. Los textos usan los colores de texto, nunca el de la serie. */
'use strict';

const Charts = (() => {
  const NS = 'http://www.w3.org/2000/svg';

  function svgEl(tag, attrs = {}, parent = null) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function showTip(ev, html) {
    const t = document.getElementById('tip');
    t.innerHTML = html;
    t.classList.remove('hidden');
    t.style.left = Math.min(ev.clientX + 14, window.innerWidth - t.offsetWidth - 8) + 'px';
    t.style.top = Math.min(ev.clientY + 14, window.innerHeight - t.offsetHeight - 8) + 'px';
  }
  function hideTip() { document.getElementById('tip').classList.add('hidden'); }

  // Máximo "redondo" del eje y paso de las líneas de la rejilla (4 o menos, enteros si son cuentas)
  function scale(max, integer) {
    if (!(max > 0)) max = 1;
    const raw = max / 4;
    const p = 10 ** Math.floor(Math.log10(raw));
    let step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
    if (integer) step = Math.max(1, Math.ceil(step));
    return { top: Math.ceil(max / step) * step, step };
  }

  function frame(host, height, pad) {
    host.innerHTML = '';
    const w = Math.max(host.clientWidth, 280);
    const svg = svgEl('svg', { viewBox: `0 0 ${w} ${height}`, width: w, height });
    host.appendChild(svg);
    return { svg, w, h: height, pad, iw: w - pad.l - pad.r, ih: height - pad.t - pad.b };
  }

  function yGrid(f, sc, fmt) {
    const g = svgEl('g', { class: 'axis' }, f.svg);
    for (let v = 0; v <= sc.top + 1e-9; v += sc.step) {
      const y = f.pad.t + f.ih - (v / sc.top) * f.ih;
      svgEl('line', { x1: f.pad.l, x2: f.w - f.pad.r, y1: y, y2: y, class: v === 0 ? 'base' : 'grid' }, g);
      svgEl('text', { x: f.pad.l - 6, y: y + 4, 'text-anchor': 'end' }, g).textContent = fmt(v);
    }
  }

  // Columna con el extremo de datos redondeado y la base recta
  function colPath(x, y, w, h, round) {
    const r = round ? Math.min(4, w / 2, h) : 0;
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  // Barra horizontal: base recta a la izquierda y extremo de datos redondeado a la derecha
  function barPath(x, y, w, h) {
    const r = Math.min(4, h / 2, w);
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}` +
      `Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  function legend(host, series) {
    const d = document.createElement('div');
    d.className = 'legend';
    for (const s of series) {
      const it = document.createElement('span');
      it.innerHTML = `<i style="background:${s.color}"></i>${s.label}`;
      d.appendChild(it);
    }
    host.prepend(d);
  }

  function empty(host, text) { host.innerHTML = `<div class="empty">${text}</div>`; }

  /* Serie temporal (una sola línea): xs en ms, ys números. Línea de 2 px, área suave y cruz al pasar. */
  function line(host, { xs, ys, color, fmtX, fmtTip, height = 200 }) {
    if (!xs.length) return empty(host, 'Sin datos en este periodo.');
    const f = frame(host, height, { l: 34, r: 10, t: 8, b: 24 });
    const sc = scale(Math.max(...ys), true);
    yGrid(f, sc, (v) => v);
    const x0 = xs[0], x1 = xs[xs.length - 1] || x0 + 1;
    const X = (x) => f.pad.l + ((x - x0) / (x1 - x0 || 1)) * f.iw;
    const Y = (y) => f.pad.t + f.ih - (y / sc.top) * f.ih;
    let d = '';
    xs.forEach((x, i) => { d += (i ? 'H' : 'M') + X(x) + (i ? 'V' : ',') + Y(ys[i]); });   // escalones: es una cuenta
    svgEl('path', { d: `${d}V${Y(0)}H${X(x0)}Z`, fill: color, opacity: 0.12 }, f.svg);
    svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round' }, f.svg);
    const ax = svgEl('g', { class: 'axis' }, f.svg);
    const n = Math.max(2, Math.floor(f.iw / 110));
    for (let i = 0; i <= n; i++) {
      const x = x0 + ((x1 - x0) * i) / n;
      svgEl('text', { x: X(x), y: f.h - 6, 'text-anchor': i === 0 ? 'start' : i === n ? 'end' : 'middle' }, ax)
        .textContent = fmtX(x);
    }
    const cross = svgEl('line', { y1: f.pad.t, y2: f.pad.t + f.ih, stroke: '#6b7280', 'stroke-dasharray': '3 3',
      visibility: 'hidden' }, f.svg);
    const dot = svgEl('circle', { r: 4.5, fill: color, stroke: '#fff', 'stroke-width': 2, visibility: 'hidden' }, f.svg);
    const hit = svgEl('rect', { x: f.pad.l, y: f.pad.t, width: f.iw, height: f.ih, class: 'hit' }, f.svg);
    hit.addEventListener('mousemove', (ev) => {
      const box = f.svg.getBoundingClientRect();
      const px = ((ev.clientX - box.left) / box.width) * f.w;
      const t = x0 + ((px - f.pad.l) / f.iw) * (x1 - x0);
      let i = xs.findIndex((x) => x > t) - 1;
      if (i < 0) i = t < x0 ? 0 : xs.length - 1;
      cross.setAttribute('x1', X(xs[i])); cross.setAttribute('x2', X(xs[i]));
      dot.setAttribute('cx', X(xs[i])); dot.setAttribute('cy', Y(ys[i]));
      cross.setAttribute('visibility', 'visible'); dot.setAttribute('visibility', 'visible');
      showTip(ev, fmtTip(i));
    });
    hit.addEventListener('mouseleave', () => {
      cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip();
    });
  }

  /* Barras horizontales: rows = [{label, value, mark, color, tip}]. 'mark' es una raya (p. ej. el p90). */
  function hbars(host, rows, { fmt }) {
    const shown = rows.filter((r) => r.value != null);
    if (!shown.length) return empty(host, 'Todavía no hay escalas completas (OK) en este periodo.');
    const rowH = 34;
    const f = frame(host, shown.length * rowH + 22, { l: 150, r: 70, t: 4, b: 18 });
    const sc = scale(Math.max(...shown.map((r) => Math.max(r.value, r.mark || 0))), false);
    const X = (v) => f.pad.l + (v / sc.top) * f.iw;
    const ax = svgEl('g', { class: 'axis' }, f.svg);
    const labelEvery = Math.ceil(56 / ((sc.step / sc.top) * f.iw));   // etiquetas separadas al menos 56 px
    for (let v = 0, i = 0; v <= sc.top + 1e-9; v += sc.step, i++) {
      svgEl('line', { x1: X(v), x2: X(v), y1: f.pad.t, y2: f.h - f.pad.b, class: v === 0 ? 'base' : 'grid' }, ax);
      if (i % labelEvery === 0) {
        svgEl('text', { x: X(v), y: f.h - 4, 'text-anchor': 'middle' }, ax).textContent = fmt(v);
      }
    }
    shown.forEach((r, i) => {
      const y = f.pad.t + i * rowH + 7, bh = 18, w = Math.max(X(r.value) - X(0), 1);
      svgEl('text', { x: f.pad.l - 8, y: y + 13, 'text-anchor': 'end', class: 'val' }, f.svg).textContent = r.label;
      const g = svgEl('g', {}, f.svg);
      svgEl('path', { d: barPath(X(0), y, w, bh), fill: r.color }, g);
      if (r.mark != null) {
        svgEl('line', { x1: X(r.mark), x2: X(r.mark), y1: y - 3, y2: y + bh + 3, stroke: '#1f2933', 'stroke-width': 2 }, g);
      }
      svgEl('text', { x: Math.max(X(r.value), X(r.mark || 0)) + 8, y: y + 13, class: 'val' }, g).textContent = fmt(r.value);
      const hit = svgEl('rect', { x: 0, y: y - 6, width: f.w, height: rowH, class: 'hit' }, g);
      hit.addEventListener('mousemove', (ev) => showTip(ev, r.tip));
      hit.addEventListener('mouseleave', hideTip);
    });
  }

  /* Columnas apiladas: cats = etiquetas del eje, series = [{key, label, color}], value(cat, key). */
  function stacked(host, { cats, series, value, fmtCat, tipFn, height = 210 }) {
    const totals = cats.map((c) => series.reduce((a, s) => a + (value(c, s.key) || 0), 0));
    if (!cats.length || !Math.max(0, ...totals)) return empty(host, 'Sin datos en este periodo.');
    const f = frame(host, height, { l: 30, r: 8, t: 8, b: 30 });
    const sc = scale(Math.max(...totals), true);
    yGrid(f, sc, (v) => v);
    const slot = f.iw / cats.length, bw = Math.min(24, slot * 0.7);
    const Y = (v) => (v / sc.top) * f.ih;
    const every = Math.ceil(cats.length / Math.max(1, Math.floor(f.iw / 46)));
    cats.forEach((c, i) => {
      const x = f.pad.l + i * slot + (slot - bw) / 2;
      let base = f.pad.t + f.ih;
      const parts = series.filter((s) => value(c, s.key) > 0);
      parts.forEach((s, j) => {
        const h = Y(value(c, s.key));
        const gap = j > 0 ? 2 : 0;                       // 2 px de separación entre segmentos
        svgEl('path', { d: colPath(x, base - h, bw, Math.max(h - gap, 0.5), j === parts.length - 1),
          fill: s.color }, f.svg);
        base -= h;
      });
      if (i % every === 0) {
        svgEl('text', { x: x + bw / 2, y: f.h - 12, 'text-anchor': 'middle', class: 'lbl' }, f.svg)
          .textContent = fmtCat(c);
      }
      const hit = svgEl('rect', { x: f.pad.l + i * slot, y: f.pad.t, width: slot, height: f.ih, class: 'hit' }, f.svg);
      hit.addEventListener('mousemove', (ev) => showTip(ev, tipFn(c, totals[i])));
      hit.addEventListener('mouseleave', hideTip);
    });
    if (series.length > 1) legend(host, series);
  }

  return { line, hbars, stacked, showTip, hideTip };
})();
