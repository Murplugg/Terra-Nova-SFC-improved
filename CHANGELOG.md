# Changelog

Notable changes to TNova Native, grouped by subject within each release.
The release history is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries marked **Fixed [legacy]** address faults found in the original game code or data.
Some became more noticeable at higher frame rates or resolutions. A fault that crashes
the native game may behave differently under DOSBox. Other fixes address the Windows
port, integrated features and changes needed for higher frame rates.

Bracketed references identify groups in the [patch catalogue](docs/patch-catalogue.md),
named patches or source files. See the [source guide](docs/source-guide.md) for file locations.

## [Unreleased]

### Controls and interface

- Fixed steeply misdirected unlocked shots at nearby mobile units with Shot Aim Assist disabled, especially when firing from wrist height. Aiming now uses the body's contact depth along the crosshair ray. Target Lock and Shot Aim Assist enabled retain their existing behavior. [WEAPONS, OPTIONS; shot_assist.py]

- **Fixed [legacy]:** clicking unit labels or gaps between buttons in Enemy Outfitting could crash the native game. The menu now checks whether a button was found before reading its action. [INPUT; input_views.py]

- Manual Camera Drone and Explod-O-Drone turning now follows elapsed time, preventing faster rotation at higher frame rates. Automatic following and attack steering retain their existing behavior. [TIMING; actor_timing.py]

### Windows, audio and saves

- Fixed an intermittent restart error when the Windows process list still included a game that had just exited. The launcher confirms termination before ignoring that entry. [SAVES; sessions.py]

- Fixed snapshot capture in Arena and Random Scenario Builder sessions when retained campaign counters referred to reports outside the scenario. Existing scenario reports are preserved. [SAVES; state_core.py]

- **Fixed [legacy]:** damaging a drone's weapon could crash the game when another energy weapon was checked without an energy-pool record. The check now handles that missing record while retaining the original weapon-damage rules. [WEAPONS; weapon_timing.py]
- Setup now shares unchanged assets through hard links and reuses extracted CD data, reducing storage for repeated installations. Saves, settings and generated resources remain separate; `--data-mode copy` creates independent copies. [SETUP; install_portable.py]

- Installation paths are now resolved when the game starts. Moving the complete installation no longer requires rewriting its normal executable. Saved snapshots still restore against the selected installation. [HOST, SAVES; runtime_paths.py, state_core.py]

- Fixed a combat crash when a new clone could not be created because all object slots were occupied. If a detached beam trail holds a slot, the game now removes one such trail to make room. [WEAPONS; effect_timing.py, weapon_timing.py]
- Fixed mission-start crashes introduced by the smoke changes. The smoke code now sits outside the memory cleared for scenery at mission start. [SMOKE; smoke.py]
- **Fixed [legacy]:** a failed QSound channel allocation could overwrite memory and crash the game during combat. If a sound pair cannot be allocated, the game releases any partially reserved channels. [AUDIO; audio_safety.py]

### AI and squad behavior

- **Fixed [legacy]:** enemy PBAs could reject a working Laser assigned through Customized Enemy Outfitting solely because of their faction. The selector now evaluates it with the normal readiness and scoring rules. [AI; ai_firing.py, 0x25124B]

### Graphics and performance

- Fixed thick, lingering Railgun trails and intermittent missing trails introduced by the larger particle pool. Visual effects again use their original particle budget, while smoke clouds retain their extra space and protection from thinning. [SMOKE; smoke.py]
- **Fixed [legacy]:** the last visible segment of a laser or pulsar bolt could bend toward a mobile unit on impact. The trail now follows its incoming direction, while hit detection, damage and impact effects keep their existing behavior. [WEAPONS; effect_timing.py]
- Existing smoke clouds now keep their particles when unrelated weapon effects fill the particle pool. Additional storage lets smoke coexist with the original visual-effect budget; normal smoke expiry and shot interaction remain unchanged. [SMOKE; smoke.py]
- Fixed narrow, oval smoke puffs on native world views. Their horizontal size now matches the original doubled vertical size. [SMOKE; smoke.py]
- Improved smoke visibility at native resolutions and increased its draw distance in the main view. [SMOKE; smoke.py]
- **Fixed [legacy]:** smoke could block shots passing below or beside the visible cloud. Collision now follows the moving smoke particles, and repeated frame updates no longer give the cloud extra chances to stop the same shot. [SMOKE; smoke.py, smoke_ray.c]

---------------

## [0.1.0] - 2026.10.13

The first public test release. These changes are relative to the original game.
See [README](README.md) for setup, option defaults and known limitations.

### Windows, audio and saves

