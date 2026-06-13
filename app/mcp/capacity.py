# 건축물 여력(추가 건축 가능량) 계산 — 토지특성 + 건축물대장 조합 (MCP 비의존 순수 로직)
import logging
from typing import Any

from app.mcp.building import fetch_building_title
from app.mcp.vworld import fetch_land_characteristics

logger = logging.getLogger(__name__)

# 국토계획법 시행령 제84조(건폐율)·제85조(용적률) 용도지역별 표준 상한 (%, %)
# 주의: 전국 공통 상한선이며, 지자체 조례가 더 엄격하게 정할 수 있다 (실제 여력은 이보다 작을 수 있음).
ZONING_LIMITS: dict[str, dict[str, int]] = {
    "제1종전용주거지역": {"건폐율": 50, "용적률": 100},
    "제2종전용주거지역": {"건폐율": 50, "용적률": 150},
    "제1종일반주거지역": {"건폐율": 60, "용적률": 200},
    "제2종일반주거지역": {"건폐율": 60, "용적률": 250},
    "제3종일반주거지역": {"건폐율": 50, "용적률": 300},
    "준주거지역": {"건폐율": 70, "용적률": 500},
    "중심상업지역": {"건폐율": 90, "용적률": 1500},
    "일반상업지역": {"건폐율": 80, "용적률": 1300},
    "근린상업지역": {"건폐율": 70, "용적률": 900},
    "유통상업지역": {"건폐율": 80, "용적률": 1100},
    "전용공업지역": {"건폐율": 70, "용적률": 300},
    "일반공업지역": {"건폐율": 70, "용적률": 350},
    "준공업지역": {"건폐율": 70, "용적률": 400},
    "보전녹지지역": {"건폐율": 20, "용적률": 80},
    "생산녹지지역": {"건폐율": 20, "용적률": 100},
    "자연녹지지역": {"건폐율": 20, "용적률": 100},
    "보전관리지역": {"건폐율": 20, "용적률": 80},
    "생산관리지역": {"건폐율": 20, "용적률": 80},
    "계획관리지역": {"건폐율": 40, "용적률": 100},
    "농림지역": {"건폐율": 20, "용적률": 80},
    "자연환경보전지역": {"건폐율": 20, "용적률": 80},
}

LEGAL_BASIS = "국토계획법 시행령 표준 상한 (지자체 조례가 더 엄격할 수 있어 실제 여력은 더 작을 수 있음)"


def _to_float(value: Any) -> float | None:
    """문자열·숫자·빈값을 float로 안전 변환. 변환 불가 시 None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def lookup_zoning_limit(zone_name: str | None) -> dict[str, int] | None:
    """용도지역명으로 법정 상한(건폐율·용적률)을 조회한다. 공백 차이를 무시한다."""
    if not zone_name:
        return None
    key = zone_name.replace(" ", "")
    return ZONING_LIMITS.get(key)


async def calculate_building_headroom(pnu: str) -> dict[str, Any]:
    """PNU로 토지특성·건축물대장을 조회해 건축물 여력(추가 건축 가능량)을 계산한다.

    여력 = 법정 상한(용도지역 기준) − 현재값. 오류 시 {"error": ...} 반환.
    """
    land = await fetch_land_characteristics(pnu=pnu)
    if "error" in land:
        return {"error": f"토지특성 조회 실패: {land['error']}"}

    building = await fetch_building_title(pnu=pnu)
    if "error" in building:
        return {"error": f"건축물대장 조회 실패: {building['error']}"}

    land_fields = land.get("fields") or []
    if not land_fields:
        return {"error": "해당 PNU의 토지특성 정보가 없습니다.", "pnu": pnu}
    land_rec = land_fields[0]

    zone_name = land_rec.get("용도지역1")
    plat_area = _to_float(land_rec.get("토지면적_㎡"))

    buildings = building.get("buildings") or []
    # 대지면적: V-World 토지면적 우선, 없으면 건축물대장 대지면적
    if not plat_area and buildings:
        plat_area = _to_float(buildings[0].get("대지면적_㎡"))

    limit = lookup_zoning_limit(zone_name)
    result: dict[str, Any] = {
        "pnu": pnu,
        "용도지역": zone_name,
        "대지면적_㎡": plat_area,
        "기준": LEGAL_BASIS,
    }

    if limit is None:
        result["message"] = f"용도지역 '{zone_name}'의 법정 상한 기준이 표준표에 없어 여력을 계산할 수 없습니다."
        return result

    result["법정상한"] = {"건폐율_％": limit["건폐율"], "용적률_％": limit["용적률"]}

    if not buildings:
        # 건물이 없으면 대지 전체가 여력
        result["현재"] = {"건축면적_㎡": 0.0, "용적률산정연면적_㎡": 0.0, "건폐율_％": 0.0, "용적률_％": 0.0}
        result["여력"] = _compute_headroom(plat_area, 0.0, 0.0, limit)
        result["message"] = "등록된 건축물이 없어 대지 전체가 여력입니다."
        return result

    # 필지 단위 합산: 건폐율=Σ건축면적/대지면적, 용적률=Σ용적률산정연면적/대지면적
    arch_sum = sum(_to_float(b.get("건축면적_㎡")) or 0.0 for b in buildings)
    vlrat_area_sum = sum(_to_float(b.get("용적률산정연면적_㎡")) or 0.0 for b in buildings)

    cur_bc = round(arch_sum / plat_area * 100, 2) if plat_area else None
    cur_vl = round(vlrat_area_sum / plat_area * 100, 2) if plat_area else None
    # 면적 기반 산정이 0이면 대장의 직접 비율값으로 보정 (대표 = 연면적 최대 건물)
    rep = max(buildings, key=lambda b: _to_float(b.get("연면적_㎡")) or 0.0)
    if not cur_bc:
        cur_bc = _to_float(rep.get("건폐율_％"))
    if not cur_vl:
        cur_vl = _to_float(rep.get("용적률_％"))

    result["현재"] = {
        "건축면적_㎡": round(arch_sum, 2),
        "용적률산정연면적_㎡": round(vlrat_area_sum, 2),
        "건폐율_％": cur_bc,
        "용적률_％": cur_vl,
    }
    result["여력"] = _compute_headroom(plat_area, cur_bc, cur_vl, limit)
    return result


def _compute_headroom(
    plat_area: float | None,
    cur_bc: float | None,
    cur_vl: float | None,
    limit: dict[str, int],
) -> dict[str, Any]:
    """법정 상한 대비 여력(％p) 및 추가 건축 가능 면적(㎡)을 계산한다."""
    headroom: dict[str, Any] = {}

    if cur_bc is not None:
        headroom["건폐율_％p"] = round(limit["건폐율"] - cur_bc, 2)
    if cur_vl is not None:
        headroom["용적률_％p"] = round(limit["용적률"] - cur_vl, 2)

    if plat_area:
        if cur_bc is not None:
            add_arch = plat_area * (limit["건폐율"] - cur_bc) / 100
            headroom["추가건축가능_건축면적_㎡"] = round(max(add_arch, 0.0), 2)
        if cur_vl is not None:
            add_floor = plat_area * (limit["용적률"] - cur_vl) / 100
            headroom["추가건축가능_연면적_㎡"] = round(max(add_floor, 0.0), 2)

    return headroom
