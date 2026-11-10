// Deck shell: stage scaling, navigation, continuation clones, generic entry choreography,
// magic moves between adjacent slides, breadcrumb/question chrome, and speaker notes.
import { decorate } from './sketch.js';
import { figures, slideAnims, binds, DATA_FILES } from './figs.js';

const EASE_IN = 'cubic-bezier(.2,.7,.2,1)';
const EASE_MOVE = 'cubic-bezier(.65,0,.25,1)';
const FILL = { fill: 'both' };
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const stage = document.getElementById('stage');
const sections = [...stage.querySelectorAll(':scope > section.slide')];
const STAGES = ['Measure', 'Catalog', 'Screen', 'Assess', 'Decide', 'Share'];
let current = -1, previous = -1;
const data = {};

/* ---------------- layout ---------------- */

function fit() {
  const k = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = `translate(${(innerWidth - 1920 * k) / 2}px, ${(innerHeight - 1080 * k) / 2}px) scale(${k})`;
  stage.__k = k;
}
addEventListener('resize', fit);
fit();

/* ---------------- chrome ---------------- */

const chrome = document.getElementById('chrome');
const crumbs = document.getElementById('crumbs');

// Continuation slides (data-clone) are builds of the slide before them and share its number;
// lifecycle section dividers are their own slides.
const isBuild = s => s.dataset.clone && !s.dataset.lcCurrent;
const slideNumber = i => sections.slice(0, i + 1).filter(s => !isBuild(s)).length;

function updateChrome(sec) {
  const st = sec.dataset.stage;
  crumbs.classList.toggle('on', !!st);
  if (st) crumbs.textContent = st;
  const num = document.querySelector('#footer .num');
  const backupStart = sections.findIndex(s => s.dataset.label === 'Backup');
  num.textContent = backupStart >= 0 && current >= backupStart ? `B${slideNumber(current) - slideNumber(backupStart)}` : `${slideNumber(current)}`;
  document.getElementById('footer').style.opacity = sec.dataset.nofooter !== undefined ? 0 : 1;
}

/* ---------------- continuations ---------------- */

// <section data-clone="Label"> receives a copy of that slide's content (final state, no entry
// animation) beneath its own new elements. data-figstate sets the cloned figures' state, and
// data-dim="selector:opacity;..." dims cloned elements.
function buildClones() {
  const byLabel = Object.fromEntries(sections.map(s => [s.dataset.label, s]));
  sections.forEach(sec => {
    const src = byLabel[sec.dataset.clone];
    if (!src) return;
    const frag = document.createDocumentFragment();
    [...src.children].forEach(c => {
      if (c.matches('aside.notes, .ghost, svg.rough-layer')) return;
      const k = c.cloneNode(true);
      [k, ...k.querySelectorAll('*')].forEach(n => {
        if (n.hasAttribute?.('data-in')) n.setAttribute('data-was-in', n.getAttribute('data-in'));
        n.removeAttribute?.('data-in');
        n.removeAttribute?.('data-rough-done');
        n.removeAttribute?.('data-dim-to');
        n.removeAttribute?.('data-step');
      });
      k.classList.add('cloned');
      frag.appendChild(k);
    });
    sec.prepend(frag);
    if (sec.dataset.figstate) sec.querySelectorAll('.cloned[data-fig], .cloned [data-fig]').forEach(f => f.dataset.state = sec.dataset.figstate);
    (sec.dataset.drop || '').split(',').filter(Boolean).forEach(sel => sec.querySelectorAll(`.cloned${sel}, .cloned ${sel}`).forEach(n => n.remove()));
    (sec.dataset.dim || '').split(';').filter(Boolean).forEach(rule => {
      const [sel, op] = rule.split(':');
      sec.querySelectorAll(`.cloned${sel}, .cloned ${sel}`).forEach(n => { n.style.opacity = op; n.dataset.dimTo = op; });
    });
  });
}

/* ---------------- figures ---------------- */

