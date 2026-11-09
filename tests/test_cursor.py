"""The Cursor plugin on fake answers: it loads as an assistant plugin, its tables hold together, the free plan sends
through Composer 2.5, an answer is asked the model at standard speed, the argument's own system line and the user's
text (never the key, nothing about the account), an answer's usage, model and cost are read, Cursor's refusals are
said in words with the key scrubbed, a key that is not Cursor's and a plan without the SDK send nothing, Connect
checks the key, the account and the models, the machine's caps hold, and the SDK's bridge is started windowless and
the SDK driven locked down (a fake SDK module, a fake bridge process and a fake Shutdown under the real SdkRuntime:
nothing imported, no process started, nothing sent)."""
from __future__ import annotations

import queue
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from liminal_libs.assistants import Answer, Offline, Question, Usage, evaluate
from liminal_libs.config import ConfigError
from liminal_libs.errors import BudgetExhausted, NotEntitled, RateLimited, SourceError, Unauthorized

import plugin_platform_cursor as cursor
from plugin_platform_cursor import ASSISTANT, FAST, LEGACY, MODELS, PLANS, SOURCES, SUBSCRIPTION, CursorPlugin
from plugin_platform_cursor.runtime import (ANSWER_SECONDS, CREATE_NO_WINDOW, READY, Ask, CursorError, SdkRuntime,
                                            child_env, classify, failure, find_bridge, ready_of, stop_bridge, token_of,
                                            wait_ready)

from conftest import (AgentOptions, AuthenticationError, ConfigurationError, FakeProc, FakeRuntime, LocalAgentOptions,
                      ModelParameterValue, ModelSelection, PermissionDeniedError, RateLimitError, answer, listed,
                      ready_line)

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
KEY, EMAIL = "crsr_" + "0" * 24 + "testonlyscratchkey", "me@example.com"


def test_it_loads_as_an_assistant_plugin(installed):
    found = installed(ASSISTANT)
    assert list(found) == ["cursor"] and isinstance(found["cursor"], CursorPlugin)
    p = found["cursor"]
    assert p.KIND == "assistant" and p.SYSTEM == "platform" and p.api == "2.0" and p.vendor == "Cursor"
    assert p.origin == "package: plugin_platform_cursor" and p.order == 504
    import liminal_libs

    icons = (Path(liminal_libs.__file__).parent / "ui" / "static" / "icons.js").read_text(encoding="utf-8")
    assert p.ICON == "cursor" and re.search(r"^\s*cursor:", icons, flags=re.MULTILINE)  # its maker's mark, the library's
    key, account = p.keys
    assert (key.name, account.name) == ("CURSOR_API_KEY", "CURSOR_ACCOUNT") and key.aliases == ()
    assert key.secret and not account.secret and "crsr_" in key.hint and "Team Admin" in key.hint
    assert p.plan_vars == ("CURSOR_PLAN", "CURSOR_MODEL", "CURSOR_REQUESTS_PER_DAY", "CURSOR_TOKENS_PER_DAY")
    assert p.options == ("CURSOR_MAX_OUTPUT_TOKENS",) and p.has_scan and p.has_settings  # no effort: no parameter id
    assert p.plan_choices["CURSOR_PLAN"][0] == "free" and p.plan_choices["CURSOR_MODEL"][0] == "composer-2.5"
    assert p.plan_choices["CURSOR_REQUESTS_PER_DAY"][0] == "20"  # conservative: 20 a day here unless you set more
    assert [d.where for d in p.databases] == ["assistants/cursor/"] and p.refusal() is None
    from liminal_libs.sources import registry

    assert registry.errors() == []
    assert set(registry.variables()) >= {"CURSOR_API_KEY", "CURSOR_ACCOUNT", "CURSOR_PLAN", "CURSOR_MODEL"}


