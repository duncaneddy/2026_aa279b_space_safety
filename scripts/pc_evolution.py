# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy", "scipy"]
# ///
"""Pc dilution and simulated Pc evolution across a sequence of CDM updates.

1. Dilution. For the real conjunction used in scripts/pc.py (CARA test CDM,
   CALIPSO x COSMOS 2251 DEB) the encounter-plane covariance is scaled by
   k^2 (every 1-sigma scaled by k) at fixed miss distance and HBR. Pc rises
   as the ellipse grows toward the miss vector, peaks, then falls as the same
   probability mass is spread over an ever larger area: a small Pc can mean
   "safe" or "we don't know".

2. Covariance growth with time to TCA, from public data:
   - Primary: SpaceX's public Starlink operator ephemerides (Modified ITC,
     https://api.starlink.com/public-files/ephemerides/) via brahe's
     StarlinkClient. Each file starts at the operator's OD epoch and carries
     a 6x6 RTN covariance every 60 s. Per satellite, records are kept up to
     the first point where the along-track sigma stops growing (later
     records are held or reset across planned maneuvers). The median 1-sigma
     R, T, N over satellites is fit with a power law sigma = a t^p in hours.
   - Secondary: the 53 real CARA CDMs used for validation in scripts/pc.py.
     Their secondary-object RTN sigmas versus lead time (TCA minus CDM
     creation time) are fit with a power law per axis. These are SP catalog
     covariances of debris and rocket bodies at 330-1250 km, as received by
     the operator.

3. Simulated CDM sequence (a simulation, not data). Using the geometry of the
   example conjunction (TCA states, relative velocity, encounter frame), a
   true miss vector of fixed length is placed along the CDM miss direction.
   At each update, t hours before TCA, the primary and secondary covariances
   are the growth models evaluated at t (diagonal in each object's RTN frame,
   rotated to inertial with brahe and combined), the estimated miss vector is
   the true miss plus one independent draw from that update's combined
   encounter-plane covariance, and the 2D Foster Pc is computed from the
   estimate.

4. False-alarm statistics. The sequence is repeated for 2,000 seeds at each
   of several true miss distances, counting how often Pc crosses the 1e-4
   alarm level at an update 24 h or more before TCA, and how often it is
   still above it at the last update. The "false alarm" example sequence is
   chosen by a fixed rule stated in config.false_alarm_selection; the
   "threat" sequence uses the script seed.

References:
  - J. L. Foster and H. S. Estes, NASA JSC-25898, 1992 (2D Pc).
  - F. K. Chan, Spacecraft Collision Probability, The Aerospace Press, 2008.
  - S. Alfano, "Relating Position Uncertainty to Maximum Conjunction
    Probability," J. Astronaut. Sci. 53(2), 2005 (dilution).
  - NASA CARA, "NASA Spacecraft Conjunction Assessment and Collision
    Avoidance Best Practices Handbook," NASA/SP-20230002470, 2023.

Run:
  uv run scripts/pc_evolution.py [--out path.json]

Output (deck/data/pc_evolution.json):
  {generated_utc, dilution:{sigma_scale, pc, miss_m, hbr_m, max_pc,
   sigma_scale_at_max}, sigma_growth_source, sigma_growth:{...},
   config:{...}, false_alarm_stats:{...}, scenarios:[{name, true_miss_m, seed,
   updates:[{t_before_tca_h, est_miss_m, sigma_T_m, sigma1_T_m, sigma2_T_m, pc,
   primary_extrapolated, secondary_extrapolated}]}]}
  sigma_T_m is the root-sum-square of the two objects' along-track sigmas.
  *_extrapolated marks updates outside the time span of that object's fit.
  Scenario pc values are clipped below at config.pc_floor.
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.ccsds import CDM
from scipy import integrate, optimize, special

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deck/data/pc_evolution.json"
RAW_CARA = ROOT / "deck/data/raw/cara"
RAW_STARLINK = ROOT / "deck/data/raw/starlink_ephemerides"

CARA_COMMIT = "86ba28ad2ae6acacff29df5933809e731f500935"
CARA_URL = f"https://raw.githubusercontent.com/nasa/CARA_Analysis_Tools/{CARA_COMMIT}/DataFiles/PcTestCaseCDMs"
EXAMPLE_ID = "000029108_conj_000034995_20220706_165058_20220705_143113"
HBR_M = 14.8

SEED = 279
STARLINK_SATS = 12
STARLINK_FIT_HOURS = np.array([1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 21.0, 24.0])
DILUTION_SCALES = np.logspace(-2, 2, 161)
UPDATES_H = [168, 144, 120, 96, 72, 60, 48, 36, 30, 24, 18, 12, 9, 6]
THREAT_MISS_M = 50.0
ALARM_PC = 1e-4
EARLY_H = 24
STAT_RUNS = 2000
STAT_MISSES_M = [50.0, 200.0, 500.0, 1000.0, 2000.0]
FALSE_ALARM_MIN_FRACTION = 0.1
PC_FLOOR = 1e-12

CARA_CDM_IDS = [
    "000020580_conj_000022015_20210315_212955_20210313_065123",
    "000025994_conj_000037558_20210324_151047_20210323_154356",
    "000028485_conj_000044777_20220407_231108_20220406_140506",
    "000029108_conj_000034995_20220706_165058_20220705_143113",
    "000032060_conj_000044396_20221004_061656_20221003_054027",
    "000033591_conj_000042216_20211203_183431_20211202_153618",
    "000037849_conj_000013512_20210612_084905_20210611_062043",
    "000038771_conj_000030802_20201216_182131_20201215_171306",
    "000040059_conj_000035921_20220326_194122_20220325_215435",
    "000041848_conj_000044431_20210708_055146_20210707_060703",
    "000043477_conj_000046952_20220130_183651_20220129_070200",
    "000044628_conj_000027127_20220313_181420_20220311_225243",
    "000027424_conj_000048164_20210803_232939_20210801_222613",
    "000028654_conj_000041835_20220106_193032_20220105_161142",
    "000028654_conj_000042397_20230830_144301_20230828_004035",
    "000032060_conj_000053480_20220918_094157_20220916_064125",
    "000040115_conj_000030660_20230721_100115_20230720_061903",
    "000048901_conj_000048954_20220529_223144_20220528_141942",
    "000025994_conj_000026980_20220928_223445_20220924_220647",
    "000027424_conj_000041740_20220530_042037_20220525_221911",
    "000032060_conj_000035644_20220303_131758_20220227_152710",
    "000025994_conj_000026132_20220224_100307_20220221_225515",
    "000027424_conj_000031201_20230823_165542_20230819_215513",
    "000054234_conj_000028343_20221130_142342_20221127_152412",
    "000035946_conj_000030648_20221210_140311_20221206_003234",
    "000032060_conj_000049574_20220227_152525_20220222_065043",
    "000020580_conj_000002017_20230613_001923_20230608_063715",
    "000029108_conj_000040337_20230403_231644_20230328_215738",
    "000039574_conj_000045957_20210115_194737_20210112_152605",
    "000030580_conj_000019175_20230302_224136_20230224_154111",
    "000043613_conj_000048526_20220521_201359_20220517_152316",
    "000043613_conj_000050564_20220203_012436_20220127_232009",
    "000043613_conj_000050666_20220205_042713_20220131_225404",
    "000043613_conj_000050710_20220204_133038_20220130_150419",
    "000045121_conj_000014729_20210123_024852_20210116_154409",
    "000029479_conj_000042794_20220623_035251_20220619_055818",
    "000029479_conj_000054630_20230725_134006_20230718_222924",
    "000033331_conj_000049571_20221005_095022_20221002_220322",
    "000043613_conj_000043712_20221015_083008_20221009_220335",
    "000043613_conj_000049557_20221119_064308_20221115_150510",
    "000043613_conj_000050929_20220128_234921_20220123_065918",
    "000043613_conj_000051228_20220215_122556_20220209_225622",
    "000043613_conj_000051418_20220204_181230_20220129_152147",
    "000043613_conj_000052010_20230626_045217_20230620_061741",
    "000043613_conj_000052010_20230626_062628_20230619_143324",
    "000043613_conj_000053131_20221020_115338_20221014_064753",
    "000045121_conj_000045957_20220912_081610_20220908_142756",
    "000032060_conj_000050346_20220311_070404_20220305_230151",
    "000039574_conj_000039477_20220711_110033_20220705_220442",
    "000040376_conj_000054517_20230606_101715_20230531_221558",
    "000048901_conj_000048903_20211219_182317_20211217_232706",
    "000048901_conj_000048903_20211219_235030_20211215_225057",
    "000048901_conj_000048903_20211220_012535_20211215_145954",
]


def sig(x: float, digits: int = 6) -> float:
    return float(f"{x:.{digits}g}")


def load_cdm(name: str) -> CDM:
    """Fetch a CARA CDM once into deck/data/raw/cara/ and parse it with brahe.

    CARA's files write unavailable OD statistics as NaN, which the CCSDS
    standard does not allow for integer fields, so those lines are dropped.
    """
    path = RAW_CARA / f"{name}.cdm"
    if not path.exists():
        RAW_CARA.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{CARA_URL}/{name}.cdm", timeout=60) as resp:
            path.write_bytes(resp.read())
    lines = path.read_text().splitlines()
    kept = [ln for ln in lines if "=" not in ln or ln.split("=", 1)[1].split()[:1] != ["NaN"]]
    return CDM.from_str("\n".join(kept))


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


def pc_2d(mu: np.ndarray, cp: np.ndarray, hbr: float) -> float:
    """2D Pc for an arbitrary encounter-plane miss vector: rotate it onto +x first."""
    c, s = mu / np.linalg.norm(mu)
    rot = np.array([[c, s], [-s, c]])
    return pc_circle(float(np.linalg.norm(mu)), rot @ cp @ rot.T, hbr)


def power_law(t_h: np.ndarray, sigma: np.ndarray) -> tuple[float, float]:
    """Least-squares fit of log(sigma) = log(a) + p log(t); returns (a, p)."""
    p, log_a = np.polyfit(np.log(t_h), np.log(sigma), 1)
    return float(np.exp(log_a)), float(p)


def starlink_files() -> list[Path]:
    """Operator ephemerides for STARLINK_SATS satellites spread across the manifest, cached in deck/data/raw."""
    cached = sorted(RAW_STARLINK.glob("MEME_*.txt"))
    if len(cached) >= STARLINK_SATS:
        return cached[:STARLINK_SATS]
    client = bh.StarlinkClient()
    entries = [e for e in client.get_manifest().entries() if "Operational" in e.file_name_string()]
    picks = entries[:: max(1, len(entries) // STARLINK_SATS)][:STARLINK_SATS]
    RAW_STARLINK.mkdir(parents=True, exist_ok=True)
    return [Path(client.save_ephemeris(e.norad_cat_id, str(RAW_STARLINK), keep_cached=True)) for e in picks]


def primary_growth() -> dict:
    """Median Starlink operator RTN sigma vs propagation time, fit per axis."""
    files = starlink_files()
    curves = []
    for path in files:
        itc = bh.ITC.from_file(str(path))
        t0 = itc.states[0].epoch
        t_h = np.array([(s.epoch - t0) / 3600.0 for s in itc.states])
        cov = np.array(itc.covariances)
        sigma = np.sqrt(np.stack([cov[:, 0, 0], cov[:, 1, 1], cov[:, 2, 2]], axis=1))
        stall = np.nonzero((t_h[1:] > 1.0) & (sigma[1:, 1] <= sigma[:-1, 1]))[0]
        end = stall[0] if len(stall) else len(t_h) - 1
        curve = np.full((len(STARLINK_FIT_HOURS), 3), np.nan)
        ok = STARLINK_FIT_HOURS <= t_h[end]
        for k in range(3):
            curve[ok, k] = np.interp(STARLINK_FIT_HOURS[ok], t_h[: end + 1], sigma[: end + 1, k])
        curves.append(curve)
    curves = np.array(curves)
    enough = np.sum(~np.isnan(curves[:, :, 1]), axis=0) >= len(curves) / 2
    t_fit = STARLINK_FIT_HOURS[enough]
    median = np.nanmedian(curves[:, enough, :], axis=0)
    fits = {ax: power_law(t_fit, median[:, k]) for k, ax in enumerate("RTN")}
    return {
        "source": f"SpaceX public Starlink operator ephemerides (Modified ITC), {len(curves)} satellites, "
        "median 1-sigma RTN vs hours since ephemeris start",
        "files": [p.name for p in files],
        "t_h": t_fit.tolist(),
        "median_sigma_rtn_m": {ax: [sig(v, 4) for v in median[:, k]] for k, ax in enumerate("RTN")},
        "fit": {ax: {"a": sig(a, 4), "p": sig(p, 4)} for ax, (a, p) in fits.items()},
        "fit_range_h": [float(t_fit[0]), float(t_fit[-1])],
    }


def secondary_growth() -> dict:
    """CARA CDM secondary-object RTN sigma vs lead time (TCA - creation), fit per axis."""
    lead, sigma = [], []
    for cid in CARA_CDM_IDS:
        cdm = load_cdm(cid)
        lead.append((cdm.tca - cdm.creation_date) / 3600.0)
        sigma.append(np.sqrt(np.diag(np.asarray(cdm.object2_covariance, dtype=float)[:3, :3])))
    lead, sigma = np.array(lead), np.array(sigma)
    fits = {ax: power_law(lead, sigma[:, k]) for k, ax in enumerate("RTN")}
    return {
        "source": f"NASA CARA test CDMs (CARA_Analysis_Tools DataFiles/PcTestCaseCDMs), {len(lead)} secondary objects, "
        "1-sigma RTN vs CDM lead time",
        "lead_h": [sig(v, 4) for v in lead],
        "sigma_rtn_m": {ax: [sig(v, 4) for v in sigma[:, k]] for k, ax in enumerate("RTN")},
        "fit": {ax: {"a": sig(a, 4), "p": sig(p, 4)} for ax, (a, p) in fits.items()},
        "fit_range_h": [sig(float(lead.min()), 4), sig(float(lead.max()), 4)],
    }


def sigma_model(growth: dict, t_h: float) -> np.ndarray:
    return np.array([growth["fit"][ax]["a"] * t_h ** growth["fit"][ax]["p"] for ax in "RTN"])


def rtn_cov_to_eci(x: np.ndarray, sigma_rtn: np.ndarray) -> np.ndarray:
    rot = bh.rotation_rtn_to_eci(x)
    return rot @ np.diag(sigma_rtn**2) @ rot.T


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()

    cdm = load_cdm(EXAMPLE_ID)
    x1 = np.asarray(cdm.object1_state, dtype=float)
    x2 = np.asarray(cdm.object2_state, dtype=float)
    variant = bh.OrbitRelativeFrameVariant.INERTIAL
    p1 = bh.covariance_rtn_to_eci(x1, np.asarray(cdm.object1_covariance, dtype=float), variant)
    p2 = bh.covariance_rtn_to_eci(x2, np.asarray(cdm.object2_covariance, dtype=float), variant)

    # Encounter frame of the example (CARA convention): x along the miss, y along v_rel, z along r x v.
    r, v = x2[:3] - x1[:3], x2[3:] - x1[3:]
    y_hat = v / np.linalg.norm(v)
    z_hat = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
    x_hat = np.cross(y_hat, z_hat)
    proj = np.vstack([x_hat, z_hat])
    miss0 = float(np.linalg.norm(r))

    cp0 = proj @ (p1[:3, :3] + p2[:3, :3]) @ proj.T
    dil = [pc_circle(miss0, k**2 * cp0, HBR_M) for k in DILUTION_SCALES]
    best = optimize.minimize_scalar(
        lambda u: -pc_circle(miss0, np.exp(2 * u) * cp0, HBR_M),
        bounds=(np.log(DILUTION_SCALES[0]), np.log(DILUTION_SCALES[-1])),
        method="bounded",
        options={"xatol": 1e-6},
    )
    k_max, pc_max = float(np.exp(best.x)), float(-best.fun)

    prim, sec = primary_growth(), secondary_growth()
    covs = []
    for t_h in UPDATES_H:
        s1, s2 = sigma_model(prim, t_h), sigma_model(sec, t_h)
        cp = proj @ (rtn_cov_to_eci(x1, s1) + rtn_cov_to_eci(x2, s2)) @ proj.T
        lam, vec = np.linalg.eigh(cp)
        covs.append((t_h, s1, s2, cp, lam, vec))

    def simulate(true_miss: float, z: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
        """Estimated miss vectors and Pc for one CDM sequence with standard-normal draws z."""
        mus = [np.array([true_miss, 0.0]) + vec @ (np.sqrt(lam) * zk) for (_, _, _, _, lam, vec), zk in zip(covs, z)]
        return mus, np.array([pc_2d(mu, c[3], HBR_M) for mu, c in zip(mus, covs)])

    def draws(seed: int) -> np.ndarray:
        return np.random.default_rng(seed).standard_normal((len(UPDATES_H), 2))

    early = np.array(UPDATES_H) >= EARLY_H
    stats, alarm_runs = [], {}
    for true_miss in STAT_MISSES_M:
        n_early = n_last = 0
        first = None
        for seed in range(STAT_RUNS):
            pcs = simulate(true_miss, draws(seed))[1]
            alarm, still = bool(np.any(pcs[early] >= ALARM_PC)), bool(pcs[-1] >= ALARM_PC)
            n_early += alarm
            n_last += still
            if first is None and alarm and not still:
                first = seed
        alarm_runs[true_miss] = first
        stats.append(
            {
                "true_miss_m": true_miss,
                "runs": STAT_RUNS,
                "frac_alarm_early": round(n_early / STAT_RUNS, 4),
                "frac_alarm_last": round(n_last / STAT_RUNS, 4),
            }
        )

    eligible = [st for st in stats if st["frac_alarm_early"] >= FALSE_ALARM_MIN_FRACTION and alarm_runs[st["true_miss_m"]] is not None]
    false_alarm = max(eligible, key=lambda st: st["true_miss_m"]) if eligible else None

    def scenario(name: str, true_miss: float, seed: int) -> dict:
        mus, pcs = simulate(true_miss, draws(seed))
        updates = []
        for (t_h, s1, s2, _, lam, _), mu, pc in zip(covs, mus, pcs):
            updates.append(
                {
                    "t_before_tca_h": t_h,
                    "est_miss_m": sig(float(np.linalg.norm(mu)), 5),
                    "est_miss_xy_m": [sig(float(mu[0]), 5), sig(float(mu[1]), 5)],
                    "sigma_T_m": sig(float(np.hypot(s1[1], s2[1])), 5),
                    "sigma1_T_m": sig(float(s1[1]), 5),
                    "sigma2_T_m": sig(float(s2[1]), 5),
                    "sigma_major_minor_m": [sig(float(np.sqrt(lam[1])), 5), sig(float(np.sqrt(lam[0])), 5)],
                    "pc": sig(max(float(pc), PC_FLOOR), 5),
                    "primary_extrapolated": not prim["fit_range_h"][0] <= t_h <= prim["fit_range_h"][1],
                    "secondary_extrapolated": not sec["fit_range_h"][0] <= t_h <= sec["fit_range_h"][1],
                }
            )
        return {"name": name, "true_miss_m": true_miss, "seed": seed, "updates": updates}

    scenarios = []
    if false_alarm is not None:
        miss_fa = false_alarm["true_miss_m"]
        scenarios.append(scenario(f"False alarm: true miss {miss_fa:g} m", miss_fa, alarm_runs[miss_fa]))
    scenarios.append(scenario(f"Threat: true miss {THREAT_MISS_M:g} m", THREAT_MISS_M, SEED))

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dilution": {
            "sigma_scale": [sig(k, 5) for k in DILUTION_SCALES],
            "pc": [sig(p, 5) for p in dil],
            "miss_m": sig(miss0),
            "hbr_m": HBR_M,
            "cov_xy_m2": [[sig(v) for v in row] for row in cp0],
            "max_pc": sig(pc_max),
            "sigma_scale_at_max": sig(k_max, 5),
            "source": f"CARA test CDM {EXAMPLE_ID} ({cdm.object1_name.strip()} x {cdm.object2_name.strip()}), "
            "encounter-plane covariance scaled by sigma_scale^2",
        },
        "sigma_growth_source": f"primary: {prim['source']}; secondary: {sec['source']}",
        "sigma_growth": {"primary": prim, "secondary": sec},
        "config": {
            "simulation": True,
            "geometry": f"TCA states and encounter frame of CARA test CDM {EXAMPLE_ID}",
            "hbr_m": HBR_M,
            "true_miss_direction": "along the CDM miss vector (encounter-plane +x)",
            "covariance_model": "diagonal RTN per object, sigma_axis = a * t^p (t = hours before TCA), "
            "rotated to inertial with each object's RTN frame at TCA and summed",
            "estimate_model": "est_miss = true_miss + L z, L L^T = combined encounter-plane covariance at that update, "
            "z ~ N(0, I) independent per update, drawn from numpy default_rng(seed)",
            "pc_method": "Foster 2D Pc",
            "pc_floor": PC_FLOOR,
            "threat_seed": SEED,
            "false_alarm_selection": f"true miss: the largest of {STAT_MISSES_M} m whose runs exceed Pc {ALARM_PC:g} at an update "
            f">= {EARLY_H} h before TCA in at least {FALSE_ALARM_MIN_FRACTION:.0%} of {STAT_RUNS} seeds; seed: the first seed "
            f"(0, 1, 2, ...) that exceeds Pc {ALARM_PC:g} at an update >= {EARLY_H} h before TCA and is below it at the last update",
        },
        "false_alarm_stats": {
            "alarm_pc": ALARM_PC,
            "early_h": EARLY_H,
            "definition": f"frac_alarm_early: fraction of seeds with Pc >= {ALARM_PC:g} at any update >= {EARLY_H} h before TCA; "
            f"frac_alarm_last: fraction with Pc >= {ALARM_PC:g} at the last update ({UPDATES_H[-1]} h)",
            "by_true_miss": stats,
        },
        "scenarios": scenarios,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"dilution: miss {miss0:.1f} m, HBR {HBR_M} m, Pc(k=1) {pc_circle(miss0, cp0, HBR_M):.3e}, max Pc {pc_max:.3e} at k = {k_max:.3f}")
    for label, g in (("primary", prim), ("secondary", sec)):
        fit = ", ".join(f"{ax}: {g['fit'][ax]['a']:.3g} t^{g['fit'][ax]['p']:.2f}" for ax in "RTN")
        print(f"{label} sigma [m] = {fit}  (fit range {g['fit_range_h'][0]:g}-{g['fit_range_h'][1]:g} h)")
    for st in stats:
        print(
            f"true miss {st['true_miss_m']:6.0f} m: Pc >= {ALARM_PC:g} at >= {EARLY_H} h in {st['frac_alarm_early']:.1%} "
            f"of runs, still >= {ALARM_PC:g} at {UPDATES_H[-1]} h in {st['frac_alarm_last']:.1%}"
        )
    for scen in scenarios:
        print(f"{scen['name']} (seed {scen['seed']})")
        for u in scen["updates"]:
            flag = " (extrapolated)" if u["primary_extrapolated"] or u["secondary_extrapolated"] else ""
            print(
                f"  T-{u['t_before_tca_h']:4d} h: sigma_T1 {u['sigma1_T_m']:10.1f} m, sigma_T2 {u['sigma2_T_m']:9.1f} m, "
                f"est miss {u['est_miss_m']:10.1f} m, Pc {u['pc']:.3e}{flag}"
            )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
