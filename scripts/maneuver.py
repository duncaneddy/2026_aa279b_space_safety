# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy", "scipy"]
# ///
"""Collision-avoidance maneuver trade space: lead time x along-track delta-v.

For the real conjunction used in scripts/pc.py (CARA test CDM, CALIPSO x
COSMOS 2251 DEB), an impulsive prograde burn (along the primary's inertial
velocity) is applied to the primary a given number of hours before TCA. The
maneuvered and unmaneuvered primary are both propagated with brahe's
numerical propagator (20x20 EGM2008 gravity + Harris-Priester drag) from the
burn epoch, and the difference between them is added to the CDM primary
state, so integration error common to both arcs cancels. The time of closest
approach to the unchanged secondary is then re-found by Newton iteration on
rho . rho_dot = 0 using propagated states, and the 2D Foster Pc is recomputed
at the new miss vector with the CDM covariances unchanged.

A prograde burn raises the semi-major axis by da = 2 dv / n, the mean motion
drops by dn = -3 n dv / v, and the along-track position therefore drifts as
roughly -3 dv t once t exceeds an orbital period: the same miss distance costs
less delta-v the earlier the burn.

For each lead time the minimum delta-v achieving Pc below the threshold is
the first crossing on the delta-v grid, refined by bisection with further
propagations.

References:
  - J. L. Foster and H. S. Estes, NASA JSC-25898, 1992 (2D Pc).
  - F. K. Chan, Spacecraft Collision Probability, The Aerospace Press, 2008.
  - S. Alfano, "Satellite Conjunction Monte Carlo Analysis," AAS 09-233, 2009.
  - NASA CARA, "NASA Spacecraft Conjunction Assessment and Collision
    Avoidance Best Practices Handbook," NASA/SP-20230002470, 2023.

Run:
  uv run scripts/maneuver.py [--out path.json]

Output (deck/data/maneuver.json):
  {generated_utc, conjunction:{...}, lead_h:[...], dv_cms:[...],
   log10_pc:[[lead x dv]], miss_km:[[lead x dv]],
   along_track_shift_km:[[lead x dv]], log10_pc_floor, threshold,
   min_dv_cms:[per lead]}
  log10_pc is clipped below at log10_pc_floor for plotting.
  along_track_shift_km is the maneuvered minus unmaneuvered primary position
  at the nominal TCA along the primary's T axis (negative = behind).
  min_dv_cms is null where no delta-v on the grid reaches the threshold.
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.ccsds import CDM
from scipy import integrate, special

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deck/data/maneuver.json"
RAW_DIR = ROOT / "deck/data/raw/cara"

CARA_COMMIT = "86ba28ad2ae6acacff29df5933809e731f500935"
CARA_URL = f"https://raw.githubusercontent.com/nasa/CARA_Analysis_Tools/{CARA_COMMIT}/DataFiles"
EXAMPLE_ID = "000029108_conj_000034995_20220706_165058_20220705_143113"
HBR_M = 14.8

LEAD_H = [1, 2, 3, 4, 6, 8, 12, 18, 24, 36, 48, 60, 72]
DV_CMS = [round(0.25 * i, 2) for i in range(41)]
THRESHOLD = 1e-4
LOG10_PC_FLOOR = -30.0
BISECTION_STEPS = 8
TCA_ITERATIONS = 3

# Generic LEO spacecraft: [mass kg, drag area m^2, Cd].
PARAMS = np.array([600.0, 5.0, 2.2])


def load_cdm(name: str) -> CDM:
    """Fetch the CARA CDM once into deck/data/raw/cara/ and parse it with brahe.

    CARA's files write unavailable OD statistics as NaN, which the CCSDS
    standard does not allow for integer fields, so those lines are dropped.
    """
    path = RAW_DIR / f"{name}.cdm"
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{CARA_URL}/PcTestCaseCDMs/{name}.cdm", timeout=60) as resp:
            path.write_bytes(resp.read())
    lines = path.read_text().splitlines()
    kept = [ln for ln in lines if "=" not in ln or ln.split("=", 1)[1].split()[:1] != ["NaN"]]
    return CDM.from_str("\n".join(kept))


def encounter_plane(r1, v1, c1, r2, v2, c2) -> tuple[float, np.ndarray]:
    """Miss distance and 2x2 combined covariance in CARA's encounter frame."""
    r, v = r2 - r1, v2 - v1
    y = v / np.linalg.norm(v)
    h = np.cross(r, v)
    z = h / np.linalg.norm(h)
    x = np.cross(y, z)
    proj = np.vstack([x, z])
    return float(np.linalg.norm(r)), proj @ (c1[:3, :3] + c2[:3, :3]) @ proj.T


