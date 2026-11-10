// Figures: every renderer draws from deck/data/*.json produced by scripts/*.py.
// Hand-drawn strokes (sketch.js) for frames, axes and diagrams; exact paths for orbits and data.
import { roughLine, roughRect, roughEllipse, roughArrow, roughPolyline, svgEl, strokePath, hashSeed, mulberry32 } from './sketch.js';

export const DATA_FILES = ['avoidance_budget', 'rideshare_tracks', 'catalog', 'debris_clouds', 'ssn_sensors', 'tle_gotchas', 'starlink_vs_gp', 'gps_od',
  'covariance_banana', 'screening', 'pc', 'maneuver', 'pc_evolution', 'land'];

const EASE_IN = 'cubic-bezier(.2,.7,.2,1)';
const EASE_MOVE = 'cubic-bezier(.65,0,.25,1)';
const FILL = { fill: 'both' };
const C = { ink: '#2E2D29', cardinal: '#8C1515', lagunita: '#006CB8', sky: '#0098DB', green: '#279989', gray: '#9A9A9A', board: '#FAF8F3' };
const R_EARTH = 6378.137;

/* ======================= helpers ======================= */

const fmtInt = v => Math.round(v).toLocaleString('en-US');
const fmt = (v, d = 1) => Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const sup = n => String(n).replace(/-/g, '−').split('').map(c => '⁰¹²³⁴⁵⁶⁷⁸⁹'['0123456789'.indexOf(c)] ?? (c === '−' ? '⁻' : c)).join('');
const pow10 = e => `10${sup(e)}`;
const sci = (v, digits = 2) => v.toExponential(digits).replace(/e([-+]\d+)/, (m, e) => ` × 10${sup(+e)}`);
const median = a => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN; };

function svgFor(el) {
  const w = el.offsetWidth, h = el.offsetHeight;
  return svgEl('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}` }, el);
}

function text(parent, x, y, str, { size = 24, color = C.ink, anchor = 'start', weight = 400, family = 'var(--sans)', italic = false, cls = '', opacity = 1, baseline = 'alphabetic' } = {}) {
  const t = svgEl('text', { x, y, 'font-size': size, fill: color, 'text-anchor': anchor, 'font-weight': weight, 'font-family': family, 'dominant-baseline': baseline }, parent);
  if (italic) t.setAttribute('font-style', 'italic');
  if (cls) t.setAttribute('class', cls);
  if (opacity !== 1) t.setAttribute('opacity', opacity);
  t.textContent = str;
  return t;
}

function linPath(pts) { return pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(''); }

function exactPath(parent, pts, { color = C.ink, width = 3, opacity = 1, dash = null, fill = 'none', closed = false } = {}) {
  const p = svgEl('path', { d: linPath(pts) + (closed ? 'Z' : ''), stroke: color, 'stroke-width': width, fill, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, parent);
  if (!dash) p.setAttribute('pathLength', 100); else p.setAttribute('stroke-dasharray', dash);
  if (opacity !== 1) p.setAttribute('opacity', opacity);
  return p;
}

const scaleLin = (d0, d1, r0, r1) => v => r0 + (v - d0) / (d1 - d0) * (r1 - r0);
const scaleLog = (d0, d1, r0, r1) => v => r0 + (Math.log10(Math.max(v, 1e-300)) - Math.log10(d0)) / (Math.log10(d1) - Math.log10(d0)) * (r1 - r0);

function niceTicks(a, b, n = 5) {
  const span = b - a, step0 = Math.pow(10, Math.floor(Math.log10(span / n)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * step0).find(s => span / s <= n) || step0 * 10;
  const out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

// Axes with hand-drawn lines, exact tick placement. Returns {x, y, g, box}.
function axes(svg, { left = 110, right = 30, top = 20, bottom = 80, xr, yr, xlog = false, ylog = false, xlabel = '', ylabel = '', xticks, yticks, xfmt = v => v, yfmt = v => v, seed = 1 }) {
  const W = +svg.getAttribute('width'), H = +svg.getAttribute('height');
  const x0 = left, x1 = W - right, y0 = H - bottom, y1 = top;
  const x = (xlog ? scaleLog : scaleLin)(xr[0], xr[1], x0, x1);
  const y = (ylog ? scaleLog : scaleLin)(yr[0], yr[1], y0, y1);
  const g = svgEl('g', { class: 'axes' }, svg);
  strokePath(g, roughLine(x0 - 6, y0, x1 + 10, y0, { seed, rough: 0.8 }), { color: 'rgba(46,45,41,.55)', width: 2.2 });
  strokePath(g, roughLine(x0, y0 + 6, x0, y1 - 10, { seed: seed + 1, rough: 0.8 }), { color: 'rgba(46,45,41,.55)', width: 2.2 });
  const xt = xticks || (xlog ? decades(xr) : niceTicks(xr[0], xr[1]));
  const yt = yticks || (ylog ? decades(yr) : niceTicks(yr[0], yr[1]));
  xt.forEach(v => { const px = x(v); svgEl('line', { x1: px, x2: px, y1: y0, y2: y0 + 8, stroke: 'rgba(46,45,41,.45)', 'stroke-width': 2 }, g); text(g, px, y0 + 36, xfmt(v), { size: 22, anchor: 'middle', color: 'rgba(46,45,41,.6)' }); });
  yt.forEach(v => { const py = y(v); svgEl('line', { x1: x0 - 8, x2: x0, y1: py, y2: py, stroke: 'rgba(46,45,41,.45)', 'stroke-width': 2 }, g); text(g, x0 - 14, py + 8, yfmt(v), { size: 22, anchor: 'end', color: 'rgba(46,45,41,.6)' }); });
  if (xlabel) text(g, (x0 + x1) / 2, H - 14, xlabel, { size: 24, anchor: 'middle', color: 'rgba(46,45,41,.7)' });
  if (ylabel) { const t = text(g, 0, 0, ylabel, { size: 24, anchor: 'middle', color: 'rgba(46,45,41,.7)' }); t.setAttribute('transform', `translate(${22} ${(y0 + y1) / 2}) rotate(-90)`); }
  return { x, y, g, box: { x0, x1, y0, y1 } };
}

function decades([a, b]) {
  const out = [];
  for (let e = Math.ceil(Math.log10(Math.min(a, b)) - 1e-9); e <= Math.floor(Math.log10(Math.max(a, b)) + 1e-9); e++) out.push(Math.pow(10, e));
  return out;
}

function drawOnAnim(paths, A, delay = 0, dur = 1300, stagger = 120) {
  paths.forEach((p, i) => {
    if (!p) return;
    if (!p.hasAttribute('pathLength')) { A.push(p.animate([{ opacity: 0 }, { opacity: +(p.getAttribute('opacity') ?? 1) }], { duration: dur, delay: delay + i * stagger, easing: EASE_IN, ...FILL })); return; }
    p.style.strokeDasharray = '100';
    A.push(p.animate([{ strokeDashoffset: 100 }, { strokeDashoffset: 0 }], { duration: dur, delay: delay + i * stagger, easing: 'cubic-bezier(.45,0,.3,1)', ...FILL }));
  });
}
const fadeIn = (el, A, delay = 0, dur = 600) => el && A.push(el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: dur, delay, easing: EASE_IN, ...FILL }));
const popIn = (el, A, delay = 0) => el && A.push(el.animate([{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'scale(1.08)', offset: .7 }, { opacity: 1, transform: 'none' }], { duration: 600, delay, easing: EASE_IN, ...FILL }));

// rAF loop with cancel; fn(tMs) returns false to stop.
function loop(fn) {
  let raf, t0;
  const tick = t => { t0 ??= t; if (fn(t - t0) !== false) raf = requestAnimationFrame(tick); };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

function rollNumber(el, from, to, { duration = 1600, delay = 0, log = false, format = fmtInt } = {}) {
  return loop(t => {
    const p = Math.min(1, Math.max(0, (t - delay) / duration)), e = 1 - Math.pow(1 - p, 3);
    const v = log ? Math.pow(10, Math.log10(from) + (Math.log10(to) - Math.log10(from)) * e) : from + (to - from) * e;
    el.textContent = format(v);
    return p < 1;
  });
}

// Orthographic view of ECI points: yaw about z, then tilt toward the viewer.
function projector(cx, cy, kmPerPx, yawDeg = 30, tiltDeg = 22) {
  const yaw = yawDeg * Math.PI / 180, t = tiltDeg * Math.PI / 180, cyw = Math.cos(yaw), syw = Math.sin(yaw), ct = Math.cos(t), st = Math.sin(t);
  return ([x, y, z]) => {
    const x1 = x * cyw - y * syw, y1 = x * syw + y * cyw;
    const y2 = y1 * ct - z * st, z2 = y1 * st + z * ct;
    return [cx + x1 / kmPerPx, cy - z2 / kmPerPx, y2];
  };
}
const hidden = (p, cx, cy, rpx) => p[2] > 0 && Math.hypot(p[0] - cx, p[1] - cy) < rpx;

function earth(svg, cx, cy, r, seed = 11) {
  svgEl('circle', { cx, cy, r, fill: 'rgba(0,108,184,0.05)' }, svg);
  return strokePath(svg, roughEllipse(cx, cy, r, r, { seed, rough: 0.7 }), { color: C.ink, width: 2.6 });
}

function canvasFor(el) {
  const w = el.offsetWidth, h = el.offsetHeight, dpr = 2;
  const cv = document.createElement('canvas');
  cv.width = w * dpr; cv.height = h * dpr; cv.style.width = `${w}px`; cv.style.height = `${h}px`;
  el.appendChild(cv);
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  return { cv, ctx, w, h };
}

function legend(svg, x, y, items, { size = 24, gap = 40 } = {}) {
  items.forEach(([label, color, kind = 'line'], i) => {
    const yy = y + i * gap;
    if (kind === 'dot') svgEl('circle', { cx: x + 12, cy: yy - 8, r: 7, fill: color }, svg);
    else if (kind === 'band') svgEl('rect', { x, y: yy - 18, width: 26, height: 18, fill: color, opacity: 0.25 }, svg);
    else svgEl('line', { x1: x, x2: x + 28, y1: yy - 8, y2: yy - 8, stroke: color, 'stroke-width': 4, 'stroke-linecap': 'round' }, svg);
    text(svg, x + 40, yy, label, { size, color: C.ink });
  });
}

// Call fn when the slide reaches `step` by a click; returns a cleanup function.
function onStep(el, step, fn) {
  const sec = el.closest('section');
  const h = e => { if (e.detail.step === step && e.detail.animate) fn(); };
  sec.addEventListener('deckstep', h);
  return () => sec.removeEventListener('deckstep', h);
}

/* ======================= data bindings ======================= */

export const binds = {
  'collision.speed': d => fmt(d.debris_clouds.collision.rel_speed_kms, 1),
  'collision.alt': d => fmtInt(d.debris_clouds.collision.alt_km ?? Math.hypot(...d.debris_clouds.collision.position_km ?? [0]) - R_EARTH),
  'collision.angle': d => fmtInt(d.debris_clouds.collision.crossing_angle_deg),
  'debris.cataloged': d => fmtInt(d.debris_clouds.groups.reduce((s, g) => s + g.cataloged, 0)),
  'debris.onorbit': d => fmtInt(d.debris_clouds.groups.reduce((s, g) => s + g.on_orbit, 0)),
  'catalog.total': d => fmtInt(d.catalog.counts.total),
  'catalog.payload': d => fmtInt(d.catalog.counts.payload),
  'catalog.starlink': d => fmtInt(d.catalog.counts.starlink),
  'catalog.active': d => d.catalog.counts.active_payloads == null ? null : fmtInt(d.catalog.counts.active_payloads),
  'catalog.debris': d => fmtInt(d.catalog.counts.debris),
  'catalog.rb': d => fmtInt(d.catalog.counts.rocket_body),
  'budget.roadMph': d => fmtInt(d.avoidance_budget.road.speed_mph),
  'budget.headOnMph': d => fmtInt(d.avoidance_budget.road.head_on_closing_mph),
  'budget.brakeG': d => fmt(d.avoidance_budget.road.brake_g, 1),
  'budget.brakeS': d => fmt(d.avoidance_budget.road.brake_time_s, 1),
  'budget.brakeFt': d => fmtInt(d.avoidance_budget.road.brake_distance_ft),
  'budget.reactionS': d => fmt(d.avoidance_budget.road.reaction_s, 1),
  'budget.stopFt': d => fmtInt(d.avoidance_budget.road.stop_distance_ft),
  'budget.orbitMph': d => fmtInt(d.avoidance_budget.orbit.median_closing_mph),
  'budget.orbitKms': d => fmt(d.avoidance_budget.orbit.median_closing_kms, 1),
  'budget.warnS': d => fmt(d.avoidance_budget.orbit.warning_s, 1),
  'budget.sightFt': d => fmtInt(d.avoidance_budget.road.aashto_sight_distance_ft),
  'budget.t0cm': d => fmt(d.avoidance_budget.orbit.thrusters[0].shift_cm, 1),
  'budget.t1cm': d => fmt(d.avoidance_budget.orbit.thrusters[1].shift_cm, 1),
  'ex.a': d => fmtInt(d.avoidance_budget.orbit.early_burn_orbit.a_km),
  'ex.v': d => fmt(d.avoidance_budget.orbit.early_burn_orbit.v_kms, 2),
  'ex.T': d => fmt(d.avoidance_budget.orbit.early_burn_orbit.period_min, 1),
  ...Object.fromEntries([0, 1].flatMap(i => [
    [`ex.dv${i}`, d => `${fmt(d.avoidance_budget.orbit.thrusters[i].dv_mms, 1)} mm/s`],
    [`ex.da${i}`, d => `${fmt(d.avoidance_budget.orbit.thrusters[i].early.da_m, 1)} m`],
    [`ex.dT${i}`, d => `${fmt(d.avoidance_budget.orbit.thrusters[i].early.dT_ms, 1)} ms`],
    [`ex.ds${i}`, d => `${fmtInt(d.avoidance_budget.orbit.thrusters[i].early.ds_analytic_m)} m`],
    [`ex.last${i}`, d => `${fmt(d.avoidance_budget.orbit.thrusters[i].shift_cm, 1)} cm`],
    [`ex.chk${i}`, d => `${fmt(Math.abs(d.avoidance_budget.orbit.thrusters[i].early.ds_brahe_along_track_m), 1)} m`],
  ])),
  'ssn.passes': d => fmtInt((d.ssn_sensors.stats.radar_only ?? d.ssn_sensors.stats).passes_24h),
  'ssn.gap': d => fmt((d.ssn_sensors.stats.radar_only ?? d.ssn_sensors.stats).longest_gap_h, 1),
  'ssn.sat': d => d.ssn_sensors.sample_track.name,
  'collision.miss': d => fmtInt(d.debris_clouds.collision.miss_km_sgp4 * 1000),
  'catalog.alpha5': d => fmtInt(d.catalog.counts.norad_ge_100000),
  'pc.miss': d => fmtInt(d.pc.example.miss_m),
  'pc.speed': d => fmt(d.pc.example.rel_speed_kms, 1),
  'pc.cross': d => fmtInt(d.pc.example.crossing_angle_deg),
  'pc.sigma': d => d.pc.example.encounter_plane.sigma_major_minor_m.map(v => `${fmtInt(v)} m`).join(' × '),
  'pc.hbr': d => fmt(d.pc.example.hbr_m, 0),
  'pc.foster': d => sci(d.pc.example.pc_foster),
  'pc.fosterOneIn': d => fmtInt(Math.round(1 / d.pc.example.pc_foster)),
  'pc.mc': d => sci(d.pc.example.pc_mc),
  'pc.mcN': d => fmtInt(d.pc.example.mc_n),
  'pc.valN': d => fmtInt(d.pc.validation.length),
  'pc.valErr': d => sci(Math.max(...d.pc.validation.map(v => Math.abs(v.rel_err))), 1),
  'pc.pair': d => `${d.pc.example.primary.name} vs. ${d.pc.example.secondary.name.replace('DEB', 'debris')}, ${new Date(d.pc.example.tca_utc).toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })} · a NASA CARA test case`,
};

/* ======================= figures ======================= */

export const figures = {};

/* ---------- title: Earth with crossing orbits (illustration) ---------- */
function circOrbit(incDeg, raanDeg, r, n = 240) {
  const i_ = incDeg * Math.PI / 180, O = raanDeg * Math.PI / 180, pts = [];
  for (let k = 0; k <= n; k++) {
    const a = k / n * 2 * Math.PI;
    pts.push([r * (Math.cos(O) * Math.cos(a) - Math.sin(O) * Math.sin(a) * Math.cos(i_)), r * (Math.sin(O) * Math.cos(a) + Math.cos(O) * Math.sin(a) * Math.cos(i_)), r * Math.sin(a) * Math.sin(i_)]);
  }
  return pts;
}

// Split a projected polyline into runs that are in front of / behind the Earth disk.
function frontBack(pp, cx, cy, re) {
  const runs = [];
  let cur = null;
  pp.forEach(p => {
    const h = hidden(p, cx, cy, re);
    if (!cur || cur.h !== h) { if (cur) cur.pts.push([p[0], p[1]]); cur = { h, pts: [] }; runs.push(cur); }
    cur.pts.push([p[0], p[1]]);
  });
  return runs;
}

figures.titleOrbits = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth, cx = W / 2, cy = W / 2, re = 170;
    const P = projector(cx, cy, R_EARTH / re, 25, 18);
    const orbits = [[53, 10, 1.5, 'rgba(46,45,41,.45)'], [97.6, 75, 1.62, C.cardinal], [86.4, 165, 1.62, C.lagunita], [0, 0, 2.3, 'rgba(46,45,41,.3)']];
    el.__orbits = orbits.map(([inc, raan, k, col]) => {
      const g = svgEl('g', {}, svg);
      frontBack(circOrbit(inc, raan, R_EARTH * k).map(P), cx, cy, re).forEach(run => exactPath(g, run.pts, { color: col, width: 3, opacity: run.h ? 0.25 : 1 }));
      return g;
    });
    el.__earth = earth(svg, cx, cy, re, 5);
    // Two objects on the crossing polar orbits, phased to meet at the node line.
    const a = circOrbit(97.6, 75, R_EARTH * 1.62, 720), b = circOrbit(86.4, 165, R_EARTH * 1.62, 720);
    el.__dots = [svgEl('circle', { r: 9, fill: C.cardinal }, svg), svgEl('circle', { r: 9, fill: C.lagunita }, svg)];
    el.__place = f => {
      [[a, el.__dots[0]], [b, el.__dots[1]]].forEach(([orb, dotEl], j) => {
        const idx = Math.floor((((j ? 0.42 : 0.4) + f) % 1) * 719);
        const p = P(orb[idx]);
        dotEl.setAttribute('cx', p[0]); dotEl.setAttribute('cy', p[1]);
        dotEl.setAttribute('opacity', hidden(p, cx, cy, re) ? 0.2 : 1);
      });
    };
    el.__place(0);
  },
  animate(el, d, s, A) {
    drawOnAnim([el.__earth], A, 200, 1200);
    el.__orbits.forEach((g, i) => drawOnAnim([...g.querySelectorAll('path')], A, 600 + i * 250, 1600, 0));
    return loop(t => { el.__place(t / 60000); });
  },
};

/* ---------- Iridium 33 / Cosmos 2251 geometry ---------- */
figures.collision = {
  needs: ['debris_clouds'],
  render(el, d) {
    const c = d.debris_clouds.collision, svg = svgFor(el), W = el.offsetWidth, H = el.offsetHeight;
    const cx = W / 2, cy = H / 2, re = 230, P = projector(cx, cy, R_EARTH / re, 200, 25);
    el.__earth = earth(svg, cx, cy, re, 9);
    const cols = [C.lagunita, C.cardinal];
    el.__orbits = c.orbits.map((o, i) => {
      const pp = o.xyz_km.map(P);
      const segs = [];
      let cur = [];
      pp.forEach(p => { const h = hidden(p, cx, cy, re); if (h) { if (cur.length > 1) segs.push(cur); cur = []; } else cur.push([p[0], p[1]]); });
      if (cur.length > 1) segs.push(cur);
      const g = svgEl('g', {}, svg);
      segs.forEach(sg => exactPath(g, sg, { color: cols[i], width: 3.5 }));
      // Label at the visible point farthest from Earth's center, pushed outward past the orbit.
      const lab = pp.filter(q => !hidden(q, cx, cy, re)).reduce((best, q) => Math.hypot(q[0] - cx, q[1] - cy) > Math.hypot(best[0] - cx, best[1] - cy) ? q : best);
      const ang = Math.atan2(lab[1] - cy, lab[0] - cx), lx = lab[0] + Math.cos(ang) * 28, ly = lab[1] + Math.sin(ang) * 28 + 9;
      text(g, lx, ly, o.name, { size: 26, color: cols[i], anchor: Math.cos(ang) > 0.3 ? 'start' : Math.cos(ang) < -0.3 ? 'end' : 'middle', weight: 600 });
      return g;
    });
    const mid = c.orbits[0].xyz_km[Math.floor(c.orbits[0].xyz_km.length / 2)];
    const hit = c.position_km ? P(c.position_km) : P(mid);
    el.__x = svgEl('g', {}, svg);
    strokePath(el.__x, roughLine(hit[0] - 16, hit[1] - 16, hit[0] + 16, hit[1] + 16, { seed: 3 }) + roughLine(hit[0] + 16, hit[1] - 16, hit[0] - 16, hit[1] + 16, { seed: 4 }), { color: C.cardinal, width: 4 });
    el.__x.style.transformOrigin = `${hit[0]}px ${hit[1]}px`;
  },
  animate(el, d, s, A) {
    drawOnAnim([el.__earth], A, 0, 900);
    el.__orbits.forEach((g, i) => drawOnAnim([...g.querySelectorAll('path')], A, 400 + i * 400, 1500, 0));
    el.__orbits.forEach((g, i) => fadeIn(g.querySelector('text'), A, 900 + i * 400));
    popIn(el.__x, A, 2000);
  },
};

/* ---------- debris clouds today (canvas, slow rotation) ---------- */
function cloudDraw(ctx, w, h, groups, yaw, { re = 210, tilt = 22 } = {}) {
  const cx = w / 2, cy = h / 2, P = projector(cx, cy, R_EARTH / re, yaw, tilt);
  ctx.clearRect(0, 0, w, h);
  const back = [], front = [];
  groups.forEach(([pts, col, r]) => pts.forEach(xyz => { const p = P(xyz); (p[2] > 0 ? back : front).push([p, col, r]); }));
  const dot = ([p, col, r]) => { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 6.2832); ctx.fill(); };
  ctx.globalAlpha = 0.35; back.forEach(q => { if (!hidden(q[0], cx, cy, re)) dot(q); });
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(250,248,243,0.92)'; ctx.beginPath(); ctx.arc(cx, cy, re, 0, 6.2832); ctx.fill();
  ctx.fillStyle = 'rgba(0,108,184,0.06)'; ctx.beginPath(); ctx.arc(cx, cy, re, 0, 6.2832); ctx.fill();
  ctx.globalAlpha = 0.85; front.forEach(dot); ctx.globalAlpha = 1;
}

