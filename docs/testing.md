# What the checks tell us

The tests grew out of reverse engineering, reported gameplay problems and the
work of bringing the patches into one build. They serve two purposes: checking
the intended behavior and catching accidental changes to the executable or its
memory layout. Those are different kinds of evidence. A matching hash establishes
that bytes stayed the same; it does not establish that the behavior is correct.

Run synthetic checks with `python -B test.py`. Add `--retail-exe PATH_TO___FF.EXE`
for the full suite. Retained renderer/scaler/cursor instructions are read from
that hash-checked file; they are not embedded in fixtures. Without it, those
checks report skips. Synthetic textures, pixels and expected results remain
invented test data. The [build guide](building.md)
lists the dependencies and the additional checks performed by a complete build.

## Where the evidence comes from

The address-map tests use invented LE/PE layouts and patch writes. They check
section-relative offsets, embedded-file origins, zero-filled memory, unmapped
helper ranges and overlapping final writes. Generating the published table also
checks the real executable identities and surviving complete-write hashes.
These checks establish location mapping, not that a native patch can run
unchanged inside DOSBox.

The descrambler pacing check comes from reports that weak reception remained
visually too busy even with a working timer. It executes the timer and completion
helper at several drawing rates, checks held frames and signal/clock resets,
and models only the original random-letter generator. Private panel replays use
the game resources to check the resulting text and adjacent signal thresholds.
Neither check establishes an intended historical speed; the slower whole-line
refresh is a readability choice, accepted in player testing.

* **Original executable contracts.** Hook addresses, expected instructions,
  structure offsets and continuation addresses come from analysis of the supported
  executables. Input hashes identify those editions. Names assigned to functions
  and fields describe our interpretation; they are not original source symbols.
* **Synthetic execution fixtures.** Tests create small actor records, projected
  shapes, buffers, clocks and input states, then run generated x86 in Unicorn.
  Calls into the original game or Windows are usually intercepted. A fixture may
  return a chosen result or stop at that boundary. It does not reproduce the whole
  original function, map, pathfinder or operating system.
* **Independent calculations and fixed expectations.** Distance calculations,
  pixel models, explicit restore instructions and fixed byte fingerprints provide
  expectations outside the helper being tested. Some installation tests instead
  compare two ways of composing the same helpers. That checks composition but
  cannot independently establish that those shared helpers are correct.
* **Accepted build outputs.** Engine, geometry, resource and layout hashes pin
  reviewed outputs. `tests/render-view-fingerprints.json` records assembled view
  bodies at specified addresses. These are project regression baselines, not
  hashes supplied by the original developer. Full builds also check original
  inputs and generate each selected game/resource output locally to verify its identity.
* **Gameplay observations.** Playtesting motivated many fixes, including rapid
  descrambler text, damaged-camera noise, shots blocked by hills, stalled AI routes
  and mission-specific map colors. Synthetic tests isolate the relevant condition;
  they do not claim to reproduce the entire reported encounter.

Tests use selected values to exercise a boundary deliberately. Actor positions,
fake handles, return sentinels and invalid records are fixture data, not captured
game state. Seeded random samples are repeatable arithmetic inputs, not gameplay
statistics. A test's `boundary`, `hook` or mocked API function shows which original
behavior has been replaced for that test.

The vertical projectile test comes from a reproduced straight-down miss: the
map-cell gate measured only horizontal travel. Its controlled inputs check both
sides of that threshold, rising/falling/unchanged height and projectile versus
other-query classification. It verifies dispatch and preserved registers/flags;
it does not include a terrain map. Original projectile and terrain execution was
checked separately in a private captured encounter.

## Finding the relevant tests

The infrared terrain checks in `test_final_bindings.py` exercise generated drawing
code with synthetic texture and palette data. They check changing parameters,
texture wrapping, row bounds and preserved stack/register state. The optimization
keeps the original setup and reads its mutable instruction operands as data from
separate, fixed drawing code. Private comparisons also execute original and new
routines on captured span inputs and compare complete scene pixels. Those checks
support equivalent drawing; scene timing measures world rendering only and does
not predict complete gameplay frame rate on every machine.

All names below are under `tests/` and have the `test_` prefix and `.py` suffix.
Read the test method names for the individual cases and their fixture helpers for
the modeled calls.

