"""The Cursor SDK's surface the runtime (runtime.py) relies on, read from the installed SDK where there is one (CI's
sdk job installs the plugin's `sdk` extra; a machine without it skips these): attaching to a running bridge, the
one-shot prompt and its options, the account and catalog reads with an explicit key and client, the error classes.
Read by signature only: no bridge is started, nothing is sent."""
from __future__ import annotations

import inspect

import pytest

from plugin_platform_cursor.runtime import KINDS

cursor_sdk = pytest.importorskip("cursor_sdk", reason="the Cursor SDK is not installed here (the plugin's sdk extra)")


def takes(fn, *names: str) -> bool:
    """Whether a callable takes these keywords (by name, or through **kwargs)."""
    params = inspect.signature(fn).parameters
    return any(p.kind is p.VAR_KEYWORD for p in params.values()) or set(names) <= set(params)


def test_the_client_attaches_to_a_running_bridge():
    assert takes(cursor_sdk.CursorClient.connect, "auth_token")
    assert takes(cursor_sdk.Agent.prompt, "client")


def test_the_options_take_what_the_runtime_gives():
    assert takes(cursor_sdk.AgentOptions, "model", "api_key", "name", "tools", "local")
    assert takes(cursor_sdk.LocalAgentOptions, "cwd", "setting_sources")
    assert takes(cursor_sdk.ModelSelection, "id", "params") and takes(cursor_sdk.ModelParameterValue, "id", "value")
    cursor_sdk.AgentOptions(model=cursor_sdk.ModelSelection(id="composer-2.5", params=[
        cursor_sdk.ModelParameterValue(id="fast", value="false")]), api_key="crsr_x", name="n", tools=[],
        local=cursor_sdk.LocalAgentOptions(cwd=".", setting_sources=[]))


def test_the_account_and_catalog_reads_take_a_key_and_a_client():
    assert takes(cursor_sdk.Cursor.me, "api_key", "client")
    assert takes(cursor_sdk.Cursor.models.list, "api_key", "client")


def test_the_error_classes_are_there():
    names = {n for n in dir(cursor_sdk) if n.endswith("Error")}
    import cursor_sdk.errors as errors  # noqa: F401 - where the SDK keeps them, when it does

    found = names | {n for n in dir(errors) if n.endswith("Error")}
    assert {"AuthenticationError", "PermissionDeniedError", "RateLimitError", "ConfigurationError"} <= found
    assert set(KINDS) & found
