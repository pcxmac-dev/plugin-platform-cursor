"""Cursor for Liminal: an AI assistant plugin (liminal_libs.assistants, plugin API 2.2) that evaluates
standardized arguments through Cursor's models on your own Cursor API key, by the Cursor SDK, with
Cursor's plans, models and prices written in, dated, and checked against Cursor's pages.

A Liminal plugin released on its own, registered under the entry point group `liminal.providers` as
`cursor`: the plugin `CursorPlugin` (ASSISTANT below), its assistant `CursorAssistant` (assistant.py),
the SDK and its bridge driven by runtime.py, what it attaches to its cards (apis.py: the Cursor SDK, what it reaches
and the bridge it talks to, their pages). It relies on plugin API 2.2 and nothing of the apps.

The user, 2026-11-09: "lets add an AI plugin for cursor", beside the assistants asked for on 2026-11-03
("AI plugins that have a vanilla API, are compliant with the rest of the plugin structure (setup /
connecting methods / etc) but allow interfacing with Claude, Grock and ChatGPT Codex via API key, an
email / account name") and Copilot (2026-11-08).

The way in: Cursor has no model-inference API. Its Cloud Agents API (api.cursor.com/v1/agents) and its
SDKs run Cursor's agent and "are not a standalone model-inference or chat-completions API"
(cursor.com/docs/api). Of the three ways an agent answers on a key, the Python SDK's local runtime is the
most direct: the API page opens the SDK to "All users", it answers in words alone (`tools=[]`), it
reports the run's tokens, and its bridge is a process this plugin starts and stops itself, windowless.
The Cloud Agents API needs a plan with Cloud Agents (Premium and up: not Free or Plus), starts a VM for
every answer and keeps each agent in the account; the CLI (`agent -p`) keeps its read tools even in ask
mode, documents no token counts, and would carry a long argument on a command line. The SDK is the
`sdk` extra (`pip install "plugin-platform-cursor[sdk]"`, which brings the bridge, cursor-sdk-bridge).

What the user sets (the platform's Settings on the plugin's page, kept by the login): `CURSOR_API_KEY`,
a Cursor API key (crsr_: a user's key from the dashboard's API Keys page, or a service account's; another
vendor's key is refused before it is sent); `CURSOR_ACCOUNT`, the email of the Cursor account the key
belongs to, shown with its evaluations and sent to no one (Connect says whether the key is that
account's); its plan `CURSOR_PLAN` (free: The X Subscription's Free; plus, premium, super, ultra, teams,
enterprise; the legacy hobby, start, pro, pro-plus), its model `CURSOR_MODEL` (composer-2.5 by default:
Cursor's cheapest, on every plan), its caps on this machine `CURSOR_REQUESTS_PER_DAY` (20),
`CURSOR_TOKENS_PER_DAY` (200,000), `CURSOR_MAX_OUTPUT_TOKENS` (1,024; the SDK takes no output cap, so it
is not sent). No effort setting: Cursor publishes no parameter id for a model's effort.

The user, 2026-11-03: "the ai plugins should support free, and if that means they have no API access,
then so be it": Cursor opens the SDK to all users, so the Free plan sends (its usage limited, its models
Cursor's own); legacy Start, which "doesn't include ... the Cursor SDK", sends nothing. "every time any
of the three vendors changes their plans/rates there will have to be a way to query through the plugin
to update itself, or worst case, just version up every time w/ CI catching the disparity between code and
latest rates through unit testing": Connect compares the models the key's catalog lists with the table;
the weekly CI run reads Cursor's pages (SOURCES) and fails when a written-in figure is gone or a model's
prices or a plan's price changed, which is a new release of this plugin.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from liminal_libs.assistants import AssistantPlugin, Caps, Model, Plan, Source
from liminal_libs.layout import Database
from liminal_libs.sources.keys import KeyVar

from .apis import API_PAGE, APIS, BRIDGE_PAGE, LEGACY_PAGE, PRICING, SDK_PAGE
from .assistant import KEY_PREFIX, CursorAssistant
from .runtime import SDK_WRITTEN_FOR, SdkRuntime

__all__ = ["ASSISTANT", "CursorPlugin", "CursorAssistant", "PLANS", "MODELS", "SOURCES", "VERIFIED", "SUBSCRIPTION",
           "LEGACY", "FAST", "LONG_CONTEXT", "CURSOR_MODELS", "PRICING", "LEGACY_PAGE", "API_PAGE", "SDK_PAGE",
           "BRIDGE_PAGE", "PROTOCOL", "RUNTIME_HOME", "SDK_WRITTEN_FOR", "KEY_PREFIX", "APIS"]

VERIFIED = "2026-11-09"  # the day the tables below were checked against SOURCES
RUNTIME_HOME = "assistants/cursor/"  # the bridge's empty workspace and its agents' state, in the data folder

# The X Subscription's plans (cursor.com/docs/models-and-pricing, 2026-11-09): Cursor is sold in one subscription
# for Grok, Cursor and X (billed by X Subscription Corp at grok.com/dashboard/billing). Each paid plan includes a
# weekly pool of usage for Cursor's own models, shared with Grok, refreshed weekly; Cursor publishes its size only
# as a multiple of Plus's. The price a month and a year in dollars, the usage included.
SUBSCRIPTION = {"plus": (8, 80, "Base"), "premium": (30, 300, "4x Plus"), "super": (100, 1_000, "15x Plus"),
                "ultra": (200, 2_000, "50x Plus")}
# Cursor's plans before The X Subscription (cursor.com/docs/account/pricing/legacy-cursor-plans): closed to new
# customers, kept by their subscribers (two monthly pools, Cursor Models and Other Models): the price a month.
# Legacy Ultra ($200) and Teams (Standard $40, Premium $120 a user a month) are under `ultra` and `teams`.
LEGACY = {"pro": 20, "pro-plus": 60}
CURSOR_MODELS = ("composer-2.5", "grok-4.5", "grok-4.6", "grok-4.7")  # Cursor's own: every plan's, Free's alone
BEYOND = ("prepaid credit (top-ups) at the table's rates, within the monthly additional usage limit you set (the "
          "spending cap)")


def _subscription(name: str) -> str:
    month, year, usage = SUBSCRIPTION[name]
    return f"${month} a month (${year:,} a year): {'the base' if usage == 'Base' else usage} usage of Cursor's models"


PLANS = (
    Plan("free", "Free", models=CURSOR_MODELS, price="free: Agent and Chat with limited usage (its size not published)",
         spend_cap="none to set: no prepaid credit or additional usage",
         note="Cursor's own models only (Grok 4.7, 4.6, 4.5, Composer 2.5); the SDK is open to all users (the API page), "
              "but Cursor does not say whether a Free account can make an API key: Connect tells"),
    Plan("plus", "Plus", models=CURSOR_MODELS, price=_subscription("plus"), spend_cap=BEYOND,
         note="Cursor's own models only, at fixed settings (Fast off, effort medium, Grok 4.7 at 256k); no Auto, Cloud "
              "Agents, Automations, Bugbot, Origin or third-party models; the SDK is not among what Plus leaves out"),
    Plan("premium", "Premium", price=_subscription("premium"), spend_cap=BEYOND,
         note="adds Cloud Agents, Automations, Bugbot, Origin and third-party models at API list price (prepaid credit; "
              "not in this table: Cursor publishes no ids for them)"),
    Plan("super", "Super", price=_subscription("super"), spend_cap=BEYOND,
         note="Premium's, with priority model access at peak times"),
    Plan("ultra", "Ultra", price=_subscription("ultra"), spend_cap=BEYOND,
         note="Super's, with the earliest access to new products and models; a legacy Ultra ($200 a month: two monthly "
              "pools, on-demand usage) includes the Cursor SDK too"),
    Plan("teams", "Teams", price="$30, $100 or $200 a seat a month (a Premium, Super or Ultra seat); legacy Teams "
                                  "Standard $40 and Premium $120 a user a month",
         spend_cap="the team's shared prepaid balance and its one cap (legacy: on-demand usage, on by default, the team's "
                   "spend limit)",
         note="a seat's usage is the matching individual plan's; third-party models also carry the Cursor Token Rate "
              "($0.25 a million tokens; Cursor's own models are exempt); the catalog is the team's: admins may hold "
              "models back"),
    Plan("enterprise", "Enterprise", price="custom (contact sales)", spend_cap="pooled usage, the organization's controls",
         note="pooled usage across Grok and Cursor; the Cursor Token Rate on eligible third-party models"),
    Plan("hobby", "Hobby (legacy)", models=CURSOR_MODELS, price="free: Agent, Chat and Tab with limited usage",
         spend_cap="none: no on-demand usage; AI features pause until the pool resets",
         note="the free legacy plan: a monthly Cursor Models pool, no Other Models pool, no Cloud Agents; the legacy page "
              "names the SDK on Pro, Pro+ and Ultra and leaves it out of Start, and says nothing of Hobby, while the API "
              "page opens the SDK to all users: Connect tells"),
    Plan("start", "Start (legacy, India)", api_access=False, models=CURSOR_MODELS, price="₹649 a month (tax inclusive)",
         spend_cap="none: no on-demand usage",
         note="\"Start doesn't include ... the Cursor SDK\" (the legacy plans' page): nothing is sent; Cursor's own "
              "models at fixed settings (medium effort, standard speed)"),
    Plan("pro", "Pro (legacy)", price=f"${LEGACY['pro']} a month: two monthly pools (Cursor Models, Other Models)",
         spend_cap="on-demand usage, off until you turn it on, with a monthly spend limit",
         note="includes the Cursor SDK; Fast mode and Grok's effort levels"),
    Plan("pro-plus", "Pro+ (legacy)", price=f"${LEGACY['pro-plus']} a month: more of both monthly pools than Pro",
         spend_cap="on-demand usage, off until you turn it on, with a monthly spend limit",
         note="includes the Cursor SDK; Fast mode and Grok's effort levels"),
)

# The other speed and the long context, per million tokens (input, a cached input token, output): not asked for
# (the plugin asks for standard speed and the standard window), written in for the notes and checked weekly.
FAST = {"composer-2.5": (3.00, 0.50, 15.00), "grok-4.5": (4.00, 1.00, 18.00), "grok-4.6": (4.00, 1.00, 12.00),
        "grok-4.7": (4.00, 1.00, 12.00)}
LONG_CONTEXT = {"grok-4.7": ((4.00, 1.00, 12.00), (6.00, 1.50, 18.00))}  # Grok 4.7 500k: standard, then Fast


def _fast(model_id: str) -> str:
    i, c, o = FAST[model_id]
    return f"its Fast speed (not asked for) ${i:.2f} in, ${c:.2f} cached, ${o:.2f} out"


OWN = ("Cursor's own: it draws from the plan's pool; these are the rates beyond it (prepaid credit, or a legacy plan's "
       "on-demand usage)")
UNPUBLISHED = ("its id is not in Cursor's docs: {id} by the catalog's scheme (Cursor's catalog listed grok-4.5 and "
               "composer-2.5 to the SDK, its forum, 2026-07-29): Connect says whether your catalog has it")

# Cursor's own models (cursor.com/docs/models-and-pricing, 2026-11-09), with the ids the SDK takes: prices per
# million tokens at standard speed (input, output, a cached input token; Cursor's models have no cache-write price),
# the context window where published, whether a reasoning effort applies (Grok's: low, medium, high, xhigh; fixed at
# medium on Plus and Start; not set by this plugin: Cursor publishes no parameter id for it). The cheapest first.
# Left out: the third-party models (Claude, GPT, Gemini ..., at API list price on Premium and up: Cursor publishes no
# ids the SDK takes for them; Connect lists your catalog's under "models not in the table"), Auto and Cursor Router
# (auto-smart, Teams and Enterprise, with an optimize_for parameter).
MODELS = (
    Model("composer-2.5", "Composer 2.5", 0.50, 2.50, 0.20, None, (), False,
          note=f"{OWN}; Cursor's agentic coding model, its id in Cursor's SDK docs; {_fast('composer-2.5')}"),
    Model("grok-4.5", "Grok 4.5", 2.00, 6.00, 0.50, None, (), True,
          note=f"{OWN}; jointly trained by Cursor and SpaceXAI; its id as Cursor's catalog listed it to the SDK (its forum, "
               f"2026-07-29), not in the docs; {_fast('grok-4.5')}"),
    Model("grok-4.6", "Grok 4.6", 2.00, 6.00, 0.50, None, (), True,
          note=f"{OWN}; jointly trained by Cursor and SpaceXAI; {UNPUBLISHED.format(id='grok-4.6')}; {_fast('grok-4.6')}"),
    Model("grok-4.7", "Grok 4.7", 2.00, 6.00, 0.50, 256_000, (), True,
          note=f"{OWN}; jointly trained by Cursor and SpaceXAI; its 256k window (the 500k long context, not asked for: "
               f"$4.00 in, $1.00 cached, $12.00 out); effort high by default, medium on Plus and Start; "
               f"{UNPUBLISHED.format(id='grok-4.7')}; {_fast('grok-4.7')}"),
)

# PRICING, LEGACY_PAGE, API_PAGE, SDK_PAGE and BRIDGE_PAGE (apis.py): the pricing, legacy plans, APIs, Python SDK
# and bridge pages; PROTOCOL, the bridge's protocol as text (the weekly check reads it)
PROTOCOL = "https://raw.githubusercontent.com/cursor/sdk-bridge/main/docs/protocol.md"

# Where the tables come from, with what each page must still show (verify.check_sources, weekly in CI; the models'
# prices and the plans' prices are compared row by row there too: tests/test_vendor_pages.py). A marker never ends at
# a code span (a page's text puts a space before the punctuation after one).
SOURCES = (
    Source(PRICING, "the plans, their prices, the pool and the models' prices", "Cursor is sold as part of The X Subscription",
           ("$8/mo", "$30/mo", "$100/mo", "$200/mo", "$80/yr for Plus", "$300/yr for Premium", "$1,000/yr for Super",
            "$2,000/yr for Ultra", "4x Plus", "15x Plus", "50x Plus", "$30, $100, or $200 per seat/mo",
            "Fast is off, effort is medium", "It refreshes weekly", "These rates apply when you buy additional usage beyond",
            *(m.title for m in MODELS))),
    Source(LEGACY_PAGE, "the legacy plans and which include the Cursor SDK",
           "Legacy Cursor plans are the plans Cursor sold before The X Subscription",
           ("$20/mo", "$60/mo", "$40/user/mo", "$120/user/mo", "Hobby is the free legacy plan",
            "Automations, Origin, and the Cursor SDK", "or the Cursor SDK")),
    Source(API_PAGE, "the SDKs open to all users, the key's form", "They are not a standalone model-inference or "
                                                                    "chat-completions API.",
           ("Run Cursor agents from Python with sync and async clients for local and cloud runtimes.", "All users",
            KEY_PREFIX)),
    Source(SDK_PAGE, "the Python SDK the runtime drives", "pip install cursor-sdk",
           ("Requires Python 3.10 or later.", "offers no built-in tools, so the model can only respond with text.",
            "Cache reads and writes are already part of", "Reasoning tokens, a subset of", "Ambient settings layers",
            "Team Admin API keys are not yet supported.", "attach to it with")),
    Source(BRIDGE_PAGE, "the bridge the SDK's wheel carries", "The SDK Bridge is a small local server",
           ("Windows is x64 only.", "The bridge listens on", "Python already talks to a bundled copy of the bridge.")),
    Source(PROTOCOL, "the bridge's handshake and shutdown runtime.py follows", "Spawning and the ready line",
           ("cursor-sdk-bridge ready", "authTokenFile", "schemaVersion", "--state-root", "SdkBridgeControlService.Shutdown")),
)


class CursorPlugin(AssistantPlugin):
    """Cursor: the plugin (see the module's docstring)."""

    ICON = "cursor"  # its maker's mark (icons.js, liminal-libs 1.40.0): Cursor's cube, the arrow cut out of it
    name = "cursor"
    title = "Cursor"
    about = "Cursor's models through the Cursor SDK: evaluations of standardized arguments on your Cursor API key"
    vendor = "Cursor"
    signup = "https://cursor.com/dashboard"
    order = 504
    api = "2.2"  # 2.2: what it attaches to (apis)
    apis = APIS  # the Cursor SDK, what it reaches and the bridge it talks to (apis.py)
    assistant = CursorAssistant
    plans = PLANS
    models = MODELS
    default_model = "composer-2.5"
    verified = VERIFIED
    sources = SOURCES
    caps = Caps(requests_per_day=20)  # 20 requests and 200,000 tokens a day here, 1,024 output tokens (not sent)
    efforts = ()  # Cursor publishes no parameter id for a model's effort: none is set
    standard_speed = frozenset(FAST)  # the models asked for at standard speed (fast=false)
    account_label = "account (Cursor email)"
    account_hint = ("the email of the Cursor account the key belongs to: shown with its evaluations, sent to no one (the "
                    "SDK takes no user field); Connect says whether a user's key is that account's")
    databases = (Database(RUNTIME_HOME, "the Cursor SDK bridge's empty workspace and its agents' local state", engine="files"),)

    @property
    def keys(self) -> tuple[KeyVar, ...]:
        key, account = super().keys
        return (replace(key, label="Cursor API key (crsr_)",
                        hint="a user API key from the Cursor dashboard's API Keys page, or a service account's from your "
                             "team's settings (a Team Admin key is not taken); it begins with crsr_"), account)

    @property
    def plan_note(self) -> str:
        return ("its plan is what you choose: Cursor sends no limits the plans differ by and no usage left (your editor "
                "and the dashboard show the pool); Connect checks the key and compares the models your catalog lists with "
                f"the tables (verified {self.verified or 'at release'})")

    def build(self, settings, session=None, now=None):
        """Its Assistant, the runtime's folder beside the settings' main file (the data folder)."""
        a = super().build(settings, session=session, now=now)
        db = getattr(settings, "db_path", None)
        if isinstance(a.runtime, SdkRuntime) and db and str(db) != ":memory:":
            a.runtime.home = Path(db).parent / RUNTIME_HOME
        return a


ASSISTANT = CursorPlugin()
