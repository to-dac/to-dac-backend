# 공공데이터포털 토지이용규제정보서비스 호출 및 응답 정제 (MCP 비의존 순수 로직)
import logging
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import httpx

from app.mcp.settings import settings

logger = logging.getLogger(__name__)

SEARCH_ENDPOINT = "DTsearchLunCd"
REGULATION_ENDPOINT = "DTarLandUseInfo"
DEFAULT_NUM_OF_ROWS = 10
DEFAULT_PAGE_NO = 1
MAX_NUM_OF_ROWS = 100
REQUEST_TIMEOUT = 10.0
RESULT_OK = "0"


async def _get_xml(endpoint: str, params: dict[str, Any]) -> str | dict[str, Any]:
    """엔드포인트를 GET 호출해 응답 text(str)를 반환한다. 오류 시 {"error": ...} dict 반환.

    응답은 charset=euc-kr 이며 XML 선언이 없으므로 httpx가 디코딩한 text를 그대로 넘긴다.
    Encoding 인증키를 unquote 하여 httpx가 정확히 1회만 인코딩하도록 한다 (이중 인코딩 방지).
    """
    merged = {"serviceKey": unquote(settings.DATAGO_SERVICE_KEY), **params}
    url = f"{settings.DATAGO_BASE_URL}/{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=merged)
            response.raise_for_status()
            return response.text
    except httpx.TimeoutException:
        logger.warning("토지이용규제 요청 타임아웃: %s", endpoint)
        return {"error": "토지이용규제 API 요청이 시간 초과되었습니다."}
    except httpx.HTTPStatusError as exc:
        logger.warning("토지이용규제 HTTP 오류: %s", exc.response.status_code)
        return {"error": f"토지이용규제 API 오류 (HTTP {exc.response.status_code})"}
    except httpx.HTTPError as exc:
        logger.warning("토지이용규제 요청 실패: %s", exc)
        return {"error": "토지이용규제 API 요청에 실패했습니다."}


async def search_land_use_act(
    land_use_nm: str,
    num_of_rows: int = DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """토지이용행위명으로 행위명·행위코드를 검색한다. 오류 시 예외 대신 {"error": ...} 반환."""
    if not settings.DATAGO_SERVICE_KEY:
        logger.warning("DTarLandUseInfo_API_KEY가 설정되지 않았습니다")
        return {"error": "DTarLandUseInfo_API_KEY가 설정되지 않았습니다. app/mcp/.env 를 확인하세요."}

    if not land_use_nm:
        return {"error": "필수 파라미터 'land_use_nm'(토지이용행위명)이 없습니다."}

    result = await _get_xml(
        SEARCH_ENDPOINT,
        {
            "landUseNm": land_use_nm,
            "numOfRows": min(num_of_rows, MAX_NUM_OF_ROWS),
            "pageNum": page_no,
        },
    )
    if isinstance(result, dict):
        return result

    logger.info("토지이용행위 검색 성공: landUseNm=%s", land_use_nm)
    return parse_search_response(result)


async def get_land_use_regulation(
    area_cd: str,
    ucode_list: str,
    land_use_nm: str,
) -> dict[str, Any]:
    """시군구·지역지구별로 특정 토지이용행위의 가능여부(행위제한)를 조회한다.

    오류 시 예외 대신 {"error": ...} 를 반환한다.

    Args:
        area_cd: 시군구코드(5자리). 예: "11110"(서울 종로구). PNU 앞 5자리.
        ucode_list: 지역지구코드. 예: "UQA121"(제1종일반주거지역). 쉼표로 다건 가능.
        land_use_nm: 토지이용행위명. 예: "단독주택".
    """
    if not settings.DATAGO_SERVICE_KEY:
        logger.warning("DTarLandUseInfo_API_KEY가 설정되지 않았습니다")
        return {"error": "DTarLandUseInfo_API_KEY가 설정되지 않았습니다. app/mcp/.env 를 확인하세요."}

    missing = [
        name
        for name, value in (("area_cd", area_cd), ("ucode_list", ucode_list), ("land_use_nm", land_use_nm))
        if not value
    ]
    if missing:
        return {"error": f"필수 파라미터가 없습니다: {', '.join(missing)}"}

    result = await _get_xml(
        REGULATION_ENDPOINT,
        {"areaCd": area_cd, "ucodeList": ucode_list, "landUseNm": land_use_nm},
    )
    if isinstance(result, dict):
        return result

    logger.info("토지이용규제 조회 성공: areaCd=%s ucode=%s", area_cd, ucode_list)
    return parse_regulation_response(result)


def parse_search_response(text: str) -> dict[str, Any]:
    """DTsearchLunCd XML 응답에서 행위명·행위코드 목록을 추출한다."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("토지이용규제 응답 XML 파싱 실패")
        return {"error": "응답 XML 파싱에 실패했습니다.", "raw": text}

    result_code = root.findtext(".//resultCode")
    if result_code is not None and result_code != RESULT_OK:
        result_msg = root.findtext(".//resultMsg") or ""
        return {"error": f"토지이용규제 API 오류 ({result_code}): {result_msg}", "resultCode": result_code}

    acts = [
        {"행위명": item.findtext("LUN_NM"), "행위코드": item.findtext("LUN_CD")}
        for item in root.findall(".//items/item")
    ]
    return {"acts": acts, "totalCount": root.findtext(".//totalCount")}


def parse_regulation_response(text: str) -> dict[str, Any]:
    """DTarLandUseInfo XML 응답에서 지역지구별 행위제한(가능여부)을 추출한다."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("토지이용규제 응답 XML 파싱 실패")
        return {"error": "응답 XML 파싱에 실패했습니다.", "raw": text}

    result_code = root.findtext(".//resultCode")
    if result_code is not None and result_code != RESULT_OK:
        result_msg = root.findtext(".//resultMsg") or ""
        return {"error": f"토지이용규제 API 오류 ({result_code}): {result_msg}", "resultCode": result_code}

    # 조건 설명: RNUM -> QNODE_DESC (행위제한이 RNUM으로 조건을 참조한다)
    conds = {
        qc.findtext("RNUM"): qc.findtext("QNODE_DESC")
        for qc in root.findall(".//items/QnodeCond")
        if qc.findtext("RNUM")
    }

    items = []
    for item in root.findall(".//items/item"):
        regulations = []
        for act in item.findall("actRegList"):
            lu = act.find("luInfoList")
            rnum = act.findtext("QNODE_CONDS/RNUM")
            regulations.append(
                {
                    "행위": act.findtext("ACT_NM"),
                    "가능여부": act.findtext("REG_NM"),
                    "근거법령": lu.findtext("LU_REF_LAW_NM1") if lu is not None else None,
                    "조건": conds.get(rnum) if rnum else None,
                }
            )
        items.append(
            {
                "지역지구명": item.findtext("UNAME"),
                "지역지구코드": item.findtext("UCODE"),
                "행위제한": regulations,
            }
        )
    return {"items": items, "totalCount": root.findtext(".//totalCount")}
