# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Download the Natural Earth 1:110m land outline and save it as lon/lat polylines.

The deck draws ground tracks and sensor footprints on this outline. Natural Earth is public
domain; the TopoJSON build comes from the `world-atlas` npm package.

Run:    uv run scripts/basemap.py
Output: deck/data/land.json  {"source": str, "rings": [[[lon, lat], ...], ...]}
"""

import argparse
import json
import urllib.request
from pathlib import Path

URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/land-110m.json"


def decode_arcs(topo: dict) -> list[list[list[float]]]:
    """Undo TopoJSON delta encoding and quantization for every arc."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append([round(x * sx + tx, 3), round(y * sy + ty, 3)])
        arcs.append(pts)
    return arcs


def ring_from_arcs(indices: list[int], arcs: list[list[list[float]]]) -> list[list[float]]:
    """Stitch arc indices into a ring; negative index ~i means arc i reversed."""
    ring: list[list[float]] = []
    for i in indices:
        pts = arcs[i] if i >= 0 else arcs[~i][::-1]
        ring.extend(pts if not ring else pts[1:])
    return ring


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "deck/data/land.json")
    args = ap.parse_args()

    with urllib.request.urlopen(URL) as r:
        topo = json.load(r)
    arcs = decode_arcs(topo)
    rings = []
    for geom in topo["objects"]["land"]["geometries"]:
        polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
        for poly in polys:
            for ring in poly:
                rings.append(ring_from_arcs(ring, arcs))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"source": "Natural Earth 1:110m land via world-atlas@2.0.2", "rings": rings}, separators=(",", ":")))
    print(f"{len(rings)} rings, {sum(map(len, rings))} points -> {args.out}")


if __name__ == "__main__":
    main()