def test_the_tables_hold_together():
    assert [p.name for p in PLANS] == ["free", "plus", "premium", "super", "ultra", "teams", "enterprise", "hobby",
                                       "start", "pro", "pro-plus"]
    assert [p.name for p in PLANS if not p.api_access] == ["start"]  # "Start doesn't include ... the Cursor SDK"
    assert all(not (p.rpm or p.tpm or p.rpd) for p in PLANS)  # Cursor publishes no limits for the SDK
    free, plus, premium, start = (ASSISTANT.plan_of(n) for n in ("free", "plus", "premium", "start"))
    assert ASSISTANT.free_plan is free and free.api_access
    ids = [m.id for m in MODELS]
    assert ids == ["composer-2.5", "grok-4.5", "grok-4.6", "grok-4.7"] and ids[0] == ASSISTANT.default_model
    assert ASSISTANT.reach(free) == ASSISTANT.reach(plus) == ASSISTANT.reach(premium) == tuple(ids)  # Cursor's own on all
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9.-]*", i) for i in ids)
    assert all(0 < m.cached_usd < m.input_usd < m.output_usd for m in MODELS)
    assert [m.input_usd for m in MODELS] == sorted(m.input_usd for m in MODELS)  # the cheapest first
    assert set(FAST) == set(ids) == ASSISTANT.standard_speed  # each has a Fast speed: asked for at the standard one
    assert all(FAST[m.id][0] > m.input_usd and FAST[m.id][2] > m.output_usd for m in MODELS)
    assert ASSISTANT.cost("composer-2.5", Usage(1_000_000, 1_000_000, 0, 0)) == 3.0
    assert ASSISTANT.cost("grok-4.7", Usage(1_000_000, 0, 1_000_000, 0)) == 0.5  # every input token a cached one
    assert ASSISTANT.cost("gpt-9", Usage(10, 10)) is None
    assert SUBSCRIPTION["premium"] == (30, 300, "4x Plus") and "$30 a month ($300 a year)" in premium.price
    assert LEGACY == {"pro": 20, "pro-plus": 60} and "$20 a month" in ASSISTANT.plan_of("pro").price
    assert "Cursor SDK" in start.note and "649" in start.price
    assert cursor.VERIFIED == "2026-11-09" and ASSISTANT.verified == cursor.VERIFIED
    assert all(s.url.startswith(("https://cursor.com/docs/", "https://raw.githubusercontent.com/cursor/")) and s.sentinel
               and s.markers for s in SOURCES)
    assert {m.title for m in MODELS} <= set(SOURCES[0].markers)  # every model's name must stay on the pricing page
    for s in SOURCES:  # a marker never ends at a code span: the page's text would put a space before its punctuation
        assert not any(re.search(r"[a-z_]+\(?\)?\.$", m) and "_" in m for m in s.markers), s.url
    with pytest.raises(ConfigError, match="not a model of Cursor"):
        ASSISTANT.settings({"CURSOR_API_KEY": KEY, "CURSOR_MODEL": "claude-4.6-sonnet-thinking"})
    with pytest.raises(ConfigError, match="not a plan of Cursor"):
        ASSISTANT.settings({"CURSOR_API_KEY": KEY, "CURSOR_PLAN": "pro+"})


def test_the_free_plan_sends_through_composer_and_the_request_is_the_arguments_own(installed, settings_for):
    installed(ASSISTANT)
    settings = settings_for(CURSOR_API_KEY=KEY, CURSOR_ACCOUNT=EMAIL)
    own = settings.plugin("cursor")
    assert own.has_key and own.plan == "free" and own.model == "composer-2.5"
    assert ASSISTANT.keys_set(settings) and ASSISTANT.served(settings) and ASSISTANT.free_note(settings) == ""
    rt = FakeRuntime(answers=[answer("The exchange is closed.\nVerdict: no")])
    q = Question("Is the market open?", answer=Answer("verdict", scale=("yes", "no")))
    ev = evaluate(q, settings, assistant="cursor", session=rt, now=lambda: NOW)
    (ask,) = rt.asks
    assert isinstance(ask, Ask) and ask.model == "composer-2.5" and ask.fast == "false" and ask.timeout == ANSWER_SECONDS
    assert ask.system.startswith("You are an analyst's assistant") and "Verdict:" in ask.system
    assert ask.prompt == "Question: Is the market open?"
    assert KEY not in repr(ask) and EMAIL not in repr(ask)  # never the key, nothing about the account
    assert rt.opened == rt.closed == 1 and [c[0] for c in rt.calls] == ["ask"]  # started for the answer, stopped after
    assert ev.assistant == "cursor" and ev.provider == "Cursor" and ev.verdict == "no" and ev.ok and ev.stop == "end_turn"
    assert ev.model == "composer-2.5" and ev.usage == Usage(120, 30, 20, 8) and ev.request_id == "run-1"
    assert ev.cost_usd == pytest.approx(ASSISTANT.model_of("composer-2.5").cost(Usage(120, 30, 20, 8)))