figures.debrisCloud = {
  needs: ['debris_clouds'],
  render(el, d) {
    const { ctx, w, h } = canvasFor(el);
    const cols = { 0: 'rgba(0,108,184,0.9)', 1: 'rgba(140,21,21,0.9)' };
    el.__groups = d.debris_clouds.groups.map((g, i) => [g.xyz_km, cols[i] || C.gray, 3.4]);
    el.__draw = yaw => cloudDraw(ctx, w, h, el.__groups, yaw, { re: 220 });
    el.__draw(20);
    const svg = svgFor(el);
    strokePath(svg, roughEllipse(w / 2, h / 2, 220, 220, { seed: 21, rough: 0.6 }), { color: C.ink, width: 2.4 });
    legend(svg, 20, h - 60, d.debris_clouds.groups.map((g, i) => [`${g.name} fragments`, i ? C.cardinal : C.lagunita, 'dot']), { gap: 36 });
  },
  animate(el, d, s, A) {
    A.push(el.querySelector('canvas').animate([{ opacity: 0, transform: 'scale(.92)' }, { opacity: 1, transform: 'none' }], { duration: 1200, easing: EASE_IN, ...FILL }));
    return loop(t => { el.__draw(20 + t * 0.004); });
  },
};

/* ---------- catalog cloud (interactive: toggle categories) ---------- */
const CATALOG_CATS = [
  ['S', 'Starlink', 'rgba(0,108,184,0.6)', '#006CB8', 'starlink'],
  ['P', 'Other payloads', 'rgba(46,45,41,0.6)', '#2E2D29', 'other_payload'],
  ['D', 'Debris', 'rgba(140,21,21,0.55)', '#8C1515', 'debris'],
  ['R', 'Rocket bodies', 'rgba(39,153,137,0.7)', '#279989', 'rocket_body'],
  ['U', 'Unknown', 'rgba(154,154,154,0.7)', '#9A9A9A', 'unknown'],
];

