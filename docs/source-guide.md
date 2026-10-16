# Source guide

## What is being built

The original DOS executable contains the game logic and software renderer. The build reads and relocates its LE image, adapts system services, emits checked x86 changes and places the resulting code/data in a Windows PE executable. The approximately 32 MiB image includes a deliberately reserved address layout; its size does not represent a newly rewritten engine. The Windows bridge is a separate DLL for display, input, time, digital audio and system integration.

Most changes are Python functions containing readable assembly, with explicit addresses, expected instructions and reserved ranges. Five small freestanding C helpers implement geometric collision work. The mesh helpers use model headers generated from the user's verified original resource archive rather than stored in this tree.

The original campaign scripts and resource formats still matter. Prequel adapts demo scripts/resources for the native runtime, supplies the four-mission menu and handles same-window retail/demo transitions. Launcher snapshots capture compatible game state and rebuild process-specific resources on restore; ordinary campaign saves remain the game's own mechanism.

## Navigation

| Area | Start here |
| --- | --- |
| Complete build and packaging | `build.py`, `engine/release_package.py`, `package_core.py`, `install_portable.py` |
| Engine and dependency order | `engine/build_engine.py`, `feature_plan.py`, `feature_build.py` |
| Foundation and native host | `le_image.py`, `patch_engine.py`, `foundation_*.py`, `native_host.py`, `host_*.py` |
| Windows display, audio and ABI | `engine/bridge/` |
| Rendering and terrain | `features/render_*.py`, `terrain_distance.py`, `terrain_raster.py` |
| HUD, maps, cameras and pointer | `features/hud*.py`, `maps.py`, `cameras.py`, `input_views.py`, `modal_ui.py` |
| Selection, physics and weapons | `features/target_picking.py`, `projectiles.py`, `weapon_timing.py`, `shot_assist.py`, `engine/helpers/` |
| AI response, range and cadence | `features/ai_response.py`, `ai_firing.py`, `ai_cadence.py` |
| Smoke visibility and contacts | `features/smoke.py`, `engine/helpers/smoke_ray.c` |
| Frame, actor and effect clocks | `features/frame_clock.py`, `actor_timing.py`, `effect_timing.py`, `timing_install.py` |
| Options and terminal | `features/options*.py`, `option_contracts.py`, `terminal.py`, `room_hover.py` |
| Prequel and campaign lifecycle | `features/campaign_*.py`, `prequel_*.py`, `resource_transforms.py`, `build_resources.py` |
| Launcher and snapshots | `launcher.py`, `tnova/`, `features/snapshot_controls.py`, `export_snapshot_layout.py` |
| Tests and their evidence | `test.py`, `tests/`, [test guide](testing.md) |

Unqualified engine filenames live under `engine/`; `features/` is its feature directory. The foundation providers divide responsibility as follows: `foundation_cursor.py` owns mouse updates and text coverage; `foundation_hud.py` owns bounded world preparation, panel coverage and compositor source; `foundation_cameras.py` binds the optimized compositor to camera preparation and merging. Each installs its final hooks once. Fixed helper slots and some unreachable tails are retained to preserve executable and snapshot identity; their comments identify that purpose. `foundation_recipes.py` also owns navigation, target projection and display/allocation guards; `foundation_weather.py` owns weather scaling, terrain row buffers and sky bounds; `foundation_overlays.py` owns dialog coverage, damage drawing and movie callbacks. The contributor tree contains the final providers, with no numbered foundation patch sequence.

## Contracts and build flow

1. Verify original files and source hashes. Relocate retail and demo images explicitly.
2. Decode original model resources, compile collision helpers, and verify code/data regions.
3. Generate the relocatable foundation and native Windows image using maintained providers.
4. Install the named feature groups in dependency order. Each binds current inputs, verifies hooks and owns reserved state. No predecessor executable is loaded.
5. Export the renderer/snapshot layout and check it against the launcher. Verify the executable identity.
6. Generate menu/campaign resources, normalize limited bridge linker metadata, and verify every output. Package the maintained generators and their input/output contracts.
7. Optionally freeze and attach the launcher runtime. Setup repeats local generation from verified originals, then creates a separate installation.

