# deepagents 에이전트 호출이 가능한지 확인하는 스모크 테스트 스크립트
import asyncio
import logging
import os
from pathlib import Path

from deepagents import create_deep_agent
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

# 이 파일과 같은 폴더의 .env에서 환경변수를 로드한다.
load_dotenv(Path(__file__).resolve().with_name(".env"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MODEL_NAME = "claude-sonnet-4-6"


def _normalize_base_url(url: str) -> str:
    """base_url 끝의 /v1/messages, /v1 경로를 제거한다.

    Anthropic SDK가 자동으로 /v1/messages를 붙이므로, 환경변수에 해당 경로가
    포함돼 있으면 중복되어 404가 발생한다.
    """
    url = url.rstrip("/")
    for suffix in ("/v1/messages", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url


def build_agent():
    """환경변수(ANTHROPIC_URL, GMS_API_KEY)로 deep agent를 생성한다."""
    base_url = _normalize_base_url(os.environ["ANTHROPIC_URL"])
    api_key = os.environ["GMS_API_KEY"]

    model = ChatAnthropic(
        model=MODEL_NAME,
        base_url=base_url,
        api_key=api_key,
    )
    return create_deep_agent(
        model=model,
        system_prompt="너는 한국어로 간결하게 답하는 비서다.",
    )


async def run_agent(prompt: str) -> str:
    """프롬프트를 실행하고 마지막 응답 텍스트를 반환한다."""
    agent = build_agent()
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content


async def _main() -> None:
    answer = await run_agent("한 문장으로 자기소개 해줘.")
    logger.info("=== 에이전트 응답 ===\n%s", answer)


if __name__ == "__main__":
    asyncio.run(_main())
