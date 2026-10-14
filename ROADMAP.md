# Roadmap

Terra Nova Native's first public test release brings the original engine to Windows,
with the retail campaign, four Prequel missions and the changes in the
[changelog](CHANGELOG.md). The immediate priority is making this build easy to
try, report problems with and contribute to.

This is the initially uploaded working plan, not a release schedule. Feedback and reproducible bugs
will help set the order. Larger ideas need investigation before implementation.

## Initial feedback and continued collaboration

- Check setup on clean Windows installations and other hardware. Test Wine
  compatibility separately; it is currently unverified.
- Compare overlapping fixes with Terra Nova Plus and agree on useful ways to
  share patches, evidence and improvements.
- Get detailed terrain draw-distance on par with Terra Nova Plus' improvements.
- Integrate with the Terra Nova Plus launcher and keyboard/mouse remapping support.
- Restore synthesized music alongside the existing digital audio and QSound. Terra Nova Plus already supports great Awe32 music.
- Support mouselook/freelook. Terra Nova Plus already does.
- Continue campaign, Prequel, save/load and difficulty playtesting. Give special
  attention to Full-Rate AI Firing with mixed enemy groups and squad orders.

## Next gameplay and presentation work

- Investigate shots appearing offset from the reticle/crosshair center across suit arms, 
  firing height, HUD modes and reticle positions.
- Wide-screen support. Terra Nova Plus already supports this as well as 1x1 pixel ratios.
- Investigate short smoke-particle visibility and the occasional final laser
  segment changing direction at impact (visible with Shot Aim Assist off and shots outside PBA body center).
- Document enemy AI behavior/logic in plain language, including acquisition, pursuit,
  failed routes, retreat and firing decisions. Use that foundation to assess further changes/improvements, 
  including stationary defenses in some situations acquiring in-range targets late.
- Continue profiling demanding terrain and sprite scenes in normal and infrared
  views, preserving the performance improvements already made.
  Mission 9, 10 and especially 24 offer good scenes.
- Revisit remaining foliage visibility changes, Target Video distortion and
  object-depth overlaps where useful reproductions are available. Changes to
  depth ordering need particular care because of their performance cost.
  If depth ordering can't be fixed without maintaining stable 60 FPS, drop it.
- The player can still take frequent friendly fire from team PBAs if standing in or close to their line-of-fire 
  to targeted enemy units. Unclear if their line-of-fire was initially clear and the player moved, 
  if they used multipulsars or the current fix does not cover all logical behavior paths.
  Accounting for grenade/missile blast damage should also be checked deeper. Mission 9 is suitable for testing.
- Friendly PBA AI should be more wary of hitting civil/friendly buildings.
  If fighting takes place around or between such buildings, team AI can easily destroy them during the firefight.
  It is unclear what a fix should look like that won't also make them "sitting ducks" in those moments; 
  possibly modify path planning.
- The entire player team can lob grenades at the same single target at the same time.
  This is wasteful and it should be possible to make them act smarter to ration grenades better.
  This is the SFC after all -- tactical, best of the best! Mission 9 is suitable for testing.
- Co-op support; split-screen. Terra Nova Plus has already started work on this.
- Support changing the crosshair/reticle color.

## Usability and features to explore

- Make one-time setup friendlier?
- Consider controller support, e.g. Logitech F710 etc.
- Add resolution and draw-distance controls while preserving HUD proportions,
  readable text and correct mouse aiming.
- Orient explosion bursts to the surface hit, including walls and slopes.
- Investigate support for additional game editions and languages.

## Longer-term ideas with substantially larger scope

- GPU presentation or rendering, ideally with anti-aliasing support.
- Research the viability of adding a prone stance and movement to the player and PBA team-mates; 
  jump-jet disabled in that state, jump button can instead set the player back up to crouch.
- Additional modding tools for custom missions, graphics and sound etc.
- Random Scenario Builder improvements; 
  buttons for random params and outfits, return to builder screen and remember settings after missions.
- Recovery of unused game features?
- Online multi-player support? Needs serious thought; nobody wants to get RCE'd.


The project will continue to favor readable, focused patches and reproducible
builds with docs in accessible/plain, non-AI speak language.
See [Contributing](CONTRIBUTING.md) for how changes are developed and checked.
