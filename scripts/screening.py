# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy", "scipy"]
# ///
"""One-vs-catalog conjunction screening of a primary over a 7-day span.

Screens one primary spacecraft (default: the ISS, NORAD 25544) against every
on-orbit object in the public Space-Track GP catalog, the way an operator does:
cheap geometric sieves first, then SGP4 fine screening of the survivors.

Sieves, in the classic order of Hoots, Crawford & Roehrich (1984) and as named
in Figure 1 of Srinivas, Kim, Eddy & Kochenderfer (2026):

  1. APSIS  the radial shells [perigee, apogee] of the two orbits overlap.
  2. PATH   the minimum orbit intersection distance (MOID) between the two
            orbit ellipses is small enough.
  3. PHASE  both objects are near the other's orbital plane at the same time.

The span is cut into 30-minute windows. In each window every object is frozen
as the two-body ellipse of its osculating SGP4 state at the window midpoint.
The deviation of SGP4 from that ellipse grows monotonically from the midpoint,
so it is measured at the two window edges and, enlarged by 20 %, used as each
object's pad. It covers node and perigee drift, short-period terms and drag
over the window. With D the screening distance (the radius of the sphere that
encloses the screening box) and pads e_p, e_s, an object can only reach the box
during a window if

  APSIS  q_s <= Q_p + D + e_p + e_s  and  q_p <= Q_s + D + e_p + e_s
  PATH   MOID <= D + e_p + e_s
  PHASE  there is a time t in the window with |r_s(t) . h_p| <= D + e_p + e_s
         and |r_p(t) . h_s| <= D + e_p + e_s  (h = orbit-plane unit normal)

so the sieves only reject pairs that cannot violate the box. Survivors are
propagated with SGP4 on a 60 s grid inside the windows they passed; each local
minimum of range is refined to the time of closest approach (TCA, where
r_rel . v_rel = 0) and kept if the relative position at TCA, in the primary's
RTN frame, is inside the screening box. Unless --no-validate is given, every catalog object is also brute-force
screened on the same grid to confirm that the sieves lose no event (this takes
a few minutes).

Screening box (half-widths, centered on the primary): 2 km radial x 25 km
in-track x 25 km cross-track, the near-Earth operator screening volume of the
18th/19th Space Defense Squadron Spaceflight Safety Handbook for Satellite
Operators, v1.7 (April 2023).

Objects that share the primary's element set (modules and docked vehicles of
the ISS) are not screened. SGP4 states are compared in TEME; distances and RTN
components do not depend on the inertial frame. The hero trajectories are
written in GCRF.

Sources:
  F. R. Hoots, L. L. Crawford, R. L. Roehrich, "An analytic method to determine
    future close approaches between satellites", Celestial Mechanics 33, 143-158
    (1984).
  V. Srinivas, G. R. Kim, D. Eddy, M. J. Kochenderfer, "Scalable LEO Conjunction
    Screening using Adaptive Synthetic-Covariance Thresholds", arXiv:2610.11645
    (2026).
  T. Wisniowski, H. Rickman, "Fast geometric method for calculating accurate
    minimum orbit intersection distances", Acta Astronomica 63, 293-307 (2013).
  18th/19th Space Defense Squadron, Spaceflight Safety Handbook for Satellite
    Operators, v1.7 (2023).
  Space-Track.org GP class (requires SPACETRACK_USER / SPACETRACK_PASS). The raw
    download is cached in deck/data/raw/ and reused when present.

Run:
  uv run scripts/screening.py [--norad 25544] [--days 7] [--no-validate] [--out PATH]

Output: deck/data/screening.json (km, km/s, s)
  counts        objects left after each sieve (passing in at least one window),
                objects with a box event, objects with a TCA closer than 5 km
  pair_windows  the same funnel counted in (object, window) pairs
  recall        brute-force box events and how many the sieves retained
  events        box events sorted by miss distance
  rel_speeds_kms  relative speed at every TCA within the screening distance
  hero          closest box event: secondary RTN track over +/-10 min (t_s from
                TCA) and both GCRF orbits over +/- half a primary period
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import brahe as bh
import numpy as np
from brahe.spacetrack import operators as op
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "deck/data/raw"
GP_CACHE = RAW / "spacetrack_gp_catalog.json"

RAD = bh.AngleFormat.RADIANS
KM = 1e3
BOX_KM = np.array([2.0, 25.0, 25.0])  # radial, in-track, cross-track half-widths
D_SCREEN = float(np.linalg.norm(BOX_KM)) * KM  # sphere enclosing the box
STEP_S = 60.0  # fine-screening grid
WINDOW_S = 1800.0  # sieve window
PAD_FACTOR = 1.2  # margin on the measured two-body deviation
REFINE_MARGIN = 15.0 * KM  # linearized-miss margin for refining a grid minimum
HERO_HALF_S = 600.0
HERO_DT_S = 0.5
ORBIT_DT_S = 20.0

ALL_VS_ALL_PAPER = {
    "catalog": 33791,
    "brute": 570898945,
    "fixed50": 228619849,
    "adaptive": 162819449,
    "cite": "Srinivas et al. 2026, arXiv:2610.11645",
}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


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


def element_key(rec: dict) -> tuple:
    keys = ("EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
            "ARG_OF_PERICENTER", "MEAN_ANOMALY")
    return tuple(rec[k] for k in keys)


def gp_propagator(rec: dict) -> bh.SGPPropagator:
    """SGP4 propagator from the record's TLE lines.

    Space-Track pads catalog numbers below 10000 with blanks; the brahe TLE parser
    expects zeros. The checksum is unchanged since blanks and zeros both count 0.
    """
    def zero_pad(line: str) -> str:
        return line[:2] + line[2:7].replace(" ", "0") + line[7:]

    return bh.SGPPropagator.from_tle(zero_pad(rec["TLE_LINE1"]), zero_pad(rec["TLE_LINE2"]), STEP_S)


def propagate(prop: bh.SGPPropagator, epochs: list) -> np.ndarray:
    """SGP4 TEME states (m, m/s) at `epochs`; rows from the first SGP4 failure on are NaN."""
    try:
        return np.asarray(prop.states(epochs))
    except bh.BraheError:
        pass
    # SGP4 fails once an orbit decays; bisect for the first failing epoch.
    lo, hi = 0, len(epochs)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        try:
            prop.states(epochs[:mid])
            lo = mid
        except bh.BraheError:
            hi = mid
    x = np.full((len(epochs), 6), np.nan)
    if lo > 0:
        x[:lo] = np.asarray(prop.states(epochs[:lo]))
    return x


# ---------------------------------------------------------------------------
# Two-body geometry
# ---------------------------------------------------------------------------


def perifocal_axes(oe: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit vectors to perigee (P), 90 deg ahead in the plane (Q), and orbit normal (W)."""
    i, raan, argp = oe[..., 2], oe[..., 3], oe[..., 4]
    ci, si, cO, sO, cw, sw = np.cos(i), np.sin(i), np.cos(raan), np.sin(raan), np.cos(argp), np.sin(argp)
    P = np.stack([cO * cw - sO * sw * ci, sO * cw + cO * sw * ci, sw * si], axis=-1)
    Q = np.stack([-cO * sw - sO * cw * ci, -sO * sw + cO * cw * ci, cw * si], axis=-1)
    W = np.stack([sO * si, -cO * si, ci], axis=-1)
    return P, Q, W


