# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Three common TLE mistakes, quantified for the ISS over 24 hours.

(a) Frame: SGP4 returns states in TEME (true equator, mean equinox of date).
    Treating that output as if it were GCRF/J2000 leaves a rotation of a few
    tenths of a degree (mostly precession since J2000), i.e. tens of km in LEO.
    Computed as |r_TEME - r_GCRF| for the same SGP4 state.

(b) Elements: TLE elements are SGP4 mean elements, not osculating Keplerian
    elements. Converting them directly to a Cartesian state and propagating
    with another propagator gives the wrong orbit. Computed as the position
    difference between SGP4 (the reference the elements were fitted for) and
    a numerical J2 propagation started from the TLE mean elements treated as
    osculating elements in TEME. A control run of the same J2 propagator,
    started from the SGP4 state at epoch, shows how much of the difference
    comes from the force models alone.

(c) Propagator: the elements are only valid with SGP4. Even with the proper
    mean-to-osculating conversion (SGP4's own state at epoch, which applies
    its short-period terms), a numerical propagator with an approximately
    equivalent force model (J2-J4 zonals, Harris-Priester drag with the
    ballistic coefficient implied by B*) drifts away from SGP4.

Data source: latest ISS (NORAD 25544) GP element set from Space-Track.org
(requires SPACETRACK_USER / SPACETRACK_PASS). The raw download is cached in
deck/data/raw/ and reused when present.

Run:
  uv run scripts/tle_gotchas.py [--out PATH]

Output: deck/data/tle_gotchas.json
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "deck/data/raw"
NORAD = 25544
CACHE = RAW / f"spacetrack_gp_{NORAD}.json"
SPAN_H = 24.0
STEP_S = 300.0
BSTAR_TO_BALLISTIC = 12.741621  # Cd*A/m [m^2/kg] per unit B* [1/Earth radii]