| Modules | Purpose and evidence | What still needs another check |
| --- | --- | --- |
| `actor_timing`, `weapon_timing`, `projectile_physics` | Execute clocks, signed remainders, projectile sampling and partial-volley accounting against controlled time and caller records. Turret pass-through investigations supply the exclusion-slot and short-cylinder tests: modeled query boundaries check scope/restoration, while known cylinder contacts check top, side, tangent, empty space and nearest fraction. | Actual movement, collisions and combat balance need in-game testing. The exclusion fixture models world/mesh calls; the cylinder fixture stops at the original continuation for ordinary segments. |
| `ai_firing`, `ai_cadence` | Execute range, clearance, weapon selection and optional polling. Synthetic weapon/faction records cover eligibility and cooldown boundaries; range also has an independent distance calculation. | Full encounters and difficulty balance require playtesting. |
| `ai_response`, `ai_recovery` | Execute attacker memory, order checks and retry/retreat decisions. Planner hooks record route requests and supply success or failure. | The fixtures do not prove that a real map has a usable route. |
| `shot_assist` | Supply collision-query results and verify projection back onto the camera ray, range clamping and option gating. | Real target geometry, explicit locks and weapon feel need gameplay coverage. |
| `target_picking`, `target_profiles` | Execute selection and coordinate conversion using synthetic quads, rectangles, depths and cache records. | Original visibility and projection routines are modeled boundaries. |
| `render_arena`, `render_inputs`, `render_views` | Check allocation, dependencies, cache identity, relocation and view ownership. Startup/view x86 executes with modeled Windows and original rendering calls. | These are not complete scene renders or performance measurements. |
| `foundation_hud`, `foundation_views`, `hud` | Exercise panel coverage, copying, clipping, sky rows and view restoration with small synthetic buffers and pixel expectations. | Visual composition across real suit layouts still needs screenshots/playtesting. |
| `foundation_recipes` | Reject malformed or overlapping plans, verify order independence, and execute navigation coordinates, projection restoration, allocation tracking and cursor clipping with explicit original-call models. | Byte/layout agreement does not prove behavior correct in every mission. |
| `maps`, `cameras` | Execute map caching, palette repair, centering, camera heading and interference timing. | Terrain generation, signal appearance and damage feedback need in-game review. |
| `input_views`, `hud_overlays` | Exercise pointer mapping/capture, borders, FPS display, sprite collision radii and roster labels. Windows calls and widget records are supplied by fixtures. | Focus changes, actual mouse use and final pixels need desktop testing. |
| `options_feature`, `option_lifecycle` | Execute preference helpers and the connected Accept/Cancel/restore chain with modeled profile APIs. Fixed restore instructions check the launcher interface independently. | Actual Options interaction and persistence across a real restart remain useful checks. |
| `mesh_geometry` | Decode synthetic model records and reject bad bounds, opcodes and membership. The complete build compares geometry generated from verified original resources. | Synthetic models alone do not cover every original model. |
| `terrain_install`, `hud_bindings`, `collision_install`, `beam_install`, `final_bindings` | Check required bytes, reservation boundaries, dependency order and complete installation. Some cases compare combined installation with separate helper composition. | Matching installation plans do not establish runtime behavior. |
| `release_contracts` | Check snapshot identities, region ownership and rejection before payload access. | A successful full capture/restore still needs a running game. |
| `sessions` | Test session selection, snapshot preparation, process races and retention using temporary files and mocked process services. | Actual Windows process and handle behavior needs integration tests. |
| `opening_movies` | Execute the startup callback guard with zero or several completed campaign switches. Verify the original callback destination, return stack and rejection of an occupied code reservation. | The movie player is a sentinel in these tests. Actual playback, skipping and menu transitions need live checks. |
| `install_paths`, `launcher_package` | Use small temporary packages to test deltas, paths, input preservation and launcher attachment, including malformed packages and failed child launches. The frozen launcher's separate self-check exercises Tk, Keystone, a Windows API call and a native-to-Python sorting callback to check libffi integration. | Full original-input builds and a clean Windows installation are separate acceptance steps. The self-check reads installation metadata; it does not exercise a live game's snapshot round trip. |

## Why the build guards exist

Expected instruction bytes prevent a patch from being applied to the wrong
edition or an incompatible hook. Empty-range checks catch a second feature using
the same memory. Bounds and guard bytes detect writes beyond a declared buffer.
Installers check all inputs before making the first change, so a late failure
does not leave half a feature installed. Tests deliberately corrupt late hooks,
truncate reads and occupy the end of a reservation to exercise that guarantee.

Idempotence checks ask whether reinstalling an already complete feature leaves
its state intact. Fresh installation and restoration have different rules:
initializing an empty table is appropriate during construction, but clearing a
live clock, actor identity or cached preference during restore can change play.
The tests check these distinctions where the feature supports both operations.

Some tests disable imports or make source-file access fail. This verifies that
the public feature has all of its dependencies declared and can build from the
supplied inputs. Those checks guard contributor reproducibility.

The build's assertions are intentional validation, so use ordinary Python rather
than `python -O`. Source hashes flag changes for review; refreshing those hashes
accepts a source edit only. It does not approve new executable or resource hashes.
An intentional output change needs its own explanation, tests and compatibility
decision before the corresponding expected output is updated.

## Adding or changing a check

Describe the failure the test would catch and where its expectation comes from.
Name modeled original/Windows calls and state their limits. A guard comment should
explain the memory, caller or file condition it protects. Prefer one clear
explanation beside the fixture or shared validation routine over repeating it at
every assertion. If a failure is deferred, retain the conditions and uncertainty;
do not turn a flaky result into a passing baseline without understanding it.

The suite runs without original game assets. Public tests contain neither saved
player memory nor a requirement to reconstruct development builds. Private
comparisons can supply additional regression evidence without becoming part of
the contributor workflow.
