"""The Cursor SDK (cursor-sdk) driven for one assistant's calls, its bridge started and stopped here.

Cursor offers no model-inference API: its Cloud Agents API and its SDKs "are not a standalone
model-inference or chat-completions API" (cursor.com/docs/api); they run Cursor's agent. The Python
SDK, which that page opens to "All users", runs the agent locally or in Cursor's cloud; this plugin
runs it locally and as locked down as the SDK allows: no tool at all (`tools=[]`: "the model can
only respond with text"), no settings layer of this machine's (`setting_sources=[]`: no .cursor
rules, MCP servers, hooks, skills or plugins, the user's or a project's), an empty working folder of
the plugin's own with the agents' state beside it, and the models asked at standard speed. The
inference is Cursor's ("All inference goes through Cursor's hosted models in both modes"); what runs
here is the SDK's bridge, cursor-sdk-bridge, a local server the SDK's wheel carries ("Python already
talks to a bundled copy of the bridge").

The bridge is started by this module rather than by the SDK's launch_bridge, so that it runs
windowless (CREATE_NO_WINDOW: no console pops up from a process that has none) with an environment of
its own: this machine's without any credential, and CURSOR_API_KEY the login's key (the bridge reads
it there; nothing else does). Its handshake is cursor/sdk-bridge's docs/protocol.md: one line on
stderr, `cursor-sdk-bridge ready {json}` (schemaVersion 1, transport tcp, protocol connect, a loopback
url, authTokenFile), the bearer token read from that file (or an older bridge's inline authToken),
the line itself never logged; the SDK attaches with CursorClient.connect(url, auth_token=...). It
runs only while a call needs it (`SdkRuntime.open`): started, asked, stopped by its Shutdown RPC and
killed if it is still there 5 s later, whatever happened.

What the assistant gets back is plain data (`Connection.me`, `models`, `ask`), so it knows nothing of
the SDK's types; a refusal is a CursorError carrying the SDK error's status, code and request id, its
kind from the SDK's error class (authentication, permission, rate_limit, configuration ...) or its
words (quota), or this module's own kinds: setup (no SDK, no bridge, no handshake) and timeout.
"""
from __future__ import annotations

import importlib
import json
import os
import queue
import re
import shutil
import subprocess
import sysconfig
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit

SDK_PACKAGE = "cursor-sdk"
SDK_MODULE = "cursor_sdk"
SDK_WRITTEN_FOR = "1.0.40"  # the SDK release this plugin was written against (its 1.x API; the sdk extra allows <2)
BRIDGE = "cursor-sdk-bridge"  # the bridge's executable (.exe on Windows), installed beside the SDK by its wheel
READY = "cursor-sdk-bridge ready "  # the discovery line's prefix (protocol.md), its trailing space part of it
INSTALL = ('install the SDK into the app\'s environment with pip install "plugin-platform-cursor[sdk]" (its wheel '
           "carries the bridge, cursor-sdk-bridge; on Windows for x64 only)")
CREATE_NO_WINDOW = 0x08000000  # no console window for a console child of a process without one
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
START_SECONDS = 30.0  # the bridge's handshake (the reference adapters' startup timeout)
CALL_SECONDS = 60.0  # an account read: the key, the models
ANSWER_SECONDS = 180.0  # an answer
STOP_SECONDS = 5.0  # a bridge still running this long after its Shutdown is killed (the reference adapters')
SHUTDOWN_PATH = "/sdk.v1.SdkBridgeControlService/Shutdown"  # Connect: POST <url>/sdk.v1.<Service>/<Method>
STANDARD = "false"  # the `fast` parameter asked for: standard speed (Fast costs more and draws the pool faster)
AGENT_NAME = "Liminal evaluation"  # the name each answer's agent is given (AgentOptions.name)

# What the bridge's environment leaves out: the variables it or Cursor's tools would read a key or a setting from
# on their own (CURSOR_*, the bridge's CURSOR_SDK_*), and any other program's credential here (the other plugins'
# keys and accounts). CURSOR_API_KEY is then set to the login's key alone.
OWN_PREFIXES = ("CURSOR_",)
CREDENTIAL = re.compile(r"(^|_)(API_KEY|KEY|KEY_ID|KEYS|TOKEN|TOKENS|SECRET|SECRET_KEY|PASSWORD|PASSWD|ACCOUNT|"
                        r"CREDENTIAL|CREDENTIALS|PAT)$")

