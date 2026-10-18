# What the checks tell us

The QSound allocation regression tests follow a combat crash whose automatic
dump contained sound function pointers in the sample-handle table. They run the
original availability counter, selector and allocator from the contributor's
verified executable. A reserved-but-stopped channel makes the availability
estimate too optimistic; the unpatched code then reproduces the three corrupted
handles. The guarded version checks both allocation results, releases an
unfinished reservation, and preserves successful pairs and permitted mono
playback. Sample-device calls are modeled, so these tests do not reproduce the
whole battle or validate audible mixing. The original code stays in the user's
game files; it is not embedded in the test source.

The tests grew out of reverse engineering, reported gameplay problems and the
work of bringing the patches into one build. They serve two purposes: checking
the intended behavior and catching accidental changes to the executable or its
memory layout. Those are different kinds of evidence. A matching hash establishes
that bytes stayed the same; it does not establish that the behavior is correct.

Run synthetic checks with `python -B test.py`. Add `--retail-exe PATH_TO___FF.EXE`
and `--helpers PATH_TO_BUILD_HELPERS` for the original-routine and compiled-helper
cases. Retained renderer/scaler/cursor instructions are read from
that hash-checked file; they are not embedded in fixtures. Without it, those
checks report skips. Synthetic textures, pixels and expected results remain
invented test data. The [build guide](building.md)
lists the dependencies and the additional checks performed by a complete build.

## Camera unit visibility

`test_terrain_install.ObjectRowHandoffTests` follows a Target Camera report in
which two nearby Clones disappeared while a farther Clone remained visible.
The extended scenery cutoff also delayed the original spatial unit scan. By the
time that scan ran, its terrain clipping rows could already hide visible bodies.
The correction retains the caller's original cutoff for that scan and leaves
the extended scenery flag in place for terrain-cell collection.

Execution tests cover the threshold boundary, disabled and original canvases,
register/stack preservation, and both scenery multipliers. Captured rendering
comparisons check unit admission and scenery submissions in main and camera
views. A deliberately lowered-body control still fails the original terrain
clipping test. These checks do not replace visual playtesting of tracking cameras.

## Drone weapon damage

`test_weapon_timing.WeaponReadinessSafetyTests` follows a native crash while a
Hornet was taking damage. The original actor lookup supplies no energy record
for drones, but the weapon-damage routine checks another weapon's readiness.
An energy weapon then reads through the missing pointer. Normal drone firing
supplies its energy record through a separate path.

The tests run the original lookup, readiness and damage routines with authored
weapon records and an unmapped null page. The original case must fail at the
observed instruction; the guarded case must apply damage and still protect the
last intact, nonempty weapon. Other cases compare charge checks, cooldowns and
registers with the original behavior. The guard occupies fourteen existing code
bytes at `0x28F05F` and adds no persistent state. Captured-crash replay also passes;
these checks do not replace longer combat playtesting.

## Smoke under particle pressure

`test_smoke.SmokeBudget` runs the original particle allocator, compactor and
particle-deletion routine from the verified retail executable. Synthetic groups
contain identifiable particle records, allowing the checks to compare retained
positions as well as counts. Repeated allocations must preserve existing smoke
in draw modes 0, 1 and 8, while other modes follow the original thinning rule.
The cases cover both particle capacities, a completely smoke-filled pool and a
full group table. Ordinary particle deletion must still free space. These tests
establish allocation behavior; crowded-scene appearance and frame rate also need
playtesting. Group capacity remains 64, while particle capacity rises from 1,024
to 4,096 (36 KiB of additional particle storage).

A later held-fire report exposed a consequence of increasing storage alone:
Railgun trails kept too many old particles, then exhausted the separate group
table. Two capacity queries now count protected smoke separately and preserve
the original 1,024-particle budget for other effects. A repeated-allocation test
compares their particle records with the original smaller pool. Mixed-cloud,
empty-group, physical-capacity and register/flag checks cover the new query.
Private four-second held-fire comparisons retain normal cooldowns and physics;
the corrected particle positions, group attributes, allocations and thinning
match the previous pool policy on every sampled frame. Visual playtesting remains
the final check of the reported trail appearance.

## Runtime installation paths

`test_runtime_paths` executes the startup initializer with modeled Windows APIs.
It checks folder moves, spaces and quoted campaign commands, drive-root paths,
startup registers/stack, and rejection of long, non-ASCII or inaccessible paths.
Launcher contract checks distinguish the fixed disk image from relocated snapshot
memory. The startup jump is mutable during snapshot boot, so live code guards
cover the initializer and its constant table rather than that jump.

