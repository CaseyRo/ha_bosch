"""Every locale keeps the placeholders its source string uses.

Hassfest only validates translations/en.json for custom integrations, so a
locale that drops `{auth_url}` passes CI and silently removes the login link.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

BOSCH = Path(__file__).parent.parent / "custom_components" / "bosch"
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _load(path: Path) -> dict[str, str]:
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


SOURCE = _load(BOSCH / "strings.json")


@pytest.mark.parametrize(
    "locale", sorted(p.name for p in (BOSCH / "translations").glob("*.json"))
)
def test_locale_keeps_source_placeholders(locale):
    strings = _load(BOSCH / "translations" / locale)
    mismatched = {
        key: value
        for key, value in strings.items()
        if key in SOURCE
        and sorted(PLACEHOLDER.findall(str(value)))
        != sorted(PLACEHOLDER.findall(str(SOURCE[key])))
    }
    assert not mismatched
