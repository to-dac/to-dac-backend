# 인허가 멀티턴 대화 에이전트 — docs/ 문서에 직접 접근해 질문에 근거 기반으로 답한다
from __future__ import annotations

import asyncio
import logging

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.state import StateBackend
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.llm import build_model
from app.agents.permits import (
    DOCS_DIR,
    DOCS_MOUNT,
    build_docs_index,
    build_forms_index,
    format_land_context,
)
from app.agents.state import ConversationState
from app.agents.tools import set_permit_type

logger = logging.getLogger(__name__)


def _system_prompt() -> str:
    """인허가 문서 인덱스를 주입한 시스템 프롬프트를 만든다.

    전체 문서를 미리 싣지 않고 인덱스(유형·경로)만 노출한다. 실제 내용은
    필요한 턴에 read_file/grep 으로 직접 읽어 근거로 삼는다.
    """
    return f"""너는 토지 인허가 안내 비서다. 한국어로 간결하고 정확하게 답한다.

{DOCS_MOUNT} 디렉토리에 인허가 유형별 '체크리스트 서류'·'처리 프로세스' 문서와,
유형별 '신청서 서식'(작성 항목 정의) 문서가 있다. 아래는 그 인덱스다(전체 내용 아님).

[인허가 문서 인덱스 — 체크리스트·프로세스]
{build_docs_index()}

[신청서 서식 인덱스 — 작성 항목 정의]
{build_forms_index()}

[작업 방식 — 반드시 준수]
1) 사용자 질문의 의도와 키워드로 인허가 유형을 좁혀라.
   - 후보가 여러 개로 모호하면, 후보를 제시하고 한 가지로 확정하는 질문을 먼저 하라.
   - 단정할 수 있으면 곧장 진행하라.
2) 유형이 확정되면 set_permit_type(code) 도구를 호출해 대화 상태에 기록하라.
3) 그 다음, 해당 유형의 문서 경로를 read_file 로 직접 읽어
   '## 체크리스트 서류'와 '## 처리 프로세스' 원문을 근거로 답하라.
   - "필요 서류만" 같은 부분 질문은 grep 으로 '- [ ]' 항목만 추려도 된다.
   - 문서에 없는 내용은 추측하지 말고 "문서에 명시되어 있지 않다"고 답하라.
4) 이전 턴에서 이미 유형이 확정된 상태(permit_type)면 다시 묻지 말고
   같은 문서로 이어서 답하라. 사용자가 다른 유형으로 바꾸면 그때 갱신하라.
5) 인덱스에 없는 유형을 물으면, 지원 목록을 안내하고 가장 가까운 유형을 제안하라.

[대상 필지 정보 활용]
- 대화에 '## 대상 필지 정보' 블록이 있으면, 그 필지의 용도지역·지목·면적·건폐율/용적률·
  토지이용 규제(landUses) 등을 인허가 가능 여부·규모 판단의 근거로 적극 활용하라.
- 필지 데이터에 없는 값은 추측하지 말고 "필지 정보에 없다"고 답하라.
- 이 '추측 금지·읽기전용'은 외부에서 받은 '대상 필지 정보'에만 적용된다.
  아래 '신청서 항목 값 입력'과 혼동하지 마라.
- 필지 정보는 첫 턴에만 제공되며 이후 턴에도 동일하게 유효하니 매번 다시 묻지 마라.

[신청서 항목 값 입력 — 거절하지 말 것]
- 사용자는 대화 중 신청서(서식)의 항목 값을 직접 제공하거나 정정할 수 있다.
  예: "입목 벌채 수량 100그루", "전용목적은 주택 신축", "신청인 성명 홍길동".
- 이는 외부 시스템이 준 '대상 필지 정보'(읽기전용)와 전혀 다른, 사용자가 작성하는 신청서 값이다.
  절대 "필지 정보는 수정할 수 없다"는 식으로 거절하지 마라.
- 그런 값을 받으면: (1) 어떤 신청서 항목에 해당하는지 확인하고, (2) 받은 값을 자연스럽게
  확인·요약해 답하라. 값의 실제 반영은 서버가 별도로 처리하므로, 너는 받아들이고 확인해 주면 된다.
- 어떤 항목이 있는지 모호하면, 확정 유형의 '신청서 서식' 문서를 read_file 로 읽어 항목명을 확인하라.

[출력 형식 — 반드시 준수]
- 답변에 마크다운 문법(제목 #, 목록 - / 1., 표 |, 굵게 ** 등)을 사용하는 부분은
  반드시 ```markdown 펜스로 감싸서 출력하라. 예:
  ```markdown
  ## 필요 서류
  - [ ] 토지이용계획확인서
  - [ ] 사업계획서
  ```
- 마크다운 문법이 들어가는 모든 블록(목록·표·제목 포함)을 ``` ``` 코드펜스 안에 넣어,
  렌더링되지 않은 원본 마크다운 형태로 전달되게 하라.
- 코드펜스 밖의 일반 설명 문장은 마크다운 문법 없이 평문으로 작성하라."""


