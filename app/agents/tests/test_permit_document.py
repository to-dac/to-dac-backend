# 문서 자동작성 로직 단위 테스트 — LLM/세션 호출은 mock, 채우기·검증만 검증
from types import SimpleNamespace

import pytest

from app.agents import permit_document
from app.agents.permit_document import (
    _AnswerItem,
    _build_extraction_prompt,
    _coerce_answer,
    _conversation_transcript,
    _ExtractionResult,
    _save_snapshot,
    detect_document_changes,
    fill_permit_document,
)
from app.schemas.permit_document import (
    DocumentTemplate,
    PermitDocumentRequest,
    Question,
)


def _change_template() -> DocumentTemplate:
    return DocumentTemplate(
        templateCode="tc",
        sections=[
            {
                "id": 1,
                "questions": [
                    {"id": 1, "layoutKey": "applicantName", "name": "성명"},
                    {"id": 2, "layoutKey": "occupancyArea", "questionType": "NUMBER", "name": "면적"},
                ],
            }
        ],
    )


def _human(content: str):
    return SimpleNamespace(type="human", content=content)


class _MsgAgent:
    """aget_state 로 고정 메시지를 돌려주는 가짜 에이전트."""

    def __init__(self, messages: list) -> None:
        self._messages = messages

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": self._messages})


class _RecordingAgent:
    """aget_state + aupdate_state 를 기록하는 가짜 에이전트."""

    def __init__(self, messages: list | None = None) -> None:
        self._messages = messages or []
        self.updates: list = []

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": self._messages})

    async def aupdate_state(self, config, values):
        self.updates.append((config, values))


def _radio_q() -> Question:
    return Question(
        id=112,
        questionType="RADIO",
        name="신청 구분",
        options='["대수선","용도변경","대수선 및 용도변경"]',
        validation='{"required": true}',
    )


def test_coerce_answer_accepts_valid_option():
    answer, source = _coerce_answer(_radio_q(), "용도변경", "conversation")
    assert answer == "용도변경"
    assert source == "conversation"


def test_coerce_answer_rejects_out_of_options():
    """선택지 밖의 값은 null + unknown 으로 강등."""
    answer, source = _coerce_answer(_radio_q(), "신축", "conversation")
    assert answer is None
    assert source == "unknown"


def test_coerce_answer_rejects_maxlength_violation():
    q = Question(id=1, questionType="TEXT", name="성명", validation='{"maxLength": 3}')
    answer, source = _coerce_answer(q, "홍길동입니다", "land_info")
    assert answer is None
    assert source == "unknown"


def test_coerce_answer_none_value_is_unknown():
    answer, source = _coerce_answer(Question(id=1), None, "land_info")
    assert answer is None
    assert source == "unknown"


def test_coerce_answer_keeps_generated_source():
    """임의 생성된 값은 source='generated' 로 유지된다(옵션·검증 위반만 강등)."""
    answer, source = _coerce_answer(Question(id=1, questionType="TEXT"), "임의값", "generated")
    assert answer == "임의값"
    assert source == "generated"


def test_extraction_prompt_always_fills_with_generation():
    """프롬프트는 항상 모든 질문을 채우고, 근거 없으면 임의 생성하도록 유도한다."""
    prompt = _build_extraction_prompt({}, "", [Question(id=1, name="성명")])

    assert "null 을 두지 마라" in prompt
    assert "임의로 생성" in prompt
    assert 'source="generated"' in prompt
    assert "추측 금지" not in prompt


def test_conversation_transcript_keeps_human_and_ai():
    messages = [
        SimpleNamespace(type="human", content="대수선 하려고요"),
        SimpleNamespace(type="ai", content="건축허가가 필요합니다"),
        SimpleNamespace(type="tool", content="무시되는 도구 메시지"),
    ]
    text = _conversation_transcript(messages)
    assert "사용자: 대수선 하려고요" in text
    assert "비서: 건축허가가 필요합니다" in text
    assert "도구" not in text


@pytest.mark.asyncio
async def test_fill_permit_document_maps_answers(monkeypatch):
    """추출 결과가 템플릿에 병합되고 filled_count 가 집계된다(agent=None, LLM mock)."""
    template = DocumentTemplate(
        id=1,
        templateCode="tc",
        sections=[
            {
                "id": 10,
                "questions": [
                    {"id": 101, "questionType": "TEXT", "name": "대지 위치"},
                    {"id": 102, "questionType": "TEXT", "name": "신청인 성명"},
                ],
            }
        ],
    )
    body = PermitDocumentRequest(
        land_info={"pnu": "1", "address": "서울 강남구 삼성동 1"},
        template=template,
    )

    async def fake_extract(land_info, transcript, questions, **_):
        assert land_info["pnu"] == "1"
        return _ExtractionResult(
            answers=[
                _AnswerItem(question_id=101, value="서울 강남구 삼성동 1", source="land_info"),
                _AnswerItem(question_id=102, value=None, source="unknown"),
            ]
        )

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)

    result = await fill_permit_document(None, body)

    assert result.templateCode == "tc"
    assert result.total_count == 2
    assert result.filled_count == 1
    q101 = result.sections[0].questions[0]
    assert q101.answer == "서울 강남구 삼성동 1"
    assert q101.source == "land_info"
    assert result.sections[0].questions[1].answer is None