def ellipse_point(a, e, P, Q, E):
    """Position on the orbit ellipse at eccentric anomaly E (broadcasts; P, Q carry a trailing 3)."""
    x = a * (np.cos(E) - e)
    y = a * np.sqrt(1.0 - e * e) * np.sin(E)
    return x[..., None] * P + y[..., None] * Q


def ellipse_derivs(a, e, P, Q, E):
    """Position and its first two derivatives with respect to eccentric anomaly."""
    b = a * np.sqrt(1.0 - e * e)
    c, s = np.cos(E)[..., None], np.sin(E)[..., None]
    a, b, e = a[..., None], b[..., None], e[..., None]
    r = a * (c - e) * P + b * s * Q
    dr = -a * s * P + b * c * Q
    ddr = -a * c * P - b * s * Q
    return r, dr, ddr


def projection_scan(aA, eA, PA, QA, aB, eB, PB, QB, n_scan):
    """Sample orbit A and pair each sample with the point of orbit B at the same in-plane angle.

    Each sample of A is projected onto the plane of B; the point of B at the true
    anomaly of that projection lies on (or next to) the floor of the distance valley,
    even for nearly tangent or coplanar orbits (Wisniowski & Rickman 2013).
    Returns the anomalies E_A, E_B and squared distances, each of shape (K, n_scan).
    """
    EA = np.broadcast_to(np.linspace(0.0, 2.0 * np.pi, n_scan, endpoint=False), (len(aA), n_scan))
    rA = ellipse_point(aA[:, None], eA[:, None], PA[:, None, :], QA[:, None, :], EA)
    f = np.arctan2(np.sum(rA * QB[:, None, :], -1), np.sum(rA * PB[:, None, :], -1))
    eb = eB[:, None]
    EB = 2.0 * np.arctan2(np.sqrt(1.0 - eb) * np.sin(f / 2), np.sqrt(1.0 + eb) * np.cos(f / 2))
    rB = ellipse_point(aB[:, None], eb, PB[:, None, :], QB[:, None, :], EB)
    return EA, EB, np.sum((rA - rB) ** 2, -1)