# The SDK's error classes (cursor.com/docs/sdk/python, Errors), each a kind of refusal here.
KINDS = {"AuthenticationError": "authentication", "PermissionDeniedError": "permission", "RateLimitError": "rate_limit",
         "ConfigurationError": "configuration", "BadRequestError": "bad_request", "NotFoundError": "not_found",
         "AgentNotFoundError": "not_found", "APITimeoutError": "timeout", "NetworkError": "network",
         "InternalServerError": "server", "AgentBusyError": "busy", "IntegrationNotConnectedError": "integration",
         "UnsupportedRunOperationError": "unsupported"}
# A RateLimitError is "Too many requests or usage limits exceeded": these words tell the usage limit (final: the
# pool or the credit is spent) from a rate limit (wait and try again)
QUOTA_WORDS = ("usage_limit", "usage limit", "quota", "insufficient_credit", "out of credit", "no credit", "credits",
               "spend limit", "spending limit", "spending cap", "additional usage limit")
# Words a refusal without an SDK error class is read by: (status, kind, the words), the first that matches
WORDS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (401, "authentication", ("401", "unauthorized", "unauthenticated", "invalid api key", "not logged in",
                             "authentication failed")),
    (402, "quota", QUOTA_WORDS),
    (403, "permission", ("403", "forbidden", "permission denied", "feature_unavailable", "not available on your plan")),
    (429, "rate_limit", ("429", "rate limit", "rate-limit", "too many requests", "resource_exhausted")),
    (404, "not_found", ("404", "unknown model", "model not found", "no such model", "invalid model", "not_found")),
)


class CursorError(Exception):
    """What the SDK or its bridge refused or could not do, in its own terms: the HTTP status (0: none given), the
    kind (authentication, permission, quota, rate_limit, configuration ...; setup and timeout, this module's own),
    the SDK's code, its request id, when to try again (seconds) and its message (not yet scrubbed)."""

    def __init__(self, message: str, status: int = 0, kind: str = "", code: str = "", request_id: str = "",
                 retry_after: float | None = None):
        super().__init__(str(message))
        self.message = str(message)
        self.status = _int(status) or 0
        self.kind = str(kind or "")
        self.code = str(code or "")
        self.request_id = str(request_id or "")
        self.retry_after = retry_after


@dataclass(frozen=True)
class Ask:
    """One prompt as the SDK takes it: the model, the system line and the user's text (sent as one message: the SDK
    takes no system prompt of the caller's), the `fast` parameter's value to send (None: no parameter), and how long
    the answer may take."""
    model: str
    system: str
    prompt: str
    fast: str | None = STANDARD
    timeout: float = ANSWER_SECONDS


# -- what the bridge and the SDK are given ------------------------------------------------------------

def child_env(environ: Mapping[str, str], key: str) -> dict[str, str]:
    """The bridge's environment: this process's, without CURSOR_* (the bridge's own settings and a key of the
    environment's) and without any other program's credential (a name ending in _KEY, _TOKEN, _SECRET, _PASSWORD,
    _ACCOUNT ...); then CURSOR_API_KEY, the login's key, and the client's language (protocol.md's attribution)."""
    out: dict[str, str] = {}
    for k, v in environ.items():
        up = str(k).upper()
        if up.startswith(OWN_PREFIXES) or CREDENTIAL.search(up):
            continue
        out[str(k)] = str(v)
    out["CURSOR_API_KEY"] = key
    out["CURSOR_SDK_CLIENT_LANGUAGE"] = "python"
    return out


def bridge_command(bridge: str, workspace: Path, state: Path) -> list[str]:
    """The bridge's command line (protocol.md's flags): this machine's loopback, an ephemeral port, the plugin's
    empty workspace and the agents' state root beside it (not the default under ~/.cursor)."""
    return [bridge, "--host", "127.0.0.1", "--port", "0", "--workspace", str(workspace), "--state-root", str(state)]


def windowless() -> dict:
    """Popen's options for a child without a window: CREATE_NO_WINDOW on Windows, nothing elsewhere."""
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_bridge(environ: Mapping[str, str] | None = None) -> str | None:
    """The bridge's executable, found by shutil.which alone: in this interpreter's scripts folder first (where pip
    puts it beside the SDK: the app's venv, on PATH or not), then on PATH. None when it is in neither."""
    env = os.environ if environ is None else environ
    path = env.get("PATH") or env.get("Path") or os.defpath
    folders = [sysconfig.get_path("scripts") or "", path]
    return shutil.which(BRIDGE, path=os.pathsep.join(f for f in folders if f))


