"""Annex B.0 operational constraints, assembly relations, and crew-aware installation.

Checks feasibility of a proposed CURRENT state. Arbitration/search over future
ship-state transitions, priorities, recovery deadlines is delegated to Steps 5/6.
Every PASS/FAIL/UNKNOWN has a source and reason. No real ship commands issued.
"""
from .common import model, need, n, flag, result, rule, unknown, InputError

FIELDS = {
 'navigation.speed_knots': 'speed_kn',
 'navigation.course_keeping': 'course',
 'navigation.noise_level': 'noise',
 'navigation.manoeuvre_freedom': 'manoeuvre_freedom',
 'environment.sea_state': 'sea_state',
 'environment.wind_knots': 'wind_kn',
 'platform.deck_area_around_bay_clear': 'deck_area_around_bay_clear',
 'platform.emission_state': 'emission',
 'platform.deck_machinery_active': 'deck_machinery',
 'platform.stern_ramp_free': 'stern_ramp_free',
 'platform.stern_ramp_in_use': 'ramp_in_use',
 'platform.flight_deck_clear': 'deck_state',
 'platform.hangar_roof_available': 'hangar_roof_available',
 'platform.drone_clearance_verified': 'drone_clearance_verified',
 'platform.own_radar_transmitting_nearby': 'own_radar_transmitting_nearby',
}

def _condition(expr, state, guest_id):
    field = expr['field']; op = expr['operator']; expected = expr['value']
    if field not in FIELDS:
        return unknown(guest_id+'.'+field, 'Rule refers to unsupported field '+field)
    skey = FIELDS[field]
    if field == 'platform.flight_deck_clear':
        actual = state.get('deck_state') == 'clear' if 'deck_state' in state else None
    elif field == 'platform.stern_ramp_in_use':
        actual = 'ramp' in state.get('active_operations', []) if 'active_operations' in state else None
    else:
        actual = state.get(skey)
    if actual is None:
        return unknown(guest_id+'.'+field, f'Missing state field {skey} for {guest_id}.')
    if isinstance(expected, bool) and not isinstance(actual, bool):
        return unknown(guest_id+'.'+field, f'{skey} must be boolean')
    if op in ('lte','gte','lt','gt'):
        if isinstance(actual,bool) or not isinstance(actual,(int,float)):
            return unknown(guest_id+'.'+field,f'Numeric state expected for {skey}.')
        passed = {'lte':lambda a,b:a<=b,'gte':lambda a,b:a>=b,
                  'lt':lambda a,b:a<b,'gt':lambda a,b:a>b}[op](actual,expected)
    elif op in ('eq','neq'):
        passed = (actual == expected) if op=='eq' else (actual != expected)
    else:
        return unknown(guest_id+'.'+field,f'Unrecognized rule operator {op}')
    return rule(guest_id+'.'+field+'.'+op, passed,
                f'{guest_id}: {field} {actual!r} must be {op} {expected!r}.', 'Annex B / canonical manifest')

