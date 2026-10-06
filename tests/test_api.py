"""API client tests with a fake aiohttp session serving the recorded fixtures."""

from __future__ import annotations

from datetime import date
import os
import ssl
from typing import Any

import aiohttp
import pytest

from custom_components.cherkasy_outage.api import (
    OblenergoClient,
    OblenergoConnectionError,
    OblenergoResponseError,
    create_ssl_context,
)
from custom_components.cherkasy_outage.const import CABINET_URL, KIND_PLANNED

from .conftest import KYIV, fixture_text

ACCOUNT = "71010000002"


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self._text = text
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)  # type: ignore[arg-type]

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeSession:
    """Routes GETs to fixtures; records the calls it saw."""

    def __init__(
        self, routes: dict[tuple[str, str], str] | None = None, error: Exception | None = None
    ) -> None:
        self.routes = routes or {}
        self.error = error
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any], **kwargs: Any) -> FakeResponse:
        self.calls.append((url, params, kwargs))
        if self.error:
            raise self.error
        key = (url, str(params.get("op") or "") + str(params.get("disconn_selector", "")))
        if key not in self.routes:
            key = (url, "*")
        return FakeResponse(self.routes[key])


def _client(session: FakeSession) -> OblenergoClient:
    return OblenergoClient(session, ssl.create_default_context())  # type: ignore[arg-type]


async def test_queue_info_uses_selector_2_and_tls_context() -> None:
    session = FakeSession(
        {(CABINET_URL, "disconn_by_ls2"): fixture_text("cabinet_account_queue.json")}
    )
    client = _client(session)
    queue, as_of = await client.queue_info(ACCOUNT, date(2026, 10, 6))
    assert queue.gpv == "4.1" and queue.gav == "3"
    assert as_of and as_of.endswith("06.10.2026")
    url, params, kwargs = session.calls[0]
    assert params == {
        "op": "disconn_by_ls",
        "abon_ls": ACCOUNT,
        "disconn_selector": 2,
        "n_date": "06.10.2026",
        "k_date": "06.10.2026",
    }
    assert isinstance(kwargs["ssl"], ssl.SSLContext)


async def test_works_merges_planned_and_emergency() -> None:
    session = FakeSession(
        {
            (CABINET_URL, "disconn_by_ls0"): fixture_text("cabinet_dept_selector0.json"),
            (CABINET_URL, "disconn_by_ls1"): fixture_text("cabinet_dept_selector1.json"),
        }
    )
    outages = await _client(session).works(ACCOUNT, date(2026, 10, 5), date(2026, 10, 13), KYIV)
    assert {o.kind for o in outages} == {KIND_PLANNED, "emergency"}
    assert len(session.calls) == 2


async def test_unsupported_op_raises() -> None:
    session = FakeSession({(CABINET_URL, "*"): fixture_text("cabinet_no_op.json")})
    with pytest.raises(OblenergoResponseError):
        await _client(session).departments()


async def test_invalid_json_raises() -> None:
    session = FakeSession({(CABINET_URL, "*"): "<html>502</html>"})
    with pytest.raises(OblenergoResponseError):
        await _client(session).departments()


async def test_connection_error_is_wrapped() -> None:
    session = FakeSession(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(OblenergoConnectionError):
        await _client(session).departments()


async def test_timeout_is_wrapped() -> None:
    session = FakeSession(error=TimeoutError())
    with pytest.raises(OblenergoConnectionError):
        await _client(session).latest_posts()


async def test_address_dictionaries() -> None:
    session = FakeSession(
        {
            (CABINET_URL, "department_list"): fixture_text("cabinet_department_list.json"),
            (CABINET_URL, "city_list"): fixture_text("cabinet_city_list.json"),
            (CABINET_URL, "street_list"): fixture_text("cabinet_street_list.json"),
            (CABINET_URL, "house_list"): fixture_text("cabinet_house_list.json"),
            (CABINET_URL, "ls_list_by_addr"): fixture_text("cabinet_ls_list.json"),
        }
    )
    client = _client(session)
    departments = await client.departments()
    assert departments[0]["ID"] == "1"
    assert (await client.cities("1"))[0]["NAME"] == "м. Черкаси"
    assert (await client.streets("1", "Зін"))[0]["ID"] == "115"
    assert any(h["HOUSE"] == "12" for h in await client.houses("115"))
    assert [a["LS"] for a in await client.accounts_at("115", "12")] == [
        "71010000001",
        "71010000002",
    ]


async def test_news_list_and_post() -> None:
    from custom_components.cherkasy_outage.const import NEWS_LIST_URL, NEWS_POST_URL

    slug = "hrafik-pohodynnykh-vidklyuchen-hpv-na-7-zhovtnya"
    session = FakeSession(
        {
            (NEWS_LIST_URL, "*"): fixture_text("news_list.json"),
            (NEWS_POST_URL.format(slug=slug), "*"): fixture_text(f"news_post_{slug}.json"),
        }
    )
    client = _client(session)
    posts = await client.latest_posts()
    assert posts[0]["slug"] == slug
    assert session.calls[0][1] == {"lang": "uk", "page": 0, "size": 20}
    post = await client.post(slug)
    assert "4.1" in post["content"]
    # The news host has a complete certificate chain: no custom TLS context.
    assert "ssl" not in session.calls[1][2]


def test_ssl_context_trusts_bundled_intermediate() -> None:
    context = create_ssl_context()
    subjects = [dict(x[0] for x in cert["subject"]) for cert in context.get_ca_certs()]
    assert any(
        s.get("commonName") == "Sectigo Public Server Authentication CA DV R36" for s in subjects
    )


@pytest.mark.skipif(
    not os.environ.get("CHERKASY_LIVE"), reason="set CHERKASY_LIVE=1 to hit the real APIs"
)
async def test_live_apis() -> None:
    """Smoke test against the real services (they may be geo-restricted to Ukraine)."""
    async with aiohttp.ClientSession() as session:
        client = OblenergoClient(session, create_ssl_context())
        assert await client.departments()
        assert await client.latest_posts()
        account = os.environ.get("CHERKASY_ACCOUNT")
        if account:
            queue, _ = await client.queue_info(account, date.today())
            assert queue.gpv
