# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Simulated radar tracks of a rideshare deployment: many objects, one cluster of measurements.

A rideshare dispenser in a 525 km sun-synchronous orbit releases satellites one minute apart,
each with a small random separation velocity (0.5 to 1.5 m/s). Every object is propagated with
brahe's numerical propagator (8x8 gravity). A ground radar from the brahe SSN dataset (Eglin)
then observes the group on two passes, a few hours and about a day after deployment, producing
range, azimuth and elevation measurements every 2 s with noise. Each measurement records which
object it came from, which a real sensor would not know: the measurements arrive unlabeled and
must be associated with objects (tracks to objects) before orbits can be estimated.

Run:    uv run scripts/rideshare_tracks.py
Output: deck/data/rideshare_tracks.json
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEED = 279
N_OBJECTS = 20
RELEASE_DT_S = 60.0
DV_RANGE_MS = (0.5, 1.5)
ALT_KM = 525.0
INC_DEG = 97.5
SPAN_H = 36.0
SAMPLE_DT_S = 2.0
EL_MIN_DEG = 10.0
SENSOR = "Eglin"
SIGMA_RANGE_M = 30.0
SIGMA_ANGLE_DEG = 0.02
PASS_TARGET_H = (3.0, 24.0)


def force_model() -> bh.ForceModelConfig:
    return bh.ForceModelConfig(gravity=bh.GravityConfiguration(degree=8, order=8))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "deck/data/rideshare_tracks.json")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    bh.initialize_eop()
    epoch0 = bh.Epoch.from_datetime(2026, 11, 1, 0, 0, 0.0, 0.0, bh.TimeSystem.UTC)
    oe = np.array([bh.R_EARTH + ALT_KM * 1e3, 0.0005, INC_DEG, 30.0, 0.0, 0.0])
    x_disp = bh.state_koe_to_eci(oe, bh.AngleFormat.DEGREES)
    cfg = bh.NumericalPropagationConfig.with_method(bh.IntegrationMethod.RKF78).with_abs_tol(1e-6).with_rel_tol(1e-12)

    # Dispenser trajectory, then each object released from it with a random separation velocity.
    dispenser = bh.NumericalOrbitPropagator(epoch0, x_disp, cfg, force_model())
    dispenser.set_trajectory_mode(bh.TrajectoryMode.DISABLED)
    objects = []
    for k in range(N_OBJECTS):
        t_rel = epoch0 + k * RELEASE_DT_S
        dispenser.propagate_to(t_rel)
        x = dispenser.current_state().copy()
        u = rng.normal(size=3)
        x[3:] += rng.uniform(*DV_RANGE_MS) * u / np.linalg.norm(u)
        objects.append(bh.NumericalOrbitPropagator(t_rel, x, cfg, force_model()))

    # Common sample grid after the last release, positions in ITRF.
    t0 = epoch0 + N_OBJECTS * RELEASE_DT_S
    t_s = np.arange(0.0, SPAN_H * 3600.0, SAMPLE_DT_S)
    epochs = [t0 + float(t) for t in t_s]
    bh.par_propagate_to(objects, epochs[-1])
    r_itrf = np.array([np.array(o.states_itrf(epochs))[:, :3] for o in objects])  # (obj, time, 3)

    sensor = next(s for s in bh.SimpleSSNSensor.from_locations(bh.datasets.ssn_sensors.load()) if s.name == SENSOR)
    loc = sensor.location
    site = bh.position_geodetic_to_ecef(np.array([loc.lon, loc.lat, loc.alt]), bh.AngleFormat.DEGREES)
    azel = np.array([
        bh.position_enz_to_azel(
            bh.relative_position_ecef_to_enz(site, r_itrf[i], bh.EllipsoidalConversionType.GEODETIC),
            bh.AngleFormat.DEGREES,
        )
        for i in range(N_OBJECTS)
    ])  # (obj, time, [az, el, range])

    # Passes: contiguous intervals where the group's centroid object is above the elevation mask.
    mid = N_OBJECTS // 2
    up = azel[mid, :, 1] > EL_MIN_DEG
    edges = np.flatnonzero(np.diff(up.astype(int)))
    starts = [i + 1 for i in edges if not up[i]]
    passes_idx = []
    for s in starts:
        e = s
        while e < len(up) and up[e]:
            e += 1
        passes_idx.append((s, e))

    out_passes = []
    for target in PASS_TARGET_H:
        s, e = min(passes_idx, key=lambda p: abs(t_s[p[0]] / 3600.0 - target))
        # Widen the window so every object's full pass is included.
        lo, hi = max(0, s - int(900 / SAMPLE_DT_S)), min(len(t_s), e + int(900 / SAMPLE_DT_S))
        meas = []
        for i in range(N_OBJECTS):
            for j in range(lo, hi):
                az, el, rho = azel[i, j]
                if el <= EL_MIN_DEG:
                    continue
                meas.append([
                    round(float(t_s[j] - t_s[lo]), 1),
                    round((rho + rng.normal(0.0, SIGMA_RANGE_M)) / 1e3, 3),
                    round(float(az + rng.normal(0.0, SIGMA_ANGLE_DEG)), 3),
                    round(float(el + rng.normal(0.0, SIGMA_ANGLE_DEG)), 3),
                    i,
                ])
        meas.sort(key=lambda m: m[0])
        out_passes.append({
            "hours_after_deploy": round(float(t_s[lo]) / 3600.0 + N_OBJECTS * RELEASE_DT_S / 3600.0, 2),
            "start_utc": (t0 + float(t_s[lo])).isostring(),
            "t_s": [m[0] for m in meas],
            "range_km": [m[1] for m in meas],
            "az_deg": [m[2] for m in meas],
            "el_deg": [m[3] for m in meas],
            "obj": [m[4] for m in meas],
        })
        print(f"pass ~{target:.0f} h: {len(meas)} measurements of {len({m[4] for m in meas})} objects")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "objects": N_OBJECTS, "release_interval_s": RELEASE_DT_S, "separation_dv_ms": list(DV_RANGE_MS),
            "orbit": {"alt_km": ALT_KM, "inc_deg": INC_DEG}, "force_model": "brahe numerical, 8x8 gravity",
            "sensor": SENSOR, "sample_s": SAMPLE_DT_S, "el_min_deg": EL_MIN_DEG,
            "noise": {"range_m": SIGMA_RANGE_M, "angle_deg": SIGMA_ANGLE_DEG}, "seed": SEED,
        },
        "sensor": {"name": SENSOR, "lat": round(loc.lat, 3), "lon": round(loc.lon, 3)},
        "passes": out_passes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