def test_a_paid_plans_request_carries_the_model(installed, settings_for):
    installed(ASSISTANT)
    settings = settings_for(CURSOR_API_KEY=KEY, CURSOR_PLAN="premium", CURSOR_MODEL="grok-4.7",
                            CURSOR_MAX_OUTPUT_TOKENS="512", CURSOR_REQUESTS_PER_DAY="50")
    own = settings.plugin("cursor")
    assert (own.plan, own.model, own.caps.max_output_tokens, own.caps.requests_per_day) == ("premium", "grok-4.7", 512, 50)
    rt = FakeRuntime(answers=[answer('{"verdict": "bearish", "score": 3}', model="grok-4.7", in_=160, read=100, wrote=10)])
    fields = Question("Score it", answer=Answer("fields", fields=("verdict", "score")))
    ev = evaluate(fields, settings, assistant="cursor", session=rt, now=lambda: NOW)
    (ask,) = rt.asks
    assert (ask.model, ask.fast) == ("grok-4.7", "false") and "JSON object" in ask.system
    assert ev.fields == {"verdict": "bearish", "score": 3} and ev.verdict == "bearish" and ev.model == "grok-4.7"
    assert ev.usage == Usage(160, 30, 100, 8)  # the cache reads and writes are among the input, as the SDK counts them
    a = ASSISTANT.build(settings, session=FakeRuntime(), now=lambda: NOW)
    apart = a.parse({"usage": {"input": 50, "cache_read": 100, "cache_write": 10, "output": 5}, "model": "grok-4.7"})
    assert apart.usage == Usage(160, 5, 100, 0)  # an input count without its cache reads and writes is added to
    assert a.body(SimpleNamespace(system="s", user="u"), "gpt-9", "")["fast"] is None  # a model the table has not


def test_no_key_a_foreign_key_and_a_plan_without_the_sdk_send_nothing(installed, settings_for):
    installed(ASSISTANT)
    rt = FakeRuntime()
    with pytest.raises(Unauthorized, match="no key"):
        evaluate(Question("x"), settings_for(CURSOR_PLAN="pro"), assistant="cursor", session=rt)
    foreign = settings_for(CURSOR_API_KEY="sk-ant-" + "0" * 30)
    assert ASSISTANT.keys_set(foreign)
    with pytest.raises(Unauthorized, match="not a Cursor API key"):
        evaluate(Question("x"), foreign, assistant="cursor", session=rt)
    ((what, ok, detail),) = ASSISTANT.run_scan(ASSISTANT.build(foreign, session=rt, now=lambda: NOW)).results
    assert (what, ok) == ("the key", False) and detail.startswith("not sent: cursor: not a Cursor API key")
    with pytest.raises(Unauthorized, match="crsr_"):
        ASSISTANT.build(foreign, session=rt, now=lambda: NOW).models()
    start = settings_for(CURSOR_API_KEY=KEY, CURSOR_PLAN="start")
    assert not ASSISTANT.served(start) and "Start (legacy, India) plan has no API access" in ASSISTANT.free_note(start)
    with pytest.raises(NotEntitled, match="no API access"):
        evaluate(Question("x"), start, assistant="cursor", session=rt)
    ((what, ok, detail),) = ASSISTANT.run_scan(ASSISTANT.build(start, session=rt, now=lambda: NOW)).results
    assert (what, ok) == ("its plan", False) and "does not include the Cursor SDK" in detail
    with pytest.raises(Offline):  # nothing is sent from an offline copy of the app
        evaluate(Question("x"), settings_for(CURSOR_API_KEY=KEY, LIMINAL_OFFLINE="1"), assistant="cursor", session=rt)
    assert rt.opened == 0 and rt.calls == []