def message_of(ask: Ask) -> str:
    """The one message an answer is asked: the argument's system line, then the user's text."""
    return f"{ask.system}\n\n{ask.prompt}" if ask.system else ask.prompt


def agent_options(sdk: Any, ask: Ask, key: str, workspace: Path) -> Any:
    """The SDK's AgentOptions for one answer: the model (at standard speed where `fast` is given), the key given
    explicitly (never the environment's), no tool at all, no settings layer of this machine's, the plugin's empty
    workspace."""
    model = (sdk.ModelSelection(id=ask.model, params=[sdk.ModelParameterValue(id="fast", value=ask.fast)])
             if ask.fast is not None else ask.model)
    local = sdk.LocalAgentOptions(cwd=str(workspace), setting_sources=[])
    return sdk.AgentOptions(model=model, api_key=key, name=AGENT_NAME, tools=[], local=local)


# -- the bridge's handshake -----------------------------------------------------------------------------

def ready_of(line: str) -> dict | None:
    """The bridge's discovery line read (protocol.md): {url, version, token, token_file}; None for any other line
    (an ordinary diagnostic). A CursorError (setup) for a discovery line this plugin cannot use: not JSON, another
    schema, transport or protocol, or an address off this machine's loopback."""
    if not line.startswith(READY):
        return None
    try:
        info = json.loads(line[len(READY):])
    except ValueError:
        info = None
    if not isinstance(info, Mapping):
        raise CursorError("the Cursor SDK's bridge gave a ready line that could not be read", kind="setup")
    if info.get("schemaVersion") != 1 or info.get("transport") != "tcp" or info.get("protocol") != "connect":
        raise CursorError(f"the Cursor SDK's bridge speaks another handshake (schema {info.get('schemaVersion')!r}, "
                          f"{info.get('transport')!r}, {info.get('protocol')!r}) than this plugin was written for: "
                          "update the plugin", kind="setup")
    url = str(info.get("url") or "")
    host, port = str(info.get("host") or ""), _int(info.get("port"))
    if not url and host and port:
        url = f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"
    try:
        where = urlsplit(url).hostname or ""
    except ValueError:
        where = ""
    if where not in LOOPBACK:
        raise CursorError("the Cursor SDK's bridge is not on this machine's loopback address: not used", kind="setup")
    return {"url": url.rstrip("/"), "version": str(info.get("serverVersion") or ""),
            "token": str(info.get("authToken") or ""), "token_file": str(info.get("authTokenFile") or "")}


def token_of(ready: Mapping[str, Any]) -> str:
    """The bridge's bearer token: an older bridge's inline one, else its token file's, trimmed."""
    token = str(ready.get("token") or "").strip()
    if not token and ready.get("token_file"):
        try:
            token = Path(str(ready["token_file"])).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise CursorError(f"the Cursor SDK's bridge token could not be read ({type(e).__name__})", kind="setup") from None
    if not token:
        raise CursorError("the Cursor SDK's bridge gave no token", kind="setup")
    return token


class Stderr:
    """The bridge's stderr, read on a thread of its own so its pipe never fills: each line queued (at most 200
    waiting: the ready line comes first, nothing after it is wanted), the last few kept for a refusal (never the
    ready line: it holds paths, and an older bridge's token); nothing is logged."""

    def __init__(self, stream):
        self.lines: queue.Queue = queue.Queue(maxsize=200)
        self.tail: deque = deque(maxlen=12)
        self.thread = threading.Thread(target=self._read, args=(stream,), name="cursor-sdk-bridge-stderr", daemon=True)
        self.thread.start()

    def _read(self, stream) -> None:
        try:
            for raw in iter(stream.readline, b""):
                line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).rstrip("\r\n")
                if not line:
                    continue
                if not line.startswith(READY):
                    self.tail.append(line)
                try:
                    self.lines.put_nowait(line)
                except queue.Full:
                    pass
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.lines.put_nowait(None)  # the end of its stderr: the bridge has stopped
            except queue.Full:
                pass
            try:
                stream.close()  # closed here, by the thread reading it (never from another: that could block)
            except (OSError, ValueError):
                pass

    def said(self) -> str:
        return "; ".join(x.strip() for x in self.tail if x.strip())[-400:]