def pc_circle(miss: float, cp: np.ndarray, hbr: float) -> float:
    """Mass of N(0, cp) inside the circle of radius hbr at (miss, 0) (see scripts/pc.py)."""
    lam, vec = np.linalg.eigh(cp)
    cp = vec @ np.diag(np.maximum(lam, (1e-4 * hbr) ** 2)) @ vec.T
    sxx, sxz, szz = cp[0, 0], cp[0, 1], cp[1, 1]
    k = sxz / sxx
    s = np.sqrt(szz - sxz**2 / sxx)

    def integrand(x: float) -> float:
        h = np.sqrt(max(hbr**2 - (x - miss) ** 2, 0.0))
        a, b = (-h - k * x) / s, (h - k * x) / s
        mass = special.ndtr(b) - special.ndtr(a) if a < 0 else special.ndtr(-a) - special.ndtr(-b)
        return np.exp(-0.5 * x * x / sxx) / np.sqrt(2.0 * np.pi * sxx) * mass

    # Breakpoints around the Gaussian's core so a covariance much narrower than the
    # circle is never stepped over by the adaptive quadrature.
    lo, hi = miss - hbr, miss + hbr
    sx = np.sqrt(sxx)
    points = [p for p in (0.0, -5 * sx, -2 * sx, 2 * sx, 5 * sx) if lo < p < hi]
    pc, _ = integrate.quad(integrand, lo, hi, epsabs=0.0, epsrel=1e-10, limit=200, points=points or None)
    return float(pc)


