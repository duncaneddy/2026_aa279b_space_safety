# brahe 1.8.1 issues

Found while writing the AA 279B lecture scripts (`scripts/*.py`). Each is worked around in the scripts.

## Bugs

1. **NORAD IDs below 10000 rejected by GP/OMM paths.**
   `GPRecord.to_sgp_propagator` and `SGPPropagator.from_omm_elements` fail with "NORAD ID too short" for every
   catalog number < 10000 (1,982 records in the current catalog). `norad_id_numeric_to_alpha5` does not zero-pad,
   then the TLE parser trims and length-checks.
   Where: `src/propagators/sgp_propagator.rs` ~L1165, `src/orbits/tle.rs` ~L97.
   Workaround: build from TLE lines with the catalog-number field zero-padded.

2. **Blank-padded TLE catalog numbers rejected.**
   `SGPPropagator.from_tle` rejects Space-Track lines like `1    20U ...` (226 records). Blanks should parse as
   zeros; the checksum is unchanged since blanks and zeros both count 0.

3. **RKN1210 wrong for velocity-dependent forces.**
   Every stage evaluates dynamics with the step-start velocity, so drag uses a stale velocity. With 8x8 gravity +
   Harris-Priester drag at tight tolerances (1e-9 / 1e-12): 544 m off DP54 after 1 day (gravity only: 6 mm);
   143 km after 7 days at default tolerances; 29 m off an RKF78 reference after 72 h via `high_precision()`.
   No warning; docs present RKN1210 as the high-precision choice.
   Where: `src/integrators/rkn1210.rs` ~L172-180.
   Workaround: RKF78 (abs 1e-9, rel 1e-12).

4. **`Epoch.isostring_with_decimals(3)` does not zero-pad fractional seconds.**
   0.010 s prints as `.10`, 0.0996 s as `.99`.
   Workaround: format from `to_pydatetime()`.

5. **`Epoch.from_string` rejects ISO strings without a trailing `Z`.**
   e.g. `"2023-06-08T06:37:15.000"`.

6. **CDM parser rejects `NaN` in integer fields.**
   e.g. `OBS_AVAILABLE = NaN` in NASA CARA test CDMs. Separately, two CARA SingleCov CDMs fail on a missing
   secondary international designator.
   Workaround: drop those lines before parsing.

## Docs

7. `ForceModelConfig.default()` docstring says Harris-Priester drag; the code uses NRLMSISE-00 (which needs
   space-weather data).
8. `states()` docstring says it returns "the propagator's current output format"; it returns TEME like `state()`.

## Worth investigating

9. `state_eci_to_koe` rounds e below ~1e-4 to 0 (near-circular handling in `src/coordinates/cartesian.rs`), which
   shifts a rebuilt orbit by up to a·e (~1 km).
10. Trajectory `state_eci(t)` between stored steps was off by up to 0.4 m; stepping backward after propagating
    forward appears to return stored states rather than re-integrating.
11. `states_gcrf` is ~50x slower than `states`.
12. `state_koe_mean` (Brouwer from GCRF) jitters ~0.2° in RAAN for ISS, too noisy for drift rates.
13. Default DP54 tolerances (abs 1e-8 m, rel 1e-10) are slow: ~4 s for 7 days with drag, vs 1.7 s for RKF78 at
    abs 1e-6 / rel 1e-12 with better accuracy.

## API ergonomics

14. `CentralBody` has `Earth`, `Moon`, `Mars`, `EMB` and `SSB` but no `Sun`; heliocentric propagation needs
    `CentralBody.from_naif_id(NAIFId.SUN)`.
15. `spk_position(NAIFId.MARS, ...)` fails with the default `de440s` kernel ("No ephemeris path from target 499");
    only `NAIFId.MARS_BARYCENTER` works. A hint in the error toward the barycenter or a kernel with 499 would help.
