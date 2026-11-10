# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Earth-to-Mars transfer with an impulsive burn, propagated with brahe around the Sun.

The spacecraft starts on Earth's heliocentric orbit (DE440s), coasts one day, then a
TimeEvent callback applies a prograde trans-Mars injection burn. The departure date and
burn size are chosen by scanning a launch window for the pair that brings the spacecraft
closest to Mars. Daily positions of the spacecraft, Earth and Mars are written
in the ecliptic plane for a top-down view.

Run:    uv run scripts/mars_transfer.py
Output: deck/data/mars_transfer.json
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DV0_MS = 2945.0  # Hohmann trans-Mars injection from a circular 1 AU orbit
BURN_AFTER_S = 86400.0
WINDOW = ((2028, 9, 1), 240)  # scan start date, days to scan
ARRIVAL_DAYS = (150, 330)  # closest approach to Mars searched in this range
DV_GRID_MS = np.arange(2700.0, 3501.0, 50.0)
OBLIQUITY_RAD = np.deg2rad(23.439291)


def burn(dv_ms: float):
    def tmi(epoch, x):
        x = x.copy()
        x[3:] += dv_ms * x[3:] / np.linalg.norm(x[3:])
        return x, bh.EventAction.CONTINUE
    return tmi


def force_model() -> bh.ForceModelConfig:
    return bh.ForceModelConfig.for_body(
        bh.CentralBody.from_naif_id(bh.NAIFId.SUN),
        gravity=bh.GravityConfiguration.point_mass(),
        third_body=[bh.ThirdBody.JUPITER, bh.ThirdBody.VENUS],
    )


def transfer(t0: bh.Epoch, dv_ms: float) -> bh.NumericalOrbitPropagator:
    x0 = bh.spk_state(bh.NAIFId.EARTH, bh.NAIFId.SUN, t0)
    prop = bh.NumericalOrbitPropagator(t0, x0, bh.NumericalPropagationConfig.default(), force_model())
    prop.add_event_detector(bh.TimeEvent(t0 + BURN_AFTER_S, "TMI").with_callback(burn(dv_ms)))
    return prop


def closest_approach(t0: bh.Epoch, dv_ms: float) -> tuple[float, int]:
    """Smallest daily-sampled spacecraft-Mars distance [m] within ARRIVAL_DAYS, and its day."""
    prop = transfer(t0, dv_ms)
    best = (np.inf, 0)
    for d in range(ARRIVAL_DAYS[0], ARRIVAL_DAYS[1] + 1):
        t = t0 + d * 86400.0
        prop.propagate_to(t)
        miss = np.linalg.norm(prop.current_state()[:3] - bh.spk_position(bh.NAIFId.MARS_BARYCENTER, bh.NAIFId.SUN, t))
        best = min(best, (miss, d))
    return best


def to_ecliptic(r: np.ndarray) -> np.ndarray:
    c, s = np.cos(OBLIQUITY_RAD), np.sin(OBLIQUITY_RAD)
    return np.array([r[0], c * r[1] + s * r[2], -s * r[1] + c * r[2]])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "deck/data/mars_transfer.json")
    args = ap.parse_args()

    bh.initialize_eop()
    bh.load_spice_kernel("de440s")
    start = bh.Epoch(*WINDOW[0], 0, 0, 0.0, time_system=bh.TimeSystem.TDB)

    # Coarse scan of departure dates at the Hohmann burn, then refine date and burn size.
    coarse = min((closest_approach(start + k * 86400.0, DV0_MS)[0], k) for k in range(0, WINDOW[1], 3))
    best = None
    for k in range(coarse[1] - 4, coarse[1] + 5):
        for dv in DV_GRID_MS:
            miss, day = closest_approach(start + k * 86400.0, float(dv))
            if best is None or miss < best[0]:
                best = (miss, k, float(dv), day)
    miss_m, k, dv_ms, arrival_day = best
    t0 = start + k * 86400.0
    print(f"departure {t0}, burn {dv_ms:.0f} m/s, closest to Mars on day {arrival_day}: {miss_m / 1e9:.3f} million km")

    prop = transfer(t0, dv_ms)
    days = np.arange(0, arrival_day + 1)
    sc, earth, mars = [], [], []
    for d in days:
        t = t0 + float(d) * 86400.0
        prop.propagate_to(t)
        sc.append(to_ecliptic(prop.current_state()[:3]) / bh.AU)
        earth.append(to_ecliptic(bh.spk_position(bh.NAIFId.EARTH, bh.NAIFId.SUN, t)) / bh.AU)
        mars.append(to_ecliptic(bh.spk_position(bh.NAIFId.MARS_BARYCENTER, bh.NAIFId.SUN, t)) / bh.AU)
    # Full orbits for context, sampled over one period of each planet.
    orbit = lambda body, period_d: [to_ecliptic(bh.spk_position(body, bh.NAIFId.SUN, t0 + float(d) * 86400.0))[:2] / bh.AU for d in np.linspace(0, period_d, 181)]

    r = lambda a: [[round(float(v[0]), 5), round(float(v[1]), 5)] for v in a]
    sc_r = np.linalg.norm(np.array(sc), axis=1)
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "departure_tdb": str(t0),
        "config": {"dv_ms": dv_ms, "burn_after_days": BURN_AFTER_S / 86400.0, "transfer_days": arrival_day,
                   "central_body": "Sun (point mass)", "third_body": ["Jupiter", "Venus"], "ephemeris": "DE440s"},
        "days": days.tolist(),
        "spacecraft_au": r(sc),
        "earth_au": r(earth),
        "mars_au": r(mars),
        "earth_orbit_au": r(orbit(bh.NAIFId.EARTH, 365.25)),
        "mars_orbit_au": r(orbit(bh.NAIFId.MARS_BARYCENTER, 687.0)),
        "arrival": {"sun_distance_au": round(float(sc_r[-1]), 4), "mars_distance_mkm": round(miss_m / 1e9, 3)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
