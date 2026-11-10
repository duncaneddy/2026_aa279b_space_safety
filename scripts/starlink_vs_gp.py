# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Catalog GP element set versus operator ephemeris for one Starlink satellite.

Computes the position difference between the public 18 SDS general perturbations
(GP) element set propagated with SGP4 and SpaceX's own GPS-based predicted
ephemeris for the same satellite, expressed in the radial / along-track /
cross-track (RTN) frame of the operator trajectory, together with the 1-sigma
RTN position uncertainty SpaceX publishes with that ephemeris.

Data sources:
  - Operator ephemeris: SpaceX's public Modified ITC ephemerides
    (https://api.starlink.com/public-files/ephemerides/), EME2000 states at
    60 s spacing over ~3 days with a 6x6 RTN ("UVW") covariance per record,
    fetched with brahe's StarlinkClient.
  - Catalog GP: Space-Track GP_HISTORY; the most recent element set whose
    epoch and creation date are at or before the first operator ephemeris
    epoch, i.e. the catalog state an analyst would have had when the operator
    ephemeris was produced.
    Requires SPACETRACK_USER and SPACETRACK_PASS in the environment.

SGP4 output (TEME) is rotated to GCRF and the operator EME2000 states are
rotated to GCRF (frame bias) before differencing.

Raw downloads are cached in deck/data/raw/starlink_vs_gp/ and reused when
present, so a rerun reproduces the same output. Delete that directory (or pass
a different --norad) to fetch the current ephemeris.

Run:
  uv run scripts/starlink_vs_gp.py [--norad 53253] [--out path.json]

Output (deck/data/starlink_vs_gp.json):
  {generated_utc, object:{name,norad}, operator_epoch, gp_epoch, t_h:[...],
   gp_minus_operator_rtn_km:{R,T,N}, operator_sigma_rtn_km:{R,T,N}|null}
  t_h is hours since the first operator ephemeris epoch.
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
DEFAULT_OUT = ROOT / "deck/data/starlink_vs_gp.json"
RAW_DIR = ROOT / "deck/data/raw/starlink_vs_gp"

DEFAULT_NORAD = 53253
GP_LOOKBACK_DAYS = 3.0
OUTPUT_STRIDE = 5  # keep every 5th 60 s record (5 min spacing)


def spacetrack_time(epc: bh.Epoch) -> str:
    y, mo, d, h, mi, s, _ = epc.to_datetime()
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{int(s):02d}"


def operator_ephemeris(norad: int) -> tuple[bh.ITC, Path]:
    cached = sorted(RAW_DIR.glob(f"MEME_{norad}_*.txt"))
    if cached:
        path = cached[-1]
    else:
        client = bh.StarlinkClient()
        path = Path(client.save_ephemeris(norad, str(RAW_DIR), keep_cached=True))
    return bh.ITC.from_file(str(path)), path


def catalog_gp(norad: int, t0: bh.Epoch, op_path: Path) -> bh.GPRecord:
    path = RAW_DIR / f"gp_history_{op_path.stem}.json"
    if path.exists():
        records = json.loads(path.read_text())
    else:
        client = bh.SpaceTrackClient(os.environ["SPACETRACK_USER"], os.environ["SPACETRACK_PASS"])
        start = t0 - GP_LOOKBACK_DAYS * 86400.0
        query = (
            bh.SpaceTrackQuery(bh.RequestClass.GP_HISTORY)
            .filter("NORAD_CAT_ID", str(norad))
            .filter("EPOCH", op.inclusive_range(spacetrack_time(start), spacetrack_time(t0)))
            .filter("CREATION_DATE", op.less_than(spacetrack_time(t0)))
            .order_by("EPOCH", bh.SortOrder.DESC)
            .limit(1)
        )
        records = client.query_json(query)
        if not records:
            raise RuntimeError(f"No GP for NORAD {norad} in the {GP_LOOKBACK_DAYS} d before {t0}")
        path.write_text(json.dumps(records, indent=1))
    return bh.GPRecord.from_json(json.dumps(records[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--norad", type=int, default=DEFAULT_NORAD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    itc, op_path = operator_ephemeris(args.norad)
    states = itc.states
    t0 = states[0].epoch
    epochs = [s.epoch for s in states]
    t_h = np.array([(e - t0) / 3600.0 for e in epochs])

    x_op = bh.state_eme2000_to_gcrf(np.array([s.to_vector() for s in states]))

    gp = catalog_gp(args.norad, t0, op_path)
    sgp = gp.to_sgp_propagator(60.0)
    x_gp = np.array(sgp.states_gcrf(epochs))

    # Relative position of the GP state with respect to the operator state,
    # in the operator trajectory's RTN frame.
    d_rtn_km = bh.state_eci_to_rtn(x_op, x_gp)[:, :3] / 1e3

    sigma_rtn_km = None
    if itc.has_covariance:
        if itc.header.covariance_frame != bh.ITCCovarianceFrame.RTN:
            raise RuntimeError(f"Expected RTN covariance, got {itc.header.covariance_frame}")
        sigma_rtn_km = np.array([np.sqrt(np.diag(c)[:3]) for c in itc.covariances]) / 1e3

    keep = slice(None, None, OUTPUT_STRIDE)
    name = itc.source_name.object_name if itc.source_name else gp.object_name
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "object": {"name": name, "norad": args.norad},
        "operator_epoch": t0.isostring(),
        "gp_epoch": sgp.epoch.isostring(),
        "t_h": np.round(t_h[keep], 4).tolist(),
        "gp_minus_operator_rtn_km": {
            k: np.round(d_rtn_km[keep, i], 4).tolist() for i, k in enumerate("RTN")
        },
        "operator_sigma_rtn_km": None
        if sigma_rtn_km is None
        else {k: np.round(sigma_rtn_km[keep, i], 5).tolist() for i, k in enumerate("RTN")},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    gp_age_h = (t0 - sgp.epoch) / 3600.0
    print(f"{name} (NORAD {args.norad})  operator file {op_path.name}")
    print(f"operator span {t0} .. {epochs[-1]} ({t_h[-1]:.1f} h, {len(states)} records)")
    print(f"GP epoch {sgp.epoch} ({gp_age_h:.1f} h before operator start)")
    print("   t [h]   GP-op R / T / N [km]           op 1-sigma R / T / N [km]")
    for h in (0, 6, 12, 24, 48, 72):
        k = int(np.argmin(np.abs(t_h - h)))
        sig = "" if sigma_rtn_km is None else "  ".join(f"{v:7.3f}" for v in sigma_rtn_km[k])
        rtn = "  ".join(f"{v:8.3f}" for v in d_rtn_km[k])
        print(f"  {t_h[k]:5.1f}   {rtn}     {sig}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
