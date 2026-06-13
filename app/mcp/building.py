# 건축HUB 건축물대장 표제부 조회 및 응답 정제 (건축물 여력 계산용, MCP 비의존 순수 로직)
import logging
from typing import Any
from urllib.parse import unquote

import httpx

from app.mcp.settings import settings

logger = logging.getLogger(__name__)

TITLE_ENDPOINT = "getBrTitleInfo"
HSPRC_ENDPOINT = "getBrHsprcInfo"
DEFAULT_NUM_OF_ROWS = 10
HSPRC_DEFAULT_NUM_OF_ROWS = 20
DEFAULT_PAGE_NO = 1
MAX_NUM_OF_ROWS = 100
REQUEST_TIMEOUT = 10.0
RESULT_OK = "00"
PNU_LENGTH = 19

# PNU 11번째 자리(필지구분) → 건축물대장 platGbCd 매핑 (PNU 1:대지/2:산 → API 0:대지/1:산)
_PLAT_GB_MAP = {"1": "0", "2": "1"}

# 표제부 응답 원본 키 → 사람이 읽을 수 있는 의미 키 매핑 (건축물 여력 관련 핵심 필드)
FIELD_MAP: dict[str, str] = {
    "platPlc": "지번주소",
    "newPlatPlc": "도로명주소",
    "bldNm": "건물명",
    "mainPurpsCdNm": "주용도",
    "strctCdNm": "구조",
    "platArea": "대지면적_㎡",
    "archArea": "건축면적_㎡",
    "bcRat": "건폐율_％",
    "totArea": "연면적_㎡",
    "vlRatEstmTotArea": "용적률산정연면적_㎡",
    "vlRat": "용적률_％",
    "grndFlrCnt": "지상층수",
    "ugrndFlrCnt": "지하층수",
    "hhldCnt": "세대수",
    "useAprDay": "사용승인일",
}

# 주택가격(getBrHsprcInfo) 응답 원본 키 → 의미 키 매핑
HSPRC_FIELD_MAP: dict[str, str] = {
    "platPlc": "지번주소",
    "newPlatPlc": "도로명주소",
    "bldNm": "건물명",
    "hsprc": "주택가격_원",
    "stdDay": "가격기준일",
    "crtnDay": "생성일자",
}


def split_pnu(pnu: str) -> dict[str, str]:
    """PNU(19자리)를 건축물대장 조회 파라미터로 분해한다."""
    return {
        "sigunguCd": pnu[0:5],
        "bjdongCd": pnu[5:10],
        "platGbCd": _PLAT_GB_MAP.get(pnu[10], "0"),
        "bun": pnu[11:15],
        "ji": pnu[15:19],
    }


