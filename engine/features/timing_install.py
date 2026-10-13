"""One checked installation of actor/effect clocks from original hook preimages.

All authoring is in maintained timing modules. Reset entries and the aircraft
trampoline deliberately select their final owners once; no intermediate hooks
or retry-operand patches are installed. Frame callbacks are explicit providers.
Later route recovery wraps the two shared reset entries through its own checked
contract; it does not own these tables or duplicate their reset implementations.
"""
from dataclasses import dataclass
from features import actor_timing as actor, effect_timing as effects, frame_clock

PARTS = ('drone', 'aircraft', 'gates', 'perception', 'avoidance', 'nozzles', 'idle', 'pose')
# The only intentional repeated spans inside this family. Every replacement
# must match the prior generator's complete span and its checked preimage.
SHARED_ENTRIES = frozenset((0x249b2c, 0x24b52d, 0x253b56, actor.AIRCRAFT_ORIGINAL))


@dataclass(frozen=True)
class Plan:
    pieces: tuple
    hooks: tuple
    clock: tuple
    mutable: tuple

    @property
    def ranges(self):
        return tuple((a, a + len(b)) for a, b in self.pieces)


def owned_parts():
    merged = {}
    hooks = {}
    state = []
    for part in PARTS:
        for a, b in actor._HOOKS[part].items():
            if a < 0x354000:
                hooks.setdefault(a, b)
        for a, b in actor.part_bodies(part):
            if a in merged:
                if (
                    a not in SHARED_ENTRIES or actor._SHARED[part].get(a) != merged[a]
                    or len(b) != len(merged[a])
                ):
                    raise ValueError('Undeclared actor timing replacement: ' + hex(a))
            elif any(a < start + len(old) and start < a + len(b) for start, old in merged.items()):
                raise ValueError('Partial actor timing overlap')
            merged[a] = b
        state.extend(actor._STATE[part])
    for a, b in effects.bodies() + [(effects.STATE, bytes(effects.LIMIT - effects.STATE))]:
        if any(a < start + len(old) and start < a + len(b) for start, old in merged.items()):
            raise ValueError('Effect/actor timing overlap')
        merged[a] = b
    hooks.update(effects.SITES)
    state.append((effects.STATE, effects.LIMIT - effects.STATE))
    return tuple(sorted(merged.items())), tuple(sorted(hooks.items())), tuple(state)


def prepare(callbacks):
    pieces, hooks, state = owned_parts()
    return Plan(pieces, hooks, tuple(frame_clock.bodies(callbacks)), state)


def install(plan, write, read):
    from features.input_views import _verify, _install
    _verify(plan.clock, read)
    mutable = {a for a, n in plan.mutable}
    if all(bytes(read(a, len(b))) == b for a, b in plan.pieces if a not in mutable):
        return dict(already_installed=True, ranges=[])
    return _install(plan.pieces, dict(plan.hooks), write, read)


def verify(plan, read):
    from features.input_views import _verify
    _verify(plan.clock, read)
    mutable = {a for a, n in plan.mutable}
    return _verify([(a, b) for a, b in plan.pieces if a not in mutable], read)
