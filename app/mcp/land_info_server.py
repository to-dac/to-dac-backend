# V-World 토지 기본 정보 조회 독립 실행 MCP 서버 (FastMCP)
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.land_use import (
    DEFAULT_NUM_OF_ROWS as LAND_USE_DEFAULT_NUM_OF_ROWS,
)
from app.mcp.land_use import (
    DEFAULT_PAGE_NO as LAND_USE_DEFAULT_PAGE_NO,
)
from app.mcp.building import (
    DEFAULT_NUM_OF_ROWS as BLD_DEFAULT_NUM_OF_ROWS,
)
from app.mcp.building import (
    DEFAULT_PAGE_NO as BLD_DEFAULT_PAGE_NO,
)
from app.mcp.building import (
    HSPRC_DEFAULT_NUM_OF_ROWS,
)
from app.mcp.capacity import (
    calculate_building_headroom,
)
from app.mcp.land_plan import (
    fetch_land_use_plan,
)
from app.mcp.building import (
    fetch_building_housing_price,
    fetch_building_title,
)
from app.mcp.land_use import (
    get_land_use_regulation,
    search_land_use_act,
)
from app.mcp.settings import settings
from app.mcp.vworld import (
    DEFAULT_NUM_OF_ROWS,
    DEFAULT_PAGE_NO,
    fetch_land_characteristics,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="vworld-land",
    host=settings.MCP_HOST,
    port=settings.MCP_PORT,
)