def test_cursors_refusals_are_said_in_words_with_the_key_scrubbed(installed, settings_for):
    installed(ASSISTANT)
    settings = settings_for(CURSOR_API_KEY=KEY, CURSOR_ACCOUNT=EMAIL, CURSOR_PLAN="pro")

    def run(refusal, **runtime):
        rt = FakeRuntime(answers=[refusal], **runtime)
        a = ASSISTANT.build(settings, session=rt, now=lambda: NOW)
        with pytest.raises(SourceError) as caught:
            a.evaluate(Question("x"))
        return type(caught.value), caught.value, rt

    kind, e, rt = run(CursorError(f"Invalid API key {KEY} of {EMAIL}", 401, "authentication", request_id="req-9"))
    assert kind is Unauthorized and KEY not in e.message and EMAIL not in e.message and "Invalid API key … of …" in e.message
    assert e.message.startswith("the key was refused") and "(request req-9)" in e.message and rt.opened == rt.closed == 1
    kind, e, _ = run(CursorError("Authenticated caller does not have permission", 403, "permission"))
    assert kind is NotEntitled and e.message.startswith("not allowed: Authenticated caller") and "Cursor SDK" in e.message
    kind, e, _ = run(CursorError("usage limits exceeded", 429, "quota", "usage_limit_exceeded"))
    assert kind is NotEntitled and e.message.startswith("no usage left for it") and "refreshes weekly" in e.message
    kind, e, _ = run(CursorError("Too many requests", 429, "rate_limit", retry_after=12.0))
    assert kind is RateLimited and e.message.startswith("rate limited: Too many requests") and e.retry_after == 12.0
    kind, e, _ = run(CursorError("Invalid model grok-9", 400, "configuration"))
    assert kind is NotEntitled and e.message.startswith("no such model or option") and "Connect's list" in e.message
    kind, e, _ = run(CursorError("the upstream failed", 502, "server"))
    assert kind is SourceError and e.message == "the upstream failed"
    kind, e, _ = run(CursorError("no answer from the Cursor SDK in 180 s", kind="timeout"))
    assert kind is SourceError and e.message == "no answer from the Cursor SDK in 180 s"
    kind, e, rt = run(None, open_error=CursorError("the Cursor SDK is not installed here: install it", kind="setup"))
    assert kind is SourceError and "not installed" in e.message and rt.calls == []
    assert classify("HTTP 401: invalid API key") == (401, "authentication") and classify("all is well") == (0, "")
    assert classify("Rate limit of 10 per 60s exceeded") == (429, "rate_limit")
    assert classify("usage_limit_exceeded: your weekly pool is spent") == (402, "quota")


def test_connect_checks_the_key_the_account_and_the_models(installed, settings_for):
    installed(ASSISTANT)
    settings = settings_for(CURSOR_API_KEY=KEY, CURSOR_ACCOUNT=EMAIL.upper(), CURSOR_PLAN="premium", CURSOR_MODEL="grok-4.7")
    models = [listed("composer-2.5"), listed("grok-4.5"), listed("grok-4.7", aliases=["grok-latest"]),
              listed("claude-4.6-sonnet-thinking", fast=None), listed("gpt-5.5-high", fast=None)]
    rt = FakeRuntime(models=models, answers=[answer("OK", model="grok-4.7", in_=12, out=1, read=0, thought=0)])
    scanned = ASSISTANT.run_scan(ASSISTANT.build(settings, session=rt, now=lambda: NOW))
    rows = {w: (ok, d) for w, ok, d in scanned.results}
    assert rows["the Cursor SDK"] == (True, "cursor-sdk 1.0.40, its bridge 1.0.40")
    assert rows["the key"] == (True, "accepted: a user's key, named liminal")
    assert rows["the account"] == (True, "the key is the Cursor account CURSOR_ACCOUNT names")
    assert rows["the model grok-4.7"] == (True, "listed")
    assert rows["its speed"][0] and "standard speed (fast=false)" in rows["its speed"][1]
    ok, gone = rows["the table's models"]
    assert not ok and gone.startswith("not listed by the key's catalog: grok-4.6 (the table is stale")
    assert rows["models not in the table"] == (True, "claude-4.6-sonnet-thinking, gpt-5.5-high")
    ok, said = rows["an answer"]
    assert ok and said.startswith("grok-4.7 answered in ") and said.endswith(
        ": 13 tokens ($0.000030 by the table's prices, were it beyond the plan's pool)")
    assert scanned.plan == {}  # Cursor sends no limits the plans differ by: the plan stays the one chosen
    assert scanned.limits["perMinute"] is None and scanned.limits["seen"] == {}
    assert [c[0] for c in rt.calls] == ["me", "models", "ask"] and rt.opened == rt.closed == 1  # one bridge for it all
    (probe,) = rt.asks
    assert (probe.model, probe.system, probe.prompt, probe.fast) == ("grok-4.7", "Reply with the single word OK.",
                                                                     "Are you there?", "false")
    light = FakeRuntime(models=models)
    found = {w for w, _, _ in ASSISTANT.build(settings, session=light, now=lambda: NOW).connect(light=True).results}
    assert "an answer" not in found and light.asks == []
    listing = ASSISTANT.build(settings, session=FakeRuntime(models=models[:1]), now=lambda: NOW).models()
    assert [(m["id"], m["title"]) for m in listing] == [("composer-2.5", "composer-2.5")]


