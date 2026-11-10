# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""How much can you dodge with the warning time you get, on the road and in orbit?

Road: time and distance to stop from highway speed under hard braking plus driver reaction, and
the AASHTO design stopping sight distance highways are built to provide at that speed.

Orbit: the warning time an onboard sensor with a given range provides at the median closing
speed found by scripts/screening.py, and how far real thrusters move a satellite in that time
when firing continuously (0.5 * a * t^2):
  - Orbion Aurora Hall thruster, 19 mN at 300 W, on a 100 kg smallsat,
  - 1 N of thrust on a 2,000 kg K2 Space bus.
Over a few seconds orbital dynamics do not matter; a brahe two-body propagation of an
instantaneous delta-v confirms the separation equals dv * t (reported as a check).

Early burn: the same burn made one orbit before the encounter, along the velocity of a circular
550 km orbit. The delta-v changes the semi-major axis (da = 2 a dv / v), hence the period
(dT = 3 pi da / v), so one orbit later the satellite is displaced along-track by about
ds = v dT = 3 pi da. The analytic value is checked against brahe two-body propagation.

References: AASHTO, A Policy on Geometric Design of Highways and Streets (stopping sight distance:
2.5 s brake reaction, 11.2 ft/s^2 deceleration); Orbion Aurora datasheet (2021).

Run:    uv run scripts/avoidance_budget.py   (after scripts/screening.py)
Output: deck/data/avoidance_budget.json
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MPH = 0.44704  # m/s per mph
FT = 0.3048  # m per ft
G0 = 9.80665


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--screening", type=Path, default=ROOT / "deck/data/screening.json")
    ap.add_argument("--out", type=Path, default=ROOT / "deck/data/avoidance_budget.json")
    ap.add_argument("--road-mph", type=float, default=65.0, help="highway speed")
    ap.add_argument("--brake-g", type=float, default=0.8, help="hard braking deceleration on dry pavement")
    ap.add_argument("--reaction-s", type=float, default=1.5, help="driver perception-reaction time")
    ap.add_argument("--sensor-km", type=float, default=100.0, help="onboard sensor detection range")
    args = ap.parse_args()
    thrusters = [
        {"name": "Orbion Aurora on a 100 kg smallsat", "thrust_n": 0.019, "mass_kg": 100.0},
        {"name": "K2 Space bus, 1 N on 2,000 kg", "thrust_n": 1.0, "mass_kg": 2000.0},
    ]

    # Road: v^2 / (2a) braking distance, v / a braking time, plus reaction distance.
    v = args.road_mph * MPH
    a = args.brake_g * G0
    brake_s, brake_m = v / a, v**2 / (2 * a)
    total_m = brake_m + v * args.reaction_s
    # AASHTO design stopping sight distance (ft): 1.47 V t + 1.075 V^2 / a, V in mph.
    ssd_ft = 1.47 * args.road_mph * 2.5 + 1.075 * args.road_mph**2 / 11.2

    # Orbit: warning time at the median closing speed from the screening run.
    speeds = json.loads(args.screening.read_text())["rel_speeds_kms"]
    v_close = float(np.median(speeds))
    warn_s = args.sensor_km / v_close

    bh.initialize_eop()
    epoch = bh.Epoch.from_datetime(2026, 11, 10, 0, 0, 0.0, 0.0, bh.TimeSystem.UTC)
    oe = np.array([bh.R_EARTH + 550e3, 0.0, 53.0, 0.0, 0.0, 0.0])
    x0 = bh.state_koe_to_eci(oe, bh.AngleFormat.DEGREES)
    # Check that orbital dynamics are negligible over the warning time: a 1 m/s radial impulse
    # propagated two-body separates from the reference orbit by ~ dv * t.
    r_hat = x0[:3] / np.linalg.norm(x0[:3])
    x1 = x0.copy()
    x1[3:] += 1.0 * r_hat
    t_end = epoch + warn_s
    ref = bh.KeplerianPropagator.from_eci(epoch, x0, 1.0).state_eci(t_end)
    burn = bh.KeplerianPropagator.from_eci(epoch, x1, 1.0).state_eci(t_end)
    impulse_check = {"dv_ms": 1.0, "two_body_shift_m": round(float(np.linalg.norm(burn[:3] - ref[:3])), 3), "dv_times_t_m": round(warn_s, 3)}

    # Early burn: circular-orbit quantities and the reference state one period later.
    a0 = oe[0]
    v0 = float(np.linalg.norm(x0[3:]))
    period = bh.orbital_period(a0)
    v_hat = x0[3:] / v0
    t_one = epoch + period
    ref_one = bh.KeplerianPropagator.from_eci(epoch, x0, 60.0).state_eci(t_one)
    r_hat1 = ref_one[:3] / np.linalg.norm(ref_one[:3])
    h_hat1 = np.cross(ref_one[:3], ref_one[3:])
    h_hat1 /= np.linalg.norm(h_hat1)
    t_hat1 = np.cross(h_hat1, r_hat1)

    for t in thrusters:
        accel = t["thrust_n"] / t["mass_kg"]
        dv = accel * warn_s
        t["accel_ms2"] = accel
        t["dv_mms"] = round(dv * 1e3, 2)
        t["shift_cm"] = round(0.5 * accel * warn_s**2 * 100, 2)
        # Same delta-v applied one orbit before the encounter, along the velocity.
        da = 2 * a0 * dv / v0
        dT = 3 * np.pi * da / v0
        xb = x0.copy()
        xb[3:] += dv * v_hat
        burned = bh.KeplerianPropagator.from_eci(epoch, xb, 60.0).state_eci(t_one)
        d = burned[:3] - ref_one[:3]
        t["early"] = {
            "da_m": round(da, 2),
            "dT_ms": round(dT * 1e3, 2),
            "ds_analytic_m": round(v0 * dT, 1),
            "ds_brahe_m": round(float(np.linalg.norm(d)), 1),
            "ds_brahe_along_track_m": round(float(d @ t_hat1), 1),
        }

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "road": {
            "speed_mph": args.road_mph,
            "head_on_closing_mph": 2 * args.road_mph,
            "brake_g": args.brake_g,
            "reaction_s": args.reaction_s,
            "brake_time_s": round(brake_s, 2),
            "brake_distance_m": round(brake_m, 1),
            "brake_distance_ft": round(brake_m / FT),
            "stop_distance_m": round(total_m, 1),
            "stop_distance_ft": round(total_m / FT),
            "aashto_sight_distance_ft": round(ssd_ft),
        },
        "orbit": {
            "median_closing_kms": round(v_close, 2),
            "median_closing_mph": round(v_close * 1e3 / MPH, -1),
            "sensor_range_km": args.sensor_km,
            "warning_s": round(warn_s, 2),
            "thrusters": thrusters,
            "impulse_check": impulse_check,
            "early_burn_orbit": {
                "alt_km": 550.0,
                "a_km": round(a0 / 1e3, 1),
                "v_kms": round(v0 / 1e3, 3),
                "period_min": round(period / 60, 2),
            },
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
