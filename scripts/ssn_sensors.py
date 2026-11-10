# /// script
# requires-python = ">=3.12"
# dependencies = ["brahe==1.8.1", "numpy"]
# ///
"""Space Surveillance Network sensor coverage for a LEO and a GEO target.

Sensors: the 21 Vallado SSN sites bundled with brahe (Fundamentals of
Astrodynamics and Applications, 4th ed., Tables 4-2/4-3/4-4), with each
site's azimuth window, minimum elevation and maximum range. Sites without
published limits use brahe's open defaults (azimuth 0-360 deg, elevation
0 deg, unlimited range).

Footprints: for each sensor and target altitude, the outer boundary of the
sub-satellite points at which a target at that altitude is inside the
sensor's field of view (elevation >= el_min, slant range <= range_max,
azimuth within the window). Along each azimuth the boundary lies at the
lowest usable elevation: el_min, or the elevation where the slant range
reaches range_max if that is higher. Sensors with a limited azimuth window
give a wedge that starts and ends at the site. The ring is null when the
target altitude is beyond the sensor's range. Longitudes are in [-180, 180),
so a ring jumps by ~360 deg where it crosses the antimeridian; rings around
high-latitude sites can enclose the pole. Rings are outer envelopes: the
overhead blind cone from el_max < 90 deg is not removed.

Sample track: a sun-synchronous LEO satellite (Sentinel-2A, NORAD 40697)
propagated with SGP4 from its latest Space-Track GP element set for 24 h.
Access windows per sensor come from brahe's access search with each sensor's
elevation, azimuth and range limits. Visibility is purely geometric: optical
sensors also need a dark sky and a sunlit target, so stats are also given
for radars only.

radar_ratio: the radar equation gives SNR ~ 1/R^4, so moving the same target
from 1,000 km to 36,000 km range costs (36000/1000)^4. Optical detection of
reflected sunlight scales as 1/R^2.

Data source: brahe SSN sensor dataset (offline); Space-Track.org GP for the
sample satellite (requires SPACETRACK_USER / SPACETRACK_PASS), cached in
deck/data/raw/ and reused when present.

Run:
  uv run scripts/ssn_sensors.py [--out PATH]

Output: deck/data/ssn_sensors.json
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
SAMPLE_NORAD = 40697
CACHE = RAW / f"spacetrack_gp_{SAMPLE_NORAD}.json"

LEO_ALT_KM = 800.0
GEO_ALT_KM = 35786.0
AZ_STEP_DEG = 2.0
TRACK_SPAN_S = 86400.0
TRACK_STEP_S = 10.0
ACCESS_STEP_S = 5.0
RADAR_LEO_KM, RADAR_GEO_KM = 1000.0, 36000.0


def fetch_gp() -> dict:
    """Latest GP record for the sample satellite."""
    if not CACHE.exists():
        client = bh.SpaceTrackClient(os.environ["SPACETRACK_USER"], os.environ["SPACETRACK_PASS"])
        query = (
            bh.SpaceTrackQuery(bh.RequestClass.GP)
            .filter("NORAD_CAT_ID", str(SAMPLE_NORAD))
            .order_by("EPOCH", bh.SortOrder.DESC)
            .limit(1)
        )
        RAW.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(client.query_raw(query))
    return json.loads(CACHE.read_text())[0]


def bisect(f, lo: np.ndarray, hi: np.ndarray, iters: int = 50) -> np.ndarray:
    """Vectorized bisection for the root of a function increasing from lo to hi."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        pos = f(mid) > 0.0
        hi = np.where(pos, mid, hi)
        lo = np.where(pos, lo, mid)
    return 0.5 * (lo + hi)


def los_ecef(site_ecef: np.ndarray, az: np.ndarray, el: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """ECEF points at slant range rho along azimuth/elevation (radians) from the site."""
    enz = np.stack([np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)], axis=-1) * rho[:, None]
    return bh.relative_position_enz_to_ecef(site_ecef, enz, bh.EllipsoidalConversionType.GEODETIC)


def slant_range_to_altitude(site_ecef, az, el, h_m) -> np.ndarray:
    """Slant range at which the line of sight reaches geodetic altitude h_m."""

    def excess(rho):
        geod = bh.position_ecef_to_geodetic(los_ecef(site_ecef, az, el, rho), bh.AngleFormat.DEGREES)
        return geod[:, 2] - h_m

    return bisect(excess, np.zeros_like(az), np.full_like(az, 2.0 * (h_m + 2.0 * bh.R_EARTH)))


def footprint(sensor: bh.SimpleSSNSensor, h_km: float) -> list[list[float]] | None:
    """Boundary of the sub-satellite points visible to the sensor at altitude h_km."""
    loc = sensor.location
    site_geod = np.array([loc.lon, loc.lat, loc.alt])
    site_ecef = bh.position_geodetic_to_ecef(site_geod, bh.AngleFormat.DEGREES)
    h_m = h_km * 1e3

    full = (sensor.az_max - sensor.az_min) % 360.0 == 0.0
    span = 360.0 if full else (sensor.az_max - sensor.az_min) % 360.0
    n = int(np.ceil(span / AZ_STEP_DEG)) + 1
    az = np.radians(sensor.az_min + np.linspace(0.0, span, n))
    el_min = np.full(n, np.radians(sensor.el_min))

    if sensor.range_max is not None:
        overhead = slant_range_to_altitude(site_ecef, az, np.full(n, np.pi / 2), h_m)
        if np.any(overhead > sensor.range_max):
            return None
        rho_low = slant_range_to_altitude(site_ecef, az, el_min, h_m)
        # Where the lowest elevation is out of range, raise the elevation until range == range_max.
        el_range = bisect(
            lambda el: sensor.range_max - slant_range_to_altitude(site_ecef, az, el, h_m),
            el_min,
            np.full(n, np.pi / 2),
            iters=30,
        )
        el = np.where(rho_low > sensor.range_max, el_range, el_min)
    else:
        el = el_min

    rho = slant_range_to_altitude(site_ecef, az, el, h_m)
    geod = bh.position_ecef_to_geodetic(los_ecef(site_ecef, az, el, rho), bh.AngleFormat.DEGREES)
    lonlat = geod[:, :2]
    if not full:
        lonlat = np.vstack([site_geod[:2], lonlat, site_geod[:2]])
    lonlat[:, 0] = (lonlat[:, 0] + 180.0) % 360.0 - 180.0
    return np.round(lonlat, 2).tolist()


