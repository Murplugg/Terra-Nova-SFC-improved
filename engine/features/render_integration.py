"""Integrate the 1280x960 world, maps and cameras with the software renderer.

The caller owns the rendering arena for the process lifetime. Images and tables
have guard bytes. The original game heap and 8-MiB VBE buffer keep their existing
ownership. Snapshot capture and restore include the arena and its layout.
"""
import struct
from features import hud as h, maps, hud_install, input_views
from features import target_picking as pick
from features import render_views as views
from features import render_inputs
import foundation_weather as weather
from patch_support import asm

from features.render_arena import Layout, W, H, CAP

MODE_IO = 0x1f98000


class Integration(Layout):

    def __init__(self, base):
        super().__init__(base)
        self.nextcode = base + 0xc00000
        self.writes = []
        self.sources = {}
        self.entries = {}

    def emit(self, name, s, site=None):
        a = self.nextcode
        b = views.assemble(a, s)
        assert len(b) < 0x2000, (name, len(b))
        self.nextcode += (len(b) + 255) & ~255
        assert self.nextcode < self.base + 0xe00000
        self.writes.append((a, b))
        self.entries[name] = a
        self.sources[name] = s
        if site is not None:
            self.writes.append((site, asm(site, f'jmp {a}')))
        return a

    def word(self, a, v):
        self.writes.append((a, struct.pack('<I', v)))

    def bind(self, read):
        return render_inputs.bind(
            read,
            self,
            tuple(weather.ROW_TABLES.values()), ((weather.SKY_D, 'edx'), (weather.SKY_C, 'ecx')),
            old_effect=weather.EFFECT,
            stats=weather.STATS
        )

    def build(self, ram=None, *, bindings=None):
        if bindings is None:
            if ram is None:
                raise ValueError('Renderer requires an image or bound providers')
            bindings = self.bind(lambda address, size: ram[address:address + size])
        elif ram is not None:
            raise ValueError('Supply either an image or bound renderer providers')
        st = self.state
        mode = asm(MODE_IO, views.mode())
        assert len(mode) < 0x100
        self.writes.append((MODE_IO, mode))
        ctor = self.emit(
            'original_constructor',
            ("push esi;"
             "push edi;"
             "push ebp;"
             "sub esp,12;"
             "jmp 0x29e836;")
        )
        self.emit(
            'constructor_invalidate', (
                f"pushfd;"
                f"cmp eax,{h.CTX};"
                f"jne done;"
                f"mov dword ptr [{st}],1;"
                f"done:popfd;"
                f"jmp {ctor};"
            ), 0x29e830
        )
        self.emit('world', views.world(self, h, ctor, MODE_IO), h.WORLD)
        # Target rectangles stay on the logical HUD; renderer quads stay physical.
        self.emit('target_convert', pick.rectangle_source(pick.Profile.HD960), h.CONVERT)
        self.emit('pick', pick.quad_source(pick.Profile.HD960), h.PICK)
        # Map has its own enlarged image. Camera source buffers remain unchanged.
        self.emit('map_entry', views.map_entry(self, maps), maps.ENTRY)
        self.emit('map_background', views.map_background(self, maps), maps.BACKGROUND)
        map_prepare = self.emit('map_prepare', views.map_prepare(self, h))
        slot = self.slot_merger()
        self.emit('camera_merge', views.camera_merge(h, slot), h.MERGE)
        self.emit('map_merge', views.map_merge(maps, slot, self), maps.MERGE)
        s = (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"cmp dword ptr [0x9aa0e8],0;"
            f"jne done;"
            f"\n         mov dword ptr [0x9aa0e8],1;"
            f"inc byte ptr [0x447115];"
            f"\n         mov esi,[0x446f78];"
            f"mov edi,{h.CACHE};"
            f"mov ecx,32000;"
            f"rep movsd;"
            f"call {h.PREPARE};"
            f"call {map_prepare};"
            f"call {h.COVER};"
            f"\n         cmp dword ptr [{h.READY}],0;"
            f"je hud;"
            f"\n         mov esi,{self.pixels};"
            f"mov edi,[{h.DATA+4}];"
            f"imul edi,edi,{W};"
            f"add edi,[{h.DATA}];"
            f"add edi,{self.frame};"
            f"\n         mov ebp,[{h.DATA+20}];"
            f"mov ebx,[{h.DATA+16}];"
            f"mov edx,{W};"
            f"sub edx,ebx;"
            f"\n         worldrow:mov ecx,ebx;"
            f"shr ecx,2;"
            f"rep movsd;"
            f"mov ecx,ebx;"
            f"and ecx,3;"
            f"rep movsb;"
            f"add edi,edx;"
            f"dec ebp;"
            f"jnz worldrow;"
            f"\n         hud:mov esi,{h.CACHE};"
            f"mov edi,{self.frame};"
            f"xor ebp,ebp;"
            f"sub esp,8;"
            f"mov dword ptr [esp],0;"
            f"\n         row:mov eax,[esp];"
            f"mov edx,[{self.yedges}+eax*4+4];"
            f"sub edx,[{self.yedges}+eax*4];"
            f"mov [esp+4],edx;"
            f"xor ebx,ebx;"
            f"\n         pixel:movzx eax,byte ptr [esi];"
            f"test al,al;"
            f"jnz opaque;"
            f"cmp dword ptr [{h.READY}],0;"
            f"je opaque;"
            f"\n         cmp ebp,[{h.DATA+4}];"
            f"jb opaque;"
            f"cmp ebp,[{h.DATA+12}];"
            f"jae opaque;"
            f"\n         cmp ebx,[{h.DATA}];"
            f"jb opaque;"
            f"cmp ebx,[{h.DATA+8}];"
            f"jae opaque;"
            f"\n         cmp byte ptr [esi+{h.MASK-h.CACHE}],0;"
            f"jne next;"
            f"\n         opaque:imul eax,eax,0x01010101;"
            f"mov [edi],eax;"
            f"mov [edi+{W}],eax;"
            f"\n         cmp dword ptr [esp+4],3;"
            f"jne next;"
            f"mov [edi+{2*W}],eax;"
            f"\n         next:inc esi;"
            f"add edi,4;"
            f"add ebx,4;"
            f"cmp ebx,{W};"
            f"jb pixel;"
            f"\n         mov eax,[esp+4];"
            f"add ebp,eax;"
            f"dec eax;"
            f"imul eax,eax,{W};"
            f"add edi,eax;"
            f"\n         inc dword ptr [esp];"
            f"cmp dword ptr [esp],400;"
            f"jb row;"
            f"\n         add esp,8;"
            f"call {h.MERGE};"
            f"call {maps.MERGE};"
            f"mov esi,{self.frame};"
            f"mov edi,{self.screen};"
            f"mov ecx,{W*H//4};"
            f"rep movsd;"
            f"\n         mov dword ptr [{st+24}],1;"
            f"inc dword ptr [{st+28}];"
            f"\n         dec byte ptr [0x447115];"
            f"mov dword ptr [0x9aa0e8],0;"
            f"\n         done:popad;"
            f"popfd;"
            f"ret;"
        )
        self.emit('compose', s, h.COMPOSE)
        # Mouse IRQ restores only its previous rectangle from completed output.
        self.emit('cursor', views.cursor(self, h), h.PAINT)
        self.writes.append((self.cols, struct.pack('<1280H', *(x // 4 for x in range(W)))))
        self.writes.append(
            (self.rows, struct.pack('<960I', *((y * 5 // 12) * 320 for y in range(H))))
        )
        self.writes.append(
            (self.yedges, struct.pack('<401I', *((y * 12 + 4) // 5 for y in range(401))))
        )
        self.weather_point()
        # Keep the 800-pixel effect handlers intact. Fork only the drawing
        # helpers used on the new primary canvas; original RNG/commands/timers
        # and camera handlers retain their existing code and shared state.
        keys = ('ENTRY', 'DRAW', 'RECT', 'NOISE', 'LINES')
        start = self.nextcode
        addresses = {k: start + n * 0x400 for n, k in enumerate(keys)}
        self.nextcode = start + 0x1400
        pieces = h.damage_bodies(
            asm,
            entry_address=addresses['ENTRY'],
            draw_address=addresses['DRAW'],
            rect_address=addresses['RECT'],
            noise_address=addresses['NOISE'],
            lines_address=addresses['LINES'],
            pixels=self.pixels,
            width=W,
            height=H
        )
        self.writes.extend((a, b) for a, b in pieces if a in addresses.values())
        entry = self.emit(
            'damage_gate', (
                f"""pushfd;"""
                f"""cmp dword ptr [{h.CANVAS}],{self.pixels};"""
                f"""je large;"""
                f"""popfd;"""
                f"""jmp {h.DAMAGE_ENTRY};"""
                f"""large:popfd;"""
                f"""jmp {addresses["ENTRY"]};"""
            )
        )
        self.writes.append((h.DAMAGE_SITE, asm(h.DAMAGE_SITE, f'call {entry}')))
        newlabel = self.nextcode
        self.nextcode += 0x400
        self.writes.extend(h.nav_bodies(asm, label=newlabel, pixels=self.pixels))
        entry = self.emit(
            'nav_gate', (
                f"pushfd;"
                f"cmp dword ptr [{h.CANVAS}],{self.pixels};"
                f"je large;"
                f"popfd;"
                f"jmp {h.NAV_LABEL};"
                f"large:popfd;"
                f"jmp {newlabel};"
            )
        )
        self.writes.append((h.NAV_TEXT, asm(h.NAV_TEXT, f'call {entry}')))
        # The planet sprite cap was expressed in 800-pixel output units.
        # Increase it only on the larger primary view, retaining camera sizes.
        s = (
            f"cmp dword ptr [0x44b1a0],{h.CANVAS};"
            f"jne old;"
            f"\n         cmp dword ptr [{h.CANVAS}],{self.pixels};"
            f"jne old;"
            f"\n         cmp ebp,0x40000;"
            f"jle aspect;"
            f"cmp ecx,0x40000;"
            f"jle aspect;"
            f"mov ebp,0x40000;"
            f"mov ecx,ebp;"
            f"\n         aspect:push eax;"
            f"push edx;"
            f"push ebx;"
            f"mov eax,ecx;"
            f"mov ebx,6;"
            f"imul ebx;"
            f"\n         mov ebx,5;"
            f"idiv ebx;"
            f"mov ecx,eax;"
            f"pop ebx;"
            f"pop edx;"
            f"pop eax;"
            f"jmp 0x2a81c8;"
            f"\n         old:jmp {input_views.SKY};"
        )
        self.emit('planet', s, 0x2a81a2)
        edits = {
            0x29e3ef: self.clip,
            0x29e210: self.clip - 4,
            0x29e24c: self.clip - 4,
            0x29e374: self.clip - 4,
            0x2a84ae: self.clip2,
            0x2a86ad: self.clip2,
            0x2a84b3: 1600 * 4,
            0x2a87b7: self.effect,
            0x2b22f6: self.effect
        }
        edits.update(bindings.edits)
        for a, v in edits.items():
            self.word(a, v)
        # Override only the presenter's source image. VBE queries, movie buffers
        # and input's logical range keep their established contract.
        site = bindings.presenter
        self.emit(
            'present', (
                f"pushfd;"
                f"cmp dword ptr [0x1d0b000],0x103;"
                f"jne old;"
                f"\n         cmp dword ptr [0x446f80],0x01900140;"
                f"jne old;"
                f"cmp dword ptr [{st+24}],1;"
                f"jne old;"
                f"\n         mov eax,{self.screen};"
                f"mov edx,{W};"
                f"mov dword ptr [0x1d1d010],{W};"
                f"mov dword ptr [0x1d1d014],{H};"
                f"\n         old:popfd;"
                f"mov [0x1d1d00c],eax;"
                f"jmp {site+5};"
            ), site
        )
        return self.writes

    def slot_merger(self):
        # Source pixel edge tables are derived per cell from each slot's actual
        # dimensions; cameras retain old resolution, maps use full output size.
        # Stack: x,y,source x/y edges,destination row count,source row count.
        s = (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"sub esp,48;"
            f"\n         mov dword ptr [esp+4],0;"
            f"\n         row:mov eax,[esp+4];"
            f"imul eax,[ebp+52];"
            f"xor edx,edx;"
            f"div dword ptr [ebp+36];"
            f"mov [esp+16],eax;"
            f"\n         mov eax,[esp+4];"
            f"inc eax;"
            f"imul eax,[ebp+52];"
            f"xor edx,edx;"
            f"div dword ptr [ebp+36];"
            f"sub eax,[esp+16];"
            f"mov [esp+20],eax;"
            f"\n         mov eax,[esp+4];"
            f"add eax,[ebp+28];"
            f"mov edx,[{self.yedges}+eax*4];"
            f"mov [esp+24],edx;"
            f"\n         mov ecx,[{self.yedges}+eax*4+4];"
            f"sub ecx,edx;"
            f"mov [esp+28],ecx;"
            f"\n         mov dword ptr [esp],0;"
            f"\n         pixel:mov eax,[esp+4];"
            f"imul eax,[ebp+32];"
            f"add eax,[esp];"
            f"mov edx,[ebp+64];"
            f"cmp byte ptr [edx+eax],0;"
            f"je next;"
            f"\n         mov edx,[ebp+60];"
            f"mov cl,[edx+eax];"
            f"mov eax,[esp+4];"
            f"imul eax,eax,320;"
            f"add eax,[ebp+20];"
            f"add eax,[esp];"
            f"\n         cmp byte ptr [eax+{h.CACHE}],cl;"
            f"jne next;"
            f"mov [esp+44],eax;"
            f"\n         mov eax,[esp];"
            f"imul eax,[ebp+48];"
            f"xor edx,edx;"
            f"div dword ptr [ebp+32];"
            f"mov [esp+8],eax;"
            f"\n         mov eax,[esp];"
            f"inc eax;"
            f"imul eax,[ebp+48];"
            f"xor edx,edx;"
            f"div dword ptr [ebp+32];"
            f"sub eax,[esp+8];"
            f"mov [esp+12],eax;"
            f"\n         mov dword ptr [esp+32],0;"
            f"\n         scan:mov eax,[esp+32];"
            f"imul eax,[esp+20];"
            f"xor edx,edx;"
            f"div dword ptr [esp+28];"
            f"add eax,[esp+16];"
            f"imul eax,[ebp+48];"
            f"add eax,[esp+8];"
            f"add eax,[ebp+56];"
            f"mov esi,eax;"
            f"\n         mov edi,[esp+24];"
            f"add edi,[esp+32];"
            f"imul edi,edi,{W};"
            f"mov eax,[esp];"
            f"add eax,[ebp+24];"
            f"lea edi,[edi+eax*4+{self.frame}];"
            f"\n         xor ecx,ecx;"
            f"\n         sample:mov eax,ecx;"
            f"imul eax,[esp+12];"
            f"shr eax,2;"
            f"mov al,[esi+eax];"
            f"stosb;"
            f"inc ecx;"
            f"cmp ecx,4;"
            f"jb sample;"
            f"\n         inc dword ptr [esp+32];"
            f"mov eax,[esp+32];"
            f"cmp eax,[esp+28];"
            f"jb scan;"
            f"\n         mov eax,[esp+44];"
            f"mov byte ptr [eax+{h.CACHE}],0;"
            f"\n         next:inc dword ptr [esp];"
            f"mov eax,[esp];"
            f"cmp eax,[ebp+32];"
            f"jb pixel;"
            f"\n         inc dword ptr [esp+4];"
            f"mov eax,[esp+4];"
            f"cmp eax,[ebp+36];"
            f"jb row;"
            f"\n         add esp,48;"
            f"popad;"
            f"popfd;"
            f"ret;"
        )
        return self.emit('slot', s)

    def weather_point(self):
        # Logical weather coordinates relative to the active view, including
        # small team cameras. Use that view's own width/height for each cell.
        s = (
            f"cmp dword ptr [0x44b1a0],{h.CANVAS};"
            f"jne original;"
            f"\n         pushfd;"
            f"pushad;"
            f"cld;"
            f"sub esp,24;"
            f"mov [esp+20],eax;"
            f"movsx edx,dx;"
            f"movsx ebx,bx;"
            f"\n         test edx,edx;"
            f"js done;"
            f"test ebx,ebx;"
            f"js done;"
            f"mov esi,[{h.LOW+28}];"
            f"\n         movzx ecx,word ptr [esi+8];"
            f"cmp edx,ecx;"
            f"jae done;"
            f"movzx ebp,word ptr [{h.CANVAS+8}];"
            f"\n         mov eax,edx;"
            f"inc eax;"
            f"imul eax,ebp;"
            f"push edx;"
            f"xor edx,edx;"
            f"div ecx;"
            f"mov [esp+8],eax;"
            f"pop eax;"
            f"\n         imul eax,ebp;"
            f"xor edx,edx;"
            f"div ecx;"
            f"mov [esp],eax;"
            f"sub [esp+4],eax;"
            f"\n         movzx ecx,word ptr [esi+10];"
            f"cmp ebx,ecx;"
            f"jae done;"
            f"movzx ebp,word ptr [{h.CANVAS+10}];"
            f"\n         mov eax,ebx;"
            f"inc eax;"
            f"imul eax,ebp;"
            f"xor edx,edx;"
            f"div ecx;"
            f"mov [esp+12],eax;"
            f"\n         mov eax,ebx;"
            f"imul eax,ebp;"
            f"xor edx,edx;"
            f"div ecx;"
            f"mov [esp+8],eax;"
            f"sub [esp+12],eax;"
            f"\n         movzx ebx,word ptr [{h.CANVAS+12}];"
            f"imul eax,ebx;"
            f"add eax,[esp];"
            f"add eax,[{h.CANVAS}];"
            f"mov edi,eax;"
            f"\n         mov edx,[esp+12];"
            f"mov eax,[esp+20];"
            f"\n         row:mov ecx,[esp+4];"
            f"push edi;"
            f"rep stosb;"
            f"pop edi;"
            f"add edi,ebx;"
            f"dec edx;"
            f"jnz row;"
            f"\n         done:add esp,24;"
            f"popad;"
            f"popfd;"
            f"ret;"
            f"original:jmp 0x2fad20;"
        )
        self.emit('weather', s, h.POINT)

    def install(self, l):
        ram = l.dump()
        self.build(ram)
        for a, b in self.writes:
            l.p.write(a, b)
        for name, a, n in self.regions:
            for edge in (a - 256, a + n):
                l.p.write(edge, b'\xa5' * 256)
        l.p.write(self.state, bytes(128))
        l.p.write(h.READY, bytes(4))
        l.p.write(0x9af5e8, bytes(4))
        l.p.write(maps.SLOT, bytes(4))
        l.p.write(self.map_slots, bytes(4 * 512))
        return self

    def guards(self, p):
        for name, a, n in self.regions:
            for edge in (a - 256, a + n):
                assert p.read(edge, 256) == b'\xa5' * 256, (name, hex(edge))
        assert hud_install.validate_guards(p.read, maps.BUFFERS) == 24
        return len(self.regions) * 2 + 24
