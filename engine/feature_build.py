"""Build the accepted runtime from named features and verified original inputs."""
import hashlib, importlib, time
from feature_plan import PLAN, validate, FOUNDATION_SHA, OUTPUT_SHA, REVISION
from patch_support import asm

START = 0x11000


def owned_component(name, write, ram, context):
    """Connect each feature to its declared inputs and checked installation routine."""
    from features import ai_response, ai_firing, ai_cadence, cameras, input_views, audio_safety, weapon_timing
    from features import actor_timing, terrain_raster, sprite_variation, campaign_switch, target_picking
    from features import terrain_distance, hud, hud_install, hud_overlays, modal_ui, maps, effect_timing, projectiles
    read = lambda a, n: ram[a:a + n]
    original = lambda a, n: bytes(context['original'][a:a + n])
    if name == 'ballistic-safety':
        from features import ballistic_safety
        helper = importlib.import_module('ballistic_safety_code')
        options = dict(entry=helper.ENTRY, regions=helper.REGIONS)
        ballistic_safety.install(write, read, **options)
        if not ballistic_safety.verify(read, **options):
            raise ValueError('Ballistic helper verification failed')
        return
    if name == 'smoke-clouds':
        from features import smoke
        helper = importlib.import_module('collision_smoke')
        prior = importlib.import_module('collision_mobile')
        options = dict(entry=helper.ENTRY, regions=helper.REGIONS, mobile_entry=prior.ENTRY)
        smoke.install(write, read, **options)
        if not smoke.verify(read, **options):
            raise ValueError('Smoke helper verification failed')
        return
    if name in ('static-contacts', 'mobile-contacts'):
        # Compiled helpers are generated from checked C and owner resources by
        # build_helpers. Pass their outputs explicitly to the ray feature.
        def compiled(module_name):
            module = importlib.import_module(module_name)
            return module.ENTRY, tuple(module.REGIONS)

        if name == 'static-contacts':
            entry, regions = compiled('collision_cannon')
            options = dict(mesh_entry=entry, mesh_regions=regions)
            projectiles.install_static_contacts(write, read, **options)
            projectiles.verify_static_contacts(read, **options)
        else:
            options = {
                key: compiled(module)
                for key, module in (
                    ('vehicle', 'collision_vehicle'), ('pba', 'collision_pba'),
                    ('mobile', 'collision_mobile')
                )
            }
            projectiles.install_mobile_contacts(write, read, **options)
            projectiles.verify_mobile_contacts(read, **options)
        return
    if name == 'effect-storage':
        source = context['original_executable']
        effect_timing.pool_install(write, read, source, cold=True)
        effect_timing.pool_verify(read, source)
        return
    surface_paths = (
        dict(
            span_audio_path=(context['root'] / 'native-v100/tn-audio.dll').resolve(),
            movie_audio_path=(context['root'] / 'native-v101/tn-audio.dll').resolve()
        ) if name == 'terrain-surfaces' else {}
    )
    bindings = {
        'enemy-outfitting-click': (input_views.outfit_install, input_views.outfit_verify, read, {}, {}),
        'weapon-readiness': (weapon_timing.readiness_install, weapon_timing.readiness_verify, read, {}, {}),
        'sound-allocation': (audio_safety.install, audio_safety.verify, read, {}, {}),
        'static-instance-storage':
        (terrain_distance.instance_install, terrain_distance.instance_verify, read, {}, {}),
        'hit-investigation':
        (ai_response.investigate_install, ai_response.investigate_verify, read, {}, {}),
        'pose-repair':
        (actor_timing.pose_guard_install, actor_timing.pose_guard_verify, read, {}, {}),
        'storm-clock': (effect_timing.storm_install, effect_timing.storm_verify, read, {}, {}),
        'deployable-contacts':
        (projectiles.deploy_install, projectiles.deploy_verify, read, {}, {}),
        'panel-compositor': (hud_install.install_fast, hud_install.verify_fast, ram, {}, {}),
        'terrain-columns':
        (terrain_raster.column_install, terrain_raster.column_verify, read, {}, {}),
        'terrain-shading': (terrain_raster.shad_install, terrain_raster.shad_verify, read, {}, {}),
        'object-fog': (terrain_distance.fog_install, terrain_distance.fog_verify, read, {}, {}),
        'water-rows': (terrain_raster.water_install, terrain_raster.water_verify, read, {}, {}),
        'sky-rows': (terrain_raster.sky_install, terrain_raster.sky_verify, read, {}, {}),
        'volley-timing':
        (projectiles.install, projectiles.verify, read, dict(part='volley'), dict(part='volley')),
        'hud-infill': (
            hud_overlays.install, hud_overlays.verify, read, dict(imports=context['imports']),
            dict(imports=context['imports'])
        ),
        'sprite-variation':
        (sprite_variation.sprite_install, sprite_variation.sprite_verify, read, {}, {}),
        'damage-save-safety':
        (campaign_switch.safety_install, campaign_switch.safety_verify, read, {}, {}),
        'terrain-surfaces': (
            terrain_raster.surface_install, terrain_raster.surface_verify, read, surface_paths,
            surface_paths
        ),
        'scorch-variation':
        (sprite_variation.scorch_install, sprite_variation.scorch_verify, read, {}, {}),
        'target-names': (target_picking.names_install, target_picking.names_verify, read, {}, {}),
        'map-drag': (hud_overlays.drag_setup, hud_overlays.drag_verify, ram, {}, {}),
        'reticle-convergence':
        (projectiles.reticle_install, projectiles.reticle_verify, read, {}, {}),
        'beam-rendering': (effect_timing.beam_install, effect_timing.beam_verify, read, {}, {}),
        'hit-alert': (ai_response.alert_install, ai_response.alert_verify, read, {}, {}),
        'scenery-distance':
        (terrain_distance.scenery_install, terrain_distance.scenery_verify, read, {}, {}),
        'keyboard-state': (input_views.keyboard_install, input_views.keyboard_verify, read, {}, {}),
        'drone-controls': (input_views.drone_controls_install, input_views.drone_controls_verify, read, {}, {}),
        'renderer-lists':
        (terrain_distance.list_install, terrain_distance.list_verify, read, {}, {}),
        'railgun-provider': (ai_cadence.railgun_install, ai_cadence.railgun_verify, read, {}, {}),
        'fuel-contacts': (projectiles.fuel_install, projectiles.fuel_verify, read, {}, {}),
        'damage-display': (hud.damage_install, hud.damage_verify, read, {}, {}),
        'navigation-label': (hud.nav_install, hud.nav_verify, read, {}, {}),
        'quick-command-coverage': (hud.menu_install, hud.menu_verify, read, {}, {}),
        'rain-clock': (effect_timing.rain_install, effect_timing.rain_verify, read, {}, {}),
        'logical-panels': (
            hud_install.install_logical, hud_install.verify_logical, read, dict(original=original),
            dict(original=original)
        ),
        'view-distance': (terrain_distance.install, terrain_distance.verify, read, {}, {}),
        'logical-aspect': (input_views.aspect_install, input_views.aspect_verify, read, {}, {}),
        'detail-zoom': (input_views.zoom_install, input_views.zoom_verify, read, {}, {}),
        'native-cursor': (
            input_views.cursor_install, input_views.cursor_verify, read,
            dict(imports=context['imports']), dict(imports=context['imports'])
        ),
        'room-cursor': (
            input_views.room_install, input_views.room_verify, read,
            dict(imports=context['imports']), dict(imports=context['imports'])
        ),
        'compass-coverage': (hud_install.install_compass, hud_install.verify_compass, ram, {}, {}),
        'camera-heading': (cameras.heading_setup, cameras.heading_verify, ram, {}, {}),
        'camera-noise': (cameras.noise_setup, cameras.noise_verify, ram, {}, {}),
        'ai-firing-policy':
        (ai_firing.install, ai_firing.verify, read, dict(choice=False), dict(choice=False)),
        'ai-response': (ai_response.install, ai_response.verify, read, {}, {}),
        'ai-weapon-choice':
        (ai_firing.install, ai_firing.verify, read, dict(choice=True), dict(choice=True)),
        'ally-response': (ai_response.ally_install, ai_response.ally_verify, read, {}, {}),
        'ai-scenery-preview': (ai_firing.scenery_install, ai_firing.scenery_verify, read, {}, {}),
        'ai-cadence': (
            ai_cadence.install, ai_cadence.verify, read,
            dict(
                imports=context['imports'],
                gate_before=asm(ai_cadence.GATE_SITE, 'jmp 0x1fcd000') + b'\x90' * 6
            ), dict(imports=context['imports'])
        ),
        'route-recovery': (ai_response.recovery_install, ai_response.recovery_verify, read, {}, {}),
        'modal-dialog': (modal_ui.dialog_setup, modal_ui.dialog_verify, ram, {}, {}),
        'modal-tooltip': (modal_ui.tooltip_setup, modal_ui.tooltip_verify, ram, {}, {}),
        'map-centering': (maps.install_center, maps.verify_center, ram, {}, {}),
        'scenery-clipping': (
            terrain_distance.install_scenery_clipping, terrain_distance.verify_scenery_clipping,
            read, {}, {}
        ),
    }
    if name in ('map-persistence', 'panel-visibility'):
        if name == 'map-persistence':
            hud_install.install_visual(write, read)
            hud_install.verify_visual(ram, original)
        else:
            cameras.visibility_install(write, read)
            hud_install.verify_visibility(ram, original)
        return
    if name not in bindings:
        raise ValueError('Unknown maintained component: ' + name)
    install, verify, view, options, verification = bindings[name]
    install(write, view, **options)
    if not verify(view, **verification):
        raise ValueError('Maintained component verification failed: ' + name)


