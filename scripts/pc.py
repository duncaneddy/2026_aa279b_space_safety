# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy", "scipy"]
# ///
"""Two-dimensional probability of collision (Pc): Foster method, Monte Carlo, cost.

1. Foster 2D Pc. Under the short-encounter assumption (rectilinear relative
   motion, no velocity uncertainty, position uncertainty constant through the
   encounter) the collision probability is the integral of the combined
   relative-position Gaussian over the hard-body circle, both projected onto
   the encounter (conjunction) plane perpendicular to the relative velocity at
   the time of closest approach (TCA):

       Pc = 1 / (2 pi sqrt(det C)) * integral over |rho - mu| <= HBR of
            exp(-1/2 rho^T C^-1 rho) d rho,     C = P_xz (C1 + C2) P_xz^T

   with mu the miss vector and HBR the combined hard-body radius. The
   encounter frame follows NASA CARA's Pc2D_Foster.m: y along the relative
   velocity, z along r x v, x = y x z, so the miss vector lies on +x.
   The integral is evaluated as a 1D quadrature over x of the Gaussian
   marginal in x times the conditional Gaussian probability mass in z across
   the circle chord.

2. Validation against NASA CARA's reference implementation and test data
   (https://github.com/nasa/CARA_Analysis_Tools, pinned commit below):
     - Pc2D_Foster_UnitTest.m: Omitron circle case and the eleven Alfano (2009)
       test cases (inputs read from the CARA sample CDMs).
     - PcCircle_UnitTest.m: Omitron case 2.
     - DataFiles/PcTestCaseCDMs: 53 real CARA conjunctions with CARA's 2D Pc
       (Pc2D_NoAdj, PcCircle on the CDM states) and CARA's Monte Carlo
       (SDMC) Pc, ported from CARA_PcMethod_Test_Conjunctions.xlsx.
   CDMs are downloaded once to deck/data/raw/cara/ and parsed with
   brahe.ccsds.CDM. RTN covariances are rotated to the inertial frame with
   brahe.covariance_rtn_to_eci (block-diagonal convention, as CARA's RIC2ECI).

3. Monte Carlo baseline for one real conjunction (CALIPSO x COSMOS 2251 DEB,
   CARA test case): sample both objects' 6D states from their covariances at
   TCA, move each sample pair along straight lines through the encounter to
   its own closest approach, count misses below HBR.

4. Monte Carlo cost model. For a binomial estimate with relative standard
   error eps at two-sided confidence (1 - alpha):

       N = z^2 (1 - Pc) / (eps^2 Pc),   z = Phi^-1(1 - alpha / 2)

   A full Monte Carlo propagates every sample of both objects from the OD
   epoch to TCA. The per-sample cost is measured by timing a brahe numerical
   propagation (20x20 EGM2008 gravity + Harris-Priester drag) of the example
   LEO primary over 3 days; each sample needs two such propagations.

References:
  - J. L. Foster and H. S. Estes, "A Parametric Analysis of Orbital Debris
    Collision Probability and Maneuver Rate for Space Vehicles,"
    NASA JSC-25898, 1992.
  - F. K. Chan, Spacecraft Collision Probability, The Aerospace Press, 2008.
  - S. Alfano, "Satellite Conjunction Monte Carlo Analysis," AAS 09-233, 2009.
  - NASA CARA, "NASA Spacecraft Conjunction Assessment and Collision
    Avoidance Best Practices Handbook," NASA/SP-20230002470, 2023.
  - D. Hall et al., "High Fidelity Collision Probabilities Estimated using
    Brute Force Monte Carlo Simulations," AAS 18-244, 2018.

Run:
  uv run scripts/pc.py [--out path.json]

Output (deck/data/pc.json):
  {generated_utc, validation:[{case, source, pc_ours, pc_cara, rel_err,
   pc_cara_sdmc?}], example:{..., encounter_plane:{...}, ellipsoids:{...}},
   mc_cost:{...}}
  Encounter-plane coordinates: origin at the primary, x along the miss vector
  (secondary minus primary), z along (r x v) of the relative state, in meters.
  Ellipsoid block: primary RTN axes at TCA, meters and m/s; rel_* is secondary
  minus primary (inertial difference expressed in RTN axes).
"""

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.ccsds import CDM
from scipy import integrate, special

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deck/data/pc.json"
RAW_DIR = ROOT / "deck/data/raw/cara"