def _install_checks(request, state):
    """Use the updated installation operation/target and its crew/time demand."""
    gid = request.get('guest_id')
    change = request.get('change')
    location = state.get('ship_location')
    if location not in ('in_port', 'at_sea'):
        return [unknown('installation.location', 'ship_location must be in_port or at_sea')]
    at_sea = location == 'at_sea'
    if change == 'logical_retask':
        return [rule('installation.logical_retask', True,
                     'Logical re-tasking has no physical installation demand in this screen.', 'A.11 / model scope')]
    # Preserve the legacy names while accepting the new manifest operation names.
    operation = request.get('operation')
    target = request.get('operation_target')
    component = request.get('component_id')
    if change == 'vehicle_swap':
        operation, target = 'swap_vehicle_only', 'vehicle'
    elif change == 'drone_swap':
        operation, component = 'swap_component', 'drone'
    allowed_swap = (gid == 'G3' and operation == 'swap_vehicle_only' and target == 'vehicle') or (
        gid == 'G4' and operation == 'swap_component' and component == 'drone')
    checks = []
    if at_sea:
        checks.append(rule('installation.at_sea_physical_type', allowed_swap,
            'At sea only the declared G3 vehicle-only or G4 drone swap is eligible; the cradle/hangar remains installed.',
            'Updated guest installation records'))
        if not allowed_swap:
            return checks
    manifest = state.get('_guest_manifests', {}).get(gid)
    if manifest is None:
        return checks + [unknown('installation.manifest', f'No manifest for {gid}')]
    entries = [x for x in manifest['installation'] if x.get('component_ids')]
    if operation:
        entries = [x for x in entries if x.get('operation') == operation]
    elif change in ('new_guest', 'mast_install', 'bay_install', 'hangar_install'):
        entries = [x for x in entries if x.get('port_only') is True]
    else:
        return checks + [unknown('installation.type', 'Specify an installation operation or supported legacy change')]
    if target:
        entries = [x for x in entries if x.get('operation_target') == target]
    if component:
        entries = [x for x in entries if component in x['component_ids']]
    if len(entries) != 1:
        return checks + [unknown('installation.selection', 'Select exactly one installation record by operation and component/target')]
    entry = entries[0]
    if at_sea and entry['port_only']:
        return checks + [rule('installation.port_only', False, 'This record requires installation in port.', 'Guest installation')]
    crew_needed = n(entry, 'crew_required')
    duration = n(entry, 'duration_minutes')
    crew_key = 'installation.crew' if at_sea else 'installation.port_crew'
    checks.append(rule(crew_key, n(state, 'crew') >= crew_needed,
        f'{gid}: requires {crew_needed:g} crew; {state.get("crew")} available.', 'Guest installation'))
    available = request.get('available_minutes')
    if available is None:
        checks.append(unknown('installation.duration', f'{gid}: {duration:g} minutes required; no installation time budget supplied'))
    else:
        checks.append(rule('installation.duration', n(request, 'available_minutes') >= duration,
            f'{gid}: needs {duration:g} min within a {available} min window.', 'Guest installation'))
    if not at_sea:
        return checks
    limits = state.get('_operational_policy', {}).get('at_sea_installation')
    if limits is None:
        return checks + [unknown('installation.window_policy', 'No at-sea installation limits supplied')]
    if any(k not in state for k in ('sea_state','wind_kn','speed_kn','course','deck_state')):
        checks.append(unknown('installation.weather','Installation window state incomplete.'))
    else:
        checks.extend([
            rule('installation.sea_state', n(state,'sea_state') <= n(limits,'max_sea_state'), 'At-sea swap sea-state limit.', 'OP-01'),
            rule('installation.wind', n(state,'wind_kn') <= n(limits,'max_wind_kn'), 'At-sea swap wind limit.', 'OP-01'),
            rule('installation.speed', n(limits,'min_speed_kn') <= n(state,'speed_kn') <= n(limits,'max_speed_kn'), 'At-sea swap speed window.', 'OP-01'),
            rule('installation.course',state['course']=='steady','At-sea swaps require steady course.','OP-01'),
            rule('installation.deck',state['deck_state']=='clear','Deck must be clear.','OP-01')])
    survey_active = state.get('guest_operations',{}).get('G3') == 'surveying'
    checks.append(rule('installation.survey',not survey_active,
                       'At-sea swapping prohibited while G3 is listening.','OP-01'))
    return checks