def runtime_labels(write, read, config):
    """Finalize six declared strings once, preserving snapshot-compatible slots."""
    from pathlib import Path
    root = Path(config['log_root']).parent
    pieces = []
    for address, filename in (
        (0x1d05000, 'services.bin'), (0x1d05400, 'stopped-memory.bin'),
        (0x1d05500, 'framebuffer.bin'), (0x1d05600, 'stdout.txt')
    ):
        before = str(Path(config['log_root']) / filename).encode('ascii') + b'\0'
        after = str(root / f'native-v{REVISION}' / filename).encode('ascii') + b'\0'
        pieces.append((address, before, after, 256))
    # This obsolete DLL string remains part of the accepted image; the active
    # DLL path is owned by the span-storage helper, and packaging relocates it.
    pieces.append(
        (
            0x1d28000, str(Path(config['audio_dll']).resolve()).encode('ascii') + b'\0',
            str(root / 'native-v99/tn-audio.dll').encode('ascii') + b'\0', 256
        )
    )
    pieces.append((0x1d1e102, b'research 37 (PCM audio)\0', f'research {REVISION} (PCM audio)\0'.encode(), 64))
    for address, before, after, capacity in pieces:
        if (
            len(after) > capacity or len(before) > capacity
            or bytes(read(address, len(before))) != before
        ):
            raise ValueError('Runtime label provider differs at ' + hex(address))
        extent = max(len(before), len(after))
        if any(read(address + len(before), extent - len(before))):
            raise ValueError('Runtime label extension is occupied')
    for address, before, after, _ in pieces:
        write(address, after)