figures.catalogCloud = {
  needs: ['catalog'],
  render(el, d) {
    const W = 980, H = el.offsetHeight, re = 72, dpr = 2;
    const cv = document.createElement('canvas');
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = `${W}px`; cv.style.height = `${H}px`;
    el.appendChild(cv);
    const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
    const o = d.catalog.objects, by = Object.fromEntries(CATALOG_CATS.map(([k]) => [k, []]));
    o.xyz_km.forEach((xyz, i) => (by[o.type[i]] || by.U).push(xyz));
    // Draw order puts the sparse categories on top of the dense ones.
    const order = ['U', 'R', 'P', 'S', 'D'];
    el.__on = new Set(CATALOG_CATS.map(([k]) => k));
    el.__yaw = 30;
    el.__draw = (yaw = el.__yaw) => {
      el.__yaw = yaw;
      const groups = order.filter(k => el.__on.has(k)).map(k => { const c = CATALOG_CATS.find(x => x[0] === k); return [by[k], c[2], 1.15]; });
      cloudDraw(ctx, W, H, groups, yaw, { re, tilt: 18 });
    };
    el.__draw();
    const svg = svgEl('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, el);
    strokePath(svg, roughEllipse(W / 2, H / 2, re, re, { seed: 31, rough: 0.6 }), { color: C.ink, width: 2.2 });
    const gx = W / 2 + 42164 / (R_EARTH / re);
    text(svg, Math.min(gx, W - 10), H / 2 - 60, 'GEO ring', { size: 24, color: 'rgba(46,45,41,.6)', anchor: 'end' });

    // Clickable legend: one row per category with its count.
    const c = d.catalog.counts;
    const lg = document.createElement('div');
    lg.className = 'catalog-legend interactive';
    lg.style.cssText = 'position:absolute; left:1060px; top:40px; width:620px; font-family:var(--sans);';
    const ep = new Date(d.catalog.epoch);
    const epText = `${ep.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}, ${ep.toISOString().slice(11, 16)} UTC`;
    lg.innerHTML = `<div style="font-size:26px; color:var(--ink-50)">Tracked objects in orbit, ${epText}</div>
      <div class="big-number" style="font-size:64px; margin:0 0 6px">${fmtInt(c.total)}</div>
      <div class="showing" style="font-size:24px; color:var(--ink-50); margin-bottom:26px">showing all</div>` +
      CATALOG_CATS.map(([k, label, , solid, key]) => `<div class="cat-row" data-k="${k}" style="display:flex; align-items:center; gap:18px; padding:10px 0; cursor:pointer; user-select:none;">
        <span class="sw" style="width:22px; height:22px; border-radius:50%; background:${solid}; border:3px solid ${solid}; flex:none"></span>
        <span style="font-size:32px; flex:1; color:var(--ink)">${label}</span>
        <span class="big-number" style="font-size:40px; color:${solid}">${fmtInt(c[key])}</span></div>`).join('');
    el.appendChild(lg);
    const update = () => {
      let shown = 0;
      lg.querySelectorAll('.cat-row').forEach(row => {
        const on = el.__on.has(row.dataset.k), cat = CATALOG_CATS.find(x => x[0] === row.dataset.k);
        row.style.opacity = on ? 1 : 0.35;
        row.querySelector('.sw').style.background = on ? cat[3] : 'transparent';
        if (on) shown += c[cat[4]];
      });
      lg.querySelector('.showing').textContent = shown === c.total ? 'showing all' : `showing ${fmtInt(shown)}`;
      el.__draw();
    };
    lg.addEventListener('click', e => {
      e.stopPropagation();
      const row = e.target.closest('.cat-row');
      if (!row) return;
      const k = row.dataset.k;
      el.__on.has(k) ? el.__on.delete(k) : el.__on.add(k);
      update();
    });
    lg.addEventListener('pointerdown', e => e.stopPropagation());
    el.__reset = () => { el.__on = new Set(CATALOG_CATS.map(([k]) => k)); update(); };
  },
  animate(el, d, s, A) {
    fadeIn(el.querySelector('canvas'), A, 0, 900);
    fadeIn(el.querySelector('.catalog-legend'), A, 400, 700);
    return loop(t => { el.__draw(30 + t * 0.003); });
  },
};

/* ---------- icons for lifecycle cards ---------- */
// Small SSA diagrams: hand-drawn objects, exact paths for orbits and uncertainty.
function quadPath(p0, c, p1) { return `M${p0[0]} ${p0[1]}Q${c[0]} ${c[1]} ${p1[0]} ${p1[1]}`; }

function satGlyph(svg, x, y, seed, color = C.ink) {
  const g = svgEl('g', {}, svg);
  strokePath(g, roughRect(x - 5, y - 5, 10, 10, { seed, rough: 0.5, passes: 1 }), { color, width: 2.2 });
  strokePath(g, roughRect(x - 19, y - 3, 11, 6, { seed: seed + 1, rough: 0.4, passes: 1 }), { color, width: 1.8 });
  strokePath(g, roughRect(x + 8, y - 3, 11, 6, { seed: seed + 2, rough: 0.4, passes: 1 }), { color, width: 1.8 });
  return g;
}

figures.icon = {
  render(el, d, kind) {
    const svg = svgFor(el), w = el.offsetWidth, cx = w / 2, s = hashSeed(kind);
    const R = (dd, col = C.ink, wd = 2.6) => strokePath(svg, dd, { color: col, width: wd });
    const E = (dd, col, wd = 2.4, dash = null) => { const p = svgEl('path', { d: dd, stroke: col, 'stroke-width': wd, fill: 'none', 'stroke-linecap': 'round' }, svg); if (dash) p.setAttribute('stroke-dasharray', dash); return p; };
    if (kind === 'radar') {
      // Ground radar tracking a satellite on its orbit.
      E(quadPath([cx - 85, 40], [cx, -8], [cx + 85, 40]), C.lagunita, 2.2);
      satGlyph(svg, cx + 38, 24, s);
      // Parabolic dish aimed at the satellite: bowl, feed horn at the focus on two struts, pedestal.
      const vx = cx - 44, vy = 78, sx = cx + 38, sy = 24;
      const ang = Math.atan2(sy - vy, sx - vx), ax = [Math.cos(ang), Math.sin(ang)], pr = [-ax[1], ax[0]];
      const fl = 8, half = 20;
      const P = (u, w) => [vx + u * ax[0] + w * pr[0], vy + u * ax[1] + w * pr[1]];
      const bowl = Array.from({ length: 13 }, (_, i) => { const w = -half + (2 * half * i) / 12; return P(w * w / (4 * fl), w); });
      const rimA = bowl[0], rimB = bowl[12], focus = P(fl + 6, 0);
      svgEl('path', { d: `M${focus[0]} ${focus[1]}L${sx - 10} ${sy + 4}L${sx + 6} ${sy + 12}Z`, fill: 'rgba(0,108,184,0.22)' }, svg);
      R(roughPolyline(bowl, { seed: s + 3, rough: 0.35 }), C.ink, 2.8);
      R(roughLine(rimA[0], rimA[1], focus[0], focus[1], { seed: s + 7, passes: 1, rough: 0.3 }), C.ink, 1.8);
      R(roughLine(rimB[0], rimB[1], focus[0], focus[1], { seed: s + 8, passes: 1, rough: 0.3 }), C.ink, 1.8);
      svgEl('circle', { cx: focus[0], cy: focus[1], r: 3.5, fill: C.ink }, svg);
      R(roughLine(vx, vy, vx + 2, 97, { seed: s + 4, passes: 1, rough: 0.4 }), C.ink, 2.6);
      R(roughPolyline([[vx - 13, 105], [vx - 6, 95], [vx + 10, 95], [vx + 17, 105]], { seed: s + 6, rough: 0.4 }), C.ink, 2.4);
      R(roughLine(cx - 90, 105, cx + 90, 105, { seed: s + 5, passes: 1 }), 'rgba(46,45,41,.6)', 2);
    }
    if (kind === 'catalog') {
      // Observations associated with a known orbit, and one uncorrelated track.
      E(quadPath([cx - 85, 85], [cx, 0], [cx + 85, 85]), C.lagunita, 2.2);
      // Points on the arc (quadratic Bezier) with a little measurement scatter.
      [[0.14, 2], [0.3, -3], [0.46, 2], [0.62, -2], [0.78, 3]].forEach(([t, off], i) => {
        const x = cx - 85 + 170 * t, y = 85 * (1 - 2 * t + 2 * t * t) + off;
        R(roughLine(x - 6, y - 6, x + 6, y + 6, { seed: s + 10 + i, passes: 1, rough: 0.5 }), C.ink, 2.2);
        R(roughLine(x + 6, y - 6, x - 6, y + 6, { seed: s + 20 + i, passes: 1, rough: 0.5 }), C.ink, 2.2);
      });
      const ux = cx + 58, uy = 92;
      R(roughLine(ux - 6, uy - 6, ux + 6, uy + 6, { seed: s + 31, passes: 1, rough: 0.5 }), C.cardinal, 2.4);
      R(roughLine(ux + 6, uy - 6, ux - 6, uy + 6, { seed: s + 32, passes: 1, rough: 0.5 }), C.cardinal, 2.4);
      text(svg, ux + 14, uy + 8, '?', { size: 24, color: C.cardinal, weight: 600, family: 'var(--serif)' });
    }
    if (kind === 'sieve') {
      // Two crossing orbits and the screening box riding on the primary.
      E(linPath(circlePts(cx, 58, 88, 30, 0.0, 80)), C.lagunita, 2.2);
      E(linPath(circlePts(cx, 58, 80, 34, 0.55, 80)), C.cardinal, 2.2, '6 6');
      // Box at the crossing of the two orbits, aligned with the primary's direction of motion.
      const A1 = circlePts(cx, 58, 88, 30, 0.0, 360), B1 = circlePts(cx, 58, 80, 34, 0.55, 360);
      let best = [1e9, 0];
      A1.forEach((a, i) => { if (a[1] < 58) return; B1.forEach(b => { const dd = Math.hypot(a[0] - b[0], a[1] - b[1]); if (dd < best[0] && a[0] > cx) best = [dd, i]; }); });
      const [bx, by] = A1[best[1]], nxt = A1[(best[1] + 1) % A1.length];
      const ang = Math.atan2(nxt[1] - by, nxt[0] - bx) * 180 / Math.PI;
      const box = svgEl('g', {}, svg);
      box.setAttribute('transform', `rotate(${ang} ${bx} ${by})`);
      strokePath(box, roughRect(bx - 22, by - 7, 44, 14, { seed: s + 2, rough: 0.6 }), { color: C.ink, width: 2.4 });
      svgEl('circle', { cx: bx, cy: by, r: 4, fill: C.lagunita }, svg);
    }
    if (kind === 'dice') {
      // Encounter plane: covariance ellipses, hard-body circle, miss vector.
      const ex = cx + 18, ey = 55;
      [1, 2].forEach(k => E(linPath(circlePts(ex, ey, 34 * k, 13 * k, -0.35, 70)) + 'Z', C.lagunita, k === 1 ? 2.4 : 1.8));
      const hx = cx - 38, hy = 70;
      svgEl('circle', { cx: hx, cy: hy, r: 9, fill: 'rgba(140,21,21,0.15)', stroke: C.cardinal, 'stroke-width': 2.4 }, svg);
      R(roughArrow(hx + 9, hy - 3, ex - 2, ey + 1, { seed: s + 5, head: 9, rough: 0.5 }), C.ink, 2.2);
      svgEl('circle', { cx: ex, cy: ey, r: 3.5, fill: C.ink }, svg);
    }
    if (kind === 'fork') {
      // Wait (dashed, ends at closest approach) or maneuver (burn, curved away).
      const nx = cx - 25, ny = 72;
      R(roughLine(cx - 90, ny, nx, ny, { seed: s, passes: 1 }), C.ink, 2.6);
      E(`M${nx} ${ny}L${cx + 70} ${ny}`, C.ink, 2.2, '6 7');
      const tx = cx + 78;
      R(roughLine(tx - 8, ny - 8, tx + 8, ny + 8, { seed: s + 2, passes: 1, rough: 0.5 }), C.cardinal, 2.6);
      R(roughLine(tx + 8, ny - 8, tx - 8, ny + 8, { seed: s + 3, passes: 1, rough: 0.5 }), C.cardinal, 2.6);
      E(quadPath([nx, ny], [cx + 25, ny - 8], [cx + 75, 22]), C.green, 2.6);
      R(roughArrow(nx - 2, ny + 2, nx + 20, ny - 22, { seed: s + 4, head: 9, rough: 0.5 }), C.green, 2.4);
      text(svg, nx + 4, ny - 30, 'Δv', { size: 20, color: C.green, weight: 600 });
      svgEl('circle', { cx: nx, cy: ny, r: 4.5, fill: C.ink }, svg);
    }
    if (kind === 'share') {
      // An ephemeris file (OEM) sent to other operators.
      const x0 = cx - 82, y0 = 18, dw = 50, dh = 66, f = 13;
      R(roughPolyline([[x0, y0], [x0 + dw - f, y0], [x0 + dw, y0 + f], [x0 + dw, y0 + dh], [x0, y0 + dh]], { seed: s, closed: true, rough: 0.5 }), C.ink, 2.4);
      R(roughPolyline([[x0 + dw - f, y0], [x0 + dw - f, y0 + f], [x0 + dw, y0 + f]], { seed: s + 1, rough: 0.4 }), C.ink, 1.8);
      text(svg, x0 + dw / 2, y0 + 44, 'OEM', { size: 15, anchor: 'middle', weight: 600, color: C.ink });
      R(roughLine(x0 + 9, y0 + 54, x0 + dw - 9, y0 + 54, { seed: s + 2, passes: 1, rough: 0.3 }), 'rgba(46,45,41,.5)', 1.6);
      R(roughArrow(x0 + dw + 8, y0 + 26, cx + 30, 26, { seed: s + 3, head: 10, rough: 0.5 }), C.lagunita, 2.4);
      R(roughArrow(x0 + dw + 8, y0 + 46, cx + 30, 82, { seed: s + 4, head: 10, rough: 0.5 }), C.lagunita, 2.4);
      satGlyph(svg, cx + 58, 24, s + 5);
      satGlyph(svg, cx + 58, 84, s + 8);
    }
  },
};

/* ---------- radar vs optical scaling ---------- */
figures.snrScaling = {
  needs: ['ssn_sensors'],
  render(el, d) {
    const r = d.ssn_sensors.radar_ratio, ratio = r.geo_km / r.leo_km;
    const radar = Math.pow(ratio, -4), optical = Math.pow(ratio, -2);
    const svg = svgFor(el), W = el.offsetWidth;
    const x = scaleLog(1e-7, 1, 140, W - 120), y = 330;
    text(svg, W / 2, 60, `Signal at GEO range (${fmtInt(r.geo_km)} km) relative to LEO range (${fmtInt(r.leo_km)} km)`, { size: 30, anchor: 'middle', color: 'rgba(46,45,41,.75)' });
    el.__axis = strokePath(svg, roughLine(x(1e-7) - 10, y, x(1) + 14, y, { seed: 41 }), { color: 'rgba(46,45,41,.6)', width: 2.4 });
    [-7, -6, -5, -4, -3, -2, -1, 0].forEach(e => { svgEl('line', { x1: x(10 ** e), x2: x(10 ** e), y1: y - 10, y2: y + 10, stroke: 'rgba(46,45,41,.5)', 'stroke-width': 2 }, svg); text(svg, x(10 ** e), y + 50, e === 0 ? '1' : pow10(e), { size: 26, anchor: 'middle', color: 'rgba(46,45,41,.6)' }); });
    const mk = (v, col, label, sub, up) => {
      const g = svgEl('g', {}, svg), px = x(v);
      svgEl('circle', { cx: px, cy: y, r: 13, fill: col }, g);
      strokePath(g, roughLine(px, y + (up ? -20 : 20), px, y + (up ? -110 : 120), { seed: hashSeed(label), passes: 1 }), { color: col, width: 2.5 });
      text(g, px, y + (up ? -170 : 180), label, { size: 34, anchor: 'middle', color: col, weight: 600, family: 'var(--serif)' });
      text(g, px, y + (up ? -128 : 222), sub, { size: 26, anchor: 'middle', color: 'rgba(46,45,41,.7)' });
      g.style.transformOrigin = `${px}px ${y}px`;
      return g;
    };
    el.__leo = mk(1, C.ink, 'LEO', 'reference', true);
    el.__opt = mk(optical, C.green, `Telescope: 1/${fmtInt(1 / optical)}`, 'sunlight falls off as 1/R²', true);
    el.__rad = mk(radar, C.lagunita, `Radar: 1/${(1 / radar / 1e6).toFixed(1)} million`, 'out and back: 1/R⁴', false);
  },
  animate(el, d, s, A) { drawOnAnim([el.__axis], A, 200, 1000); popIn(el.__leo, A, 900); popIn(el.__opt, A, 1500); popIn(el.__rad, A, 2300); },
};

/* ---------- SSN map ---------- */
figures.ssnMap = {
  needs: ['ssn_sensors', 'land'],
  render(el, d, state) {
    const S = d.ssn_sensors, svg = svgFor(el), W = el.offsetWidth, H = el.offsetHeight;
    const mw = Math.min(W, 2 * H), mh = mw / 2, ox = (W - mw) / 2, oy = (H - mh) / 2;
    const px = ([lon, lat]) => [ox + (lon + 180) / 360 * mw, oy + (90 - lat) / 180 * mh];
    const land = svgEl('g', {}, svg);
    const splitLon = pts => { const out = []; let cur = []; pts.forEach((p, i) => { if (i && Math.abs(p[0] - pts[i - 1][0]) > 180) { out.push(cur); cur = []; } cur.push(p); }); out.push(cur); return out; };
    d.land.rings.forEach(r => { if (r.length > 8) splitLon(r).forEach(seg => seg.length > 1 && exactPath(land, seg.map(px), { color: 'rgba(46,45,41,.35)', width: 1.6 })); });
    const clipId = `ssn-clip-${Math.random().toString(36).slice(2, 8)}`;
    const defs = svgEl('defs', {}, svg), cp = svgEl('clipPath', { id: clipId }, defs);
    svgEl('rect', { x: ox, y: oy, width: mw, height: mh }, cp);
    const fp = svgEl('g', { 'clip-path': `url(#${clipId})` }, svg);
    S.sensors.forEach(s => {
      const ring = S.footprints.rings[s.name]?.leo;
      if (!ring) return;
      const radar = /radar|range|rae|azelrange/i.test(s.type) || s.range_max_km;
      const col = radar ? C.lagunita : C.green, fill = radar ? 'rgba(0,108,184,0.08)' : 'rgba(39,153,137,0.08)';
      const crossings = ring.filter((q, i) => i && Math.abs(q[0] - ring[i - 1][0]) > 180).length;
      if (crossings % 2 === 1) {
        // The footprint encloses a pole: open the ring at the antimeridian and close the fill over the pole.
        const k = ring.findIndex((q, i) => i && Math.abs(q[0] - ring[i - 1][0]) > 180);
        let run = ring.slice(k).concat(ring.slice(0, k));
        if (run[0][0] > run[run.length - 1][0]) run = run.reverse();
        const pole = run.reduce((a, q) => a + q[1], 0) > 0 ? 90 : -90;
        const poly = [[-180, run[0][1]], ...run, [180, run[run.length - 1][1]], [180, pole], [-180, pole]];
        exactPath(fp, poly.map(px), { color: 'none', width: 0, fill, closed: true });
        exactPath(fp, run.map(px), { color: col, width: 1.5, opacity: 0.9 });
      } else {
        // Unwrap longitudes into one continuous closed ring and draw it with copies shifted by
        // 360 degrees; the map clip keeps whichever parts land on the map.
        let off = 0;
        const un = ring.map((q, i) => { if (i && q[0] - ring[i - 1][0] > 180) off -= 360; else if (i && q[0] - ring[i - 1][0] < -180) off += 360; return [q[0] + off, q[1]]; });
        (crossings ? [-360, 0, 360] : [0]).forEach(sh => exactPath(fp, un.map(q => px([q[0] + sh, q[1]])), { color: col, width: 1.5, fill, opacity: 0.9, closed: true }));
      }
    });
    const sens = svgEl('g', {}, svg);
    S.sensors.forEach(s => {
      const [x, y] = px([s.lon, s.lat]);
      const radar = /radar|range|rae|azelrange/i.test(s.type) || s.range_max_km;
      if (radar) svgEl('circle', { cx: x, cy: y, r: 8, fill: C.lagunita }, sens);
      else svgEl('path', { d: `M${x} ${y - 10}L${x + 9} ${y + 7}L${x - 9} ${y + 7}Z`, fill: C.green }, sens);
    });
    legend(svg, ox + 20, oy + mh - 250, [['Radar (dot): sees an 800 km satellite', C.lagunita, 'band'], ['Telescope (triangle)', C.green, 'band']], { gap: 34 });
    el.__parts = [land, fp, sens];
    if (state === 'track') {
      const T = S.sample_track, g = svgEl('g', {}, svg);
      const ll = T.lonlat, t = T.t_s;
      // Radar coverage only (matches the radar-only statistics on the slide), merged into intervals.
      const radarNames = new Set(S.sensors.filter(s => /radar|range|rae|azelrange/i.test(s.type) || s.range_max_km).map(s => s.name));
      const iv = T.windows.filter(w => radarNames.has(w.sensor)).map(w => [w.start_s, w.end_s]).sort((a, b) => a[0] - b[0])
        .reduce((acc, w) => { const last = acc[acc.length - 1]; if (last && w[0] <= last[1]) last[1] = Math.max(last[1], w[1]); else acc.push([...w]); return acc; }, []);
      // Break points: every coverage edge, so observed segments start and end exactly at window times.
      const at = tt => {
        const i = Math.min(t.length - 2, Math.max(0, t.findIndex(x => x > tt) - 1)), u = (tt - t[i]) / (t[i + 1] - t[i]);
        let l0 = ll[i][0], l1 = ll[i + 1][0];
        if (l1 - l0 > 180) l1 -= 360; else if (l0 - l1 > 180) l1 += 360;
        let lon = l0 + (l1 - l0) * u; lon = ((lon + 540) % 360) - 180;
        return [lon, ll[i][1] + (ll[i + 1][1] - ll[i][1]) * u];
      };
      const edges = [t[0], ...iv.flat().filter(x => x > t[0] && x < t[t.length - 1]), t[t.length - 1]];
      for (let k = 0; k < edges.length - 1; k++) {
        const a0 = edges[k], a1 = edges[k + 1], mid = (a0 + a1) / 2;
        const cov = iv.some(([s0, s1]) => mid >= s0 && mid <= s1);
        const pts = [at(a0), ...t.map((tt, i) => [tt, ll[i]]).filter(([tt]) => tt > a0 && tt < a1).map(([, q]) => q), at(a1)];
        splitLon(pts).forEach(sg => sg.length > 1 && exactPath(g, sg.map(px), { color: cov ? C.ink : C.cardinal, width: cov ? 5 : 2.5, opacity: cov ? 1 : 0.8, dash: cov ? null : '6 8' }));
      }
      el.__track = g;
      legend(svg, ox + 20, oy + mh - 130, [[`${T.name}: seen by a radar`, C.ink], ['unobserved', C.cardinal]], { gap: 34 });
    }
  },
  animate(el, d, state, A, { adjacent }) {
    if (state === 'track') {
      // Reveal the track in time order after the summary box has appeared.
      const paths = [...el.__track.querySelectorAll('path')];
      paths.forEach(p => { p.style.opacity = 0; });
      paths.forEach((p, i) => A.push(p.animate([{ opacity: 0 }, { opacity: +(p.getAttribute('opacity') ?? 1) }], { duration: 250, delay: 900 + i * (3200 / paths.length), easing: EASE_IN, fill: 'forwards' })));
      return () => paths.forEach(p => { p.style.opacity = ''; });
    }
    fadeIn(el.__parts[0], A, 0, 900); fadeIn(el.__parts[1], A, 900, 900); fadeIn(el.__parts[2], A, 500, 600);
  },
};

/* ---------- rideshare radar tracks: sky-plot streaks (unlabeled, then by object on click) ---------- */
figures.rideshareTracks = {
  needs: ['rideshare_tracks'],
  render(el, d) {
    const R = d.rideshare_tracks, W = el.offsetWidth, H = el.offsetHeight, gap = 80, pw = (W - gap) / 2;
    const n = R.config.objects;
    const hue = i => `hsl(${Math.round((i * 360) / n)}, 55%, 42%)`;
    el.__gray = [];
    R.passes.forEach((P, k) => {
      const host = document.createElement('div');
      host.style.cssText = `position:absolute; left:${k * (pw + gap)}px; top:0; width:${pw}px; height:${H}px;`;
      el.appendChild(host);
      const svg = svgFor(host);
      // Sky plot: zenith at the center, horizon at the outer circle, north up, azimuth clockwise.
      const rad = Math.min(pw * 0.36, (H - 80) / 2), cx = rad + 30, cy = H / 2 + 20;
      const to = (az, elv) => { const r = rad * (90 - elv) / 90, a = az * Math.PI / 180; return [cx + r * Math.sin(a), cy - r * Math.cos(a)]; };
      text(svg, 0, 30, `${fmt(P.hours_after_deploy, 1)} h after deployment`, { size: 28, weight: 600, family: 'var(--serif)' });
      strokePath(svg, roughEllipse(cx, cy, rad, rad, { seed: 1300 + k, rough: 0.5 }), { color: 'rgba(46,45,41,.55)', width: 2.2 });
      [30, 60].forEach(e => svgEl('circle', { cx, cy, r: rad * (90 - e) / 90, fill: 'none', stroke: 'rgba(46,45,41,.18)', 'stroke-width': 1.5, 'stroke-dasharray': '4 6' }, svg));
      const mask = R.config.el_min_deg;
      svgEl('circle', { cx, cy, r: rad * (90 - mask) / 90, fill: 'none', stroke: 'rgba(140,21,21,.25)', 'stroke-width': 1.5 }, svg);
      [['N', 0], ['E', 90], ['S', 180], ['W', 270]].forEach(([l, az]) => { const [x, y] = to(az, -9); text(svg, x, y + 8, l, { size: 22, anchor: 'middle', color: 'rgba(46,45,41,.6)', weight: 600 }); });
      [30, 60].forEach(e => text(svg, cx + 6, cy - rad * (90 - e) / 90 - 6, `${e}°`, { size: 18, color: 'rgba(46,45,41,.45)' }));
      // Magnified inset around the highest point of the pass, where the streaks separate.
      const peak = P.el_deg.reduce((bi, e, i) => (e > P.el_deg[bi] ? i : bi), 0);
      const mag = 12, half = 13, iw = 2 * half * mag, [qx, qy] = to(P.az_deg[peak], P.el_deg[peak]);
      // Center the zoom window on the bundle of streaks near the top of the pass.
      const xy = P.az_deg.map((az, i) => to(az, P.el_deg[i]));
      const slice = xy.filter(([x, y]) => Math.abs(y - qy) < 3 && Math.abs(x - qx) < 3 * half);
      const xsorted = slice.map(q => q[0]).sort((a_, b_) => a_ - b_);
      const px = (xsorted[0] + xsorted[xsorted.length - 1]) / 2, py = qy;
      const ix = pw - iw - 10, iy = cy - iw / 2;
      strokePath(svg, roughRect(px - half, py - half, 2 * half, 2 * half, { seed: 1310 + k, passes: 1, rough: 0.4 }), { color: C.lagunita, width: 2 });
      strokePath(svg, roughRect(ix, iy, iw, iw, { seed: 1320 + k, rough: 0.6 }), { color: C.lagunita, width: 2.4 });
      svgEl('line', { x1: px + half, y1: py - half, x2: ix, y2: iy, stroke: 'rgba(0,108,184,.35)', 'stroke-width': 1.5 }, svg);
      svgEl('line', { x1: px + half, y1: py + half, x2: ix, y2: iy + iw, stroke: 'rgba(0,108,184,.35)', 'stroke-width': 1.5 }, svg);
      text(svg, ix + iw / 2, iy + iw + 30, `zoomed ${mag}×`, { size: 20, anchor: 'middle', color: C.lagunita });
      const clipId = `rt-clip-${k}-${Math.random().toString(36).slice(2, 7)}`;
      svgEl('rect', { x: ix, y: iy, width: iw, height: iw }, svgEl('clipPath', { id: clipId }, svgEl('defs', {}, svg)));
      const gray = svgEl('g', {}, svg), col = svgEl('g', { 'data-step': 1 }, svg);
      const gi = svgEl('g', { 'clip-path': `url(#${clipId})` }, gray), ci = svgEl('g', { 'clip-path': `url(#${clipId})` }, col);
      const perObj = {};
      P.az_deg.forEach((az, i) => {
        const [x, y] = to(az, P.el_deg[i]);
        svgEl('circle', { cx: x, cy: y, r: 2.2, fill: 'rgba(46,45,41,0.45)' }, gray);
        svgEl('circle', { cx: x, cy: y, r: 2.4, fill: hue(P.obj[i]) }, col);
        const zx = ix + iw / 2 + (x - px) * mag, zy = iy + iw / 2 + (y - py) * mag;
        if (Math.abs(x - px) < half + 4 && Math.abs(y - py) < half + 4) {
          svgEl('circle', { cx: zx, cy: zy, r: 4.2, fill: 'rgba(46,45,41,0.5)' }, gi);
          svgEl('circle', { cx: zx, cy: zy, r: 4.4, fill: hue(P.obj[i]) }, ci);
          (perObj[P.obj[i]] ||= []).push([P.t_s[i], zx, zy]);
        }
      });
      // After the click, join each satellite's points so its streak reads as one track.
      Object.entries(perObj).forEach(([o, pts]) => {
        pts.sort((a, b) => a[0] - b[0]);
        if (pts.length > 1) svgEl('path', { d: linPath(pts.map(q => [q[1], q[2]])), stroke: hue(+o), 'stroke-width': 1.6, fill: 'none', opacity: 0.7 }, ci);
      });
      el.__gray.push(gray);
    });
    const note = document.createElement('p');
    note.className = 'caption';
    note.setAttribute('data-step', 1);
    note.style.cssText = `position:absolute; left:0; right:0; top:${H + 6}px; text-align:center; margin:0;`;
    note.textContent = 'Each color is one satellite. The radar only sees points (each with a range too).';
    el.appendChild(note);
  },
  animate(el, d, s, A) { el.__gray.forEach((g, i) => fadeIn(g, A, 300 + i * 300, 800)); },
};

/* ---------- Starlink operator ephemeris vs GP ---------- */
figures.starlinkVsGp = {
  needs: ['starlink_vs_gp'],
  render(el, d) {
    const S = d.starlink_vs_gp, svg = svgFor(el), t = S.t_h, D = S.gp_minus_operator_rtn_km;
    const all = [...D.R, ...D.T, ...D.N].map(Math.abs), ymax = Math.max(...all) * 1.1;
    const tmax = Math.max(...t);
    const ax = axes(svg, { xr: [0, tmax], yr: [-ymax, ymax], xticks: Array.from({ length: Math.floor(tmax / 6) + 1 }, (_, i) => i * 6), xlabel: 'hours from operator ephemeris start', ylabel: 'GP minus operator (km)', right: 280, seed: 51 });
    svgEl('line', { x1: ax.box.x0, x2: ax.box.x1, y1: ax.y(0), y2: ax.y(0), stroke: 'rgba(46,45,41,.2)', 'stroke-width': 1.5 }, svg);
    if (S.operator_sigma_rtn_km) {
      const s = S.operator_sigma_rtn_km.T, up = t.map((tt, i) => [ax.x(tt), ax.y(3 * s[i])]), dn = t.map((tt, i) => [ax.x(tt), ax.y(-3 * s[i])]).reverse();
      el.__band = exactPath(svg, [...up, ...dn], { color: 'none', width: 0, fill: 'rgba(0,108,184,0.18)', closed: true });
    }
    const series = [['N', 'cross-track', C.gray], ['R', 'radial', C.ink], ['T', 'along-track', C.cardinal]];
    el.__lines = series.map(([k, name, col]) => exactPath(svg, t.map((tt, i) => [ax.x(tt), ax.y(D[k][i])]), { color: col, width: k === 'T' ? 4.5 : 3 }));
    let prev = -1e9;
    series.map(([k, name, col]) => [ax.y(D[k][D[k].length - 1]) + 8, name, col, k]).sort((a, b) => a[0] - b[0])
      .forEach(([y, name, col, k]) => { const yy = Math.max(y, prev + 30); prev = yy; text(svg, ax.box.x1 + 16, yy, name, { size: 26, color: col, weight: k === 'T' ? 600 : 400 }); });
    if (el.__band) legend(svg, ax.box.x0 + 30, 50, [['Operator 3σ along-track (GPS-based)', C.lagunita, 'band']]);
  },
  animate(el, d, s, A) { fadeIn(el.__band, A, 200); drawOnAnim(el.__lines, A, 500, 1800, 300); },
};

/* ---------- OD pipeline ---------- */
figures.odPipeline = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth, H = el.offsetHeight;
    const steps = ['Measurements', 'Initial orbit (IOD)', 'Batch / EKF / UKF', 'State + covariance', 'Predict'];
    const st = +(el.dataset.pipelineStep ?? 1), pipe = svgEl('g', st ? { 'data-step': st } : {}, svg);
    const bw = 262, gap = (W - steps.length * bw) / (steps.length - 1), y = 40, h = 96;
    el.__items = steps.map((s, i) => {
      const g = svgEl('g', {}, pipe), x = i * (bw + gap);
      strokePath(g, roughRect(x, y, bw, h, { seed: 70 + i }), { color: i === 3 ? C.lagunita : C.ink, width: 2.6 });
      text(g, x + bw / 2, y + h / 2 + 9, s, { size: 25, anchor: 'middle', color: i === 3 ? C.lagunita : C.ink, weight: 600 });
      if (i < steps.length - 1) strokePath(g, roughArrow(x + bw + 8, y + h / 2, x + bw + gap - 8, y + h / 2, { seed: 80 + i, head: 14 }), { color: C.ink, width: 2.6 });
      return g;
    });
  },
  animate(el, d, s, A) {
    const st = +(el.dataset.pipelineStep ?? 1), show = () => el.__items.forEach((g, i) => fadeIn(g, A, i * 250));
    if (!st) { show(); return; }
    return onStep(el, st, show);
  },
};