def wait_ready(proc, err: Stderr, seconds: float = START_SECONDS, clock: Callable[[], float] = time.monotonic) -> dict:
    """The bridge's discovery line, once it has printed it: a CursorError (setup) when it stops first (what it said
    on stderr given) or says nothing of the kind in `seconds`."""
    deadline = clock() + seconds
    while True:
        left = deadline - clock()
        if left <= 0:
            raise CursorError(f"the Cursor SDK's bridge was not ready in {seconds:g} s", kind="setup")
        try:
            line = err.lines.get(timeout=min(left, 0.25))
        except queue.Empty:
            if proc.poll() is not None and not err.thread.is_alive() and err.lines.empty():
                line = None
            else:
                continue
        if line is None:
            said = err.said()
            raise CursorError("the Cursor SDK's bridge stopped before it was ready" + (f": {said}" if said else ""),
                              kind="setup")
        found = ready_of(line)
        if found is not None:
            return found


def post_shutdown(url: str, token: str) -> None:
    """SdkBridgeControlService.Shutdown, nothing in flight waited for: one Connect JSON POST to the bridge's loopback
    address, never through a proxy of the environment's."""
    import requests

    with requests.Session() as session:
        session.trust_env = False
        session.post(url + SHUTDOWN_PATH, json={"graceSeconds": 0}, headers={"Authorization": f"Bearer {token}"},
                     timeout=3.0)


def stop_bridge(proc, ready: Mapping[str, Any] | None, token: str, post: Callable[[str, str], None] = post_shutdown,
                seconds: float = STOP_SECONDS) -> None:
    """The bridge stopped (protocol.md's order): its Shutdown asked (or, before its handshake, the process told to
    end), then killed if it is still there `seconds` later. Its stderr is left to the thread reading it, which closes
    it at its end."""
    if proc.poll() is None:
        asked = False
        if ready and token:
            try:
                post(str(ready["url"]), token)
                asked = True
            except Exception:  # noqa: BLE001 - a bridge that will not take its Shutdown is ended all the same
                pass
        if not asked:
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(seconds)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(seconds)
            except (OSError, subprocess.TimeoutExpired):
                pass


# -- what the SDK gives back, as plain data ---------------------------------------------------------------

def _get(obj: Any, *names: str) -> Any:
    """The first of these attributes (or keys) the object has set; None when none is."""
    if obj is None:
        return None
    for n in names:
        v = obj.get(n) if isinstance(obj, Mapping) else getattr(obj, n, None)
        if v is not None:
            return v
    return None


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip())) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _seconds(value: Any) -> float | None:
    """A retry_after (an HTTP-style string: seconds, or a date) as seconds; None for a date or nothing."""
    try:
        return float(str(value).strip()) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def model_id(selection: Any) -> str:
    """A run's model (a ModelSelection, or its id) as its id."""
    if selection is None or isinstance(selection, str):
        return selection or ""
    return str(_get(selection, "id") or "")


def model_row(m: Any) -> dict:
    """A model the key's catalog lists (Cursor.models.list): its id and name, its aliases, its parameters (each
    with the values it takes: `fast` takes "false" and "true")."""
    params = []
    for p in _get(m, "parameters") or ():
        values = [str(v).lower() if isinstance(v, bool) else str(v) if isinstance(v, (str, int, float))
                  else str(_get(v, "value", "id") or "") for v in (_get(p, "values") or ())]
        params.append({"id": str(_get(p, "id") or ""), "values": values})
    return {"id": str(_get(m, "id") or ""), "name": str(_get(m, "display_name", "displayName", "name") or _get(m, "id") or ""),
            "aliases": [str(a) for a in (_get(m, "aliases") or ())], "parameters": params}


def usage_of(u: Any) -> dict | None:
    """A run's tokens (TokenUsage): input (the cache reads and writes among it), output (the reasoning among it)."""
    if u is None:
        return None
    return {"input": _int(_get(u, "input_tokens", "inputTokens")) or 0,
            "output": _int(_get(u, "output_tokens", "outputTokens")) or 0,
            "cache_read": _int(_get(u, "cache_read_tokens", "cacheReadTokens")) or 0,
            "cache_write": _int(_get(u, "cache_write_tokens", "cacheWriteTokens")) or 0,
            "reasoning": _int(_get(u, "reasoning_tokens", "reasoningTokens")) or 0,
            "total": _int(_get(u, "total_tokens", "totalTokens")) or 0}


