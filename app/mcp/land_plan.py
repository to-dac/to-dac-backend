# 처인구 토지이용계획 CSV 조회 (DataFrame 캐시 기반, MCP 비의존 순수 로직)
import asyncio
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 처인구 전용 토지이용계획 데이터 (AL_D155_41461_*.csv). 날짜 변동 대비 glob 탐색.
DATA_DIR = Path(__file__).resolve().parent / "land_use_data"
CSV_GLOB = "AL_D155_41461_*.csv"
CSV_ENCODING = "euc-kr"

CHEONIN_SIGUNGU = "41461"  # 용인시 처인구 시군구코드
PNU_LENGTH = 19

# 원본 CSV 컬럼 인덱스 → 사용할 컬럼명 (필요한 8개만 로드)
_USECOLS = [0, 1, 2, 5, 8, 9, 10, 12]
_COL_NAMES = ["pnu", "bjd_cd", "bjd_nm", "jibun", "cnflc", "ucode", "uname", "std_day"]

# 로드된 DataFrame 캐시 (프로세스 1회 로드 후 재사용, 약 수백 MB)
_DF_CACHE: pd.DataFrame | None = None


def _resolve_csv() -> Path | None:
    """처인구 CSV 파일 경로를 찾는다 (glob 최신 1건)."""
    matches = sorted(DATA_DIR.glob(CSV_GLOB))
    return matches[-1] if matches else None


def _get_df() -> pd.DataFrame:
    """처인구 토지이용계획 DataFrame을 lazy 로드·캐시한다."""
    global _DF_CACHE
    if _DF_CACHE is not None:
        return _DF_CACHE

    csv_path = _resolve_csv()
    if csv_path is None:
        raise FileNotFoundError(f"토지이용계획 데이터 파일이 없습니다: {DATA_DIR}/{CSV_GLOB}")

    logger.info("처인구 토지이용계획 CSV 로드 시작: %s", csv_path.name)
    df = pd.read_csv(
        csv_path,
        encoding=CSV_ENCODING,
        dtype=str,
        header=0,
        usecols=_USECOLS,
    )
    df.columns = _COL_NAMES
    df = df.fillna("")
    _DF_CACHE = df
    logger.info("처인구 토지이용계획 CSV 로드 완료: %d행", len(df))
    return df


async def fetch_land_use_plan(pnu: str) -> dict[str, Any]:
    """PNU로 처인구 토지이용계획(지역지구·UCODE 목록)을 조회한다.

    DataFrame 로드/조회가 블로킹이므로 스레드에서 실행한다. 오류 시 {"error": ...} 반환.
    """
    return await asyncio.to_thread(_fetch_land_use_plan_sync, pnu)


def _fetch_land_use_plan_sync(pnu: str) -> dict[str, Any]:
    """PNU 검증 후 DataFrame에서 토지이용계획을 조회해 정제된 dict로 반환한다."""
    if not pnu or not pnu.isdigit() or len(pnu) != PNU_LENGTH:
        return {"error": f"PNU는 {PNU_LENGTH}자리 숫자여야 합니다. 입력: {pnu!r}"}

    if not pnu.startswith(CHEONIN_SIGUNGU):
        return {"error": f"처인구({CHEONIN_SIGUNGU}) 범위 밖 PNU입니다. 본 서비스는 처인구만 지원합니다. 입력: {pnu}"}

    try:
        df = _get_df()
    except FileNotFoundError as exc:
        logger.warning("토지이용계획 데이터 파일 없음: %s", exc)
        return {"error": str(exc)}

    rows = df[df["pnu"] == pnu]
    return _build_result(pnu, rows)


def _build_result(pnu: str, rows: pd.DataFrame) -> dict[str, Any]:
    """조회된 행들을 PNU 단위로 묶어 정제된 응답 dict를 만든다."""
    base: dict[str, Any] = {"pnu": pnu, "area_cd": pnu[: len(CHEONIN_SIGUNGU)]}

    if rows.empty:
        return {**base, "지역지구": [], "ucode_list": "", "건수": 0, "message": "해당 PNU의 토지이용계획 정보가 없습니다."}

    first = rows.iloc[0]
    zones = [
        {"용도지역지구코드": r["ucode"], "용도지역지구명": r["uname"], "저촉여부": r["cnflc"]}
        for _, r in rows.iterrows()
    ]
    # ucode 중복 제거(순서 보존) → regulation 도구에 바로 투입 가능한 콤마 결합 문자열
    seen: dict[str, None] = {}
    for z in zones:
        code = z["용도지역지구코드"]
        if code and code not in seen:
            seen[code] = None

    return {
        **base,
        "법정동코드": first["bjd_cd"],
        "법정동명": first["bjd_nm"],
        "지번": first["jibun"],
        "데이터기준일자": first["std_day"],
        "지역지구": zones,
        "ucode_list": ",".join(seen.keys()),
        "건수": len(zones),
    }
