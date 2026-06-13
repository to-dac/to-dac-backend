# V-World 토지 정보 MCP 서버

V-World(국토교통부 디지털 트윈국토) **토지특성 조회 API**를 감싼 독립 실행 MCP 서버.
별도 프로세스로 띄운 뒤 deepagents 등 MCP 클라이언트에서 연동한다.

## 구성

```
app/mcp/
├── land_info_server.py   # FastMCP 서버 (엔트리포인트, 툴 등록)
├── vworld.py             # V-World 토지특성 API 호출 + 응답 정제 (MCP 비의존)
├── land_use.py           # data.go.kr 토지이용규제 API 호출 + XML 파싱 (MCP 비의존)
├── building.py           # data.go.kr 건축물대장 표제부·주택가격 API 호출 (MCP 비의존)
├── capacity.py           # 토지특성+건축물대장 조합 건축물 여력 계산 (MCP 비의존)
├── land_plan.py          # 처인구 토지이용계획 CSV(DataFrame) 조회 (MCP 비의존)
├── land_use_data/        # 처인구 토지이용계획 원본 CSV (AL_D155_41461_*.csv, EUC-KR)
├── settings.py           # MCPSettings — app/mcp/.env 로드 (FastAPI 앱과 분리)
├── .env.example          # 설정 예시
└── tests/                # 단위 테스트 (httpx 모킹)
```

> `servers/`, `client.py` 는 기존 BaseMCPServer 어댑터 패턴(별개)이며 이 서버와 무관하다.

## 제공 툴

| 툴 | 입력 | 설명 |
|----|------|------|
| `get_land_characteristics` | `pnu`(필수), `stdr_year`, `num_of_rows`, `page_no` | PNU로 토지 기본 정보(지목·면적·용도지역·공시지가 등) 조회 (V-World) |
| `search_land_use_act_tool` | `land_use_nm`(필수), `num_of_rows`, `page_no` | 토지이용행위명으로 행위명·행위코드 검색 (data.go.kr `DTsearchLunCd`) |
| `get_land_use_regulation_tool` | `area_cd`, `ucode_list`, `land_use_nm` (모두 필수) | 시군구·지역지구별 행위 가능여부(행위제한) 조회 (data.go.kr `DTarLandUseInfo`) |
| `get_building_capacity` | `pnu`(필수), `num_of_rows`, `page_no` | PNU로 건축물대장 표제부(대지면적·건폐율·용적률 등) 조회 (data.go.kr `getBrTitleInfo`) |
| `get_building_housing_price` | `sigungu_cd`·`bjdong_cd`(필수), `start_date`, `end_date`, `num_of_rows`, `page_no` | 시군구·법정동 단위 건축물대장 주택가격 조회 (data.go.kr `getBrHsprcInfo`). 번·지·대지구분코드 미사용, `numOfRows` 기본 20 |
| `get_building_headroom` | `pnu`(필수) | 토지특성+건축물대장 조합으로 **건축물 여력**(법정 상한 대비 추가 건축 가능량) 계산. 법정 상한은 국토계획법 시행령 표준값(조례 더 엄격 가능) |
| `get_land_use_plan` | `pnu`(필수) | PNU로 **토지이용계획**(지역지구·용도지역지구코드 목록) 조회. 처인구(41461) 전용 CSV. 반환 `area_cd`+`ucode_list`를 `get_land_use_regulation_tool`에 바로 투입 가능 |

> **`get_land_use_plan` 데이터 메모**
> - 원본: 국가공간정보 토지이용계획(`AL_D155`) 중 **처인구(41461)만 추출**한 CSV(`land_use_data/`, EUC-KR, 약 480MB·250만행).
> - DataFrame으로 **프로세스 1회 로드**(약 10초) 후 캐시 → 이후 조회는 즉시. 처인구 외 PNU는 거부.
> - 이 도구가 PNU→`ucode_list` 자동 도출을 해결해, **PNU 하나로 토지이용계획→행위제한 판정**까지 연결된다.

> data.go.kr 토지이용규제 응답은 **XML(euc-kr) 전용**이라 내부에서 파싱 후 JSON(dict)으로 반환한다.
>
> **`get_land_use_regulation_tool` 입력 메모**
> - `area_cd`: 시군구코드 5자리 (예: `11110` 서울 종로구). PNU 앞 5자리.
> - `ucode_list`: 지역지구코드 (예: `UQA121` 제1종일반주거지역). 쉼표로 다건.
> - `land_use_nm`: 행위명 (예: `단독주택`). `search_land_use_act_tool`로 확인 가능.
> - ⚠️ `ucode_list`(지역지구 법령코드)는 V-World 토지특성 응답엔 명칭만 있고 코드가 없어, PNU만으로 자동 도출 불가 — 별도 매핑/조회 필요.

## 설정

```bash
cp app/mcp/.env.example app/mcp/.env
# .env 의 VWORLD_API_KEY 에 발급받은 인증키 입력
```

## 실행

```bash
# streamable-http (기본, MCP_PORT=8001)
uv run python -m app.mcp.land_info_server

# stdio 로 실행하려면 .env 에서 MCP_TRANSPORT=stdio
```

streamable-http 엔드포인트: `http://127.0.0.1:8001/mcp`

## deepagents 연동

`.mcp.json` 에 등록:

```json
{
  "mcpServers": {
    "vworld-land": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

## 테스트

```bash
uv run pytest app/mcp/tests -q
uv run ruff check app/mcp
```
