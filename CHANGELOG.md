# Changelog

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