def classify(message: str) -> tuple[int, str]:
    """A refusal's status and kind read from its words, where no SDK error class says it."""
    low = message.lower()
    for status, kind, words in WORDS:
        if any(w in low for w in words):
            return status, kind
    return 0, ""


def answer_of(result: Any, ask: Ask) -> dict:
    """A run's result (RunResult) as the assistant reads it: its text, its id, the model that answered, how long it
    took, its tokens. A run that did not finish is a CursorError (its error code and message, where it gives them)."""
    status = str(_get(result, "status") or "")
    if status and status != "finished":
        code = str(_get(result, "error_code", "errorCode") or "")
        message = str(_get(result, "error_message", "errorMessage") or f"the run ended: {status}")
        number, kind = classify(f"{code} {message}")
        raise CursorError(message, number, kind, code)
    return {"text": str(_get(result, "result") or ""), "id": str(_get(result, "id", "run_id", "runId") or ""),
            "model": model_id(_get(result, "model")) or ask.model, "asked": ask.model,
            "duration_ms": _int(_get(result, "duration_ms", "durationMs")) or 0, "usage": usage_of(_get(result, "usage"))}


def failure(exc: BaseException) -> CursorError:
    """The CursorError an SDK exception is: its kind by its class (or its base classes), told apart from a usage
    limit by its words, its status, code, request id and retry_after as it gives them; else its words read."""
    if isinstance(exc, CursorError):
        return exc
    if isinstance(exc, ImportError):
        return CursorError(f"the Cursor SDK could not be loaded ({exc}): {INSTALL}", kind="setup")
    kind = next((KINDS[c.__name__] for c in type(exc).__mro__ if c.__name__ in KINDS), "")
    message = str(getattr(exc, "message", "") or exc or type(exc).__name__)
    code = str(getattr(exc, "code", "") or "")
    status = _int(getattr(exc, "status_code", None)) or _int(getattr(exc, "status", None)) or 0
    if not kind:
        if isinstance(exc, TimeoutError):
            kind = "timeout"
        elif isinstance(exc, ConnectionError):
            kind = "network"
        elif isinstance(exc, OSError):
            return CursorError(f"the Cursor SDK's bridge failed: {type(exc).__name__}: {exc}", kind="setup")
    words = f"{code} {message}".lower()
    if kind in ("rate_limit", "permission", "") and any(w in words for w in QUOTA_WORDS):
        kind = "quota"
    if not kind:
        number, kind = classify(words)
        status = status or number
    return CursorError(message, status, kind, code, str(getattr(exc, "request_id", "") or ""),
                       _seconds(getattr(exc, "retry_after", None)))


# -- the runtime ------------------------------------------------------------------------------------------

class SdkRuntime:
    """The Cursor SDK for one key: nothing imported, started or written until `open` is entered; inside it the
    bridge runs (started windowless here, attached to by the SDK) and every call is a plain one on a thread of its
    own, timed; on the way out the bridge is stopped, whatever happened. `sdk` stands in for the cursor_sdk module,
    `spawn` for subprocess.Popen and `post` for the Shutdown request (the tests'); `bridge` is the bridge's path
    when it is known (else found by shutil.which)."""

    def __init__(self, key: str, home: Path | str | None = None, *, sdk: Any = None, environ: Mapping[str, str] | None = None,
                 module: str = SDK_MODULE, bridge: str | None = None, spawn: Callable | None = None,
                 post: Callable[[str, str], None] | None = None):
        self._key = key or ""
        self._home = Path(home) if home is not None else None
        self._sdk, self._environ, self._module, self._bridge = sdk, environ, module, bridge
        self._spawn = spawn or subprocess.Popen
        self._post = post or post_shutdown

    def __repr__(self) -> str:
        return f"<SdkRuntime {self._module}>"  # never the key

    @property
    def home(self) -> Path:
        """The plugin's own folder in the data folder: the bridge's workspace (empty) and its agents' state."""
        if self._home is None:
            from liminal_libs import layout

            self._home = layout.data_dir() / "assistants" / "cursor"
        return self._home

    @home.setter
    def home(self, value: Path | str) -> None:
        self._home = Path(value)

    def module(self) -> Any:
        """The SDK's module (cursor_sdk), imported when first asked; CursorError (setup) when it is not installed."""
        if self._sdk is None:
            try:
                self._sdk = importlib.import_module(self._module)
            except ImportError:
                raise CursorError(f"the Cursor SDK is not installed here: {INSTALL}", kind="setup") from None
        return self._sdk

    def bridge(self) -> str:
        """The bridge's executable; CursorError (setup) when it is neither beside this Python nor on PATH."""
        found = self._bridge or find_bridge(self._environ)
        if not found:
            raise CursorError(f"the Cursor SDK's bridge ({BRIDGE}) is not beside this Python nor on PATH: {INSTALL}",
                              kind="setup")
        return found

    @contextmanager
    def open(self) -> Iterator["Connection"]:
        """The bridge started for the calls inside (one child process, windowless), the SDK attached to it, the
        bridge stopped after them."""
        sdk = self.module()
        bridge = self.bridge()
        workspace, state = self.home / "workspace", self.home / "state"
        workspace.mkdir(parents=True, exist_ok=True)
        state.mkdir(parents=True, exist_ok=True)
        environ = os.environ if self._environ is None else self._environ
        try:
            proc = self._spawn(bridge_command(bridge, workspace, state), env=child_env(environ, self._key),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **windowless())
        except OSError as e:
            raise CursorError(f"the Cursor SDK's bridge could not start: {type(e).__name__}: {e} ({INSTALL})",
                              kind="setup") from None
        ready, token = None, ""
        try:
            err = Stderr(proc.stderr)
            ready = wait_ready(proc, err)
            token = token_of(ready)
            try:
                client = sdk.CursorClient.connect(ready["url"], auth_token=token)
            except Exception as e:  # noqa: BLE001 - the SDK's exception is the refusal: read into a CursorError
                raise failure(e) from None
            conn = Connection(sdk, client, self._key, workspace, str(getattr(sdk, "__version__", "") or ""),
                              ready["version"])
            try:
                yield conn
            finally:
                conn.close()
        finally:
            stop_bridge(proc, ready, token, self._post)


