# Whiteboard Lecture Deck: Design Guidelines

A reusable visual and motion system for technical lecture decks: a light "whiteboard" canvas, hand-drawn
strokes for structure, exact paths for data, and motion that shows continuity. Built as a single HTML page
(1920×1080 stage) with the Web Animations API. Reference implementation: `deck/` in the AA 279B
Space Debris & Collision Avoidance lecture (`deck/js/sketch.js`, `deck/js/deck.js`, `deck/js/figs.js`).

## 1. Principles

- **Hand-drawn structure, exact data.** Boxes, arrows, underlines, axes and diagrams look drawn with a
  marker. Orbits, trajectories, data curves, ellipses from covariances and anything measured are exact
  paths. The audience should never wonder whether a wobble is data.
- **Every number is computed.** Figures replay data produced by small standalone scripts. Nothing on a
  slide is typed in by hand if a script can produce it; numbers in text are bound to the data files.
- **Motion shows continuity and causality, never decoration.** Something on screen usually stays, moves,
  dims, or grows from the previous slide rather than being replaced.
- **One idea per slide.** If it needs two ideas, it is two slides (often a continuation).
- **Plain language.** See section 8.

## 2. Canvas and layout

- Fixed 1920×1080 stage, scaled to fit the window; absolute positioning in stage pixels.
- Board background `#FAF8F3`; the letterbox around the stage is slightly darker (`#E9E6DF`).
- Generous empty space. Content sits in a band roughly x 120–1800, y 120–960.
- Persistent chrome (lives inside the stage, above slides):
  - **Footer** (bottom 28 px): logo left; short course · talk title and slide number right; 22 px sans at 50% ink.
  - **Section label** (top 40 px): the current section name only, centered, 24 px sans, uppercase,
    letter-spaced, 50% ink. Slides opt in with `data-stage`; it hides when absent.
- **Section dividers**: one overview graphic (a row of hand-drawn cards, one per section) is shown in full
  ink when first introduced, then reused as the divider before each section: the current section's card in
  the accent color, past sections in gray (icons at ~35% opacity), upcoming sections in ink. Each divider is
  a continuation clone of the overview (`data-clone="<overview>" data-lc-current="<section>"`), and moving
  between dividers animates text, icon and stroke colors from the previous divider's state.
- Header on working slides: top 128 px, left/right 140 px, 48–52 px serif.
- Citation line: centered, bottom 92 px, 22 px sans at ~42% ink.

## 3. Color: few colors, fixed meanings

| Token | Value | Meaning |
|---|---|---|
| Board | `#FAF8F3` | background |
| Ink | `#2E2D29` | default text, the primary object, neutral data |
| Cardinal | `#8C1515` | danger, the threat or secondary object, the key word, errors |
| Lagunita | `#006CB8` | orbits, "our" spacecraft, uncertainty ellipses, solutions in progress |
| Sky | `#0098DB` | light fills for uncertainty (15–25% opacity) |
| Palo Verde | `#279989` | resolved, safe, the answer |
| Gray | `#9A9A9A`, or ink at 35–50% | context, dimmed prior beats, familiar alternatives |

(Values from the Stanford identity palette; swap for another brand but keep the meaning column.)

- Color a word only when the color means something from the table.
- Dim prior context to 0.3 (background) or 0.45–0.6 (still readable). Dim, don't delete.
- No gradients, shadows, glows, or accent side-bars. Panels have no fill or a 3–40% white wash.

## 4. Typography

- **Source Serif 4** for statements, headers and panel titles (its italic is the emphasis voice).
- **Source Sans 3** for labels, axes, data, captions, chrome and big numbers (tabular figures).
- Monospace (Source Code Pro / Menlo) only for literal data formats (TLE lines, CDM fields).
- Sizes at 1920×1080: statement 64–76 px, header 48–52 px, panel title 36–42 px, body 28–32 px,
  axis labels and captions 22–26 px, big numbers 64–120 px. Never below 22 px.
- `text-wrap: balance` for statements and headers.
- Italicize at most one word or phrase per slide, and only where the presenter would stress it.

## 5. Hand-drawn strokes

