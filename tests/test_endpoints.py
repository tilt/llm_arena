"""Named OpenAI-compatible endpoints: config, discovery, key routing and the app/browser APIs.

The security properties tested here: a key only ever goes to the endpoint it was entered for, never in cleartext
across the internet, and never back to a page; endpoint URLs stay out of error text that is persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from llm_arena.adapters.browser.arena import BrowserArena
from llm_arena.adapters.server.discovery import discover
from llm_arena.core.errors import ConfigError
from llm_arena.llm.catalog import Catalog, compatible_entries
from llm_arena.llm.errors import LLMError, ProviderError
from llm_arena.llm.http_client import ProtocolClient
from llm_arena.llm.protocols import openai_chat
from llm_arena.llm.registry import (
    EndpointStore,
    bound_session_key,
    check_key_transport,
    load_endpoints,
    resolve_model,
    save_endpoint,
)
from llm_arena.llm.spec import Capabilities, Endpoint, ModelSpec, key_transport_ok
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.llm.transport import HttpResponse, TransportError
from llm_arena.runner.fingerprint import fingerprint, setup_of
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.server.app import create_app
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService
from server_test_client import SESSION_TOKEN, authenticated_client

SECRET = "sk-endpoint-DO-NOT-LEAK-0987654321"
GPU = Endpoint(id="gpu-box", base_url="https://llm.example.com/v1/")


# ---- config ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "GPU"),  # upper case
        ("id", "-gpu"),
        ("id", "openai"),  # would shadow a provider ref
        ("id", "ollaya"),  # would shadow a decision-service prefix
        ("base_url", "ftp://llm.example.com/v1"),
        ("base_url", "https://user:pw@llm.example.com/v1"),  # credentials belong in a header
        ("base_url", "https://llm.example.com/v1?key=x"),
        ("base_url", "llm.example.com/v1"),
    ],
)
def test_endpoint_validation(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Endpoint.model_validate({"id": "gpu-box", "base_url": "https://llm.example.com/v1", field: value})


def test_endpoint_defaults_and_yaml_round_trip(tmp_path: Path) -> None:
    assert GPU.base_url == "https://llm.example.com/v1" and GPU.api_key_env is None
    path = tmp_path / "endpoints.yaml"
    named = Endpoint(id="vllm", base_url="http://10.0.0.5:8000/v1", api_key_env="MY_VLLM_KEY",
                     capabilities=Capabilities(vision=True), input_cost_per_mtok=0.5, output_cost_per_mtok=1.5)  # fmt: skip
    store = EndpointStore(path)
    store.put(GPU)
    store.put(named)
    assert load_endpoints(path) == {"gpu-box": GPU, "vllm": named} == EndpointStore(path).all()
    assert "MY_VLLM_KEY" in path.read_text() and "key:" not in path.read_text()  # a key's env var name, never a key
    store.remove("gpu-box")
    assert set(load_endpoints(path)) == {"vllm"}
    save_endpoint(path, "vllm", None)
    assert load_endpoints(path) == {} and load_endpoints(tmp_path / "missing.yaml") == {}


def test_identity_follows_the_url_without_revealing_it(tmp_path: Path) -> None:
    moved = GPU.model_copy(update={"base_url": "https://other.example.net/v1"})
    assert GPU.identity != moved.identity and len(GPU.identity) == 12
    assert GPU.identity == Endpoint.model_validate(GPU.model_dump()).identity  # stable for the same salt and URL
    # Keyed by a random salt: knowing the URL is not enough to compute it, so it cannot be brute-forced back.
    assert Endpoint(id="gpu-box", base_url=GPU.base_url).identity != GPU.identity
    # A hand-written endpoint gets a salt on first load, saved so every later process sees the same identity.
    path = tmp_path / "endpoints.yaml"
    path.write_text("endpoints:\n  gpu-box:\n    base_url: https://llm.example.com/v1\n", encoding="utf-8")
    first = EndpointStore(path).get("gpu-box")
    assert first and "salt:" in path.read_text() and EndpointStore(path).get("gpu-box") == first
    # Editing the URL by hand changes the identity too.
    path.write_text(path.read_text().replace("llm.example.com", "other.example.net"), encoding="utf-8")
    edited = EndpointStore(path).get("gpu-box")
    assert edited and edited.identity != first.identity


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://llm.example.com/v1", True),
        ("http://localhost:8000/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://192.168.1.20:8000/v1", True),  # your own network
        ("http://[::1]:8000/v1", True),
        ("http://llm.example.com/v1", False),  # cleartext across the internet
        ("http://52.28.1.9:8000/v1", False),
    ],
)
def test_keys_never_travel_in_cleartext_across_the_internet(url: str, ok: bool) -> None:
    assert key_transport_ok(url) is ok
    spec = ModelSpec(name="e:m", provider="openai_compatible", model="m", endpoint="e", base_url=url)
    check_key_transport(spec, "none")  # no key, nothing to protect
    if ok:
        check_key_transport(spec, SECRET)
    else:
        with pytest.raises(LLMError, match="https"):
            check_key_transport(spec, SECRET)


def test_compatible_models_never_fall_back_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARENA_OPENAI_COMPATIBLE_BASE_URL", raising=False)
    with pytest.raises(LLMError, match="needs a base_url"):
        openai_chat.endpoint(ModelSpec(name="x", provider="openai_compatible", model="m"))


# ---- catalog and discovery ------------------------------------------------------------------


def test_compatible_entries_carry_the_endpoint() -> None:
    priced = Endpoint(id="hosted", base_url="https://api.example.com/v1", input_cost_per_mtok=0.2,
                      output_cost_per_mtok=0.6, capabilities=Capabilities(tools=False), concurrency=2)  # fmt: skip
    [entry] = compatible_entries(priced, [{"id": "Qwen/Qwen3-32B", "max_model_len": 32768}])
    assert entry.spec.endpoint_identity == priced.identity
    assert entry.ref == "hosted:Qwen/Qwen3-32B" and entry.endpoint == "hosted" and entry.context_length == 32768
    spec = entry.spec
    assert (spec.provider, spec.model, spec.endpoint, spec.base_url) == (
        "openai_compatible", "Qwen/Qwen3-32B", "hosted", "https://api.example.com/v1"
    )  # fmt: skip
    assert spec.tool_mode == "json" and spec.concurrency == 2 and spec.api_key_env is None
    assert (spec.input_cost_per_mtok, spec.output_cost_per_mtok) == (0.2, 0.6)
    odd = [{"id": "a#reasoning=high"}, {"id": "two words"}, {"id": 7}, {"object": "model"},
           {"id": "ok", "max_model_len": "lots"}, {"id": "ok2", "max_model_len": -1}]  # fmt: skip
    listed = compatible_entries(priced, odd)  # untrusted listing: odd entries are skipped, odd metadata dropped
    assert [(e.ref, e.context_length) for e in listed] == [("hosted:ok", None), ("hosted:ok2", None)]
    resolved = resolve_model("hosted:Qwen/Qwen3-32B#temperature=0", {}, {entry.ref: spec})
    assert resolved.endpoint == "hosted" and resolved.temperature == 0.0


async def test_discovery_sends_each_key_only_to_its_own_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GPU_BOX_KEY", SECRET)
    # A variable named after an endpoint is not its key: only the env var its YAML names, or a session key, is.
    monkeypatch.setenv("ARENA_ENDPOINT_OPEN_KEY", "sk-guessed-name")
    monkeypatch.setenv("ARENA_OPENAI_COMPATIBLE_KEY", "sk-provider-wide")
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.headers.get("authorization")
        if request.url.host == "down.example.com":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"data": [{"id": f"model-on-{request.url.host}"}]})

    endpoints = {
        "gpu-box": GPU.model_copy(update={"api_key_env": "GPU_BOX_KEY"}),
        "open": Endpoint(id="open", base_url="https://open.example.com/v1"),
        "session": Endpoint(id="session", base_url="https://session.example.com/v1"),
        "down": Endpoint(id="down", base_url="https://down.example.com/v1"),
    }
    sessions = {"session": "sk-session"}
    catalog = await discover(
        sources=(), transport=httpx.MockTransport(handler), endpoints=endpoints, endpoint_keys=sessions.get
    )
    assert [e.ref for e in catalog.entries] == [
        "gpu-box:model-on-llm.example.com", "open:model-on-open.example.com", "session:model-on-session.example.com"
    ]  # fmt: skip
    assert seen == {"llm.example.com": f"Bearer {SECRET}", "open.example.com": None,
                    "session.example.com": "Bearer sk-session", "down.example.com": None}  # fmt: skip
    assert set(catalog.errors) == {"down"}


async def test_discovery_refuses_a_key_over_plain_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAIN_KEY", SECRET)
    sent: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200, json={"data": []}))
    plain = Endpoint(id="plain", base_url="http://llm.example.com/v1", api_key_env="PLAIN_KEY")
    catalog = await discover(sources=(), transport=transport, endpoints={"plain": plain})
    assert not sent and "https" in catalog.errors["plain"]


def test_same_model_on_two_endpoints_is_two_setups_without_changing_old_fingerprints() -> None:
    plain = ModelSpec(name="openai:gpt-5-mini", provider="openai", model="gpt-5-mini")
    assert fingerprint(setup_of({"agent": plain}, {"k": 1}, None)) == "05ac98e6364b"  # pinned before endpoints
    a, b = (ModelSpec(name=f"{e}:m", provider="openai_compatible", model="m", endpoint=e) for e in ("a", "b"))
    assert fingerprint(setup_of({"agent": a}, {}, None)) != fingerprint(setup_of({"agent": b}, {}, None))


def test_a_moved_endpoint_is_a_new_setup_and_its_url_stays_out_of_the_setup() -> None:
    moved = GPU.model_copy(update={"base_url": "https://other.example.net/v1"})
    [before], [after] = (compatible_entries(e, [{"id": "m"}]) for e in (GPU, moved))
    setups = [setup_of({"agent": entry.spec}, {}, None) for entry in (before, after)]
    assert before.ref == after.ref and fingerprint(setups[0]) != fingerprint(setups[1])
    assert setups[0]["roles"]["agent"]["endpoint_identity"] == GPU.identity
    assert not any(host in json.dumps(setups) for host in ("llm.example.com", "other.example.net"))


def test_session_keys_stay_with_the_url_they_were_entered_for() -> None:
    [entry] = compatible_entries(GPU, [{"id": "m"}])
    sessions = {"gpu-box": "sk-session"}
    assert bound_session_key(entry.spec, {"gpu-box": GPU}, sessions.get) == "sk-session"
    moved = GPU.model_copy(update={"base_url": "https://other.example.net/v1"})
    assert bound_session_key(entry.spec, {"gpu-box": moved}, sessions.get) is None  # spec still points at the old URL
    assert bound_session_key(entry.spec, {}, sessions.get) is None
    assert bound_session_key(ModelSpec(name="openai:x", provider="openai", model="x"), {}, sessions.get) is None


async def test_errors_name_the_endpoint_not_its_url() -> None:
    class Down:
        async def post_json(self, url: str, headers: dict[str, str], body: object, timeout_s: float) -> HttpResponse:
            raise TransportError(f"cannot reach {url}")

    [entry] = compatible_entries(GPU, [{"id": "m"}])
    client = ProtocolClient(entry.spec.with_overrides(max_retries=0), Down(), api_key="none")
    with pytest.raises(ProviderError) as raised:
        await client.complete([{"role": "user", "content": "hi"}])
    assert "llm.example.com" not in str(raised.value) and "<endpoint gpu-box>" in str(raised.value)


# ---- local app ------------------------------------------------------------------------------


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    async def discover_nothing() -> Catalog:
        return Catalog()

    service = ArenaService(
        Runtime(client_factory=lambda spec: ScriptedLLM(["x"], spec=spec), discover=discover_nothing),
        store_factory=lambda _: MemoryStore(),
    )
    path = tmp_path / "endpoints.local.yaml"
    # An endpoint from YAML whose key comes from the environment, as from .env.
    monkeypatch.setenv("YAML_BOX_KEY", SECRET)
    save_endpoint(
        path, "yaml-box", Endpoint(id="yaml-box", base_url="https://yaml.example.com/v1", api_key_env="YAML_BOX_KEY")
    )
    app = create_app(service, runs_dir=tmp_path, keys=KeyStore(), endpoints=EndpointStore(path),
                     session_token=SESSION_TOKEN)  # fmt: skip
    return authenticated_client(app), path


def test_app_manages_endpoints_without_returning_keys(app_client: tuple[TestClient, Path]) -> None:
    client, path = app_client
    body = {"base_url": "https://llm.example.com/v1", "key": SECRET, "capabilities": {"vision": True}}
    saved = client.put("/api/endpoints/gpu-box", json=body)
    assert saved.status_code == 200 and saved.json()["key"] == "session" and saved.json()["capabilities"]["vision"]
    assert SECRET not in path.read_text() and "llm.example.com" in path.read_text()
    for route in ("/api/endpoints", "/api/runtime", "/api/models", "/openapi.json"):
        assert SECRET not in client.get(route).text, route
    # Editing without a key keeps it; moving the endpoint to another host forgets it.
    assert (
        client.put("/api/endpoints/gpu-box", json={"base_url": "https://llm.example.com/v1"}).json()["key"] == "session"
    )
    moved = client.put("/api/endpoints/gpu-box", json={"base_url": "https://other.example.net/v1"})
    assert moved.json()["key"] == "missing"
    assert client.delete("/api/endpoints/gpu-box").status_code == 204
    assert [e["id"] for e in client.get("/api/endpoints").json()] == ["yaml-box"]
    assert client.delete("/api/endpoints/gpu-box").status_code == 404


def test_an_env_key_does_not_follow_its_endpoint_to_a_new_url(app_client: tuple[TestClient, Path]) -> None:
    client, path = app_client
    [listed] = client.get("/api/endpoints").json()
    assert listed["key"] == "env" and listed["api_key_env"] == "YAML_BOX_KEY"
    salt = listed["salt"]
    same = client.put("/api/endpoints/yaml-box", json={"base_url": "https://yaml.example.com/v1"}).json()
    assert same["key"] == "env" and same["salt"] == salt  # editing in place keeps the key and the identity's salt
    moved = client.put("/api/endpoints/yaml-box", json={"base_url": "https://moved.example.net/v1"}).json()
    assert moved["key"] == "missing" and moved["api_key_env"] is None
    assert "YAML_BOX_KEY" not in path.read_text()  # not even after a restart, which reloads .env


def test_app_rejects_bad_endpoints_and_cleartext_keys(app_client: tuple[TestClient, Path]) -> None:
    client, path = app_client
    assert client.put("/api/endpoints/openai", json={"base_url": "https://x.example.com/v1"}).status_code == 400
    assert client.put("/api/endpoints/gpu-box", json={"base_url": "file:///etc/passwd"}).status_code == 400
    plain = client.put("/api/endpoints/gpu-box", json={"base_url": "http://llm.example.com/v1", "key": SECRET})
    assert plain.status_code == 400 and "https" in plain.json()["detail"]
    # A page cannot bind an existing key env (say OPENAI_API_KEY) to a host of its choosing.
    rebind = {"base_url": "https://evil.example.com/v1", "api_key_env": "OPENAI_API_KEY"}
    assert client.put("/api/endpoints/gpu-box", json=rebind).status_code == 400
    assert set(load_endpoints(path)) == {"yaml-box"}  # nothing was saved


# ---- browser engine -------------------------------------------------------------------------


class EndpointFetch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def post_json(self, url: str, headers: dict[str, str], body: object, timeout_s: float) -> HttpResponse:
        self.calls.append((url, headers))
        reply = {"choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1}}  # fmt: skip
        return HttpResponse(200, reply)

    async def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append((url, headers))
        return HttpResponse(200, {"data": [{"id": "qwen3"}]})

    async def get_bytes(self, url: str) -> bytes:
        raise AssertionError(url)


async def test_browser_endpoints_bind_keys_to_their_url() -> None:
    fetch = EndpointFetch()
    arena = BrowserArena(transport=fetch, http_get=fetch.get, get_bytes=fetch.get_bytes, emit=lambda _: None)
    view = json.loads(
        arena.set_endpoint("gpu-box", json.dumps({"base_url": "https://llm.example.com/v1", "key": SECRET}))
    )
    assert view["key"] == "session" and SECRET not in arena.endpoints() + await arena.runtime()
    models = json.loads(await arena.models(refresh=True))
    assert [m["ref"] for m in models["models"]] == ["gpu-box:qwen3"]
    assert fetch.calls[-1] == ("https://llm.example.com/v1/models", {"Authorization": f"Bearer {SECRET}"})
    spec = resolve_model("gpu-box:qwen3", {}, (await arena.service.catalog()).specs())
    await arena._client(spec).complete([{"role": "user", "content": "hi"}])
    assert fetch.calls[-1] == ("https://llm.example.com/v1/chat/completions", {
        "Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"})  # fmt: skip

    arena.set_endpoint("gpu-box", json.dumps({"base_url": "https://other.example.net/v1"}))
    assert json.loads(arena.endpoints())[0]["key"] == "missing"  # moving the endpoint forgets its key
    with pytest.raises(ConfigError, match="Models page"):
        arena._client(spec)  # a spec listed before the move may not reach the new host with any key
    with pytest.raises(ConfigError, match="https"):
        arena.set_endpoint("plain", json.dumps({"base_url": "http://llm.example.com/v1", "key": SECRET}))
    arena.clear_endpoint("gpu-box")
    assert arena.endpoints() == "[]"