CARA_COMMIT = "86ba28ad2ae6acacff29df5933809e731f500935"
CARA_URL = f"https://raw.githubusercontent.com/nasa/CARA_Analysis_Tools/{CARA_COMMIT}/DataFiles"

SEED = 279
MC_SAMPLES = 10_000_000
MC_CHUNK = 1_000_000
MC_PLOT_POINTS = 3000
COST_PCS = [1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7]
COST_REL_ERR = 0.1
COST_CONF = 0.95
COST_SPAN_DAYS = 3.0
COST_TIMING_RUNS = 3

# Example conjunction: CARA test case CALIPSO (29108) x COSMOS 2251 DEB (34995).
EXAMPLE_ID = "000029108_conj_000034995_20220706_165058_20220705_143113"

# Generic LEO spacecraft for the propagation timing: [mass kg, drag area m^2, Cd].
PROP_PARAMS = np.array([600.0, 5.0, 2.2])

# Pc2D_Foster_UnitTest.m: Alfano (2009) case number, HBR (m), expected Pc.
ALFANO_CASES = [
    (1, 15, 1.46749549e-01),
    (2, 4, 6.22226700e-03),
    (3, 15, 1.00351176e-01),
    (4, 15, 4.93234060e-02),
    (5, 10, 4.44873860e-02),
    (6, 10, 4.33545500e-03),
    (7, 10, 1.58147000e-04),
    (8, 4, 3.69480080e-02),
    (9, 6, 2.90146291e-01),
    (10, 6, 2.90146291e-01),
    (11, 4, 2.67202600e-03),
]

# Explicit-state unit tests (km, km/s, km^2; HBR in km).
OMITRON_CASES = [
    (
        "Omitron case 1 (Pc2D_Foster_UnitTest)",
        [378.39559, 4305.721887, 5752.767554],
        [2.360800244, 5.580331936, -4.322349039],
        [
            [44.5757544811362, 81.6751751052616, -67.8687662707124],
            [81.6751751052616, 158.453402956163, -128.616921644857],
            [-67.8687662707124, -128.616921644858, 105.490542562701],
        ],
        [374.5180598, 4307.560983, 5751.130418],
        [-5.388125081, -3.946827739, 3.322820358],
        [
            [2.31067077720423, 1.69905293875632, -1.4170164577661],
            [1.69905293875632, 1.24957388457206, -1.04174164279599],
            [-1.4170164577661, -1.04174164279599, 0.869260558223714],
        ],
        0.020,
        2.70601573490125e-05,
    ),
    (
        "Omitron case 2 (PcCircle_UnitTest)",
        [-3239.128337196251, 2404.575152356222, 5703.228541709001],
        [-3.745768373154199, 5.012339015927846, -4.231864565717194],
        [
            [0.342072996423899e-3, -0.412677096778269e-3, 0.371500417511149e-3],
            [-0.412677096778269e-3, 0.609905946319294e-3, -0.540401385544286e-3],
            [0.371500417511149e-3, -0.540401385544286e-3, 0.521238634755377e-3],
        ],
        [-3239.138264917246, 2404.568320465936, 5703.235605231182],
        [6.110192790100711, -1.767321407894830, 4.140369261741708],
        [
            [0.028351300975134, -0.008204103437377, 0.019253747960155],
            [-0.008204103437377, 0.002404377774847, -0.005586512197914],
            [0.019253747960155, -0.005586512197914, 0.013289250260317],
        ],
        0.020,
        1.807363058494765e-01,
    ),
]

