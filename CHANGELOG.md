# Changelog

Notable changes to TNova Native, grouped by subject within each release.
The release history is based on the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

The first public test release is being prepared. These changes are relative to the original game.
Setup, option defaults and known limitations are in [README](README.md).

NOTE: Entries marked **Fixed — original game** address faults identified in original
routines or game data. Some became more apparent at higher frame rates or
resolutions; a native crash does not necessarily mean DOSBox would crash on the
same input. Other fixes cover porting, integration and frame-rate corrections.

### Windows, audio and saves

- Added native Windows input, display, timing, file and digital-audio support for the original engine, including speech, effects, movie audio and QSound positioning.
- Added a portable launcher and exact paused-mission snapshots alongside ordinary campaign saves, with installation and snapshot compatibility checks.
- Fixed persistent movie-video stutter after prolonged window dragging or HDMI audio-device changes.
- Fixed missing mission-report history when making an ordinary save after restoring a snapshot.
- Fixed skipped opening movies on a fresh retail launch.
- Fixed reproduced crashes involving expanded renderer/effect capacity, targeting, native input and restored saves.

### Graphics and performance

- Added 1280×960 world rendering, higher-resolution terrain detail in minimaps and the large tactical map, and support for all four suit HUDs.
- Added stable horizontal variation for scenery and effect sprites, plus flips and quarter-turns for detailed brown scorch marks.
- Extended terrain detail and scenery visibility, and optimized normal/infrared terrain, reflections and HUD composition.
- **Fixed — original game:** renderer queue overflows corrupting object lists, and polygon drawing crashing when its temporary buffer filled during a row update.
- **Fixed — original game:** accumulated rounding in the sky calculation making clouds jump vertically during small changes in walking tilt.
- Fixed zoom-dependent shoreline gaps, inconsistent Ground Detail presets, scenery-list truncation and clipping capacity problems.
- Fixed incorrect map palettes and out-of-bounds terrain-lighting reads near map edges.

### HUD, controls and menus

- Added options for an FPS counter, Improved Target Selection, Wrist-Height Firing and Shot Aim Assist.
- Added **N** to center the large map on the player, and pointer confinement while dragging maps.
- Improved terminal keyboard navigation and scrolling, including the keyboard exit sound.
- Slowed scrambled Pirate descrambler reception for clearer pacing. This deliberately changes the original effect; decoded text retains its separate scrolling pace.
- **Fixed — original game:** the player's forward mini-camera sitting below the normal eye position, and teammate feeds following changing AI goals instead of the suit's visible heading.
- **Fixed — original game:** head-centering sounds restarting during a single continuous reset.
- **Fixed — original game:** Ashford's retained post-reveal Outfit entry incorrectly saying he was away on a mission.
- **Fixed — original game:** lost room-hover notifications and rapid clicks using a stale hotspot, including incorrect navigation from the medals screen.
- **Fixed — original game:** canceling a dialog resuming the game clock when the mission was already paused.
- **Fixed — original game:** loss of actual magnification after closing Options while the logical zoom level remained unchanged.
- Fixed missing mini-panel borders, arrow outlines and tooltip backgrounds, and incorrect Pirate compass transparency.
- Fixed frame-rate-dependent suit interference and descrambler animation.
- Fixed paused dialog/tooltip redraws and slider/map pointer jumps.
- Fixed oval weapon/sensor range rings after display-state changes, and lost magnification when reapplying Ground Detail.

### Weapons, collision and movement

- Adjusted physics, movement and animation timing for faster rendering while retaining original weapon statistics and difficulty modifiers.
- Improved projectile hit detection and collision shapes (hitboxes) for selected buildings, vehicles, drones, PBA legs and articulated cannons.
- Improved target selection, with an option to retain the original selection behavior.
- Improved beam visibility and clearance past thin tree branches.
- **Fixed — original game:** leftover projectile exclusions that could make later shots pass through a previously hit turret.
- **Fixed — original game:** short cylinder sweeps and vertical map-cell traversal that could miss a turret entirely.
- **Fixed — original game:** projectile searches that skipped objects on very short movement segments or stopped before the end of a partial sampling step.
- **Fixed — original game:** missing sound, energy and cooldown accounting when a Multipulsar/Tripulsar volley could not emit all its bolts.
- **Fixed — original game:** small physics intervals being counted repeatedly after their accumulated time had already been consumed.
- **Fixed — original game:** fractional protection recovery being discarded each update, slowing or stopping suit and tank recovery at higher frame rates.
- **Fixed — original game:** fuel-tank collision volumes that left part of the visible tank unhittable.
- **Fixed — original game:** newly deployed ASF Autoturrets floating above the ground because the model base and physics-body center used the same height.
- **Fixed — original game:** vehicle damage reading an absent suit-subsystem record instead of applying only the applicable damage work.
- Fixed repeated jump-launch impulses and accumulated weapon-cooldown delay at different update rates.

### AI

- Added optional **Full-Rate AI Firing**, allowing more frequent weapon-readiness checks for both sides while retaining cooldowns, costs, bursts and difficulty rules. It defaults off.
- Stopped AI firing outside nominal weapon range and reduced friendly fire.
- Improved responses to recent attackers and added bounded retreat/detour recovery for eligible stalled enemies, while retaining original pathfinding, Hold/scripted orders and mission restrictions.
- Adjusted spotting, turning and retry timing for faster updates while retaining original weapon statistics and difficulty modifiers.
- **Fixed — original game:** friendly missiles ignoring terrain/building obstructions, and PBAs firing to clear scenery when a hill still blocked the target beyond it.
- **Fixed — original game:** correlated random retry rolls that could leave an AI route failure stuck despite repeated retry attempts.

### Prequel missions

- Added the four demo missions as **Prequel** on the main menu, with mission selection, sequential progression, shared Options and paused **F5** save / **F9** load pickers.
- Fixed false busy-menu errors when entering Prequel after loading a game and leaving Quarters.
- Fixed incorrect Prequel equipment, missing success narrative, premature recruitment-letter dismissal, missing target names and the dockside-craft targeting crash.

### Installation and contributor tools

- Added local generation of the adapted executable, model geometry and edited resources from verified original files, with automatic or offline tool setup.