class Encounter:
    """Propagation setup for the conjunction: CDM states at TCA in GCRF and covariances."""

    def __init__(self, cdm: CDM):
        self.tca = cdm.tca
        x1 = bh.state_eme2000_to_gcrf(np.asarray(cdm.object1_state, dtype=float))
        x2 = bh.state_eme2000_to_gcrf(np.asarray(cdm.object2_state, dtype=float))
        variant = bh.OrbitRelativeFrameVariant.INERTIAL
        self.x1, self.x2 = x1, x2
        self.p1 = bh.covariance_rtn_to_eci(x1, np.asarray(cdm.object1_covariance, dtype=float), variant)
        self.p2 = bh.covariance_rtn_to_eci(x2, np.asarray(cdm.object2_covariance, dtype=float), variant)
        src = bh.ParameterSource.parameter_index
        self.force = bh.ForceModelConfig(
            gravity=bh.GravityConfiguration.spherical_harmonic(20, 20),
            drag=bh.DragConfiguration(model=bh.AtmosphericModel.HARRIS_PRIESTER, area=src(1), cd=src(2)),
            mass=src(0),
        )
        self.config = (
            bh.NumericalPropagationConfig.with_method(bh.IntegrationMethod.RKF78).with_abs_tol(1e-9).with_rel_tol(1e-12)
        )

    def propagator(self, epoch: bh.Epoch, state: np.ndarray) -> bh.NumericalOrbitPropagator:
        return bh.NumericalOrbitPropagator(epoch, state, self.config, self.force, PARAMS)

    def state_at(self, state_tca: np.ndarray, dt: float) -> np.ndarray:
        """Propagate a state given at the nominal TCA by dt seconds."""
        prop = self.propagator(self.tca, state_tca)
        prop.propagate_to(self.tca + dt)
        return prop.current_state()

    def burn_states(self) -> dict[int, np.ndarray]:
        """Unmaneuvered primary state at each burn epoch, by backward propagation from TCA."""
        prop = self.propagator(self.tca, self.x1)
        states = {}
        for lead in sorted(LEAD_H):
            prop.propagate_to(self.tca - lead * 3600.0)
            states[lead] = prop.current_state()
        return states

    def closest_approach(self, x1_tca: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        """Newton iteration on f(dt) = rho . rho_dot with f' ~ |rho_dot|^2 (rectilinear motion)."""
        x1, x2, dt = x1_tca, self.x2, 0.0
        for _ in range(TCA_ITERATIONS):
            rho, rho_dot = x2[:3] - x1[:3], x2[3:] - x1[3:]
            dt -= float(rho @ rho_dot / (rho_dot @ rho_dot))
            x1, x2 = self.state_at(x1_tca, dt), self.state_at(self.x2, dt)
        return x1, x2, dt

    def run(self, lead: float, x_burn: np.ndarray, nom_tca: np.ndarray, dvs_cms: list[float]) -> list[dict]:
        """Burn, propagate to TCA (in parallel), re-find TCA and recompute Pc for each delta-v.

        The maneuver effect is the difference between the maneuvered arc and the
        unmaneuvered arc from the same burn state, both at the nominal TCA; it is
        added to the CDM primary state so that the two arcs' common integration
        error cancels and dv = 0 reproduces the CDM geometry exactly.
        """
        epoch0 = self.tca - lead * 3600.0
        v_hat = x_burn[3:] / np.linalg.norm(x_burn[3:])
        props = []
        for dv in dvs_cms:
            x0 = x_burn.copy()
            x0[3:] += 0.01 * dv * v_hat
            props.append(self.propagator(epoch0, x0))
        bh.par_propagate_to(props, self.tca)
        rtn = bh.rotation_eci_to_rtn(nom_tca)
        out = []
        for prop in props:
            delta = prop.current_state() - nom_tca
            x1, x2, dt = self.closest_approach(self.x1 + delta)
            miss, cp = encounter_plane(x1[:3], x1[3:], self.p1, x2[:3], x2[3:], self.p2)
            out.append(
                {"pc": pc_circle(miss, cp, HBR_M), "miss_m": miss, "tca_shift_s": dt, "dT_m": float((rtn @ delta[:3])[1])}
            )
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()
    cdm = load_cdm(EXAMPLE_ID)
    enc = Encounter(cdm)
    burn = enc.burn_states()

    miss0, cp0 = encounter_plane(enc.x1[:3], enc.x1[3:], enc.p1, enc.x2[:3], enc.x2[3:], enc.p2)
    pc0 = pc_circle(miss0, cp0, HBR_M)

    log10_pc, miss_km, shift_km, min_dv = [], [], [], []
    for lead in LEAD_H:
        nominal = enc.propagator(enc.tca - lead * 3600.0, burn[lead])
        nominal.propagate_to(enc.tca)
        nom_tca = nominal.current_state()
        rows = enc.run(lead, burn[lead], nom_tca, DV_CMS)
        pcs = np.array([r["pc"] for r in rows])
        log10_pc.append([round(max(float(np.log10(max(p, 1e-320))), LOG10_PC_FLOOR), 3) for p in pcs])
        miss_km.append([round(r["miss_m"] / 1e3, 4) for r in rows])
        shift_km.append([round(r["dT_m"] / 1e3, 4) for r in rows])

        below = np.nonzero(pcs < THRESHOLD)[0]
        if len(below) == 0:
            min_dv.append(None)
        elif below[0] == 0:
            min_dv.append(0.0)
        else:
            lo, hi = DV_CMS[below[0] - 1], DV_CMS[below[0]]
            for _ in range(BISECTION_STEPS):
                mid = 0.5 * (lo + hi)
                if enc.run(lead, burn[lead], nom_tca, [mid])[0]["pc"] < THRESHOLD:
                    hi = mid
                else:
                    lo = mid
            min_dv.append(round(hi, 3))
        print(
            f"lead {lead:3d} h: Pc(dv=0) {pcs[0]:.3e}, Pc(dv={DV_CMS[-1]} cm/s) {pcs[-1]:.3e}, "
            f"miss {rows[-1]['miss_m'] / 1e3:.2f} km, min dv for Pc<{THRESHOLD:g}: {min_dv[-1]} cm/s"
        )

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conjunction": {
            "source": f"CARA test CDM {EXAMPLE_ID}",
            "primary": {"name": cdm.object1_name.strip(), "norad": int(cdm.object1_designator)},
            "secondary": {"name": cdm.object2_name.strip(), "norad": int(cdm.object2_designator)},
            "tca_utc": enc.tca.isostring_with_decimals(3),
            "miss_m": round(miss0, 2),
            "rel_speed_kms": round(float(np.linalg.norm(enc.x2[3:] - enc.x1[3:])) / 1e3, 4),
            "hbr_m": HBR_M,
            "pc": float(f"{pc0:.6g}"),
            "burn": "impulsive, along the primary's inertial velocity (prograde) at TCA - lead",
            "propagation": "brahe NumericalOrbitPropagator, 20x20 EGM2008 + Harris-Priester drag, RKF78 (abs 1e-9, rel 1e-12); "
            "mass 600 kg, drag area 5 m^2, Cd 2.2",
            "pc_method": "Foster 2D Pc at the re-found TCA, CDM covariances unchanged",
        },
        "lead_h": LEAD_H,
        "dv_cms": DV_CMS,
        "log10_pc": log10_pc,
        "miss_km": miss_km,
        "along_track_shift_km": shift_km,
        "log10_pc_floor": LOG10_PC_FLOOR,
        "threshold": THRESHOLD,
        "min_dv_cms": min_dv,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))
    print(f"nominal: miss {miss0:.1f} m, Pc {pc0:.4e}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