def moid(a1, e1, P1, Q1, a2, e2, P2, Q2, accept_below=0.0, n_scan=48, n_iter=30) -> np.ndarray:
    """Minimum orbit intersection distance for each pair of ellipses (vectorized over pairs).

    Starting points come from a projection scan of each orbit against the other.
    Every local minimum of a scan, and each scan's smallest sample, is refined with
    damped Newton steps (Levenberg-Marquardt) on f = |r1(E1) - r2(E2)|^2 / 2. The
    smallest value over all starting points is the MOID. Pairs whose scan already
    comes within accept_below are not refined: their value is the scan minimum, an
    upper bound that is enough to decide a test MOID <= accept_below.
    """
    E1a, E2a, d2a = projection_scan(a1, e1, P1, Q1, a2, e2, P2, Q2, n_scan)
    E2b, E1b, d2b = projection_scan(a2, e2, P2, Q2, a1, e1, P1, Q1, n_scan)
    E1s, E2s, d2s = (np.concatenate(v, 1) for v in ((E1a, E1b), (E2a, E2b), (d2a, d2b)))
    is_min = np.zeros(d2s.shape, dtype=bool)
    for d2, cols in ((d2a, slice(0, n_scan)), (d2b, slice(n_scan, 2 * n_scan))):
        is_min[:, cols] = (d2 < np.roll(d2, 1, axis=1)) & (d2 <= np.roll(d2, -1, axis=1))
        is_min[np.arange(len(d2)), cols.start + np.argmin(d2, axis=1)] = True
    is_min[d2s.min(axis=1) <= np.square(accept_below)] = False
    k, i = np.nonzero(is_min)
    x = np.stack([E1s[k, i], E2s[k, i]], -1)
    seed = d2s[k, i]
    o1, o2 = (a1[k], e1[k], P1[k], Q1[k]), (a2[k], e2[k], P2[k], Q2[k])

    def f_and_derivs(x):
        p1, dp1, ddp1 = ellipse_derivs(*o1, x[:, 0])
        p2, dp2, ddp2 = ellipse_derivs(*o2, x[:, 1])
        d = p1 - p2
        g = np.stack([np.sum(d * dp1, -1), -np.sum(d * dp2, -1)], -1)
        h11 = np.sum(dp1 * dp1, -1) + np.sum(d * ddp1, -1)
        h22 = np.sum(dp2 * dp2, -1) - np.sum(d * ddp2, -1)
        h12 = -np.sum(dp1 * dp2, -1)
        return 0.5 * np.sum(d * d, -1), g, h11, h12, h22

    f, g, h11, h12, h22 = f_and_derivs(x)
    lam = 1e-3 * (h11 + h22)
    for _ in range(n_iter):
        # Solve (H + lam I) step = -g for each pair.
        a, c = h11 + lam, h22 + lam
        det = a * c - h12 * h12
        det = np.where(det > 0, det, np.inf)
        step = -np.stack([c * g[:, 0] - h12 * g[:, 1], a * g[:, 1] - h12 * g[:, 0]], -1) / det[:, None]
        step = np.clip(step, -0.5, 0.5)
        f_new, g_new, n11, n12, n22 = f_and_derivs(x + step)
        better = f_new < f
        x = np.where(better[:, None], x + step, x)
        f = np.where(better, f_new, f)
        g = np.where(better[:, None], g_new, g)
        h11, h12, h22 = (np.where(better, n, o) for n, o in ((n11, h11), (n12, h12), (n22, h22)))
        lam = np.where(better, lam / 3.0, lam * 4.0)
    out = np.full(len(a1), np.inf)
    np.minimum.at(out, k, np.minimum(2.0 * f, seed))
    out = np.minimum(out, d2s.min(axis=1))
    return np.sqrt(np.maximum(out, 0.0))


