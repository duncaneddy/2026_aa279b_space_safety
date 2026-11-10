# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Monte Carlo versus linearized covariance propagation for a LEO object.

An object at ~400 km starts with a Gaussian uncertainty in position, velocity
(diagonal in RTN) and drag coefficient. Samples drawn from that distribution
are propagated with brahe's numerical propagator (8x8 EGM2008 gravity and
NRLMSISE-00 drag with observed space weather) and compared at several
snapshot times with the linearized covariance of the nominal trajectory,
P(t) = Phi P0 Phi^T + S sigma_Cd^2 S^T, built from brahe's state transition
matrix Phi and parameter sensitivity S.

Each snapshot is expressed in a local Cartesian frame centered on the nominal
position: x along the along-track (RTN T) direction at the nominal, y along the
radial direction, in km. The Monte Carlo samples follow the curved orbit (the
"banana"), while the linear covariance is an ellipse in the tangent plane.

Data sources: brahe's default EOP and space weather files (downloaded to the
brahe cache on first use). No other downloads.

Run:
  uv run scripts/covariance_banana.py [--samples 500] [--out path.json]
Propagation is parallelized over brahe's thread pool; 500 samples over 7 days
take about 4-5 minutes on a 10-core laptop.

Output (deck/data/covariance_banana.json):
  {generated_utc, config:{...}, snapshots:[{t_h, samples_xy_km:[[along,radial],...],
   ellipse_cov_km2:[[a,b],[b,c]], arc_xy_km:[[along,radial],...]}]}
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deck/data/covariance_banana.json"

SEED = 279
DEFAULT_SAMPLES = 500
EPOCH = (2025, 3, 1, 0, 0, 0.0)
ALT_KM = 400.0
ECC = 0.0005
INC_DEG = 51.6
MASS_KG = 100.0
AREA_M2 = 1.0  # area-to-mass 0.01 m^2/kg
CD = 2.2

SIGMA_POS_RTN_M = np.array([100.0, 500.0, 100.0])
SIGMA_VEL_RTN_MS = np.array([0.5, 0.1, 0.1])
SIGMA_CD_FRAC = 0.20

SNAPSHOT_DAYS = [0.0, 1.0, 3.0, 5.0, 7.0]
ARC_POINTS = 101
ARC_MARGIN = 1.25
ARC_PAD_S = 3600.0

CD_INDEX = 2


def force_model() -> bh.ForceModelConfig:
    return bh.ForceModelConfig(
        gravity=bh.GravityConfiguration(degree=8, order=8),
        drag=bh.DragConfiguration(
            bh.AtmosphericModel.NRLMSISE00,
            bh.ParameterSource.parameter_index(1),
            bh.ParameterSource.parameter_index(CD_INDEX),
        ),
        mass=bh.ParameterSource.parameter_index(0),
    )


def propagation_config() -> bh.NumericalPropagationConfig:
    return bh.NumericalPropagationConfig.with_method(bh.IntegrationMethod.RKF78).with_abs_tol(1e-6).with_rel_tol(1e-12)


