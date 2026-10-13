"""Define the memory shared by Options, gameplay checks and snapshot restore.

All checkboxes store initialized, active, pending and open values at offsets
0, 4, 8 and 12. FPS and AI preferences have separate Windows API/path caches;
wrist height and shot assistance use the AI cache. Fixed addresses and numeric
compatibility IDs let the launcher restore supported snapshots safely.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Preference:
    state: int
    size: int
    init: int
    save: int
    default: int
    section: str
    key: str
    api_owner: str
    since: int


FPS = Preference(0x1f77900, 0x200, 0x1f76500, 0x1f76700, 0, 'Display', 'ShowFPS', 'fps', 99)
AI = Preference(0x1e39c00, 0x200, 0x1e39200, 0x1e39400, 0, 'Gameplay', 'WeaponTimedAI', 'ai', 110)
WRIST = Preference(
    0x1fcae00, 0x100, 0x1fca100, 0x1fca200, 1, 'Gameplay', 'WristHeightFiring', 'ai', 120
)
SHOT = Preference(
    0x1d35800, 0x40, 0x1d34500, 0x1d34600, 1, 'Gameplay', 'UnlockedShotAssist', 'ai', 143
)
# Selection uses the unused second half of the shot-preference cache, which
# existing snapshot restore already clears. The settings remain independent.
PICK = Preference(
    0x1d35820, 0x10, 0x1d35900, 0x1d35a00, 1, 'Gameplay', 'ImprovedTargetSelection', 'ai', 152
)
PREFERENCES = {'fps': FPS, 'ai': AI, 'wrist': WRIST, 'shot': SHOT, 'pick': PICK}
ORIGINAL_STATE = 0x1fc2f00
ORIGINAL_STATE_SIZE = 0x100
ORIGINAL_LOADED = ORIGINAL_STATE + 104
ORIGINAL_VALUES = 0x43d510
ORIGINAL_VALUES_SIZE = 100
SHARED_ROOT = 0x1fc2a00
SHARED_SAVE = 0x1fc2d00
PATH_OFFSET = 64
AI_READ_OFFSET = 16
AI_WRITE_OFFSET = 20
FPS_READ_OFFSET = 28
FPS_WRITE_OFFSET = 32
AI_DRAW = 0x1e39600
AI_EVENT = 0x1e39800
AI_ACCEPT = 0x1e39a00
AI_CLOSE = 0x1e39a80
FPS_DRAW = 0x1f75900
FPS_ACCEPT = 0x1f75d00
FPS_CLOSE = 0x1f75d80
WRIST_DRAW = 0x1fca400
WRIST_EVENT = 0x1fca700
WRIST_ACCEPT = 0x1fca900
WRIST_CLOSE = 0x1fca950

# Calls among helpers, not a blanket topological installation schedule. Drawing
# initializes the pending values once per opening; Cancel discards them on close.
INITIALIZATION = {'original25': ('fps', ), 'fps': (), 'ai': (), 'wrist': ('ai', ), 'shot': ('ai', ), 'pick': ('ai', )}
ACCEPT_ORDER = ('pick', 'shot', 'wrist', 'ai', 'fps', 'original25')
CLOSE_ORDER = ('pick', 'shot', 'wrist', 'ai', 'fps')


def restore_ranges(revision):
    """Choose transient preference fields to clear for a supported snapshot format.

    Clear caches and UI scratch, then set ORIGINAL_LOADED=1 separately. Keep
    captured original settings, simulation clocks and AI weapon tables intact.
    Same-window campaign changes retain these caches because their paths refer
    to the shared installation root.
    """
    regions = [
        (FPS.state, FPS.size), (AI.state, AI.size), (ORIGINAL_STATE, ORIGINAL_STATE_SIZE),
        (WRIST.state, WRIST.size)
    ]
    if revision >= SHOT.since:
        regions.append((SHOT.state, SHOT.size))
    return tuple(regions)