/* ---------- GPS OD error and covariance ---------- */
// Envelope of |x| over a centered window (one orbit), so oscillating signed errors read as a band edge.
function envelope(t, x, win) {
  const out = new Array(x.length);
  let j0 = 0, j1 = 0;
  for (let i = 0; i < x.length; i++) {
    while (t[j0] < t[i] - win / 2) j0++;
    while (j1 < x.length - 1 && t[j1 + 1] <= t[i] + win / 2) j1++;
    let m = 0;
    for (let j = j0; j <= j1; j++) m = Math.max(m, Math.abs(x[j]));
    out[i] = m;
  }
  return out;
}

figures.gpsOd = {
  needs: ['gps_od'],
  render(el, d) {
    const G = d.gps_od, svg = svgFor(el), t = G.t_h, period = 1.58;
    const env = k => envelope(t, G.err_rtn_m[k], period), sig = envelope(t, G.sigma3_rtn_m.T, period);
    const E = { R: env('R'), T: env('T'), N: env('N') };
    const ymax = Math.max(...E.T, ...sig) * 2;
    const ax = axes(svg, { xr: [0, Math.max(...t) / 24], yr: [1, Math.pow(10, Math.ceil(Math.log10(ymax)))], ylog: true, xlabel: 'days', ylabel: 'position error, per-orbit envelope', right: 260, seed: 61, yfmt: v => v >= 1000 ? `${v / 1000} km` : `${v} m` });
    const xe = ax.x(G.est_end_h / 24);
    el.__split = svgEl('g', {}, svg);
    svgEl('rect', { x: ax.box.x0, y: ax.box.y1, width: xe - ax.box.x0, height: ax.box.y0 - ax.box.y1, fill: 'rgba(0,108,184,0.10)' }, el.__split);
    text(el.__split, xe + 12, ax.box.y1 + 24, `← ${G.est_end_h} h of GPS fixes`, { size: 24, color: C.lagunita, weight: 600 });
    text(el.__split, xe + 12, ax.box.y1 + 56, 'prediction only, no measurements →', { size: 24, color: C.cardinal, weight: 600 });
    const step = Math.max(1, Math.floor(t.length / 400));
    const mk = (arr, col, w, dash) => exactPath(svg, t.map((tt, i) => [tt, arr[i]]).filter((_, i) => i % step === 0 || i === t.length - 1).map(([tt, v]) => [ax.x(tt / 24), ax.y(Math.max(v, 1))]), { color: col, width: w, dash });
    el.__sig = mk(sig, C.cardinal, 2.5, '8 8');
    el.__lines = [mk(E.N, C.gray, 2.5), mk(E.R, C.ink, 2.5), mk(E.T, C.cardinal, 4)];
    const lastY = arr => ax.y(Math.max(arr[arr.length - 1], 1));
    const lab = [[E.T, 'along-track error', C.cardinal, 600, 0], [sig, "filter's own 3σ", C.cardinal, 400, 0], [E.R, 'radial', C.ink, 400, 0], [E.N, 'cross-track', C.gray, 400, 0]]
      .map(([a, l, c, w]) => [lastY(a), l, c, w]).sort((a, b) => a[0] - b[0]);
    let prev = -1e9;
    lab.forEach(([y, l, c, w]) => { const yy = Math.max(y + 8, prev + 30); prev = yy; text(svg, ax.box.x1 + 14, yy, l, { size: 24, color: c, weight: w }); });
  },
  animate(el, d, s, A) { fadeIn(el.__split, A, 100); drawOnAnim([...el.__lines, el.__sig], A, 400, 2200, 150); },
};

/* ---------- MHT tree (built in step with the algorithm list) ---------- */
figures.mhtTree = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth;
    const node = (x, y, label, col, seed, parent) => {
      const g = svgEl('g', {}, parent || svg), w = Math.max(170, label.length * 14 + 36);
      g.__box = strokePath(g, roughRect(x - w / 2, y - 32, w, 64, { seed }), { color: col, width: 2.6 });
      g.__txt = text(g, x, y + 9, label, { size: 25, anchor: 'middle', color: col, weight: 600 });
      return g;
    };
    const edge = (x1, y1, x2, y2, seed, parent, col = C.ink) => strokePath(parent, roughArrow(x1, y1, x2, y2, { seed, head: 12 }), { color: col, width: 2.2 });
    const cx = W / 2, xs = [W * 0.13, W * 0.38, W * 0.63, W * 0.88], y0 = 50, y1 = 230, y2 = 450;
    node(cx, y0, 'New track', C.ink, 101);
    // Step 1: hypotheses.
    const s1 = svgEl('g', { 'data-step': 1 }, svg);
    const l1 = ['Object A', 'Object B', 'New object', 'False alarm'];
    el.__l1 = l1.map((l, i) => { edge(cx, y0 + 34, xs[i], y1 - 34, 110 + i, s1); return node(xs[i], y1, l, i >= 2 ? C.cardinal : C.ink, 120 + i, s1); });
    // Step 2: scores.
    const s2 = svgEl('g', { 'data-step': 2 }, svg);
    [['good fit', C.green], ['fair fit', C.ink], ['unlikely', 'rgba(46,45,41,.6)'], ['unlikely', 'rgba(46,45,41,.6)']]
      .forEach(([t, c], i) => text(s2, xs[i], y1 + 66, t, { size: 23, anchor: 'middle', color: c, italic: true }));
    // Step 3: next track extends each surviving branch.
    const s3 = svgEl('g', { 'data-step': 3 }, svg);
    const l2 = [[0, 'T2 fits A', C.green], [1, 'T2 misfits B', 'rgba(46,45,41,.6)'], [2, 'T2 fits new', C.ink]];
    l2.forEach(([i, l, c], k) => { edge(xs[i], y1 + 80, xs[i], y2 - 34, 130 + k, s3); node(xs[i], y2, l, c, 140 + k, s3); });
    // Step 4: prune the unlikely branches, keep the best path.
    const s4 = svgEl('g', { 'data-step': 4 }, svg);
    const cross = (x, y, seed) => { strokePath(s4, roughLine(x - 70, y - 30, x + 70, y + 30, { seed, passes: 1 }), { color: C.cardinal, width: 3.5 }); strokePath(s4, roughLine(x + 70, y - 30, x - 70, y + 30, { seed: seed + 1, passes: 1 }), { color: C.cardinal, width: 3.5 }); };
    cross(xs[1], y2, 150); cross(xs[3], y1, 152);
    strokePath(s4, roughRect(xs[0] - 110, y1 - 48, 220, y2 - y1 + 96, { seed: 154 }), { color: C.green, width: 3.2 });
    text(s4, xs[0], y2 + 76, 'keep', { size: 24, anchor: 'middle', color: C.green, weight: 600 });
    text(s4, xs[2], y2 + 76, 'keep for now', { size: 24, anchor: 'middle', color: C.ink, italic: true });
  },
};

/* ---------- TLE card: every field annotated ---------- */
const TLE_FIELDS = {
  1: [[1, 1, 'line', 'id'], [3, 7, 'catalog #', 'id'], [8, 8, 'class', 'id'], [10, 17, 'intl. designator', 'id'], [19, 32, 'epoch (year, day of year)', 'el'],
      [34, 43, 'ṅ / 2', 'drag'], [45, 52, 'n̈ / 6', 'drag'], [54, 61, 'B* drag term', 'drag'], [63, 63, 'eph. type', 'id', 0], [65, 68, 'element set #', 'id', 1], [69, 69, 'checksum', 'chk', 2]],
  2: [[1, 1, 'line', 'id'], [3, 7, 'catalog #', 'id'], [9, 16, 'inclination (deg)', 'el'], [18, 25, 'RAAN (deg)', 'el'], [27, 33, 'eccentricity', 'el'],
      [35, 42, 'arg. of perigee (deg)', 'el'], [44, 51, 'mean anomaly (deg)', 'el'], [53, 63, 'mean motion (rev/day)', 'el'], [64, 68, 'rev # at epoch', 'id'], [69, 69, 'checksum', 'chk']],
};