async def fetch_building_title(
    pnu: str,
    num_of_rows: int = DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """PNU로 건축물대장 표제부(대지면적·건폐율·용적률 등)를 조회한다.

    건축물 여력(추가 건축 가능량) 판단의 기초 데이터를 제공한다.
    오류 시 예외 대신 {"error": ...} 를 반환한다.
    """
    if not settings.DATAGO_SERVICE_KEY:
        logger.warning("DTarLandUseInfo_API_KEY가 설정되지 않았습니다")
        return {"error": "DTarLandUseInfo_API_KEY가 설정되지 않았습니다. app/mcp/.env 를 확인하세요."}

    if not pnu or not pnu.isdigit() or len(pnu) != PNU_LENGTH:
        return {"error": f"PNU는 {PNU_LENGTH}자리 숫자여야 합니다. 입력: {pnu!r}"}

    # Encoding 인증키를 unquote 하여 httpx가 정확히 1회만 인코딩하도록 한다 (이중 인코딩 방지)
    params: dict[str, Any] = {
        "serviceKey": unquote(settings.DATAGO_SERVICE_KEY),
        **split_pnu(pnu),
        "_type": "json",
        "numOfRows": min(num_of_rows, MAX_NUM_OF_ROWS),
        "pageNo": page_no,
    }
    url = f"{settings.DATAGO_BASE_URL_BLD}/{TITLE_ENDPOINT}"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("건축물대장 요청 타임아웃: pnu=%s", pnu)
        return {"error": "건축물대장 API 요청이 시간 초과되었습니다."}
    except httpx.HTTPStatusError as exc:
        logger.warning("건축물대장 HTTP 오류: %s", exc.response.status_code)
        return {"error": f"건축물대장 API 오류 (HTTP {exc.response.status_code})"}
    except httpx.HTTPError as exc:
        logger.warning("건축물대장 요청 실패: %s", exc)
        return {"error": "건축물대장 API 요청에 실패했습니다."}

    logger.info("건축물대장 표제부 조회 성공: pnu=%s", pnu)
    return parse_response(data)


async def fetch_building_housing_price(
    sigungu_cd: str,
    bjdong_cd: str,
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = HSPRC_DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """시군구·법정동코드로 건축물대장 주택가격(공동주택가격 등)을 조회한다.

    번·지·대지구분코드는 전송하지 않고 시군구·법정동 단위로 조회한다.
    오류 시 예외 대신 {"error": ...} 를 반환한다.

    Args:
        sigungu_cd: 시군구코드(5자리). 예: "11110".
        bjdong_cd: 법정동코드(5자리). 예: "10100".
        start_date: 검색 시작일(YYYYMMDD). 생략 가능.
        end_date: 검색 종료일(YYYYMMDD). 생략 가능.
        num_of_rows: 리스트 수 (기본 20, 최대 100).
        page_no: 페이지 번호 (기본 1).
    """
    if not settings.DATAGO_SERVICE_KEY:
        logger.warning("DTarLandUseInfo_API_KEY가 설정되지 않았습니다")
        return {"error": "DTarLandUseInfo_API_KEY가 설정되지 않았습니다. app/mcp/.env 를 확인하세요."}

    missing = [
        name
        for name, value in (("sigungu_cd", sigungu_cd), ("bjdong_cd", bjdong_cd))
        if not value
    ]
    if missing:
        return {"error": f"필수 파라미터가 없습니다: {', '.join(missing)}"}

    # Encoding 인증키를 unquote 하여 httpx가 정확히 1회만 인코딩하도록 한다 (이중 인코딩 방지)
    params: dict[str, Any] = {
        "serviceKey": unquote(settings.DATAGO_SERVICE_KEY),
        "sigunguCd": sigungu_cd,
        "bjdongCd": bjdong_cd,
        "_type": "json",
        "numOfRows": min(num_of_rows, MAX_NUM_OF_ROWS),
        "pageNo": page_no,
    }
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date

    url = f"{settings.DATAGO_BASE_URL_BLD}/{HSPRC_ENDPOINT}"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("주택가격 요청 타임아웃: sigunguCd=%s bjdongCd=%s", sigungu_cd, bjdong_cd)
        return {"error": "건축물대장 API 요청이 시간 초과되었습니다."}
    except httpx.HTTPStatusError as exc:
        logger.warning("주택가격 HTTP 오류: %s", exc.response.status_code)
        return {"error": f"건축물대장 API 오류 (HTTP {exc.response.status_code})"}
    except httpx.HTTPError as exc:
        logger.warning("주택가격 요청 실패: %s", exc)
        return {"error": "건축물대장 API 요청에 실패했습니다."}

    logger.info("건축물대장 주택가격 조회 성공: sigunguCd=%s bjdongCd=%s", sigungu_cd, bjdong_cd)
    return parse_housing_price_response(data)


def parse_response(data: Any) -> dict[str, Any]:
    """건축물대장 JSON 응답에서 표제부 레코드를 추출해 정제한다."""
    return _parse_items(data, FIELD_MAP, "buildings")


def parse_housing_price_response(data: Any) -> dict[str, Any]:
    """건축물대장 JSON 응답에서 주택가격 레코드를 추출해 정제한다."""
    return _parse_items(data, HSPRC_FIELD_MAP, "prices")


def _parse_items(data: Any, field_map: dict[str, str], result_key: str) -> dict[str, Any]:
    """공통 응답 파서: header 오류 확인 후 items.item 을 field_map 으로 정제한다."""
    if not isinstance(data, dict):
        return {"error": "응답 형식이 올바르지 않습니다.", "raw": data}

    body = data.get("response", {}).get("body", {})
    header = data.get("response", {}).get("header", {})
    result_code = header.get("resultCode")
    if result_code is not None and result_code != RESULT_OK:
        return {
            "error": f"건축물대장 API 오류 ({result_code}): {header.get('resultMsg', '')}",
            "resultCode": result_code,
        }

    records = _extract_records(body)
    if not records:
        return {result_key: [], "totalCount": body.get("totalCount"), "message": "조회 결과가 없습니다."}

    mapped = [_map_fields(record, field_map) for record in records]
    return {result_key: mapped, "totalCount": body.get("totalCount")}


def _extract_records(body: Any) -> list[dict[str, Any]]:
    """body.items.item 에서 레코드 리스트를 방어적으로 추출한다 (단건은 dict, 다건은 list)."""
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    if not isinstance(items, dict):
        return []
    item = items.get("item")
    if isinstance(item, list):
        return [x for x in item if isinstance(x, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def _map_fields(record: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    """원본 키를 한국어 의미 키로 매핑. 매핑 없는 키는 원본 키로 보존."""
    return {field_map.get(key, key): value for key, value in record.items()}