`original_inputs.edited_assembly` decodes retained routines from a checked local
image and applies small, address-specific edits. This keeps original renderer,
sprite-scaling and cursor passages out of the source archive while preserving
their generated code exactly. Its recipes contain ranges, hashes and changes.

`source-manifest.json` pins engine sources. `release-recipe.json` declares inputs, CD extents, portable path replacements and package outputs. `helpers/manifest.json` declares C sources, compiler, addresses and output hashes. `helpers/mesh-recipes.json` describes resource traversal without embedding model coordinates. `recipes/foundation.json` is the single foundation plan: eleven named groups, each with addresses, sizes and fingerprints. `patch_inventory.py` verifies generated bytes and rejects overlapping spans, including identical writes. Descriptor order therefore does not select implementations. Other files in `recipes/` describe demo bindings; contributors do not apply a patch chronology.

The patch catalogue groups behavior by purpose; the build groups express implementation dependencies. Contributors do not apply either list manually. Renderer/campaign files remain separate where their buffer and lifecycle contracts differ; reducing file count alone would obscure those boundaries.

## DOSBox and native address mapping

The generated [address table](address-map.csv) lists original memory regions,
useful entry points and final patch ranges. Its [metadata](address-map.json)
identifies the exact original and native executables, layout and coverage.
The table contains addresses and labels, not copied game instructions.

For the supported English retail executable, original code and data locations
use the same numeric virtual addresses in the Terra Nova Plus reference DOSBox
layout and our native image. The small second LE object's DOSBox base is not
established here, so those guest addresses are blank. Other DOSBox environments,
demo executables and game editions need their own verified mappings.

| Example | DOSBox guest address | Native virtual address | Original file offset | Native file offset |
| --- | --- | --- | --- | --- |
| Projectile sampling hook | `0x311553` | `0x311553` | `0x1669F7` | `0x300753` |
| Camera setup | `0x29E830` | `0x29E830` | `0xF3CD4` | `0x28DA30` |
| AI firing-check gate | `0x251D6E` | `0x251D6E` | `0xA7212` | `0x240F6E` |

The generator reads LE pages and PE sections to obtain file offsets. Original
zero-filled memory has no file offset. For example, the original code starts at
offset `0x994A4` in the complete executable, or `0x64200` relative to its embedded
MZ image. Mixing those two file origins gives the wrong answer.

Ranges use an exclusive end; other addresses within a row advance by the same
offset from its start. An `original-region` row maps locations only. A `patch`
row identifies a final feature writer or a surviving foundation declaration;
it can contain instructions, data or padding. The source column points to the
foundation generator or named feature dispatcher. Original-region, patch and
anchor rows can overlap intentionally. A jump-target entry decodes an `E9 rel32`
at the row's start; confirm that the bytes represent code before following it.

Native-only ranges have blank DOSBox addresses. Backporting those helpers means
allocating suitable DOS memory, reassembling references and checking calling
conventions, selectors, buffer ownership and host services. A shared address
does not prove equivalent behavior. This table does not inventory every host
routine, runtime allocation or dependency; declarations and audited writes set
its coverage. It also cannot determine where a dynamically allocated buffer is
currently pointed to.

After a complete build, regenerate the table from the repository root:

```powershell
py -3.12 -B engine/address_map.py --original C:\TNBuild\originals\TNOVA\__FF.EXE --native C:\TNBuild\output\engine\native-chain.exe --patch-audit C:\TNBuild\output\engine\patch-audit.json --output C:\TNBuild\address-map
```

The output folder must be new. The command checks executable identities and
patch-audit consistency, then writes `address-map.csv` and `address-map.json`.
Use the unbundled build image shown above, whose identity is checked; an installed
executable has different embedded paths. Review the generated files before
replacing the copies in `docs/` for a later release.