def sensor_constraint(sensor: bh.SimpleSSNSensor):
    parts = [
        bh.ElevationConstraint(min_elevation_deg=sensor.el_min, max_elevation_deg=sensor.el_max),
        bh.AzimuthConstraint(sensor.az_min, sensor.az_max),
    ]
    if sensor.range_max is not None:
        parts.append(bh.RangeConstraint(max_range_m=sensor.range_max))
    return bh.ConstraintAll(parts)


def coverage_stats(windows: list[tuple[float, float]], span_s: float) -> dict:
    """Pass count and longest interval with no sensor in view (union of all windows)."""
    longest, covered_until = 0.0, 0.0
    for start, end in sorted(windows):
        longest = max(longest, start - covered_until)
        covered_until = max(covered_until, end)
    longest = max(longest, span_s - covered_until)
    return {"passes_24h": len(windows), "longest_gap_h": round(longest / 3600.0, 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "deck/data/ssn_sensors.json")
    args = parser.parse_args()

    bh.initialize_eop()
    sensors = bh.SimpleSSNSensor.from_locations(bh.datasets.ssn_sensors.load())

    sensor_rows, rings = [], {}
    for s in sensors:
        loc = s.location
        is_radar = s.measurement_dim == 3
        sensor_rows.append(
            {
                "name": s.name,
                "system": loc.properties["system"],
                "type": "radar" if is_radar else "optical",
                "lon": round(loc.lon, 4),
                "lat": round(loc.lat, 4),
                "alt_m": round(loc.alt, 1),
                "el_min_deg": s.el_min,
                "el_max_deg": s.el_max,
                "az_min_deg": s.az_min,
                "az_max_deg": s.az_max,
                "range_max_km": None if s.range_max is None else round(s.range_max / 1e3, 1),
                "fov_published": "el_min_deg" in loc.properties,
            }
        )
        rings[s.name] = {"leo": footprint(s, LEO_ALT_KM), "geo": footprint(s, GEO_ALT_KM)}

    rec = fetch_gp()
    sat = bh.SGPPropagator.from_tle(rec["TLE_LINE1"], rec["TLE_LINE2"], 60.0)
    start = sat.epoch
    end = start + TRACK_SPAN_S
    t_s = np.arange(0.0, TRACK_SPAN_S + 1.0, TRACK_STEP_S)
    r_itrf = np.array(sat.states_itrf([start + float(t) for t in t_s]))[:, :3]
    lonlat = bh.position_ecef_to_geodetic(r_itrf, bh.AngleFormat.DEGREES)[:, :2]

    windows, all_w, radar_w = [], [], []
    for s, row in zip(sensors, sensor_rows):
        # A fine search step is needed to resolve short exclusions such as passes
        # briefly rising above a phased array's maximum elevation.
        found = bh.location_accesses(
            s.location, sat, start, end, sensor_constraint(s),
            config=bh.AccessSearchConfig(initial_time_step=ACCESS_STEP_S),
        )
        for w in found:
            interval = (w.window_open - start, w.window_close - start)
            windows.append({"sensor": s.name, "start_s": round(interval[0], 1), "end_s": round(interval[1], 1)})
            all_w.append(interval)
            if row["type"] == "radar":
                radar_w.append(interval)
    windows.sort(key=lambda w: w["start_s"])

    stats = coverage_stats(all_w, TRACK_SPAN_S)
    stats["radar_only"] = coverage_stats(radar_w, TRACK_SPAN_S)

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sensors": sensor_rows,
        "footprints": {"leo_alt_km": LEO_ALT_KM, "geo_alt_km": GEO_ALT_KM, "rings": rings},
        "sample_track": {
            "name": rec["OBJECT_NAME"],
            "norad": SAMPLE_NORAD,
            "start_utc": start.isostring(),
            "t_s": t_s.astype(int).tolist(),
            "lonlat": np.round(lonlat, 2).tolist(),
            "windows": windows,
        },
        "stats": stats,
        "radar_ratio": {
            "leo_km": RADAR_LEO_KM,
            "geo_km": RADAR_GEO_KM,
            "snr_ratio": (RADAR_GEO_KM / RADAR_LEO_KM) ** 4,
            "optical_ratio": (RADAR_GEO_KM / RADAR_LEO_KM) ** 2,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")))

    print(f"{len(sensors)} sensors; GEO-capable: "
          f"{', '.join(n for n, r in rings.items() if r['geo'] is not None)}")
    print(f"sample {rec['OBJECT_NAME']} from {start.isostring()}: {stats['passes_24h']} passes, "
          f"longest gap {stats['longest_gap_h']} h; radars only {stats['radar_only']['passes_24h']} passes, "
          f"longest gap {stats['radar_only']['longest_gap_h']} h")
    print(f"radar SNR ratio {out['radar_ratio']['snr_ratio']:.3g}, optical {out['radar_ratio']['optical_ratio']:.3g}")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
