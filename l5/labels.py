"""English display names for shared application identifiers."""

from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _labels():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def display_label(value):
    return _labels().get(value, value) if isinstance(value, str) else value
