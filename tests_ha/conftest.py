"""Fixtures for tests that run the integration inside a real Home Assistant core.

Run with: pytest tests_ha (needs pytest-homeassistant-custom-component).
"""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

from aiohttp import ClientConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.cherkasy_outage.const import (
    CABINET_URL,
    CONF_ACCOUNT,
    CONF_ADDRESS,
    CONF_QUEUE,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
ACCOUNT = "71010000002"
SLUG_6 = "hrafik-pohodynnykh-vidklyuchen-hpv-na-6-zhovtnya"
SLUG_6_UPDATED = "onovleno-hrafik-pohodynnykh-vidklyuchen-hpv-na-6-zhovtnya"
SLUG_7 = "hrafik-pohodynnykh-vidklyuchen-hpv-na-7-zhovtnya"
SLUG_GOP = "dlya-promyslovosti-ta-biznesu-cherkaskoyi-oblasti-6-zhovtnya-diyatymut-hrafiky-obmezhennya-potuzhnosti-hop"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let HA load custom_components/ from the repo."""


@pytest.fixture(autouse=True)
def plain_ssl_context() -> Generator[None]:
    """The real context works too, but there is no need to touch certifi in tests."""
    import ssl

    with patch(
        "custom_components.cherkasy_outage.helpers.create_ssl_context",
        side_effect=ssl.create_default_context,
    ):
        yield


class CabinetRouter:
    """aiohttp mock side effect answering every cabinet API op from fixtures."""

    def __init__(self) -> None:
        self.queue = fixture_text("cabinet_account_queue.json")
        self.planned = fixture_text("cabinet_account_planned_empty.json")
        self.emergency = fixture_text("cabinet_account_planned_empty.json")
        self.dictionaries = {
            "department_list": fixture_text("cabinet_department_list.json"),
            "city_list": fixture_text("cabinet_city_list.json"),
            "street_list": fixture_text("cabinet_street_list.json"),
            "house_list": fixture_text("cabinet_house_list.json"),
            "ls_list_by_addr": fixture_text("cabinet_ls_list.json"),
        }
        self.fail = False
        self.requests: list[dict[str, str]] = []

    async def __call__(self, method: str, url: Any, data: Any) -> Any:
        query = dict(url.query)
        self.requests.append(query)
        if self.fail:
            raise ClientConnectionError("down")
        if query.get("op") == "disconn_by_ls":
            body = {"0": self.planned, "1": self.emergency, "2": self.queue}[
                query["disconn_selector"]
            ]
        else:
            body = self.dictionaries.get(query.get("op", ""), fixture_text("cabinet_no_op.json"))
        return AiohttpClientMockResponse(method, url, text=body)


class NewsRouter:
    """aiohttp mock side effect for the news API; posts can be swapped per test."""

    def __init__(self) -> None:
        self.listing = json.loads(fixture_text("news_list.json"))
        self.posts = {
            slug: json.loads(fixture_text(f"news_post_{slug}.json"))
            for slug in (SLUG_6, SLUG_6_UPDATED, SLUG_7)
        }
        self.fail = False

    def hide(self, slug: str) -> None:
        self.listing["data"]["content"] = [
            p for p in self.listing["data"]["content"] if p["slug"] != slug
        ]

    async def __call__(self, method: str, url: Any, data: Any) -> Any:
        if self.fail:
            raise ClientConnectionError("down")
        if url.path.endswith("/category/news"):
            return AiohttpClientMockResponse(method, url, text=json.dumps(self.listing))
        slug = url.path.rsplit("/", 1)[-1]
        return AiohttpClientMockResponse(method, url, text=json.dumps(self.posts[slug]))


@pytest.fixture
def news_router(aioclient_mock: AiohttpClientMocker) -> NewsRouter:
    router = NewsRouter()
    aioclient_mock.get(
        re.compile(r"^https://www\.cherkasyoblenergo\.com/api/v1/posts/"), side_effect=router
    )
    return router


@pytest.fixture
def cabinet_router(aioclient_mock: AiohttpClientMocker) -> CabinetRouter:
    router = CabinetRouter()
    aioclient_mock.get(CABINET_URL, side_effect=router)
    return router


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="м. Черкаси, вул. Тестова, 1",
        unique_id=ACCOUNT,
        data={
            CONF_ACCOUNT: ACCOUNT,
            CONF_ADDRESS: "м. Черкаси, вул. Тестова, 1",
            CONF_QUEUE: "4.1",
        },
    )
