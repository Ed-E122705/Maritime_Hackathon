"""Translate canonical Annex B G1–G5 and custom G6 JSON into resource-model input.

This is NOT a second manifest database: the canonical `data/guests/G*.json` files
are read without modification. `resource_profiles.json` contains ONLY synthetic
engineering assignments needed where the cards leave quantitative information out.
Installed/placement/operating state comes from runtime_state.json, not manifests.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from .resource_models.common import InputError, number

ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_canonical_guests(directory=None, validate=True):
    directory = Path(directory) if directory is not None else ROOT / 'data' / 'guests'
    files = sorted(directory.glob('[Gg][0-9]*.json'))
    if not files:
        raise InputError(f'No canonical guest files in {directory}')
    guests = [load_json(p) for p in files]
    ids = [g.get('id') for g in guests]
    if len(set(ids)) != len(ids):
        raise InputError('Canonical guest IDs must be unique')
    if validate:
        try:
            import jsonschema
        except ImportError:
            # Pure-Python deployment remains possible; structural fields are still
            # checked by the adapter, but full schema validation needs jsonschema.
            for g in guests:
                for key in ('id','assembly','resources','placement','operational_modes'):
                    if key not in g:
                        raise InputError(f'{g.get("id")}: missing {key}')
        else:
            schema = load_json(ROOT / 'data' / 'guest_schema.json')
            for g in guests:
                jsonschema.validate(g, schema)
    for guest in guests:
        validate_manifest_references(guest)
    return guests


def validate_manifest_references(guest):
    """Validate references even when the optional jsonschema package is absent."""
    gid = guest['id']
    collections = [guest['assembly']['components'], guest['placement']['configurations'],
                   guest['resources']['power_modes'], guest['operational_modes']]
    for collection in collections:
        ids = [item['id'] for item in collection]
        if len(ids) != len(set(ids)):
            raise InputError(f'{gid}: duplicate manifest IDs')
    power_ids = {item['id'] for item in guest['resources']['power_modes']}
    for operation in guest['operational_modes']:
        fixed = operation.get('power_mode_id')
        allowed = operation.get('allowed_power_mode_ids')
        if fixed is not None and fixed not in power_ids:
            raise InputError(f'{gid}.{operation["id"]}: undefined power_mode_id {fixed}')
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed or any(x not in power_ids for x in allowed):
                raise InputError(f'{gid}.{operation["id"]}: invalid allowed_power_mode_ids')
            if fixed is not None and fixed not in allowed:
                raise InputError(f'{gid}.{operation["id"]}: conflicting power mappings')


def resolve_location(location):
    return {'mast_slot': 'mast3', 'flight_deck_hangar': 'hangar',
            'hangar_roof': 'roof'}.get(location, location)


def _placing(g, config, synth):
    components = {p['id']: p for p in g['assembly']['components']}
    selected = [a['component_id'] for a in config['assignments']]
    if len(selected) != len(set(selected)) or set(selected) != set(components):
        raise InputError(f'{g["id"]}: placement must assign every assembly component exactly once')
    combined = {}
    for a in config['assignments']:
        cid = a['component_id']
        if cid not in components:
            raise InputError(f'{g["id"]}: unknown component {cid}')
        loc = resolve_location(a['location'])
        row = combined.setdefault(loc, {'location': loc, 'mass_kg': 0})
        row['mass_kg'] += number(components[cid]['mass_kg'], f'{g["id"]}.{cid}.mass')
        if loc.startswith('mast'):
            row['area_m2'] = row.get('area_m2', 0) + number(a['area_m2'], f'{g["id"]}.{cid}.area')
        else:
            if loc not in synth['dimensions_by_location']:
                raise InputError(f'{g["id"]}: missing synthetic dimensions for {loc}')
            row['dimensions_m'] = synth['dimensions_by_location'][loc]
            row['units'] = 2 if loc == 'bay1' and a.get('bay_fraction') == 1.0 else 1
    return list(combined.values())


def _link_bandwidth(g, link_type, bound='nominal'):
    matches = [x for x in g['resources']['data_links'] if x['type'] == link_type]
    if len(matches) != 1:
        raise InputError(f'{g["id"]}: expected one {link_type} declaration')
    return number(matches[0]['bandwidth_mbps'][bound], f'{g["id"]}.{link_type}.{bound}')


def _evidence_gaps(g, pmode, operation, placements):
    """Do not confuse a simulation PASS with supported source requirements."""
    gaps = []
    resources = g['resources']
    if any(v is None for v in resources['compute'].values()):
        gaps.append('Guest compute requirements are incomplete; simulation profile values are substituted.')
    source_mode = next(m for m in resources['power_modes'] if m['id'] == pmode)
    if source_mode['power_kw']['peak'] is None:
        gaps.append('Peak demand/duration not established; zero extra peak only scopes this demo to sustained load.')
    gaps.append('Per-link maximum permitted latency is not declared; profile tolerances are assumptions.')
    if resources['response_time']['max_processing_latency_ms'] is None:
        gaps.append('Guest processing-latency limit is unknown.')
    if any(not p['location'].startswith('mast') for p in placements):
        gaps.append('Equipment bounding dimensions are synthetic; physical fit is conditional.')
    if g['id'] in ('G1', 'G2'):
        gaps.append('Shore transport selection is a runtime/profile assignment, not a manifest fact.')
    selected_op = next((o for o in g['operational_modes'] if o['id'] == operation), None)
    if g['id'] == 'G3' and operation == 'surveying':
        if selected_op.get('power_mode_id') is None:
            gaps.append('Deployed survey power is a demo estimate.')
        acoustic = next(x for x in resources['data_links'] if x['type'] == 'submerged_acoustic')
        if acoustic['bandwidth_mbps']['nominal'] is None:
            gaps.append('Acoustic bandwidth is a demo estimate.')
    if g['id'] == 'G5' and pmode == 'low_power':
        gaps.append('Low-power data demand is unknown; full declared maximum is reserved for screening.')
    if selected_op and selected_op.get('power_mode_id') is None and not selected_op.get('allowed_power_mode_ids'):
        gaps.append('This operation has no declared power mapping; its selected ship-side load is conditional.')
    return gaps


def normalize_guests(canonical, runtime, assumptions):
    """Build normalized installed guests; synthetic allocations are reported separately.

    `runtime`: per-guest configuration, no mutation. Each selected entry has
    installed (bool), placement (configuration ID), power_mode (canonical ID),
    operation (canonical activity ID or null), power_line (port/stbd).
    """
    cards = runtime.get('guests', {})
    if not isinstance(cards, dict):
        raise InputError('runtime.guests must be an object keyed by guest ID')
    undeclared = set(cards) - {g['id'] for g in canonical}
    if undeclared:
        raise InputError(f'Runtime references undeclared guests: {sorted(undeclared)}')
    profiles = assumptions['guest_resource_profiles']
    output, used_assumptions = [], set()
    for g in canonical:
        validate_manifest_references(g)
        gid = g['id']
        choice = cards.get(gid, {'installed': False})
        if not isinstance(choice.get('installed'), bool):
            raise InputError(f'{gid}: installed must be a boolean')
        if not choice['installed']:
            continue
        configs = {x['id']: x for x in g['placement']['configurations']}
        config_id = choice.get('placement')
        if config_id not in configs:
            raise InputError(f'{gid}: unknown placement {config_id}; choose {sorted(configs)}')
        cfg = configs[config_id]
        declared_modes = {x['id']: x for x in g['resources']['power_modes']}
        operation = choice.get('operation')
        operations = {x['id']: x for x in g['operational_modes']}
        if operation is not None and operation not in operations:
            raise InputError(f'{gid}: unknown operation {operation}; choose {sorted(operations)}')
        definition = operations.get(operation, {})
        fixed_power = definition.get('power_mode_id')
        pmode = choice.get('power_mode', fixed_power)
        if pmode not in declared_modes:
            raise InputError(f'{gid}: unknown power_mode {pmode}; choose {sorted(declared_modes)}')
        if fixed_power is not None and pmode != fixed_power:
            raise InputError(f'{gid}.{operation}: requires power_mode {fixed_power}, got {pmode}')
        allowed = definition.get('allowed_power_mode_ids')
        if allowed is not None and pmode not in allowed:
            raise InputError(f'{gid}.{operation}: power_mode must be one of {allowed}')
        if operation is not None and fixed_power is None and allowed is None:
            used_assumptions.add('MODE-08')
        profile = profiles.get(gid)
        if profile is None:
            raise InputError(f'{gid}: no resource profile configured; unresolved guest demands and geometry prevent admission assessment')
        placements = _placing(g, cfg, profile)
        power_kw = number(declared_modes[pmode]['power_kw']['nominal'], f'{gid}.{pmode}.power')
        if gid == 'G3' and operation == 'surveying' and fixed_power is None:
            if pmode != 'standby':
                raise InputError('G3 cannot be surveying while a charging power mode is selected')
            power_kw = number(profile['survey_power_kw'], 'G3.survey_power_kw')
            used_assumptions.add('MODE-01')
        # Follow the manifest's thermal rule. No additional antenna dissipation is invented.
        cooling = g['resources']['cooling']
        if cooling['electrical_kw_to_heat_kw'] != 1.0:
            raise InputError(f'{gid}: this challenge model requires declared 1:1 heat coupling')
        if gid == 'G5':
            if cooling['chilled_water_load_rule'] != 'equals_electrical_kw':
                raise InputError('G5 cooling rule changed; explicit thermal adapter update required')
            main = next(p for p in placements if p['location'].startswith('bay'))
            heat_paths = [{'location': main['location'], 'kw': power_kw}]
        else:
            heat_paths = [{'location': placements[0]['location'], 'kw': power_kw}]
        compute_mode = 'surveying' if gid == 'G3' and operation == 'surveying' else pmode
        node_data = profile['compute_by_mode'].get(compute_mode, profile['compute_by_mode'].get('default'))
        if node_data is None and all(v is not None for v in g['resources']['compute'].values()):
            node_data = {}
        if node_data is None:
            raise InputError(f'{gid}: no synthetic compute profile for {pmode}')
        node_data = copy.deepcopy(node_data)
        declared_compute = g['resources']['compute']
        for source_key, target_key in [('cpu_cores','cores'), ('ram_gb','ram_gb'), ('accelerator_units','accelerators')]:
            if declared_compute[source_key] is not None:
                node_data[target_key] = number(declared_compute[source_key], gid+'.'+source_key)
        if declared_compute['storage_gb'] is not None:
            node_data['storage_tb'] = number(declared_compute['storage_gb'], gid+'.storage_gb') / 1000
        for field in ('cores', 'ram_gb', 'accelerators', 'storage_tb'):
            if field not in node_data:
                raise InputError(f'{gid}: missing compute demand {field}')
            node_data[field] = number(node_data[field], gid + '.' + field)
        node = profile['compute_node']
        compute = {'cores':node_data['cores'],'ram_gb':node_data['ram_gb'],
                   'accelerators':node_data['accelerators'],
                   'storage_tb':node_data['storage_tb'],
                   'allocations':[{'node':node,'cores':node_data['cores'],
                                   'ram_gb':node_data['ram_gb'],
                                   'accelerators':node_data['accelerators']}]}
        used_assumptions.add('SYS-01')
        streams = {name: {'mbps':0,'max_latency_ms': assumptions['link_latency_ms'][name],
                          'latency_source':'COM-06 / synthetic guest tolerance',
                          'required':False} for name in ('backbone','satcom','los','acoustic')}
        if gid == 'G1':
            streams['backbone']['mbps']=_link_bandwidth(g, 'backbone');streams['backbone']['required']=True
            if runtime.get('emission','normal') != 'silent':
                shore = profile['shore_transport']
                if shore not in ('satcom', 'los'):
                    raise InputError(f'{gid}: unsupported shore transport {shore}')
                streams[shore]['mbps']=_link_bandwidth(g, 'shore_link_transport_unspecified'); streams[shore]['required']=True
            used_assumptions.add('COM-02')
        elif gid == 'G2':
            streams['backbone']['mbps']=_link_bandwidth(g, 'backbone'); streams['backbone']['required']=True
            if runtime.get('emission','normal') != 'silent':
                shore = profile['shore_transport']
                if shore not in ('satcom', 'los'):
                    raise InputError(f'{gid}: unsupported shore transport {shore}')
                streams[shore]['mbps']=_link_bandwidth(g, 'shore_link_transport_unspecified'); streams[shore]['required']=True
            used_assumptions.add('COM-02')
        elif gid == 'G3':
            if operation == 'surveying':
                declared_acoustic = next(x for x in g['resources']['data_links'] if x['type'] == 'submerged_acoustic')['bandwidth_mbps']['nominal']
                if declared_acoustic is None:
                    declared_acoustic = assumptions['acoustic_guest_demand_mbps']
                    used_assumptions.add('COM-03')
                streams['acoustic']['mbps']=number(declared_acoustic, 'G3.acoustic_demand_mbps'); streams['acoustic']['required']=True
            else:
                streams['backbone']['mbps']=_link_bandwidth(g, 'cradle_backbone'); streams['backbone']['required']=True
        elif gid == 'G4':
            if operation in ('launch_recovery','in_flight') and runtime.get('emission','normal') != 'silent':
                declared_video = next(x for x in g['resources']['data_links'] if x['type'] == 'line_of_sight_video')['bandwidth_mbps']['nominal']
                rate = number(assumptions['g4_los_nominal_mbps'] if declared_video is None else declared_video, 'g4_los_nominal_mbps')
                if not _link_bandwidth(g, 'line_of_sight_video', 'min') <= rate <= _link_bandwidth(g, 'line_of_sight_video', 'max'):
                    raise InputError('G4 selected video demand lies outside its declared range')
                streams['los']['mbps']=rate; streams['los']['required']=True
                if declared_video is None:
                    used_assumptions.add('COM-04')
        elif gid == 'G5':
            streams['backbone']['mbps']=_link_bandwidth(g, 'backbone'); streams['backbone']['required']=True
            if profile['satcom_demand_policy'] != 'manifest_maximum_for_each_mode':
                raise InputError('Unknown G5 SATCOM screening policy')
            streams['satcom']['mbps']=_link_bandwidth(g, 'satcom', 'max')
            streams['satcom']['required']=True
            used_assumptions.add('COM-05')
        else:
            # Custom G6+ can use the same adapter if they have a valid B.0 manifest
            # and their OWN synthetic compute/dimension profile. No guest-specific
            # resource logic is silently synthesized for unknown transports.
            link_types={'backbone':'backbone','satcom':'satcom',
                        'line_of_sight_video':'los','submerged_acoustic':'acoustic',
                        'cradle_backbone':'backbone'}
            for link in g['resources']['data_links']:
                linktype=link['type']
                if linktype not in link_types:
                    raise InputError(f'{gid}: link transport {linktype} requires an explicit mapping in its profile')
                hostlink=link_types[linktype]
                bw=link['bandwidth_mbps']
                chosen=bw.get('nominal')
                if chosen is None:
                    raise InputError(f'{gid}: specify a numeric nominal {linktype} bandwidth or team assumption')
                if runtime.get('emission','normal')=='silent' and link.get('disabled_in_emission_silence'):
                    chosen=0
                streams[hostlink]['mbps']+=number(chosen,f'{gid}.{linktype}.bandwidth')
                streams[hostlink]['required'] |= chosen>0
        peak = declared_modes[pmode]['power_kw']['peak']
        peak_extra, peak_duration = 0, 0
        if peak is not None:
            peak = number(peak, f'{gid}.{pmode}.peak')
            if peak < power_kw:
                raise InputError(f'{gid}: declared peak is below selected sustained power')
            peak_extra = peak - power_kw
            if peak_extra > 0:
                # Sustained max_duration_minutes is NOT an electrical-peak duration.
                # Missing evidence yields UNKNOWN in electrical, never a guessed 60 s.
                peak_duration = profile.get('peak_duration_s_by_mode', {}).get(pmode)
        guest = {'id':gid,'name':g['name'],'installed':True,
                 'mass_kg':sum(row['mass_kg'] for row in placements),
                 'power_line':choice.get('power_line') or profile['default_power_line'], 'placements':placements,
                 'mode':pmode, 'operation':operation, '_manifest':copy.deepcopy(g),
                 '_configuration_id':config_id, '_configuration':copy.deepcopy(cfg),
                 'modes':{pmode:{'power_kw':power_kw,'peak_extra_kw':peak_extra,'peak_duration_s':peak_duration,
                                 'heat_paths':heat_paths,'datalinks':streams,'compute':compute,
                                 'sustained_duration_minutes':declared_modes[pmode].get('max_duration_minutes'),
                                 'interruptible':declared_modes[pmode].get('interruptible'),
                                 'capability_fraction':declared_modes[pmode].get('capability_fraction')}}}
        guest['_source_evidence_gaps'] = _evidence_gaps(g, pmode, operation, placements)
        guest['_operational_policy'] = copy.deepcopy(assumptions['operational_policy'])
        used_assumptions.update(('OP-01', 'MODE-05'))
        used_assumptions.update(('PHY-01','PHY-02','PHY-03','PHY-04','SYS-01','SYS-02','SYS-03','COM-01','COM-06','MODE-07','STATE-01','STATE-02','TIME-01'))
        if any(p['location'].startswith('bay') for p in placements):
            used_assumptions.add('PHY-08')
        if gid=='G4': used_assumptions.add('PHY-06')
        if any(p['location']=='roof' for p in placements): used_assumptions.add('PHY-07')
        output.append(guest)
    return output, sorted(used_assumptions)


def load_runtime(runtime_path=None):
    path = runtime_path or ROOT / 'physical_model' / 'data' / 'sample_runtime.json'
    return load_json(path)


def evaluate_canonical(guest_dir=None, runtime_path=None, specs_path=None, state_path=None, profile_path=None):
    """Backward-compatible file interface. See snapshot.build_snapshot for live dict inputs."""
    from .snapshot import load_snapshot
    return load_snapshot(guest_dir=guest_dir, runtime_path=runtime_path,
                         specs_path=specs_path, state_path=state_path, profile_path=profile_path)