Native Windows checks launched the unchanged executable from a foreign working
directory, moved its installation, switched both campaign directions and entered
a Prequel mission. A paused snapshot restored after another move with the same
game clock, saved again and resumed. The ordinary executable remained unchanged.
These checks do not establish Wine, clean-machine or external-data-root support.

## Manual drone steering

The original aircraft heading update adds twice the current turn control on
every call. Executing the original keyboard scanner and conversion routines
confirms that held turn keys reach that field. At 60 updates per second, the
unchanged heading code turns three times as far as it does at 20 updates.

The timing tests execute the patched heading store with positive and negative
controls over equal elapsed time, including one-millisecond steps and uneven
frame durations. Expected angles use the existing 50-ms aircraft calibration
interval; this is a chosen reference speed, not a measured original frame rate.
Separate cases cover Camera Drone following, Explod-O-Drone target steering,
other aircraft, pauses, stalls, small fractional inputs and reused records.
Mission/deletion tests verify that the shared timing table is cleared. These
checks establish the arithmetic and input path; they do not establish the
feel of steering during a mission or fix simultaneous-key limitations.

## Smoke contacts and visibility

A later fresh-mission crash exposed a memory-ownership mistake in the smoke
helper. Its initially empty storage overlapped the scenery table that mission
initialization clears. Snapshot restoration bypassed that clear, so the earlier
restored-fight test could not catch it. The helper now uses an explicit gap
between the Options reservation and host log. The installer rejects placement
outside that gap even when the supplied image is blank. A regression test runs
the original table-clear instructions and memset implementation, with the
expanded scenery operands, and verifies that smoke code and state survive.
Live retail, Prequel and random-scenario starts supplement that focused check.

The smoke tests follow a captured Particle Beam shot that stopped below a
rising cloud instead of reaching a tank. The original cloud object kept a
fixed, open-bottomed collision column while its particles moved upward. Its
admission test also drew a new random result on repeated ray checks.

The replacement follows the current particle transform and tests finite puff
volumes. A stable shot/cloud density decision prevents additional updates from
creating additional chances to stop that shot. This retains probabilistic smoke
obstruction, but deliberately removes the accumulated odds of repeated checks;
combat balance still needs player feedback. Non-projectile sight/picking queries
use a short game-time interval. Particle movement and expiry retain their
existing elapsed-time updates.

Synthetic geometry covers clear paths above, below and beside puffs, inside and
tangent contacts, rotation, expiry, unsupported modes, segment subdivision and
nearer solid obstructions. The compiled C runs through Unicorn; the group
transform and prior solid result are modeled for these independent geometry
expectations. Separate hook checks cover installation conflicts, reused shot
slots, display scaling and main-view distance scope. Negative projection values
and very large positive values are included after live testing exposed an
arithmetic overflow in the first candidate.

Private captured-state comparisons execute the original transform and actual
firing, grenade-contact and particle drawing routines. The formerly blocked
elevated beam reaches the tank at 20, 60 and 120 supplied updates per second;
the low trajectory still hits intervening terrain. A real smoke grenade retains
its particle counts and lifetime. Raster checks confirm larger puffs and a later
transition to single pixels at native resolution. These are bounded regression
checks, not proof of every weapon, cloud combination or difficulty setting.
Finite puff volumes approximate the artwork; original raster size caps,
transparency, terrain collection and fog can still limit what is visible.

## Detached beam trails under object pressure

A Mission 34 crash dump contained 299 occupied object IDs, including 48
detached beam segments retained briefly for smoother presentation. The original
PBA-creation caller exits the game when allocation fails. Suit records were
still available; the shared object-ID pool was exhausted.

The pressure check releases one matching detached visual tail only when the
object free list is empty. The synthetic tests cover available space, one-tail
reclamation, inactive objects, reused effect-record identities, untagged live
segments, the last valid ID and preservation of caller registers/flags. Their
deletion callback is modeled. A separate captured-memory replay uses the real
deletion and object/suit allocation paths: unchanged allocation fails; releasing
one retained tail, manually or through the new hook, allocates a valid PBA slot.

