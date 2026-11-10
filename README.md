# Space Debris & Collision Avoidance

Lecture for AA 279B: Advanced Space Mechanics, Stanford University, November 10, 2026.

The slides are a single HTML page in `deck/`. Every figure is drawn from data produced by a small
standalone script in `scripts/`, built on the open-source [brahe](https://github.com/duncaneddy/brahe)
astrodynamics library. Each script runs on its own with [uv](https://docs.astral.sh/uv/); no
environment setup is needed.

## Running the scripts

```bash
uv run scripts/screening.py
```

Each script writes `deck/data/<name>.json`. To regenerate everything:

```bash
just data
```

Scripts that query [Space-Track](https://www.space-track.org) read credentials from
`SPACETRACK_USER` and `SPACETRACK_PASS`. Downloads are cached under `deck/data/raw/`.

| Script | What it computes |
|---|---|
| `catalog.py` | Current on-orbit catalog propagated to a common epoch, counts by object type and regime |
| `debris_clouds.py` | Iridium 33 / Cosmos 2251: collision geometry reconstructed with SGP4, surviving fragments today |
| `ssn_sensors.py` | US Space Surveillance Network sensors (Vallado), visibility footprints, coverage of one LEO satellite |
| `rideshare_tracks.py` | Simulated radar tracks of 20 satellites released from one rideshare dispenser, two passes over the Eglin radar |
| `starlink_vs_gp.py` | Public GP element set + SGP4 vs SpaceX's GPS-based operator ephemeris, in RTN |
| `gps_od.py` | GPS orbit determination with an extended Kalman filter, then prediction error growth |
| `tle_gotchas.py` | Errors from treating TLE mean elements as osculating, and TEME as an inertial frame |
| `screening.py` | One-vs-catalog conjunction screening: apsis, path (MOID) and phase sieves, then a screening box |
| `avoidance_budget.py` | Warning time and how far you can move in it: highway braking vs a cold-gas burn at orbital closing speeds |
| `pc.py` | 2D probability of collision (Foster), validated against NASA CARA, plus a Monte Carlo baseline and its cost |
| `maneuver.py` | Maneuver trade space: along-track Δv vs lead time vs resulting Pc |
| `pc_evolution.py` | How Pc evolves as updates arrive, and Pc dilution |
| `covariance_banana.py` | Monte Carlo vs linearized covariance: non-Gaussian ("banana") uncertainty under drag |
| `mars_transfer.py` | Earth-to-Mars transfer around the Sun with an impulsive burn; departure date and burn chosen by a launch-window scan |
| `basemap.py` | Natural Earth land outline for the map figures |

## Viewing the slides

```bash
just serve
```

Then open <http://localhost:8279>. Keys: arrows or space to move, `n` for speaker notes, `b` to
jump to backup slides, `r` to replay the current slide's animation.

## References

- Spaceflight Safety Handbook for Satellite Operators, v1.7, 18th and 19th Space Defense Squadrons (2023)
- NASA Spacecraft Conjunction Assessment and Collision Avoidance Best Practices Handbook, Rev. 2 (2026)
- NASA CARA Analysis Tools: <https://github.com/nasa/CARA_Analysis_Tools>
- Hoots, Crawford & Roehrich, "An Analytic Method to Determine Future Close Approaches Between Satellites," *Celestial Mechanics* 33 (1984)
- Foster & Estes, "A Parametric Analysis of Orbital Debris Collision Probability and Maneuver Rate for Space Vehicles," NASA JSC-25898 (1992)
- Srinivas, Kim, Eddy & Kochenderfer, "Scalable LEO Conjunction Screening using Adaptive Synthetic-Covariance Thresholds," arXiv:2610.11645 (2026)
- Kim, Eddy & Kochenderfer, "Chance-Constrained Belief-Space Maneuver Planning for Autonomous Collision Avoidance Under Uncertainty," AMOS (2026), arXiv:2609.13428
- Kim, Al-Husseini, Eddy & Kochenderfer, "Semi-Decentralized Multi-Spacecraft Collision Avoidance under Communication Constraints," AAS/AIAA Astrodynamics Specialist Conference (2026), arXiv:2607.26570
