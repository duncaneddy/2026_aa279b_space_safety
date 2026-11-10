# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Snapshot of the public on-orbit catalog at one common epoch.

Downloads the latest Space-Track GP (OMM) element set for every non-decayed
object whose element set is less than 30 days old, propagates each one with
SGP4 to a single common epoch, and writes GCRF positions, geodetic altitude,
object type, and counts by object type and orbit regime. The CelesTrak
"active" group supplies the count of active payloads and of active Starlink
satellites.

Orbit regimes are assigned from the GP mean elements (h = a - R_earth):
  HEO  e >= 0.25
  LEO  h < 2000 km
  GEO  |h - 35786 km| <= 200 km, e < 0.01, i < 20 deg
  MEO  2000 km <= h < 35586 km
  other  the rest: inclined/eccentric near-GEO, super-GEO disposal and cislunar orbits

Data sources:
  Space-Track.org GP class (requires SPACETRACK_USER / SPACETRACK_PASS)
  CelesTrak GP "active" group
Raw downloads are cached in deck/data/raw/ and reused when present; delete
the cache files to fetch fresh data.

Run:
  uv run scripts/catalog.py [--out PATH]

Output: deck/data/catalog.json
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.spacetrack import operators as op

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "deck/data/raw"
GP_CACHE = RAW / "spacetrack_gp_catalog.json"
ACTIVE_CACHE = RAW / "celestrak_active.json"

TYPE_CODE = {"PAYLOAD": "P", "ROCKET BODY": "R", "DEBRIS": "D"}
H_GEO_KM = 35786.0


def fetch_catalog() -> list[dict]:
    """Latest GP record of every non-decayed object with an epoch in the last 30 days."""
    if not GP_CACHE.exists():
        client = bh.SpaceTrackClient(os.environ["SPACETRACK_USER"], os.environ["SPACETRACK_PASS"])
        query = (
            bh.SpaceTrackQuery(bh.RequestClass.GP)
            .filter("DECAY_DATE", op.null_val())
            .filter("EPOCH", op.greater_than(op.now_offset(-30)))
            .order_by("NORAD_CAT_ID", bh.SortOrder.ASC)
        )
        RAW.mkdir(parents=True, exist_ok=True)
        GP_CACHE.write_text(client.query_raw(query))
    return json.loads(GP_CACHE.read_text())


def fetch_active() -> list[dict] | None:
    """CelesTrak GP records for the 'active' group (operational payloads), or None if unreachable."""
    if not ACTIVE_CACHE.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        query = bh.celestrak.CelestrakQuery.gp.group("active").format(
            bh.celestrak.CelestrakOutputFormat.JSON
        )
        try:
            bh.celestrak.CelestrakClient(max_retries=1).download(query, str(ACTIVE_CACHE))
        except bh.BraheError as err:
            ACTIVE_CACHE.unlink(missing_ok=True)
            print(f"WARNING: CelesTrak unreachable ({err}); active_payloads and starlink set to null")
            return None
    return json.loads(ACTIVE_CACHE.read_text())


def tle_lines(rec: dict) -> tuple[str, str]:
    """TLE lines of a GP record with the catalog-number field zero-padded.

    Space-Track blank-pads some catalog numbers ("1   115U ..."); brahe's TLE
    parser expects five characters without blanks. Blanks and zeros both count
    as 0 in the TLE checksum, so the checksum stays valid. Objects above 99999
    already use the five-character Alpha-5 form.
    """
    return tuple(line[:2] + line[2:7].replace(" ", "0") + line[7:] for line in (rec["TLE_LINE1"], rec["TLE_LINE2"]))


def regime(rec: dict) -> str:
    a_km = float(rec["SEMIMAJOR_AXIS"])
    e = float(rec["ECCENTRICITY"])
    i = float(rec["INCLINATION"])
    h = a_km - bh.R_EARTH / 1e3
    if e >= 0.25:
        return "heo"
    if h < 2000.0:
        return "leo"
    if abs(h - H_GEO_KM) <= 200.0 and e < 0.01 and i < 20.0:
        return "geo"
    if h < H_GEO_KM - 200.0:
        return "meo"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "deck/data/catalog.json")
    args = parser.parse_args()

    bh.initialize_eop()
    records = fetch_catalog()
    active = fetch_active()

    # Common epoch: when Space-Track generated the download, floored to the hour.
    created = datetime.fromisoformat(max(r["CREATION_DATE"] for r in records))
    epoch = bh.Epoch.from_datetime(
        created.year, created.month, created.day, created.hour, 0, 0.0, 0.0, bh.TimeSystem.UTC
    )

    ok, r_gcrf = [], []
    for rec in records:
        try:
            prop = bh.SGPPropagator.from_tle(*tle_lines(rec), 60.0)
            r_gcrf.append(prop.state_gcrf(epoch)[:3])
            ok.append(rec)
        except bh.BraheError:
            # SGP4 raises when an element set propagates to an unphysical orbit
            # (e.g. negative eccentricity) by the target epoch.
            pass
    r_gcrf = np.array(r_gcrf)
    alt_km = (
        bh.position_ecef_to_geodetic(bh.position_gcrf_to_itrf(epoch, r_gcrf), bh.AngleFormat.DEGREES)[:, 2]
        / 1e3
    )

    # Stale element sets of reentering objects can propagate below the surface without
    # an SGP4 error; anything under 100 km at the epoch has decayed.
    alive = alt_km >= 100.0
    kept = [rec for rec, a in zip(ok, alive) if a]
    r_gcrf, alt_km = r_gcrf[alive], alt_km[alive]
    n_dropped = len(records) - len(kept)

    # Starlink satellites get their own code ("S") so the deck can show them separately.
    types = [
        "S" if r["OBJECT_TYPE"] == "PAYLOAD" and r["OBJECT_NAME"].startswith("STARLINK") else TYPE_CODE.get(r["OBJECT_TYPE"], "U")
        for r in kept
    ]
    regimes = [regime(r) for r in kept]
    active_payloads = None if active is None else len(active)
    starlink_active = None if active is None else sum(1 for r in active if r["OBJECT_NAME"].startswith("STARLINK"))

    counts = {
        "total": len(kept),
        "payload": types.count("P") + types.count("S"),
        "starlink": types.count("S"),
        "other_payload": types.count("P"),
        "rocket_body": types.count("R"),
        "debris": types.count("D"),
        "unknown": types.count("U"),
        "active_payloads": active_payloads,
        "starlink_active": starlink_active,
        "leo": regimes.count("leo"),
        "meo": regimes.count("meo"),
        "geo": regimes.count("geo"),
        "heo": regimes.count("heo"),
        "other": regimes.count("other"),
        "norad_ge_100000": sum(1 for r in kept if int(r["NORAD_CAT_ID"]) >= 100000),
    }

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "epoch": epoch.isostring(),
        "source": (
            "Space-Track.org GP (non-decayed, epoch within 30 days of download), "
            "SGP4 to common epoch, TEME->GCRF via brahe; active payloads and Starlink "
            "from CelesTrak 'active' group"
        ),
        "counts": counts,
        "objects": {
            "type": types,
            "xyz_km": np.rint(r_gcrf / 1e3).astype(int).tolist(),
            "alt_km": np.rint(alt_km).astype(int).tolist(),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"epoch {epoch.isostring()}  ({len(records)} GP records, {n_dropped} failed SGP4 or below 100 km)")
    for k, v in counts.items():
        print(f"  {k:16s} {v}")
    print(f"altitude range {alt_km.min():.0f} .. {alt_km.max():.0f} km")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