All strokes are **seeded** (mulberry32 PRNG, seed from a stable key such as the element's text or a
`data-rough-key`) so a shape renders identically every load and a cloned slide redraws the same wobble.

**One marker stroke** from A to B is a cubic Bézier with:
- endpoint jitter: `min(2.2·rough, 3% of length)` px,
- overshoot past each end: up to `min(3·rough, 4% of length)` px,
- a shared perpendicular bow on both control points: `±min(2.5% of length, 5·rough)` px,
- control points at 25–40% and 60–75% along the segment.

```js
function strokeSegment(rnd, x1, y1, x2, y2, rough) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, nx = -uy, ny = ux;
  const j = Math.min(rough * 2.2, len * 0.03), over = Math.min(rough * 3, len * 0.04);
  const bow = (rnd() - 0.5) * Math.min(len * 0.025, rough * 5);
  const sx = x1 - ux * over * rnd() + (rnd() - 0.5) * j, sy = y1 - uy * over * rnd() + (rnd() - 0.5) * j;
  const ex = x2 + ux * over * rnd() + (rnd() - 0.5) * j, ey = y2 + uy * over * rnd() + (rnd() - 0.5) * j;
  const c1 = [x1 + dx * (0.25 + rnd() * 0.15) + nx * bow, y1 + dy * (0.25 + rnd() * 0.15) + ny * bow];
  const c2 = [x1 + dx * (0.60 + rnd() * 0.15) + nx * bow, y1 + dy * (0.60 + rnd() * 0.15) + ny * bow];
  return `M${sx} ${sy}C${c1} ${c2} ${ex} ${ey}`;
}
```