def test_connect_says_what_it_cannot_reach(installed, settings_for):
    installed(ASSISTANT)

    def scan(rt, **env):
        settings = settings_for(CURSOR_API_KEY=KEY, **env)
        return ASSISTANT.run_scan(ASSISTANT.build(settings, session=rt, now=lambda: NOW)).results

    missing = CursorError("the Cursor SDK is not installed here: install it", kind="setup")
    assert scan(FakeRuntime(open_error=missing)) == (("the Cursor SDK", False, "the Cursor SDK is not installed here: install it"),)
    rt = FakeRuntime(me=CursorError(f"Invalid API key {KEY}", 401, "authentication"))
    sdk, (what, ok, detail) = scan(rt)
    assert sdk[0] == "the Cursor SDK" and (what, ok) == ("the key", False) and KEY not in detail
    assert detail.startswith("refused: the key was refused: Invalid API key …") and "crsr_" in detail
    assert [c[0] for c in rt.calls] == ["me"]  # nothing more is asked with a key refused
    what, ok, detail = scan(FakeRuntime(models=CursorError("forbidden", 403, "permission")))[-1]
    assert (what, ok) == ("the models", False) and detail.startswith("not listed: not allowed: forbidden")
    rows = {w: (ok, d) for w, ok, d in scan(FakeRuntime(models=[listed("composer-2.5")], answers=[answer("OK")]),
                                            CURSOR_ACCOUNT="someone@else.example")}
    assert rows["the account"] == (False, "the key belongs to another Cursor account than CURSOR_ACCOUNT names: check "
                                          "the key or the account")
    assert rows["the model composer-2.5"] == (True, "listed") and rows["an answer"][0]
    assert rows["the table's models"][0] is False  # the free plan reaches every model of the table: three are missing
    service = {"name": "ci", "email": "", "user_id": "", "created": ""}
    rows = {w: (ok, d) for w, ok, d in scan(FakeRuntime(me=service, models=[listed("composer-2.5", fast=("true",))],
                                                        answers=[answer("OK")]), CURSOR_ACCOUNT=EMAIL)}
    assert rows["the key"] == (True, "accepted: a service account's key, named ci") and "the account" not in rows
    assert rows["its speed"] == (False, "the catalog offers it at Fast speed only: the plugin asks for standard speed "
                                        "and would be refused")
    rows = {w: (ok, d) for w, ok, d in scan(FakeRuntime(models=[listed("grok-4.5", fast=None),
                                                                {**listed("x"), "parameters": [{"id": "thinking", "values": ["high"]}]}],
                                                        answers=[answer("OK")]), CURSOR_MODEL="grok-4.5")}
    assert "its speed" not in rows  # no parameters listed at all: nothing to tell
    rows = scan(FakeRuntime(models=[], answers=[answer("OK")]))
    assert ("the model composer-2.5", False, "not listed by the key's catalog: choose another model (the ones listed are "
                                             "in the scan's rows below)") in rows


def test_the_machines_daily_request_cap_holds(installed, settings_for):
    installed(ASSISTANT)
    settings = settings_for(CURSOR_API_KEY=KEY, CURSOR_REQUESTS_PER_DAY="1")
    rt = FakeRuntime(answers=[answer("Verdict: yes"), answer("Verdict: yes")])
    a = ASSISTANT.build(settings, session=rt, now=lambda: NOW)
    assert a.evaluate(Question("x")).ok
    with pytest.raises(BudgetExhausted, match="daily request cap"):
        a.evaluate(Question("x"))
    assert len(rt.asks) == 1 and rt.opened == 1  # the second was not sent: the bridge was not even started
    assert a.tokens.today(NOW) == 150  # the answer's tokens counted on the machine's ledger


def test_the_runtime_is_the_sdks_by_default_beside_the_data(installed, settings_for, tmp_path):
    installed(ASSISTANT)
    a = ASSISTANT.build(settings_for(CURSOR_API_KEY=KEY), now=lambda: NOW)
    assert isinstance(a.runtime, SdkRuntime) and a.runtime.home == tmp_path / "assistants" / "cursor"
    assert not a.runtime.home.exists() and KEY not in repr(a.runtime)  # nothing written until a call needs the bridge
    assert a.headers(KEY) == {} and a.client._headers == {}  # the key is the SDK's to send, never a header here