def install_feature(feature, write, ram, context):
    from features import target_picking, terminal, timing_install, frame_clock, descrambler
    from features import hud_overlays, options, room_hover, shot_assist, snapshot_controls
    from features import campaign_startup, render_install, render_compositor
    read = lambda a, n: ram[a:a + n]
    for name in feature.sources:
        owned_component(name, write, ram, context)
    name = feature.name
    if name == 'terrain-foundation':
        from features import terrain_distance
        terrain_distance.install_foundation(write, read)
    elif name == 'terrain-storage':
        from features import terrain_distance
        terrain_distance.install_storage(write, read)
    elif name == 'world-effects':
        from features import terrain_distance
        terrain_distance.install_profiles(write, read)
    elif name == 'target-acquisition':
        target_picking.install(write, ram)
    elif name == 'route-storage':
        from features import ai_response
        ai_response.route_install(write, read)
        ai_response.route_verify(read)
    elif name == 'logical-hud':
        # Unreachable allocation retained explicitly for accepted image/snapshot identity.
        parts = terminal.retained_bodies(asm)
        if any(any(read(a, len(b))) for a, b in parts):
            raise ValueError('Compatibility terminal storage occupied')
        for a, b in parts:
            write(a, b)
    elif name == 'actor-and-effect-timing':
        from host_audio import slot
        from host_window import PUMP
        callbacks = frame_clock.Callbacks(
            slot('TN_FrameBegin'), slot('TN_FrameEnd'), slot('TN_TimeMS'), PUMP
        )
        timing_install.install(timing_install.prepare(callbacks), write, read)
    elif name == 'communications':
        descrambler.install(write, ram, context['original'])
    elif name == 'native-renderer':
        from features.render_integration import Integration, h, maps
        from features.render_arena import BASE
        from export_snapshot_layout import capture, encode
        integration = Integration(BASE)
        integration.build(bindings=integration.bind(read))
        base = render_install.prepare(integration, read, context['imports'])
        plan = render_compositor.prepare(base, integration, h, maps, read)
        contract = capture(integration)
        encode(contract, REVISION)
        render_install.install(plan, write, read)
        context['snapshot'] = contract
    elif name == 'hud-and-input':
        hud_overlays.install(write, read, context['imports'], ui=True, terminal_exit=False)
    elif name == 'terminal':
        terminal.install(write, ram)
    elif name == 'campaign-startup':
        from features.prequel_scripts import pieces
        from original_inputs import demo_ram
        from build_paths import source_path
        import json
        rows = json.loads(source_path("recipes/demo-bindings.json").read_text(encoding="utf-8"))
        root = context['root']
        plan = campaign_startup.prepare(
            read,
            imports=context['imports'],
            demo_pieces=pieces(context['original'], demo_ram, rows),
            home=root / 'native-v120',
            demo_root=root / 'native-demo-prequel-v104/TNOVA',
            shared_root=root / 'native-v28/drive-c/TNOVA'
        )
        campaign_startup.install(plan, write, read)
    elif name == 'shared-options':
        bound = options.bind_providers(
            ram, imports=context['imports'], root=context['root'] / 'native-v28/drive-c/TNOVA'
        )
        options.install(write, ram, **bound)
    elif name == 'campaign-lifecycle':
        from features import campaign_switch
        root = context['root']
        campaign_switch.install_from_startup(
            write,
            read,
            imports=context['imports'],
            home=root / 'native-v120',
            demo_root=root / 'native-demo-prequel-v104/TNOVA',
            shared_root=root / 'native-v28/drive-c/TNOVA'
        )
        campaign_switch.install_content(write, read)
        campaign_switch.install_opening_policy(write, read)
    elif name == 'snapshot-controls':
        snapshot_controls.install(write, read, imports=context['imports'], presentation=False)
    elif name == 'room-hover':
        room_hover.install(write, ram)
    elif name == 'final-options':
        shot_assist.install(write, ram)
    elif name == 'runtime-paths':
        import json
        from build_paths import source_path
        from features import runtime_paths
        recipe = json.loads(source_path('release-recipe.json').read_text(encoding='utf-8'))
        runtime_paths.install(write, read, imports=context['imports'], relocations=recipe['relocations'])
    elif name == 'runtime-labels':
        runtime_labels(write, read, context['config'])


