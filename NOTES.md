# AA 279B Lecture: Space Debris & Collision Avoidance (2026-11-10)

Working notes for the deck. Not lecture content.

## Story

- **Audience:** upper-graduate astrodynamics students (know two-body, perturbations, frames, basic estimation).
- **Length:** 40 min slot, main path planned for ~30 min, overflow in Backup.
- **Naive belief:** "Collision avoidance is like driving: look around, see the other object, steer.
  And computing whether two orbits collide is just a propagation problem."
- **Leave with:** Avoiding collisions in space is a decision under uncertainty, built on a shared and
  imperfect global catalog. The maneuver is easy; knowing *whether* to make it is hard.
- **Outcomes:** (1) end-to-end lifecycle of a conjunction, (2) obligations and capabilities a new
  operator must plan for, (3) the websites, data and resources to use.

### Recurring framing (one card row per lifecycle stage)

Lifecycle graphic (`Lifecycle` slide) is introduced all ink, then reused as a divider before each section
(`Section <name>` slides): current section red, past gray, upcoming ink. Working slides show only the
section name at the top (`data-stage`).

## Visual system

| Role | Value | Meaning |
|---|---|---|
| Board (bg) | `#FAF8F3` | whiteboard |
| Ink | `#2E2D29` (Stanford Black) | default text, primary object |
| Cardinal | `#8C1515` | danger, collision, the secondary object, the key word |
| Lagunita | `#006CB8` | orbits, our spacecraft, uncertainty ellipses |
| Sky | `#0098DB` | lighter orbit/uncertainty fills (at 15-25% opacity) |
| Palo Verde | `#279989` | resolved, safe, "the answer" |
| Gray | `#9A9A9A` / ink at 35-50% | context, dimmed prior beats |

- Type (Stanford identity): **Source Serif 4** for statements (italic = emphasis voice),
  **Source Sans 3** for labels, axes, data. Never below 22px at 1920x1080.
- Hand-drawn: rough.js strokes for boxes, arrows, underlines, callouts (seeded so they render
  identically every time). Orbits, trajectories and data curves are exact SVG paths.
- Footer: Stanford logo (user to supply PNG) left, "AA 279B · Space Debris & Collision Avoidance" right.
- Motion: Web Animations API per `narrative-slides` skill; precompute + replay for all data
  (scripts write `deck/data/*.json`, deck only interpolates).

## Layout

```
scripts/      standalone `uv run` brahe scripts, each writes deck/data/<name>.json
deck/         index.html, js/, css/, data/, img/
justfile      `just data` regenerates all data, `just serve` serves the deck
pocs/         gitignored scratch
```

## Beat sheet

`[Q]` = pause and ask the room before revealing. `[S:name]` = data from `scripts/name.py`.
`[IMG]` = image/video the user supplies.


### Act 1: Motivation (~4 min)
1. Title.
2. Feb 2009, ~790 km: Iridium 33 x Cosmos 2251. [IMG gif] Then today's debris clouds. [S:debris_clouds]
   BUT
3. It still happens: Starlink near-miss video. [IMG mp4]
   BUT
4. Capella story: Pc 1-in-10, thrusters not commissioned. [Q] "What would you do?"
   THEREFORE
5. [Q] "How do you avoid a crash when you drive?"
   BUT
6. Car vs spacecraft contrast: closing speeds, warning seconds. Local info is nearly useless. Stargaze needs scale. [S:screening closing speeds]
   THEREFORE
7. A global problem: know where everything is, days ahead.
8. Lifecycle cards: Measure, Catalog, Screen, Assess, Decide, Share. Four-card frame per stage.

### Act 2: Lifecycle (~21 min)
Measure: 9 catalog [S:catalog] · 10 [Q] find 10 cm at 1,000 / 36,000 km · 11 1/R^4 vs 1/R^2 · 12 SSN map + FOV [S:ssn_sensors] · 13 USG free, warns everyone · 14 GPS: Starlink operator vs GP [S:starlink_vs_gp] · 15 [Q] fixes to 5-day orbit · 16 measurement models, IOD, EKF [S:gps_od]
Catalog: 17 what is it · 18 [Q] rideshare, UCTs · 19 MHT · 20 TLE/GP history · 21 gotchas [S:tle_gotchas] · 22 number exhaustion, GP/OMM
Screen: 23 [Q] how to check · 24 570,898,945 pairs · 25 apsis/path/phase sieves [S:screening] · 26 [Q] why a box; sweep animation [S:screening]
Assess: 27 [Q] how to compute Pc · 28 MC cost [S:pc] · 29 Foster 2D [S:pc] · 30 3D / MC when 2D breaks · 31 CDMs, thresholds · aside: covariance realism, banana [S:covariance_banana] · aside: ephemeris quality: operator vs GP [S:starlink_vs_gp], GPS OD prediction [S:gps_od], dilution for hit / CDM / 2 km miss [S:pc_evolution], public GP vs SP (HAC) vs operator ephemerides
Decide: 32 [Q] poll Pc 1e-3 at 3 d · 33 trade space [S:maneuver] · 34 Pc evolution, dilution [S:pc_evolution] · 35 unknowns · 36 rules, tables, POMDP · 37 rescreen, OEM, SpaceX on-board
Share: 19 SDS screening types and schedule (handbook pp. 5–9) · after maneuver: baseline Space Force rescreen loop, then in-house screening against ingested SP ephemerides