- **Boxes**: four strokes, drawn **twice** (second pass at 0.7× roughness) for the marker double-line look.
- **Ellipses/circles** (non-data only, e.g. Earth outline, call-out rings): ~18 points with ±1.75% radius
  noise, a random start angle, and 0.25–0.45 rad of overlap past the start (the pen doesn't quite close);
  smoothed with Catmull-Rom → Bézier; two passes.
- **Arrows**: one stroke for the shaft, two short strokes (half roughness) for a ~0.45 rad head.
- **Underlines**: two offset strokes under the word, accent color.
- Stroke widths: 2.2–3 px for structure, 3.5–4.5 px for the highlighted data series. Round caps and joins.
- Declarative use: `data-rough="box|ellipse|underline"`, `data-color`, `data-pad`; a decorator measures
  the element with offset geometry (unaffected by the stage scale) after fonts load and inserts the path.

## 6. Figures

- Draw charts yourself in SVG (canvas for >5k points). Axes are hand-drawn lines at ~55% ink; tick marks
  and tick labels are exact; no gridlines.
- One highlighted series in a meaning color; everything else ink, gray or dimmed.
- Label series directly at the line end (de-overlap labels with a minimum 30 px spacing) instead of legends
  where possible.
- Same scale on both axes whenever the geometry matters (e.g. uncertainty clouds); if an axis must be
  stretched, say so on the axis ("radial, stretched 8×").
- Log axes with decade ticks (`10⁻⁴`) for quantities spanning orders of magnitude; label "log scale".
- Orthographic 3D views: yaw then tilt; split paths into front/behind-Earth runs and draw the behind runs
  at ~20% opacity.
- SVG text sizes and colors are set as attributes; don't let a blanket CSS rule override them.
- Heatmaps: one-hue sequential ramp (board → accent) with alpha ∝ normalized value²; cell edges from the
  real grid (geometric midpoints on log axes); mark infeasible cells explicitly rather than interpolating.

## 7. Motion

Web Animations API (`el.animate`) with `fill: 'both'`, started when a slide becomes active, cancelled
when it leaves. rAF loops (rotations, number rolls, replays) return a cancel function and stop on leave.

**Timing vocabulary**
- Enter easing `cubic-bezier(.2,.7,.2,1)`: fades 600–800 ms, rise 24–28 px.
- Move easing `cubic-bezier(.65,0,.25,1)`: magic moves and zooms 900–1100 ms.
- Draw-on (stroke-dashoffset 100 → 0 on `pathLength="100"` paths) 900–1600 ms,
  easing `cubic-bezier(.45,0,.3,1)`. Dashed paths fade instead (dash-offset would break their pattern).
- Stagger siblings 150–300 ms; a line that turns a statement waits ~1.1–1.5 s.
- Whole entry sequence under ~2.5 s, except deliberate replays (orbit approach, Monte Carlo spread).
- No bounce; a tiny scale pop (0.85 → 1.05 → 1) is allowed for a key number.

**Declarative entry**: `data-in="up|fade|pop|wipe|draw"`, `data-delay`, `data-dur`.

**Transition menu** (decide one per slide)
1. **Fresh**: content enters; use at section turns.
2. **Continuation** (most common): `data-clone="<label>"` copies the previous slide's content in its final
   state; this slide adds one element. Optional `data-dim="<selector>:<opacity>"`, `data-drop`, and
   `data-figstate` to switch a cloned figure into its next state.
3. **Magic move**: matching `data-flip="key"` on adjacent slides animates position and scale (FLIP).
   Used for question → header (the question moves up and the answer appears beneath). A moved element
   skips its own entry animation so backward navigation reverses the move cleanly.
4. **Draw-on**: boxes and data series draw themselves; points and labels fade in after.
5. **Click reveal (steps)**: anything that appears after the slide's first state appears on the presenter's
   click, never after a timed delay. Mark it `data-step="n"`; it stays hidden (outline included) until the
   nth click, previous hides steps one at a time, and stepping back from the next slide shows the slide fully
   built. Figures mark their own SVG groups with `data-step` and can start animations on the section's
   `deckstep` event. Timed delays are only for the first state's entry choreography (under ~600 ms).
6. **Replay**: data-driven animation over precomputed time series (objects converge on a crossing point;
   a relative trajectory passes through a screening box; a sample cloud bends over days).

**Interactivity**: sliders built from plain elements (thin track, round outlined thumb in the accent color);
`stopPropagation` on pointer events; user input stops any autoplay.

**Reliability**: respect `prefers-reduced-motion` (jump to final state); set starting states synchronously
to avoid a first-frame flash; step forward and backward through every transition before presenting.

## 8. Copy

- **Titles are plain descriptions the presenter can talk to**, or a clear, complete statement of the point.
  Prefer "Iridium 33 and Cosmos 2251 collision, February 10, 2009" over "two orbits, one point in space."
- **No pithy, TED-style lines.** Avoid tautologies, dramatic fragments, rhetorical flourishes, and
  "It's not X, it's Y" constructions. If a line sounds like a tagline, rewrite it as a sentence that states
  a fact or a claim.
- A longer, specific sentence beats a short evocative one: "Starlink satellites made 207,152 collision
  avoidance maneuvers between December 2025 and May 2026" rather than "Today it's routine."
- Questions to the room are asked directly and literally ("How would you estimate the probability of
  collision?"), with no "Ask the room" label; the presenter asks.
- Avoid widows: use `text-wrap: balance` and a non-breaking space before the last word when a caption
  would otherwise leave one word on its own line.
- Comparisons build one side at a time: show the familiar case alone first, then add the new case on the
  next click with the familiar one dimmed.
- No em-dashes in slide copy. No exclamation marks.
- Numbers carry units and a source line; round consistently and show the same value everywhere it appears.
- Speaker notes hold the story, caveats and exact sources; the slide holds the claim.

## 9. Stats panels

- Label above value; labels 26 px sans at 50% ink, values 64–72 px sans semibold, all values the same size
  and weight unless one is the point of the slide (then accent color, same size).
- One column, consistent spacing (label-to-value 4 px, value-to-next-label 32 px), left-aligned.
- Units in the same font at ~60% of the value size. Qualifiers ("actual: 0") as a separate labeled row,
  not appended in a different typeface.

## 10. Data pipeline

- One standalone script per figure (`uv run scripts/<name>.py`, PEP 723 inline dependencies), writing
  `deck/data/<name>.json` with a `generated_utc` field; raw downloads cached and gitignored.
- The deck fetches the JSON at load; figures render from it; inline numbers use `data-bind="key"` with a
  binder function. Missing data shows "data pending: run scripts/<name>.py" instead of a broken figure.
- Keep a slide registry (label, figure, data file, transition) in a notes file.