- Added native Windows input, display, timing, file access and digital audio for the original engine. This includes speech, sound effects, movie audio and QSound positioning. [HOST; native_host.py, engine/bridge/]
- Added a portable launcher and snapshots that preserve a paused mission exactly, alongside ordinary campaign saves. The launcher checks installation files and snapshot compatibility. [SAVES; tnova/]
- Fixed persistent video stutter after dragging the game window for an extended period or changing HDMI audio devices during a movie. [AUDIO; terrain_raster.py]
- **Fixed [legacy]:** movies could attempt to read ahead after all remaining data was already buffered, slowing their final frames. [AUDIO]
- Fixed missing mission-report history when making an ordinary save after restoring a snapshot. [SAVES]
- Restored opening movies on a fresh retail launch. [PREQUEL; campaign_startup.py]
- Fixed crashes involving expanded rendering and effect limits, target selection, native input and restored saves. [RENDER, COLLISION, INPUT, SAVES]

### Graphics and performance

- Added 1280×960 world rendering, higher-resolution camera feeds and map terrain. All four suit HUDs use the original higher-detail visor artwork. [RENDER, HUD; render_integration.py, cameras.py, maps.py]
- Improved navigation-marker outlines at higher resolutions while keeping distance labels readable. [HUD; navigation-label]
- Added horizontal flips to scenery and effect sprites, with each sprite keeping its orientation. Detailed brown scorch marks can also be flipped and rotated in quarter-turns. [RENDER; sprite_variation.py]
- Extended terrain, scenery and unit draw distances, including detailed base pavement and markings. Optimized normal and infrared terrain rendering, reflections and HUD composition. [RENDER; terrain_distance.py, terrain_raster.py]
- Increased the number of simultaneous effects from 127 to 255 to accommodate busy combat scenes. [RENDER; effect-storage]
- **Fixed [legacy]:** overflowing the rendering queue could corrupt object lists. Polygon drawing could also crash when its temporary buffer filled during a row update. [RENDER; renderer-lists]
- **Fixed [legacy]:** rounding errors in the sky calculation could make clouds jump vertically as the player walked. [RENDER; terrain_raster.py, SKY_ROW_SITE 0x2A73DE]
- Fixed shoreline gaps when zooming, inconsistent Ground Detail settings, truncated scenery lists and insufficient clipping capacity. [RENDER; terrain_distance.py]
- Fixed incorrect map palettes and terrain-lighting reads outside the map boundaries. [RENDER, HUD]
- Fixed squashed night-sky planet sprites and their incorrect apparent sizes on the native display. [RENDER; logical-aspect]
- Fixed rain covering only part of the enlarged view. Adjusted rain, water, particle and lightning timing for higher frame rates. [RENDER; rain-clock, storm-clock]
- Fixed malformed PBA leg poses that drew long streaks across the sky when units first appeared. [RENDER; pose-repair]
- Fixed pickup-dropship engine jets jumping between positions at higher frame rates. [RENDER; effect_timing.py]

### HUD, controls and menus

- Added options for an FPS counter, Improved Target Selection, Wrist-Height Firing and Shot Aim Assist. [OPTIONS; options.py, shot_assist.py, target_picking.py]
- Added **N** to center the large map on the player. The mouse pointer stays inside the game window while dragging maps. [INPUT; map-centering, map-drag]
- Improved terminal keyboard navigation and scrolling. Leaving the terminal with the keyboard now plays its exit sound. [INPUT; terminal.py]
- Slowed the Pirate descrambler's scrambled-text animation to make the sequence easier to follow. This is a deliberate change to the original effect; decoded text keeps its separate scrolling speed. [HUD; descrambler.py]
- **Fixed [legacy]:** the player's forward camera feed used a position below the normal eye height. Teammate feeds followed changing AI goals instead of the suit's visible heading. [HUD; cameras.py]
- **Fixed [legacy]:** the head-centering sound could restart during a single continuous reset. [INPUT; terrain_raster.py]
- **Fixed [legacy]:** Ashford's Outfit entry still said he was away on a mission after his departure from the SFC. [INPUT]
- **Fixed [legacy]:** room-hover notifications could be lost, and rapid clicks could act on the previous hotspot. This included incorrect navigation from the medals screen. [INPUT; room_hover.py]
- **Fixed [legacy]:** canceling a dialog could resume the game clock while the mission was paused. [INPUT; modal_ui.py]
- **Fixed [legacy]:** closing Options could reset the displayed magnification while leaving the logical zoom level unchanged. [INPUT; detail-zoom]
- Restored missing mini-panel borders, arrow and text outlines, tooltip backgrounds and quick-command menu backgrounds. Corrected Pirate compass transparency. [HUD; hud-infill, compass-coverage]
- Restored the scale and duration of suit-damage static and distortion, including damaged camera feeds. The original component-health rules remain in use. [HUD; damage-display, camera-noise]
- Corrected suit-interference and descrambler animation timing at higher frame rates. [HUD; descrambler.py, cameras.py]
- Fixed dialog and tooltip redraws while paused, and mouse-pointer jumps when clicking sliders or releasing slider and map drags. [INPUT; modal_ui.py, input_views.py]
- Fixed cursor trails, flickering, delayed redraws, duplicate Windows cursors and pointer jumps when entering rooms. [INPUT; native-cursor, room-cursor]
- Fixed navigation-point placement freezing after a mission restart. [INPUT]
- Fixed minimaps alternating between low and high detail, and hidden camera or map panels leaving their last image on screen. [HUD; map-persistence, panel-visibility]
- Fixed oval weapon and sensor range rings after display-state changes, and lost magnification when reapplying Ground Detail. [HUD, INPUT; maps.py, detail-zoom]