### Act 3: New operator (~4 min)
40 [Q] what must you do · 41 resources · 42 "that's a lot" · 43 brahe · 44 close

### Backup
Knock-on effects, orbital capacity, coordination, rideshare Gabbard, adaptive sieve detail, 3D Pc, SSN table.

## Data contracts (scripts -> deck/data/*.json)

All scripts: PEP 723 header with `brahe==1.8.1` + `numpy` (+ `scipy` only if needed), runnable as
`uv run scripts/<name>.py`, default output `deck/data/<name>.json` resolved from the script location,
`generated_utc` field in every file, floats rounded sensibly, each file < 2 MB. Units: km, km/s, s, h
as named in keys. ECI = GCRF unless key says otherwise.

- `catalog.json`: `{generated_utc, epoch, source, counts:{total,payload,starlink,other_payload,rocket_body,debris,unknown,active_payloads,starlink_active,leo,meo,geo,heo}, objects:{type:["P"|"S"(Starlink)|"R"|"D"|"U",...], xyz_km:[[x,y,z],...], alt_km:[...]}}`
- `debris_clouds.json`: `{generated_utc, epoch, groups:[{name, parent_norad, cataloged, on_orbit, xyz_km:[[...]], alt_km:[...]}], collision:{tca_utc, miss_km_sgp4, rel_speed_kms, crossing_angle_deg, orbits:[{name, xyz_km:[[...]]}]}}`
- `ssn_sensors.json`: `{generated_utc, sensors:[{name, system, type, lon, lat, alt_m, el_min_deg, range_max_km}], footprints:{leo_alt_km, geo_alt_km, rings:{<name>:{leo:[[lon,lat]...], geo:[[lon,lat]...]|null}}}, sample_track:{name, norad, t_s:[...], lonlat:[[lon,lat]...], windows:[{sensor,start_s,end_s}]}, stats:{passes_24h, longest_gap_h}, radar_ratio:{leo_km, geo_km, snr_ratio}}`
- `tle_gotchas.json`: `{generated_utc, object:{name,norad}, example_tle:[l1,l2], t_h:[...], teme_vs_gcrf_km:[...], mean_as_osc_km:[...], osc_init_j2_km:[...], osc_init_numerical_km:[...], notes:{...}}`
- `starlink_vs_gp.json`: `{generated_utc, object:{name,norad}, operator_epoch, gp_epoch, t_h:[...], gp_minus_operator_rtn_km:{R,T,N}, operator_sigma_rtn_km:{R,T,N}|null}`
- `gps_od.json`: `{generated_utc, config:{...}, est_end_h, t_h:[...], err_rtn_m:{R,T,N}, sigma3_rtn_m:{R,T,N}, meas_t_h:[...]}`
- `covariance_banana.json`: `{generated_utc, config:{...}, snapshots:[{t_h, samples_xy_km:[[along,radial]...], ellipse_cov_km2:[[a,b],[b,c]], arc_xy_km:[[...]]}]}` (x = along-track tangent at nominal, y = radial, Cartesian, nominal at origin)
- `screening.json`: `{generated_utc, primary:{name,norad}, span_days, box_km:{R,T,N}, counts:{catalog,apsis,path,phase,box,lt_5km}, recall:{brute_force_events, retained}, events:[{norad,name,tca_utc,miss_km,rel_speed_kms}], rel_speeds_kms:[...], hero:{secondary:{name,norad}, tca_utc, miss_km, rel_speed_kms, t_s:[...], rel_rtn_km:[[R,T,N]...], primary_xyz_km:[[...]], secondary_xyz_km:[[...]]}, all_vs_all_paper:{catalog:33791,brute:570898945,fixed50:228619849,adaptive:162819449,cite:"Srinivas et al. 2026, arXiv:2610.11645"}}`
- `pc.json`: `{generated_utc, validation:[{case,pc_ours,pc_cara,rel_err}], example:{miss_m, rel_speed_kms, hbr_m, pc_foster, pc_mc, mc_n, mc_hits, encounter_plane:{miss_xy_m, cov_xy_m2, mc_samples_xy_m, mc_hit}, ellipsoids:{cov1_rtn_m2, cov2_rtn_m2, rel_pos_m, rel_vel_ms}}, mc_cost:{pc:[...], n_samples:[...], rel_err, conf, prop_seconds_per_sample, cpu_hours:[...]}}`
- `maneuver.json`: `{generated_utc, conjunction:{...}, lead_h:[...], dv_cms:[...], log10_pc:[[lead x dv]], miss_km:[[lead x dv]], threshold, min_dv_cms:[per lead]}`
- `pc_evolution.json`: `{generated_utc, dilution:{sigma_scale:[...], pc:[...], miss_m, hbr_m, sigma_major_m, by_miss:[{miss_m, pc:[...]}]}, sigma_growth_source, scenarios:[{name, true_miss_m, updates:[{t_before_tca_h, est_miss_m, sigma_T_m, pc}]}]}`

