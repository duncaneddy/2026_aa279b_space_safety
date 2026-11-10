// Hand-drawn ("whiteboard marker") stroke generators.
// Every generator is seeded so a given shape renders identically on every load.
// Orbits, trajectories and data curves are NOT drawn with these; they use exact paths.

const SVGNS = 'http://www.w3.org/2000/svg';

export function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

const f = v => v.toFixed(1);

// One marker stroke from (x1,y1) to (x2,y2): slight bow, jittered ends, small overshoot.
function strokeSegment(rnd, x1, y1, x2, y2, rough) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, nx = -uy, ny = ux;
  const j = Math.min(rough * 2.2, len * 0.03);
  const over = Math.min(rough * 3, len * 0.04);
  const bow = (rnd() - 0.5) * Math.min(len * 0.025, rough * 5);
  const sx = x1 - ux * over * rnd() + (rnd() - 0.5) * j, sy = y1 - uy * over * rnd() + (rnd() - 0.5) * j;
  const ex = x2 + ux * over * rnd() + (rnd() - 0.5) * j, ey = y2 + uy * over * rnd() + (rnd() - 0.5) * j;
  const c1x = x1 + dx * (0.25 + rnd() * 0.15) + nx * bow, c1y = y1 + dy * (0.25 + rnd() * 0.15) + ny * bow;
  const c2x = x1 + dx * (0.6 + rnd() * 0.15) + nx * bow, c2y = y1 + dy * (0.6 + rnd() * 0.15) + ny * bow;
  return `M${f(sx)} ${f(sy)}C${f(c1x)} ${f(c1y)} ${f(c2x)} ${f(c2y)} ${f(ex)} ${f(ey)}`;
}

export function roughLine(x1, y1, x2, y2, { seed = 1, rough = 1, passes = 2 } = {}) {
  const rnd = mulberry32(seed);
  let d = '';
  for (let p = 0; p < passes; p++) d += strokeSegment(rnd, x1, y1, x2, y2, rough * (p ? 0.8 : 1));
  return d;
}

export function roughPolyline(pts, { seed = 1, rough = 1, passes = 1, closed = false } = {}) {
  const rnd = mulberry32(seed);
  let d = '';
  const P = closed ? [...pts, pts[0]] : pts;
  for (let p = 0; p < passes; p++)
    for (let i = 0; i < P.length - 1; i++) d += strokeSegment(rnd, P[i][0], P[i][1], P[i + 1][0], P[i + 1][1], rough);
  return d;
}

export function roughRect(x, y, w, h, { seed = 1, rough = 1, passes = 2 } = {}) {
  const rnd = mulberry32(seed);
  let d = '';
  for (let p = 0; p < passes; p++) {
    const r = rough * (p ? 0.7 : 1);
    d += strokeSegment(rnd, x, y, x + w, y, r);
    d += strokeSegment(rnd, x + w, y, x + w, y + h, r);
    d += strokeSegment(rnd, x + w, y + h, x, y + h, r);
    d += strokeSegment(rnd, x, y + h, x, y, r);
  }
  return d;
}

// Hand-drawn ellipse: wobbly radius, start/end overlap like a pen that doesn't quite close.
export function roughEllipse(cx, cy, rx, ry, { seed = 1, rough = 1, passes = 2, rot = 0 } = {}) {
  const rnd = mulberry32(seed);
  let d = '';
  const cr = Math.cos(rot), sr = Math.sin(rot);
  for (let p = 0; p < passes; p++) {
    const n = 18, start = rnd() * Math.PI * 2, overlap = 0.25 + rnd() * 0.2;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const a = start + (i / n) * (Math.PI * 2 + overlap);
      const k = 1 + (rnd() - 0.5) * 0.035 * rough;
      const ex = Math.cos(a) * rx * k, ey = Math.sin(a) * ry * k;
      pts.push([cx + ex * cr - ey * sr, cy + ex * sr + ey * cr]);
    }
    d += catmull(pts);
  }
  return d;
}