### Weapons, collision and movement

- Adjusted physics, movement and animation timing for higher frame rates, including PBA idle turns, body tilt and landing poses. Original weapon statistics and difficulty modifiers are preserved. [PHYSICS; actor_timing.py]
- Improved projectile hit detection and collision shapes (hitboxes) for selected buildings, vehicles, drones, PBA legs and articulated cannons. [COLLISION; projectiles.py, engine/helpers/]
- Improved selection of overlapping targets using distance, visible PBA markers and armor-piece bounds. An option retains the original selection behavior. [COLLISION; target_picking.py]
- Changed direct-fire aiming without target lock to converge on the surface under the reticle instead of a fixed distance. This reduces aiming errors caused by the offset between the camera and weapon muzzle. [WEAPONS; reticle-convergence]
- Increased the visible density of nearby Laser and Particle Beam particles while keeping their fine, one-pixel appearance. Detached beam trails remain visible briefly after the shot ends. [WEAPONS; beam-rendering, effect_timing.py]
- Reduced movement-collision radii by 20% for six upright tree species, allowing PBAs to walk closer to their trunks through the outer branches shown by the sprites. Weapon collision is unchanged. [COLLISION]
- **Fixed [legacy]:** leftover projectile exclusions could make later shots pass through a previously hit turret. [COLLISION; projectiles.py]
- **Fixed [legacy]:** collision checks against cylinders over short distances, and traversal of vertical map cells, could miss a turret entirely. [COLLISION; projectiles.py]
- **Fixed [legacy]:** projectile collision searches could skip objects on very short movement segments or stop before the end of the final sampling step. [COLLISION; projectiles.py]
- **Fixed [legacy]:** Multipulsar and Tripulsar volleys could omit sound, energy use and cooldown accounting when they could not create every bolt. [WEAPONS; volley-timing]
- **Fixed [legacy]:** small physics intervals could be counted again after their accumulated time had already been used. [PHYSICS]
- **Fixed [legacy]:** fractional armor regeneration was discarded each update, slowing or stopping PBA and tank armor regeneration at higher frame rates. [PHYSICS]
- **Fixed [legacy]:** fuel-tank collision volumes left part of the visible tank unhittable. [COLLISION; fuel-contacts]
- **Fixed [legacy]:** newly deployed ASF Autoturrets floated above the ground because the model base and physics-body center used the same height. [COLLISION; deployable-contacts]
- **Fixed [legacy]:** vehicle damage could access a nonexistent suit-subsystem record. Vehicles now receive only the damage processing that applies to them. [COLLISION; damage-save-safety]
- Fixed repeated jump-launch impulses and weapon cooldowns accumulating delays at different update rates. [PHYSICS, WEAPONS; weapon_timing.py]

### AI

- Added optional **Full-Rate AI Firing** for friendly and enemy units. It checks weapon readiness more often while preserving cooldowns, costs, bursts and difficulty rules. The option defaults to off. [AI; ai_cadence.py]
- Stopped AI units firing beyond their weapons' nominal ranges. Weapon selection now considers which weapons can reach the target, and additional firing checks reduce friendly fire. [AI; ai_firing.py, ai-weapon-choice]
- Improved responses to recent attackers. Eligible enemies that become stuck can attempt a retreat or detour, using the original pathfinding. Hold orders, scripted orders and mission restrictions remain in effect. [AI; ai_response.py, route-recovery]
- Adjusted spotting, turning and retry timing for higher frame rates. Original weapon statistics and difficulty modifiers are preserved. [AI; ai_response.py]
- **Fixed [legacy]:** friendly missiles could ignore terrain and building obstructions. PBAs could also fire to clear scenery even when a hill behind it still blocked the target. [AI; ai_firing.py, ai-scenery-preview]
- **Fixed [legacy]:** correlated random rolls could repeatedly prevent an AI unit from retrying after a route failure. [AI; route-recovery]
- **Fixed [legacy]:** stationary defenses could access nonexistent movement-route data when reacting to an attack, causing native crashes. [AI; ai_response.py]

### Prequel missions

- Added the four demo missions under **Prequel** on the main menu, with mission selection, progression between missions and shared Options. While paused, **F5** and **F9** open snapshot save and load pickers. [PREQUEL; campaign-lifecycle, snapshot-controls]
- Fixed false “menu not ready” errors when entering Prequel after loading a game and leaving Quarters. [PREQUEL; campaign_switch.py]
- Corrected Prequel equipment and restored missing success text and target names. Fixed the recruitment letter closing too soon and the crash when targeting the dockside craft. [PREQUEL; target-names, build_resources.py]

### Installation and contributor tools

- Added local generation of the adapted executable, model geometry and edited resources from verified original game files. Required tools can be set up automatically or supplied offline. [HOST; build.py, build_engine.py, build_resources.py]