figures.tleCard = {
  needs: ['tle_gotchas'],
  render(el, d) {
    const [l1, l2] = d.tle_gotchas.example_tle, svg = svgFor(el), W = el.offsetWidth;
    const cw = 22.6, x0 = (W - 69 * cw) / 2, ys = { 1: 175, 2: 275 };
    const mono = '"Source Code Pro", Menlo, Consolas, monospace';
    const col = { id: 'rgba(46,45,41,.65)', el: C.lagunita, drag: C.cardinal, chk: C.gray };
    [l1, l2].forEach((str, li) => [...str].forEach((ch, i) => { if (ch !== ' ') text(svg, x0 + i * cw + cw / 2, ys[li + 1], ch, { size: 36, family: mono, anchor: 'middle' }); }));
    el.__fields = [];
    [1, 2].forEach(ln => {
      const above = ln === 1, y = ys[ln];
      TLE_FIELDS[ln].forEach(([a, b, label, kind, tierOverride], i) => {
        const g = svgEl('g', {}, svg), xa = x0 + (a - 1) * cw + 2, xb = x0 + b * cw - 2, c = col[kind];
        const by = above ? y - 40 : y + 16, tick = above ? 7 : -7;
        strokePath(g, roughPolyline([[xa, by + tick], [xa, by], [xb, by], [xb, by + tick]], { seed: 300 + ln * 20 + i, rough: 0.3 }), { color: c, width: 2 });
        // Two label tiers so neighboring short fields don't collide.
        const tier = tierOverride ?? i % 2, ly = above ? by - 14 - tier * 30 : by + 32 + tier * 30;
        const lx = Math.min(Math.max((xa + xb) / 2, 60), W - 60);
        if (tier) svgEl('line', { x1: (xa + xb) / 2, x2: (xa + xb) / 2, y1: above ? by : by, y2: above ? ly + 6 : ly - 22, stroke: c, 'stroke-width': 1.2, opacity: 0.6 }, g);
        text(g, lx, ly, label, { size: 20, anchor: 'middle', color: c, weight: 600 });
        el.__fields.push(g);
      });
    });
    text(svg, x0, 40, `${d.tle_gotchas.object.name} (NORAD ${d.tle_gotchas.object.norad})`, { size: 24, color: 'rgba(46,45,41,.6)' });
  },
  animate(el, d, s, A) { el.__fields.forEach((g, i) => fadeIn(g, A, 300 + i * 60, 500)); },
};

/* ---------- GP record (CCSDS OMM keys, JSON) ---------- */
figures.gpRecord = {
  needs: ['tle_gotchas'],
  render(el, d) {
    const rec = d.tle_gotchas.gp_record;
    const hi = { NORAD_CAT_ID: 'var(--cardinal)', REF_FRAME: 'var(--lagunita)', MEAN_ELEMENT_THEORY: 'var(--lagunita)' };
    const esc = v => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const lines = Object.entries(rec).map(([k, v]) => {
      const val = v === null ? 'null' : `"${esc(v)}"`, c = hi[k];
      return `<div${c ? ` style="color:${c}; font-weight:600"` : ''}><span style="color:${c || 'var(--ink-50)'}">"${k}"</span>: ${val},</div>`;
    });
    el.innerHTML = `<div data-rough="box" data-color="dim" data-rough-key="gp-record" style="position:absolute; inset:0; padding:26px 34px; background:rgba(255,255,255,.4);">
      <div style="font-family:'Source Code Pro', Menlo, monospace; font-size:21px; line-height:1.5; column-count:3; column-gap:40px; color:var(--ink)">${lines.join('')}</div></div>`;
  },
  animate(el, d, s, A) { fadeIn(el.firstElementChild, A, 300, 800); },
};

/* ---------- TLE gotchas ---------- */
figures.tleGotchas = {
  needs: ['tle_gotchas'],
  render(el, d) {
    const G = d.tle_gotchas, svg = svgFor(el), t = G.t_h;
    const ymax = Math.max(...G.teme_vs_gcrf_km, ...G.mean_as_osc_km) * 1.1;
    const ax = axes(svg, { xr: [0, Math.max(...t)], yr: [0, ymax], xlabel: 'hours', ylabel: 'position error (km)', right: 40, seed: 91 });
    el.__a = exactPath(svg, t.map((tt, i) => [ax.x(tt), ax.y(G.mean_as_osc_km[i])]), { color: C.cardinal, width: 4 });
    el.__b = exactPath(svg, t.map((tt, i) => [ax.x(tt), ax.y(G.teme_vs_gcrf_km[i])]), { color: C.lagunita, width: 4 });
    el.__b.setAttribute('data-step', 1);
    const n = t.length - 1;
    el.__la = text(svg, ax.x(t[n]) - 10, ax.y(G.mean_as_osc_km[n]) - 18, 'TLE elements converted to a state, propagated with J2', { size: 24, anchor: 'end', color: C.cardinal, weight: 600 });
    el.__lb = text(svg, ax.x(t[n]) - 10, ax.y(G.teme_vs_gcrf_km[n]) - 18, 'TEME used as if it were GCRF', { size: 24, anchor: 'end', color: C.lagunita, weight: 600 });
    el.__lb.setAttribute('data-step', 1);
  },
  animate(el, d, s, A) { drawOnAnim([el.__a], A, 500, 1400); fadeIn(el.__la, A, 1500); return onStep(el, 1, () => drawOnAnim([el.__b], A, 0, 1200)); },
};

/* ---------- brute force count ---------- */
figures.bruteForce = {
  needs: ['screening'],
  render(el, d) {
    const P = d.screening.all_vs_all_paper, steps = 7 * 24 * 60;
    el.innerHTML = `
      <div style="position:absolute; left:0; right:0; top:20px; text-align:center;">
        <p class="caption" style="margin:0">${fmtInt(P.catalog)} objects → ${window.katex ? katex.renderToString('\\dfrac{N(N-1)}{2}') : 'N(N−1)/2'} pairs</p>
        <p class="big-number" style="font-size:130px; margin:0" data-roll="${P.brute}">${fmtInt(P.brute)}</p>
      </div>
      <div class="bf2" data-step="1" style="position:absolute; left:0; right:0; top:300px; text-align:center;">
        <p class="caption" style="margin:0">× ${fmtInt(steps)} one-minute steps</p>
        <p class="big-number c-cardinal" style="font-size:110px; margin:0"><span data-roll="${P.brute * steps}">${fmt(P.brute * steps / 1e12, 2)}</span> trillion distance checks</p>
      </div>`;
  },
  animate(el, d, s, A) {
    const [a, b] = el.querySelectorAll('[data-roll]'), steps = 7 * 24 * 60, P = d.screening.all_vs_all_paper;
    const c1 = rollNumber(a, 1, P.brute, { duration: 1800, log: true });
    let c2 = () => {};
    const off = onStep(el, 1, () => { c2 = rollNumber(b, P.brute / 1e12, P.brute * steps / 1e12, { duration: 1400, log: true, format: v => fmt(v, 2) }); });
    return () => { c1(); c2(); off(); };
  },
};

/* ---------- sieves ---------- */
figures.sieves = {
  needs: ['screening'],
  render(el, d) {
    const S = d.screening, c = S.counts, W = el.offsetWidth, H = el.offsetHeight;
    const FC = { apsis: '#006CB8', path: '#279989', phase: '#E98300' };
    const tex = s => (window.katex ? katex.renderToString(s, { throwOnError: false }) : s);
    const D = Math.hypot(S.box_km.R, S.box_km.T, S.box_km.N);
    const cards = [
      ['apsis', 'Apsis', 'Do the altitude ranges overlap?', tex('q_1 - D \\le Q_2 \\quad\\text{and}\\quad q_2 - D \\le Q_1'), 'q: perigee radius, Q: apogee radius'],
      ['path', 'Path', 'Do the orbits come close anywhere?', tex('\\mathrm{MOID} \\le D'), 'minimum distance between the two orbit paths'],
      ['phase', 'Phase', 'Are both there at the same time?', tex('d_1(t) \\le D \\quad\\text{and}\\quad d_2(t) \\le D'), 'd: distance from the other orbit’s plane'],
    ];
    const cw = 500, ch = 380, gap = (W - 3 * cw) / 2;
    const wrap = document.createElement('div');
    wrap.style.cssText = `position:absolute; left:0; top:0; width:${W}px; height:${ch}px;`;
    el.appendChild(wrap);
    el.__cards = wrap;
    el.__diag = cards.map(([key, title, q, formula, sub], i) => {
      const card = document.createElement('div');
      card.className = 'card';
      card.setAttribute('data-rough', 'box');
      card.setAttribute('data-rough-key', `sieve-${key}`);
      card.style.cssText = `left:${i * (cw + gap)}px; top:0; width:${cw}px; height:${ch}px; padding:14px 18px;`;
      card.innerHTML = `<div class="dg" style="position:relative; width:100%; height:170px;"></div>
        <h3 style="color:${FC[key]}; margin:6px 0 4px">${title}</h3>
        <p style="margin:0 0 10px">${q}</p>
        <div style="font-size:26px; color:var(--ink)">${formula}</div>
        <div class="sans" style="font-size:20px; color:var(--ink-50); margin-top:6px">${sub}</div>`;
      wrap.appendChild(card);
      const host = card.querySelector('.dg');
      const svg = svgEl('svg', { width: cw - 36, height: 170, viewBox: `0 0 ${cw - 36} 170` }, host);
      const cx = (cw - 36) / 2, cy = 86, col = FC[key];
      if (key === 'apsis') {
        // Secondary's perigee-apogee shell (band), primary's circular orbit inside it.
        svgEl('path', { d: linPath(circlePts(cx, cy, 78, 78)) + 'Z' + linPath(circlePts(cx, cy, 50, 50).reverse()) + 'Z', fill: col, opacity: 0.16, 'fill-rule': 'evenodd' }, svg);
        exactPath(svg, circlePts(cx, cy, 78, 78), { color: col, width: 2, dash: '6 6' });
        exactPath(svg, circlePts(cx, cy, 50, 50), { color: col, width: 2, dash: '6 6' });
        exactPath(svg, circlePts(cx, cy, 64, 64), { color: C.ink, width: 3 });
      }
      if (key === 'path') {
        const A_ = circlePts(cx, cy, 96, 50, 0.25, 180), B_ = circlePts(cx + 6, cy + 4, 90, 58, -0.45, 180);
        exactPath(svg, A_, { color: C.ink, width: 3 });
        exactPath(svg, B_, { color: 'rgba(46,45,41,.55)', width: 2.4, dash: '8 7' });
        // Closest approach between the two paths (the MOID), found by brute force on the sampled curves.
        let best = [1e9];
        A_.forEach(a => B_.forEach(b => { const dd = Math.hypot(a[0] - b[0], a[1] - b[1]); if (dd < best[0] && a[0] > cx) best = [dd, a, b]; }));
        const [, a, b] = best, ux = (b[0] - a[0]) || 0.001, uy = (b[1] - a[1]) || 0.001, L = Math.hypot(ux, uy);
        const m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        svgEl('line', { x1: m[0] - ux / L * 9, y1: m[1] - uy / L * 9, x2: m[0] + ux / L * 9, y2: m[1] + uy / L * 9, stroke: col, 'stroke-width': 4, 'stroke-linecap': 'round' }, svg);
        svgEl('circle', { cx: m[0], cy: m[1], r: 16, fill: col, opacity: 0.18 }, svg);
      }
      if (key === 'phase') {
        const A_ = circlePts(cx, cy, 98, 56, 0.2, 180), B_ = circlePts(cx, cy, 98, 56, -0.6, 180);
        exactPath(svg, A_, { color: C.ink, width: 3 });
        exactPath(svg, B_, { color: 'rgba(46,45,41,.55)', width: 2.4, dash: '8 7' });
        svgEl('circle', { cx: cx + 92, cy: cy + 4, r: 24, fill: col, opacity: 0.18, stroke: col, 'stroke-width': 2, 'stroke-dasharray': '4 5' }, svg);
        svgEl('circle', { cx: cx + 84, cy: cy - 12, r: 6, fill: C.ink }, svg);
        svgEl('circle', { cx: cx + 98, cy: cy + 20, r: 6, fill: 'rgba(46,45,41,.6)' }, svg);
      }
      svgEl('circle', { cx, cy, r: 11, fill: 'rgba(0,108,184,.1)', stroke: C.ink, 'stroke-width': 2 }, svg);
      return card;
    });
    // Funnel bars, one color per filter.
    const svg = svgFor(el), pw_ = S.pair_windows;
    const stages = [['all', pw_.total, C.gray], ['apsis', pw_.apsis, FC.apsis], ['path', pw_.path, FC.path], ['phase', pw_.phase, FC.phase], ['box events', S.events.length, C.cardinal]];
    const bx = 220, bw = W - bx - 220, y0 = ch + 60, bh = 40, x = v => bw * Math.log10(Math.max(v, 1)) / Math.log10(pw_.total);
    const barsG = svgEl('g', { 'data-step': 1 }, svg);
    text(barsG, 0, y0 - 16, `${S.primary.name} vs ${fmtInt(c.catalog)} objects × ${Math.round(pw_.total / c.catalog)} half-hour windows over ${S.span_days} days (log scale) · D ≈ ${Math.round(D)} km`, { size: 22, color: 'rgba(46,45,41,.6)' });
    el.__bars = stages.map(([name, v, col], i) => {
      const g = svgEl('g', {}, barsG), y = y0 + i * (bh + 12);
      text(g, bx - 18, y + bh / 2 + 9, name, { size: 25, anchor: 'end', color: col === C.gray ? 'rgba(46,45,41,.6)' : col, weight: 600 });
      svgEl('rect', { x: bx, y, width: Math.max(4, x(v)), height: bh, fill: col, opacity: col === C.gray ? 0.25 : 0.7 }, g);
      text(g, bx + Math.max(4, x(v)) + 14, y + bh / 2 + 9, fmtInt(v), { size: 26, weight: 600, color: col });
      return g;
    });
    el.__dy = (H - ch) / 2;
  },
  animate(el, d, s, A) {
    const sec = el.closest('section');
    // Cards start centered on the slide and move up when the bars appear.
    if (!(sec.__step >= 1)) el.__cards.style.transform = `translateY(${el.__dy}px)`;
    el.__diag.forEach((card, i) => fadeIn(card, A, 200 + i * 250));
    fadeIn(el.__cards.querySelector('svg.rough-layer'), A, 200, 900);
    return onStep(el, 1, () => {
      A.push(el.__cards.animate([{ transform: `translateY(${el.__dy}px)` }, { transform: 'none' }], { duration: 900, easing: EASE_MOVE, fill: 'forwards' }));
      el.__cards.style.transform = '';
      el.__bars.forEach((g, i) => A.push(g.animate([{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'none' }], { duration: 600, delay: 600 + i * 350, easing: EASE_IN, ...FILL })));
    });
  },
};

function circlePts(cx, cy, rx, ry, rot = 0, n = 90) {
  const out = [];
  for (let i = 0; i <= n; i++) { const a = i / n * 2 * Math.PI, x = rx * Math.cos(a), y = ry * Math.sin(a); out.push([cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)]); }
  return out;
}

/* ---------- screening box sweep ---------- */
// Linear interpolation of a sampled series at time t.
function sampleAt(ts, xs, t) {
  if (t <= ts[0]) return xs[0];
  if (t >= ts[ts.length - 1]) return xs[xs.length - 1];
  let lo = 0, hi = ts.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m; }
  const u = (t - ts[lo]) / (ts[hi] - ts[lo]);
  return xs[lo].map((v, k) => v + (xs[hi][k] - v) * u);
}

