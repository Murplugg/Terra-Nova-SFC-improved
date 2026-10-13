"""Cooperative original system-clock delivery and displayed-frame boundaries.

The host supplies a virtual elapsed clock and frame callbacks explicitly.
Only the identified original system-clock callback is delivered; this does
not simulate hardware IRQs or add arbitrary timer callbacks.
"""
from dataclasses import dataclass
from patch_support import asm

TICK = 0x1d18200
WAIT = 0x1d18400
FRAME = 0x1d18500
S = 0x1d0f300


def _emit(write, *, resynchronize=True):
    delayed = "clock_start" if resynchronize else "clock_fault"
    write(
        TICK,
        asm(
            TICK, (
                f"\n pushfd;"
                f"pushad;"
                f"\n cmp dword ptr [0x36d1a4],2;"
                f"jne clock_inactive;"
                f"cmp dword ptr [0x36d164],0x2eb220;"
                f"jne clock_fault;"
                f"\n mov ebx,[0x35f8ec];"
                f"test ebx,ebx;"
                f"jz clock_fault;"
                f"cmp ebx,10000;"
                f"ja clock_fault;"
                f"\n cmp ebx,[{S+8}];"
                f"jne clock_start;"
                f"mov ecx,eax;"
                f"sub ecx,[{S}];"
                f"mov [{S}],eax;"
                f"cmp ecx,1000;"
                f"ja {delayed};"
                f"\n mov eax,ecx;"
                f"mul ebx;"
                f"add eax,[{S+4}];"
                f"adc edx,0;"
                f"mov ecx,1000;"
                f"div ecx;"
                f"mov [{S+4}],edx;"
                f"mov [{S+12}],eax;"
                f"\n clock_tick_loop:cmp dword ptr [{S+12}],0;"
                f"je clock_done;"
                f"dec dword ptr [{S+12}];"
                f"inc dword ptr [{S+16}];"
                f"push 0;"
                f"call 0x2eb220;"
                f"add esp,4;"
                f"jmp clock_tick_loop;"
                f"\n clock_start:mov [{S}],eax;"
                f"mov [{S+8}],ebx;"
                f"mov dword ptr [{S+4}],0;"
                f"jmp clock_done;"
                f"\n clock_inactive:mov dword ptr [{S+8}],0;"
                f"\n clock_done:popad;"
                f"popfd;"
                f"ret;"
                f"\n clock_fault:mov eax,0xff00;"
                f"int 0x21;"
                f"\n "
            )
        )
    )
    # Keep the original wait comparison and flags; service Windows between polls.
    write(0x2deacd, asm(0x2deacd, f'jmp {WAIT}') + b'\x90' * 3)
    write(
        WAIT,
        asm(
            WAIT, (
                "push eax;"
                "call 0x1d18000;"
                "pop eax;"
                "cmp eax,[0x35f8dc];"
                "ja 0x2deacd;"
                "jmp 0x2dead5;"
            )
        )
    )
    # Main dispatch continues to present and service time once the wait has ended.
    write(0x2de888, asm(0x2de888, f'jmp {FRAME}'))
    write(
        FRAME,
        asm(
            FRAME, (
                "pushfd;"
                "pushad;"
                "call 0x1d18000;"
                "popad;"
                "popfd;"
                "push ebx;"
                "push ecx;"
                "push edx;"
                "push esi;"
                "push edi;"
                "jmp 0x2de88d;"
            )
        )
    )


SERVICE = 0x1d18000
FRAME_END = 0x1d2e300
SITES = {
    0x2deacd: bytes.fromhex('3b05dcf8350077f8'),
    0x2de888: bytes.fromhex('5351525657'),
    0x2dead5: bytes.fromhex('83c4045f5e')
}


