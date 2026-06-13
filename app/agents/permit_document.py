# 인허가 문서 자동작성 로직 — 필지·대화 근거로 양식을 채우고, 작성 이력을 thread 에 남긴다
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.llm import build_model
from app.agents.permit_template import load_template
from app.schemas.permit_chat import DocumentChange
from app.schemas.permit_document import (
    DocumentTemplate,
    FilledQuestion,
    FilledSection,
    PermitDocumentRequest,
    PermitDocumentResponse,
    Question,
)

logger = logging.getLogger(__name__)

# 추출 모델이 반환할 고정 스키마. 템플릿이 동적이라 question_id 로 매핑한다.
# generated: 근거 없이 모델이 그럴듯하게 생성한 값. unknown: 끝내 못 채운 값.
_VALID_SOURCES = {"land_info", "conversation", "unknown", "generated"}


class _AnswerItem(BaseModel):
    """질문 1개에 대한 추출 결과."""

    question_id: int = Field(description="대상 질문 id")
    value: str | None = Field(default=None, description="채운 값(근거 없으면 null)")
    source: str = Field(default="unknown", description="land_info/conversation/unknown")


class _ExtractionResult(BaseModel):
    """추출 모델의 구조화 출력."""

    answers: list[_AnswerItem] = Field(default_factory=list)


def _conversation_transcript(messages: list) -> str:
    """체크포인터에서 읽은 메시지들을 사람이 읽을 수 있는 대화 텍스트로 요약한다.

    도구 호출/시스템 잡음은 제외하고 user/assistant 발화 위주로 추린다.
    """
    lines: list[str] = []
    for msg in messages or []:
        msg_type = getattr(msg, "type", None)
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        if msg_type == "human":
            lines.append(f"사용자: {content}")
        elif msg_type == "ai":
            lines.append(f"비서: {content}")
    return "\n".join(lines)


async def _load_messages(agent, thread_id: str | None) -> list:
    """thread_id 세션의 메시지 목록을 조회한다(읽기 전용). 실패/부재 시 빈 리스트."""
    if agent is None or not thread_id:
        return []
    try:
        snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        logger.warning("세션 상태 조회 실패 — 대화 보강 없이 진행 (thread_id=%s)", thread_id)
        return []
    values = getattr(snapshot, "values", None) or {}
    return values.get("messages", []) or []


async def _collect_conversation(agent, thread_id: str | None) -> str:
    """thread_id 세션의 대화 이력을 사람이 읽을 텍스트로 조회한다."""
    return _conversation_transcript(await _load_messages(agent, thread_id))


def _resolve_template(body: PermitDocumentRequest) -> DocumentTemplate:
    """요청에서 채울 양식을 확정한다. template 직접 지정이 우선, 없으면 permit_type 로 로드."""
    if body.template is not None:
        return body.template
    template = load_template(body.permit_type) if body.permit_type else None
    if template is None:
        raise ValueError(f"양식을 찾을 수 없습니다: permit_type={body.permit_type!r}")
    return template


def _iter_questions(template: DocumentTemplate) -> list[Question]:
    """템플릿의 모든 섹션 질문을 평탄화한다."""
    return [q for section in template.sections for q in section.questions]


_FILL_RULES = """[규칙]
- 모든 질문을 빠짐없이 채운다. value=null 을 두지 마라(항상 값을 생성한다).
- 필지 정보에 근거가 있으면 그 값으로 채우고 source="land_info".
- 대화 이력에 근거가 있으면 그 값으로 채우고 source="conversation".
- 둘 다 근거가 없으면, 질문명·유형·설명에 어울리는 그럴듯한 예시 값을 임의로 생성해 채우고 source="generated".
- 선택지(options)가 있으면 생성할 때도 반드시 그 중 하나만 고른다.
- 검증(validation: maxLength/min 등)이 있으면 생성 값도 그 제약을 지킨다.
- 날짜는 YYYY-MM-DD, 숫자는 숫자만, 개인정보(주민등록번호 등)는 형식만 맞춘 가짜 값으로 생성한다.
- 모든 질문에 대해 한 개씩 answers 항목을 반환한다."""


