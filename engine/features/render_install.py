"""Install the renderer into a build image after validating all affected spans.

The plan records the expected bytes, replacement bytes and owned storage. Every
dependency is checked before writes begin. Runtime snapshot restoration has its
own path because it must preserve live buffers and game state.
"""
from dataclasses import dataclass
from . import render_arena as arena
from patch_support import asm

IMAGE_END = 0x2000000
STARTUP_HOOK = asm(arena.SITE, f'jmp {arena.CODE}')


def checked(read, address, size):
    if not 0x11000 <= address < address + size <= IMAGE_END:
        raise ValueError('Renderer installation span outside image')
    data = bytes(read(address, size))
    if len(data) != size:
        raise ValueError('Truncated renderer installation input at ' + hex(address))
    return data


@dataclass(frozen=True)
class Patch:
    address: int
    before: bytes
    after: bytes


@dataclass(frozen=True)
class Plan:
    patches: tuple

    def __post_init__(self):
        if type(self.patches) is not tuple or not self.patches:
            raise ValueError('Renderer installation requires immutable patches')
        spans = []
        startup = []
        for p in self.patches:
            if (
                not isinstance(p, Patch) or type(p.before) is not bytes
                or type(p.after) is not bytes
            ):
                raise ValueError('Renderer installation requires immutable byte spans')
            if not p.after or len(p.before) != len(p.after):
                raise ValueError('Renderer installation span lengths differ')
            if not 0x11000 <= p.address < p.address + len(p.after) <= IMAGE_END:
                raise ValueError('Renderer installation span outside image')
            spans.append((p.address, p.address + len(p.after)))
            if p.address == arena.SITE:
                startup.append(p)
        ordered = sorted(spans)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Overlapping renderer installation spans')
        if (
            len(startup) != 1 or startup[0].after != STARTUP_HOOK
            or startup[0].before[:1] != b'\x68'
        ):
            raise ValueError('Renderer installation requires its exact startup hook')

    def pieces(self):
        return [(p.address, p.after) for p in self.patches]


def prepare(integration, read, imports):
    """Generate once, capture full preimages and reject overlapping output spans."""
    pieces = arena.bodies(integration, read, imports)
    return Plan(tuple(Patch(a, checked(read, a, len(b)), bytes(b)) for a, b in pieces))


def installed(read):
    # A matching hook is only a dispatch hint. verify checks every owned span.
    return checked(read, arena.SITE, len(STARTUP_HOOK)) == STARTUP_HOOK


def verify(plan, read):
    for p in plan.patches:
        if checked(read, p.address, len(p.after)) != p.after:
            raise ValueError('Renderer installed bytes differ at ' + hex(p.address))
    return True


def install(plan, write, read):
    """Validate all preimages before writing; an exact reinstall is a no-op.

    A write callback failure is propagated, not rolled back. The caller owns
    its offline output image and must discard it after such a failure.
    """
    if installed(read):
        verify(plan, read)
        return dict(ranges=[], already_installed=True)
    for p in plan.patches:
        if checked(read, p.address, len(p.before)) != p.before:
            raise ValueError('Renderer predecessor differs at ' + hex(p.address))
    for p in plan.patches:
        write(p.address, p.after)
    return dict(
        ranges=[(p.address, p.address + len(p.after)) for p in plan.patches],
        arena=[arena.BASE, arena.SIZE],
        resolution=[arena.W, arena.H]
    )


def predecessor_view(plan, image):
    """Return a verified diagnostic shadow; never change the supplied image."""
    if len(image) != IMAGE_END:
        raise ValueError('Renderer shadow requires a complete native image')
    verify(plan, lambda a, n: image[a:a + n])
    shadow = bytearray(image)
    for p in plan.patches:
        shadow[p.address:p.address + len(p.before)] = p.before
    return shadow