@dataclass(frozen=True)
class Callbacks:
    frame_begin: int
    frame_end: int
    time_ms: int
    pump: int

    def __post_init__(self):
        slots = (self.frame_begin, self.frame_end, self.time_ms)
        if any(type(a) is not int or not 0x11000 <= a <= 0x1fffffc or a % 4 for a in slots):
            raise ValueError('Invalid clock callback slot')
        if len(set(slots)) != 3:
            raise ValueError('Clock callback slots overlap')
        if type(self.pump) is not int or not 0x11000 <= self.pump < 0x2000000:
            raise ValueError('Invalid host pump address')


def base_bodies(*, resynchronize=True):
    pieces = []
    _emit(lambda a, b: pieces.append((a, b)), resynchronize=resynchronize)
    return pieces


def service_body(callbacks):
    return asm(
        SERVICE, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"call {callbacks.pump};"
            f"call dword ptr [{callbacks.time_ms}];"
            f"call {TICK};"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )


def bodies(callbacks, *, include_service=True):
    pieces = dict(base_bodies())
    pieces[FRAME] = asm(
        FRAME, (
            f"pushfd;"
            f"pushad;"
            f"call dword ptr [{callbacks.frame_begin}];"
            f"call {SERVICE};"
            f"popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x2de88d;"
        )
    )
    pieces[0x2dead5] = asm(0x2dead5, f'jmp {FRAME_END}')
    pieces[FRAME_END] = asm(
        FRAME_END, (
            f"pushfd;"
            f"pushad;"
            f"call dword ptr [{callbacks.frame_end}];"
            f"popad;"
            f"popfd;"
            f"add esp,4;"
            f"pop edi;"
            f"pop esi;"
            f"jmp 0x2deada;"
        )
    )
    if include_service:
        pieces[SERVICE] = service_body(callbacks)
    return list(pieces.items())


def install(write, read, callbacks, *, include_service=True):
    from features.input_views import _install
    pieces = bodies(callbacks, include_service=include_service)
    return _install(pieces, SITES, write, read, cold_state=((S, 20), ))


def verify(read, callbacks, *, include_service=True):
    from features.input_views import _verify
    return _verify(bodies(callbacks, include_service=include_service), read)


# Smacker digital progress follows consumed PCM, not time since first queue.
MOVIE_SITE = 0x2febc0

MOVIE_CODE = 0x1e3f800

MOVIE_ORIGINAL = bytes.fromhex('565589e58b750c')


def movie_body():
    # Keep original refilling and clock/window pumping. Its wall-time estimate can
    # otherwise outrun delayed audio and clamp repeatedly at each 0.28-second block.
    # 50+68 is cumulative queued PCM. Miles lengths minus positions are outstanding
    # PCM in its two streaming buffers. Consumed PCM includes the native output
    # queue's bounded lead (four 1024-frame buffers at 48 kHz), not its wall stalls.
    return asm(
        MOVIE_CODE, (
            "push esi;"
            "push ebp;"
            "mov ebp,esp;"
            "mov esi,[ebp+12];"
            "\n  call 0x2fec00;"
            "call dword ptr [0x364684];"
            "\n  mov edx,[esi+0x38];"
            "mov eax,[esi+0x50];"
            "add eax,[esi+0x68];"
            "\n  mov ecx,[edx+0x10];"
            "sub ecx,[edx+0x18];"
            "jae remain0;"
            "xor ecx,ecx;"
            "\n  remain0:mov ebx,[edx+0x14];"
            "sub ebx,[edx+0x1c];"
            "jae remain1;"
            "xor ebx,ebx;"
            "\n  remain1:add ecx,ebx;"
            "sub eax,ecx;"
            "jae done;"
            "xor eax,eax;"
            "\n  done:pop ebp;"
            "pop esi;"
            "ret 4;"
        )
    )


def movie_bodies():
    return [
        (MOVIE_CODE, movie_body()),
        (MOVIE_SITE, asm(MOVIE_SITE, f'jmp {MOVIE_CODE}') + b'\x90' * 2)
    ]