def _build_extraction_prompt(
    land_info: dict, transcript: str, questions: list[Question]
) -> str:
    """추출 모델에 줄 프롬프트를 만든다.

    근거가 있으면 그 값으로, 없으면 그럴듯한 임의 값을 생성해 모든 질문을 채우도록 유도한다.
    """
    q_lines = []
    for q in questions:
        parts = [f"- id={q.id}", f"name={q.name!r}"]
        if q.questionType:
            parts.append(f"type={q.questionType}")
        if q.description:
            parts.append(f"설명={q.description!r}")
        if q.options:
            parts.append(f"선택지={q.options}")
        if q.validation:
            parts.append(f"검증={q.validation}")
        q_lines.append(" | ".join(parts))

    conversation_block = transcript or "(대화 이력 없음)"
    return f"""너는 인허가 신청서 자동작성 도우미다. 아래 근거로 각 질문의 답을 채워라.

[필지 정보(JSON)]
{json.dumps(land_info, ensure_ascii=False)}

[대화 이력]
{conversation_block}

[채울 질문 목록]
{chr(10).join(q_lines)}

{_FILL_RULES}"""


async def _extract_answers(
    land_info: dict, transcript: str, questions: list[Question]
) -> _ExtractionResult:
    """LLM 경계 — 구조화 출력으로 질문별 답을 추출한다.

    이 함수만 모델을 호출하므로, 테스트에서는 이 함수를 대체(monkeypatch)한다.
    """
    model = build_model()
    structured = model.with_structured_output(_ExtractionResult)
    prompt = _build_extraction_prompt(land_info, transcript, questions)
    return await structured.ainvoke(prompt)


def _coerce_answer(question: Question, value: str | None, source: str) -> tuple[str | None, str]:
    """추출된 값을 질문 제약(options·validation)으로 검증한다. 위반 시 (None, "unknown")."""
    if value is None or value == "":
        return None, "unknown"

    source = source if source in _VALID_SOURCES else "unknown"

    # 선택지 제약: options 안의 값만 허용.
    if question.options:
        try:
            choices = json.loads(question.options)
        except (json.JSONDecodeError, TypeError):
            choices = None
        if isinstance(choices, list) and value not in choices:
            return None, "unknown"

    # 검증 규칙: maxLength 초과 시 무효.
    if question.validation:
        try:
            rules = json.loads(question.validation)
        except (json.JSONDecodeError, TypeError):
            rules = {}
        max_length = rules.get("maxLength") if isinstance(rules, dict) else None
        if isinstance(max_length, int) and len(value) > max_length:
            return None, "unknown"

    return value, source


async def fill_permit_document(agent, body: PermitDocumentRequest) -> PermitDocumentResponse:
    """필지·세션 근거로 양식 질문을 채워 응답을 만든다.

    - agent 는 세션 대화 이력 조회(읽기)에만 쓰인다. None 이면 필지만으로 채운다.
    - 실제 채우기는 별도 모델 호출(_extract_answers)로 수행한다(채팅 스레드 미오염).
    """
    template = _resolve_template(body)
    transcript = await _collect_conversation(agent, body.thread_id)
    land_info = body.land_info.model_dump()
    questions = _iter_questions(template)

    extraction = await _extract_answers(land_info, transcript, questions)
    by_id = {a.question_id: a for a in extraction.answers}

    filled_count = 0
    snapshot_answers: dict[int, str | None] = {}
    filled_sections: list[FilledSection] = []
    for section in template.sections:
        filled_questions: list[FilledQuestion] = []
        for q in section.questions:
            item = by_id.get(q.id)
            answer, source = (
                _coerce_answer(q, item.value, item.source) if item else (None, "unknown")
            )
            if answer is not None:
                filled_count += 1
            snapshot_answers[q.id] = answer
            filled_questions.append(
                FilledQuestion(**q.model_dump(), answer=answer, source=source)
            )
        filled_sections.append(
            FilledSection(
                id=section.id,
                sectionCode=section.sectionCode,
                name=section.name,
                orderNo=section.orderNo,
                questions=filled_questions,
            )
        )

    # 베이스라인 스냅샷 저장 + 작성 이력을 thread 대화에 남긴다(이후 턴 맥락·변경 감지 기준).
    if body.thread_id:
        _save_snapshot(body.thread_id, template, land_info, snapshot_answers)
        await _record_document_in_thread(agent, body.thread_id, template, questions, snapshot_answers)

    return PermitDocumentResponse(
        thread_id=body.thread_id,
        templateCode=template.templateCode,
        sections=filled_sections,
        filled_count=filled_count,
        total_count=len(questions),
    )


