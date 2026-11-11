"""What the plugin attaches to (plugin API 2.2, apis.py): the Cursor SDK's card and the bridge's are sound, say how the
key is given, the limits, the prices, the status page and the key page, name exactly what the real runtime calls (run
on the fake SDK, bridge process and Shutdown: nothing imported, started or sent) among the SDK's and the bridge's
others, and every address on them is Cursor's own (and the Connect protocol's, the bridge's wire). The page check is
the weekly one (tests/test_vendor_pages.py, LIMINAL_VENDOR_PAGES=1); nothing is sent here. The user, 2026-11-11: "each
plugin should reflect the the API its attached to, and present links that provide documentation"."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from urllib.parse import urlsplit

from liminal_libs.sources.apis import problems, urls

import plugin_platform_cursor as cursor
from plugin_platform_cursor import ASSISTANT
from plugin_platform_cursor.apis import APIS, CURSOR_BRIDGE, CURSOR_SDK
from plugin_platform_cursor.runtime import BRIDGE, SDK_WRITTEN_FOR, SHUTDOWN_PATH, Ask, SdkRuntime

KEY = "crsr_" + "0" * 24 + "testonlyscratchkey"


def test_the_cards_are_sound_and_are_the_plugins():
    assert problems(APIS, today=date(2026, 11, 11)) == []
    assert ASSISTANT.apis == APIS and cursor.CursorPlugin.apis is APIS and cursor.APIS is APIS
    assert [a.kind for a in APIS] == ["sdk", "socket"] and all(a.verified == "2026-11-11" for a in APIS)
    assert SDK_WRITTEN_FOR in CURSOR_SDK.version and BRIDGE in CURSOR_BRIDGE.base
    assert CURSOR_SDK.link("console") == "https://cursor.com/dashboard/api" and CURSOR_SDK.docs == cursor.SDK_PAGE
    assert all(CURSOR_SDK.link(k) for k in ("docs", "reference", "auth", "pricing", "status", "changelog", "terms"))
    assert "crsr_" in CURSOR_SDK.auth and "pool" in CURSOR_SDK.limits and "$0.50" in CURSOR_SDK.costs
    assert CURSOR_BRIDGE.link("source") == "https://github.com/cursor/sdk-bridge" and CURSOR_BRIDGE.docs == cursor.BRIDGE_PAGE
    assert {cursor.PRICING, cursor.LEGACY_PAGE, cursor.API_PAGE} <= set(urls(APIS))  # the tables' pages among them
    assert ASSISTANT.interface()["apis"] == ["Cursor Python SDK", "Cursor SDK Bridge"]
    assert ASSISTANT.api_facts() == {}  # the instance keeps nothing of a run: each Connect builds its own Assistant


def test_the_cards_name_exactly_what_the_runtime_calls(fake_sdk, tmp_path):
    """The real SdkRuntime on the fake SDK, bridge process and Shutdown: the bridge started with the card's flags, the
    SDK attached, the key's identity, the catalog and one answer asked, the bridge shut down. Each is a used call on
    a card, and the SDK card uses nothing else."""
    result = SimpleNamespace(id="run-1", status="finished", result="OK", model=SimpleNamespace(id="composer-2.5"),
                             duration_ms=10, usage=None)
    sdk, made, spawn, post, procs, posts = fake_sdk(me=SimpleNamespace(api_key_name="k"), models=[], result=result)
    with SdkRuntime(KEY, tmp_path / "home", sdk=sdk, environ={}, bridge=BRIDGE, spawn=spawn, post=post).open() as conn:
        conn.me(), conn.models()
        assert conn.ask(Ask("composer-2.5", "You are terse.", "Is it open?", "false", 5.0))["text"] == "OK"
    (proc,), (client,) = procs, made
    sdk_used = {c.name.split("(")[0] for c in CURSOR_SDK.used}
    assert sdk_used == {"CursorClient.connect", "Cursor.me", "Cursor.models.list", "Agent.prompt"}
    assert client.token and client.me_asked == KEY and client.models_asked == KEY and len(client.prompts) == 1
    bridge_used = [c.name for c in CURSOR_BRIDGE.used]
    started = bridge_used[0].split()
    assert started[0] == proc.args[0] == BRIDGE
    assert [a for a in started if a.startswith("--")] == [a for a in proc.args if a.startswith("--")]
    assert started[started.index("--host") + 1] == proc.args[proc.args.index("--host") + 1] == "127.0.0.1"
    assert f"POST {SHUTDOWN_PATH}" in bridge_used and len(posts) == 1  # its Shutdown, asked once
    assert all(c.used.startswith("through the SDK") for c in CURSOR_BRIDGE.used if "Service." in c.name)
    for api in APIS:
        assert all(c.area in {a.name for a in api.areas} for c in api.calls)
        assert len(api.areas) > len(api.covered) and len(api.calls) > len(api.used)
    prompt = next(c for c in CURSOR_SDK.used if c.name.startswith("Agent.prompt"))
    assert prompt.costs and "tools=[]" in prompt.name and "setting_sources=[]" in prompt.name


def test_every_address_is_cursors_own():
    hosts = {urlsplit(u).hostname for u in urls(APIS)}
    assert hosts == {"cursor.com", "pypi.org", "status.cursor.com", "x.ai", "github.com", "connectrpc.com"}
    assert all(u.startswith("https://github.com/cursor/sdk-bridge") for u in urls(APIS)
               if urlsplit(u).hostname == "github.com")