def check_moid() -> None:
    """MOID against closed-form cases (km)."""
    def orbit(a_km, e, inc_deg, raan_deg=0.0, argp_deg=0.0):
        oe = np.array([[a_km, e, np.radians(inc_deg), np.radians(raan_deg), np.radians(argp_deg), 0.0]])
        P, Q, _ = perifocal_axes(oe)
        return oe[:, 0], oe[:, 1], P, Q

    cases = [
        ("coplanar circles 7000 / 7100 km", orbit(7000, 0, 0), orbit(7100, 0, 0), 100.0),
        ("equal circles, 60 deg apart, crossing at the nodes", orbit(7000, 0, 0), orbit(7000, 0, 60), 0.0),
        ("equatorial 7000 km vs polar 7050 km circle", orbit(7000, 0, 0), orbit(7050, 0, 90, 30), 50.0),
        ("coplanar ellipse 6750 x 8250 km crossing a 7000 km circle", orbit(7500, 0.1, 0), orbit(7000, 0, 0), 0.0),
        ("ellipse 6750 x 8250 km, nodes at 7000 km on a polar circle", orbit(7500, 0.1, 0, 0, 0),
         orbit(7000, 0, 90, np.degrees(np.arccos((7500 * 0.99 / 7000 - 1) / 0.1))), 0.0),
        ("equal coplanar ellipses, perigees 1 deg apart (nearly tangent)", orbit(11000, 0.3, 30, 40, 100),
         orbit(11000, 0.3, 30, 40, 101), 0.0),
    ]
    for name, o1, o2, expected in cases:
        got = moid(*o1, *o2)[0]
        assert abs(got - expected) < 0.05, f"MOID check failed: {name}: {got:.3f} km, expected {expected} km"


# ---------------------------------------------------------------------------
# Sieves
# ---------------------------------------------------------------------------


def window_models(x_nodes: np.ndarray, half: float) -> tuple[np.ndarray, np.ndarray]:
    """Osculating elements at each window midpoint and the two-body pad for each window.

    x_nodes holds SGP4 states at window edges and midpoints (2W+1 rows). The pad is
    PAD_FACTOR times the larger distance between SGP4 and the midpoint two-body
    orbit at the two edges of the window. Windows in which SGP4 failed at any node
    get an infinite pad (the sieves then keep them).
    """
    start, mid, end = x_nodes[0:-1:2], x_nodes[1::2], x_nodes[2::2]
    oe = np.full(mid.shape, np.nan)
    pad = np.full(len(mid), np.inf)
    ok = np.isfinite(start[:, 0]) & np.isfinite(mid[:, 0]) & np.isfinite(end[:, 0])
    if not ok.any():
        return oe, pad
    oe[ok] = bh.state_eci_to_koe(mid[ok], RAD)
    ok &= oe[:, 1] < 0.99
    o = oe[ok]
    n = np.sqrt(bh.GM_EARTH / o[:, 0] ** 3)
    dev = np.zeros(len(o))
    for sign, edge in ((-1.0, start[ok]), (1.0, end[ok])):
        o_edge = o.copy()
        o_edge[:, 5] = o[:, 5] + sign * n * half
        r_edge = bh.state_koe_to_eci(o_edge, RAD)[:, :3]
        dev = np.maximum(dev, np.linalg.norm(edge[:, :3] - r_edge, axis=1))
    pad[ok] = PAD_FACTOR * dev
    return oe, pad