@dataclass
class _DocumentSnapshot:
    """문서 생성 시점의 베이스라인. 이후 채팅 변경분 감지의 기준값."""

    template: DocumentTemplate
    land_info: dict
    answers: dict[int, str | None]


# thread_id → 마지막 생성 문서 스냅샷. InMemorySaver 와 동일하게 인메모리·단일 프로세스 전제.
_SNAPSHOTS: dict[str, _DocumentSnapshot] = {}


def _save_snapshot(
    thread_id: str, template: DocumentTemplate, land_info: dict, answers: dict[int, str | None]
) -> None:
    """문서 생성 결과를 베이스라인으로 보관한다."""
    _SNAPSHOTS[thread_id] = _DocumentSnapshot(
        template=template, land_info=land_info, answers=dict(answers)
    )


def _summarize_document(
    template: DocumentTemplate, questions: list[Question], answers: dict[int, str | None]
) -> str:
    """작성된 문서를 thread 에 남길 한국어 요약 텍스트로 만든다."""
    form_name = template.name or template.templateCode or "신청서"
    lines = [
        f"- {q.name}: {answers.get(q.id)}"
        for q in questions
        if answers.get(q.id) not in (None, "")
    ]
    header = f"[서류 작성] '{form_name}' 양식을 작성했습니다 (채움 {len(lines)}/{len(questions)} 항목)."
    if not lines:
        return header
    return f"{header}\n채운 항목:\n" + "\n".join(lines)


async def _record_document_in_thread(
    agent,
    thread_id: str,
    template: DocumentTemplate,
    questions: list[Question],
    answers: dict[int, str | None],
) -> None:
    """작성 요약을 assistant 메시지로 thread 대화에 append 한다(best-effort).

    상태 기록 실패가 문서 생성 자체를 깨지 않도록 예외는 경고 로그로만 처리한다.
    """
    if agent is None:
        return
    summary = _summarize_document(template, questions, answers)
    try:
        await agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [{"role": "assistant", "content": summary}]},
        )
    except Exception:
        logger.warning("서류 작성 이력 thread 기록 실패 (thread_id=%s)", thread_id)


async def detect_document_changes(agent, thread_id: str | None) -> list[DocumentChange]:
    """문서 생성 이후 채팅으로 바뀐 서류 값을 감지해 변경분 목록을 반환한다.

    - 베이스라인(생성 스냅샷)이 없으면 빈 목록(감지 비활성).
    - 베이스라인이 있으면 매 턴 대화를 재추출(LLM)해 스냅샷과 diff 한다.
    - 감지된 값은 스냅샷에 반영해 다음 턴은 직전 대비 변경분만 내보낸다.
    """
    snap = _SNAPSHOTS.get(thread_id) if thread_id else None
    if snap is None:
        return []

    transcript = await _collect_conversation(agent, thread_id)
    questions = _iter_questions(snap.template)
    extraction = await _extract_answers(snap.land_info, transcript, questions)
    by_id = {a.question_id: a for a in extraction.answers}

    changes: list[DocumentChange] = []
    for q in questions:
        item = by_id.get(q.id)
        new_val, source = _coerce_answer(q, item.value, item.source) if item else (None, "unknown")
        if new_val is None or new_val == snap.answers.get(q.id):
            continue
        changes.append(
            DocumentChange(
                questionId=q.id,
                layoutKey=q.layoutKey,
                name=q.name,
                previous=snap.answers.get(q.id),
                current=new_val,
                source=source,
            )
        )
        snap.answers[q.id] = new_val
    return changes
