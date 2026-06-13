# land_info_server MCP 서버의 툴 등록/실행 테스트
from typing import Any

import pytest

from app.mcp import vworld
from app.mcp.land_info_server import (
    get_building_capacity,
    get_building_headroom,
    get_building_housing_price,
    get_land_characteristics,
    get_land_use_plan,
    get_land_use_regulation_tool,
    mcp,
    search_land_use_act_tool,
)


async def test_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_land_characteristics" in names

    tool = next(t for t in tools if t.name == "get_land_characteristics")
    assert "pnu" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["pnu"]


async def test_land_use_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "search_land_use_act_tool" in names

    tool = next(t for t in tools if t.name == "search_land_use_act_tool")
    assert "land_use_nm" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["land_use_nm"]


async def test_land_use_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_search(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"acts": [{"행위명": "단독주택", "행위코드": "03650"}], "totalCount": "1"}

    monkeypatch.setattr("app.mcp.land_info_server.search_land_use_act", fake_search)

    result = await search_land_use_act_tool(land_use_nm="단독주택")

    assert result["acts"][0]["행위코드"] == "03650"
    assert captured["land_use_nm"] == "단독주택"


async def test_regulation_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_land_use_regulation_tool" in names

    tool = next(t for t in tools if t.name == "get_land_use_regulation_tool")
    props = tool.inputSchema["properties"]
    assert {"area_cd", "ucode_list", "land_use_nm"} <= set(props)
    assert set(tool.inputSchema["required"]) == {"area_cd", "ucode_list", "land_use_nm"}


async def test_regulation_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_reg(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"items": [{"지역지구명": "제1종일반주거지역", "행위제한": []}], "totalCount": "1"}

    monkeypatch.setattr("app.mcp.land_info_server.get_land_use_regulation", fake_reg)

    result = await get_land_use_regulation_tool(
        area_cd="11110", ucode_list="UQA121", land_use_nm="단독주택"
    )

    assert result["items"][0]["지역지구명"] == "제1종일반주거지역"
    assert captured["area_cd"] == "11110"
    assert captured["ucode_list"] == "UQA121"


async def test_building_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_building_capacity" in names

    tool = next(t for t in tools if t.name == "get_building_capacity")
    assert "pnu" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["pnu"]


async def test_building_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"buildings": [{"건폐율_％": 7.28}], "totalCount": 1}

    monkeypatch.setattr("app.mcp.land_info_server.fetch_building_title", fake_fetch)

    result = await get_building_capacity(pnu="1111010100100010000")

    assert result["buildings"][0]["건폐율_％"] == 7.28
    assert captured["pnu"] == "1111010100100010000"


async def test_housing_price_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_building_housing_price" in names

    tool = next(t for t in tools if t.name == "get_building_housing_price")
    props = tool.inputSchema["properties"]
    assert {"sigungu_cd", "bjdong_cd"} <= set(props)
    assert set(tool.inputSchema["required"]) == {"sigungu_cd", "bjdong_cd"}
    # 번·지·대지구분코드는 도구 입력에 노출하지 않는다
    assert "bun" not in props
    assert "ji" not in props
    assert "plat_gb_cd" not in props


async def test_housing_price_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"prices": [{"주택가격_원": 333000000}], "totalCount": 1}

    monkeypatch.setattr("app.mcp.land_info_server.fetch_building_housing_price", fake_fetch)

    result = await get_building_housing_price(sigungu_cd="11110", bjdong_cd="10100")

    assert result["prices"][0]["주택가격_원"] == 333000000
    assert captured["sigungu_cd"] == "11110"
    assert captured["bjdong_cd"] == "10100"


async def test_headroom_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_building_headroom" in names

    tool = next(t for t in tools if t.name == "get_building_headroom")
    assert "pnu" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["pnu"]


async def test_headroom_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_calc(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"여력": {"건폐율_％p": 40.0}}

    monkeypatch.setattr("app.mcp.land_info_server.calculate_building_headroom", fake_calc)

    result = await get_building_headroom(pnu="1111010100100010000")

    assert result["여력"]["건폐율_％p"] == 40.0
    assert captured["pnu"] == "1111010100100010000"


async def test_land_use_plan_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_land_use_plan" in names

    tool = next(t for t in tools if t.name == "get_land_use_plan")
    assert "pnu" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["pnu"]


async def test_land_use_plan_tool_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"area_cd": "41461", "ucode_list": "UQA001", "건수": 1}

    monkeypatch.setattr("app.mcp.land_info_server.fetch_land_use_plan", fake_fetch)

    result = await get_land_use_plan(pnu="4146110200100010000")

    assert result["ucode_list"] == "UQA001"
    assert captured["pnu"] == "4146110200100010000"


async def test_tool_delegates_to_vworld(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"fields": [{"지목명": "대"}]}

    monkeypatch.setattr(
        "app.mcp.land_info_server.fetch_land_characteristics", fake_fetch
    )

    result = await get_land_characteristics(pnu="1111010100100010000", stdr_year="2025")

    assert result["fields"][0]["지목명"] == "대"
    assert captured["pnu"] == "1111010100100010000"
    assert captured["stdr_year"] == "2025"


def test_field_map_has_core_fields() -> None:
    # 핵심 토지특성 필드가 매핑에 포함되어 있는지 회귀 방지
    for raw_key in ("lndcgrCodeNm", "lndpclAr", "pblntfPclnd", "prposArea1Nm"):
        assert raw_key in vworld.FIELD_MAP
