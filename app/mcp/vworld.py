# V-World 토지특성 조회 API 호출 및 응답 정제 (MCP 비의존 순수 로직)
import logging
from typing import Any

import httpx

from app.mcp.settings import settings

logger = logging.getLogger(__name__)

ENDPOINT = "getLandCharacteristics"
DEFAULT_FORMAT = "json"
DEFAULT_NUM_OF_ROWS = 10
DEFAULT_PAGE_NO = 1
MAX_NUM_OF_ROWS = 1000
REQUEST_TIMEOUT = 10.0

# V-World 응답 원본 키 → 사람이 읽을 수 있는 의미 키 매핑
FIELD_MAP: dict[str, str] = {
    "pnu": "필지고유번호",
    "ldCodeNm": "법정동명",
    "regstrSeCodeNm": "대장구분",
    "lndcgrCodeNm": "지목명",
    "lndpclAr": "토지면적_㎡",
    "prposArea1Nm": "용도지역1",
    "prposArea2Nm": "용도지역2",
    "ladUseSittnNm": "토지이용상황",
    "tpgrphHgCodeNm": "지형고저",
    "tpgrphFrmCodeNm": "지형형상",
    "roadSideCodeNm": "도로접면",
    "pblntfPclnd": "공시지가_원㎡",
    "lastUpdtDt": "데이터기준일자",
    "stdrYear": "기준연도",
}


async def fetch_land_characteristics(
    pnu: str,
    stdr_year: str | None = None,
    num_of_rows: int = DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """PNU로 토지 기본 정보를 조회한다. 오류 시 예외 대신 {"error": ...} 를 반환."""
    if not settings.VWORLD_API_KEY:
        logger.warning("VWORLD_API_KEY가 설정되지 않았습니다")
        return {"error": "VWORLD_API_KEY가 설정되지 않았습니다. app/mcp/.env 를 확인하세요."}

    if not pnu:
        return {"error": "필수 파라미터 'pnu'가 없습니다."}

    params: dict[str, Any] = {
        "key": settings.VWORLD_API_KEY,
        "pnu": pnu,
        "format": DEFAULT_FORMAT,
        "numOfRows": min(num_of_rows, MAX_NUM_OF_ROWS),
        "pageNo": page_no,
    }
    if stdr_year:
        params["stdrYear"] = stdr_year

    url = f"{settings.VWORLD_BASE_URL}/{ENDPOINT}"
    # V-World는 Referer 헤더로 등록 도메인을 검증한다. 없으면 INCORRECT_KEY 로 거부됨.
    headers = {"Referer": settings.VWORLD_REFERER} if settings.VWORLD_REFERER else {}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("V-World 요청 타임아웃: pnu=%s", pnu)
        return {"error": "V-World API 요청이 시간 초과되었습니다."}
    except httpx.HTTPStatusError as exc:
        logger.warning("V-World HTTP 오류: %s", exc.response.status_code)
        return {"error": f"V-World API 오류 (HTTP {exc.response.status_code})"}
    except httpx.HTTPError as exc:
        logger.warning("V-World 요청 실패: %s", exc)
        return {"error": "V-World API 요청에 실패했습니다."}

    logger.info("V-World 토지특성 조회 성공: pnu=%s", pnu)
    return parse_response(data)


def parse_response(data: Any) -> dict[str, Any]:
    """V-World 응답에서 필지 레코드를 추출해 정제된 dict로 변환."""
    records = _extract_records(data)
    if not records:
        return {"fields": [], "raw": data, "message": "조회 결과가 없습니다."}

    fields = [_map_fields(record) for record in records]
    return {"fields": fields, "raw": data}


def _extract_records(data: Any) -> list[dict[str, Any]]:
    """응답 본문에서 필지 레코드 리스트를 방어적으로 찾아낸다."""
    if not isinstance(data, dict):
        return []
    for value in data.values():
        if isinstance(value, dict) and "field" in value:
            field = value["field"]
            if isinstance(field, list):
                return [item for item in field if isinstance(item, dict)]
            if isinstance(field, dict):
                return [field]
    return []


def _map_fields(record: dict[str, Any]) -> dict[str, Any]:
    """원본 키를 한국어 의미 키로 매핑. 매핑 없는 키는 원본 키로 보존."""
    return {FIELD_MAP.get(key, key): value for key, value in record.items()}