def test_the_bridge_is_started_windowless_and_the_sdk_driven_locked_down(fake_sdk, tmp_path):
    usage = SimpleNamespace(input_tokens=120, output_tokens=30, cache_read_tokens=20, cache_write_tokens=0,
                            total_tokens=150, reasoning_tokens=8)
    result = SimpleNamespace(id="run-7", agent_id="bc-1", status="finished", result="Closed.\nVerdict: no",
                             model=SimpleNamespace(id="composer-2.5", params=[]), duration_ms=870, usage=usage)
    me = SimpleNamespace(api_key_name="liminal", created_at="2026-11-01", user_id=42, user_email=EMAIL)
    catalog = SimpleNamespace(items=[SimpleNamespace(id="composer-2.5", display_name="Composer 2.5", aliases=None,
                                                     parameters=[SimpleNamespace(id="fast", display_name="Fast",
                                                                                 values=[SimpleNamespace(value="false"), True])])])
    sdk, made, spawn, post, procs, posts = fake_sdk(me=me, models=catalog, result=result)
    environ = {"PATH": r"C:\Windows", "LIMINAL_DB": "x.db", "CLAUDE_API_KEY": "sk-ant-x", "CODEX_ACCOUNT": EMAIL,
               "CURSOR_API_KEY": "crsr_of_the_environment", "CURSOR_SDK_BRIDGE_PORT": "1", "CURSOR_CONFIG_DIR": "elsewhere",
               "GITHUB_TOKEN": "ghs_x", "LIMINAL_SMTP_PASSWORD": "pw", "AWS_SECRET_ACCESS_KEY": "s"}
    home = tmp_path / "home"
    rt = SdkRuntime(KEY, home, sdk=sdk, environ=environ, bridge="C:/venv/Scripts/cursor-sdk-bridge.exe", spawn=spawn,
                    post=post)
    assert KEY not in repr(rt) and made == procs == [] and not home.exists()  # nothing made or written before open
    with rt.open() as conn:
        assert (conn.version, conn.bridge) == ("1.0.40", "1.0.40") and KEY not in repr(conn)
        whose, models = conn.me(), conn.models()
        got = conn.ask(Ask("composer-2.5", "You are terse.", "Is it open?", "false", 30.0))
    (proc,) = procs
    assert proc.args == ["C:/venv/Scripts/cursor-sdk-bridge.exe", "--host", "127.0.0.1", "--port", "0",
                         "--workspace", str(home / "workspace"), "--state-root", str(home / "state")]
    assert proc.kwargs["env"] == {"PATH": r"C:\Windows", "LIMINAL_DB": "x.db", "CURSOR_API_KEY": KEY,
                                  "CURSOR_SDK_CLIENT_LANGUAGE": "python"}  # the login's key alone, no other credential
    assert proc.kwargs["stdin"] is subprocess.DEVNULL and proc.kwargs["stdout"] is subprocess.DEVNULL
    assert proc.kwargs["stderr"] is subprocess.PIPE and (home / "workspace").is_dir() and (home / "state").is_dir()
    import os

    assert proc.kwargs.get("creationflags") == (CREATE_NO_WINDOW if os.name == "nt" else None)  # windowless on Windows
    (client,) = made
    assert (client.url, client.token) == ("http://127.0.0.1:49152", "tok-0123456789") and client.closed
    assert client.me_asked == KEY and client.models_asked == KEY  # the key given explicitly, never the environment's
    ((message, options),) = client.prompts
    assert message == "You are terse.\n\nIs it open?"
    assert options == AgentOptions(model=ModelSelection(id="composer-2.5", params=[ModelParameterValue(id="fast", value="false")]),
                                   api_key=KEY, name="Liminal evaluation", tools=[],  # no tool: words only
                                   local=LocalAgentOptions(cwd=str(home / "workspace"), setting_sources=[]))
    assert posts == [("http://127.0.0.1:49152", "tok-0123456789")] and not proc.killed  # its Shutdown, then it ended
    assert whose == {"name": "liminal", "email": EMAIL, "user_id": "42", "created": "2026-11-01"}
    assert models == [{"id": "composer-2.5", "name": "Composer 2.5", "aliases": [],
                       "parameters": [{"id": "fast", "values": ["false", "true"]}]}]
    assert got == {"text": "Closed.\nVerdict: no", "id": "run-7", "model": "composer-2.5", "asked": "composer-2.5",
                   "duration_ms": 870, "usage": {"input": 120, "output": 30, "cache_read": 20, "cache_write": 0,
                                                 "reasoning": 8, "total": 150}}
    sdk, made, spawn, post, procs, posts = fake_sdk(result=result)
    with SdkRuntime(KEY, home, sdk=sdk, environ={}, bridge="b", spawn=spawn, post=post).open() as conn:
        conn.ask(Ask("auto", "", "Is it open?", None))
    ((message, options),) = made[0].prompts
    assert message == "Is it open?" and options.kw["model"] == "auto"  # no `fast` for a model the table has not


