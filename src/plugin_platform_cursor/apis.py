"""What the plugin attaches to (plugin API 2.2, liminal_libs.sources.apis), as Cursor's own pages describe it (read
2026-11-11): Cursor's Python SDK (its docs, the package), what it reaches (Cursor's agent and models, the plans' pools
and prices; Cursor's REST APIs beside it) and the local bridge it talks to (cursor-sdk-bridge, which the plugin starts
and stops itself; its protocol in cursor/sdk-bridge). The SDK's parts the plugin uses come first, then the rest. The
tables the evaluations are costed and planned by stay the plugin's (PLANS, MODELS, SOURCES). The user, 2026-11-11:
"each plugin should reflect the the API its attached to, and present links that provide documentation ... it should
also expose more of what the API is about"."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

from .runtime import BRIDGE, SDK_PACKAGE, SDK_WRITTEN_FOR, SHUTDOWN_PATH

DOCS = "https://cursor.com/docs/"
PRICING = DOCS + "models-and-pricing"
LEGACY_PAGE = DOCS + "account/pricing/legacy-cursor-plans"
API_PAGE = DOCS + "api"
SDK_PAGE = DOCS + "sdk/python"
BRIDGE_PAGE = DOCS + "sdk/bridge"
REPO = "https://github.com/cursor/sdk-bridge"
BRIDGE_DOCS = REPO + "/blob/main/docs/"
VERIFIED = "2026-11-11"  # the day these facts were read from Cursor's pages

AGENT = "Agent"
CATALOG = "The Cursor namespace"
CLIENT = "CursorClient"

CURSOR_SDK = Api(
    name="Cursor Python SDK",
    maker="Cursor",
    about=("Cursor's SDK runs Cursor's agent (the one in its editor, CLI and web app) from Python: an Agent holding a "
           "conversation and its settings, runs (one prompt each, with its stream, status, result and tokens), local or "
           "cloud runtimes behind one interface, the account's identity and model catalog, MCP servers, subagents, "
           "custom tools, hooks and artifacts. Cursor says it is not a standalone model-inference API: every answer is "
           "an agent run. Locally the SDK talks to its bundled bridge; Cursor's REST APIs (Cloud Agents, Admin, "
           "Analytics ...) are beside it."),
    kind="sdk",
    base=f"cursor_sdk ({SDK_PACKAGE}: the plugin's sdk extra), its local runtime",
    version=f"{SDK_PACKAGE} {SDK_WRITTEN_FOR} (the 1.x API)",
    auth=("a Cursor API key (crsr_) given as api_key on every call, never the environment's: a user's key from the "
          "dashboard's API Keys page, or a service account's from the team's settings; Team Admin keys are not taken"),
    limits=("Cursor publishes no rate limits for the SDK (its REST APIs default to 20 requests a minute where an "
            "endpoint says none); a RateLimitError is too many requests or the usage limits exceeded; the limit that "
            "counts is the plan's pool of usage (weekly on The X Subscription, monthly on the legacy plans)"),
    costs=("SDK runs follow the editor's pricing and pools (shown on the usage dashboard under the SDK tag): the plan's "
           "pool first, then prepaid credit (a legacy plan's on-demand usage) at the model's rate per million tokens: "
           "Composer 2.5 $0.50 in and $2.50 out, Grok 4.5 to 4.7 $2 and $6, each at standard speed; plans Plus $8, "
           "Premium $30, Super $100, Ultra $200 a month"),
    links=(
        Link("Python SDK", SDK_PAGE, "docs"),
        Link("Cursor APIs overview", API_PAGE, "reference"),
        Link(f"{SDK_PACKAGE} on PyPI", "https://pypi.org/project/cursor-sdk/", "sdk"),
        Link("TypeScript SDK", DOCS + "sdk/typescript", "sdk"),
        Link("SDK release notes", DOCS + "release-notes/sdk", "changelog"),
        Link("Service accounts", DOCS + "account/enterprise/service-accounts", "auth"),
        Link("Models and pricing", PRICING, "pricing"),
        Link("Legacy Cursor plans", LEGACY_PAGE, "pricing"),
        Link("Cursor status", "https://status.cursor.com/", "status"),
        Link("API keys (dashboard)", "https://cursor.com/dashboard/api", "console"),
        Link("Usage (dashboard)", "https://cursor.com/dashboard/usage", "console"),
        Link("Terms of service", "https://cursor.com/en-US/terms-of-service", "terms"),
        Link("SpaceXSI subscription terms", "https://x.ai/legal", "terms"),
    ),
    areas=(
        Area(AGENT, "an agent created, prompted, resumed, listed and closed; Agent.prompt the one-shot: create, send one "
                    "prompt, wait for the run, dispose", SDK_PAGE,
             covered=("one Agent.prompt for each answer: the model at standard speed (fast=false), the key, no tool, "
                      "no settings layer of this machine's, the plugin's empty workspace")),
        Area("Runs", "one prompt's run: its stream, wait, status, result, conversation, cancellation", SDK_PAGE,
             covered="the run's result: its text, its id, the model that answered"),
        Area("Token usage", "a run's tokens (cache reads and writes, reasoning among them); an agent's billed usage and "
                            "cost (cloud agents)", SDK_PAGE,
             covered="each run's tokens counted on the plugin's caps and costed by the table"),
        Area(CATALOG, "the key's identity (Cursor.me), the model catalog with each model's parameters, the repositories "
                      "for cloud agents", SDK_PAGE,
             covered="Connect: the key's name and email, and the catalog compared with the table"),
        Area(CLIENT, "a client attached to a bridge (connect) or launching one (launch_bridge), its timeouts and "
                     "retries", SDK_PAGE, covered="attached to the bridge the plugin starts itself (connect)"),
        Area("Model selection", "a model by id with its parameters (fast, reasoning effort), and Cursor Router "
                                "(auto-smart) on Teams and Enterprise", SDK_PAGE,
             covered="the model chosen, at standard speed where it has a Fast one"),
        Area("Tools and settings", "the toolset restricted (tools), custom tools, the settings layers loaded "
                                   "(setting_sources)", SDK_PAGE,
             covered="no tool at all (tools=[]) and no settings layer (setting_sources=[])"),
        Area("Errors", "the SDK's error classes: authentication, permission, rate limit, configuration, busy agent, "
                       "network, timeout", SDK_PAGE, covered="each said in words as a refusal, scrubbed of the key"),
        Area("Cursor's models and pricing", "Cursor's own models and the third-party ones, the plans' pools and prices",
             PRICING, covered="the plugin's tables (plans, models, prices) and the weekly page check"),
        Area("Cloud runtime", "agents run in Cursor's cloud, a VM with the repository cloned in", SDK_PAGE),
        Area("MCP servers and subagents", "MCP servers offered to the agent; subagents, nested and in the background",
             SDK_PAGE),
        Area("Hooks and artifacts", "hooks on the agent's steps; a cloud agent's artifacts", SDK_PAGE),
        Area("Cloud Agents API", "the REST API for cloud agents (api.cursor.com/v1/agents), Basic or Bearer auth, on "
                                 "plans with Cloud Agents", DOCS + "cloud-agent/api/endpoints"),
        Area("Cursor's other APIs", "the Admin, Analytics, AI Code Tracking, Bugbot and Origin APIs (Enterprise teams, "
                                    "Origin in early beta)", API_PAGE),
    ),
    calls=(
        Call("CursorClient.connect(url, auth_token)", "attach the SDK to a running bridge", CLIENT,
             used="the client on the bridge the plugin started", docs=SDK_PAGE),
        Call("Cursor.me(api_key, client)", "whose key it is", CATALOG,
             used="Connect: a user's or a service account's key, its email checked", docs=SDK_PAGE),
        Call("Cursor.models.list(api_key, client)", "the key's model catalog", CATALOG,
             used="Connect: the models compared with the table, the speed checked", docs=SDK_PAGE),
        Call('Agent.prompt(message, AgentOptions(model=ModelSelection(id, params=[fast=false]), api_key, name, '
             'tools=[], local=LocalAgentOptions(cwd, setting_sources=[])), client)', "one prompt to a new agent",
             AGENT, used="each evaluation's answer, and Connect's probe", docs=SDK_PAGE, costs=True),
        Call("Agent.create(options)", "an agent kept for several prompts", AGENT, docs=SDK_PAGE),
        Call("agent.send(message)", "a prompt to an agent, its run returned", "Runs", docs=SDK_PAGE, costs=True),
        Call("run.stream()", "a run's messages as they come", "Runs", docs=SDK_PAGE),
        Call("run.cancel()", "cancel a run", "Runs", docs=SDK_PAGE),
        Call("agent.get_usage()", "a cloud agent's billed usage and cost", "Token usage", docs=SDK_PAGE),
        Call("Cursor.repositories.list()", "the repositories for cloud agents", CATALOG, docs=SDK_PAGE),
        Call("CursorClient.launch_bridge()", "start the bundled bridge (the plugin starts it itself, windowless)",
             CLIENT, docs=SDK_PAGE),
        Call("POST api.cursor.com/v1/agents", "create a cloud agent over REST", "Cloud Agents API",
             docs=DOCS + "cloud-agent/api/endpoints", writes=True, costs=True),
        Call("GET api.cursor.com/v1/me", "the key's identity over REST", "Cloud Agents API", docs=API_PAGE),
    ),
    verified=VERIFIED,
)

HANDSHAKE = "Lifecycle and handshake"
CONTROL = "SdkBridgeControlService"

CURSOR_BRIDGE = Api(
    name="Cursor SDK Bridge",
    maker="Cursor",
    about=("A small local server that embeds Cursor's TypeScript SDK and serves its agent surface as the sdk.v1 Connect "
           "protocol (protobuf or JSON in plain POSTs over HTTP/1.1, not classic gRPC) on a loopback port; the Python "
           "SDK talks to a bundled copy and adapters in other languages spawn it. It prints a ready line on stderr with "
           "its address and a token file, serves the agent, Cursor and control services, and calls back an adapter's "
           "custom-tool and store servers."),
    kind="socket",
    base=f"{BRIDGE} (installed beside the SDK by its wheel) on 127.0.0.1, an ephemeral port",
    version="sdk.v1 (the ready line's schemaVersion 1, transport tcp, protocol connect); its release tags are the SDK's",
    auth=("a bearer token the bridge writes to the file its ready line names (an older bridge gives it inline), read "
          "once and never logged; the bridge reaches Cursor's API over HTTPS with the key the SDK gives each call"),
    limits="",
    costs="none of its own: the agent runs it serves are billed as the SDK's card says",
    links=(
        Link("SDK Bridge", BRIDGE_PAGE, "docs"),
        Link("cursor/sdk-bridge", REPO, "source"),
        Link("Lifecycle and handshake", BRIDGE_DOCS + "protocol.md", "reference"),
        Link("Services", BRIDGE_DOCS + "services.md", "reference"),
        Link("Streaming", BRIDGE_DOCS + "streaming.md", "reference"),
        Link("Errors", BRIDGE_DOCS + "errors.md", "reference"),
        Link("Versioning", BRIDGE_DOCS + "versioning.md", "reference"),
        Link("Curl smoke test", BRIDGE_DOCS + "smoke-test.md", "guide"),
        Link("Releases", REPO + "/releases", "changelog"),
        Link("The Connect protocol", "https://connectrpc.com/docs/protocol", "spec"),
    ),
    areas=(
        Area(HANDSHAKE, "spawn flags, the ready line on stderr, the token file, the shutdown order",
             BRIDGE_DOCS + "protocol.md",
             covered=("started windowless for each call on 127.0.0.1 and an ephemeral port, in an empty workspace with "
                      "its own state root and an environment with no credential but the key; its ready line and token "
                      "file read; Shutdown asked, then killed 5 s later if it stays")),
        Area("SdkAgentService", "agents created, resumed, listed, archived and deleted; Send and the run's stream; "
                                "runs observed, waited for, cancelled; artifacts; usage", BRIDGE_DOCS + "services.md",
             covered="through the SDK's Agent.prompt: an agent created and sent one prompt for each answer"),
        Area("SdkCursorService", "the key's identity (Me), the model catalog (ListModels), the repositories",
             BRIDGE_DOCS + "services.md", covered="through the SDK's Cursor.me and Cursor.models.list, for Connect"),
        Area(CONTROL, "the bridge itself: Ping, GetVersion (its capabilities), Shutdown, SetToolCallback",
             BRIDGE_DOCS + "services.md", covered="Shutdown, asked by the plugin itself after each call"),
        Area("Local agent store", "a local agent's durable state (SQLite by default)", BRIDGE_DOCS + "services.md",
             covered="kept in the plugin's own state root, beside its empty workspace"),
        Area("Callback services", "an adapter's custom-tool and store servers the bridge calls back",
             BRIDGE_DOCS + "services.md"),
        Area("Streaming", "a run's stream messages and their offsets", BRIDGE_DOCS + "streaming.md"),
        Area("Errors", "the Connect errors the bridge answers with", BRIDGE_DOCS + "errors.md"),
        Area("Versioning", "the sdk.v1 contract and the bridge's releases", BRIDGE_DOCS + "versioning.md",
             covered="the ready line's schema, transport and protocol checked: another handshake is refused"),
    ),
    calls=(
        Call(f"{BRIDGE} --host 127.0.0.1 --port 0 --workspace <folder> --state-root <folder>", "start the bridge",
             HANDSHAKE, used="the bridge for one call, windowless (CREATE_NO_WINDOW)", docs=BRIDGE_DOCS + "protocol.md"),
        Call("cursor-sdk-bridge ready {json} (stderr)", "the ready line: the address, the version, the token file",
             HANDSHAKE, used="the handshake read, the line itself never logged", docs=BRIDGE_DOCS + "protocol.md"),
        Call("POST " + SHUTDOWN_PATH, "shut the bridge down", CONTROL,
             used="the bridge stopped after each call", docs=BRIDGE_DOCS + "protocol.md"),
        Call("SdkAgentService.CreateAgent", "create an agent", "SdkAgentService",
             used="through the SDK's Agent.prompt", docs=BRIDGE_DOCS + "services.md"),
        Call("SdkAgentService.Send", "send a message and stream the run", "SdkAgentService",
             used="through the SDK's Agent.prompt", docs=BRIDGE_DOCS + "services.md", costs=True),
        Call("SdkCursorService.Me", "the key's identity", "SdkCursorService", used="through the SDK's Cursor.me",
             docs=BRIDGE_DOCS + "services.md"),
        Call("SdkCursorService.ListModels", "the model catalog", "SdkCursorService",
             used="through the SDK's Cursor.models.list", docs=BRIDGE_DOCS + "services.md"),
        Call("SdkCursorService.ListRepositories", "the repositories for cloud agents", "SdkCursorService",
             docs=BRIDGE_DOCS + "services.md"),
        Call("SdkBridgeControlService.Ping", "is the bridge there", CONTROL, docs=BRIDGE_DOCS + "services.md"),
        Call("SdkBridgeControlService.GetVersion", "the bridge's version and capabilities", CONTROL,
             docs=BRIDGE_DOCS + "services.md"),
        Call("SdkAgentService.GetUsage", "a cloud agent's billed usage and cost", "SdkAgentService",
             docs=BRIDGE_DOCS + "services.md"),
        Call("SdkAgentService.CancelRun", "cancel a run", "SdkAgentService", docs=BRIDGE_DOCS + "services.md"),
    ),
    verified=VERIFIED,
)

APIS = (CURSOR_SDK, CURSOR_BRIDGE)