def plane_band_times(oe: np.ndarray, h_other: np.ndarray, tol: np.ndarray, half: float) -> np.ndarray:
    """Time intervals (s from window midpoint) when the two-body orbit is within tol of a plane.

    With r(E) = a (cos E - e) P + b sin E Q, the distance to the plane with unit
    normal h is A cos E + B sin E + C = R cos(E - phi) + C, so |.| <= tol gives at
    most two arcs of eccentric anomaly per revolution. Each arc is mapped to mean
    anomaly and then to time, for the revolutions that can touch the window.
    Returns (K, 6, 2) [start, end] intervals clipped to the window; empty ones are (inf, -inf).
    """
    a, e, M0 = oe[:, 0], oe[:, 1], oe[:, 5]
    P, Q, _ = perifocal_axes(oe)
    ph, qh = np.sum(P * h_other, -1), np.sum(Q * h_other, -1)
    A, B, C = a * ph, a * np.sqrt(1.0 - e * e) * qh, -a * e * ph
    R = np.hypot(A, B)
    phi = np.arctan2(B, A)
    lo, hi = -tol - C, tol - C
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha_lo = np.arccos(np.clip(lo / R, -1.0, 1.0))  # cos(psi) >= lo/R  <=>  |psi| <= alpha_lo
        alpha_hi = np.arccos(np.clip(hi / R, -1.0, 1.0))  # cos(psi) <= hi/R  <=>  |psi| >= alpha_hi
    empty = (hi < -R) | (lo > R)
    arcs = np.stack([np.stack([alpha_hi, alpha_lo], -1), np.stack([-alpha_lo, -alpha_hi], -1)], 1)
    E = arcs + phi[:, None, None]
    M = E - e[:, None, None] * np.sin(E)
    n = np.sqrt(bh.GM_EARTH / a**3)
    period = 2.0 * np.pi / n
    start = np.mod(M[:, :, 0] - M0[:, None], 2.0 * np.pi) / n[:, None]
    length = (M[:, :, 1] - M[:, :, 0]) / n[:, None]
    revs = np.array([0.0, -1.0, -2.0])
    t0 = (start[:, :, None] + revs * period[:, None, None]).reshape(len(a), 6)
    t1 = t0 + np.repeat(length, 3, axis=1)
    t0, t1 = np.maximum(t0, -half), np.minimum(t1, half)
    bad = (t1 < t0) | np.repeat(empty, 6).reshape(-1, 6)[:, :6]
    return np.stack([np.where(bad, np.inf, t0), np.where(bad, -np.inf, t1)], -1)


def phase_overlap(oe_p, oe_s, tol, half) -> np.ndarray:
    """True where the primary is near the secondary's plane while the secondary is near the primary's."""
    _, _, W_p = perifocal_axes(oe_p)
    _, _, W_s = perifocal_axes(oe_s)
    iv_p = plane_band_times(oe_p, W_s, tol, half)
    iv_s = plane_band_times(oe_s, W_p, tol, half)
    start = np.maximum(iv_p[:, :, None, 0], iv_s[:, None, :, 0])
    end = np.minimum(iv_p[:, :, None, 1], iv_s[:, None, :, 1])
    return np.any(start <= end, axis=(1, 2))


