# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Simulated GPS-based orbit determination followed by a measurement-free prediction.

A ~500 km sun-synchronous satellite is simulated with a high-fidelity truth
model (20x20 EGM2008 gravity, NRLMSISE-00 drag driven by observed space
weather, SRP with conical eclipse, Sun and Moon third body). An on-board GPS
receiver provides ECEF position fixes every 30 s with 5 m (1-sigma, per axis)
white noise for 6 h. An extended Kalman filter with a deliberately simpler
dynamics model (20x20 gravity, Harris-Priester density, drag coefficient 2.0
instead of the true 2.3, no SRP or third body) and white acceleration process
noise processes the fixes, then predicts without measurements for 4 days.

The output is the estimation error (filter minus truth) and the filter's
3-sigma position uncertainty, both in the RTN frame of the filter estimate,
through the estimation and prediction phases.

Data sources: brahe's default EOP and space weather files (downloaded to the
brahe cache on first use). No other downloads.

Run:
  uv run scripts/gps_od.py [--out path.json]

Output (deck/data/gps_od.json):
  {generated_utc, config:{...}, est_end_h, t_h:[...], err_rtn_m:{R,T,N},
   sigma3_rtn_m:{R,T,N}, meas_t_h:[...]}
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deck/data/gps_od.json"

SEED = 279
EPOCH = (2025, 3, 1, 0, 0, 0.0)
ALT_KM = 500.0
ECC = 0.001
INC_DEG = 97.4  # sun-synchronous at 500 km
MASS_KG = 100.0
AREA_M2 = 1.0
CD_TRUE = 2.3
CD_FILTER = 2.0
CR = 1.3

MEAS_DT_S = 30.0
MEAS_SIGMA_M = 5.0
EST_SPAN_H = 6.0
PRED_SPAN_D = 4.0
PRED_OUTPUT_DT_S = 600.0

SIGMA0_POS_M = 100.0
SIGMA0_VEL_MS = 0.1
# White acceleration noise PSD on the velocity states [m^2/s^3]. The filter's
# drag acceleration is ~35% low (Harris-Priester vs NRLMSISE-00 at F10.7 ~150,
# and Cd 2.0 vs 2.3), a bias of a few 1e-7 m/s^2. The PSD is tuned so the
# predicted along-track 3-sigma bound contains that error over the 4-day
# prediction; a white-noise model cannot reproduce the t^2 growth of a bias,
# so the radial bound is exceeded late in the prediction.
Q_ACCEL = 3e-9
MAX_NOISE_DT_S = 60.0


def truth_force_model() -> bh.ForceModelConfig:
    return bh.ForceModelConfig(
        gravity=bh.GravityConfiguration(degree=20, order=20),
        drag=bh.DragConfiguration(
            bh.AtmosphericModel.NRLMSISE00,
            bh.ParameterSource.parameter_index(1),
            bh.ParameterSource.parameter_index(2),
        ),
        srp=bh.SolarRadiationPressureConfiguration(
            bh.ParameterSource.parameter_index(3),
            bh.ParameterSource.parameter_index(4),
            bh.EclipseModel.CONICAL,
        ),
        third_body=[
            bh.ThirdBodyConfiguration(bh.ThirdBody.SUN, bh.EphemerisSource.LowPrecision),
            bh.ThirdBodyConfiguration(bh.ThirdBody.MOON, bh.EphemerisSource.LowPrecision),
        ],
        mass=bh.ParameterSource.parameter_index(0),
    )


def filter_force_model() -> bh.ForceModelConfig:
    return bh.ForceModelConfig(
        gravity=bh.GravityConfiguration(degree=20, order=20),
        drag=bh.DragConfiguration(
            bh.AtmosphericModel.HARRIS_PRIESTER,
            bh.ParameterSource.parameter_index(1),
            bh.ParameterSource.parameter_index(2),
        ),
        mass=bh.ParameterSource.parameter_index(0),
    )