This does not expand the pool or evict units, live shots or arbitrary effects.
If no eligible retained tail exists, original allocation failure remains.
The evidence addresses the captured failure; another natural crowded battle
is still needed for player acceptance.

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
The sky cases in `test_terrain_install.py` came from a cloud-layer jump during
small changes in walking tilt. Synthetic camera matrices check the direct
fixed-point ray equation at several viewport heights and verify preserved caller
state. An optional check admits the verified original instruction span. Private
scene comparisons isolate tilt from position and cloud scrolling; visual walking
checks remain necessary because matching a formula alone cannot establish the
appearance of the whole scene.

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
| `smoke` | Check finite cloud collision, frame-independent contact rolls, mission-reset storage and particle scaling. Raster tests execute the original circle drawer and compare explicit mask spans across tall/short canvases, smoke/other modes and clipped edges. | Natural cloud appearance and crowded-combat exhaustion still require playtesting. |
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

## Beam impact direction

The beam-impact tests exercise the assembled visual endpoint hook with invented
coordinates, including glancing angles, terrain/miss controls and large signed
positions. They check the original call stack and preserved processor state.
A captured-game comparison separately checks unchanged collision results, damage
and player state; visual appearance still requires playtesting.


### Enemy Outfitting click safety

A native crash on a unit-name label exposed an original null read before the
button dispatcher checked whether a button was found. The input-view tests run
the original instructions from the locally supplied retail executable, reproduce
the fault with an unmapped low page, and compare valid callback selection and
restricted rear slots against the corrected routine. The callback and audio
boundaries are modeled; live menu selection verifies the visible outcome.


## Unlocked aiming depth

The shot-assist tests use independent sphere geometry to check contact depth,
including tangency, the original query's grazing margin, an origin inside a body,
all world axes and large coordinates. A body-height offset and several physics
IDs exercise the original record layout. Accurate mesh contacts keep their depth,
and assist-on, terrain/miss results, range limits and processor state are checked.
A private captured encounter adds real firing and projectile updates with both
wrists and helmet origins. These fixtures verify the calculation; the apparent
trajectory near a visible sprite boundary still needs human playtesting.


## Customized enemy weapons and scenario snapshots

The enemy weapon tests run the original selector from the supplied retail
executable against authored PBA, vehicle, drone and structure records. They
reproduce the Laser faction rejection and check other factions, all 26 offered
weapons, cached/rescanned selection, health, energy, cooldown and ammunition.
The original controller wrapper is also checked at its 500-ms rescan boundary.
Thermal Disruptor cases reproduce an uninitialized acceptance flag and retain
the original target exclusions and unsigned timestamp conditions, including
wraparound. Smoke Grenade checks exercise its separate squad-state conditions.

A private matrix uses all 21 menu unit types and 26 offered weapons. Separate
checks execute actual unit construction and projectile-firing wrappers for all
546 combinations. These establish construction and dispatch, with audio modeled;
they do not simulate controller tactics, projectile flight or impact. Natural
customized-unit combat and ammunition-driven switching still need playtesting.

Scenario report tests use authored memory containing retained campaign counters
and a fresh report archive, matching an observed Arena capture failure. The
original scenario-launch branch selects map IDs 42, 43 and 44. Tests check all
three IDs, neighboring campaign IDs, existing report preservation and missing
files. Campaign report validation remains strict. A private Arena was captured,
restored and captured again with the same paused clock, objects and suit records.
That round trip does not establish every scenario's completion/save behavior.


## Game exit during process enumeration

Session tests model an image-path query failing after a process-list snapshot was
taken. A successful exit-status query showing termination permits the entry
to be ignored. An already-removed PID produces OpenProcess error 87 with the
fixed valid access flags and is also skipped; access-denied and other failures
still block launch. A private
Windows test also holds an actual process-list snapshot across normal game exit:
the previous scanner fails, the corrected scanner skips the exited entry, and
restart succeeds. The owner's separate paused game remains visible to the scan.


## Queued weapon sound lifetime

Audio tests run the original two-entry firing queue and its drain with authored
shooter/projectile IDs. The host audio dispatcher is modeled, so tests establish
dispatch rather than audible mixing. Projectile deletion preserves the muzzle
sample while clearing its flight association; shooter/unrelated deletion and
sound-first ordering retain their behavior. Cases cover both queue entries,
repeated deletion before draining, an empty second drain, and successful as well
as failed host dispatch. A private close Tripulsar replay
checks identical object/suit state alongside restored firing-sample dispatch.
Natural close-range and ordinary-range audio remain playtest acceptance.