@pytest.mark.asyncio
async def test_fill_permit_document_loads_template_by_permit_type(monkeypatch):
    """template 없이 permit_type 만 주면 서류 정보 문서에서 양식을 로드해 채운다."""
    captured: dict = {}

    async def fake_extract(land_info, transcript, questions, **_):
        captured["question_count"] = len(questions)
        return _ExtractionResult(answers=[])

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)

    body = PermitDocumentRequest(land_info={"pnu": "1"}, permit_type="mountain")
    result = await fill_permit_document(None, body)

    assert result.templateCode == "mountain_permit"
    assert result.total_count == captured["question_count"] > 0


def test_request_requires_template_or_permit_type():
    """template·permit_type 둘 다 없으면 검증 단계에서 거부된다."""
    with pytest.raises(ValueError):
        PermitDocumentRequest(land_info={"pnu": "1"})


@pytest.mark.asyncio
async def test_detect_no_baseline_returns_empty():
    """문서를 생성한 적 없으면(스냅샷 없음) 감지하지 않는다."""
    assert await detect_document_changes(object(), "no-baseline-thread") == []


@pytest.mark.asyncio
async def test_detect_runs_extraction_every_turn(monkeypatch):
    """베이스라인이 있으면 폼 신호 없는 발화여도 매 턴 재추출한다(A안)."""
    _save_snapshot("th-everyturn", _change_template(), {}, {1: "홍길동", 2: None})
    called = {"n": 0}

    async def fake_extract(land_info, transcript, questions):
        called["n"] += 1
        return _ExtractionResult(answers=[])

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)
    changes = await detect_document_changes(_MsgAgent([_human("고마워요")]), "th-everyturn")

    assert called["n"] == 1  # 매 턴 LLM 호출
    assert changes == []  # 추출 결과 없음 → 변경 없음


@pytest.mark.asyncio
async def test_detect_reports_changes_and_advances_baseline(monkeypatch):
    """필터 통과 발화는 재추출 후 스냅샷과 diff 해 변경분을 내고 베이스라인을 갱신한다."""
    _save_snapshot("th-detect", _change_template(), {}, {1: "홍길동", 2: None})

    async def fake_extract(land_info, transcript, questions):
        return _ExtractionResult(
            answers=[
                _AnswerItem(question_id=1, value="김철수", source="conversation"),
                _AnswerItem(question_id=2, value="500", source="conversation"),
            ]
        )

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)
    agent = _MsgAgent([_human("이름은 김철수, 면적 500")])

    changes = await detect_document_changes(agent, "th-detect")
    by_key = {c.layoutKey: c for c in changes}
    assert by_key["applicantName"].previous == "홍길동"
    assert by_key["applicantName"].current == "김철수"
    assert by_key["occupancyArea"].previous is None
    assert by_key["occupancyArea"].current == "500"

    # 같은 추출이 또 와도 직전 대비 변경분이 없으므로 빈 목록.
    assert await detect_document_changes(agent, "th-detect") == []


@pytest.mark.asyncio
async def test_fill_saves_baseline_snapshot(monkeypatch):
    """thread_id 가 있으면 문서 생성 결과를 베이스라인 스냅샷으로 저장한다."""

    async def fake_extract(land_info, transcript, questions, **_):
        return _ExtractionResult(answers=[])

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)
    body = PermitDocumentRequest(
        thread_id="th-snap", land_info={"pnu": "1"}, permit_type="mountain"
    )
    await fill_permit_document(None, body)

    assert "th-snap" in permit_document._SNAPSHOTS
    assert permit_document._SNAPSHOTS["th-snap"].template.templateCode == "mountain_permit"


@pytest.mark.asyncio
async def test_fill_records_document_summary_in_thread(monkeypatch):
    """생성 시 작성 요약을 assistant 메시지로 thread 에 append 한다."""

    async def fake_extract(land_info, transcript, questions):
        return _ExtractionResult(
            answers=[_AnswerItem(question_id=1, value="홍길동", source="conversation")]
        )

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)
    agent = _RecordingAgent()
    body = PermitDocumentRequest(
        thread_id="th-rec", land_info={"pnu": "1"}, permit_type="mountain"
    )
    await fill_permit_document(agent, body)

    assert agent.updates, "thread 에 작성 이력 메시지가 append 되어야 한다"
    config, values = agent.updates[-1]
    assert config["configurable"]["thread_id"] == "th-rec"
    msg = values["messages"][0]
    assert msg["role"] == "assistant"
    assert "서류 작성" in msg["content"]
    assert "홍길동" in msg["content"]


@pytest.mark.asyncio
async def test_fill_permit_document_pulls_conversation(monkeypatch):
    """thread_id 가 있으면 agent.aget_state 로 대화 이력을 읽어 추출에 넘긴다."""
    captured: dict = {}

    class FakeAgent:
        async def aget_state(self, config):
            captured["config"] = config
            return SimpleNamespace(
                values={"messages": [SimpleNamespace(type="human", content="대수선 할게요")]}
            )

    async def fake_extract(land_info, transcript, questions, **_):
        captured["transcript"] = transcript
        return _ExtractionResult(answers=[])

    monkeypatch.setattr(permit_document, "_extract_answers", fake_extract)

    body = PermitDocumentRequest(
        thread_id="t-1",
        land_info={"pnu": "1"},
        template=DocumentTemplate(sections=[]),
    )
    await fill_permit_document(FakeAgent(), body)

    assert captured["config"]["configurable"]["thread_id"] == "t-1"
    assert "사용자: 대수선 할게요" in captured["transcript"]
