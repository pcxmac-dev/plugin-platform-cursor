"""Fakes and guards: tests never read the user's saved keys, never touch the machine's real ledgers, never import
the Cursor SDK, never start a process and never send a request (a FakeRuntime answers the assistant; a fake SDK
module, a fake bridge process and a fake Shutdown stand in for cursor_sdk, cursor-sdk-bridge and its RPC under the
real SdkRuntime). The keys are made up."""
from __future__ import annotations

import io
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_saved_keys(monkeypatch, tmp_path):
    """Tests never read the user's saved keys (their user environment variables), never load the workspace's
    plugin directory, and count on scratch ledgers."""
    from liminal_libs import config, layout

    monkeypatch.setattr(config, "saved_user_keys", lambda: {})
    monkeypatch.setattr(layout, "plugins_dir", lambda: None)
    monkeypatch.setenv("LIMINAL_LIVE_LOCK", str(tmp_path / "machine" / "live.lock"))


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    """No test starts a process: subprocess.Popen refuses (a test that needs one gives a stand-in)."""
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError(f"a test tried to start a process: {args[0] if args else kwargs.get('args')!r}")

    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.fixture
def installed(monkeypatch):
    """The plugin loaded as an installed package's entry point, as the app loads it."""
    from liminal_libs.sources import registry

    def install(*plugins):
        eps = [SimpleNamespace(name=p.name, value=f"plugin_platform_{p.name}", load=(lambda p=p: p)) for p in plugins]
        monkeypatch.setattr(registry, "_entry_points", lambda: eps)
        registry.reload()
        return registry.assistants()

    yield install
    registry._providers = None


@pytest.fixture
def settings_for(tmp_path):
    from liminal_libs.config import load_settings

    def make(**env):
        return load_settings(env={"LIMINAL_DB": str(tmp_path / "m.db"), **env}, env_file=None)
    return make


# -- the runtime's place: what the assistant is given instead of the SDK's -------------------------------

ME = {"name": "liminal", "email": "me@example.com", "user_id": "42", "created": "2026-11-01T00:00:00Z"}


class FakeRuntime:
    """The runtime (runtime.SdkRuntime's place): what each call answers (a value, or an exception raised), every
    call recorded, every open and close counted; nothing imported or started."""

    def __init__(self, *, me=None, models=(), answers=(), version="1.0.40", bridge="1.0.40", open_error=None):
        self.me_ = dict(ME) if me is None else me
        self.models_ = list(models) if not isinstance(models, Exception) else models
        self.answers = list(answers)
        self.version, self.bridge = version, bridge
        self.open_error = open_error
        self.calls: list[tuple] = []
        self.opened = self.closed = 0

    @property
    def asks(self) -> list:
        return [c[1] for c in self.calls if c[0] == "ask"]

    @contextmanager
    def open(self):
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1
        try:
            yield self
        finally:
            self.closed += 1

    @staticmethod
    def _give(value):
        if isinstance(value, Exception):
            raise value
        return value

    def me(self):
        self.calls.append(("me",))
        return self._give(self.me_)

    def models(self):
        self.calls.append(("models",))
        return self._give(self.models_)

    def ask(self, ask):
        self.calls.append(("ask", ask))
        return self._give(self.answers.pop(0))


def answer(text, model="composer-2.5", in_=120, out=30, read=20, wrote=0, thought=8, run="run-1"):
    """An answer as the runtime gives it (runtime.answer_of): the text and the run's tokens."""
    return {"text": text, "id": run, "model": model, "asked": model, "duration_ms": 900,
            "usage": {"input": in_, "output": out, "cache_read": read, "cache_write": wrote, "reasoning": thought,
                      "total": in_ + out}}


def listed(model_id, fast=("false", "true"), aliases=()):
    """A model as the runtime lists it (runtime.model_row): its `fast` parameter's values (None: no parameters)."""
    return {"id": model_id, "name": model_id, "aliases": list(aliases),
            "parameters": [] if fast is None else [{"id": "fast", "values": list(fast)}]}


# -- the SDK's place: the cursor_sdk module, the bridge's process and its Shutdown, for the real SdkRuntime ------

class Recorded:
    """One of the SDK's option types (AgentOptions, LocalAgentOptions, ModelSelection, ModelParameterValue): the
    keywords it was made with."""

    def __init__(self, **kw):
        self.kw = kw

    def __eq__(self, other):
        return type(self) is type(other) and self.kw == other.kw

    def __repr__(self):
        return f"{type(self).__name__}({self.kw!r})"


