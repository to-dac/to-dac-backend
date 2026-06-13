# 독립 실행 MCP 서버 전용 설정 — app/mcp/.env 에서 값을 읽는다
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).resolve().parent / ".env"


class MCPSettings(BaseSettings):
    """V-World MCP 서버 설정. FastAPI 앱 설정과 분리되어 독립 실행된다."""

    VWORLD_API_KEY: str = ""
    VWORLD_BASE_URL: str = "https://api.vworld.kr/ned/data"
    # V-World 키는 Referer(등록 도메인) 기반 인증 — 키 발급 시 등록한 도메인과 일치해야 한다
    VWORLD_REFERER: str = "http://localhost"

    # 공공데이터포털 (apis.data.go.kr) — Encoding 인증키 (토지이용규제·건축물대장 공통)
    DATAGO_SERVICE_KEY: str = Field(default="", validation_alias="DTarLandUseInfo_API_KEY")
    DATAGO_BASE_URL: str = "https://apis.data.go.kr/1613000/arLandUseInfoService"
    # 건축HUB 건축물대장정보 서비스 (건축물 여력 조회)
    DATAGO_BASE_URL_BLD: str = "https://apis.data.go.kr/1613000/BldRgstHubService"

    # 서버 실행(streamable-http) 설정
    MCP_HOST: str = "127.0.0.1"
    MCP_PORT: int = 8001
    MCP_TRANSPORT: str = "streamable-http"  # stdio | streamable-http | sse

    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = MCPSettings()