def local_xy(x_nom: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Positions r (n, 3) relative to the nominal, as (along-track, radial) in km."""
    rot = bh.rotation_eci_to_rtn(x_nom)
    d = (r - x_nom[:3]) @ rot.T
    return np.column_stack([d[:, 1], d[:, 0]]) / 1e3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()
    bh.initialize_sw()
    rng = np.random.default_rng(SEED)

    epoch0 = bh.Epoch(*EPOCH, time_system=bh.UTC)
    oe = np.array([bh.R_EARTH + ALT_KM * 1e3, ECC, INC_DEG, 0.0, 0.0, 0.0])
    x0 = bh.state_koe_to_eci(oe, bh.AngleFormat.DEGREES)
    params0 = np.array([MASS_KG, AREA_M2, CD])

    p0_rtn = np.diag(np.concatenate([SIGMA_POS_RTN_M, SIGMA_VEL_RTN_MS]) ** 2)
    p0 = bh.covariance_rtn_to_eci(x0, p0_rtn, bh.OrbitRelativeFrameVariant.INERTIAL)
    var_cd = (SIGMA_CD_FRAC * CD) ** 2

    # Nominal with STM and Cd sensitivity for the linearized covariance.
    nominal = bh.NumericalOrbitPropagator(
        epoch0, x0, propagation_config().with_stm().with_sensitivity(), force_model(), params=params0
    )
    nominal.set_trajectory_mode(bh.TrajectoryMode.DISABLED)

    # Dense nominal trajectory, starting before epoch0, to draw orbit arcs around each snapshot.
    back = bh.NumericalOrbitPropagator(epoch0, x0, propagation_config(), force_model(), params=params0)
    back.set_trajectory_mode(bh.TrajectoryMode.DISABLED)
    back.propagate_to(epoch0 - ARC_PAD_S)
    reference = bh.NumericalOrbitPropagator(
        epoch0 - ARC_PAD_S,
        back.current_state(),
        propagation_config().with_max_step(30.0),
        force_model(),
        params=params0,
    )
    reference.propagate_to(epoch0 + max(SNAPSHOT_DAYS) * 86400.0 + ARC_PAD_S)

    dx = rng.multivariate_normal(np.zeros(6), p0, size=args.samples)
    cd = CD * (1.0 + SIGMA_CD_FRAC * rng.standard_normal(args.samples))
    samples = []
    for k in range(args.samples):
        prop = bh.NumericalOrbitPropagator(
            epoch0, x0 + dx[k], propagation_config(), force_model(), params=np.array([MASS_KG, AREA_M2, cd[k]])
        )
        prop.set_trajectory_mode(bh.TrajectoryMode.DISABLED)
        samples.append(prop)

    snapshots = []
    print("  t [d]   MC std along/radial [km]   linear std along/radial [km]   MC mean radial [km]")
    for days in SNAPSHOT_DAYS:
        epc = epoch0 + days * 86400.0
        if days > 0.0:
            bh.par_propagate_to(samples, epc)
            nominal.propagate_to(epc)
        x_nom = nominal.current_state()
        r_samples = np.array([p.current_state()[:3] for p in samples])
        xy = local_xy(x_nom, r_samples)

        phi = nominal.stm()
        s_cd = nominal.sensitivity()[:, CD_INDEX] if days > 0.0 else np.zeros(6)
        p_t = phi @ p0 @ phi.T + var_cd * np.outer(s_cd, s_cd)
        rot = bh.rotation_eci_to_rtn(x_nom)
        c_rtn = rot @ p_t[:3, :3] @ rot.T
        cov_xy = np.array([[c_rtn[1, 1], c_rtn[1, 0]], [c_rtn[0, 1], c_rtn[0, 0]]]) / 1e6

        speed = np.linalg.norm(x_nom[3:])
        tau_max = ARC_MARGIN * np.abs(xy[:, 0]).max() * 1e3 / speed
        arc_epochs = [epc + tau for tau in np.linspace(-tau_max, tau_max, ARC_POINTS)]
        arc = local_xy(x_nom, np.array(reference.states_eci(arc_epochs))[:, :3])

        mc_std = xy.std(axis=0)
        lin_std = np.sqrt(np.diag(cov_xy))
        print(f"  {days:4.1f}    {mc_std[0]:9.2f} / {mc_std[1]:6.2f}        {lin_std[0]:9.2f} / {lin_std[1]:6.2f}            {xy[:, 1].mean():8.2f}")

        snapshots.append(
            {
                "t_h": days * 24.0,
                "samples_xy_km": np.round(xy, 3).tolist(),
                "ellipse_cov_km2": np.round(cov_xy, 6).tolist(),
                "arc_xy_km": np.round(arc, 3).tolist(),
            }
        )

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "epoch_utc": epoch0.isostring(),
            "orbit": {"alt_km": ALT_KM, "ecc": ECC, "inc_deg": INC_DEG},
            "spacecraft": {"mass_kg": MASS_KG, "area_m2": AREA_M2, "cd": CD},
            "force_model": "EGM2008 8x8, NRLMSISE-00 drag (observed space weather)",
            "initial_sigma_rtn": {
                "pos_m": SIGMA_POS_RTN_M.tolist(),
                "vel_ms": SIGMA_VEL_RTN_MS.tolist(),
                "cd_frac": SIGMA_CD_FRAC,
            },
            "samples": args.samples,
            "seed": SEED,
            "frame": "x = along-track (RTN T at nominal), y = radial, Cartesian, nominal at origin",
            "linear_covariance": "Phi P0 Phi^T + S var_cd S^T from brahe STM and Cd sensitivity",
        },
        "snapshots": snapshots,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