class AgentOptions(Recorded):
    pass


class LocalAgentOptions(Recorded):
    pass


class ModelSelection(Recorded):
    pass


class ModelParameterValue(Recorded):
    pass


class CursorAgentError(Exception):
    """The SDK's errors' base: its fields as the SDK's page lists them."""

    def __init__(self, message, *, code=None, status=None, request_id=None, retry_after=None):
        super().__init__(message)
        self.message, self.code, self.status, self.status_code = message, code, status, status
        self.request_id, self.retry_after, self.is_retryable = request_id, retry_after, False


class CursorSDKError(CursorAgentError):
    pass


class AuthenticationError(CursorSDKError):
    pass


class PermissionDeniedError(CursorSDKError):
    pass


class RateLimitError(CursorSDKError):
    pass


class ConfigurationError(CursorSDKError):
    pass


class FakeProc:
    """The bridge's process: its stderr (the lines it prints, then its end), whether it was told to shut down,
    terminated or killed; `stays` keeps it running after a Shutdown (to be killed)."""

    def __init__(self, lines, *, stays=False, exits=None):
        self.stderr = io.BytesIO("".join(f"{x}\n" for x in lines).encode("utf-8"))
        self.stays, self.code = stays, exits
        self.shut = self.terminated = self.killed = False
        self.waits: list = []

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        import subprocess

        self.waits.append(timeout)
        if self.code is None and (self.stays or not (self.shut or self.terminated)) and not self.killed:
            raise subprocess.TimeoutExpired("cursor-sdk-bridge", timeout)
        self.code = 0 if self.code is None else self.code
        return self.code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.code = -9


def ready_line(token_file, **changes):
    info = {"schemaVersion": 1, "serverVersion": "1.0.40", "pid": 4242, "transport": "tcp", "protocol": "connect",
            "host": "127.0.0.1", "port": 49152, "url": "http://127.0.0.1:49152", "authTokenFile": str(token_file),
            "workspaceRef": "w", "stateRoot": "s", **changes}
    return "cursor-sdk-bridge ready " + json.dumps({k: v for k, v in info.items() if v is not None})


@pytest.fixture
def fake_sdk(tmp_path):
    """make(**script) -> (the cursor_sdk module's place, the clients made, spawn, post, the procs made): `spawn`
    records the bridge's command line and Popen options and hands back a FakeProc printing the script's `lines`
    (a ready line by default, its token in a file); `post` records each Shutdown and lets the process end.
    The script: me, models, result (Agent.prompt's), error (raised by Agent.prompt), connect_error, lines, stays."""

    def make(**script):
        made: list = []
        procs: list = []
        posts: list = []
        token_file = tmp_path / "auth-token"
        token_file.write_text(" tok-0123456789 \n", encoding="utf-8")

        class FakeClient:
            def __init__(self, url, auth_token):
                self.url, self.token = url, auth_token
                self.closed = False
                self.prompts: list = []
                made.append(self)

            def close(self):
                self.closed = True

        def connect(url, auth_token=None):
            if script.get("connect_error") is not None:
                raise script["connect_error"]
            return FakeClient(url, auth_token)

        def me(api_key=None, client=None):
            client.me_asked = api_key
            return script.get("me")

        def models_list(api_key=None, client=None):
            client.models_asked = api_key
            return script.get("models")

        def prompt(message, options=None, *, client=None):
            client.prompts.append((message, options))
            if script.get("error") is not None:
                raise script["error"]
            return script.get("result")

        sdk = SimpleNamespace(
            __version__="1.0.40", CursorClient=SimpleNamespace(connect=connect),
            Cursor=SimpleNamespace(me=me, models=SimpleNamespace(list=models_list)),
            Agent=SimpleNamespace(prompt=prompt), AgentOptions=AgentOptions, LocalAgentOptions=LocalAgentOptions,
            ModelSelection=ModelSelection, ModelParameterValue=ModelParameterValue)

        def spawn(args, **kwargs):
            lines = script.get("lines")
            proc = FakeProc([ready_line(token_file)] if lines is None else lines, stays=script.get("stays", False),
                            exits=script.get("exits"))
            proc.args, proc.kwargs = args, kwargs
            procs.append(proc)
            return proc

        def post(url, token):
            posts.append((url, token))
            for p in procs:
                p.shut = True

        return sdk, made, spawn, post, procs, posts

    return make