@model('operational')
def evaluate(specs, state, guests):
    checks=[]
    activities={g['id']:g.get('operation') for g in guests}
    state=dict(state)
    state['guest_operations']=activities
    state['_guest_manifests'] = dict(state.get('_guest_manifests', {}))
    state['_guest_manifests'].update({g['id']:g['_manifest'] for g in guests if '_manifest' in g})
    policy = state.get('_operational_policy') or next((g.get('_operational_policy') for g in guests if g.get('_operational_policy')), {})
    state['_operational_policy'] = policy
    active=set(need(state,'active_operations'))
    crew=need(state,'crew')
    if isinstance(crew, bool) or crew not in policy.get('crew_levels', []):
        raise InputError('crew must be one of the declared operational-policy crew levels')
    if state.get('ship_location') not in ('in_port','at_sea'):
        checks.append(unknown('ship_location','Specify in_port or at_sea.'))
    if state.get('emission')=='silent':
        checks.append(rule('silent_no_deck_machinery',state.get('deck_machinery') is False,
                           'Emission silence prohibits deck machinery.','A.6'))
        checks.append(rule('silent_no_manoeuvring',state.get('noise')!='manoeuvring',
                           'Emission silence prohibits manoeuvring.','A.6'))
    for g in guests:
        gid=g['id']; manifest=g.get('_manifest')
        if not isinstance(manifest,dict):
            checks.append(unknown(gid+'.manifest','Missing canonical manifest; cannot inspect operating ontology.'))
            continue
        operation=g.get('operation')
        ops={o['id']:o for o in manifest['operational_modes']}
        if operation is not None and operation not in ops:
            checks.append(unknown(gid+'.operation',f'Unknown operation {operation}.'))
            continue
        if operation is not None:
            for condition in ops[operation].get('requirements',[]):
                checks.append(_condition(condition,state,gid))
            for incompatible in ops[operation].get('conflicts',[]):
                other=incompatible['guest_id']
                if activities.get(other)==incompatible['guest_mode']:
                    checks.append(rule(f'{gid}.{other}.operating_conflict',False,
                        incompatible['reason'],'Annex B.0 / explicit incompatibility'))
        for cond in g['_configuration'].get('requirements',[]):
            checks.append(_condition(cond,state,gid+'.placement'))
        current = g['modes'][g['mode']]
        duration = current.get('sustained_duration_minutes')
        if gid in ('G2','G4') and duration is not None:
            elapsed = state.get('guest_state',{}).get(gid,{}).get('mode_elapsed_minutes')
            if elapsed is None:
                checks.append(unknown(gid+'.sustained_duration',
                              f'{gid}: elapsed time is required to check {duration}-minute operating-mode limit.'))
            else:
                checks.append(rule(gid+'.sustained_duration',
                              isinstance(elapsed,(int,float)) and not isinstance(elapsed,bool) and 0<=elapsed<=duration,
                              f'{gid}: sustained {g["mode"]} mode limited to {duration} minutes; elapsed {elapsed}.','B.'+gid))
        if gid=='G2' and g['mode']=='winch_operation':
            checks.append(rule('G2.winch_mode_activity',operation=='winch_operation',
                               'Selecting G2 winch power mode requires declaring winch operation.','B.G2'))
        if gid=='G4':
            drone = next(c for c in manifest['assembly']['components'] if c['id'] == 'drone')
            checks.append(rule('G4.drone_mass', n(drone, 'mass_kg') <= n(policy, 'drone_mass_limit_kg'),
                               f'Drone mass {drone["mass_kg"]} kg must fit the declared hangar limit.', 'G4 assembly / OP-01'))
            if operation=='launch_recovery':
                checks.append(rule('G4.flight_operation_declared','flight' in active,
                                   'G4 launch/recovery must declare active flight-deck operation.','A.3'))
            if operation=='in_flight' and state.get('emission')=='silent':
                home = state.get('guest_state',{}).get('G4',{}).get('return_home_requested')
                if home is None:
                    checks.append(unknown('G4.emission_silence_return_home',
                                          'In-flight G4 must return home during emission silence; return-home action not reported.'))
                else:
                    checks.append(rule('G4.emission_silence_return_home',home is True,
                                       'G4 must initiate return-home in emission silence.','B.G4'))
            if operation=='in_flight':
                elapsed = state.get('guest_state',{}).get('G4',{}).get('flight_elapsed_minutes')
                if elapsed is None:
                    checks.append(unknown('G4.endurance', 'Flight elapsed time is missing.'))
                else:
                    checks.append(rule('G4.endurance',isinstance(elapsed,(int,float)) and not isinstance(elapsed,bool) and 0<=elapsed<=n(policy,'g4_endurance_minutes'),
                                       'Flight elapsed time must fit the declared endurance.', 'G4 operation notes / OP-01'))
            if operation in ('launch_recovery','in_flight'):
                guest_state = state.get('guest_state', {}).get('G4', {})
                bat = guest_state.get('battery_percent')
                emergency = next(e for e in manifest['special_events'] if e['type'] == 'battery_emergency')
                threshold = n(emergency['trigger'], 'value')
                deadline = n(emergency, 'recovery_deadline_minutes')
                if bat is None or isinstance(bat, bool) or not isinstance(bat, (int, float)) or not 0 <= bat <= 100:
                    checks.append(unknown('G4.battery_percent', 'Battery percentage must be supplied in [0,100].'))
                elif bat < threshold:
                    eta = guest_state.get('eta_to_landing_min')
                    since = guest_state.get('minutes_since_low_battery')
                    valid = lambda v: isinstance(v, (int,float)) and not isinstance(v,bool) and 0 <= v < float('inf')
                    if not valid(eta):
                        checks.append(unknown('G4.emergency_recovery_eta', 'Supply a nonnegative landing ETA.'))
                    elif eta > deadline:
                        checks.append(rule('G4.emergency_recovery_eta', False,
                            f'ETA {eta} min exceeds the entire {deadline:g} min recovery budget.', 'G4 battery event'))
                    elif not valid(since):
                        checks.append(unknown('G4.emergency_recovery_eta', 'Supply minutes_since_low_battery; ETA alone cannot prove the deadline.'))
                    else:
                        checks.append(rule('G4.emergency_recovery_eta', since + eta <= deadline,
                            f'{since} min elapsed + {eta} min ETA must be <= {deadline:g} min.', 'G4 battery event'))
        if gid=='G3' and operation=='launch_recovery':
            checks.append(rule('G3.ramp_operation_declared','ramp' in active,
                              'G3 launch/recovery must declare active ramp operation.','A.3'))
        if gid=='G2' and operation=='winch_operation':
            checks.append(rule('G2.deck_machinery_declared',state.get('deck_machinery') is True,
                              'G2 winch operation requires deck machinery active.','B.G2'))
        if gid=='G5' and state.get('emission')=='silent':
            checks.append(rule('G5.silence_exclusion',False,
                              'G5 excludes emission silence; cease transmission or choose a compliant state.','B.G5'))
        # Assembly is atomic for admission/shed; no automatic component-level action.
        for request in state.get('shedding_requests',[]):
            if request.get('guest_id')==gid:
                whole = request.get('component_id') is None
                checks.append(rule(gid+'.atomic_shedding', whole,
                                   'Guest assembly must be shed as a whole, not by component.','B.0'))
                if manifest['criticality']['safety_critical'] and request.get('automatic'):
                    checks.append(rule(gid+'.safety_critical_no_auto_shed',False,
                                       'Safety-critical guest cannot be shed automatically.','B.0'))
    # Silent mode G1 passive listening remains allowed; shore upload is suppressed by adapter; G1 buffering is not established.
    for change in state.get('mode_change_requests', []):
        gid = change.get('guest_id')
        manifest = state['_guest_manifests'].get(gid)
        if manifest is None:
            checks.append(unknown('mode_change.manifest', f'No manifest for {gid}'))
            continue
        previous = next((m for m in manifest['resources']['power_modes'] if m['id'] == change.get('from_mode')), None)
        if previous is None:
            checks.append(unknown('mode_change.mode', f'Unknown previous mode for {gid}'))
            continue
        if previous.get('interruptible') is False and change.get('to_mode') != previous['id']:
            elapsed = change.get('elapsed_minutes')
            duration = previous.get('max_duration_minutes')
            name = gid + '.noninterruptible_charge'
            if elapsed is None or duration is None:
                checks.append(unknown(name, 'Charge duration/elapsed evidence is missing.'))
            else:
                checks.append(rule(name, n(change, 'elapsed_minutes') >= n(previous, 'max_duration_minutes'),
                    f'{gid}: complete the declared {duration} min noninterruptible cycle before changing mode.', 'Guest power mode'))
    for request in state.get('install_requests',[]):
        checks.extend(_install_checks(request,state))
    modifiers = {}
    if 'G1' in activities and state.get('own_radar_transmitting_nearby'):
        event = next(e for e in state['_guest_manifests']['G1']['special_events'] if e['type'] == 'capability_modifier')
        loss = n(event, 'capability_loss_fraction')
        if loss > 1:
            raise InputError('Capability loss fraction must be <= 1')
        modifiers['G1'] = {'remaining_capability_fraction': 1-loss, 'reason': 'Declared own-radar capability modifier'}
    capability={g['id']:g['modes'][g['mode']].get('capability_fraction') for g in guests}
    details={'capability_modifiers':modifiers,'declared_mode_capability_fractions':capability, 'active_guest_operations':activities,
             'crew':crew,
             'deck_clearance_window_minutes':policy.get('deck_clearance_minutes', {}).get(str(crew)),
             'human_confirmation_window_s':policy.get('human_confirmation_seconds', {}).get(str(crew)),
             'note':'Deck clearance/confirmation windows are planning constraints, not completed actions.'}
    return result('operational',checks,details)