## Copy rule

Plain titles the presenter can talk to, or clear complete statements. No pithy/TED-style lines,
tautologies or flourishes. See `design-guidelines.md` section 8.

## Deck implementation

- Shell: `deck/js/deck.js` (stage scaling, keys, hash routing, chrome, continuations, entry choreography, FLIP).
- Strokes: `deck/js/sketch.js` (seeded hand-drawn lines/boxes/ellipses; `[data-rough]` auto-decoration, seed from
  `data-rough-key` or text so clones redraw identically).
- Figures: `deck/js/figs.js` (`figures.<name>.render/animate`, `binds` for `[data-bind]` numbers).
- Declarative motion: `data-in="up|fade|pop|wipe|draw"` + `data-delay`; magic move with matching `data-flip` keys on
  adjacent slides; continuation with `data-clone="<label>"`, `data-dim="<sel>:<opacity>"`, `data-figstate`, `data-drop`.
- Chrome: `data-stage` shows the section name at the top. Dividers: `data-clone="Lifecycle" data-lc-current="<stage>"`.
- Dev server: `just serve` (scripts/serve.py, no-cache headers).
- Keys: arrows/space, `n` notes, `b` backup, `r` replay.
- Click steps: `data-step="n"` on HTML or SVG elements; figures listen with `onStep(el, n, fn)`.

### Slide registry (label · figure · inherits)

| # | Label | Figure / data | Transition |
|---|---|---|---|
| 1 | Title | titleOrbits (illustration) | fresh |
| 3 | Iridium geometry | collision ← debris_clouds | fresh |
| 4 | Debris today | debrisCloud ← debris_clouds | fresh |
| 5 | Starlink video | placeholder `img/starlink-near-miss.mp4` | fresh |
| 6 | Capella | WIRED image + link (`img/capella-wired.jpg`) | fresh |
| 8 | Driving Q | text, flip key q-drive | fresh |
| 9 | Road vs orbit | binds screen.* | magic move q-drive |
| 10 | Global problem | text | fresh |
| 11 | Lifecycle | icon ×6 | fresh |
| 12 | Catalog | catalogCloud ← catalog | fresh |
| 13–14 | Find Q / Find Q GEO | text | continuation |
| 15 | Radar vs optical | snrScaling ← ssn_sensors | fresh |
| 16–17 | SSN map / SSN gaps | ssnMap ← ssn_sensors, land; state=track | continuation |
| 18 | Free warnings | text | fresh |
| 20–21 | OD Q / Measurement models | odPipeline | magic move q-od |
| 23–28 | Catalog section | mhtTree, tleCard, tleGotchas | fresh |
| 29–33 | Screen section | bruteForce, sieves, boxSweep ← screening | magic move q-box |
| 34–38 | Assess section | mcLoop, mcMethod, mcCost, foster, cdmCard ← pc; banana (interactive slider); ephemeris quality aside: starlinkVsGp, gpsOd, dilution ← pc_evolution (continuation "Dilution live": state=live adds a slider-driven fourth curve, Pc computed in the browser), screening sources cards | fresh |
| 39–43 | Decide section | tradespace ← maneuver, pcEvolution ← pc_evolution, decisionLadder | fresh |
| 44–47 | Share section | screeningSchedule, afterManeuver (baseline + in-house rows) | fresh |
| 48–55 | New operator, brahe, close | resources, brahe modules, LEO code, Mars code + marsTransfer ← mars_transfer, adopters, closeLinks (repo + brahe QR) | magic move q-op |
| B | Backup | allVsAll, ssnTable, statements | fresh |

### Needed from Duncan

- `deck/img/stanford-logo.png` (footer + title)
- `deck/img/logos/<slug>.png` for adopters (northwood, capella, d-orbit-usa, ksat, heo, trusted-space, k2-space, vyoma, orbital-sidekick)
- Repo URL for the closing slide QR
