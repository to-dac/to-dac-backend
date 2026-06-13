from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_chat_sessions():
    response = client.get("/api/v1/chat/sessions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_chat_session():
    response = client.post("/api/v1/chat/sessions", json={"title": "테스트 채팅"})
    assert response.status_code == 201
    assert response.json()["title"] == "테스트 채팅"


def test_create_message():
    session_id = client.post("/api/v1/chat/sessions", json={"title": "메시지 테스트"}).json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "안녕하세요"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "안녕하세요"
    assert body["status"] == "pending"