def build_permit_agent():
    """docs 파일시스템 + 멀티턴 체크포인터를 갖춘 인허가 대화 에이전트를 생성한다.

    - CompositeBackend: 기본 StateBackend(대화 상태) + /docs(읽기용 FilesystemBackend).
    - InMemorySaver: thread_id 별 대화 상태를 프로세스 메모리에 보존(멀티턴).

    앱 기동 시 1회 호출해 재사용해야 InMemorySaver 가 턴 간 유지된다.
    """
    backend = CompositeBackend(
        default=StateBackend(),
        routes={
            f"{DOCS_MOUNT}/": FilesystemBackend(root_dir=DOCS_DIR, virtual_mode=True),
        },
    )
    return create_deep_agent(
        model=build_model(),
        backend=backend,
        checkpointer=InMemorySaver(),
        state_schema=ConversationState,
        tools=[set_permit_type],
        system_prompt=_system_prompt(),
    )


async def run_permit_chat(
    agent,
    prompt: str,
    thread_id: str,
    land_context: dict | None = None,
) -> tuple[str, str | None]:
    """단일 발화를 실행하고 (응답 텍스트, 확정 인허가 유형)을 반환한다.

    동일 thread_id 로 호출하면 이전 턴 상태(대화 이력·permit_type·land_context)가 이어진다.

    land_context 가 주어지면(첫 턴) 상태에 보존하고, 포맷한 필지 정보를 발화 앞에
    붙여 모델이 즉시 인지하도록 한다. 이후 턴에는 생략해도 대화 이력으로 유지된다.
    """
    content = prompt
    input_state: dict = {}
    if land_context:
        content = f"{format_land_context(land_context)}\n\n## 질문\n{prompt}"
        input_state["land_context"] = land_context

    input_state["messages"] = [{"role": "user", "content": content}]

    result = await agent.ainvoke(
        input_state,
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content, result.get("permit_type")


async def run_permit_turn(agent, prompt: str, session_id: str) -> str:
    """run_permit_chat 의 텍스트만 반환하는 래퍼(데모·하위호환용)."""
    reply, _ = await run_permit_chat(agent, prompt, session_id)
    return reply


async def _demo() -> None:
    """간단한 멀티턴 데모: 같은 session_id 로 두 턴을 이어 실행한다."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    agent = build_permit_agent()
    session_id = "demo-session"

    for turn in ("농지에 건물을 지으려면 어떤 허가가 필요하고 서류는 뭐가 필요해?", "그럼 처리 절차는?"):
        logger.info("\n>>> 사용자: %s", turn)
        answer = await run_permit_turn(agent, turn, session_id)
        logger.info(">>> 에이전트:\n%s", answer)


if __name__ == "__main__":
    asyncio.run(_demo())