class Connection:
    """The SDK attached to a running bridge while `SdkRuntime.open` holds it: its calls, each a plain one on a
    thread of its own (a call that outlasts its time is a CursorError, timeout: the bridge's stop ends it), each
    returning plain data."""

    def __init__(self, sdk: Any, client: Any, key: str, workspace: Path, version: str = "", bridge: str = ""):
        self._sdk, self._client, self._key, self._workspace = sdk, client, key, Path(workspace)
        self.version, self.bridge = version, bridge

    def __repr__(self) -> str:
        return "<Connection cursor-sdk>"  # never the key

    def _call(self, make: Callable[[], Any], seconds: float) -> Any:
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = make()
            except BaseException as e:  # noqa: BLE001 - carried to the caller's thread
                box["error"] = e

        thread = threading.Thread(target=run, name="cursor-sdk-call", daemon=True)
        thread.start()
        thread.join(seconds)
        if thread.is_alive():
            raise CursorError(f"no answer from the Cursor SDK in {seconds:g} s", kind="timeout")
        if "error" in box:
            raise failure(box["error"]) from None
        return box.get("value")

    def close(self) -> None:
        """The SDK's client closed (the bridge is the runtime's to stop)."""
        client, self._client = self._client, None
        close = getattr(client, "close", None)
        try:
            if callable(close):
                close()
            elif callable(getattr(client, "__exit__", None)):
                client.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - the bridge is stopped next in any case
            pass

    def me(self) -> dict:
        """Whose key it is (Cursor.me: an SDKUser): {name, email, user_id, created}; the email and user id empty for
        a service account's key."""
        user = self._call(lambda: self._sdk.Cursor.me(api_key=self._key, client=self._client), CALL_SECONDS)
        return {"name": str(_get(user, "api_key_name", "apiKeyName") or ""),
                "email": str(_get(user, "user_email", "userEmail") or ""),
                "user_id": str(_get(user, "user_id", "userId") or ""),
                "created": str(_get(user, "created_at", "createdAt") or "")}

    def models(self) -> list[dict]:
        """The models the key's catalog lists (model_row each): it is the account's and its team's."""
        listed = self._call(lambda: self._sdk.Cursor.models.list(api_key=self._key, client=self._client), CALL_SECONDS)
        items = _get(listed, "items")
        return [model_row(m) for m in ((items if items is not None else listed) or ())]

    def ask(self, ask: Ask) -> dict:
        """One answer from an agent of its own (Agent.prompt: created, asked once, disposed of), answer_of."""
        options = agent_options(self._sdk, ask, self._key, self._workspace)
        result = self._call(lambda: self._sdk.Agent.prompt(message_of(ask), options, client=self._client), ask.timeout)
        return answer_of(result, ask)