def rtn_error_and_sigma3(x_est: np.ndarray, p_est: np.ndarray, x_true: np.ndarray):
    rot = bh.rotation_eci_to_rtn(x_est)
    err = rot @ (x_est[:3] - x_true[:3])
    p_rtn = bh.covariance_eci_to_rtn(x_est, p_est, bh.OrbitRelativeFrameVariant.INERTIAL)
    return err, 3.0 * np.sqrt(np.diag(p_rtn)[:3])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()
    bh.initialize_sw()
    rng = np.random.default_rng(SEED)

    epoch0 = bh.Epoch(*EPOCH, time_system=bh.UTC)
    oe = np.array([bh.R_EARTH + ALT_KM * 1e3, ECC, INC_DEG, 0.0, 0.0, 0.0])
    x_true0 = bh.state_koe_to_eci(oe, bh.AngleFormat.DEGREES)

    truth = bh.NumericalOrbitPropagator(
        epoch0,
        x_true0,
        bh.NumericalPropagationConfig.default(),
        truth_force_model(),
        params=np.array([MASS_KG, AREA_M2, CD_TRUE, AREA_M2, CR]),
    )
    truth.set_trajectory_mode(bh.TrajectoryMode.DISABLED)

    p0 = np.diag([SIGMA0_POS_M**2] * 3 + [SIGMA0_VEL_MS**2] * 3)
    x_filter0 = x_true0 + rng.multivariate_normal(np.zeros(6), p0)
    q = np.diag([0.0] * 3 + [Q_ACCEL] * 3)
    ekf = bh.ExtendedKalmanFilter(
        epoch0,
        x_filter0,
        p0,
        propagation_config=bh.NumericalPropagationConfig.default(),
        force_config=filter_force_model(),
        measurement_models=[bh.ECEFPositionMeasurementModel(MEAS_SIGMA_M)],
        config=bh.EKFConfig(
            process_noise=bh.ProcessNoiseConfig(q, scale_with_dt=True, max_noise_dt=MAX_NOISE_DT_S),
            store_records=False,
        ),
        params=np.array([MASS_KG, AREA_M2, CD_FILTER]),
    )

    t_h, err, sig3 = [], [], []

    def record(epc: bh.Epoch) -> None:
        truth.propagate_to(epc)
        e, s = rtn_error_and_sigma3(ekf.current_state(), ekf.current_covariance(), truth.current_state())
        t_h.append((epc - epoch0) / 3600.0)
        err.append(e)
        sig3.append(s)

    record(epoch0)

    # Estimation: GPS position fixes in ECEF with white noise.
    n_meas = int(round(EST_SPAN_H * 3600.0 / MEAS_DT_S))
    meas_t_h = []
    for k in range(1, n_meas + 1):
        epc = epoch0 + k * MEAS_DT_S
        truth.propagate_to(epc)
        r_ecef = bh.position_eci_to_ecef(epc, truth.current_state()[:3])
        z = r_ecef + rng.normal(0.0, MEAS_SIGMA_M, 3)
        ekf.process_observation(bh.Observation(epc, z, model_index=0))
        meas_t_h.append((epc - epoch0) / 3600.0)
        record(epc)

    est_end = epoch0 + n_meas * MEAS_DT_S

    # Prediction: time update only (state, STM-mapped covariance, process noise).
    n_pred = int(round(PRED_SPAN_D * 86400.0 / PRED_OUTPUT_DT_S))
    for k in range(1, n_pred + 1):
        epc = est_end + k * PRED_OUTPUT_DT_S
        ekf.propagate_to(epc)
        record(epc)

    t_h = np.array(t_h)
    err = np.array(err)
    sig3 = np.array(sig3)
    est_end_h = (est_end - epoch0) / 3600.0

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "epoch_utc": epoch0.isostring(),
            "orbit": {"alt_km": ALT_KM, "ecc": ECC, "inc_deg": INC_DEG},
            "spacecraft": {"mass_kg": MASS_KG, "area_m2": AREA_M2, "cd_true": CD_TRUE, "cr": CR},
            "truth_model": "EGM2008 20x20, NRLMSISE-00 drag, SRP (conical), Sun+Moon",
            "filter_model": f"EGM2008 20x20, Harris-Priester drag, Cd={CD_FILTER}",
            "measurements": f"ECEF position every {MEAS_DT_S:.0f} s, {MEAS_SIGMA_M:.0f} m 1-sigma per axis",
            "filter": "EKF (brahe ExtendedKalmanFilter)",
            "initial_sigma": {"pos_m": SIGMA0_POS_M, "vel_ms": SIGMA0_VEL_MS},
            "process_noise_accel_psd_m2_s3": Q_ACCEL,
            "prediction_days": PRED_SPAN_D,
            "seed": SEED,
        },
        "est_end_h": round(est_end_h, 4),
        "t_h": np.round(t_h, 4).tolist(),
        "err_rtn_m": {k: np.round(err[:, i], 2).tolist() for i, k in enumerate("RTN")},
        "sigma3_rtn_m": {k: np.round(sig3[:, i], 2).tolist() for i, k in enumerate("RTN")},
        "meas_t_h": np.round(meas_t_h, 4).tolist(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    est = (t_h > 1.0) & (t_h <= est_end_h)
    rms = np.sqrt(np.mean(err[est] ** 2, axis=0))
    print(f"estimation (1 h .. {est_end_h:.0f} h): RMS error R/T/N = {rms.round(2)} m")
    print(f"  3-sigma at end of estimation R/T/N = {sig3[t_h <= est_end_h][-1].round(2)} m")
    print("prediction     |err| R / T / N [m]          3-sigma R / T / N [m]")
    for d in (1, 2, 3, 4):
        k = int(np.argmin(np.abs(t_h - (est_end_h + 24.0 * d))))
        print(f"  +{d} d   {np.abs(err[k]).round(1)}   {sig3[k].round(1)}")
    inside = np.abs(err) <= sig3
    for label, mask in (("estimation", est), ("prediction", t_h > est_end_h)):
        frac = inside[mask].mean(axis=0)
        print(f"{label}: fraction of epochs with |err| <= 3-sigma R/T/N = {frac.round(3)}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
