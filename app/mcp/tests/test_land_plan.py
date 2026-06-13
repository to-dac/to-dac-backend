# land_plan 처인구 토지이용계획 조회 로직 단위 테스트 (DataFrame 캐시 주입, 파일 IO 없음)
import pandas as pd
import pytest

from app.mcp import land_plan

SAMPLE_DF = pd.DataFrame(
    {
        "pnu": ["4146110200100010000", "4146110200100010000", "4146110200100020000"],
        "bjd_cd": ["4146110200", "4146110200", "4146110200"],
        "bjd_nm": ["용인시 처인구 김량장동", "용인시 처인구 김량장동", "용인시 처인구 김량장동"],
        "jibun": ["1-0", "1-0", "2-0"],
        "cnflc": ["포함", "저촉", "포함"],
        "ucode": ["UQA001", "UMI100", "UQA430"],
        "uname": ["제1종일반주거지역", "상대보호구역", "지구단위계획구역"],
        "std_day": ["2026-06-06", "2026-06-06", "2026-06-06"],
    }
)


@pytest.fixture(autouse=True)
def _inject_df(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실제 CSV 로드 대신 작은 DataFrame을 캐시에 주입
    monkeypatch.setattr(land_plan, "_DF_CACHE", SAMPLE_DF)


async def test_fetch_returns_zones_and_ucode_list() -> None:
    result = await land_plan.fetch_land_use_plan("4146110200100010000")

    assert result["pnu"] == "4146110200100010000"
    assert result["area_cd"] == "41461"
    assert result["법정동명"] == "용인시 처인구 김량장동"
    assert result["건수"] == 2
    # 지역지구 배열
    assert result["지역지구"][0] == {
        "용도지역지구코드": "UQA001",
        "용도지역지구명": "제1종일반주거지역",
        "저촉여부": "포함",
    }
    # ucode_list 는 콤마결합 (regulation 도구 투입용)
    assert result["ucode_list"] == "UQA001,UMI100"


async def test_fetch_single_zone() -> None:
    result = await land_plan.fetch_land_use_plan("4146110200100020000")
    assert result["건수"] == 1
    assert result["ucode_list"] == "UQA430"


async def test_fetch_not_found() -> None:
    result = await land_plan.fetch_land_use_plan("4146119999999990000")
    assert result["건수"] == 0
    assert result["지역지구"] == []
    assert "message" in result


async def test_fetch_rejects_non_cheonin() -> None:
    # 기흥구(41463) PNU → 범위 밖
    result = await land_plan.fetch_land_use_plan("4146310200100010000")
    assert "error" in result
    assert "처인구" in result["error"]


async def test_fetch_rejects_invalid_pnu() -> None:
    result = await land_plan.fetch_land_use_plan("123")
    assert "error" in result


def test_resolve_csv_uses_glob(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / "AL_D155_41461_cheonin_20260609.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr(land_plan, "DATA_DIR", tmp_path)
    assert land_plan._resolve_csv().name == "AL_D155_41461_cheonin_20260609.csv"


def test_resolve_csv_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(land_plan, "DATA_DIR", tmp_path)
    assert land_plan._resolve_csv() is None