function renderFigures(root = stage) {
  root.querySelectorAll('[data-bind]').forEach(el => {
    try { const v = binds[el.dataset.bind]?.(data); if (v != null && !/NaN|undefined/.test(v)) el.textContent = v; }
    catch { /* leave placeholder */ }
  });
  root.querySelectorAll('[data-bind-wrap]').forEach(w => { w.hidden = [...w.querySelectorAll('[data-bind]')].some(b => b.textContent === '--'); });
  root.querySelectorAll('[data-fig]').forEach(el => {
    const fig = figures[el.dataset.fig];
    if (!fig) return;
    el.innerHTML = '';
    const missing = (fig.needs || []).filter(n => !data[n]);
    if (missing.length) {
      el.insertAdjacentHTML('beforeend', `<div class="pending">data pending: run scripts/${missing.join('.py, scripts/')}.py</div>`);
      return;
    }
    try { fig.render(el, data, el.dataset.state || ''); }
    catch (e) { console.error(el.dataset.fig, e); el.insertAdjacentHTML('beforeend', `<div class="pending">figure error: ${el.dataset.fig}</div>`); }
  });
}

/* ---------------- lifecycle section dividers ---------------- */

// Divider slides (data-lc-current) color the lifecycle cards: past sections gray, the current
// section red, upcoming sections ink. Moving between dividers animates from the previous colors.
const LC_STROKE = { past: '#9A9A9A', current: '#8C1515', future: '#2E2D29' };

function applyLifecycle() {
  sections.forEach(sec => {
    const ci = STAGES.indexOf(sec.dataset.lcCurrent);
    if (ci < 0) { sec.querySelectorAll('[data-lc]').forEach(card => card.__roughPath?.setAttribute('stroke', LC_STROKE.future)); return; }
    sec.querySelectorAll('[data-lc]').forEach(card => {
      const i = STAGES.indexOf(card.dataset.lc), st = i < ci ? 'past' : i === ci ? 'current' : 'future';
      card.classList.add(`lc-${st}`);
      card.__roughPath?.setAttribute('stroke', LC_STROKE[st]);
    });
  });
}

function lifecycleMove(sec, prevSec, A) {
  const opts = { duration: 700, easing: EASE_IN, ...FILL };
  sec.querySelectorAll('[data-lc]').forEach(card => {
    const prev = prevSec.querySelector(`[data-lc="${card.dataset.lc}"]`);
    if (!prev) return;
    ['h3', 'p', '.icon'].forEach(sel => {
      const a = prev.querySelector(sel), b = card.querySelector(sel);
      if (!a || !b) return;
      const ca = getComputedStyle(a), cb = getComputedStyle(b);
      if (ca.color !== cb.color || ca.opacity !== cb.opacity)
        A.push(b.animate([{ color: ca.color, opacity: ca.opacity }, { color: cb.color, opacity: cb.opacity }], opts));
    });
    const pa = prev.__roughPath, pb = card.__roughPath;
    if (pa && pb && pa.getAttribute('stroke') !== pb.getAttribute('stroke'))
      A.push(pb.animate([{ stroke: pa.getAttribute('stroke') }, { stroke: pb.getAttribute('stroke') }], opts));
  });
}

/* ---------------- entry choreography ---------------- */

function restart(sec) {
  (sec.__anims || []).forEach(a => a.cancel());
  (sec.__cancels || []).forEach(c => c());
  sec.__cancels = [];
  return (sec.__anims = []);
}

