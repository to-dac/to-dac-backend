# vworld 토지특성 조회 로직 단위 테스트 (httpx 모킹, 네트워크 호출 없음)
from typing import Any

import httpx
import pytest

from app.mcp import vworld
from app.mcp.settings import settings

SAMPLE_RESPONSE: dict[str, Any] = {
    "landCharacteristicss": {
        "field": [
            {
                "pnu": "1111010100100010000",
                "ldCodeNm": "서울특별시 종로구 청운동",
                "lndcgrCodeNm": "대",
                "lndpclAr": "100.5",
                "prposArea1Nm": "제1종일반주거지역",
                "pblntfPclnd": "5000000",
                "lastUpdtDt": "2025-01-01",
            }
        ]
    }
}


class _FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.vworld.kr/x")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> Any:
        return self._json


class _FakeClient:
    def __init__(self, *, response: _FakeResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.called_params: dict[str, Any] | None = None
        self.called_headers: dict[str, Any] | None = None

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        self.called_params = params
        self.called_headers = headers
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(vworld.httpx, "AsyncClient", lambda *a, **k: client)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VWORLD_API_KEY", "test-key")


# ---- parse_response ----

def test_parse_response_maps_fields() -> None:
    result = vworld.parse_response(SAMPLE_RESPONSE)
    assert len(result["fields"]) == 1
    field = result["fields"][0]
    assert field["법정동명"] == "서울특별시 종로구 청운동"
    assert field["지목명"] == "대"
    assert field["공시지가_원㎡"] == "5000000"
    assert result["raw"] == SAMPLE_RESPONSE


def test_parse_response_empty() -> None:
    result = vworld.parse_response({"landCharacteristicss": {"field": []}})
    assert result["fields"] == []
    assert "message" in result


def test_parse_response_unknown_key_preserved() -> None:
    result = vworld.parse_response({"x": {"field": {"someRawKey": "v"}}})
    assert result["fields"][0]["someRawKey"] == "v"


# ---- fetch_land_characteristics ----

async def test_fetch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_RESPONSE))
    _patch_client(monkeypatch, client)

    result = await vworld.fetch_land_characteristics("1111010100100010000")

    assert result["fields"][0]["지목명"] == "대"
    assert client.called_params is not None
    assert client.called_params["pnu"] == "1111010100100010000"
    assert client.called_params["key"] == "test-key"
    assert client.called_params["format"] == "json"
    # V-World 인증을 위해 Referer 헤더가 반드시 전송되어야 한다
    assert client.called_headers is not None
    assert client.called_headers["Referer"] == settings.VWORLD_REFERER


async def test_fetch_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VWORLD_API_KEY", "")
    result = await vworld.fetch_land_characteristics("1111010100100010000")
    assert "error" in result


async def test_fetch_missing_pnu() -> None:
    result = await vworld.fetch_land_characteristics("")
    assert "error" in result


async def test_fetch_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(None, status_code=500))
    _patch_client(monkeypatch, client)
    result = await vworld.fetch_land_characteristics("1111010100100010000")
    assert "error" in result
    assert "500" in result["error"]


async def test_fetch_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timeout"))
    _patch_client(monkeypatch, client)
    result = await vworld.fetch_land_characteristics("1111010100100010000")
    assert "error" in result
    assert "시간 초과" in result["error"]


async def test_fetch_caps_num_of_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_RESPONSE))
    _patch_client(monkeypatch, client)
    await vworld.fetch_land_characteristics("1111010100100010000", num_of_rows=99999)
    assert client.called_params is not None
    assert client.called_params["numOfRows"] == vworld.MAX_NUM_OF_ROWS
