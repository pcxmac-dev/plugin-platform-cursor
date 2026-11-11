# Changelog

## 0.2.0 (2026-11-11)

Its API on its page (plugin API 2.2, liminal-libs 1.49.0; the user: "each plugin should reflect the the API its attached
to, and present links that provide documentation, the plugin interface should more or less contain what it already
has, BUT, it should also expose more of what the API is about"). `CursorPlugin.apis` (apis.py) holds two cards, from
Cursor's pages, verified 2026-11-11:
- the Cursor Python SDK: what it is (Cursor's agent, not a model-inference API), the package and the 1.x release it is
  written for, how the key is given, the limits (none published for the SDK; the plans' pools), what it costs, and
  Cursor's pages (the Python SDK, the APIs overview, PyPI, the TypeScript SDK, the SDK's release notes, service
  accounts, models and pricing, the legacy plans, the status page, the dashboard's API keys and usage, the terms);
  every part of it (the agent, runs, token usage, the Cursor namespace, the client, model selection, tools and
  settings, errors and Cursor's models and pricing, which the plugin uses; the cloud runtime, MCP servers and
  subagents, hooks and artifacts, the Cloud Agents API and Cursor's other APIs, which it does not) and its calls
  (`CursorClient.connect`, `Cursor.me`, `Cursor.models.list`, `Agent.prompt`, and others);
- the Cursor SDK Bridge it talks to (cursor-sdk-bridge, started and stopped by the plugin): its handshake, services
  (agent, Cursor, control), local agent store, callbacks, streaming, errors and versioning, and its calls (the command
  line, the ready line, `Shutdown`, and the RPCs the SDK's calls are made of), with cursor/sdk-bridge's pages.

`PRICING`, `LEGACY_PAGE`, `API_PAGE`, `SDK_PAGE` and `BRIDGE_PAGE` come from apis.py. Nothing it sends or shows changes;
the instance keeps nothing of a run, so `api_facts()` says nothing. Needs liminal-libs>=1.49.0. A test runs the real
runtime on the fake SDK, bridge and Shutdown and checks that the cards name exactly what it calls; the weekly page check
asks each address too.

## 0.1.0 (2026-11-09)

The first release (the user: "lets add an AI plugin for cursor"): `CursorPlugin` (an `AssistantPlugin`, plugin API 2.0)
and `CursorAssistant` on the Cursor SDK's local runtime (`cursor-sdk` 1.x, the `sdk` extra). Cursor has no
model-inference API, and of the three ways its agent answers on a key, the SDK is the one open to all users. It
answers in words alone and reports its tokens. The Cloud Agents API needs Premium and up and a VM per answer, and the
CLI keeps its read tools and counts no tokens. The SDK's bridge, `cursor-sdk-bridge`, is started by the plugin for a
call and stopped after it:

- windowless, on this machine's loopback address;
- in an empty folder of its own, with no settings layer of the user's;
- with no tool;
- with an environment without credentials but the login's key;
- shut down by its Shutdown RPC, and killed 5 s later if it is still there.

The plans of The X Subscription (Free, which sends; Plus, Premium, Super, Ultra, Teams, Enterprise) and the legacy ones
(Hobby; Start, which "doesn't include ... the Cursor SDK" and sends nothing; Pro, Pro+). Cursor's own models with their
prices at standard speed and Fast: Composer 2.5 (the default), Grok 4.5, 4.6 and 4.7, asked for at standard speed. The
pages they were written from, verified 2026-11-09.

`CURSOR_API_KEY` (a `crsr_` key; anything else is refused before it is sent) and `CURSOR_ACCOUNT`, read through the
login. Connect checks the key, the account named and the models the key's catalog lists, and sends one answer. The
weekly CI run reads Cursor's pages again and compares every model's prices and every plan's price row by row. Every
error is said in words and scrubbed of the key and the account. Its icon is its maker's mark, Cursor's cube
(`ICON = "cursor"`, liminal-libs 1.40.0's icons.js).