def test_the_default_spawn_is_popen_windowless(fake_sdk, monkeypatch, tmp_path):
    seen = {}

    def recording(args, **kwargs):
        seen.update(args=args, **kwargs)
        return FakeProc([ready_line(token)])

    token = tmp_path / "t"
    token.write_text("tok", encoding="utf-8")
    monkeypatch.setattr(subprocess, "Popen", recording)
    sdk, made, _, post, _, _ = fake_sdk()
    with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={"PATH": "x"}, bridge="b", post=post).open():
        pass
    import os

    if os.name == "nt":
        assert seen["creationflags"] == 0x08000000  # CREATE_NO_WINDOW: no Windows Terminal window for a console child
    else:
        assert "creationflags" not in seen
    assert made[0].token == "tok"


def test_the_bridges_handshake_and_its_failures(fake_sdk, tmp_path):
    token = tmp_path / "token"
    token.write_text("abc\n", encoding="utf-8")
    assert ready_of("starting the bridge") is None
    found = ready_of(ready_line(token, url=None, host="::1", port=5000))
    assert found["url"] == "http://[::1]:5000" and found["version"] == "1.0.40" and token_of(found) == "abc"
    assert token_of(ready_of(ready_line(token, authToken="inline"))) == "inline"  # an older bridge's, preferred
    for wrong in ({"schemaVersion": 2}, {"transport": "unix"}, {"protocol": "grpc"}):
        with pytest.raises(CursorError, match="another handshake") as caught:
            ready_of(ready_line(token, **wrong))
        assert caught.value.kind == "setup"
    with pytest.raises(CursorError, match="loopback"):
        ready_of(ready_line(token, url="http://10.0.0.5:49152"))
    with pytest.raises(CursorError, match="could not be read"):
        ready_of(READY + "{not json")
    with pytest.raises(CursorError, match="gave no token"):
        token_of({"token": "", "token_file": ""})
    with pytest.raises(CursorError, match="token could not be read"):
        token_of({"token_file": str(tmp_path / "gone")})

    sdk, made, spawn, post, procs, posts = fake_sdk(lines=["error: CURSOR_API_KEY is invalid", "bye"], exits=3)
    with pytest.raises(CursorError, match="stopped before it was ready: error: CURSOR_API_KEY is invalid; bye") as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={}, bridge="b", spawn=spawn, post=post).open():
            pass
    assert caught.value.kind == "setup" and made == [] and posts == []  # never attached, never asked to shut down

    sdk, made, spawn, post, procs, posts = fake_sdk(connect_error=AuthenticationError("Invalid API key", status=401), stays=True)
    with pytest.raises(CursorError) as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={}, bridge="b", spawn=spawn, post=post).open():
            pass
    assert (caught.value.kind, caught.value.status) == ("authentication", 401)
    assert len(posts) == 1 and procs[0].killed  # asked to shut down, still there: killed

    sdk, made, spawn, post, procs, posts = fake_sdk(error=RateLimitError("usage limits exceeded", code="usage_limit_exceeded",
                                                                         status=429, request_id="r-1", retry_after="30"))
    with pytest.raises(CursorError) as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={}, bridge="b", spawn=spawn, post=post).open() as conn:
            conn.ask(Ask("composer-2.5", "s", "p"))
    e = caught.value
    assert (e.kind, e.status, e.code, e.request_id, e.retry_after) == ("quota", 429, "usage_limit_exceeded", "r-1", 30.0)
    assert made[0].closed and posts  # the client closed and the bridge stopped all the same

    failed = SimpleNamespace(status="error", error_code="feature_unavailable", error_message="the SDK is not on your plan")
    sdk, made, spawn, post, procs, posts = fake_sdk(result=failed)
    with pytest.raises(CursorError, match="not on your plan") as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={}, bridge="b", spawn=spawn, post=post).open() as conn:
            conn.ask(Ask("composer-2.5", "s", "p"))
    assert (caught.value.kind, caught.value.code) == ("permission", "feature_unavailable")

    with pytest.raises(CursorError, match="not installed here") as caught:
        with SdkRuntime(KEY, tmp_path / "h", module="no_such_cursor_sdk_here", environ={}, bridge="b").open():
            pass
    assert caught.value.kind == "setup" and 'pip install "plugin-platform-cursor[sdk]"' in caught.value.message

    def missing(args, **kwargs):
        raise FileNotFoundError(2, "No such file", args[0])

    with pytest.raises(CursorError, match="could not start: FileNotFoundError") as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={}, bridge="b", spawn=missing).open():
            pass
    assert caught.value.kind == "setup"


