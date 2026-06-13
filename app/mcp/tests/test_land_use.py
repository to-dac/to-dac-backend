# land_use 토지이용행위 검색 로직 단위 테스트 (httpx 모킹, 네트워크 호출 없음)
from typing import Any

import httpx
import pytest

from app.mcp import land_use
from app.mcp.settings import settings

SAMPLE_XML = (
    "<response><header><resultCode>0</resultCode><resultMsg>OK</resultMsg></header>"
    "<body><items>"
    "<item><LUN_NM>단독주택</LUN_NM><LUN_CD>03650</LUN_CD></item>"
    "<item><LUN_NM>공동주택</LUN_NM><LUN_CD>03651</LUN_CD></item>"
    "</items><numOfRows>5</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body>"
    "</response>"
)

ERROR_XML = (
    "<response><header><resultCode>30</resultCode>"
    "<resultMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</resultMsg></header></response>"
)

REGULATION_XML = (
    "<response><header><resultCode>0</resultCode><resultMsg>OK</resultMsg></header>"
    "<body><items>"
    "<item>"
    "<UNAME>제1종일반주거지역</UNAME>"
    "<UCODE_REF_LAW_CD>0000...1002001</UCODE_REF_LAW_CD>"
    "<UCODE>UQA121</UCODE>"
    "<actRegList>"
    "<ACT_NM>건축</ACT_NM><REG_NM>가능</REG_NM>"
    "<QNODE_CONDS><RNUM>06237</RNUM></QNODE_CONDS>"
    "<luInfoList><NODE_DESC>단독주택</NODE_DESC>"
    "<LU_REF_LAW_NM1>건축법 시행령 별표1</LU_REF_LAW_NM1></luInfoList>"
    "</actRegList>"
    "</item>"
    "<QnodeCond><QNODE_DESC>4층 이하 조건</QNODE_DESC><RNUM>06237</RNUM></QnodeCond>"
    "</items><totalCount>1</totalCount></body></response>"
)


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://apis.data.go.kr/x")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


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
    monkeypatch.setattr(land_use.httpx, "AsyncClient", lambda *a, **k: client)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "test-key")


# ---- parse_search_response ----

def test_parse_search_response_maps_fields() -> None:
    result = land_use.parse_search_response(SAMPLE_XML)
    assert result["totalCount"] == "2"
    assert len(result["acts"]) == 2
    assert result["acts"][0] == {"행위명": "단독주택", "행위코드": "03650"}


def test_parse_search_response_api_error() -> None:
    result = land_use.parse_search_response(ERROR_XML)
    assert "error" in result
    assert result["resultCode"] == "30"


def test_parse_search_response_invalid_xml() -> None:
    result = land_use.parse_search_response("not xml <<<")
    assert "error" in result


# ---- search_land_use_act ----

async def test_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_XML))
    _patch_client(monkeypatch, client)

    result = await land_use.search_land_use_act("단독주택")

    assert result["acts"][0]["행위코드"] == "03650"
    assert client.called_params is not None
    assert client.called_params["landUseNm"] == "단독주택"
    # Encoding 키는 unquote 되어 httpx가 1회만 인코딩하도록 전달되어야 한다
    assert "%" not in client.called_params["serviceKey"]


async def test_search_caps_num_of_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(SAMPLE_XML))
    _patch_client(monkeypatch, client)
    await land_use.search_land_use_act("단독주택", num_of_rows=99999)
    assert client.called_params is not None
    assert client.called_params["numOfRows"] == land_use.MAX_NUM_OF_ROWS


async def test_search_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "")
    result = await land_use.search_land_use_act("단독주택")
    assert "error" in result


async def test_search_missing_name() -> None:
    result = await land_use.search_land_use_act("")
    assert "error" in result


async def test_search_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse("", status_code=500))
    _patch_client(monkeypatch, client)
    result = await land_use.search_land_use_act("단독주택")
    assert "error" in result
    assert "500" in result["error"]


async def test_search_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timeout"))
    _patch_client(monkeypatch, client)
    result = await land_use.search_land_use_act("단독주택")
    assert "error" in result
    assert "시간 초과" in result["error"]


# ---- parse_regulation_response ----

def test_parse_regulation_response_maps_fields() -> None:
    result = land_use.parse_regulation_response(REGULATION_XML)
    assert result["totalCount"] == "1"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["지역지구명"] == "제1종일반주거지역"
    assert item["지역지구코드"] == "UQA121"
    reg = item["행위제한"][0]
    assert reg["행위"] == "건축"
    assert reg["가능여부"] == "가능"
    assert reg["근거법령"] == "건축법 시행령 별표1"
    # 조건은 RNUM(06237)으로 QnodeCond와 연결되어야 한다
    assert reg["조건"] == "4층 이하 조건"


def test_parse_regulation_response_api_error() -> None:
    result = land_use.parse_regulation_response(ERROR_XML)
    assert "error" in result
    assert result["resultCode"] == "30"


# ---- get_land_use_regulation ----

async def test_regulation_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(response=_FakeResponse(REGULATION_XML))
    _patch_client(monkeypatch, client)

    result = await land_use.get_land_use_regulation("11110", "UQA121", "단독주택")

    assert result["items"][0]["행위제한"][0]["가능여부"] == "가능"
    assert client.called_params is not None
    assert client.called_params["areaCd"] == "11110"
    assert client.called_params["ucodeList"] == "UQA121"
    assert client.called_params["landUseNm"] == "단독주택"
    assert "%" not in client.called_params["serviceKey"]


async def test_regulation_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATAGO_SERVICE_KEY", "")
    result = await land_use.get_land_use_regulation("11110", "UQA121", "단독주택")
    assert "error" in result


async def test_regulation_missing_params() -> None:
    result = await land_use.get_land_use_regulation("11110", "", "단독주택")
    assert "error" in result
    assert "ucode_list" in result["error"]


async def test_regulation_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timeout"))
    _patch_client(monkeypatch, client)
    result = await land_use.get_land_use_regulation("11110", "UQA121", "단독주택")
    assert "error" in result
    assert "시간 초과" in result["error"]