figures.boxSweep = {
  needs: ['screening'],
  render(el, d) {
    const S = d.screening, Hh = S.hero, svg = svgFor(el), W = el.offsetWidth, H = el.offsetHeight;
    // Left: both orbits projected onto the primary's orbit plane at TCA (to scale).
    const lw = 640, cx = lw / 2, cy = H / 2 - 20;
    const pr = Hh.primary_xyz_km, sc = Hh.secondary_xyz_km, ot = Hh.orbit_t_s;
    const mid = sampleAt(ot, pr, 0), r0 = Math.hypot(...mid), u = mid.map(v => v / r0);
    const v0 = sampleAt(ot, pr, 1).map((v, i) => v - mid[i]);
    const hv = cross(u, v0), hn = Math.hypot(...hv), n = hv.map(v => v / hn), tv = cross(n, u);
    // Camera looks down on the TCA point from above and behind the primary's orbit plane.
    const k = 250 / r0, dv = u.map((x, i) => 0.6 * x - 0.8 * n[i]), ey = cross(dv, tv);
    const toP3 = p => [cx + dot(p, tv) * k, cy - dot(p, ey) * k, -dot(p, dv)];
    const toP = p => toP3(p).slice(0, 2);
    const re = R_EARTH * k;
    el.__earthL = earth(svg, cx, cy, re, 33);
    const drawOrbit = (pts, col, dash) => {
      const g = svgEl('g', {}, svg);
      frontBack(pts.map(toP3), cx, cy, re).forEach(run => exactPath(g, run.pts, { color: col, width: 3.5, opacity: run.h ? 0.2 : 1, dash: run.h ? '4 8' : dash }));
      return g;
    };
    el.__pr = drawOrbit(pr, C.lagunita, null);
    el.__sc = drawOrbit(sc, C.cardinal, null);
    text(svg, cx, H - 30, 'orbit view, to scale', { size: 22, anchor: 'middle', color: 'rgba(46,45,41,.55)' });
    text(svg, 20, 40, `${S.primary.name}`, { size: 26, color: C.lagunita, weight: 600 });
    el.__dotP = svgEl('circle', { r: 10, fill: C.lagunita }, svg);
    el.__dotS = svgEl('circle', { r: 10, fill: C.cardinal }, svg);
    el.__setOrbit = t => {
      [[pr, el.__dotP], [sc, el.__dotS]].forEach(([orb, dotEl]) => {
        const q = toP3(sampleAt(ot, orb, t));
        dotEl.setAttribute('cx', q[0]); dotEl.setAttribute('cy', q[1]);
        dotEl.setAttribute('opacity', hidden(q, cx, cy, re) ? 0.15 : 1);
      });
    };
    // Right: the primary's RTN frame, along-track horizontal, radial vertical (radial stretched).
    const rx0 = 760, rw = W - rx0 - 20, rcx = rx0 + rw / 2, rcy = H / 2 - 40;
    const box = S.box_km, halfT = box.half_widths ? box.T : box.T / 2, halfR = box.half_widths ? box.R : box.R / 2, halfN = box.half_widths ? box.N : box.N / 2;
    const tRange = halfT * 1.9, xs = rw / (2 * tRange), ys = 150 / halfR;
    const toRT = ([R, T]) => [rcx + T * xs, rcy - R * ys];
    strokePath(svg, roughLine(rx0, rcy, rx0 + rw, rcy, { seed: 401, passes: 1 }), { color: 'rgba(46,45,41,.35)', width: 2 });
    strokePath(svg, roughLine(rcx, rcy - 230, rcx, rcy + 230, { seed: 402, passes: 1 }), { color: 'rgba(46,45,41,.35)', width: 2 });
    text(svg, rx0 + rw, rcy + 36, 'along-track (km)', { size: 22, anchor: 'end', color: 'rgba(46,45,41,.6)' });
    text(svg, rcx + 12, rcy - 236, `radial (km, stretched ${Math.round(ys / xs)}×)`, { size: 22, color: 'rgba(46,45,41,.6)' });
    [-halfT, halfT].forEach(v => text(svg, toRT([0, v])[0], rcy + 36, `${v > 0 ? '+' : '−'}${Math.abs(v)}`, { size: 22, anchor: 'middle', color: 'rgba(46,45,41,.6)' }));
    [-halfR, halfR].forEach(v => text(svg, rcx - 12, toRT([v, 0])[1] + 8, `${v > 0 ? '+' : '−'}${Math.abs(v)}`, { size: 22, anchor: 'end', color: 'rgba(46,45,41,.6)' }));
    const [bx0, by0] = toRT([halfR, -halfT]), [bx1, by1] = toRT([-halfR, halfT]);
    el.__box = strokePath(svg, roughRect(bx0, by0, bx1 - bx0, by1 - by0, { seed: 410 }), { color: C.lagunita, width: 3.5 });
    el.__boxLabel = text(svg, bx1, by0 - 16, `screening box: ±${halfR} km radial, ±${halfT} km along-track, ±${halfN} km cross-track`, { size: 24, anchor: 'end', color: C.lagunita, weight: 600 });
    svgEl('circle', { cx: rcx, cy: rcy, r: 9, fill: C.lagunita }, svg);
    const vT = Math.abs((sampleAt(Hh.t_s, Hh.rel_rtn_km, 1)[1] - sampleAt(Hh.t_s, Hh.rel_rtn_km, -1)[1]) / 2) || 1;
    el.__tc = 1.15 * tRange / vT;
    const relPts = Hh.t_s.map((t, i) => [t, Hh.rel_rtn_km[i]]).filter(([t]) => Math.abs(t) <= el.__tc).map(([, r]) => toRT(r));
    el.__rel = exactPath(svg, relPts, { color: C.cardinal, width: 2.5, dash: '8 8' });
    el.__relDot = svgEl('circle', { r: 10, fill: C.cardinal }, svg);
    el.__setRel = t => { const [x, y] = toRT(sampleAt(Hh.t_s, Hh.rel_rtn_km, t)); el.__relDot.setAttribute('cx', x); el.__relDot.setAttribute('cy', y); };
    el.__info = svgEl('g', { 'data-step': 1 }, svg);
    const [mR, mT, mN] = Hh.miss_rtn_km;
    text(el.__info, rx0 + 10, H - 100, `${Hh.secondary.name} (NORAD ${Hh.secondary.norad}, launched 1959)`, { size: 26, weight: 600, color: C.cardinal });
    text(el.__info, rx0 + 10, H - 62, `closest: ${fmt(Hh.miss_km, 1)} km (R ${fmt(mR, 1)}, T ${fmt(mT, 1)}, N ${fmt(mN, 1)}) at ${fmt(Hh.rel_speed_kms, 1)} km/s`, { size: 24 });
    text(el.__info, rx0 + 10, H - 26, `${Hh.tca_utc.replace('T', ' ').slice(0, 16)} UTC · inside the box: goes on to risk assessment`, { size: 24, color: 'rgba(46,45,41,.7)' });
    el.__setOrbit(0); el.__setRel(0);
  },
  animate(el, d, s, A) {
    fadeIn(el.__pr, A, 200, 900);
    fadeIn(el.__sc, A, 700, 900);
    drawOnAnim([el.__box], A, 1000, 1000);
    fadeIn(el.__boxLabel, A, 1400);
    fadeIn(el.__rel, A, 3600);
    const t0 = d.screening.hero.orbit_t_s[0] * 0.6, tc = el.__tc;
    return loop(t => {
      const f1 = Math.min(1, Math.max(0, (t - 600) / 3000)), e1 = 1 - Math.pow(1 - f1, 2);
      el.__setOrbit(t0 * (1 - e1));
      const f2 = Math.min(1, Math.max(0, (t - 3600) / 2600));
      el.__setRel(-tc * (1 - f2));
      return t < 6400;
    });
  },
};
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/* ---------- Monte Carlo cost ---------- */
figures.mcCost = {
  needs: ['pc'],
  render(el, d) {
    const M = d.pc.mc_cost, W = el.offsetWidth, H = el.offsetHeight;
    const host = document.createElement('div');
    host.style.cssText = `position:absolute; left:0; top:0; width:1000px; height:${H}px;`;
    el.appendChild(host);
    const svg = svgFor(host);
    const ax = axes(svg, { xr: [1e-7, 1e-2], yr: [1e3, 1e11], xlog: true, ylog: true, xlabel: 'true probability of collision', ylabel: 'samples needed',
      xfmt: v => pow10(Math.round(Math.log10(v))), yfmt: v => pow10(Math.round(Math.log10(v))), right: 20, bottom: 90, seed: 501 });
    const line = svgEl('path', { stroke: C.cardinal, 'stroke-width': 4, fill: 'none', 'stroke-linecap': 'round' }, svg);
    const dot = svgEl('circle', { r: 11, fill: C.cardinal }, svg);
    const guideV = svgEl('line', { stroke: 'rgba(140,21,21,.35)', 'stroke-width': 1.5, 'stroke-dasharray': '5 6' }, svg);
    const guideH = svgEl('line', { stroke: 'rgba(140,21,21,.35)', 'stroke-width': 1.5, 'stroke-dasharray': '5 6' }, svg);
    // Controls and readout (right column).
    const side = document.createElement('div');
    side.className = 'interactive sans';
    side.style.cssText = 'position:absolute; left:1060px; top:20px; width:540px;';
    const seg = (name, opts) => `<div style="font-size:22px; color:var(--ink-50); margin:0 0 8px">${name}</div><div class="seg" data-name="${name}" style="display:flex; gap:10px; margin-bottom:26px">${opts.map(([lab, v], i) => `<button data-v="${v}" style="font:inherit; font-size:24px; padding:6px 16px; border-radius:10px; border:2px solid var(--ink-35); background:transparent; cursor:pointer">${lab}</button>`).join('')}</div>`;
    side.innerHTML = `<div style="font-size:22px; color:var(--ink-50); margin-bottom:8px">True Pc</div>
      <div class="pcval" style="font-size:40px; font-weight:600; margin-bottom:18px"></div>
      <div class="slider" style="position:relative; left:0; width:520px; height:60px; margin-bottom:24px"><div class="track"></div><div class="fill"></div><div class="thumb"></div></div>
      ${seg('Confidence', [['90%', 1.644854], ['95%', 1.959964], ['99%', 2.575829]])}
      ${seg('Relative error', [['±10%', 0.1], ['±25%', 0.25], ['±50%', 0.5]])}
      <div class="out" style="font-size:26px; line-height:1.5; color:var(--ink-50)"></div>`;
    el.appendChild(side);
    const st = { lp: -4, z: 1.959964, eps: 0.1 };
    const N = (p, z, eps) => (z * z * (1 - p)) / (eps * eps * p);
    const draw = () => {
      const pts = [];
      for (let lp = -7; lp <= -2.0001; lp += 0.05) { const p = 10 ** lp; pts.push([ax.x(p), ax.y(Math.min(Math.max(N(p, st.z, st.eps), 1e3), 1e11))]); }
      line.setAttribute('d', linPath(pts));
      const p = 10 ** st.lp, n = N(p, st.z, st.eps), x = ax.x(p), y = ax.y(Math.min(Math.max(n, 1e3), 1e11));
      dot.setAttribute('cx', x); dot.setAttribute('cy', y);
      guideV.setAttribute('x1', x); guideV.setAttribute('x2', x); guideV.setAttribute('y1', ax.box.y0); guideV.setAttribute('y2', y);
      guideH.setAttribute('x1', ax.box.x0); guideH.setAttribute('x2', x); guideH.setAttribute('y1', y); guideH.setAttribute('y2', y);
      side.querySelector('.pcval').textContent = `1 in ${fmtInt(1 / p)}`;
      const f = (st.lp + 7) / 5;
      side.querySelector('.thumb').style.left = `${f * 100}%`; side.querySelector('.fill').style.width = `${f * 100}%`;
      const cpuH = (n * M.objects_per_sample * M.prop_seconds_per_object) / 3600;
      side.querySelector('.out').innerHTML = `<div style="font-size:22px">Samples needed</div><b style="color:var(--cardinal); font-size:56px; line-height:1.15">${fmtInt(n)}</b><br>to see about ${fmtInt(n * p)} hits<br><span style="font-size:24px">× ${M.objects_per_sample} objects × ${fmt(M.prop_seconds_per_object, 1)} s each (${M.prop_span_days} days) ≈ <b style="color:var(--ink)">${fmtInt(cpuH)} CPU-hours</b> for one conjunction</span>`;
      side.querySelectorAll('.seg').forEach(g => g.querySelectorAll('button').forEach(b => {
        const on = +b.dataset.v === (g.dataset.name === 'Confidence' ? st.z : st.eps);
        b.style.background = on ? 'var(--ink)' : 'transparent'; b.style.color = on ? 'var(--board)' : 'var(--ink)'; b.style.borderColor = on ? 'var(--ink)' : 'var(--ink-35)';
      }));
    };
    el.__reset = () => { st.lp = -4; st.z = 1.959964; st.eps = 0.1; draw(); };
    const sl = side.querySelector('.slider');
    const onMove = e => { const r = sl.getBoundingClientRect(); st.lp = Math.round((-7 + 5 * Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))) * 10) / 10; draw(); };
    sl.addEventListener('pointerdown', e => { e.stopPropagation(); sl.setPointerCapture(e.pointerId); onMove(e); sl.onpointermove = onMove; });
    sl.addEventListener('pointerup', () => { sl.onpointermove = null; });
    side.addEventListener('click', e => {
      e.stopPropagation();
      const b = e.target.closest('button'); if (!b) return;
      if (b.closest('.seg').dataset.name === 'Confidence') st.z = +b.dataset.v; else st.eps = +b.dataset.v;
      draw();
    });
    side.addEventListener('pointerdown', e => e.stopPropagation());
    draw();
  },
  animate(el, d, s, A) { fadeIn(el.firstElementChild, A, 200, 800); },
};

/* ---------- Monte Carlo method: the loop ---------- */
figures.mcLoop = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth;
    const steps = [
      ['Sample', 'draw both objects’ states from their estimates and covariances'],
      ['Propagate', 'move each sample to its closest approach'],
      ['Check', 'miss distance < hard-body radius? count a hit'],
      ['Repeat', 'until the estimate is precise enough'],
    ];
    const bw = 500, bh = 126, gap = 30, x0 = 20;
    el.__items = steps.map(([t, s_], i) => {
      const g = svgEl('g', {}, svg), y = 10 + i * (bh + gap);
      strokePath(g, roughRect(x0, y, bw, bh, { seed: 1500 + i }), { color: i === 2 ? C.cardinal : C.ink, width: 2.6 });
      text(g, x0 + 24, y + 42, t, { size: 32, weight: 600, family: 'var(--serif)', color: i === 2 ? C.cardinal : C.ink });
      wrapText(g, x0 + 24, y + 76, s_, bw - 70, 22, 'rgba(46,45,41,.7)');
      if (i < steps.length - 1) strokePath(g, roughArrow(x0 + bw / 2, y + bh + 4, x0 + bw / 2, y + bh + gap - 4, { seed: 1510 + i, head: 12 }), { color: C.ink, width: 2.4 });
      return g;
    });
    // Loop back from Repeat to Sample.
    const yTop = 10 + bh / 2, yBot = 10 + 3 * (bh + gap) + bh / 2, xr = x0 + bw + 50;
    const back = svgEl('g', {}, svg);
    strokePath(back, roughPolyline([[x0 + bw + 4, yBot], [xr, yBot], [xr, yTop]], { seed: 1520 }), { color: C.lagunita, width: 2.6 });
    strokePath(back, roughArrow(xr, yTop, x0 + bw + 6, yTop, { seed: 1521, head: 12 }), { color: C.lagunita, width: 2.6 });
    const yP = 10 + 4 * (bh + gap) + 30;
    text(back, x0 + bw / 2, yP, 'Pc ≈ hits / samples', { size: 30, anchor: 'middle', weight: 600, color: C.lagunita });
    el.__back = back;
  },
  animate(el, d, s, A) { el.__items.forEach((g, i) => fadeIn(g, A, 200 + i * 250)); fadeIn(el.__back, A, 1300); },
};

/* ---------- Monte Carlo method: samples accumulating, then convergence ---------- */
figures.mcMethod = {
  needs: ['pc'],
  render(el, d) {
    const E = d.pc.example, P = E.encounter_plane, R = E.mc_running, W = el.offsetWidth;
    const svg = svgFor(el);
    // Top: encounter-plane samples (first 3,000 of the run) and the hard-body circle.
    const tw = W, th = 300, cx = tw * 0.4, cy = th / 2 + 10;
    const e3 = ellipseFromCov(P.cov_xy_m2, 3), k = (tw * 0.38) / e3.rx;
    const to = ([x, y]) => [cx + x * k, cy - y * k];
    text(svg, 0, 18, 'Encounter plane: one dot per sample', { size: 22, color: 'rgba(46,45,41,.6)' });
    const dots = svgEl('g', {}, svg);
    el.__dots = (P.mc_samples_xy_m || []).map((q, i) => { const [x, y] = to(q); return svgEl('circle', { cx: x, cy: y, r: P.mc_hit[i] ? 2.5 : 2, fill: P.mc_hit[i] ? C.cardinal : 'rgba(46,45,41,.3)' }, dots); });
    el.__hitFlags = P.mc_hit;
    const rH = E.hbr_m * k;
    svgEl('circle', { cx, cy, r: rH, fill: 'none', stroke: C.cardinal, 'stroke-width': 2 }, svg);
    svgEl('line', { x1: cx + rH * 0.7, y1: cy - rH * 0.7, x2: cx + 70, y2: cy - 70, stroke: C.cardinal, 'stroke-width': 1.5 }, svg);
    text(svg, cx + 76, cy - 74, `hard-body radius ${fmt(E.hbr_m, 0)} m`, { size: 22, color: C.cardinal });
    el.__counter = text(svg, tw - 10, 60, '', { size: 28, anchor: 'end', weight: 600 });
    el.__counter2 = text(svg, tw - 10, 96, '', { size: 24, anchor: 'end', color: 'rgba(46,45,41,.65)' });
    el.__setCount = n => {
      const hits = el.__hitFlags.slice(0, n).filter(Boolean).length;
      el.__counter.textContent = `${fmtInt(n)} samples · ${hits} hit${hits === 1 ? '' : 's'}`;
      el.__counter2.textContent = hits ? `Pc ≈ ${(hits / n).toExponential(1)}` : 'Pc ≈ 0 so far';
      el.__dots.forEach((c, i) => c.setAttribute('display', i < n ? 'inline' : 'none'));
    };
    el.__setCount(el.__dots.length);
    // Bottom (on click): running estimate with its 95% interval vs number of samples.
    const conv = svgEl('g', { 'data-step': 1 }, svg);
    const sub = svgEl('svg', { x: 0, y: 330, width: W, height: 370, overflow: 'visible' }, conv);
    sub.setAttribute('width', W); sub.setAttribute('height', 370);
    const ax = axes(sub, { xr: [10, R.n[R.n.length - 1]], yr: [0, 0.006], xlog: true, xfmt: v => pow10(Math.round(Math.log10(v))), xlabel: 'samples', ylabel: 'estimated Pc', yticks: [0, 0.002, 0.004, 0.006], yfmt: v => (v ? `${v * 1000}×10⁻³` : '0'), left: 120, right: 160, top: 10, bottom: 70, seed: 1530 });
    const band = R.n.map((n, i) => [ax.x(n), ax.y(Math.min(R.ci95_hi[i], 0.006))]).concat(R.n.map((n, i) => [ax.x(n), ax.y(R.ci95_lo[i])]).reverse());
    exactPath(sub, band, { color: 'none', width: 0, fill: 'rgba(0,108,184,0.16)', closed: true });
    exactPath(sub, R.n.map((n, i) => [ax.x(n), ax.y(Math.min(R.pc[i], 0.006))]), { color: C.lagunita, width: 3 });
    const yF = ax.y(E.pc_foster);
    svgEl('line', { x1: ax.box.x0, x2: ax.box.x1, y1: yF, y2: yF, stroke: C.cardinal, 'stroke-width': 2, 'stroke-dasharray': '8 7' }, sub);
    text(sub, ax.box.x1 + 10, yF + 8, `Foster ${E.pc_foster.toExponential(2)}`, { size: 22, color: C.cardinal, weight: 600 });
    text(sub, ax.x(1e3), ax.y(0.0055), 'estimate with 95% interval', { size: 22, color: C.lagunita });
  },
  animate(el, d, s, A) {
    const n = el.__dots.length;
    el.__setCount(0);
    return loop(t => { const f = Math.min(1, Math.max(0, (t - 600) / 4500)); el.__setCount(Math.round(n * f * f)); return f < 1; });
  },
};