def test_the_bridge_is_found_by_which_beside_this_python_or_on_path(fake_sdk, monkeypatch, tmp_path):
    import sysconfig

    scripts, elsewhere = tmp_path / "scripts", tmp_path / "elsewhere"
    scripts.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(sysconfig, "get_path", lambda name, *a, **k: str(scripts))
    sdk, made, spawn, post, procs, posts = fake_sdk()
    with pytest.raises(CursorError, match="is not beside this Python nor on PATH") as caught:
        with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={"PATH": str(elsewhere)}, spawn=spawn, post=post).open():
            pass
    assert caught.value.kind == "setup" and procs == [] and find_bridge({"PATH": str(elsewhere)}) is None
    found = []
    for folder in (elsewhere, scripts):  # on PATH, then beside this Python (the venv's scripts, on PATH or not)
        exe = folder / ("cursor-sdk-bridge.exe" if __import__("os").name == "nt" else "cursor-sdk-bridge")
        exe.write_bytes(b"")
        exe.chmod(0o755)
        found.append(Path(find_bridge({"PATH": str(elsewhere)})).parent)
    assert found == [elsewhere, scripts]  # this Python's scripts folder first
    with SdkRuntime(KEY, tmp_path / "h", sdk=sdk, environ={"PATH": str(elsewhere)}, spawn=spawn, post=post).open():
        pass
    assert Path(procs[0].args[0]).parent == scripts


def test_a_silent_bridge_times_out_and_is_stopped(tmp_path):
    class Silent:
        lines = queue.Queue()
        thread = SimpleNamespace(is_alive=lambda: True)

        @staticmethod
        def said():
            return ""

    ticks = iter([0.0, 0.0, 0.6, 1.2])
    with pytest.raises(CursorError, match="not ready in 1 s") as caught:
        wait_ready(FakeProc([]), Silent, seconds=1.0, clock=lambda: next(ticks))
    assert caught.value.kind == "setup"
    proc = FakeProc([])
    stop_bridge(proc, None, "", post=lambda url, token: pytest.fail("no Shutdown before the handshake"), seconds=0.1)
    assert proc.terminated and not proc.killed  # told to end, and it did
    stubborn = FakeProc([], stays=True)
    stop_bridge(stubborn, {"url": "http://127.0.0.1:1"}, "t", post=lambda url, token: None, seconds=0.1)
    assert stubborn.killed and stubborn.waits == [0.1, 0.1]
    gone = FakeProc([], exits=0)
    stop_bridge(gone, {"url": "u"}, "t", post=lambda url, token: pytest.fail("not asked: it has ended"), seconds=0.1)


def test_the_sdks_errors_and_what_the_bridges_environment_leaves_out():
    e = failure(PermissionDeniedError("Authenticated caller does not have permission", status=403, code="forbidden"))
    assert (e.kind, e.status, e.code) == ("permission", 403, "forbidden")
    assert failure(ConfigurationError("Invalid model", status=400)).kind == "configuration"
    assert failure(RateLimitError("Too many requests", status=429)).kind == "rate_limit"
    assert failure(TimeoutError("slow")).kind == "timeout" and failure(ConnectionResetError("reset")).kind == "network"
    assert failure(ImportError("no module")).kind == "setup" and failure(OSError("bad exe")).kind == "setup"
    assert failure(ValueError("HTTP 429 too many requests")).kind == "rate_limit"
    assert child_env({"Path": "x", "cursor_api_key": "k", "MY_SERVICE_TOKEN": "t", "HOTKEY": "k", "CURSOR_HOME": "h"},
                     "crsr_k") == {"Path": "x", "HOTKEY": "k", "CURSOR_API_KEY": "crsr_k", "CURSOR_SDK_CLIENT_LANGUAGE": "python"}
