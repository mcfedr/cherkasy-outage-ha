"""Shared fixtures.

The unit tests exercise the pure modules (const, models, parser, api) without a
Home Assistant install. To avoid running the package ``__init__`` (which imports
Home Assistant), the integration package is registered as a bare module whose
submodules load straight from disk.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "custom_components" / "cherkasy_outage"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if "custom_components.cherkasy_outage" not in sys.modules:
    if "custom_components" not in sys.modules:
        parent = types.ModuleType("custom_components")
        parent.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = parent
    spec = importlib.util.spec_from_loader("custom_components.cherkasy_outage", loader=None)
    package = importlib.util.module_from_spec(spec)
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules["custom_components.cherkasy_outage"] = package

KYIV = ZoneInfo("Europe/Kyiv")


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def kyiv() -> ZoneInfo:
    return KYIV
