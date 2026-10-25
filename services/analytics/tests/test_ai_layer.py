"""P2a AI layer: encrypted providers, grounded tools, chat history, usage.

No test in this module touches the network. The provider transport is replaced
with a scripted OpenAI-compatible response so the tool loop and grounding guard
are exercised deterministically.
"""

from __future__ import annotations

import json
import logging

import pytest

from conftest import FIXTURES, upload_and_finalize
from decisionos_analytics.ai import crypto, providers
from decisionos_analytics.ai.providers import ProviderError
from decisionos_analytics.api import create_app
from decisionos_analytics.migrations import MIGRATIONS

SECRET = "sk-test-super-secret-provider-key-1234"
COUNT = {"column": "*", "agg": "count", "alias": "rows"}


def _openai_response(content: str = "", tool_calls=None, prompt=10, completion=5):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
            }
            for call in tool_calls
        ]
    return {
        "choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class ScriptedTransport:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        if not self.scripts:
            raise AssertionError("provider was called more times than the script allows")
        script = self.scripts.pop(0)
        return script(payload) if callable(script) else script


def _publish(client, headers, filename: str = "tickets_cases.csv") -> str:
    _uid, final = upload_and_finalize(client, headers, FIXTURES / "tenant_alpha" / filename)
    dataset_id = final["dataset_id"]
    client.post(
        f"/v1/datasets/{dataset_id}/grain-confirmation",
        json={"key_columns": ["case_id"]},
        headers=headers,
    )
    published = client.post(
        f"/v1/datasets/{dataset_id}/revisions/{final['revision']}/publish", headers=headers
    )
    assert published.status_code == 200, published.text
    return dataset_id


def _provider(client, headers, name="deepseek-test", key=SECRET):
    response = client.post(
        "/v1/ai/providers",
        json={
            "name": name,
            "kind": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "api_key": key,
            "models": ["test-model"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _map_primary(client, headers, provider_id, model="test-model"):
    response = client.put(
        "/v1/ai/models",
        json={"primary": {"provider_id": provider_id, "model_id": model}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _chat(client, headers, message, conversation_id=None):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post("/v1/ai/chat", json=body, headers=headers)


def test_provider_key_is_encrypted_masked_and_never_returned(client, alpha_headers, caplog):
    caplog.set_level(logging.DEBUG)
    created = _provider(client, alpha_headers)
    assert created["key_suffix"] == "\u20261234"
    assert len(created["key_fingerprint"]) == 8
    assert SECRET not in json.dumps(created)
    assert "api_key_enc" not in created

    listed = client.get("/v1/ai/providers", headers=alpha_headers)
    assert listed.status_code == 200
    assert SECRET not in listed.text
    assert "api_key_enc" not in listed.text
    assert listed.json()[0]["key_suffix"] == "\u20261234"

    row = client.app.state.store.conn.execute(
        "SELECT api_key_enc FROM ai_provider WHERE tenant_id=? AND id=?",
        ("tenant_alpha", created["id"]),
    ).fetchone()
    assert SECRET not in row["api_key_enc"]
    assert row["api_key_enc"].startswith("v1:")
    assert crypto.decrypt_secret(row["api_key_enc"]) == SECRET

    assert SECRET not in caplog.text


def test_encrypt_secret_round_trip_and_random_nonce():
    first = crypto.encrypt_secret(SECRET)
    second = crypto.encrypt_secret(SECRET)
    assert first != second
    assert first.startswith("v1:")
    assert SECRET not in first
    assert crypto.decrypt_secret(first) == SECRET
    assert crypto.decrypt_secret(second) == SECRET

    with pytest.raises(ValueError):
        crypto.decrypt_secret("not-a-ciphertext")
    replacement = "A" if first[-1] != "A" else "B"
    with pytest.raises(ValueError):
        crypto.decrypt_secret(first[:-1] + replacement)


def test_tool_loop_grounds_analytics_answer_and_persists_everything(client, alpha_headers, monkeypatch):
    dataset_id = _publish(client, alpha_headers)
    tool_call = {
        "id": "call_1",
        "name": "analytics_query",
        "arguments": {
            "dataset_id": dataset_id,
            "dimensions": [],
            "measures": [COUNT],
            "filters": [],
            "limit": 10,
        },
    }

    def final_answer(payload):
        tool_message = payload["messages"][-1]
        assert tool_message["role"] == "tool"
        result = json.loads(tool_message["content"])
        assert result["ok"] is True
        rows = result["data"]["rows"]
        evidence_ref = result["data"]["evidence_ref"]
        return _openai_response(
            f"There are {rows[0][0]} support tickets in the demo dataset. Evidence: {evidence_ref}.",
            prompt=20,
            completion=10,
        )

    transport = ScriptedTransport([_openai_response(tool_calls=[tool_call]), final_answer])
    monkeypatch.setattr(providers, "_http_post_json", transport)

    created = _provider(client, alpha_headers)
    _map_primary(client, alpha_headers, created["id"])
    response = _chat(client, alpha_headers, "How many support tickets are in the demo dataset?")
    assert response.status_code == 200, response.text
    body = response.json()

    assert "420" in body["answer"]
    assert body["tool_calls"][0]["name"] == "analytics_query"
    assert body["tool_calls"][0]["ok"] is True
    assert body["tool_calls"][0]["evidence_ref"].startswith("ev-")
    assert body["usage"] == {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}
    assert "warning" not in body

    # The provider received the real encrypted key over the wire only as a bearer header.
    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert transport.calls[0]["url"].endswith("/chat/completions")
    assert transport.calls[0]["payload"]["temperature"] == 0.1

    conversation_id = body["conversation_id"]
    conversation = client.get(f"/v1/ai/conversations/{conversation_id}", headers=alpha_headers)
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == body["answer"]
    assert messages[1]["tool_trace"][0]["evidence_ref"] == body["tool_calls"][0]["evidence_ref"]

    listed = client.get("/v1/ai/conversations", headers=alpha_headers)
    assert listed.status_code == 200
    assert listed.headers["X-Total-Count"] == "1"
    assert listed.json()[0]["id"] == conversation_id

    usage = client.get("/v1/ai/usage", headers=alpha_headers)
    assert usage.status_code == 200
    usage_body = usage.json()
    assert usage_body["totals"]["prompt_tokens"] == 30
    assert usage_body["totals"]["completion_tokens"] == 15
    assert usage_body["by_model"][0]["model_id"] == "test-model"
    assert usage_body["by_day"][0]["prompt_tokens"] == 30

    usage_count = client.app.state.store.conn.execute(
        "SELECT COUNT(*) c FROM ai_usage WHERE tenant_id=?", ("tenant_alpha",)
    ).fetchone()["c"]
    assert usage_count == 1


def test_refused_predictive_score_is_surfaced_not_invented(client, alpha_headers, monkeypatch):
    tool_call = {
        "id": "call_1",
        "name": "predictive_score",
        "arguments": {"model_id": "model-missing", "case_id": "case-1", "deadline": "2026-12-01T00:00:00Z"},
    }
    transport = ScriptedTransport(
        [
            _openai_response(tool_calls=[tool_call]),
            _openai_response("I cannot score this case because no trained model artifact exists."),
        ]
    )
    monkeypatch.setattr(providers, "_http_post_json", transport)
    created = _provider(client, alpha_headers)
    _map_primary(client, alpha_headers, created["id"])

    response = _chat(client, alpha_headers, "Score case-1 with model-missing.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool_calls"][0]["refused"] is True
    assert body["tool_calls"][0]["code"] == "model_not_trained"
    assert body["tool_calls"][0]["ok"] is False
    assert "warning" not in body
    assert not any(character.isdigit() for character in body["answer"])


def test_ungrounded_number_guard_trips(client, alpha_headers, monkeypatch):
    transport = ScriptedTransport(
        [_openai_response("There are 999 support tickets in the demo dataset.")]
    )
    monkeypatch.setattr(providers, "_http_post_json", transport)
    created = _provider(client, alpha_headers)
    _map_primary(client, alpha_headers, created["id"])

    response = _chat(client, alpha_headers, "How many support tickets are in the demo dataset?")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warning"]["ungrounded_numbers"] == ["999"]


def test_provider_failure_returns_flat_502_and_records_test_error(client, alpha_headers, monkeypatch):
    created = _provider(client, alpha_headers)
    _map_primary(client, alpha_headers, created["id"])

    def failing_transport(url, headers, payload, timeout):
        raise ProviderError("provider returned HTTP 500", status=500, retryable=True)

    monkeypatch.setattr(providers, "_http_post_json", failing_transport)
    response = _chat(client, alpha_headers, "Anything?")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "provider_error"
    assert body["detail"] == "provider returned HTTP 500"
    assert "Traceback" not in response.text

    tested = client.post(f"/v1/ai/providers/{created['id']}/test", headers=alpha_headers)
    assert tested.status_code == 200
    probe = tested.json()
    assert probe["ok"] is False
    assert probe["models_seen"] == ["test-model"]
    row = client.app.state.store.conn.execute(
        "SELECT status, last_error FROM ai_provider WHERE tenant_id=? AND id=?",
        ("tenant_alpha", created["id"]),
    ).fetchone()
    assert row["status"] == "error"
    assert "HTTP 500" in row["last_error"]


def test_provider_test_success_clears_last_error(client, alpha_headers, monkeypatch):
    created = _provider(client, alpha_headers)
    transport = ScriptedTransport([_openai_response("OK", prompt=1, completion=1)])
    monkeypatch.setattr(providers, "_http_post_json", transport)
    response = client.post(f"/v1/ai/providers/{created['id']}/test", headers=alpha_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["models_seen"] == ["test-model"]
    assert transport.calls[0]["payload"]["max_tokens"] == 1


def test_tenant_isolation_on_every_ai_route(client, alpha_headers, beta_headers, monkeypatch):
    created = _provider(client, alpha_headers, name="alpha-only")
    _map_primary(client, alpha_headers, created["id"])

    assert client.get("/v1/ai/providers", headers=beta_headers).json() == []
    assert client.get("/v1/ai/models", headers=beta_headers).json()["primary"] is None
    assert client.post(f"/v1/ai/providers/{created['id']}/test", headers=beta_headers).status_code == 404
    assert client.put(
        f"/v1/ai/providers/{created['id']}", json={"base_url": "https://evil.test"}, headers=beta_headers
    ).status_code == 404
    assert client.delete(f"/v1/ai/providers/{created['id']}", headers=beta_headers).status_code == 404
    assert client.put(
        "/v1/ai/models",
        json={"primary": {"provider_id": created["id"], "model_id": "test-model"}},
        headers=beta_headers,
    ).status_code == 404

    transport = ScriptedTransport([_openai_response("Should never be called")])
    monkeypatch.setattr(providers, "_http_post_json", transport)
    beta_chat = _chat(client, beta_headers, "How many tickets?")
    assert beta_chat.status_code == 409
    assert beta_chat.json()["code"] == "ai_model_not_configured"
    assert transport.calls == []

    alpha_chat = _chat(client, alpha_headers, "Hello")
    assert alpha_chat.status_code == 200, alpha_chat.text
    conversation_id = alpha_chat.json()["conversation_id"]
    assert client.get(f"/v1/ai/conversations/{conversation_id}", headers=beta_headers).status_code == 404
    assert client.delete(f"/v1/ai/conversations/{conversation_id}", headers=beta_headers).status_code == 404
    assert client.get("/v1/ai/usage", headers=beta_headers).json()["totals"]["prompt_tokens"] == 0


def test_provider_rotation_never_exposes_either_key(client, alpha_headers):
    created = _provider(client, alpha_headers)
    rotated = "sk-rotated-credential-9876"
    response = client.put(
        f"/v1/ai/providers/{created['id']}", json={"api_key": rotated}, headers=alpha_headers
    )
    assert response.status_code == 200
    assert rotated not in response.text
    assert response.json()["key_suffix"] == "\u20269876"
    row = client.app.state.store.conn.execute(
        "SELECT api_key_enc FROM ai_provider WHERE tenant_id=? AND id=?",
        ("tenant_alpha", created["id"]),
    ).fetchone()
    assert crypto.decrypt_secret(row["api_key_enc"]) == rotated


def test_conversation_delete_is_tenant_scoped_and_cascades_messages(client, alpha_headers, monkeypatch):
    transport = ScriptedTransport([_openai_response("Hello, I can help.")])
    monkeypatch.setattr(providers, "_http_post_json", transport)
    created = _provider(client, alpha_headers)
    _map_primary(client, alpha_headers, created["id"])
    chat = _chat(client, alpha_headers, "Hello")
    conversation_id = chat.json()["conversation_id"]

    deleted = client.delete(f"/v1/ai/conversations/{conversation_id}", headers=alpha_headers)
    assert deleted.status_code == 200
    assert client.get(f"/v1/ai/conversations/{conversation_id}", headers=alpha_headers).status_code == 404
    remaining = client.app.state.store.conn.execute(
        "SELECT COUNT(*) c FROM ai_message WHERE tenant_id=? AND conversation_id=?",
        ("tenant_alpha", conversation_id),
    ).fetchone()["c"]
    assert remaining == 0


def test_strict_mode_without_secret_key_refuses_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_AUTH_STRICT", "1")
    monkeypatch.setenv(
        "DECISIONOS_JWT_SECRET", "jwt-secret-that-is-at-least-32-bytes-long!"
    )
    monkeypatch.delenv("DECISIONOS_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DECISIONOS_SECRET_KEY"):
        create_app(tmp_path / "data")


def test_migration_v5_creates_ai_tables(tmp_path):
    from decisionos_analytics.store import Store

    assert max(version for version, _, _ in MIGRATIONS) == 6
    store = Store(tmp_path / "ai.sqlite3")
    try:
        tables = {
            row["name"]
            for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "ai_provider",
            "ai_model_role",
            "ai_conversation",
            "ai_message",
            "ai_usage",
        } <= tables
        assert store.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 6
    finally:
        store.close()
