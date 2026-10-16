# Patch catalogue

These are the supported feature groups, organized by purpose. They are not separate downloads or instructions for applying patches by hand. Setup constructs one compatible game installation. The source guide maps these groups to their implementation files.

| ID | Feature group | Main changes | Important dependencies or boundaries |
| --- | --- | --- | --- |
| HOST | Windows support | Native file, memory, display, input, event handling and timing services | Executes original game code; original files are required. |
| AUDIO | Digital audio and movie timing | Speech, effects, movie PCM and retained QSound; safe sound-channel allocation and recovery from device/window interruptions | Native audio bridge; synthesized music is outside this release. |
| RENDER | Renderer and scenery | High-resolution world, terrain/maps, visibility, composition, reflections and visual variation | Owns rendering buffers and capacities; visibility changes do not extend weapon range. |
| HUD | HUD, cameras and interference | Suit layouts, mini-views, transparency, borders, map graphics, camera headings and timed distortion | Shares render coordinates and buffer ownership with RENDER. |
| INPUT | Mouse, menus and terminal | Dragging, sliders, map centering, retained zoom across Options, keyboard navigation, room events and paused UI | Original menu/script behavior and native focus/capture handling. |
| PHYSICS | Timing and movement | Elapsed-time remainder, protection recovery, jump and movement calibration | Original simulation, difficulty and actor statistics remain authoritative. |
| COLLISION | Selection and contact | Optional precise or original target selection, short projectile sweeps, stale-exclusion correction, selected model contacts and tree clearance | Geometry is derived from verified original resources; selection and collision are distinct. Projectile queries retain their source-body exclusion while preventing an unrelated previous hit from hiding a target. |
| SMOKE | Smoke visibility and obstruction | Finite contacts following living puffs, stable per-shot density decisions, resolution-aware puff sizes and longer main-view visibility | Shares the particle transform and world ray path; geometry follows smoke motion while particle lifetime stays unchanged. |
| WEAPONS | Player firing | Partial-volley accounting, beam behavior, wrist origins and optional unlocked shot assistance | Original costs/cooldowns; explicit target lock is preserved. |
| AI | Combat decisions and recovery | Range, allied-body clearance, solid-cover checks, recent-attacker response, route recovery and optional firing cadence | Uses original planner, movement restrictions and weapon/difficulty rules. |
| OPTIONS | Shared preferences | FPS, firing cadence, wrist origin and shot-assist controls, help and persistence | Accept/Cancel semantics; campaign changes and snapshot restores have different reset needs. |
| PREQUEL | Demo campaign | Four adapted missions, menus, equipment, narrative and same-window switching | Retail/demo resources, script callback tables, shared audio and Options. |
| SAVES | Launcher and persistence | Portable installation checks, exact snapshots, normal-save report preservation and restoration | Exact snapshots require matching code/layout; process-specific handles are recreated. |

The [changelog](../CHANGELOG.md) records notable changes; the [README](../README.md) describes options and current limitations. A feature may need several small source functions for code, settings and tests; those functions belong to its group and do not require a user-managed patch order.

The intended contributor workflow is to edit a named feature, run its affected tests, then build the complete game from supported originals. The current build resolves dependencies itself and validates expected instructions, memory ownership and output identities. The contributor export excludes private research histories, intermediate binaries, saved-memory fixtures and reconstruction tools. See the [build guide](building.md) and [source guide](source-guide.md).

Consolidation preserves current gameplay unless a change is explicitly identified in release notes. Optional behavior belongs in Options; obsolete intermediate installers do not belong in the public patch list.
