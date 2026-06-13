# building 건축물대장 표제부 조회 로직 단위 테스트 (httpx 모킹, 네트워크 호출 없음)
from typing import Any

import httpx
import pytest

from app.mcp import building
from app.mcp.settings import settings

SAMPLE_RESPONSE: dict[str, Any] = {
    "response": {
        "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
        "body": {
            "items": {
                "item": [
                    {
                        "platPlc": "서울특별시 종로구 청운동 5번지",
                        "bldNm": "예수그리스도후기성도교회수도원",
                        "platArea": 2464.2,
                        "archArea": 179.4,
                        "bcRat": 7.28,
                        "totArea": 397.7,
                        "vlRat": 16.14,
                        "grndFlrCnt": 2,
                        "mainPurpsCdNm": "종교시설",
                    }
                ]
            },
            "totalCount": 1,
        },
    }
}

ERROR_RESPONSE: dict[str, Any] = {
    "response": {
        "header": {"resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"},
        "body": {},
    }
}


class _FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://apis.data.go.kr/x")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> Any:
        return self._json


class _FakeClient:
    def __init__(self, *, response: _FakeResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.called_params: dict[str, Any] | None = None

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.called_params = params
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(building.httpx, "AsyncClient", lambda *a, **k: client)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "test-key")


# ---- split_pnu ----

def test_split_pnu_maps_segments() -> None:
    result = building.split_pnu("1111010100100010000")
    assert result["sigunguCd"] == "11110"
    assert result["bjdongCd"] == "10100"
    assert result["bun"] == "0001"
    assert result["ji"] == "0000"
    # PNU 11번째 자리 '1'(대지) → API platGbCd '0'
    assert result["platGbCd"] == "0"


def test_split_pnu_mountain() -> None:
    # 11번째 자리 '2'(산) → platGbCd '1'
    pnu = "1111010100" + "2" + "0001" + "0000"
    assert building.split_pnu(pnu)["platGbCd"] == "1"


# ---- parse_response ----

def test_parse_response_maps_fields() -> None:
    result = building.parse_response(SAMPLE_RESPONSE)
    assert result["totalCount"] == 1
    bld = result["buildings"][0]
    assert bld["건폐율_％"] == 7.28
    assert bld["용적률_％"] == 16.14
    assert bld["대지면적_㎡"] == 2464.2
    assert bld["주용도"] == "종교시설"


def test_parse_response_single_item_dict() -> None:
    data = {
        "response": {
            "header": {"resultCode": "00"},
            "body": {"items": {"item": {"bcRat": 50.0}}, "totalCount": 1},
        }
    }
    result = building.parse_response(data)
    assert result["buildings"][0]["건폐율_％"] == 50.0


def test_parse_response_empty() -> None:
    data = {"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}}
    result = building.parse_response(data)
    assert result["buildings"] == []
    assert "message" in result


def test_parse_response_api_error() -> None:
    result = building.parse_response(ERROR_RESPONSE)
    assert "error" in result
    assert result["resultCode"] == "30"


# ---- fetch_building_title ----

async def test_fetch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_RESPONSE))
    _patch_client(monkeypatch, client)

    result = await building.fetch_building_title("1111010100100010000")

    assert result["buildings"][0]["건폐율_％"] == 7.28
    assert client.called_params is not None
    assert client.called_params["sigunguCd"] == "11110"
    assert client.called_params["bjdongCd"] == "10100"
    assert client.called_params["_type"] == "json"
    # Encoding 키는 unquote 되어 httpx가 1회만 인코딩하도록 전달되어야 한다
    assert "%" not in client.called_params["serviceKey"]


async def test_fetch_caps_num_of_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_RESPONSE))
    _patch_client(monkeypatch, client)
    await building.fetch_building_title("1111010100100010000", num_of_rows=99999)
    assert client.called_params is not None
    assert client.called_params["numOfRows"] == building.MAX_NUM_OF_ROWS


async def test_fetch_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "")
    result = await building.fetch_building_title("1111010100100010000")
    assert "error" in result


async def test_fetch_invalid_pnu() -> None:
    result = await building.fetch_building_title("123")
    assert "error" in result


async def test_fetch_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(None, status_code=500))
    _patch_client(monkeypatch, client)
    result = await building.fetch_building_title("1111010100100010000")
    assert "error" in result
    assert "500" in result["error"]


async def test_fetch_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timeout"))
    _patch_client(monkeypatch, client)
    result = await building.fetch_building_title("1111010100100010000")
    assert "error" in result
    assert "시간 초과" in result["error"]


# ---- 주택가격: parse_housing_price_response ----

HSPRC_RESPONSE: dict[str, Any] = {
    "response": {
        "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
        "body": {
            "items": {
                "item": [
                    {
                        "platPlc": "서울특별시 종로구 청운동 56-45번지",
                        "bldNm": "청운빌딩",
                        "hsprc": 333000000,
                        "stdDay": "20220101",
                        "crtnDay": "20220813",
                    }
                ]
            },
            "totalCount": 1080,
        },
    }
}


def test_parse_housing_price_maps_fields() -> None:
    result = building.parse_housing_price_response(HSPRC_RESPONSE)
    assert result["totalCount"] == 1080
    price = result["prices"][0]
    assert price["주택가격_원"] == 333000000
    assert price["생성일자"] == "20220813"
    assert price["건물명"] == "청운빌딩"


def test_parse_housing_price_empty() -> None:
    data = {"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}}
    result = building.parse_housing_price_response(data)
    assert result["prices"] == []
    assert "message" in result


# ---- 주택가격: fetch_building_housing_price ----

async def test_fetch_housing_price_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(HSPRC_RESPONSE))
    _patch_client(monkeypatch, client)

    result = await building.fetch_building_housing_price("11110", "10100")

    assert result["prices"][0]["주택가격_원"] == 333000000
    assert client.called_params is not None
    assert client.called_params["sigunguCd"] == "11110"
    assert client.called_params["bjdongCd"] == "10100"
    assert client.called_params["_type"] == "json"
    assert client.called_params["numOfRows"] == building.HSPRC_DEFAULT_NUM_OF_ROWS
    # 번·지·대지구분코드는 전송하지 않아야 한다
    assert "bun" not in client.called_params
    assert "ji" not in client.called_params
    assert "platGbCd" not in client.called_params
    # 검색일은 미지정 시 전송하지 않는다
    assert "startDate" not in client.called_params
    assert "endDate" not in client.called_params


async def test_fetch_housing_price_with_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(HSPRC_RESPONSE))
    _patch_client(monkeypatch, client)
    await building.fetch_building_housing_price(
        "11110", "10100", start_date="20220101", end_date="20221231"
    )
    assert client.called_params is not None
    assert client.called_params["startDate"] == "20220101"
    assert client.called_params["endDate"] == "20221231"


async def test_fetch_housing_price_missing_bjdong() -> None:
    result = await building.fetch_building_housing_price("11110", "")
    assert "error" in result
    assert "bjdong_cd" in result["error"]


async def test_fetch_housing_price_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "")
    result = await building.fetch_building_housing_price("11110", "10100")
    assert "error" in result


async def test_fetch_housing_price_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timeout"))
    _patch_client(monkeypatch, client)
    result = await building.fetch_building_housing_price("11110", "10100")
    assert "error" in result
    assert "시간 초과" in result["error"]