function entry(el, A) {
  const kind = el.dataset.in, delay = +(el.dataset.delay || 0), dur = +(el.dataset.dur || 0);
  // A hand-drawn outline drawn in a separate layer enters together with its element.
  if (el.__roughPath && kind !== 'draw') A.push(el.__roughPath.animate([{ opacity: 0 }, { opacity: 1 }], { duration: dur || 700, delay, easing: EASE_IN, ...FILL }));
  if (kind === 'fade') A.push(el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: dur || 700, delay, easing: EASE_IN, ...FILL }));
  else if (kind === 'up') A.push(el.animate([{ opacity: 0, transform: 'translateY(28px)' }, { opacity: 1, transform: 'none' }], { duration: dur || 750, delay, easing: EASE_IN, ...FILL }));
  else if (kind === 'pop') A.push(el.animate([{ opacity: 0, transform: 'scale(.85)' }, { opacity: 1, transform: 'scale(1.05)', offset: 0.7 }, { opacity: 1, transform: 'none' }], { duration: dur || 650, delay, easing: EASE_IN, ...FILL }));
  else if (kind === 'wipe') A.push(el.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: dur || 900, delay, easing: EASE_MOVE, ...FILL }));
  else if (kind === 'draw') {
    const paths = el.__roughPath ? [el.__roughPath] : el.tagName === 'path' ? [el] : [...el.querySelectorAll('path')];
    paths.forEach((p, i) => {
      p.style.strokeDasharray = '100';
      A.push(p.animate([{ strokeDashoffset: 100 }, { strokeDashoffset: 0 }], { duration: dur || 1100, delay: delay + i * 60, easing: 'cubic-bezier(.45,0,.3,1)', ...FILL }));
    });
    if (el.__roughPath && el.dataset.rough) A.push(el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: delay + 300, easing: EASE_IN, ...FILL }));
  }
}

function rectOf(el) {
  const k = stage.__k, r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
  return { x: (r.left - s.left) / k, y: (r.top - s.top) / k, w: r.width / k, h: r.height / k };
}

function magicMoves(sec, prevSec, A) {
  const moved = new Set();
  if (!prevSec) return moved;
  sec.querySelectorAll('[data-flip]').forEach(el => {
    const src = prevSec.querySelector(`[data-flip="${el.dataset.flip}"]`);
    if (!src) return;
    const a = rectOf(src), b = rectOf(el);
    if (!a.w || !b.w) return;
    const dx = a.x + a.w / 2 - (b.x + b.w / 2), dy = a.y + a.h / 2 - (b.y + b.h / 2), k = a.w / b.w;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(k - 1) < 0.002) return;
    el.style.transformOrigin = '50% 50%';
    A.push(el.animate([{ transform: `translate(${dx}px, ${dy}px) scale(${k})` }, { transform: 'none' }], { duration: +(el.dataset.flipDur || 1000), easing: EASE_MOVE, ...FILL }));
    moved.add(el);
  });
  return moved;
}

function activate(sec, prevSec, forward) {
  const A = restart(sec);
  sec.querySelectorAll('[data-fig]').forEach(f => f.__reset?.());
  if (reduced()) return;
  const adjacent = prevSec && Math.abs(sections.indexOf(prevSec) - sections.indexOf(sec)) === 1;
  const moved = magicMoves(sec, adjacent ? prevSec : null, A);
  sec.querySelectorAll('[data-in]').forEach(el => {
    if (moved.has(el) || el.hasAttribute('data-step')) return;
    if (el.dataset.inForwardOnly !== undefined && !forward) return;
    entry(el, A);
  });
  sec.querySelectorAll('[data-dim-to]').forEach(el => {
    if (!forward || !adjacent) return;
    A.push(el.animate([{ opacity: 1 }, { opacity: +el.dataset.dimTo }], { duration: 700, easing: EASE_IN, ...FILL }));
  });
  sec.querySelectorAll('[data-fig]').forEach(el => {
    const fig = figures[el.dataset.fig];
    if (fig?.animate && el.childElementCount && !el.querySelector('.pending')) {
      const r = fig.animate(el, data, el.dataset.state || '', A, { forward, adjacent });
      if (typeof r === 'function') sec.__cancels.push(r);
    }
  });
  if (sec.dataset.lcCurrent && adjacent) lifecycleMove(sec, prevSec, A);
  const custom = slideAnims[sec.dataset.anim];
  if (custom) { const r = custom(sec, A, { prevSec, forward, adjacent, data }); if (typeof r === 'function') sec.__cancels.push(r); }
}

/* ---------------- in-slide steps ---------------- */

// Elements with data-step="n" stay hidden until the nth click on the slide. Figures can mark
// their own SVG groups the same way and listen for the section's 'deckstep' event.
const maxStep = sec => Math.max(0, ...[...sec.querySelectorAll('[data-step]')].map(e => +e.dataset.step));