def fetch_gp() -> dict:
    """Latest GP record for the object."""
    if not CACHE.exists():
        client = bh.SpaceTrackClient(os.environ["SPACETRACK_USER"], os.environ["SPACETRACK_PASS"])
        query = (
            bh.SpaceTrackQuery(bh.RequestClass.GP)
            .filter("NORAD_CAT_ID", str(NORAD))
            .order_by("EPOCH", bh.SortOrder.DESC)
            .limit(1)
        )
        RAW.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(client.query_raw(query))
    return json.loads(CACHE.read_text())[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "deck/data/tle_gotchas.json")
    args = parser.parse_args()

    bh.initialize_eop()
    rec = fetch_gp()
    line1, line2 = rec["TLE_LINE1"], rec["TLE_LINE2"]
    sgp = bh.SGPPropagator.from_tle(line1, line2, 60.0)
    epoch0 = sgp.epoch

    t_s = np.arange(0.0, SPAN_H * 3600.0 + 1.0, STEP_S)
    epochs = [epoch0 + float(t) for t in t_s]

    # (a) Same SGP4 state, expressed in TEME (native output) and in GCRF.
    r_teme = np.array(sgp.states(epochs))[:, :3]
    r_gcrf = np.array(sgp.states_gcrf(epochs))[:, :3]
    teme_vs_gcrf_km = np.linalg.norm(r_teme - r_gcrf, axis=1) / 1e3
    rot = bh.rotation_teme_to_gcrf(epoch0)
    teme_gcrf_angle_deg = np.degrees(np.arccos((np.trace(rot) - 1.0) / 2.0))

    # (b) TLE mean elements used as osculating Keplerian elements in TEME.
    n_deg_s = float(rec["MEAN_MOTION"]) * 360.0 / 86400.0
    oe_mean = np.array(
        [
            bh.semimajor_axis(n_deg_s, bh.AngleFormat.DEGREES),
            float(rec["ECCENTRICITY"]),
            float(rec["INCLINATION"]),
            float(rec["RA_OF_ASC_NODE"]),
            float(rec["ARG_OF_PERICENTER"]),
            float(rec["MEAN_ANOMALY"]),
        ]
    )
    x0_teme = bh.state_koe_to_eci(oe_mean, bh.AngleFormat.DEGREES)
    x0_gcrf = bh.state_teme_to_gcrf(epoch0, x0_teme)

    def numerical_positions(x0: np.ndarray, force: bh.ForceModelConfig) -> np.ndarray:
        prop = bh.NumericalOrbitPropagator(epoch0, x0, bh.NumericalPropagationConfig.default(), force)
        prop.propagate_to(epochs[-1])
        return np.array(prop.states_gcrf(epochs))[:, :3]

    def j2_positions(x0: np.ndarray) -> np.ndarray:
        return numerical_positions(x0, bh.ForceModelConfig(gravity=bh.GravityConfiguration.earth_zonal(bh.ZonalHarmonicsDegree.J2)))

    ballistic = BSTAR_TO_BALLISTIC * float(rec["BSTAR"])
    sgp4_like = bh.ForceModelConfig(
        gravity=bh.GravityConfiguration.earth_zonal(bh.ZonalHarmonicsDegree.J4),
        drag=bh.DragConfiguration(
            model=bh.AtmosphericModel.HARRIS_PRIESTER,
            area=bh.ParameterSource.value(ballistic),
            cd=bh.ParameterSource.value(1.0),
        ),
        mass=bh.ParameterSource.value(1.0),
    )

    mean_as_osc_km = np.linalg.norm(j2_positions(x0_gcrf) - r_gcrf, axis=1) / 1e3
    osc_init_km = np.linalg.norm(j2_positions(sgp.state_gcrf(epoch0)) - r_gcrf, axis=1) / 1e3
    numerical_km = np.linalg.norm(numerical_positions(sgp.state_gcrf(epoch0), sgp4_like) - r_gcrf, axis=1) / 1e3

    osc = sgp.state_koe_osc(epoch0, bh.AngleFormat.DEGREES)
    da_km = (oe_mean[0] - osc[0]) / 1e3

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "object": {"name": rec["OBJECT_NAME"], "norad": NORAD},
        "tle_epoch": epoch0.isostring(),
        "example_tle": [line1, line2],
        # The same element set as a GP record (CCSDS OMM keys), without the legacy TLE lines.
        "gp_record": {k: v for k, v in rec.items() if not k.startswith("TLE_LINE")},
        "t_h": np.round(t_s / 3600.0, 4).tolist(),
        "teme_vs_gcrf_km": np.round(teme_vs_gcrf_km, 3).tolist(),
        "mean_as_osc_km": np.round(mean_as_osc_km, 3).tolist(),
        "osc_init_j2_km": np.round(osc_init_km, 3).tolist(),
        "osc_init_numerical_km": np.round(numerical_km, 3).tolist(),
        "notes": {
            "teme": (
                "SGP4 output is in TEME (true equator, mean equinox of date), not GCRF/J2000. "
                f"At this epoch the TEME->GCRF rotation is {teme_gcrf_angle_deg:.3f} deg "
                f"({teme_vs_gcrf_km.mean():.1f} km at the ISS orbit radius)."
            ),
            "mean_elements": (
                "TLE/GP elements are SGP4 mean elements fitted to observations for use with "
                "SGP4 only. Treated as osculating elements they place the ISS "
                f"{mean_as_osc_km[0]:.1f} km from the SGP4 position at epoch (semi-major axis "
                f"off by {da_km:+.1f} km); the resulting period error grows along-track to "
                f"{mean_as_osc_km[-1]:.0f} km after {SPAN_H:.0f} h of J2 propagation. The same "
                f"J2 propagation started from the SGP4 state differs by {osc_init_km[-1]:.0f} km "
                "(force-model differences only)."
            ),
            "propagator": (
                "Started from SGP4's own osculating state at epoch and propagated numerically with "
                f"J2-J4 zonals and Harris-Priester drag (Cd*A/m = {ballistic:.2e} m^2/kg from B*), "
                f"the ISS is {numerical_km[-1]:.1f} km from SGP4 after {SPAN_H:.0f} h "
                f"(max {numerical_km.max():.1f} km)."
            ),
            "epoch": "TLE epoch is UTC as YYDDD.DDDDDDDD; two-digit year 57-99 = 19xx, 00-56 = 20xx.",
            "catalog_number": (
                "The TLE catalog-number field holds 5 characters; numbers 100000-339999 use "
                "Alpha-5 (a leading letter, e.g. A0000 = 100000). OMM/GP has no such limit."
            ),
            "bstar": "B* is a fitted drag term; it absorbs other unmodeled effects and can be negative.",
            "no_covariance": "TLE/GP data carry no uncertainty information.",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"{rec['OBJECT_NAME']} TLE epoch {epoch0.isostring()}")
    print(f"  TEME vs GCRF: rotation {teme_gcrf_angle_deg:.3f} deg, "
          f"{teme_vs_gcrf_km.min():.1f}..{teme_vs_gcrf_km.max():.1f} km")
    print(f"  mean-as-osculating, J2: {mean_as_osc_km[0]:.2f} km at epoch, "
          f"{mean_as_osc_km[-1]:.1f} km at {SPAN_H:.0f} h (max {mean_as_osc_km.max():.1f})")
    print(f"  control (J2 from SGP4 state): {osc_init_km[-1]:.1f} km at {SPAN_H:.0f} h")
    print(f"  SGP4-like numerical (J4 + drag, Cd*A/m {ballistic:.2e}): {numerical_km[-1]:.1f} km at "
          f"{SPAN_H:.0f} h (max {numerical_km.max():.1f})")
    print(f"  a_mean - a_osc at epoch: {da_km:+.2f} km")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
