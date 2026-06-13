# capacity 건축물 여력 계산 로직 단위 테스트 (vworld/building 함수 모킹, 네트워크 없음)
from typing import Any

import pytest

from app.mcp import capacity

LAND_OK: dict[str, Any] = {
    "fields": [{"용도지역1": "제1종일반주거지역", "토지면적_㎡": "1000"}]
}
BUILDING_OK: dict[str, Any] = {
    "buildings": [
        {"건축면적_㎡": 200.0, "용적률산정연면적_㎡": 500.0, "연면적_㎡": 600.0, "건폐율_％": 20.0, "용적률_％": 50.0}
    ]
}


def _patch(monkeypatch: pytest.MonkeyPatch, land: Any, building: Any) -> None:
    async def fake_land(**_kwargs: Any) -> Any:
        return land

    async def fake_building(**_kwargs: Any) -> Any:
        return building

    monkeypatch.setattr(capacity, "fetch_land_characteristics", fake_land)
    monkeypatch.setattr(capacity, "fetch_building_title", fake_building)


# ---- lookup_zoning_limit ----

def test_lookup_zoning_limit_exact() -> None:
    limit = capacity.lookup_zoning_limit("제1종일반주거지역")
    assert limit == {"건폐율": 60, "용적률": 200}


def test_lookup_zoning_limit_ignores_spaces() -> None:
    assert capacity.lookup_zoning_limit("제 2종 일반주거지역") == {"건폐율": 60, "용적률": 250}


def test_lookup_zoning_limit_unknown() -> None:
    assert capacity.lookup_zoning_limit("지정되지않음") is None
    assert capacity.lookup_zoning_limit(None) is None


# ---- calculate_building_headroom ----

async def test_headroom_computes_from_areas(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, LAND_OK, BUILDING_OK)
    result = await capacity.calculate_building_headroom("1111010100100010000")

    assert result["용도지역"] == "제1종일반주거지역"
    assert result["대지면적_㎡"] == 1000.0
    assert result["법정상한"] == {"건폐율_％": 60, "용적률_％": 200}
    # 면적 기반: 건폐율 200/1000=20%, 용적률 500/1000=50%
    assert result["현재"]["건폐율_％"] == 20.0
    assert result["현재"]["용적률_％"] == 50.0
    # 여력: 건폐 60-20=40%p, 용적 200-50=150%p
    assert result["여력"]["건폐율_％p"] == 40.0
    assert result["여력"]["용적률_％p"] == 150.0
    # 추가 가능 면적: 1000*40/100=400, 1000*150/100=1500
    assert result["여력"]["추가건축가능_건축면적_㎡"] == 400.0
    assert result["여력"]["추가건축가능_연면적_㎡"] == 1500.0


async def test_headroom_no_building_means_full(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, LAND_OK, {"buildings": []})
    result = await capacity.calculate_building_headroom("1111010100100010000")
    assert result["여력"]["건폐율_％p"] == 60.0
    assert result["여력"]["추가건축가능_연면적_㎡"] == 2000.0
    assert "message" in result


async def test_headroom_unknown_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"fields": [{"용도지역1": "지정되지않음", "토지면적_㎡": "1000"}]}, BUILDING_OK)
    result = await capacity.calculate_building_headroom("1111010100100010000")
    assert "법정상한" not in result
    assert "message" in result


async def test_headroom_falls_back_to_building_plat_area(monkeypatch: pytest.MonkeyPatch) -> None:
    land = {"fields": [{"용도지역1": "제1종일반주거지역", "토지면적_㎡": None}]}
    building = {
        "buildings": [
            {"건축면적_㎡": 100.0, "용적률산정연면적_㎡": 100.0, "연면적_㎡": 100.0, "대지면적_㎡": 500.0}
        ]
    }
    _patch(monkeypatch, land, building)
    result = await capacity.calculate_building_headroom("1111010100100010000")
    assert result["대지면적_㎡"] == 500.0
    assert result["현재"]["건폐율_％"] == 20.0  # 100/500*100


async def test_headroom_land_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"error": "INCORRECT_KEY"}, BUILDING_OK)
    result = await capacity.calculate_building_headroom("1111010100100010000")
    assert "error" in result
    assert "토지특성" in result["error"]


async def test_headroom_building_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, LAND_OK, {"error": "HTTP 500"})
    result = await capacity.calculate_building_headroom("1111010100100010000")
    assert "error" in result
    assert "건축물대장" in result["error"]