/* ---------- Foster 2D Pc in the encounter plane ---------- */
function ellipseFromCov(cov, nsig) {
  const [[a, b], [, c]] = cov, tr = a + c, det = a * c - b * b, l1 = tr / 2 + Math.sqrt(tr * tr / 4 - det), l2 = tr / 2 - Math.sqrt(Math.max(0, tr * tr / 4 - det));
  const ang = Math.atan2(l1 - a, b || 1e-12);
  return { rx: nsig * Math.sqrt(l1), ry: nsig * Math.sqrt(Math.max(l2, 0)), ang };
}

// Gaussian density drawn as an image; toM maps a pixel in the image to encounter-plane metres.
function gaussImage(parent, x, y, w, h, toM, dens) {
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const g = cv.getContext('2d'), img = g.createImageData(w, h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const o = 4 * (j * w + i);
    img.data[o + 1] = 108; img.data[o + 2] = 184; img.data[o + 3] = 150 * dens(...toM(x + i + 0.5, y + j + 0.5));
  }
  g.putImageData(img, 0, 0);
  return svgEl('image', { href: cv.toDataURL(), x, y, width: w, height: h }, parent);
}

figures.foster = {
  needs: ['pc'],
  render(el, d) {
    const E = d.pc.example, P = E.encounter_plane, svg = svgFor(el), W = el.offsetWidth, H = el.offsetHeight;
    const [[a, b], [, c]] = P.cov_xy_m2, det = a * c - b * b, [mxm, mym] = P.miss_xy_m;
    const dens = (x, y) => { const u = x - mxm, v = y - mym; return Math.exp(-0.5 * (c * u * u - 2 * b * u * v + a * v * v) / det); };
    // Secondary at the origin of the encounter plane; the combined covariance is centered on the predicted miss.
    const cx = W / 2, cy = H / 2 - 20;
    const k = Math.min((W / 2 - 20) / (3 * Math.sqrt(a) + Math.abs(mxm)), (H / 2 - 70) / (3 * Math.sqrt(c) + Math.abs(mym)));
    const to = ([x, y]) => [cx + x * k, cy - y * k];
    const [mx, my] = to(P.miss_xy_m);
    text(svg, 0, 24, 'Encounter plane (perpendicular to the relative velocity)', { size: 22, color: 'rgba(46,45,41,.6)' });

    const unc = svgEl('g', { 'data-step': 1 }, svg);
    gaussImage(unc, 0, 40, W, H - 40, (px, py) => [(px - cx) / k, (cy - py) / k], dens);
    [1, 2, 3].forEach(ns => {
      const e = ellipseFromCov(P.cov_xy_m2, ns);
      exactPath(unc, circlePts(mx, my, e.rx * k, e.ry * k, -e.ang), { color: C.lagunita, width: ns === 1 ? 3 : 1.6, opacity: 1.1 - ns * 0.25 });
    });
    const [s1, s2] = P.sigma_major_minor_m;
    legend(unc, W - 380, 70, [[`1σ, 2σ, 3σ: ${fmtInt(s1)} m × ${fmtInt(s2)} m`, C.lagunita]], { size: 22 });

    el.__miss = strokePath(svg, roughArrow(cx, cy, mx, my, { seed: 601, head: 14 }), { color: C.ink, width: 2.6 });
    svgEl('circle', { cx, cy, r: 4, fill: C.ink }, svg);
    svgEl('circle', { cx: mx, cy: my, r: 4, fill: C.ink }, svg);
    text(svg, cx - 12, cy - 14, 'secondary', { size: 22, anchor: 'end' });
    text(svg, mx + 12, my - 14, 'primary', { size: 22 });
    text(svg, (cx + mx) / 2, cy + 34, `${fmtInt(E.miss_m)} m`, { size: 24, weight: 600, anchor: 'middle' });

    // Zoom on the hard-body disk around the secondary.
    const ins = svgEl('g', { 'data-step': 3 }, svg);
    const s = 270, ix = 20, iy = H - s - 60, icx = ix + s / 2, icy = iy + s / 2, hw = 3 * E.hbr_m, ks = (s / 2) / hw;
    svgEl('line', { x1: cx, y1: cy, x2: ix + s, y2: iy, stroke: 'rgba(46,45,41,.35)', 'stroke-width': 1.5, 'stroke-dasharray': '5 6' }, ins);
    svgEl('line', { x1: cx, y1: cy, x2: ix, y2: iy, stroke: 'rgba(46,45,41,.35)', 'stroke-width': 1.5, 'stroke-dasharray': '5 6' }, ins);
    svgEl('rect', { x: ix, y: iy, width: s, height: s, fill: C.board }, ins);
    gaussImage(ins, ix, iy, s, s, (px, py) => [(px - icx) / ks, (icy - py) / ks], dens);
    svgEl('line', { x1: icx, y1: icy, x2: ix + s, y2: icy - (s / 2) * (mym / mxm || 0), stroke: C.ink, 'stroke-width': 2 }, ins);
    svgEl('circle', { cx: icx, cy: icy, r: E.hbr_m * ks, fill: 'rgba(140,21,21,.22)', stroke: C.cardinal, 'stroke-width': 3 }, ins);
    svgEl('circle', { cx: icx, cy: icy, r: 4, fill: C.ink }, ins);
    strokePath(ins, roughRect(ix, iy, s, s, { seed: 611 }), { color: C.ink, width: 2.2 });
    text(ins, ix, iy + s + 32, `hard-body disk, R = ${fmt(E.hbr_m, 0)} m (${Math.round(ks / k)}× zoom)`, { size: 22, color: C.cardinal });
  },
  animate(el, d, s, A) { drawOnAnim([el.__miss], A, 300, 700); },
};

/* ---------- CDM card ---------- */
figures.cdmCard = {
  needs: ['pc'],
  render(el, d) {
    const E = d.pc.example, C1 = E.ellipsoids?.cov1_rtn_m2, C2 = E.ellipsoids?.cov2_rtn_m2;
    const rows = [
      ['CCSDS_CDM_VERS', '2.0'],
      ['TCA', E.tca_utc || '2026-11-13T04:21:37.215'],
      ['MISS_DISTANCE', `${fmt(E.miss_m, 1)} [m]`],
      ['RELATIVE_SPEED', `${fmt(E.rel_speed_kms * 1000, 1)} [m/s]`],
      ['COLLISION_PROBABILITY', E.pc_foster.toExponential(3)],
      ['COLLISION_PROBABILITY_METHOD', 'FOSTER-1992'],
      ['OBJECT', 'OBJECT1'],
      ['CR_R', `${fmt(C1?.[0]?.[0] ?? 0, 1)} [m**2]`],
      ['CT_T', `${fmt(C1?.[1]?.[1] ?? 0, 1)} [m**2]`],
      ['OBJECT', 'OBJECT2'],
      ['CR_R', `${fmt(C2?.[0]?.[0] ?? 0, 1)} [m**2]`],
      ['CT_T', `${fmt(C2?.[1]?.[1] ?? 0, 1)} [m**2]`],
    ];
    el.innerHTML = `<div data-rough="box" data-color="ink" data-rough-key="cdm" style="position:absolute; inset:0; padding:36px 44px; font-family:'Source Code Pro', Menlo, monospace; font-size:25px; line-height:1.6; background:rgba(255,255,255,.4)">${rows.map(([k, v]) => `<div><span style="color:var(--ink-50)">${k.padEnd(28, ' ').replace(/ /g, '&nbsp;')}</span>= <b style="color:${/PROBABILITY$|MISS/.test(k) ? 'var(--cardinal)' : 'var(--ink)'}">${v}</b></div>`).join('')}</div>`;
  },
  animate(el, d, s, A) { fadeIn(el.firstElementChild, A, 300, 900); },
};

/* ---------- maneuver trade space ---------- */
figures.tradespace = {
  needs: ['maneuver'],
  render(el, d) {
    const M = d.maneuver, svg = svgFor(el), W = el.offsetWidth;
    const L = M.lead_h, V = M.dv_cms, Z = M.log10_pc;
    const xe = L.map((l, i) => i === 0 ? l / Math.sqrt(L[1] / L[0]) : Math.sqrt(L[i - 1] * l)).concat([L[L.length - 1] * Math.sqrt(L[L.length - 1] / L[L.length - 2])]);
    const dv = V[1] - V[0];
    const ax = axes(svg, { xr: [xe[0], xe[xe.length - 1]], yr: [V[0] - dv / 2, V[V.length - 1] + dv / 2], xlog: true, xticks: [1, 3, 6, 12, 24, 48, 72].filter(v => v >= xe[0] && v <= xe[xe.length - 1]), xlabel: 'burn time before closest approach (hours, log scale)', ylabel: 'along-track Δv (cm/s)', right: 300, seed: 701 });
    const zmin = -10, zmax = Math.max(...Z.flat());
    const color = z => { const f = Math.min(1, Math.max(0, (z - zmin) / (zmax - zmin))); return `rgba(140,21,21,${(0.04 + 0.86 * f * f).toFixed(3)})`; };
    el.__cells = svgEl('g', {}, svg);
    L.forEach((l, i) => V.forEach((v, j) => {
      const x0 = ax.x(xe[i]), x1 = ax.x(xe[i + 1]), y0 = ax.y(v + dv / 2), y1 = ax.y(v - dv / 2);
      svgEl('rect', { x: x0, y: y0, width: x1 - x0 + 0.6, height: y1 - y0 + 0.6, fill: color(Z[i][j]) }, el.__cells);
    }));
    const runs = [[]];
    M.min_dv_cms.forEach((v, i) => { if (v == null) { if (runs[runs.length - 1].length) runs.push([]); } else runs[runs.length - 1].push([ax.x(L[i]), ax.y(v)]); });
    el.__curve = svgEl('g', { 'data-step': 1 }, svg);
    runs.filter(r => r.length > 1).forEach(r => exactPath(el.__curve, r, { color: C.green, width: 4.5 }));
    el.__curvePts = svgEl('g', { 'data-step': 1 }, svg);
    runs.flat().forEach(p => svgEl('circle', { cx: p[0], cy: p[1], r: 6, fill: C.green }, el.__curvePts));
    M.min_dv_cms.forEach((v, i) => { if (v == null) text(el.__curvePts, ax.x(L[i]), ax.box.y1 - 4, 'none ≤ 10', { size: 20, anchor: 'middle', color: C.cardinal }); });
    const i24 = L.indexOf(24);
    if (i24 >= 0 && M.min_dv_cms[i24] != null) {
      const px = ax.x(24), py = ax.y(M.min_dv_cms[i24]), tx = px, ty = ax.y(V[V.length - 1] * 0.55);
      strokePath(el.__curvePts, roughArrow(tx, ty + 14, px, py - 12, { seed: 705, head: 14 }), { color: C.green, width: 2.6 });
      text(el.__curvePts, tx, ty - 40, `smallest Δv for Pc < 1 in ${fmtInt(1 / M.threshold)}`, { size: 25, color: C.green, weight: 600, anchor: 'middle' });
      text(el.__curvePts, tx, ty - 6, `${fmt(M.min_dv_cms[i24], 2)} cm/s one day out`, { size: 25, color: C.green, anchor: 'middle' });
    }
    const bar = svgEl('g', {}, svg), bx = W - 220, by = ax.box.y1 + 20, bh = 300;
    for (let k = 0; k < 40; k++) svgEl('rect', { x: bx, y: by + k * bh / 40, width: 36, height: bh / 40 + 0.5, fill: color(zmax - (zmax - zmin) * k / 40) }, bar);
    text(bar, bx + 50, by + 16, `Pc ${pow10(Math.round(zmax))}`, { size: 22 });
    text(bar, bx + 50, by + bh, `≤ ${pow10(zmin)}`, { size: 22 });
    el.__bar = bar;
  },
  animate(el, d, s, A) { A.push(el.__cells.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: 1400, delay: 200, easing: EASE_MOVE, ...FILL })); fadeIn(el.__bar, A, 600); },
};

/* ---------- Pc evolution ---------- */
figures.pcEvolution = {
  needs: ['pc_evolution'],
  render(el, d) {
    const P = d.pc_evolution, svg = svgFor(el), W = el.offsetWidth;
    const all = P.scenarios.flatMap(s => s.updates.map(u => u.pc)).filter(v => v > 0);
    const tmax = Math.max(...P.scenarios.flatMap(s => s.updates.map(u => u.t_before_tca_h)));
    const ymin = Math.max(1e-10, Math.pow(10, Math.floor(Math.log10(Math.min(...all)))));
    const days = Array.from({ length: Math.floor(tmax / 24) + 1 }, (_, i) => i);
    const ax = axes(svg, { xr: [tmax / 24, 0], yr: [ymin, 1], ylog: true, xticks: days, yticks: decades([ymin, 1]).filter(v => Math.round(Math.log10(v)) % 2 === 0), xlabel: 'days before closest approach', ylabel: 'probability of collision', right: 640, seed: 801, yfmt: v => v === 1 ? '1' : pow10(Math.round(Math.log10(v))) });
    const thr = ax.y(1e-4);
    strokePath(svg, roughLine(ax.box.x0, thr, ax.box.x1, thr, { seed: 802, passes: 1 }), { color: 'rgba(46,45,41,.45)', width: 2 });
    text(svg, ax.box.x1 + 14, thr + 8, '1 in 10,000', { size: 22, color: 'rgba(46,45,41,.6)' });
    const cols = [C.green, C.cardinal, C.lagunita];
    el.__lines = P.scenarios.map((s, k) => {
      const g = svgEl('g', k ? { 'data-step': k } : {}, svg), pts = s.updates.map(u => [ax.x(u.t_before_tca_h / 24), ax.y(Math.max(u.pc, 1e-10))]);
      exactPath(g, pts, { color: cols[k % 3], width: 3.5 });
      pts.forEach(p => svgEl('circle', { cx: p[0], cy: p[1], r: 6, fill: cols[k % 3] }, g));
      const last = pts[pts.length - 1];
      s.name.split(': ').forEach((part, j) => text(g, ax.box.x1 + 14, last[1] + 8 + j * 28, part, { size: j ? 22 : 24, color: cols[k % 3], weight: j ? 400 : 600 }));
      return g;
    });
    const F = P.false_alarm_stats;
    if (F) {
      const g = svgEl('g', { 'data-step': P.scenarios.length }, svg), x0 = W - 400, y0 = 60;
      text(g, x0, y0, `${fmtInt(F.by_true_miss[0].runs)} simulated events each:`, { size: 24, color: 'rgba(46,45,41,.7)' });
      text(g, x0, y0 + 50, 'true miss', { size: 22, color: 'rgba(46,45,41,.6)' });
      text(g, x0 + 150, y0 + 50, 'Pc ≥ 10⁻⁴', { size: 22, color: 'rgba(46,45,41,.6)' });
      text(g, x0 + 150, y0 + 76, `≥ ${F.early_h / 24} day out`, { size: 22, color: 'rgba(46,45,41,.6)' });
      text(g, x0 + 290, y0 + 50, 'still', { size: 22, color: 'rgba(46,45,41,.6)' });
      text(g, x0 + 290, y0 + 76, 'at 6 h', { size: 22, color: 'rgba(46,45,41,.6)' });
      F.by_true_miss.forEach((r, i) => {
        const y = y0 + 130 + i * 50, safe = r.true_miss_m >= 200;
        text(g, x0, y, r.true_miss_m >= 1000 ? `${r.true_miss_m / 1000} km` : `${r.true_miss_m} m`, { size: 28, weight: 600, color: r.true_miss_m < 100 ? C.cardinal : C.ink });
        text(g, x0 + 150, y, `${Math.round(100 * r.frac_alarm_early)}%`, { size: 28, color: safe && r.frac_alarm_early > 0.1 ? C.cardinal : C.ink });
        text(g, x0 + 290, y, `${Math.round(100 * r.frac_alarm_last)}%`, { size: 28, color: r.frac_alarm_last < 0.05 ? C.green : C.ink });
      });
      el.__stats = g;
    }
  },
  animate(el, d, s, A) {
    const draw = (g, d0) => {
      drawOnAnim([g.querySelector('path')], A, d0, 1600);
      g.querySelectorAll('circle').forEach((c, i, arr) => fadeIn(c, A, d0 + 1600 * i / arr.length, 250));
      g.querySelectorAll('text').forEach(t => fadeIn(t, A, d0 + 1600));
    };
    draw(el.__lines[0], 400);
    return onStep(el, 1, () => el.__lines.slice(1).forEach(g => draw(g, 0)));
  },
};

