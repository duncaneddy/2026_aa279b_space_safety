# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Iridium 33 / Cosmos 2251: today's debris clouds and the 2009 collision geometry.

Debris clouds: counts every cataloged fragment of each parent (SATCAT name
"<PARENT> DEB" within the parent's launch designator) and how many are still
on orbit, then propagates the current GP element set of every on-orbit
fragment with SGP4 to one common epoch and reports GCRF positions. Fragments
whose latest element set is more than 30 days older than that epoch are
counted as on orbit but not plotted.

Collision: takes each parent's last GP element set before the collision on
2009-02-10 (~16:56 UTC), propagates both with SGP4, and finds the time of
closest approach (TCA). Reports the SGP4 miss distance, relative speed,
crossing angle between the velocity vectors, and one orbit of each parent
centred on the TCA (GCRF).

Data source: Space-Track.org SATCAT, GP and GP_HISTORY classes (requires
SPACETRACK_USER / SPACETRACK_PASS). Raw downloads are cached in
deck/data/raw/ and reused when present.

Run:
  uv run scripts/debris_clouds.py [--out PATH]

Output: deck/data/debris_clouds.json
"""

import argparse
import functools
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.spacetrack import operators as op

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "deck/data/raw"

PARENTS = [
    {"name": "Iridium 33", "norad": 24946, "intldes": "1997-051", "deb_name": "IRIDIUM 33 DEB"},
    {"name": "Cosmos 2251", "norad": 22675, "intldes": "1993-036", "deb_name": "COSMOS 2251 DEB"},
]
COLLISION_GUESS = bh.Epoch.from_datetime(2009, 2, 10, 16, 56, 0.0, 0.0, bh.TimeSystem.UTC)
SEARCH_S = 1800.0
ORBIT_POINTS = 181
MAX_AGE_DAYS = 30.0


@functools.cache
def spacetrack() -> bh.SpaceTrackClient:
    return bh.SpaceTrackClient(os.environ["SPACETRACK_USER"], os.environ["SPACETRACK_PASS"])


def cached_query(name: str, query: bh.SpaceTrackQuery) -> list[dict]:
    """Raw JSON result of a Space-Track query, downloaded once into deck/data/raw/."""
    path = RAW / f"{name}.json"
    if not path.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_text(spacetrack().query_raw(query))
    return json.loads(path.read_text())


def debris_cloud(parent: dict) -> tuple[dict, list[dict]]:
    """SATCAT counts and current GP records of a parent's fragments."""
    tag = parent["intldes"]
    satcat = cached_query(
        f"spacetrack_satcat_{tag}",
        bh.SpaceTrackQuery(bh.RequestClass.SATCAT).filter("INTLDES", op.startswith(tag)),
    )
    gp = cached_query(
        f"spacetrack_gp_{tag}",
        bh.SpaceTrackQuery(bh.RequestClass.GP)
        .filter("OBJECT_ID", op.startswith(tag))
        .filter("DECAY_DATE", op.null_val()),
    )
    fragments = [r for r in satcat if r["SATNAME"] == parent["deb_name"]]
    on_orbit = [r for r in fragments if r["DECAY"] is None]
    gp_frag = [r for r in gp if r["OBJECT_NAME"] == parent["deb_name"]]
    counts = {"cataloged": len(fragments), "on_orbit": len(on_orbit)}
    return counts, gp_frag


def pre_collision_propagators() -> list[bh.SGPPropagator]:
    """SGP4 propagators from each parent's last element set before the collision."""
    history = cached_query(
        "spacetrack_gp_history_iridium33_cosmos2251",
        bh.SpaceTrackQuery(bh.RequestClass.GP_HISTORY)
        .filter("NORAD_CAT_ID", op.or_list([str(p["norad"]) for p in PARENTS]))
        .filter("EPOCH", op.inclusive_range("2009-02-03", "2009-02-11"))
        .order_by("EPOCH", bh.SortOrder.ASC),
    )
    props = []
    for parent in PARENTS:
        candidates = [
            bh.SGPPropagator.from_tle(r["TLE_LINE1"], r["TLE_LINE2"], 60.0)
            for r in history
            if int(r["NORAD_CAT_ID"]) == parent["norad"]
        ]
        before = [p for p in candidates if p.epoch < COLLISION_GUESS - 600.0]
        props.append(max(before, key=lambda p: p.epoch.mjd()))
    return props


def separation(props, epoch: bh.Epoch) -> float:
    a, b = (p.state_gcrf(epoch) for p in props)
    return float(np.linalg.norm(a[:3] - b[:3]))


def find_tca(props) -> bh.Epoch:
    """Coarse 1 s scan around the reported time, then golden-section refinement."""
    t = np.arange(-SEARCH_S, SEARCH_S + 1.0, 1.0)
    d = [separation(props, COLLISION_GUESS + float(dt)) for dt in t]
    lo, hi = t[np.argmin(d)] - 1.0, t[np.argmin(d)] + 1.0
    g = (np.sqrt(5.0) - 1.0) / 2.0
    while hi - lo > 1e-4:
        m1, m2 = hi - g * (hi - lo), lo + g * (hi - lo)
        if separation(props, COLLISION_GUESS + m1) < separation(props, COLLISION_GUESS + m2):
            hi = m2
        else:
            lo = m1
    return COLLISION_GUESS + 0.5 * (lo + hi)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "deck/data/debris_clouds.json")
    args = parser.parse_args()

    bh.initialize_eop()
    clouds = [debris_cloud(p) for p in PARENTS]

    # Common epoch for the fragment snapshot: newest GP creation time, floored to the hour.
    created = datetime.fromisoformat(max(r["CREATION_DATE"] for _, gp in clouds for r in gp))
    epoch = bh.Epoch.from_datetime(
        created.year, created.month, created.day, created.hour, 0, 0.0, 0.0, bh.TimeSystem.UTC
    )

    groups = []
    for parent, (counts, gp) in zip(PARENTS, clouds):
        r = []
        for rec in gp:
            prop = bh.SGPPropagator.from_tle(rec["TLE_LINE1"], rec["TLE_LINE2"], 60.0)
            if epoch - prop.epoch > MAX_AGE_DAYS * 86400.0:
                # Old element sets (no recent tracking) extrapolate to unreliable positions.
                continue
            try:
                r.append(prop.state_gcrf(epoch)[:3])
            except bh.BraheError:
                # SGP4 raises when an element set propagates to an unphysical orbit by the epoch.
                continue
        r = np.array(r)
        alt = bh.position_ecef_to_geodetic(bh.position_gcrf_to_itrf(epoch, r), bh.AngleFormat.DEGREES)[:, 2] / 1e3
        r, alt = r[alt >= 100.0], alt[alt >= 100.0]
        groups.append(
            {
                "name": parent["name"],
                "parent_norad": parent["norad"],
                "cataloged": counts["cataloged"],
                "on_orbit": counts["on_orbit"],
                "xyz_km": np.round(r / 1e3, 1).tolist(),
                "alt_km": np.round(alt, 1).tolist(),
            }
        )

    props = pre_collision_propagators()
    tca = find_tca(props)
    x1, x2 = (p.state_gcrf(tca) for p in props)
    miss_km = np.linalg.norm(x1[:3] - x2[:3]) / 1e3
    rel_speed = np.linalg.norm(x1[3:] - x2[3:]) / 1e3
    cos_angle = np.dot(x1[3:], x2[3:]) / (np.linalg.norm(x1[3:]) * np.linalg.norm(x2[3:]))
    crossing_deg = np.degrees(np.arccos(cos_angle))
    tca_alt_km = bh.position_ecef_to_geodetic(
        bh.position_gcrf_to_itrf(tca, x1[:3]), bh.AngleFormat.DEGREES
    )[2] / 1e3

    orbits = []
    for parent, prop in zip(PARENTS, props):
        period = bh.orbital_period(bh.state_eci_to_koe(prop.state_gcrf(tca), bh.AngleFormat.DEGREES)[0])
        t = np.linspace(-0.5 * period, 0.5 * period, ORBIT_POINTS)
        xyz = np.array(prop.states_gcrf([tca + float(dt) for dt in t]))[:, :3] / 1e3
        orbits.append({"name": parent["name"], "xyz_km": np.round(xyz, 1).tolist()})

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "epoch": epoch.isostring(),
        "groups": groups,
        "collision": {
            "tca_utc": tca.isostring_with_decimals(3),
            "miss_km_sgp4": round(float(miss_km), 3),
            "rel_speed_kms": round(float(rel_speed), 3),
            "crossing_angle_deg": round(float(crossing_deg), 2),
            "alt_km": round(float(tca_alt_km), 1),
            "element_epochs": {p["name"]: prop.epoch.isostring() for p, prop in zip(PARENTS, props)},
            "orbits": orbits,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"fragment snapshot epoch {epoch.isostring()}")
    for g in groups:
        print(f"  {g['name']:12s} cataloged {g['cataloged']:5d}  on orbit {g['on_orbit']:5d}  "
              f"propagated {len(g['alt_km']):5d}")
    for p, prop in zip(PARENTS, props):
        print(f"  {p['name']:12s} pre-collision elements epoch {prop.epoch.isostring()}")
    print(f"TCA {tca.isostring_with_decimals(3)}  miss {miss_km:.3f} km  rel speed {rel_speed:.3f} km/s  "
          f"crossing {crossing_deg:.1f} deg  alt {tca_alt_km:.1f} km")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