@mcp.tool()
async def get_land_characteristics(
    pnu: str,
    stdr_year: str | None = None,
    num_of_rows: int = DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """PNU(필지고유번호)로 토지 기본 정보를 조회한다.

    지목, 토지면적(㎡), 용도지역, 토지이용상황, 지형, 도로접면, 공시지가(원/㎡) 등
    토지특성 정보를 반환한다.

    Args:
        pnu: 필지고유번호(PNU). 19자리 숫자 문자열.
        stdr_year: 기준연도 (YYYY). 생략 시 최신 연도.
        num_of_rows: 결과 개수 (최대 1000, 기본 10).
        page_no: 페이지 번호 (기본 1).
    """
    return await fetch_land_characteristics(
        pnu=pnu,
        stdr_year=stdr_year,
        num_of_rows=num_of_rows,
        page_no=page_no,
    )


@mcp.tool()
async def search_land_use_act_tool(
    land_use_nm: str,
    num_of_rows: int = LAND_USE_DEFAULT_NUM_OF_ROWS,
    page_no: int = LAND_USE_DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """토지이용행위명으로 행위명·행위코드를 검색한다.

    토지이용규제(행위제한) 조회에 필요한 '토지이용행위코드'를 찾기 위한 도구.
    예: "단독주택" 검색 → [{행위명, 행위코드}] 목록 반환.

    Args:
        land_use_nm: 토지이용행위명(부분 검색 가능). 예: "단독주택".
        num_of_rows: 결과 개수 (최대 100, 기본 10).
        page_no: 페이지 번호 (기본 1).
    """
    return await search_land_use_act(
        land_use_nm=land_use_nm,
        num_of_rows=num_of_rows,
        page_no=page_no,
    )


@mcp.tool()
async def get_land_use_regulation_tool(
    area_cd: str,
    ucode_list: str,
    land_use_nm: str,
) -> dict[str, Any]:
    """시군구·지역지구별로 특정 토지이용행위의 가능여부(행위제한)를 조회한다.

    "이 지역지구에서 이 행위를 할 수 있는가?"를 판단한다. 지역지구별로 행위·가능여부·
    근거법령·조건을 반환한다.

    Args:
        area_cd: 시군구코드(5자리). 예: "11110"(서울 종로구). PNU 앞 5자리.
        ucode_list: 지역지구코드. 예: "UQA121"(제1종일반주거지역). 쉼표로 다건 가능.
        land_use_nm: 토지이용행위명. 예: "단독주택". search_land_use_act_tool로 확인 가능.
    """
    return await get_land_use_regulation(
        area_cd=area_cd,
        ucode_list=ucode_list,
        land_use_nm=land_use_nm,
    )


@mcp.tool()
async def get_building_capacity(
    pnu: str,
    num_of_rows: int = BLD_DEFAULT_NUM_OF_ROWS,
    page_no: int = BLD_DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """PNU로 건축물대장 표제부를 조회해 건축물 여력 기초 정보를 반환한다.

    대지면적, 건축면적, 건폐율, 연면적, 용적률, 층수, 사용승인일 등을 제공한다.
    법정 최대 건폐율·용적률(용도지역 기준)과 비교하면 추가 건축 여력을 산정할 수 있다.

    Args:
        pnu: 필지고유번호(PNU). 19자리 숫자 문자열.
        num_of_rows: 결과 개수 (최대 100, 기본 10).
        page_no: 페이지 번호 (기본 1).
    """
    return await fetch_building_title(
        pnu=pnu,
        num_of_rows=num_of_rows,
        page_no=page_no,
    )


@mcp.tool()
async def get_building_housing_price(
    sigungu_cd: str,
    bjdong_cd: str,
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = HSPRC_DEFAULT_NUM_OF_ROWS,
    page_no: int = DEFAULT_PAGE_NO,
) -> dict[str, Any]:
    """시군구·법정동코드로 건축물대장 주택가격(공동주택가격 등)을 조회한다.

    번·지·대지구분코드는 사용하지 않고 시군구·법정동 단위로 조회한다.
    각 건물의 주택가격(원), 가격기준일, 주소 등을 반환한다.

    Args:
        sigungu_cd: 시군구코드(5자리). 예: "11110"(서울 종로구). PNU 앞 5자리.
        bjdong_cd: 법정동코드(5자리). 예: "10100"(청운동). PNU 6~10번째 자리.
        start_date: 검색 시작일(YYYYMMDD). 생략 가능.
        end_date: 검색 종료일(YYYYMMDD). 생략 가능.
        num_of_rows: 리스트 수 (기본 20, 최대 100).
        page_no: 페이지 번호 (기본 1).
    """
    return await fetch_building_housing_price(
        sigungu_cd=sigungu_cd,
        bjdong_cd=bjdong_cd,
        start_date=start_date,
        end_date=end_date,
        num_of_rows=num_of_rows,
        page_no=page_no,
    )


@mcp.tool()
async def get_building_headroom(pnu: str) -> dict[str, Any]:
    """PNU로 건축물 여력(추가 건축 가능량)을 계산한다.

    토지특성(용도지역·대지면적)과 건축물대장(현재 건폐율·용적률)을 조합해,
    법정 상한(용도지역 기준) 대비 남은 여력을 ％p 및 추가 건축 가능 면적(㎡)으로 산출한다.

    법정 상한은 국토계획법 시행령 표준값이며, 지자체 조례가 더 엄격할 수 있어
    실제 여력은 이보다 작을 수 있다(반환값 '기준' 필드 참고).

    Args:
        pnu: 필지고유번호(PNU). 19자리 숫자 문자열.
    """
    return await calculate_building_headroom(pnu=pnu)


@mcp.tool()
async def get_land_use_plan(pnu: str) -> dict[str, Any]:
    """PNU로 토지이용계획(지역지구·용도지역지구코드 목록)을 조회한다. (용인시 처인구 전용)

    해당 필지에 지정된 모든 지역지구와 용도지역지구코드(UCODE), 저촉여부를 반환한다.
    반환되는 'area_cd'와 'ucode_list'는 get_land_use_regulation_tool 에 그대로 투입할 수 있다.

    Args:
        pnu: 필지고유번호(PNU). 19자리 숫자 문자열. 처인구(41461)로 시작해야 한다.
    """
    return await fetch_land_use_plan(pnu=pnu)


def main() -> None:
    """설정된 트랜스포트로 MCP 서버를 실행한다."""
    logger.info(
        "vworld-land MCP 서버 시작: transport=%s host=%s port=%s",
        settings.MCP_TRANSPORT,
        settings.MCP_HOST,
        settings.MCP_PORT,
    )
    mcp.run(transport=settings.MCP_TRANSPORT)


if __name__ == "__main__":
    main()
