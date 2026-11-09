# plugin-platform-cursor

Cursor for [Liminal](https://github.com/pcxmac-dev/liminal-charts): an AI assistant plugin (plugin API 2.0,
`liminal_libs.assistants`, a platform plugin) that evaluates standardized arguments (a question over headlines, an
assessment, a report; a judge over earlier answers) through Cursor's models on your own Cursor API key, with
Cursor's plans, models and prices written in.

The user, 2026-11-09: "lets add an AI plugin for cursor", beside the assistants asked for on 2026-11-03 ("AI plugins
that have a vanilla API, are compliant with the rest of the plugin structure (setup / connecting methods / etc) but
allow interfacing with Claude, Grock and ChatGPT Codex via API key, an email / account name"; "the ai plugins should
support free"; "CI catching the disparity between code and latest rates through unit testing") and Copilot.

## How it reaches Cursor

Cursor has no model-inference API. Its Cloud Agents API and its SDKs "are not a standalone model-inference or
chat-completions API" ([cursor.com/docs/api](https://cursor.com/docs/api)): every way in runs Cursor's agent. There
are three ways an agent answers on your own key, and this plugin takes the most direct one:

- **The Cursor SDK, its local runtime (used).** The Python SDK (`cursor-sdk`) is open to "All users" (the API page).
  It runs the agent on this machine with `tools=[]` ("the model can only respond with text"), and the inference is
  Cursor's own hosted models. A run reports its tokens (input with the cache reads and writes, output with the
  reasoning), so the plugin's caps and cost hold. What runs here is the SDK's bridge, `cursor-sdk-bridge`, a small
  local server its wheel carries. The plugin starts that bridge itself for a call and stops it after:
  - windowless (`CREATE_NO_WINDOW`);
  - on this machine's loopback address;
  - in an empty working folder of its own, `assistants/cursor/` in the data folder, with the agents' state beside it;
  - with no settings layer of yours (`setting_sources=[]`: no `.cursor` rules, MCP servers, hooks or plugins);
  - with an environment holding no credential but the key it is given.

  The SDK attaches to the bridge with `CursorClient.connect`. The handshake follows
  [cursor/sdk-bridge's protocol](https://github.com/cursor/sdk-bridge/blob/main/docs/protocol.md): the ready line on
  stderr, the token file, and Shutdown, with a kill 5 s later if the bridge is still there.
- **The Cloud Agents API** (`POST https://api.cursor.com/v1/agents`, a no-repo agent; `GET /v1/me`,
  `GET /v1/models`; the key as a Bearer or Basic credential). This needs a plan with Cloud Agents: Premium and up,
  Teams, Enterprise or a legacy paid plan, not Free or Plus. It starts a VM for every answer, keeps every
  agent in your account, and a privacy- or storage-restricted account is refused with a 403 (Cursor's staff on its
  forum, 2026-08-06). It was not used.
- **The CLI** (`agent -p --output-format json`, installed on Windows by
  `irm 'https://cursor.com/install?win32=true' | iex` into `%LOCALAPPDATA%\cursor-agent`, the key in
  `CURSOR_API_KEY`). Print mode has every tool, write and shell among them, and ask mode, read-only, still reads
  files. Its JSON output documents no token counts. A long argument would go on a command line, which Windows limits
  to 32,767 characters. It was not used, so no CLI is needed.

## Setup

- `cursor` on the platform's page (the AI assistants): Settings takes `CURSOR_API_KEY`, a Cursor API key, and
  `CURSOR_ACCOUNT`, the email of the Cursor account the key belongs to. The account is shown with the plugin's
  evaluations and sent to no one; Connect says whether a user's key is that account's. Both are kept by the
  platform's login and read only through it.
- The key: on the Cursor dashboard, **API Keys**, **New API Key**, or a service account's key from your team's
  settings. A Team Admin key is not taken by the SDK. Cursor's keys begin with `crsr_`, and the plugin refuses
  anything else before sending it, so another vendor's secret is never handed to Cursor. A user on Cursor's forum
  (2026-04-26) found the keys moved under **Integrations** on the dashboard; the docs still say API Keys.
- Plan: `CURSOR_PLAN`, the plan your account is on. Cursor sends no limits the plans differ by, so the plan is what
  you choose. `free` is the default and sends. Cursor is now "sold as part of The X Subscription, one subscription for
  Grok, Cursor, and X". Its paid plans include one weekly pool of usage for Cursor's own models, shared with Grok, and
  Cursor publishes its size only as a multiple of Plus's:

  | `CURSOR_PLAN` | Plan | Price | Usage of Cursor's models | The SDK |
  | --- | --- | --- | --- | --- |
  | `free` | Free | $0 | limited (not published) | open to all users; whether Free can make a key is not said: Connect tells |
  | `plus` | Plus | $8 a month ($80 a year) | the base | not among what Plus leaves out |
  | `premium` | Premium | $30 a month ($300 a year) | 4x Plus | yes |
  | `super` | Super | $100 a month ($1,000 a year) | 15x Plus | yes |
  | `ultra` | Ultra | $200 a month ($2,000 a year); legacy Ultra $200 | 50x Plus | yes |
  | `teams` | Teams | $30, $100 or $200 a seat a month; legacy Standard $40, Premium $120 a user | the seat's tier | yes |
  | `enterprise` | Enterprise | custom | pooled | yes |
  | `hobby` | Hobby (legacy) | free | limited, monthly | not said: Connect tells |
  | `start` | Start (legacy, India) | ₹649 a month | monthly | **no**: nothing is sent |
  | `pro` | Pro (legacy) | $20 a month | two monthly pools | yes |
  | `pro-plus` | Pro+ (legacy) | $60 a month | more of both | yes |

  Past the pool, The X Subscription goes on from prepaid credit (top-ups) at the models' rates, within a monthly
  additional usage limit you set. A legacy plan goes on with on-demand usage under its spend limit; Hobby and Start
  pause instead. Free and Plus reach Cursor's own models only, Plus at fixed settings (Fast off, medium effort).
  Third-party models (Claude, GPT, Gemini ...) are on Premium and up at their API list price. They are not in the
  table, because Cursor publishes no model ids the SDK takes for them; Connect lists the ones your catalog has.
- Model: `CURSOR_MODEL`, `composer-2.5` by default. It is the cheapest, and on every plan. Prices are per million
  tokens at standard speed (input, cached input, output): the rates Cursor charges beyond the pool. The plugin asks
  for standard speed (`fast=false`), because Fast costs more and draws the pool faster:

  | `CURSOR_MODEL` | Model | Price | Fast (not asked for) |
  | --- | --- | --- | --- |
  | `composer-2.5` | Composer 2.5 | $0.50, $0.20, $2.50 | $3.00, $0.50, $15.00 |
  | `grok-4.5` | Grok 4.5 | $2.00, $0.50, $6.00 | $4.00, $1.00, $18.00 |
  | `grok-4.6` | Grok 4.6 | $2.00, $0.50, $6.00 | $4.00, $1.00, $12.00 |
  | `grok-4.7` | Grok 4.7 (256k; the 500k long context is not asked for) | $2.00, $0.50, $6.00 | $4.00, $1.00, $12.00 |

  `composer-2.5` is the id in Cursor's SDK docs, and `grok-4.5` is the id Cursor's catalog listed to the SDK (its
  forum, 2026-07-29). The docs publish no ids for Grok 4.6 and 4.7: `grok-4.6` and `grok-4.7` follow the catalog's
  scheme, and Connect says whether your catalog has them. There is no effort setting: Grok's levels (low, medium, high,
  xhigh) exist, but Cursor publishes no parameter id for them. Auto and Cursor Router (`auto-smart`, Teams and
  Enterprise, with an `optimize_for` parameter) are not offered.