def run_sieves(props, x_prim_nodes, node_epochs, half):
    """Apply APSIS, PATH and PHASE per window. Returns per-object window masks for each stage."""
    oe_p, pad_p = window_models(x_prim_nodes, half)
    if not np.all(np.isfinite(pad_p)):
        raise RuntimeError("SGP4 failed for the primary inside the span")
    q_p, Q_p = oe_p[:, 0] * (1 - oe_p[:, 1]), oe_p[:, 0] * (1 + oe_p[:, 1])
    n_win = len(oe_p)

    apsis = np.zeros((len(props), n_win), dtype=bool)
    oe_s, pad_s = [np.empty((0, 6))], [np.empty(0)]
    for j, prop in enumerate(props):
        x = propagate(prop, node_epochs)
        oe, pad = window_models(x, half)
        tol = D_SCREEN + pad_p + pad
        q, Q = oe[:, 0] * (1 - oe[:, 1]), oe[:, 0] * (1 + oe[:, 1])
        modeled = np.isfinite(pad)
        unmodeled = np.isfinite(x[0:-1:2, 0]) & ~modeled  # SGP4 fails inside the window: keep it
        apsis[j] = unmodeled | (modeled & (q <= Q_p + tol) & (q_p <= Q + tol))
        oe_s.append(oe[apsis[j]])
        pad_s.append(pad[apsis[j]])

    # Rows of oe_s / pad_s follow np.nonzero(apsis): object-major, then window.
    rows, wins = np.nonzero(apsis)
    oe_s, pad_s = np.concatenate(oe_s), np.concatenate(pad_s)
    tol = D_SCREEN + pad_p[wins] + pad_s
    modeled = np.isfinite(tol)

    path_ok = ~modeled
    m = np.nonzero(modeled)[0]
    P_p, Q_p_ax, _ = perifocal_axes(oe_p)
    P_s, Q_s_ax, _ = perifocal_axes(oe_s)
    d_moid = np.full(len(rows), np.inf)
    for c in np.array_split(m, max(1, len(m) // 4000)):
        if not len(c):
            continue
        w = wins[c]
        d_moid[c] = moid(oe_p[w, 0], oe_p[w, 1], P_p[w], Q_p_ax[w], oe_s[c, 0], oe_s[c, 1], P_s[c], Q_s_ax[c],
                         accept_below=tol[c])
    path_ok |= d_moid <= tol

    phase_ok = path_ok & ~modeled
    c = np.nonzero(path_ok & modeled)[0]
    if len(c):
        phase_ok[c] = phase_overlap(oe_p[wins[c]], oe_s[c], tol[c], half)

    path = np.zeros_like(apsis)
    phase = np.zeros_like(apsis)
    path[rows, wins] = path_ok
    phase[rows, wins] = phase_ok
    return apsis, path, phase


# ---------------------------------------------------------------------------
# Fine screening
# ---------------------------------------------------------------------------


def refine_tca(prop_p, prop_s, t0: bh.Epoch, ta: float, tb: float) -> dict:
    """Root of the range rate r_rel . v_rel between grid times ta < tb (s from t0)."""
    def range_rate(t):
        x = prop_s.state(t0 + t) - prop_p.state(t0 + t)
        return float(np.dot(x[:3], x[3:]))

    t = brentq(range_rate, ta, tb, xtol=1e-4)
    x_p = prop_p.state(t0 + t)
    rel = prop_s.state(t0 + t) - x_p
    rtn = bh.rotation_eci_to_rtn(x_p) @ rel[:3]
    return {
        "t": t,
        "miss_km": float(np.linalg.norm(rel[:3])) / KM,
        "rtn_km": rtn / KM,
        "rel_speed_kms": float(np.linalg.norm(rel[3:])) / KM,
    }


def fine_screen(prop_p, x_prim, props, epochs, t0, grid: dict) -> list[dict]:
    """Every local range minimum within D_SCREEN of the primary.

    grid maps an object index to the sorted indices of `epochs` to screen it on; a
    minimum is detected between two consecutive grid steps where the range rate
    r_rel . v_rel changes sign from negative to non-negative.
    """
    events = []
    for j, g in grid.items():
        x = propagate(props[j], [epochs[i] for i in g])
        dr, dv = x[:, :3] - x_prim[g, :3], x[:, 3:] - x_prim[g, 3:]
        rv = np.einsum("ij,ij->i", dr, dv)
        k = np.nonzero((rv[:-1] < 0.0) & (rv[1:] >= 0.0) & (np.diff(g) == 1))[0]
        if not len(k):
            continue
        # Straight-line closest approach from the grid point before the minimum.
        tau = np.clip(-rv[k] / np.einsum("ij,ij->i", dv[k], dv[k]), 0.0, STEP_S)
        d_lin = np.linalg.norm(dr[k] + dv[k] * tau[:, None], axis=1)
        for kk in k[d_lin < D_SCREEN + REFINE_MARGIN]:
            ev = refine_tca(prop_p, props[j], t0, g[kk] * STEP_S, (g[kk] + 1) * STEP_S)
            if ev["miss_km"] * KM <= D_SCREEN:
                ev["obj"] = j
                events.append(ev)
    return events


def in_box(ev: dict) -> bool:
    return bool(np.all(np.abs(ev["rtn_km"]) <= BOX_KM))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def utc(epoch: bh.Epoch) -> str:
    return epoch.to_pydatetime().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hero_block(prop_p, prop_s, rec_s, t0, ev) -> dict:
    """Relative RTN track around TCA and both GCRF orbits over +/- half a primary period."""
    tca = t0 + ev["t"]
    t_s = np.arange(-HERO_HALF_S, HERO_HALF_S + HERO_DT_S / 2, HERO_DT_S)
    eps = [tca + float(s) for s in t_s]
    x_p = np.asarray(prop_p.states_gcrf(eps))
    x_s = np.asarray(prop_s.states_gcrf(eps))
    rel_rtn = np.einsum("kij,kj->ki", bh.rotation_eci_to_rtn(x_p), x_s[:, :3] - x_p[:, :3]) / KM

    period = 2.0 * np.pi / np.sqrt(bh.GM_EARTH / prop_p.semi_major_axis**3)
    orbit_t = np.arange(-period / 2, period / 2 + ORBIT_DT_S / 2, ORBIT_DT_S)
    orbit_eps = [tca + float(s) for s in orbit_t]
    return {
        "secondary": {"name": rec_s["OBJECT_NAME"], "norad": int(rec_s["NORAD_CAT_ID"])},
        "tca_utc": utc(tca),
        "miss_km": round(ev["miss_km"], 3),
        "miss_rtn_km": [round(float(v), 3) for v in ev["rtn_km"]],
        "rel_speed_kms": round(ev["rel_speed_kms"], 3),
        "t_s": [round(float(v), 1) for v in t_s],
        "rel_rtn_km": np.round(rel_rtn, 3).tolist(),
        "orbit_t_s": [round(float(v), 1) for v in orbit_t],
        "primary_xyz_km": np.round(np.asarray(prop_p.states_gcrf(orbit_eps))[:, :3] / KM, 2).tolist(),
        "secondary_xyz_km": np.round(np.asarray(prop_s.states_gcrf(orbit_eps))[:, :3] / KM, 2).tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--norad", type=int, default=25544, help="primary NORAD ID (default: ISS)")
    parser.add_argument("--days", type=float, default=7.0,
                        help="screening span in days (rounded up to whole 30-min windows)")
    parser.add_argument("--no-validate", action="store_true", help="skip the brute-force recall check")
    parser.add_argument("--out", type=Path, default=ROOT / "deck/data/screening.json")
    args = parser.parse_args()

    bh.initialize_eop()
    check_moid()
    records = fetch_catalog()

    prim_rec = next(r for r in records if int(r["NORAD_CAT_ID"]) == args.norad)
    prim_key = element_key(prim_rec)
    others = [r for r in records if element_key(r) != prim_key]
    n_attached = len(records) - len(others) - 1
    prop_p = gp_propagator(prim_rec)
    recs, props = [], []
    for r in others:
        try:
            props.append(gp_propagator(r))
            recs.append(r)
        except (bh.BraheError, RuntimeError):
            pass  # malformed element set
    n_bad = len(others) - len(recs)

    # Span starts at the hour of the catalog's newest creation date.
    created = max(r["CREATION_DATE"] for r in records)
    t0 = bh.Epoch.from_string(created[:13] + ":00:00Z")
    n_win = int(np.ceil(args.days * 86400.0 / WINDOW_S))
    span = n_win * WINDOW_S
    half = WINDOW_S / 2
    node_epochs = [t0 + half * k for k in range(2 * n_win + 1)]
    epochs = [t0 + STEP_S * k for k in range(int(span / STEP_S) + 1)]
    x_prim = propagate(prop_p, epochs)

    tic = time.perf_counter()
    apsis, path, phase = run_sieves(props, propagate(prop_p, node_epochs), node_epochs, half)
    t_sieve = time.perf_counter() - tic
    # Fine-screen each survivor only on the grid steps of the windows it passed.
    steps = int(round(WINDOW_S / STEP_S))
    survivors = {
        j: np.unique(np.add.outer(np.nonzero(phase[j])[0] * steps, np.arange(steps + 1)))
        for j in np.nonzero(phase.any(axis=1))[0]
    }
    tic = time.perf_counter()
    found = fine_screen(prop_p, x_prim, props, epochs, t0, survivors)
    t_fine = time.perf_counter() - tic
    box_events = sorted((ev for ev in found if in_box(ev)), key=lambda ev: ev["miss_km"])

    recall, t_brute = None, None
    if not args.no_validate:
        tic = time.perf_counter()
        every_step = np.arange(len(epochs))
        brute = fine_screen(prop_p, x_prim, props, epochs, t0, {j: every_step for j in range(len(props))})
        t_brute = time.perf_counter() - tic

        def matched(ev):
            return any(f["obj"] == ev["obj"] and abs(f["t"] - ev["t"]) < 1.0 for f in found)

        brute_box = [ev for ev in brute if in_box(ev)]
        recall = {
            "brute_force_events": len(brute_box),
            "retained": sum(matched(ev) for ev in brute_box),
            "brute_force_within_d": len(brute),
            "retained_within_d": sum(matched(ev) for ev in brute),
            "runtime_s": {"sieves_and_fine": round(t_sieve + t_fine, 1), "brute_force": round(t_brute, 1)},
        }

    def n_objects(evs):
        return len({ev["obj"] for ev in evs})

    counts = {
        "catalog": len(props),
        "apsis": int(apsis.any(axis=1).sum()),
        "path": int(path.any(axis=1).sum()),
        "phase": int(phase.any(axis=1).sum()),
        "box": n_objects(box_events),
        "lt_5km": n_objects([ev for ev in found if ev["miss_km"] < 5.0]),
    }
    events = [
        {
            "norad": int(recs[ev["obj"]]["NORAD_CAT_ID"]),
            "name": recs[ev["obj"]]["OBJECT_NAME"],
            "tca_utc": utc(t0 + ev["t"]),
            "miss_km": round(ev["miss_km"], 3),
            "rel_speed_kms": round(ev["rel_speed_kms"], 3),
        }
        for ev in box_events
    ]
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "primary": {"name": prim_rec["OBJECT_NAME"], "norad": args.norad},
        "span_start_utc": t0.isostring(),
        "span_days": span / 86400.0,
        "box_km": {"R": float(BOX_KM[0]), "T": float(BOX_KM[1]), "N": float(BOX_KM[2]), "half_widths": True},
        "counts": counts,
        "pair_windows": {
            "total": int(apsis.size),
            "apsis": int(apsis.sum()),
            "path": int(path.sum()),
            "phase": int(phase.sum()),
        },
        "recall": recall,
        "events": events,
        "rel_speeds_kms": sorted(round(ev["rel_speed_kms"], 3) for ev in found),
        "hero": None,
        "all_vs_all_paper": ALL_VS_ALL_PAPER,
    }
    if box_events:
        ev = box_events[0]
        out["hero"] = hero_block(prop_p, props[ev["obj"]], recs[ev["obj"]], t0, ev)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    speeds = np.array(out["rel_speeds_kms"])
    print(f"primary {prim_rec['OBJECT_NAME']} ({args.norad}), span {t0.isostring()} + {span / 86400.0:g} d, "
          f"{n_attached} attached objects skipped, {n_bad} unreadable element sets")
    print(f"box +/-{BOX_KM[0]:g} R x {BOX_KM[1]:g} T x {BOX_KM[2]:g} N km, screening distance {D_SCREEN / KM:.1f} km")
    print("objects: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"pair-windows: apsis {apsis.sum()}, path {path.sum()}, phase {phase.sum()} of {apsis.size}")
    print(f"box events {len(events)}, approaches within {D_SCREEN / KM:.1f} km {len(found)}")
    if len(speeds):
        print(f"rel speed min/median/max {speeds.min():.2f}/{np.median(speeds):.2f}/{speeds.max():.2f} km/s")
    if hero := out["hero"]:
        print(f"hero {hero['secondary']['name']} ({hero['secondary']['norad']}) at {hero['tca_utc']}: "
              f"miss {hero['miss_km']} km, RTN {hero['miss_rtn_km']} km, {hero['rel_speed_kms']} km/s")
    print(f"sieves {t_sieve:.1f} s + fine screening of {len(survivors)} objects {t_fine:.1f} s")
    if recall:
        print(f"brute force {t_brute:.1f} s: box events retained {recall['retained']}/{recall['brute_force_events']}, "
              f"minima within D retained {recall['retained_within_d']}/{recall['brute_force_within_d']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
