from home_agent.services.history import ChatHistory
from fastapi.testclient import TestClient

from home_agent.app import create_app


def test_history_persists_redacted_conversations(tmp_path) -> None:
    history = ChatHistory(tmp_path / "history.sqlite3")
    history.add_message("conversation-1", "user", "Check Minecraft password=secret")
    history.add_message("conversation-1", "assistant", "The guest is running.")

    conversations = history.list_conversations()
    messages = history.get_messages("conversation-1")
    assert conversations[0]["id"] == "conversation-1"
    assert conversations[0]["message_count"] == 2
    assert "secret" not in conversations[0]["title"]
    assert "secret" not in messages[0]["content"]
    assert messages[1]["role"] == "assistant"


def test_history_bounds_messages_per_conversation(tmp_path) -> None:
    history = ChatHistory(
        tmp_path / "history.sqlite3",
        max_messages_per_conversation=2,
    )
    for index in range(3):
        history.add_message("conversation-1", "user", f"message {index}")

    messages = history.get_messages("conversation-1")
    assert [message["content"] for message in messages] == ["message 1", "message 2"]


def test_history_api_lists_loads_and_deletes(settings) -> None:
    app = create_app(settings)
    app.state.services.history.add_message("conversation-1", "user", "Check Minecraft")
    client = TestClient(app, client=("127.0.0.1", 50000))

    listing = client.get("/api/conversations")
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "Check Minecraft"

    conversation = client.get("/api/conversations/conversation-1")
    assert conversation.json()["messages"][0]["role"] == "user"

    assert client.delete("/api/conversations/conversation-1").status_code == 204
    assert client.get("/api/conversations/conversation-1").status_code == 404


def test_chat_endpoint_persists_both_messages(settings) -> None:
    app = create_app(settings)
    app.state.services.runner.run = lambda _message, _session_id: {
        "message": "Guest 104 is running.",
        "pending_approval": None,
    }
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/api/chat",
        json={"message": "Check Minecraft", "session_id": "conversation-1"},
    )

    assert response.status_code == 200
    messages = client.get("/api/conversations/conversation-1").json()["messages"]
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "Check Minecraft"),
        ("assistant", "Guest 104 is running."),
    ]