# CARA_PcMethod_Test_Conjunctions.xlsx: conjunction ID, HBR (m), CARA 2D Pc on
# the CDM states (Pc2D_NoAdj), CARA Monte Carlo Pc (PcSDMC), SDMC sample count.
CARA_CDM_CASES = [
    ("000020580_conj_000022015_20210315_212955_20210313_065123", 10, 0.0006114791374065471, 0.000611125, 16000000),  # HST x DELTA 2 R/B(1)
    ("000025994_conj_000037558_20210324_151047_20210323_154356", 15, 0.021172782261112858, 0.021608695652173913, 460000),  # TERRA x IRIDIUM 33 DEB
    ("000028485_conj_000044777_20220407_231108_20220406_140506", 8.7, 0.0023236846704222935, 0.0023277272727272725, 4400000),  # SWIFT x JILIN-01 GAOFEN 2A
    ("000029108_conj_000034995_20220706_165058_20220705_143113", 14.8, 0.001760626338802878, 0.0017750877192982456, 5700000),  # CALIPSO x COSMOS 2251 DEB
    ("000032060_conj_000044396_20221004_061656_20221003_054027", 20, 0.006581747654913482, 0.006642, 1500000),  # WORLDVIEW 1 x LEMUR 2 LILLYJO
    ("000033591_conj_000042216_20211203_183431_20211202_153618", 6, 0.004538844930549139, 0.004585454545454545, 2200000),  # NOAA 19 x COSMOS 1275 DEB
    ("000037849_conj_000013512_20210612_084905_20210611_062043", 6, 0.010489561620298779, 0.01060842105263158, 950000),  # NPP x THOR ABLESTAR DEB
    ("000038771_conj_000030802_20201216_182131_20201215_171306", 10, 0.0015591403487380158, 0.00156734375, 6400000),  # METOP-B x FENGYUN 1C DEB
    ("000040059_conj_000035921_20220326_194122_20220325_215435", 6, 0.0007861432895086908, 0.0007953076923076923, 13000000),  # OCO 2 x IRIDIUM 33 DEB
    ("000041848_conj_000044431_20210708_055146_20210707_060703", 20, 0.002451845276429451, 0.0024835, 4000000),  # WORLDVIEW 4 x VCC B
    ("000043477_conj_000046952_20220130_183651_20220129_070200", 3.1, 0.00012941841104338147, 0.00012993589743589743, 78000000),  # GRACE-FO 2 x SPACEBEE-24
    ("000044628_conj_000027127_20220313_181420_20220311_225243", 4.5, 0.00016012269077373922, 0.00015716129032258065, 62000000),  # ICON x PSLV DEB
    ("000027424_conj_000048164_20210803_232939_20210801_222613", 17.3, 1.0341739680078816e-05, 1.015625e-05, 960000000),  # AQUA x NOAA 17 DEB
    ("000028654_conj_000041835_20220106_193032_20220105_161142", 6, 0.0049977577395711285, 0.005024, 2000000),  # NOAA 18 x DMSP 5D-2 F12 DEB
    ("000028654_conj_000042397_20230830_144301_20230828_004035", 6, 2.844001174049767e-05, 2.8888235294117647e-05, 340000000),  # NOAA 18 x NOAA 16 DEB
    ("000032060_conj_000053480_20220918_094157_20220916_064125", 20, 2.345015207026501e-05, 2.3595348837209302e-05, 430000000),  # WORLDVIEW 1 x STARLINK-4442
    ("000040115_conj_000030660_20230721_100115_20230720_061903", 20, 0.00010724125975531239, 0.00010509677419354839, 93000000),  # WORLDVIEW 3 x FENGYUN 1C DEB
    ("000048901_conj_000048954_20220529_223144_20220528_141942", 2, 1.3522696018782125e-05, 1.3594594594594595e-05, 740000000),  # TROPICS PATHFINDER x ASTROCAST-0201
    ("000025994_conj_000026980_20220928_223445_20220924_220647", 15, 0.00010824930523106743, 0.00010694565217391305, 92000000),  # TERRA x SL-16 DEB
    ("000027424_conj_000041740_20220530_042037_20220525_221911", 17.3, 0.00025562906509581893, 0.000255325, 40000000),  # AQUA x WORLDVIEW 2 DEB
    ("000032060_conj_000035644_20220303_131758_20220227_152710", 20, 0.0001762747699701498, 0.00017701754385964912, 57000000),  # WORLDVIEW 1 x COSMOS 2251 DEB
    ("000025994_conj_000026132_20220224_100307_20220221_225515", 15, 0.0012125491429454116, 0.0012158536585365853, 8200000),  # TERRA x CZ-4 DEB
    ("000027424_conj_000031201_20230823_165542_20230819_215513", 17.3, 3.702308967852567e-05, 3.654814814814815e-05, 270000000),  # AQUA x FENGYUN 1C DEB
    ("000054234_conj_000028343_20221130_142342_20221127_152412", 12, 0.00015375047638146902, 0.00015155384615384615, 65000000),  # NOAA 21 x DMSP 5D-2 F11 DEB
    ("000035946_conj_000030648_20221210_140311_20221206_003234", 20, 4.45453727663907e-23, 0.00015056060606060605, 66000000),  # WORLDVIEW 2 x FENGYUN 1C DEB
    ("000032060_conj_000049574_20220227_152525_20220222_065043", 20, 9.408252835447338e-05, 0.00014418571428571428, 70000000),  # WORLDVIEW 1 x COSMOS 1408 DEB
    ("000020580_conj_000002017_20230613_001923_20230608_063715", 10, 1.8622335315326665e-05, 4.6457142857142856e-05, 210000000),  # HST x DIAMANT R/B
    ("000029108_conj_000040337_20230403_231644_20230328_215738", 14.8, 4.540311697138281e-06, 1.6728333333333334e-05, 600000000),  # CALIPSO x CZ-4B R/B
    ("000039574_conj_000045957_20210115_194737_20210112_152605", 8, 2.9182522345639286e-07, 3.4186206896551724e-05, 290000000),  # GPM x FREGAT DEB
    ("000030580_conj_000019175_20230302_224136_20230224_154111", 26, 5.668783807083913e-07, 1.70225e-06, 4000000000),  # THEMIS A x SL-14 DEB
    ("000043613_conj_000048526_20220521_201359_20220517_152316", 7, 1.1088425527984942e-06, 3.2470967741935485e-06, 3100000000),  # ICESAT-2 x CZ-4B DEB
    ("000043613_conj_000050564_20220203_012436_20220127_232009", 7, 9.726641321062183e-07, 3.3043333333333333e-06, 3000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000050666_20220205_042713_20220131_225404", 7, 2.892467298543496e-07, 1.42475e-06, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000050710_20220204_133038_20220130_150419", 7, 5.36970468361891e-07, 2.306e-06, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000045121_conj_000014729_20210123_024852_20210116_154409", 4, 2.7441028646427825e-07, 1.37125e-06, 4000000000),  # CIRIS x JD 2
    ("000029479_conj_000042794_20220623_035251_20220619_055818", 20, 1.0528810522231525e-07, 5.7675e-07, 4000000000),  # HINODE (SOLAR B) x DSAT
    ("000029479_conj_000054630_20230725_134006_20230718_222924", 6.5, 2.5798883474007632e-08, 4.745e-07, 4000000000),  # HINODE (SOLAR B) x CZ-6A DEB
    ("000033331_conj_000049571_20221005_095022_20221002_220322", 20, 1.1185056583674349e-08, 2.115e-07, 4000000000),  # GEOEYE 1 x COSMOS 1408 DEB
    ("000043613_conj_000043712_20221015_083008_20221009_220335", 7, 2.897004923706724e-08, 1.7125e-07, 4000000000),  # ICESAT-2 x TIANPING 1A
    ("000043613_conj_000049557_20221119_064308_20221115_150510", 7, 2.1767597879350253e-08, 1.1025e-07, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000050929_20220128_234921_20220123_065918", 7, 1.7717251905053688e-08, 1.0775e-07, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000051228_20220215_122556_20220209_225622", 7, 1.960349710253407e-08, 1.7175e-07, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000051418_20220204_181230_20220129_152147", 7, 6.831851713802742e-08, 3.35e-07, 4000000000),  # ICESAT-2 x COSMOS 1408 DEB
    ("000043613_conj_000052010_20230626_045217_20230620_061741", 7, 9.48121992242837e-09, 1.4975e-07, 4000000000),  # ICESAT-2 x SPACEBEE-114
    ("000043613_conj_000052010_20230626_062628_20230619_143324", 7, 3.309830219667702e-08, 7.38e-07, 4000000000),  # ICESAT-2 x SPACEBEE-114
    ("000043613_conj_000053131_20221020_115338_20221014_064753", 7, 6.802956686012873e-08, 4.835e-07, 4000000000),  # ICESAT-2 x CZ-2C R/B
    ("000045121_conj_000045957_20220912_081610_20220908_142756", 4, 5.124929283626495e-12, 3.16e-07, 4000000000),  # CIRIS x FREGAT DEB
    ("000032060_conj_000050346_20220311_070404_20220305_230151", 20, 0.0002187346130053717, 7.518461538461538e-05, 130000000),  # WORLDVIEW 1 x COSMOS 1408 DEB
    ("000039574_conj_000039477_20220711_110033_20220705_220442", 8, 2.444474262376311e-05, 3.895e-07, 4000000000),  # GPM x BREEZE-M DEB (TANK)
    ("000040376_conj_000054517_20230606_101715_20230531_221558", 7.5, 4.7520143737095955e-05, 1.5138805970149254e-05, 670000000),  # SMAP x CZ-6A DEB
    ("000048901_conj_000048903_20211219_182317_20211217_232706", 2, 4.514373246174853e-81, 1.29575e-06, 4000000000),  # TROPICS PATHFINDER x LINCS2
    ("000048901_conj_000048903_20211219_235030_20211215_225057", 2, 6.474713441888025e-168, 1.1664367816091955e-05, 870000000),  # TROPICS PATHFINDER x LINCS2
    ("000048901_conj_000048903_20211220_012535_20211215_145954", 2, 3.863473078436182e-168, 1.0197979797979798e-05, 990000000),  # TROPICS PATHFINDER x LINCS2
]


def sig(x: float, digits: int = 6) -> float:
    return float(f"{x:.{digits}g}")


def load_cdm(subdir: str, name: str) -> CDM:
    """Fetch a CARA CDM once into deck/data/raw/cara/ and parse it with brahe.

    CARA's files write unavailable OD statistics as NaN, which the CCSDS
    standard does not allow for integer fields, so those lines are dropped.
    """
    path = RAW_DIR / f"{name}.cdm"
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{CARA_URL}/{subdir}/{name}.cdm", timeout=60) as resp:
            path.write_bytes(resp.read())
    lines = path.read_text().splitlines()
    kept = [ln for ln in lines if "=" not in ln or ln.split("=", 1)[1].split()[:1] != ["NaN"]]
    return CDM.from_str("\n".join(kept))


def cdm_states(cdm: CDM) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Inertial (EME2000) states [m, m/s] and 6x6 inertial covariances of both objects."""
    x1 = np.asarray(cdm.object1_state, dtype=float)
    x2 = np.asarray(cdm.object2_state, dtype=float)
    variant = bh.OrbitRelativeFrameVariant.INERTIAL
    p1 = bh.covariance_rtn_to_eci(x1, np.asarray(cdm.object1_covariance, dtype=float), variant)
    p2 = bh.covariance_rtn_to_eci(x2, np.asarray(cdm.object2_covariance, dtype=float), variant)
    return x1, p1, x2, p2


def encounter_plane(r1, v1, c1, r2, v2, c2) -> tuple[float, np.ndarray, np.ndarray]:
    """Miss distance, 2x2 combined covariance in the encounter plane, and frame axes.

    Rows of `axes` are the unit vectors x (miss direction), y (relative
    velocity) and z (relative angular momentum) in the input frame.
    """
    r = np.asarray(r2, dtype=float) - np.asarray(r1, dtype=float)
    v = np.asarray(v2, dtype=float) - np.asarray(v1, dtype=float)
    y = v / np.linalg.norm(v)
    h = np.cross(r, v)
    z = h / np.linalg.norm(h)
    x = np.cross(y, z)
    axes = np.vstack([x, y, z])
    proj = axes[[0, 2]]
    cov = np.asarray(c1, dtype=float)[:3, :3] + np.asarray(c2, dtype=float)[:3, :3]
    return float(np.linalg.norm(r)), proj @ cov @ proj.T, axes


def pc_circle(miss: float, cp: np.ndarray, hbr: float) -> float:
    """Probability mass of N(0, cp) inside the circle of radius hbr centred at (miss, 0).

    Eigenvalues are clipped at (1e-4 HBR)^2 as in CARA's CovRemEigValClip.
    For each x across the circle, the conditional distribution of z given x is
    N(k x, s^2) with k = Cxz / Cxx and s^2 = Czz - Cxz^2 / Cxx, so the chord
    |z| <= h(x) carries mass Phi((h - k x) / s) - Phi((-h - k x) / s).
    """
    lam, vec = np.linalg.eigh(cp)
    cp = vec @ np.diag(np.maximum(lam, (1e-4 * hbr) ** 2)) @ vec.T
    sxx, sxz, szz = cp[0, 0], cp[0, 1], cp[1, 1]
    k = sxz / sxx
    s = np.sqrt(szz - sxz**2 / sxx)

    def integrand(x: float) -> float:
        h = np.sqrt(max(hbr**2 - (x - miss) ** 2, 0.0))
        a, b = (-h - k * x) / s, (h - k * x) / s
        # Use upper tails when the chord lies above the conditional mean to avoid cancellation.
        mass = special.ndtr(b) - special.ndtr(a) if a < 0 else special.ndtr(-a) - special.ndtr(-b)
        return np.exp(-0.5 * x * x / sxx) / np.sqrt(2.0 * np.pi * sxx) * mass

    # Breakpoints around the Gaussian's core so a covariance much narrower than the
    # circle is never stepped over by the adaptive quadrature.
    lo, hi = miss - hbr, miss + hbr
    sx = np.sqrt(sxx)
    points = [p for p in (0.0, -5 * sx, -2 * sx, 2 * sx, 5 * sx) if lo < p < hi]
    pc, _ = integrate.quad(integrand, lo, hi, epsabs=0.0, epsrel=1e-10, limit=200, points=points or None)
    return float(pc)


def pc_foster(r1, v1, c1, r2, v2, c2, hbr: float) -> float:
    miss, cp, _ = encounter_plane(r1, v1, c1, r2, v2, c2)
    return pc_circle(miss, cp, hbr)


def validation_cases() -> list[dict]:
    rows = []
    for name, r1, v1, c1, r2, v2, c2, hbr, expected in OMITRON_CASES:
        pc = pc_foster(r1, v1, c1, r2, v2, c2, hbr)
        rows.append({"case": name, "source": "CARA unit test", "pc_ours": pc, "pc_cara": expected})
    for num, hbr, expected in ALFANO_CASES:
        x1, p1, x2, p2 = cdm_states(load_cdm("SampleCDMs", f"AlfanoTestCase{num:02d}"))
        pc = pc_foster(x1[:3], x1[3:], p1, x2[:3], x2[3:], p2, hbr)
        rows.append({"case": f"Alfano 2009 case {num}", "source": "CARA unit test", "pc_ours": pc, "pc_cara": expected})
    for cid, hbr, pc2d, pc_sdmc, _ in CARA_CDM_CASES:
        cdm = load_cdm("PcTestCaseCDMs", cid)
        x1, p1, x2, p2 = cdm_states(cdm)
        pc = pc_foster(x1[:3], x1[3:], p1, x2[:3], x2[3:], p2, hbr)
        rows.append(
            {
                "case": f"{cdm.object1_name.strip()} x {cdm.object2_name.strip()} ({cid[-31:-16]})",
                "source": "CARA test CDM",
                "pc_ours": pc,
                "pc_cara": pc2d,
                "pc_cara_sdmc": pc_sdmc,
            }
        )
    for row in rows:
        row["rel_err"] = abs(row["pc_ours"] / row["pc_cara"] - 1.0)
        for key in ("pc_ours", "pc_cara", "pc_cara_sdmc", "rel_err"):
            if key in row:
                row[key] = sig(row[key], 10 if key != "rel_err" else 3)
    return rows


def sqrt_factor(cov: np.ndarray) -> np.ndarray:
    lam, vec = np.linalg.eigh(cov)
    return vec * np.sqrt(np.maximum(lam, 0.0))


def wilson_interval(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (well behaved when k is small)."""
    p = k / n
    den = 1.0 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), mid + half


def monte_carlo(x1, p1, x2, p2, hbr: float, axes: np.ndarray, rng: np.random.Generator) -> dict:
    """Sample both states at TCA; each pair moves rectilinearly to its own closest approach."""
    l1, l2 = sqrt_factor(p1), sqrt_factor(p2)
    hits = 0
    plot_xy, plot_hit = None, None
    # Running estimate at log-spaced sample counts, to show how the estimate converges.
    checkpoints = np.unique(np.logspace(1, np.log10(MC_SAMPLES), 61).astype(int))
    running_hits = []
    for start in range(0, MC_SAMPLES, MC_CHUNK):
        n = min(MC_CHUNK, MC_SAMPLES - start)
        s1 = x1 + rng.standard_normal((n, 6)) @ l1.T
        s2 = x2 + rng.standard_normal((n, 6)) @ l2.T
        dr, dv = s2[:, :3] - s1[:, :3], s2[:, 3:] - s1[:, 3:]
        t_ca = -np.einsum("ij,ij->i", dr, dv) / np.einsum("ij,ij->i", dv, dv)
        rho = dr + dv * t_ca[:, None]
        hit = np.linalg.norm(rho, axis=1) < hbr
        cum = hits + np.cumsum(hit)
        running_hits += [int(cum[c - start - 1]) for c in checkpoints if start < c <= start + n]
        hits += int(hit.sum())
        if plot_xy is None:
            plot_xy = rho[:MC_PLOT_POINTS] @ axes[[0, 2]].T
            plot_hit = hit[:MC_PLOT_POINTS]
    pc = hits / MC_SAMPLES
    half = 1.959964 * np.sqrt(pc * (1.0 - pc) / MC_SAMPLES)
    lo, hi = zip(*(wilson_interval(k, int(c)) for k, c in zip(running_hits, checkpoints)))
    return {
        "running": {
            "n": checkpoints.tolist(),
            "hits": running_hits,
            "pc": [k / c for k, c in zip(running_hits, checkpoints)],
            "ci95_lo": list(lo),
            "ci95_hi": list(hi),
        },
        "pc": pc,
        "hits": hits,
        "ci95": [pc - half, pc + half],
        "plot_xy": plot_xy,
        "plot_hit": plot_hit,
    }


def time_propagation(x_gcrf: np.ndarray, epoch: bh.Epoch) -> float:
    """Wall time [s] to propagate one LEO state COST_SPAN_DAYS with 20x20 gravity + drag."""
    src = bh.ParameterSource.parameter_index
    force = bh.ForceModelConfig(
        gravity=bh.GravityConfiguration.spherical_harmonic(20, 20),
        drag=bh.DragConfiguration(model=bh.AtmosphericModel.HARRIS_PRIESTER, area=src(1), cd=src(2)),
        mass=src(0),
    )
    config = bh.NumericalPropagationConfig.with_method(bh.IntegrationMethod.RKF78).with_abs_tol(1e-9).with_rel_tol(1e-12)
    times = []
    for _ in range(COST_TIMING_RUNS):
        prop = bh.NumericalOrbitPropagator(epoch, x_gcrf, config, force, PROP_PARAMS)
        t0 = time.perf_counter()
        prop.propagate_to(epoch + COST_SPAN_DAYS * 86400.0)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    bh.initialize_eop()
    rng = np.random.default_rng(SEED)

    validation = validation_cases()

    ref = next(c for c in CARA_CDM_CASES if c[0] == EXAMPLE_ID)
    hbr = float(ref[1])
    cdm = load_cdm("PcTestCaseCDMs", EXAMPLE_ID)
    x1, p1, x2, p2 = cdm_states(cdm)
    miss, cp, axes = encounter_plane(x1[:3], x1[3:], p1, x2[:3], x2[3:], p2)
    pc_f = pc_circle(miss, cp, hbr)
    rel_speed = float(np.linalg.norm(x2[3:] - x1[3:]))
    crossing = float(np.degrees(np.arccos(np.dot(x1[3:], x2[3:]) / np.linalg.norm(x1[3:]) / np.linalg.norm(x2[3:]))))
    mc = monte_carlo(x1, p1, x2, p2, hbr, axes, rng)

    rot = bh.rotation_eci_to_rtn(x1)
    cov2_rtn1 = rot @ p2[:3, :3] @ rot.T
    lam = np.linalg.eigvalsh(cp)

    x1_gcrf = bh.state_eme2000_to_gcrf(x1)
    sec_per_object = time_propagation(x1_gcrf, cdm.tca)
    z = float(special.ndtri(0.5 + COST_CONF / 2.0))
    n_samples = [z**2 * (1.0 - pc) / (COST_REL_ERR**2 * pc) for pc in COST_PCS]
    sec_per_sample = 2.0 * sec_per_object

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation": validation,
        "example": {
            "source": f"CARA test CDM {EXAMPLE_ID}",
            "primary": {"name": cdm.object1_name.strip(), "norad": int(cdm.object1_designator)},
            "secondary": {"name": cdm.object2_name.strip(), "norad": int(cdm.object2_designator)},
            "tca_utc": cdm.tca.isostring_with_decimals(3),
            "miss_m": sig(miss),
            "rel_speed_kms": sig(rel_speed / 1e3),
            "crossing_angle_deg": sig(crossing, 4),
            "hbr_m": hbr,
            "pc_foster": sig(pc_f),
            "pc_cara_2d": ref[2],
            "pc_cara_sdmc": ref[3],
            "cara_sdmc_n": ref[4],
            "pc_mc": sig(mc["pc"]),
            "pc_mc_ci95": [sig(v) for v in mc["ci95"]],
            "mc_n": MC_SAMPLES,
            "mc_hits": mc["hits"],
            "mc_running": mc["running"],
            "mc_seed": SEED,
            "mc_method": "6D states of both objects sampled at TCA; rectilinear relative motion to each sample's closest approach",
            "encounter_plane": {
                "miss_xy_m": [sig(miss), 0.0],
                "cov_xy_m2": [[sig(v) for v in row] for row in cp],
                "sigma_major_minor_m": [sig(float(np.sqrt(lam[1]))), sig(float(np.sqrt(lam[0])))],
                "mc_samples_xy_m": [[round(float(a), 2), round(float(b), 2)] for a, b in mc["plot_xy"]],
                "mc_hit": [bool(h) for h in mc["plot_hit"]],
            },
            "ellipsoids": {
                "cov1_rtn_m2": [[sig(v) for v in row] for row in np.asarray(cdm.object1_covariance)[:3, :3]],
                "cov2_rtn_m2": [[sig(v) for v in row] for row in cov2_rtn1],
                "rel_pos_m": [sig(v) for v in rot @ (x2[:3] - x1[:3])],
                "rel_vel_ms": [sig(v) for v in rot @ (x2[3:] - x1[3:])],
                "encounter_axes_rtn": {k: [sig(v) for v in rot @ a] for k, a in zip("xyz", axes)},
            },
        },
        "mc_cost": {
            "pc": COST_PCS,
            "n_samples": [sig(n, 4) for n in n_samples],
            "rel_err": COST_REL_ERR,
            "conf": COST_CONF,
            "prop_span_days": COST_SPAN_DAYS,
            "prop_force_model": "brahe NumericalOrbitPropagator, 20x20 EGM2008 + Harris-Priester drag, RKF78 (abs 1e-9, rel 1e-12)",
            "prop_seconds_per_object": sig(sec_per_object, 4),
            "objects_per_sample": 2,
            "prop_seconds_per_sample": sig(sec_per_sample, 4),
            "cpu_hours": [sig(n * sec_per_sample / 3600.0, 4) for n in n_samples],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"{'case':<62s} {'ours':>12s} {'CARA':>12s} {'rel err':>9s}")
    for row in validation:
        print(f"{row['case'][:62]:<62s} {row['pc_ours']:12.5e} {row['pc_cara']:12.5e} {row['rel_err']:9.1e}")
    errs = [r["rel_err"] for r in validation]
    print(f"validation: {len(errs)} cases, max rel err {max(errs):.2e}, median {np.median(errs):.2e}")
    print(
        f"example {out['example']['primary']['name']} x {out['example']['secondary']['name']}: "
        f"miss {miss:.1f} m, v_rel {rel_speed / 1e3:.2f} km/s, HBR {hbr} m"
    )
    print(f"  Pc Foster {pc_f:.4e} | CARA 2D {ref[2]:.4e} | CARA SDMC {ref[3]:.4e}")
    print(f"  Pc MC {mc['pc']:.4e} ({mc['hits']} / {MC_SAMPLES}), 95% CI [{mc['ci95'][0]:.3e}, {mc['ci95'][1]:.3e}]")
    print(f"MC cost: {sec_per_object:.3f} s per object per {COST_SPAN_DAYS:g} d propagation, x2 objects per sample")
    for pc, n, h in zip(COST_PCS, n_samples, out["mc_cost"]["cpu_hours"]):
        print(f"  Pc {pc:.0e}: N = {n:.3g} samples, {h:.3g} CPU-hours")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
