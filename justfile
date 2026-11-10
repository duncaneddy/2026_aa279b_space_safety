scripts := "basemap catalog debris_clouds ssn_sensors rideshare_tracks tle_gotchas starlink_vs_gp gps_od covariance_banana screening avoidance_budget pc maneuver pc_evolution mars_transfer"

# Regenerate every data file the deck uses
data:
    for s in {{scripts}}; do uv run scripts/$s.py || exit 1; done

# Run one analysis script, e.g. `just run screening`
run name:
    uv run scripts/{{name}}.py

# Serve the deck at http://localhost:8279
serve:
    uv run scripts/serve.py 8279
