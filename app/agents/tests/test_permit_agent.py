# 인허가 멀티턴 에이전트 단위 테스트 — 네트워크 호출 없이 배선·문서접근만 검증한다
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents import permit_agent
from app.agents.permits import (
    DOCS_DIR,
    DOCS_MOUNT,
    PERMITS,
    PROCEDURE_DIR,
    build_docs_index,
    build_forms_index,
    format_land_context,
    get_permit,
)
from app.agents.state import ConversationState
from app.agents.tools import set_permit_type


def test_all_permits_map_to_existing_files() -> None:
    """등록된 6개 유형이 모두 docs/ 실제 파일과 1:1로 매칭된다."""
    assert len(PERMITS) == 6
    missing = [p.rel_path for p in PERMITS if not (DOCS_DIR / p.rel_path).exists()]
    assert missing == []


def test_doc_path_uses_mount_prefix() -> None:
    farm = get_permit("farmland")
    assert farm is not None
    assert farm.doc_path == f"{DOCS_MOUNT}/{farm.rel_path}"
    assert farm.rel_path.startswith(f"{PROCEDURE_DIR}/")


def test_docs_index_lists_all_codes() -> None:
    index = build_docs_index()
    for permit in PERMITS:
        assert permit.code.value in index
        assert permit.doc_path in index


def test_forms_index_lists_all_form_paths() -> None:
    """서식 인덱스가 6개 유형의 신청서 서식 경로를 모두 노출한다."""
    index = build_forms_index()
    for permit in PERMITS:
        assert permit.form_doc_path is not None
        assert permit.form_doc_path in index


def test_get_permit_unknown_returns_none() -> None:
    assert get_permit("unknown_code") is None


def test_set_permit_type_records_state() -> None:
    """확정 유형 코드는 Command 로 permit_type 상태를 갱신한다."""
    runtime = SimpleNamespace(tool_call_id="call-1")
    result = set_permit_type.func(code="farmland", runtime=runtime)
    assert isinstance(result, Command)
    assert result.update["permit_type"] == "farmland"


def test_set_permit_type_rejects_unknown_code() -> None:
    """미등록 코드는 상태를 바꾸지 않고 에러 ToolMessage 만 반환한다."""
    runtime = SimpleNamespace(tool_call_id="call-2")
    result = set_permit_type.func(code="nope", runtime=runtime)
    assert isinstance(result, Command)
    assert "permit_type" not in result.update
    assert result.update["messages"][0].status == "error"


def test_backend_exposes_six_docs() -> None:
    """CompositeBackend 의 /docs 라우트가 6개 마크다운을 노출한다."""
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.backends.state import StateBackend

    backend = CompositeBackend(
        default=StateBackend(),
        routes={f"{DOCS_MOUNT}/": FilesystemBackend(root_dir=DOCS_DIR, virtual_mode=True)},
    )
    entries = backend.ls(f"{DOCS_MOUNT}/{PROCEDURE_DIR}/").entries
    md_files = [e for e in entries if not e["is_dir"] and e["path"].endswith(".md")]
    assert len(md_files) == 6


def test_format_land_context_renders_key_fields() -> None:
    """필지 정보가 용도지역·건물현황·규제 목록으로 렌더된다."""
    ctx = {
        "pnu": "1168010100107370000",
        "address": "서울 강남구 역삼동 737",
        "prposArea1Nm": "일반상업지역",
        "lndpclAr": "13156.7",
        "building": {"hasBuilding": True, "bldNm": "강남파이낸스센터", "bcRat": 42.5677},
        "landUses": [{"code": "UQA220", "name": "일반상업지역", "conflictType": "포함"}],
    }
    text = format_land_context(ctx)
    assert "## 대상 필지 정보" in text
    assert "1168010100107370000" in text
    assert "일반상업지역" in text
    assert "강남파이낸스센터" in text
    assert "42.5677" in text
    assert "UQA220" in text
    assert "포함" in text


def test_format_land_context_marks_vacant_land() -> None:
    """건물이 없으면 나대지로 표기하고 빈 값은 생략한다."""
    text = format_land_context({"pnu": "123", "building": {"hasBuilding": False}})
    assert "나대지" in text
    assert "주소" not in text  # 빈 값은 줄을 만들지 않는다


@pytest.mark.asyncio
async def test_run_permit_chat_seeds_and_injects_land_context() -> None:
    """첫 턴 land_context 는 state 에 시드되고 발화 앞에 주입된다."""
    captured: dict = {}

    class FakeAgent:
        async def ainvoke(self, input_state, config):
            captured["input_state"] = input_state
            captured["config"] = config
            return {"messages": [SimpleNamespace(content="ok")], "permit_type": None}

    reply, permit_type = await permit_agent.run_permit_chat(
        FakeAgent(),
        "이 땅에 증축 가능해?",
        "t-1",
        {"pnu": "123", "prposArea1Nm": "일반상업지역"},
    )

    assert reply == "ok"
    assert captured["input_state"]["land_context"] == {"pnu": "123", "prposArea1Nm": "일반상업지역"}
    content = captured["input_state"]["messages"][0]["content"]
    assert "## 대상 필지 정보" in content
    assert "이 땅에 증축 가능해?" in content
    assert captured["config"]["configurable"]["thread_id"] == "t-1"


@pytest.mark.asyncio
async def test_run_permit_chat_without_land_context_omits_seed() -> None:
    """land_context 가 없으면 state 에 시드하지 않고 발화만 전달한다."""
    captured: dict = {}

    class FakeAgent:
        async def ainvoke(self, input_state, config):
            captured["input_state"] = input_state
            return {"messages": [SimpleNamespace(content="ok")]}

    await permit_agent.run_permit_chat(FakeAgent(), "그럼 서류는?", "t-1")

    assert "land_context" not in captured["input_state"]
    assert captured["input_state"]["messages"][0]["content"] == "그럼 서류는?"


def test_build_permit_agent_wires_multiturn(monkeypatch) -> None:
    """backend(Composite)·checkpointer(InMemorySaver)·state_schema·도구 배선을 검증한다."""
    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return "AGENT"

    monkeypatch.setattr(permit_agent, "build_model", lambda: "MODEL")
    monkeypatch.setattr(permit_agent, "create_deep_agent", fake_create_deep_agent)

    agent = permit_agent.build_permit_agent()

    assert agent == "AGENT"
    assert isinstance(captured["checkpointer"], InMemorySaver)
    assert captured["state_schema"] is ConversationState
    assert set_permit_type in captured["tools"]
    # /docs 라우트가 backend 에 마운트되어 있어야 한다.
    assert f"{DOCS_MOUNT}/" in captured["backend"].routes