/* ---------- decision ladder ---------- */
figures.decisionLadder = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth;
    const steps = [
      ['Fixed rules', '"If Pc > 1 in 10,000 at 24 h, maneuver."', 'Industry standard. Simple, auditable, often wasteful.', C.gray],
      ['Trade-space tables', 'Maneuver size vs. time vs. residual risk.', 'Shows the cost of waiting.', C.ink],
      ['Sequential decisions', 'A POMDP: act on beliefs, value future information.', 'Kim, Eddy & Kochenderfer, AMOS 2026 · Kim et al., AAS 2026', C.cardinal],
    ];
    const sw = 500, gap = (W - 3 * sw) / 2;
    el.__steps = steps.map(([t, a, b, col], i) => {
      const g = svgEl('g', i ? { 'data-step': i } : {}, svg), x = i * (sw + gap), y = 360 - i * 150, h = 280;
      strokePath(g, roughRect(x, y, sw, h, { seed: 900 + i }), { color: col, width: i === 2 ? 3.4 : 2.6 });
      text(g, x + 30, y + 62, t, { size: 42, weight: 600, family: 'var(--serif)', color: col === C.gray ? 'rgba(46,45,41,.7)' : col });
      wrapText(g, x + 30, y + 118, a, sw - 60, 31, C.ink);
      wrapText(g, x + 30, y + 210, b, sw - 60, 25, 'rgba(46,45,41,.6)', true);
      if (i < 2) strokePath(g, roughArrow(x + sw + 10, y + 40, x + sw + gap - 10, y - 60, { seed: 910 + i, head: 18 }), { color: C.ink, width: 2.6 });
      return g;
    });
  },
  animate(el, d, s, A) { A.push(el.__steps[0].animate([{ opacity: 0, transform: 'translateY(30px)' }, { opacity: 1, transform: 'none' }], { duration: 700, delay: 300, easing: EASE_IN, ...FILL })); },
};

function wrapText(parent, x, y, str, width, size, color, italic = false) {
  const words = str.split(' '), lines = [];
  let cur = '';
  const cpp = width / (size * 0.5);
  words.forEach(w => { if ((cur + ' ' + w).trim().length > cpp) { lines.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); });
  lines.push(cur);
  lines.forEach((l, i) => text(parent, x, y + i * size * 1.3, l, { size, color, italic }));
}

/* ---------- after a maneuver ---------- */
figures.afterManeuver = {
  render(el) {
    const svg = svgFor(el), W = el.offsetWidth;
    const steps = [['Plan maneuver', C.ink], ['Re-screen new trajectory', C.ink], ['Publish OEM with the burn', C.lagunita], ['Space Force screens it (4 to 12 h)', C.ink], ['New CDMs?', C.cardinal]];
    const bw = 280, gap = (W - steps.length * bw) / (steps.length - 1), y = 120, h = 150;
    el.__items = steps.map(([s, col], i) => {
      const g = svgEl('g', {}, svg), x = i * (bw + gap);
      strokePath(g, roughRect(x, y, bw, h, { seed: 950 + i }), { color: col, width: 2.8 });
      wrapText(g, x + 24, y + 60, s, bw - 48, 31, col);
      if (i < steps.length - 1) strokePath(g, roughArrow(x + bw + 8, y + h / 2, x + bw + gap - 8, y + h / 2, { seed: 960 + i, head: 14 }), { color: C.ink, width: 2.6 });
      return g;
    });
    const back = svgEl('g', { 'data-step': 1 }, svg), xL = (steps.length - 1) * (bw + gap) + bw / 2, x0 = bw / 2;
    strokePath(back, roughPolyline([[xL, y + h + 10], [xL, y + h + 120], [x0, y + h + 120]], { seed: 970 }), { color: C.cardinal, width: 2.6 });
    strokePath(back, roughArrow(x0, y + h + 120, x0, y + h + 12, { seed: 971, head: 16 }), { color: C.cardinal, width: 2.6 });
    text(back, (xL + x0) / 2, y + h + 160, 'repeat until TCA', { size: 26, anchor: 'middle', color: C.cardinal, italic: true });
    el.__back = back;
  },
  animate(el, d, s, A) { el.__items.forEach((g, i) => fadeIn(g, A, 300 + i * 350)); },
};

/* ---------- covariance banana (interactive) ---------- */
figures.banana = {
  needs: ['covariance_banana'],
  render(el, d) {
    const B = d.covariance_banana, snaps = B.snapshots, W = el.offsetWidth, H = el.offsetHeight;
    const svg = svgFor(el), pw = W - 40, ph = H - 150;
    const last = snaps[snaps.length - 1];
    const xs = last.samples_xy_km.map(p => p[0]), ys = last.samples_xy_km.map(p => p[1]);
    const xr = Math.max(...xs.map(Math.abs)) * 1.15, yr = Math.max(Math.max(...ys.map(Math.abs)) * 1.3, 1);
    const kx = Math.min((pw / 2) / xr, (ph / 2) / yr), ky = kx;
    const cx = pw / 2 + 20, cy = ph / 2 + 10;
    const to = ([x, y]) => [cx + x * kx, cy - y * ky];
    strokePath(svg, roughLine(20, cy, pw + 20, cy, { seed: 1001, passes: 1 }), { color: 'rgba(46,45,41,.25)', width: 1.6 });
    strokePath(svg, roughLine(cx, 10, cx, ph + 10, { seed: 1002, passes: 1 }), { color: 'rgba(46,45,41,.25)', width: 1.6 });
    text(svg, pw + 10, cy + 32, 'along-track', { size: 22, anchor: 'end', color: 'rgba(46,45,41,.6)' });
    text(svg, cx + 12, 32, 'radial', { size: 22, color: 'rgba(46,45,41,.6)' });
    const bar = 500 * kx;
    strokePath(svg, roughLine(pw + 20 - bar, ph - 10, pw + 20, ph - 10, { seed: 1003, passes: 1 }), { color: C.ink, width: 2.4 });
    text(svg, pw + 20 - bar / 2, ph - 22, '500 km, same scale on both axes', { size: 22, anchor: 'middle', color: 'rgba(46,45,41,.7)' });
    const arc = svgEl('path', { stroke: 'rgba(46,45,41,.4)', 'stroke-width': 2, fill: 'none', 'stroke-dasharray': '6 8' }, svg);
    const ell = svgEl('path', { stroke: C.lagunita, 'stroke-width': 3.5, fill: 'rgba(0,108,184,.06)' }, svg);
    const dots = svgEl('g', {}, svg);
    const label = text(svg, 30, ph + 70, '', { size: 28, weight: 600 });
    legend(svg, W - 560, ph + 60, [['Monte Carlo samples (with drag)', C.cardinal, 'dot'], ['linearized 3σ ellipse', C.lagunita]], { gap: 36 });
    const N = Math.min(...snaps.map(s => s.samples_xy_km.length));
    const circles = Array.from({ length: N }, () => svgEl('circle', { r: 3, fill: 'rgba(140,21,21,.55)' }, dots));
    el.__show = f => {
      const x = f * (snaps.length - 1), i = Math.min(snaps.length - 2, Math.floor(x)), u = x - i;
      const A_ = snaps[i], B_ = snaps[i + 1] || A_;
      for (let k = 0; k < N; k++) {
        const p = A_.samples_xy_km[k], q = B_.samples_xy_km[k];
        const [sx, sy] = to([p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u]);
        circles[k].setAttribute('cx', sx.toFixed(1)); circles[k].setAttribute('cy', sy.toFixed(1));
      }
      const S = u < 0.5 ? A_ : B_;
      const cov = A_.ellipse_cov_km2.map((r, a) => r.map((v, b) => v + (B_.ellipse_cov_km2[a][b] - v) * u));
      const e = ellipseFromCov(cov, 3);
      const pts = circlePts(0, 0, e.rx, e.ry, e.ang).map(p => to(p));
      ell.setAttribute('d', linPath(pts) + 'Z');
      arc.setAttribute('d', linPath(S.arc_xy_km.map(to)));
      const t = A_.t_h + (B_.t_h - A_.t_h) * u;
      label.textContent = `${fmt(t / 24, 1)} days after the last observation`;
    };
    el.__show(0);
    // Slider
    const sl = document.createElement('div');
    sl.className = 'slider interactive';
    sl.style.cssText = `left:${W * 0.15}px; width:${W * 0.4}px; top:${H - 70}px;`;
    sl.innerHTML = '<div class="track"></div><div class="fill"></div><div class="thumb"></div>';
    el.appendChild(sl);
    const set = f => { f = Math.min(1, Math.max(0, f)); sl.querySelector('.thumb').style.left = `${f * 100}%`; sl.querySelector('.fill').style.width = `${f * 100}%`; el.__show(f); el.__f = f; };
    el.__set = set;
    set(0);
    const k = () => el.closest('#stage').__k || 1;
    const onMove = e => { const r = sl.getBoundingClientRect(); set((e.clientX - r.left) / r.width); };
    sl.addEventListener('pointerdown', e => { e.stopPropagation(); el.__user = true; sl.setPointerCapture(e.pointerId); onMove(e); sl.onpointermove = onMove; });
    sl.addEventListener('pointerup', e => { sl.onpointermove = null; });
    sl.addEventListener('click', e => e.stopPropagation());
  },
  animate(el, d, s, A) {
    el.__user = false;
    el.__set(0);
    return loop(t => { if (el.__user) return false; if (t < 800) return true; const f = Math.min(1, (t - 800) / 5000); el.__set(f); return f < 1; });
  },
};

/* ---------- resources ---------- */
figures.resources = {
  render(el) {
    const items = [
      ['Space-Track.org', 'Catalog (GP/OMM), CDMs, ephemeris screening, SSA sharing agreements', 'space-track.org'],
      ['TraCSS', 'Office of Space Commerce traffic coordination (pilot)', 'space.commerce.gov'],
      ['space-safety.com', 'SpaceX coordination platform: share ephemerides, screen in minutes', 'space-safety.com'],
      ['NASA CA Handbook', 'Conjunction Assessment Best Practices, Rev. 2 (2026), two volumes', 'nasa.gov/cara'],
      ['CARA Analysis Tools', 'Reference Pc implementations (2D, 3D, Monte Carlo)', 'github.com/nasa/CARA_Analysis_Tools'],
      ['Spaceflight Safety Handbook', 'Space Force services, screening volumes, criteria (v1.7)', 'space-track.org/documents'],
      ['CelesTrak', 'GP data, SOCRATES, documentation, history', 'celestrak.org'],
      ['brahe', 'Open-source astrodynamics in Rust and Python', 'github.com/duncaneddy/brahe'],
    ];
    el.innerHTML = items.map(([t, s, u], i) => `<div class="card" data-rough="box" data-rough-key="res${i}" style="left:${(i % 4) * 410}px; top:${Math.floor(i / 4) * 340}px; width:380px; height:300px; text-align:left;"><h3 style="font-size:34px">${t}</h3><p style="font-size:24px">${s}</p><p class="sans" style="font-style:normal; font-size:22px; margin-top:14px; color:var(--lagunita); overflow-wrap:anywhere">${u}</p></div>`).join('');
  },
  animate(el, d, s, A) { [...el.children].forEach((c, i) => A.push(c.animate([{ opacity: 0, transform: 'translateY(24px)' }, { opacity: 1, transform: 'none' }], { duration: 600, delay: 200 + i * 120, easing: EASE_IN, ...FILL }))); },
};

/* ---------- brahe pipeline ---------- */
/* ---------- adopters ---------- */
figures.adopters = {
  render(el) {
    const logos = [['Northwood', 'northwood.svg'], ['Xona', 'xona.svg'], ['Capella', 'capella.svg'], ['AWS', 'aws.svg'], ['D-Orbit USA', 'd-orbit-usa.svg'], ['KSAT', 'ksat.svg'], ['HEO', 'heo.png'], ['Trusted Space', 'trusted-space.png'], ['K2 Space', 'k2-space.svg'], ['Vyoma', 'vyoma.svg'], ['Orbital Sidekick', 'orbital-sidekick.svg']];
    el.innerHTML = logos.map(([n, file], i) => `<div class="logo-cell" data-rough="box" data-color="dim" data-rough-key="ad${i}" style="position:absolute; left:${(i % 4) * 405}px; top:${Math.floor(i / 4) * 190}px; width:370px; height:150px; display:flex; align-items:center; justify-content:center; padding:24px 16px;"><img src="img/logos/${file}" alt="${n}" style="width:100%; height:100%; object-fit:contain;"></div>`).join('');
  },
  animate(el, d, s, A) { [...el.children].forEach((c, i) => A.push(c.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 200 + i * 90, easing: EASE_IN, ...FILL }))); },
};

/* ---------- repo link ---------- */
figures.repoLink = {
  render(el) {
    el.innerHTML = `<div style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; gap:36px;"><img src="img/repo-qr.png" alt="QR code for the lecture repository" style="height:100%;"><div class="sans" style="font-size:30px; color:var(--ink-50); line-height:1.4">Scripts and slides<br><b style="color:var(--lagunita)">github.com/duncaneddy/2026_aa279b_space_safety</b></div></div>`;
  },
  animate(el, d, s, A) { fadeIn(el.firstElementChild, A, 1200); },
};

/* ---------- backup: all-vs-all ---------- */
figures.allVsAll = {
  needs: ['screening'],
  render(el, d) {
    const P = d.screening.all_vs_all_paper, svg = svgFor(el), W = el.offsetWidth;
    const rows = [['Brute force', P.brute, C.gray], ['Fixed 50 km apsis threshold', P.fixed50, C.ink], ['Adaptive (covariance-based)', P.adaptive, C.lagunita]];
    const bx = 520, bw = W - bx - 260;
    el.__bars = rows.map(([n, v, col], i) => {
      const g = svgEl('g', {}, svg), y = 60 + i * 150;
      text(g, bx - 24, y + 52, n, { size: 30, anchor: 'end', color: col === C.gray ? 'rgba(46,45,41,.6)' : col, family: 'var(--serif)' });
      svgEl('rect', { x: bx, y, width: bw * v / P.brute, height: 80, fill: col, opacity: 0.25 }, g);
      text(g, bx + bw * v / P.brute + 18, y + 52, `${fmt(v / 1e6, 1)} M (${fmt(100 * v / P.brute, 1)}%)`, { size: 28, weight: 600, color: col });
      return g;
    });
  },
  animate(el, d, s, A) { el.__bars.forEach((g, i) => fadeIn(g, A, 300 + i * 400)); },
};

/* ---------- backup: SSN table ---------- */
figures.ssnTable = {
  needs: ['ssn_sensors'],
  render(el, d) {
    const S = d.ssn_sensors.sensors;
    el.innerHTML = `<table class="sans" style="width:100%; border-collapse:collapse; font-size:22px;">
      <tr style="text-align:left; color:var(--ink-50)"><th>Sensor</th><th>System</th><th>Type</th><th>Lat</th><th>Lon</th><th>Min el (°)</th><th>Max range (km)</th></tr>
      ${S.map(s => `<tr><td>${s.name}</td><td>${s.system}</td><td>${s.type}</td><td>${fmt(s.lat, 1)}</td><td>${fmt(s.lon, 1)}</td><td>${s.el_min_deg ?? ''}</td><td>${s.range_max_km ? fmtInt(s.range_max_km) : ''}</td></tr>`).join('')}
    </table>`;
  },
};

/* ======================= slide-level animations ======================= */

export const slideAnims = {};
