"""Named cold-build dependencies; no release timeline or intermediate images.

All components bind directly to their maintained feature APIs. Group order below follows explicit provider dependencies.
"""
from dataclasses import dataclass

REVISION = 154
FOUNDATION_SHA = 'c8d6487dcbbcf21cf21a1a85a69cf1d3b980958b6138fdb54e664da4bf99fb50'
DEMO_SHA = '886568d2d0e15c5bcce5539832cd8bf1fd2c02655825c6ddf3cc77068be2556f'
OUTPUT_SHA = '4b943f4b4b1083aaf21bd334d4d50394fe63befe2933420871dec2c4536fc4a7'


@dataclass(frozen=True)
class Feature:
    name: str
    requires: tuple
    sources: tuple = ()


# Required provider order is local to each feature. The builder never chooses
# a source from external data, nor derives this list from stages.json.
PLAN = (
    Feature('terrain-foundation', ()),
    Feature('target-acquisition', ('terrain-foundation', )),
    Feature(
        'logical-hud', ('target-acquisition', ), (
            'damage-display', 'navigation-label', 'quick-command-coverage', 'effect-storage',
            'logical-panels', 'map-persistence', 'view-distance', 'logical-aspect', 'detail-zoom',
            'panel-visibility', 'native-cursor', 'rain-clock'
        )
    ),
    Feature('route-storage', ('logical-hud', )),
    Feature('terrain-storage', ('logical-hud', )),
    Feature(
        'collision-and-projectiles', ('target-acquisition', 'route-storage', 'terrain-storage'), (
            'map-drag', 'reticle-convergence', 'beam-rendering', 'hit-alert', 'fuel-contacts',
            'scenery-distance', 'keyboard-state', 'renderer-lists', 'railgun-provider',
            'static-contacts', 'static-instance-storage', 'hit-investigation', 'pose-repair',
            'room-cursor', 'storm-clock', 'mobile-contacts', 'compass-coverage'
        )
    ),
    Feature('actor-and-effect-timing', ('collision-and-projectiles', )),
    Feature('communications', ('logical-hud', )),
    Feature(
        'terrain-rendering', ('actor-and-effect-timing', 'terrain-storage'),
        ('deployable-contacts', 'panel-compositor', 'terrain-columns', 'water-rows', 'sky-rows')
    ),
    Feature('native-renderer', ('terrain-rendering', 'logical-hud')),
    Feature(
        'hud-and-input', ('native-renderer', 'collision-and-projectiles'),
        ('volley-timing', 'hud-infill', 'camera-heading', 'sprite-variation', 'damage-save-safety')
    ),
    Feature('terminal', ('hud-and-input', )),
    Feature(
        'world-effects', ('hud-and-input', ),
        ('terrain-surfaces', 'ai-firing-policy', 'scorch-variation')
    ),
    Feature(
        'tactical-ai', ('world-effects', 'actor-and-effect-timing'), (
            'ai-response', 'ai-weapon-choice', 'ally-response', 'ai-scenery-preview', 'ai-cadence',
            'target-names', 'map-centering', 'scenery-clipping', 'route-recovery', 'camera-noise'
        )
    ),
    Feature('campaign-startup', ('tactical-ai', )),
    Feature('shared-options', ('tactical-ai', 'campaign-startup', 'terminal')),
    Feature('modal-ui', ('native-renderer', 'hud-and-input'), ('modal-dialog', 'modal-tooltip')),
    Feature('campaign-lifecycle', ('campaign-startup', 'shared-options', 'modal-ui')),
    Feature('snapshot-controls', ('campaign-lifecycle', 'shared-options')),
    Feature('room-hover', ('modal-ui', 'campaign-lifecycle')),
    Feature('final-options', ('snapshot-controls', 'shared-options')),
    Feature('runtime-labels', ('final-options', 'room-hover', 'communications', 'terminal')),
)


def validate(plan=PLAN):
    """Reject incomplete, unknown, duplicated or out-of-order build plans."""
    if type(plan) is not tuple:
        raise ValueError('Feature plan must be immutable')
    expected = {f.name: f for f in PLAN}
    seen = set()
    for feature in plan:
        if not isinstance(feature, Feature) or expected.get(feature.name) != feature:
            raise ValueError('Unknown or modified feature declaration')
        if feature.name in seen:
            raise ValueError('Duplicate feature: ' + feature.name)
        if not set(feature.requires) <= seen:
            raise ValueError('Missing feature provider: ' + feature.name)
        seen.add(feature.name)
    if seen != set(expected):
        raise ValueError('Incomplete feature plan')
    return tuple(plan)
