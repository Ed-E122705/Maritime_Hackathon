"""Compose the three functional brains into ONE authoritative state snapshot.

Navigation, platform and mission are domain modules inside one VesselOS process,
not separate competing decision engines. Environment/crew/timing are shared context.
"""
import copy
from .resource_models.common import InputError

def compose_state(navigation, platform, mission, environment=None, crew_context=None, timing=None):
    blocks={'navigation':navigation,'platform':platform,'mission':mission,
            'environment':environment or {},'crew_context':crew_context or {},'timing':timing or {}}
    state={}
    for source,values in blocks.items():
        if not isinstance(values,dict):
            raise InputError(f'{source}: expected a dictionary')
        for key,value in values.items():
            if key in state:
                raise InputError(f'Conflicting owners for ship state field {key}; first source vs {source}')
            state[key]=copy.deepcopy(value)
    return state