function setStep(sec, n, animate) {
  sec.__step = n;
  sec.querySelectorAll('[data-step]').forEach(el => {
    const k = +el.dataset.step, show = k <= n;
    el.style.visibility = show ? '' : 'hidden';
    if (el.__roughPath) el.__roughPath.style.visibility = show ? '' : 'hidden';
    if (animate && k === n && !reduced()) {
      el.getAnimations().forEach(x => x.cancel());
      const html = !(el instanceof SVGElement);
      (sec.__anims ||= []).push(el.animate([{ opacity: 0, transform: html ? 'translateY(20px)' : 'none' }, { opacity: 1, transform: 'none' }], { duration: 600, easing: EASE_IN }));
      if (el.__roughPath) sec.__anims.push(el.__roughPath.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 600, easing: EASE_IN }));
    }
  });
  sec.dispatchEvent(new CustomEvent('deckstep', { detail: { step: n, animate } }));
}

function next() {
  const sec = sections[current];
  if (sec && sec.__step < maxStep(sec)) setStep(sec, sec.__step + 1, true);
  else go(current + 1);
}

function prev() {
  const sec = sections[current];
  if (sec && sec.__step > 0) setStep(sec, sec.__step - 1, false);
  else go(current - 1);
}

/* ---------------- navigation ---------------- */

function go(i, { instant = false } = {}) {
  i = Math.max(0, Math.min(sections.length - 1, i));
  if (i === current) return;
  previous = current; current = i;
  const prevSec = sections[previous], sec = sections[current];
  sections.forEach(s => s.toggleAttribute('data-deck-active', s === sec));
  if (prevSec) { restart(prevSec); prevSec.querySelectorAll('video').forEach(v => v.pause()); }
  sec.querySelectorAll('video').forEach(v => { v.currentTime = 0; v.play().catch(() => {}); });
  updateChrome(sec);
  // Stepping back one slide shows it fully built; any other arrival starts at its first state.
  setStep(sec, previous === current + 1 ? maxStep(sec) : 0, false);
  if (!instant) activate(sec, prevSec, current > previous);
  history.replaceState(null, '', `#${current + 1}`);
  const notes = document.getElementById('notes');
  const aside = sec.querySelector('aside.notes');
  notes.innerHTML = `<h4>${slideNumber(current)} · ${sec.dataset.label || ''}</h4>${aside ? aside.innerHTML : ''}`;
}

addEventListener('keydown', e => {
  if (e.target.closest?.('input, textarea')) return;
  if ((e.key === ' ' || e.key === 'Enter') && e.target.closest?.('button')) return;
  if (['ArrowRight', 'PageDown', ' ', 'Enter'].includes(e.key)) { e.preventDefault(); next(); }
  else if (['ArrowLeft', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); prev(); }
  else if (e.key === 'Home') go(0);
  else if (e.key === 'End') go(sections.length - 1);
  else if (e.key === 'n') document.getElementById('notes').classList.toggle('on');
  else if (e.key === 'b') go(sections.findIndex(s => s.dataset.label === 'Backup'));
  else if (e.key === 'r') { const i = current; current = -1; go(i); }
});

addEventListener('hashchange', () => {
  const h = parseInt(location.hash.slice(1), 10);
  if (Number.isFinite(h)) go(h - 1);
});

stage.addEventListener('click', e => {
  if (e.target.closest('.interactive, a, button, video')) return;
  if (e.clientX < innerWidth * 0.2) prev(); else next();
});

/* ---------------- boot ---------------- */

async function loadData() {
  await Promise.all(DATA_FILES.map(async name => {
    try {
      const r = await fetch(`data/${name}.json`, { cache: 'no-cache' });
      if (r.ok) data[name] = await r.json();
    } catch { /* figure shows a pending note */ }
  }));
}

(async () => {
  buildClones();
  await loadData();
  // Typeset \( ... \) math with KaTeX before layout-dependent decoration.
  window.renderMathInElement?.(stage, { delimiters: [{ left: '\\(', right: '\\)', display: false }], throwOnError: false });
  await document.fonts.ready;
  renderFigures();
  decorate(stage);
  applyLifecycle();
  const h = parseInt(location.hash.slice(1), 10);
  go(Number.isFinite(h) ? h - 1 : 0);
  chrome.style.visibility = 'visible';
})();
