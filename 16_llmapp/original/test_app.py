import json
import pytest
import original.app as app_module

app = app_module.app

USER_MESSAGE_1 = "1たす2は？"

def _parse_sse_events(raw_bytes: bytes):
    text = raw_bytes.decode("utf-8", errors="ignore")
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                payload = line.replace("data: ", "", 1).strip()
                if payload:
                    events.append(json.loads(payload))
    return events

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "your_secret_key"
    c = app.test_client()
    with c.session_transaction() as sess:
        sess.clear()
    yield c

def test_index_get_request(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<form" in resp.data

def test_stream_returns_done_event(client, monkeypatch):
    # stream_events をモック（外部APIを叩かない）
    def fake_stream_events(user_message, thread_id):
        yield {"type": "thinking", "message": "thinking..."}
        yield {"type": "done", "message": "3"}

    monkeypatch.setattr(app_module, "stream_events", fake_stream_events)

    resp = client.post("/stream", data={"user_message": USER_MESSAGE_1})
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    events = _parse_sse_events(resp.data)
    assert any(ev.get("type") == "ping" for ev in events)  # app.pyがpingを返す
    assert any(ev.get("type") == "thinking" for ev in events)
    assert any(ev.get("type") == "done" for ev in events)
    done = [ev for ev in events if ev.get("type") == "done"][-1]
    assert "3" in done.get("message", "")

def test_history_endpoint_renders(client, monkeypatch):
    def fake_get_messages_list(memory, thread_id):
        return [
            {"class": "user-message", "text": "hello"},
            {"class": "bot-message", "text": "world"},
        ]

    monkeypatch.setattr(app_module, "get_messages_list", fake_get_messages_list)

    resp = client.get("/history")
    assert resp.status_code == 200
    decoded = resp.data.decode("utf-8", errors="ignore")
    assert "hello" in decoded
    assert "world" in decoded

def test_clear_endpoint_issues_new_thread_id(client):
    client.get("/")
    with client.session_transaction() as sess:
        tid1 = sess.get("thread_id")
    assert tid1 is not None

    resp = client.post("/clear")
    assert resp.status_code == 200

    with client.session_transaction() as sess:
        tid2 = sess.get("thread_id")
    assert tid2 is not None
    assert tid2 != tid1