function catmull(pts) {
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${f(c1[0])} ${f(c1[1])} ${f(c2[0])} ${f(c2[1])} ${f(p2[0])} ${f(p2[1])}`;
  }
  return d;
}

export function smoothPath(pts) { return catmull(pts); }

export function roughArrow(x1, y1, x2, y2, { seed = 1, rough = 1, head = 22 } = {}) {
  const rnd = mulberry32(seed + 7);
  const a = Math.atan2(y2 - y1, x2 - x1), spread = 0.45 + (rnd() - 0.5) * 0.1;
  const h1 = [x2 - head * Math.cos(a - spread), y2 - head * Math.sin(a - spread)];
  const h2 = [x2 - head * Math.cos(a + spread), y2 - head * Math.sin(a + spread)];
  return roughLine(x1, y1, x2, y2, { seed, rough, passes: 1 }) +
    roughLine(h1[0], h1[1], x2, y2, { seed: seed + 1, rough: rough * 0.5, passes: 1 }) +
    roughLine(h2[0], h2[1], x2, y2, { seed: seed + 2, rough: rough * 0.5, passes: 1 });
}

// Underline that a presenter would scribble under a word.
export function roughUnderline(x, y, w, { seed = 1 } = {}) {
  const rnd = mulberry32(seed);
  return strokeSegment(rnd, x, y, x + w, y + (rnd() - 0.5) * 6, 1.4);
}

export function svgEl(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

export function strokePath(parent, d, { color = 'var(--ink)', width = 3, cls = '', opacity = 1, dash = null } = {}) {
  const p = svgEl('path', { d, stroke: color, 'stroke-width': width, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', pathLength: 100 }, parent);
  if (cls) p.setAttribute('class', cls);
  if (opacity !== 1) p.setAttribute('opacity', opacity);
  if (dash) { p.removeAttribute('pathLength'); p.setAttribute('stroke-dasharray', dash); }
  return p;
}

// Decorate every [data-rough] element inside root with a hand-drawn outline.
//   data-rough="box" | "ellipse" | "underline"   data-color="cardinal|lagunita|ink|gray|green"
// Uses offset geometry, which is unaffected by the stage's scale transform.
const COLORS = { ink: 'var(--ink)', cardinal: 'var(--cardinal)', lagunita: 'var(--lagunita)', sky: 'var(--sky)', gray: 'var(--gray)', green: 'var(--paloverde)', dim: 'var(--ink-35)' };

export function decorate(root) {
  root.querySelectorAll('[data-rough]:not([data-rough-done])').forEach((el, i) => {
    const host = el.offsetParent;
    if (!host) return;
    const kind = el.dataset.rough, color = COLORS[el.dataset.color || 'ink'], pad = +(el.dataset.pad || 0);
    const x = el.offsetLeft - pad, y = el.offsetTop - pad, w = el.offsetWidth + 2 * pad, h = el.offsetHeight + 2 * pad;
    const seed = hashSeed((el.dataset.roughKey || el.textContent.trim().slice(0, 40)) + kind + w.toFixed(0));
    const top = el.hasAttribute('data-rough-top');
    let layer = host.querySelector(top ? ':scope > svg.rough-layer.top' : ':scope > svg.rough-layer:not(.top)');
    if (!layer) {
      layer = svgEl('svg', { class: top ? 'rough-layer top' : 'rough-layer', width: host.offsetWidth, height: host.offsetHeight });
      if (top) { layer.style.zIndex = 5; host.append(layer); } else host.prepend(layer);
    }
    let d;
    if (kind === 'box') d = roughRect(x, y, w, h, { seed, rough: 1.2 });
    else if (kind === 'ellipse') d = roughEllipse(x + w / 2, y + h / 2, w / 2 + 14, h / 2 + 10, { seed, rough: 1.3 });
    else if (kind === 'underline') d = roughUnderline(x, y + h + 4, w, { seed }) + roughUnderline(x + 6, y + h + 10, w - 12, { seed: seed + 3 });
    const p = strokePath(layer, d, { color, width: +(el.dataset.width || 3) });
    p.dataset.roughFor = el.dataset.roughKey || '';
    el.__roughPath = p;
    el.setAttribute('data-rough-done', '');
  });
}