- Caps on this machine, every database together: `CURSOR_REQUESTS_PER_DAY` (20), `CURSOR_TOKENS_PER_DAY` (200,000),
  and `CURSOR_MAX_OUTPUT_TOKENS` (1,024). The output cap is kept for the Plugins view only: the SDK takes no output
  cap, so it is not sent.
- Connect checks the key (`Cursor.me`: its name, a user's or a service account's), the account named, and the models
  your catalog lists against the table (and whether the model chosen takes standard speed). It then sends one answer
  of a few tokens. It cannot show the pool left: the editor and the dashboard do.

Nothing is sent from an offline copy of the app (`LIMINAL_OFFLINE`).

## Install

Into the app's environment, from the app's folder, with the SDK (Python 3.10 or later; on Windows the bridge is x64
only):

```powershell
.venv\Scripts\python.exe -m pip install "plugin-platform-cursor[sdk] @ git+https://github.com/pcxmac-dev/plugin-platform-cursor@main"
```

The SDK's wheel puts `cursor-sdk-bridge` in the environment's scripts folder, where the plugin finds it (by
`shutil.which`, there first, then on PATH). Without the `sdk` extra the plugin loads and is set up, and Connect says
the SDK is missing. The platform loads it on its next start.

## Sources (verified 2026-11-09)

- [Models & Pricing](https://cursor.com/docs/models-and-pricing): the plans, their prices, the weekly pool, the
  models' prices.
- [Legacy Cursor plans](https://cursor.com/docs/account/pricing/legacy-cursor-plans): Hobby, Start, Pro, Pro+,
  Ultra, Teams, and which include the Cursor SDK.
- [Cursor APIs Overview](https://cursor.com/docs/api): the SDKs open to all users, the key's form, the Cloud Agents
  API.
- [Python SDK](https://cursor.com/docs/sdk/python) and [SDK Bridge](https://cursor.com/docs/sdk/bridge): what the
  runtime drives; [protocol.md](https://github.com/cursor/sdk-bridge/blob/main/docs/protocol.md): the bridge's
  handshake.
- [Cloud Agents](https://cursor.com/docs/cloud-agent),
  [Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints), [CLI](https://cursor.com/docs/cli/overview),
  [Headless CLI](https://cursor.com/docs/cli/headless) and
  [CLI output format](https://cursor.com/docs/cli/reference/output-format): the ways not taken.

## Tests

`python -m pytest -q`: fake answers, a fake SDK, a fake bridge process and a fake Shutdown. Nothing is imported,
started or sent, and no real key is used. `LIMINAL_VENDOR_PAGES=1` adds the weekly page check: every model's prices
at both speeds and every plan's price against Cursor's pages, row by row. With the `sdk` extra installed,
`tests/test_sdk_surface.py` checks the SDK's options, client and errors the runtime relies on.