def emit(executable, *, progress=None, audit=None, runtime_contract, report):
    import original_inputs as inputs
    from build_paths import CONFIG
    plan = validate()
    if hashlib.sha256(executable).hexdigest() != FOUNDATION_SHA:
        raise ValueError('Foundation differs from supported input')
    header = executable[:512]
    ram = bytearray(bytes(START) + executable[512:])
    inputs.set_header(header)
    context = dict(
        original=inputs.original_ram,
        original_executable=inputs.original_executable(),
        imports=inputs.Image(ram).imports,
        root=inputs.reference_root(),
        config=CONFIG
    )
    reports = []
    for feature in plan:
        start = time.perf_counter()
        writes = []

        def write(a, b):
            if not b or not START <= a < a + len(b) <= len(ram):
                raise ValueError('Feature write outside runtime image')
            if audit is not None:
                audit.record(REVISION, feature.name, a, bytes(ram[a:a + len(b)]), bytes(b))
            ram[a:a + len(b)] = b
            writes.append((a, len(b)))

        install_feature(feature, write, ram, context)
        row = dict(
            feature=feature.name,
            requires=list(feature.requires),
            write_operations=len(writes),
            seconds=round(time.perf_counter() - start, 3)
        )
        reports.append(row)
        if progress:
            progress(row)
    result = bytes(header + ram[START:])
    actual = hashlib.sha256(result).hexdigest()
    if actual != OUTPUT_SHA:
        raise ValueError('Named-feature output differs: ' + actual)
    runtime_contract['snapshot'] = context['snapshot']
    report.update(
        mode='named-features',
        historical_images_disabled=True,
        history_storage_bytes=0,
        chronological_manifest_used=False,
        features=reports,
        final_sha256=actual,
        source_model='Maintained feature providers and verified original inputs'
    )
    return result, reports
