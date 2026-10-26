"""Localize only template fragments; persisted evidence never passes through here."""
from contextvars import ContextVar
from functools import lru_cache, wraps
import json
from pathlib import Path
import re

_locale = ContextVar('report_locale', default=None)


@lru_cache(maxsize=1)
def messages():
    root = Path(__file__).resolve().parents[1] / 'src' / 'i18n'
    result = {}
    for name in ('messages', 'common', 'catalog', 'service-errors'):
        result.update(json.loads((root / f'{name}.json').read_text(encoding='utf-8')))
    english = {}
    for pair in result.values():
        label = pair[1]
        if label not in english:
            english[label] = pair
        elif english[label] != pair:
            english[label] = None
    for label, pair in english.items():
        if pair is not None:
            result.setdefault(label, pair)
    return result


def text(value):
    locale = _locale.get()
    if locale is None or not isinstance(value, str):
        return value
    key = value.strip()
    pair = messages().get(key)
    if pair is None:
        return value
    start = len(value) - len(value.lstrip())
    end = len(value.rstrip())
    return value[:start] + pair[0 if locale == 'zh-CN' else 1] + value[end:]


def fragment(value):
    """Translate static HTML text/attributes, including partial f-string tags."""
    locale = _locale.get()
    if locale is None:
        return value
    parts = re.split(r'(<[^>]*>|[^<>]*>)', value)
    for i, part in enumerate(parts):
        if part.endswith('>'):
            part = re.sub(r'(\b(?:title|aria-label)=")([^"]*)(")',
                          lambda m: m[1] + text(m[2]) + m[3], part)
            parts[i] = re.sub(r'\blang="(?:en|zh-CN)"', f'lang="{locale}"', part)
        else:
            parts[i] = text(part)
    return ''.join(parts)


def localized_report(function):
    """An omitted locale preserves legacy output; a request scopes its own locale."""
    @wraps(function)
    def render(*args, locale=None, **kwargs):
        token = _locale.set(locale if locale in ('zh-CN', 'en') else None)
        try:
            return function(*args, **kwargs)
        finally:
            _locale.reset(token)
    return render
