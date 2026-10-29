/* Editor de zonas (Fase 5): crear, editar, activar y desactivar zonas.
   Tres formas de definir la geometría: coordenadas en texto (rectángulo o lista de
   puntos), importar GeoJSON y dibujar con el ratón (con vértices arrastrables).
   Usa el mapa, el estado S y las utilidades de app.js. */
'use strict';

const Z = { form: null, method: 'rect', draft: null, draftLayer: null, vertexLayer: null, drawing: null };
//  Z.draft = { type: 'Rectangle' | 'Polygon', ring: [[lat, lon], ...] }   (sin repetir el primer punto)

// ------------------------------------------------------------------ envío a la API
async function apiSend(method, path, body) {
  const r = await fetch(new URL(path, location.origin), {
    method, headers: { Authorization: 'Bearer ' + S.token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ------------------------------------------------------------------ geometría
function areaKm2(ring) {                 // aproximación plana, suficiente para áreas de pocos km
  if (ring.length < 3) return 0;
  const lat0 = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  let a = 0;
  for (let i = 0; i < ring.length; i++) {
    const [y1, x1] = ring[i], [y2, x2] = ring[(i + 1) % ring.length];
    a += x1 * k * 111.32 * y2 * 110.57 - x2 * k * 111.32 * y1 * 110.57;
  }
  return Math.abs(a) / 2;
}
const rectRing = (n, s, e, w) => [[s, w], [s, e], [n, e], [n, w]];
function bboxOf(ring) {
  const lats = ring.map((p) => p[0]), lons = ring.map((p) => p[1]);
  return { north: Math.max(...lats), south: Math.min(...lats), east: Math.max(...lons), west: Math.min(...lons) };
}
const fmtNum = (x) => Number(x.toFixed(5));

function parsePoints(text) {
  /* Una línea por vértice: "latitud, longitud". Si se usa ';' como separador, se aceptan
     decimales con coma (39,45; -0,33). */
  const pts = [];
  text.split(/\r?\n/).forEach((line, i) => {
    const t = line.trim();
    if (!t || t.startsWith('#')) return;
    const parts = t.includes(';') ? t.split(';').map((x) => x.replace(',', '.')) : t.split(/[,\s]+/);
    const nums = parts.map((x) => x.trim()).filter(Boolean).map(Number);
    if (nums.length !== 2 || nums.some(Number.isNaN)) throw new Error(`línea ${i + 1}: escribe "latitud, longitud"`);
    pts.push(nums);
  });
  if (pts.length && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) pts.pop();
  if (pts.length < 3) throw new Error('hacen falta al menos 3 vértices');
  return pts;
}

function parseGeoJSON(text) {
  let g = JSON.parse(text);
  if (g.type === 'FeatureCollection') {
    const polys = (g.features || []).filter((f) => f.geometry && f.geometry.type === 'Polygon');
    if (polys.length !== 1) throw new Error('la FeatureCollection debe tener exactamente un polígono');
    g = polys[0].geometry;
  } else if (g.type === 'Feature') g = g.geometry;
  if (!g || g.type !== 'Polygon') throw new Error('debe ser un Polygon (GeoJSON usa [longitud, latitud])');
  const ring = g.coordinates[0].map(([lon, lat]) => [lat, lon]);
  if (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring.pop();
  return ring;
}

// ------------------------------------------------------------------ borrador sobre el mapa
function clearDraft() {
  for (const l of [Z.draftLayer, Z.vertexLayer]) if (l) map.removeLayer(l);
  Z.draftLayer = Z.vertexLayer = null;
}

function setDraft(type, ring, fit = true) {
  Z.draft = { type, ring: ring.map((p) => [fmtNum(p[0]), fmtNum(p[1])]) };
  drawDraft(fit);
  syncFields();
}

function drawDraft(fit = false) {
  clearDraft();
  if (!Z.draft) return;
  Z.draftLayer = L.polygon(Z.draft.ring, { color: '#e67e22', weight: 2, fillOpacity: 0.08 }).addTo(map);
  if (Z.method === 'draw') {                      // vértices arrastrables para editar con el ratón
    Z.vertexLayer = L.layerGroup().addTo(map);
    Z.draft.ring.forEach((p, i) => {
      const m = L.marker(p, { draggable: true, icon: L.divIcon({ className: 'vertex-icon', iconSize: [10, 10] }) });
      m.on('drag', (e) => {
        const ll = e.target.getLatLng();
        if (Z.draft.type === 'Rectangle') {        // en un rectángulo se mueve la esquina y sus vecinas
          const opp = Z.draft.ring[(i + 2) % 4];
          Z.draft.ring = rectRing(Math.max(ll.lat, opp[0]), Math.min(ll.lat, opp[0]),
            Math.max(ll.lng, opp[1]), Math.min(ll.lng, opp[1]));
        } else Z.draft.ring[i] = [ll.lat, ll.lng];
        Z.draftLayer.setLatLngs(Z.draft.ring);
      });
      m.on('dragend', () => setDraft(Z.draft.type, Z.draft.ring, false));
      m.on('contextmenu', () => {                 // clic derecho: borrar vértice (mínimo 3)
        if (Z.draft.type !== 'Polygon' || Z.draft.ring.length <= 3) return;
        Z.draft.ring.splice(i, 1);
        setDraft('Polygon', Z.draft.ring, false);
      });
      m.bindTooltip(Z.draft.type === 'Polygon' ? 'Arrastra · clic derecho borra' : 'Arrastra la esquina');
      m.addTo(Z.vertexLayer);
    });
  }
  // se encuadra en la parte del mapa que no tapa el panel del editor (a la derecha)
  if (fit) map.fitBounds(Z.draftLayer.getBounds(), { paddingTopLeft: [30, 30], paddingBottomRight: [460, 30], maxZoom: 13 });
}

// Copia el borrador a los campos de texto, para que las cuatro formas muestren lo mismo
function syncFields() {
  const f = Z.form;
  if (!f || !Z.draft) return;
  const b = bboxOf(Z.draft.ring);
  for (const k of ['north', 'south', 'east', 'west']) f[k].value = fmtNum(b[k]);
  f.points.value = Z.draft.ring.map((p) => `${p[0]}, ${p[1]}`).join('\n');
  const coords = Z.draft.ring.concat([Z.draft.ring[0]]).map(([lat, lon]) => [lon, lat]);
  f.geojson.value = JSON.stringify({ type: 'Polygon', coordinates: [coords] });
  f.info.textContent = `${Z.draft.type === 'Rectangle' ? 'Rectángulo' : 'Polígono'} · ` +
    `${Z.draft.ring.length} vértices · unos ${areaKm2(Z.draft.ring).toFixed(1)} km²`;
}

// ------------------------------------------------------------------ dibujo con el ratón
function stopDrawing() {
  if (!Z.drawing) return;
  map.off('click', onDrawClick);
  map.off('dblclick', finishPolygon);
  map.doubleClickZoom.enable();
  map.getContainer().style.cursor = '';
  if (Z.drawing.preview) map.removeLayer(Z.drawing.preview);
  Z.drawing = null;
}

function startDrawing(kind) {
  stopDrawing();
  clearDraft();
  Z.drawing = { kind, pts: [], preview: null };
  map.on('click', onDrawClick);
  if (kind === 'poly') { map.doubleClickZoom.disable(); map.on('dblclick', finishPolygon); }
  map.getContainer().style.cursor = 'crosshair';
  message(kind === 'rect' ? 'Pulsa en el mapa dos esquinas opuestas del rectángulo.'
    : 'Pulsa en el mapa cada vértice. Doble clic (o «Terminar polígono») para cerrarlo.');
}

function onDrawClick(e) {
  const d = Z.drawing;
  d.pts.push([e.latlng.lat, e.latlng.lng]);
  if (d.kind === 'rect' && d.pts.length === 2) {
    const [a, b] = d.pts;
    stopDrawing();
    setDraft('Rectangle', rectRing(Math.max(a[0], b[0]), Math.min(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[1], b[1])), false);
    message('Rectángulo dibujado. Puedes arrastrar sus esquinas para ajustarlo.');
    return;
  }
  if (d.preview) map.removeLayer(d.preview);
  d.preview = L.polyline(d.pts, { color: '#e67e22', dashArray: '4 4' }).addTo(map);
}

function finishPolygon() {
  const d = Z.drawing;
  if (!d || d.kind !== 'poly') return;
  // el doble clic añade dos clics: se quitan los puntos repetidos del final
  const pts = d.pts.filter((p, i) => i === 0 || p[0] !== d.pts[i - 1][0] || p[1] !== d.pts[i - 1][1]);
  if (pts.length < 3) { message('Hacen falta al menos 3 vértices.', true); return; }
  stopDrawing();
  setDraft('Polygon', pts, false);
  message('Polígono dibujado. Arrastra los vértices para ajustarlo; clic derecho sobre uno lo borra.');
}

// ------------------------------------------------------------------ panel: lista de zonas
function message(text, error = false) {
  const box = Z.form && Z.form.msg;
  if (!box) return;
  box.textContent = text;
  box.className = 'msg' + (error ? ' err' : '');
  box.classList.toggle('hidden', !text);
}

function closeEditor() {
  stopDrawing();
  clearDraft();
  Z.form = null;
  Z.draft = null;
  $('zonePanel').classList.add('hidden');
}

function showZoneList() {
  stopDrawing();
  clearDraft();
  Z.form = null;
  const rows = Object.values(S.zones).map((z) => {
    const ring = z.geometry.coordinates[0].slice(0, -1).map(([lon, lat]) => [lat, lon]);
    return el('tr', {},
      el('td', {}, el('b', { text: z.name }), el('div', { class: 'hint', text: `${z.zone_id} · ${z.geometry_type} · ${areaKm2(ring).toFixed(0)} km²` })),
      el('td', {}, el('span', { class: 'badge ' + (z.active ? 'on' : 'off'), text: z.active ? 'activa' : 'inactiva' })),
      el('td', {},
        el('button', { text: 'Editar', onclick: () => showEditor(z) }), ' ',
        el('button', { text: z.active ? 'Desactivar' : 'Activar', onclick: () => toggleActive(z) })));
  });
  $('zonePanel').replaceChildren(
    el('h3', {}, el('span', { text: 'Zonas' }), el('button', { text: '✕', onclick: closeEditor })),
    el('p', { class: 'hint', text: 'Una zona desactivada deja de capturar pero conserva todo su histórico, que se puede seguir consultando.' }),
    el('table', {}, ...rows),
    el('button', { class: 'primary', text: '+ Nueva zona', onclick: () => showEditor(null) }));
  $('zonePanel').classList.remove('hidden');
}

async function toggleActive(z) {
  const msg = z.active
    ? `¿Desactivar ${z.name}?\n\nDejará de capturar datos. Lo ya guardado se conserva y el periodo quedará registrado como hueco «zone_disabled».`
    : `¿Activar ${z.name}? Empezará a capturar datos de nuevo.`;
  if (!confirm(msg)) return;
  try {
    await apiSend('POST', `/api/zones/${z.zone_id}/${z.active ? 'deactivate' : 'activate'}`);
    $('zonePanel').replaceChildren(el('p', { text: 'Aplicando el cambio: el Collector se está recargando…' }));
    await reloadAfterZoneChange(z.zone_id);
    showZoneList();
  } catch (e) { alert('No se pudo cambiar la zona: ' + e.message); }
}

// ------------------------------------------------------------------ panel: formulario
function showEditor(zone) {
  const isNew = !zone;
  const f = {};
  const input = (name, attrs = {}) => (f[name] = el('input', { type: 'text', ...attrs }));
  for (const k of ['north', 'south', 'east', 'west']) f[k] = el('input', { type: 'number', step: 'any' });
  f.points = el('textarea', { placeholder: '39.30, -0.33\n39.30, -0.28\n39.36, -0.28\n39.36, -0.33' });
  f.geojson = el('textarea', { placeholder: '{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}' });
  f.file = el('input', { type: 'file', accept: '.geojson,.json' });
  f.info = el('div', { class: 'hint' });
  f.msg = el('div', { class: 'msg hidden' });
  f.src = {};
  const tabsBox = el('div', { class: 'tabs' });
  const pane = el('div');
  Z.form = f;
  Z.method = zone && zone.geometry_type === 'Polygon' ? 'points' : 'rect';

  const panes = {
    rect: () => el('div', {},
      el('p', { class: 'hint', text: 'Coordenadas en grados decimales (latitud norte/sur, longitud este/oeste; oeste de Greenwich en negativo).' }),
      el('div', { class: 'grid4' },
        el('div', {}, el('label', { class: 'f', text: 'Norte (latitud)' }), f.north),
        el('div', {}, el('label', { class: 'f', text: 'Sur (latitud)' }), f.south),
        el('div', {}, el('label', { class: 'f', text: 'Oeste (longitud)' }), f.west),
        el('div', {}, el('label', { class: 'f', text: 'Este (longitud)' }), f.east)),
      el('div', { class: 'row' }, el('button', { text: 'Ver en el mapa', onclick: previewRect }))),
    points: () => el('div', {},
      el('p', { class: 'hint', text: 'Una línea por vértice: «latitud, longitud» (como en Google Maps). No hace falta repetir el primero.' }),
      f.points, el('div', { class: 'row' }, el('button', { text: 'Ver en el mapa', onclick: previewPoints }))),
    geojson: () => el('div', {},
      el('p', { class: 'hint', text: 'Pega un Polygon, Feature o FeatureCollection GeoJSON (orden [longitud, latitud]) o elige un archivo .geojson.' }),
      f.geojson, f.file, el('div', { class: 'row' }, el('button', { text: 'Ver en el mapa', onclick: previewGeoJSON }))),
    draw: () => el('div', {},
      el('p', { class: 'hint', text: 'Dibuja con el ratón. Después puedes arrastrar los vértices; con clic derecho se borra un vértice del polígono.' }),
      el('div', { class: 'row' },
        el('button', { text: '▭ Rectángulo (2 clics)', onclick: () => startDrawing('rect') }),
        el('button', { text: '⬠ Polígono', onclick: () => startDrawing('poly') }),
        el('button', { text: 'Terminar polígono', onclick: finishPolygon }))),
  };
  const labels = { rect: 'Rectángulo', points: 'Lista de puntos', geojson: 'GeoJSON', draw: 'Dibujar con el ratón' };
  function selectTab(m) {
    stopDrawing();
    Z.method = m;
    tabsBox.replaceChildren(...Object.keys(labels).map((k) =>
      el('button', { class: k === m ? 'sel' : '', text: labels[k], onclick: () => selectTab(k) })));
    pane.replaceChildren(panes[m]());
    syncFields();
    drawDraft(false);
  }
  f.file.addEventListener('change', async () => {
    const file = f.file.files[0];
    if (file) { f.geojson.value = await file.text(); previewGeoJSON(); }
  });

  $('zonePanel').replaceChildren(
    el('h3', {}, el('span', { text: isNew ? 'Nueva zona' : `Editar ${zone.zone_id}` }),
      el('button', { text: '← Zonas', onclick: showZoneList })),
    el('label', { class: 'f', text: 'Identificador (mayúsculas, números y guiones; no se puede cambiar después)' }),
    input('zone_id', isNew ? { placeholder: 'p. ej. SAGUNTO' } : { value: zone.zone_id, disabled: '' }),
    el('label', { class: 'f', text: 'Nombre' }), input('name', { value: zone ? zone.name : '' }),
    el('label', { class: 'f', text: 'Descripción' }), input('description', { value: zone ? zone.description : '' }),
    el('label', { class: 'f', text: 'Fuentes AIS' }),
    el('div', {}, ...['openseafeed', 'aisstream'].map((s) => {
      f.src[s] = el('input', { type: 'checkbox' });
      f.src[s].checked = !zone || zone.sources.includes(s);
      return el('label', { style: 'margin-right:12px' }, f.src[s], ` ${s}`);
    })),
    el('label', { class: 'f', text: 'Geometría' }), tabsBox, pane, f.info, f.msg,
    el('div', { class: 'row' },
      el('button', { class: 'primary', text: isNew ? 'Crear zona' : 'Guardar cambios', onclick: () => save(zone) }),
      el('button', { text: 'Cancelar', onclick: showZoneList })));
  selectTab(Z.method);
  Z.orig = null;
  if (zone) {
    const ring = zone.geometry.coordinates[0].slice(0, -1).map(([lon, lat]) => [lat, lon]);
    setDraft(zone.geometry_type, ring);
    Z.orig = JSON.stringify(Z.draft.ring);         // para saber si la geometría ha cambiado
  }
}

function previewRect() {
  const f = Z.form;
  const keys = ['north', 'south', 'east', 'west'];
  if (keys.some((k) => f[k].value.trim() === '' || Number.isNaN(Number(f[k].value)))) {
    message('Rellena las cuatro coordenadas con números.', true); return;
  }
  const [n, s, e, w] = keys.map((k) => Number(f[k].value));
  if (!(s < n && w < e)) { message('Norte debe ser mayor que sur y este mayor que oeste.', true); return; }
  setDraft('Rectangle', rectRing(n, s, e, w));
  message('');
}

function previewPoints() {
  try { setDraft('Polygon', parsePoints(Z.form.points.value)); message(''); } catch (e) { message(e.message, true); }
}

function previewGeoJSON() {
  try { setDraft('Polygon', parseGeoJSON(Z.form.geojson.value)); message(''); } catch (e) { message('GeoJSON: ' + e.message, true); }
}

async function save(zone) {
  const f = Z.form;
  if (!Z.draft) { message('Primero define la geometría y pulsa «Ver en el mapa» (o dibújala).', true); return; }
  const sources = Object.keys(f.src).filter((s) => f.src[s].checked);
  const body = { name: f.name.value.trim(), description: f.description.value.trim(), sources };
  if (Z.draft.type === 'Rectangle') {
    body.geometry_type = 'Rectangle';
    body.bbox = bboxOf(Z.draft.ring);
  } else {
    body.geometry_type = 'Polygon';
    const coords = Z.draft.ring.concat([Z.draft.ring[0]]).map(([lat, lon]) => [lon, lat]);
    body.geometry = { type: 'Polygon', coordinates: [coords] };
  }
  if (!zone) body.zone_id = f.zone_id.value.trim().toUpperCase();
  if (zone && JSON.stringify(Z.draft.ring) !== Z.orig &&
      !confirm('Vas a cambiar la geometría de una zona que ya tiene datos.\n\nLo capturado hasta ahora no cambia; ' +
               'desde ahora se capturará el área nueva y el cambio quedará registrado. ¿Continuar?')) return;
  try {
    message('Guardando…');
    const r = zone ? await apiSend('PUT', `/api/zones/${zone.zone_id}`, body) : await apiSend('POST', '/api/zones', body);
    message('Guardado. El Collector se está recargando para aplicarlo…');
    stopDrawing();
    await reloadAfterZoneChange(r.zone.zone_id);
    showZoneList();
  } catch (e) { message('No se pudo guardar: ' + e.message, true); }
}

$('zonesBtn').addEventListener('click', () => {
  if ($('zonePanel').classList.contains('hidden')) showZoneList(); else closeEditor();
});
