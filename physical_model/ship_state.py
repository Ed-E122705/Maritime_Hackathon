"""Immutable JSON state and explicit, repeatable scenario updates.

from_dict never inserts a healthy sensor reading or a default guest mode.
from_files explicitly loads the bundled demonstration fixtures when paths are
omitted. Missing model inputs remain missing and are reported as UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
from pathlib import Path
from .resource_models.common import InputError

DATA = Path(__file__).resolve().parent / 'data'


def merge_state(base, updates):
    """Merge nested objects; replace lists/scalars. Neither argument is changed.

    Set a guest's installed flag to false to remove it. An empty update object
    preserves its existing fields; it does not erase a whole nested object.
    """
    if not isinstance(base, dict) or not isinstance(updates, dict):
        raise InputError('Ship state and updates must be JSON objects')
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_state(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


@dataclass(frozen=True)
class ShipState:
    """Stored as JSON so callers cannot mutate nested state through a reference."""

    _serialized: str

    def __post_init__(self):
        try:
            decoded = json.loads(self._serialized)
            if not isinstance(decoded, dict):
                raise ValueError('expected a JSON object')
            json.dumps(decoded, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InputError(f'Invalid ShipState: {exc}') from exc

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise InputError('ShipState.from_dict requires a dictionary')
        try:
            return cls(json.dumps(values, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise InputError(f'State must contain finite JSON values: {exc}') from exc

    @classmethod
    def from_files(cls, state_path=None, runtime_path=None):
        state_path = Path(state_path) if state_path is not None else DATA / 'example_state.json'
        runtime_path = Path(runtime_path) if runtime_path is not None else DATA / 'sample_runtime.json'
        base = json.loads(state_path.read_text(encoding='utf-8'))
        selections = json.loads(runtime_path.read_text(encoding='utf-8'))
        return cls.from_dict(merge_state(base, selections))

    def to_dict(self):
        """Return an independent copy, including guest installation selections."""
        return json.loads(self._serialized)

    def updated(self, updates=None, **fields):
        """Return a new state with explicit overrides; leave this state unchanged."""
        values = merge_state(self.to_dict(), {} if updates is None else updates)
        return type(self).from_dict(merge_state(values, fields))

