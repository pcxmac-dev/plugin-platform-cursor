"""Cursor through the Cursor SDK (runtime.py) behind the library's Assistant (liminal_libs.assistants): the
same hooks as the other assistants' (`body`, `parse`, `parse_models`, `error`, `final`, `limits_from`),
filled with the SDK's shapes, and `models`, `answer` and `connect` going through the runtime instead of the
contract's HTTP client, each counted on the plugin's caps (the machine's requests and tokens a day) as the
client counts its own requests.

What an answer is asked (`body`): the model (at standard speed where it has a Fast one), the argument's
system line and the user's text, sent as one message (the SDK takes no system prompt of the caller's), with
nothing about the account (the SDK takes no user field) and no output cap (it takes none: the answer's
tokens are counted after). An answer's usage is the run's (its input with the cache reads and writes among
it, its output with the reasoning among it), its model the one that answered, its cost by that model's
prices in the table (the rates Cursor charges beyond the plan's pool). A refusal is said in words
(`error`), scrubbed of the key and the account.

Connect (`connect`): the bridge started once, the key tried (Cursor.me: its name, and for a user's key the
email, checked against the account named), the models the key's catalog lists compared with the table (the
ones the plan reaches, and whether the model chosen takes standard speed), and unless `light`, one answer of
a few tokens. Cursor sends no limits the plans differ by and no usage left (that is shown in the editor and on
the dashboard), so the plan stays yours.
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from liminal_libs.assistants import Assistant, Parsed, Prompt, Usage
from liminal_libs.errors import BudgetExhausted, NotEntitled, RateLimited, SourceError, Unauthorized
from liminal_libs.sources.plugin import Scanned

from .runtime import ANSWER_SECONDS, SDK_PACKAGE, SDK_WRITTEN_FOR, STANDARD, Ask, CursorError, SdkRuntime

HOST = "https://api.cursor.com"  # Cursor's API host: nothing of this plugin's own is sent there (the bridge talks to Cursor)
KEY_PREFIX = "crsr_"  # "Key format: crsr_..." (cursor.com/docs/api)
PROBE_SECONDS = 90.0
KEY_HELP = ("a user API key (crsr_) from the Cursor dashboard's API Keys page, or a service account's key from your "
            "team's settings (a Team Admin key is not taken by the SDK)")
AUTH_KINDS = ("authentication",)
QUOTA_KINDS = ("quota",)
DENIED_KINDS = ("permission", "integration")
MODEL_KINDS = ("not_found", "configuration", "bad_request")
RATE_KINDS = ("rate_limit", "busy")


class CursorAssistant(Assistant):
    """Cursor: the library's Assistant over the Cursor SDK (see the module's docstring). `session` is the runtime
    when it has `open` (the tests' fake); else the SDK's own (SdkRuntime)."""

    base_url = HOST
    models_path = ""  # the models come from the SDK (Cursor.models.list), not from a path of this plugin's
    answers_path = ""
    request_id_header = "x-request-id"
    limit_prefixes = ()
    probe_tokens = 16

    def __init__(self, plugin, settings, session=None, now=None, sleep=time.sleep):
        runtime = session if callable(getattr(session, "open", None)) else None
        super().__init__(plugin, settings, session=None, now=now, sleep=sleep)
        self.runtime = runtime if runtime is not None else SdkRuntime(settings.key or "")

    # -- the hooks, in the SDK's shapes ------------------------------------------------------------------

    def headers(self, key: str) -> dict:
        """None of this plugin's: the key goes to the SDK (AgentOptions.api_key) and to the bridge's environment,
        never into a header of this plugin's."""
        return {}

    def body(self, prompt: Prompt, model: str, user_id: str) -> dict:
        """What an answer is asked (an Ask's fields): nothing about the account, no output cap; standard speed for a
        model of the table that has a Fast one."""
        return {"model": model, "system": prompt.system, "prompt": prompt.user,
                "fast": STANDARD if model in self.plugin.standard_speed else None}

    def parse(self, raw: Mapping[str, Any]) -> Parsed:
        """An answer (runtime.answer_of): its text, the run's tokens (the cache reads and writes among the input, as
        the SDK counts them; added to an input that leaves them out), the model that answered, the run's id."""
        u = raw.get("usage") or {}
        inp, read, wrote = int(u.get("input") or 0), int(u.get("cache_read") or 0), int(u.get("cache_write") or 0)
        usage = Usage(inp if inp >= read + wrote else inp + read + wrote, int(u.get("output") or 0), read,
                      int(u.get("reasoning") or 0))
        model = str(raw.get("model") or raw.get("asked") or "")
        return Parsed(str(raw.get("text") or ""), usage, "end_turn", str(raw.get("id") or ""), model, None, raw)

    def parse_models(self, raw) -> list[dict]:
        """The catalog's models (runtime.model_row each): [{id, title, parameters ...}]."""
        rows = raw if isinstance(raw, (list, tuple)) else (raw or {}).get("data", []) if isinstance(raw, Mapping) else []
        return [{**m, "id": str(m["id"]), "title": str(m.get("name") or m["id"])}
                for m in rows if isinstance(m, Mapping) and m.get("id")]

    def error(self, status: int, body, message: str) -> SourceError | None:
        """A refusal in words, by its status and the runtime's kind ({kind, code} in `body`); `message` comes
        scrubbed. None: the plain SourceError."""
        info = body if isinstance(body, Mapping) else {}
        kind = str(info.get("kind") or "").lower()
        if kind == "setup":
            return SourceError(0, message)
        if kind == "timeout":
            return SourceError(0, message if message.startswith("no answer") else f"no answer: {message}")
        if status == 401 or kind in AUTH_KINDS:
            return Unauthorized(401, f"the key was refused: {message} (Cursor takes {KEY_HELP})")
        if status == 402 or kind in QUOTA_KINDS:
            return NotEntitled(status or 402, f"no usage left for it: {message} (the plan's pool of Cursor models "
                                              "refreshes weekly, a legacy plan's monthly; prepaid credit or a higher "
                                              "plan goes on, within your monthly additional usage limit)")
        if status == 403 or kind in DENIED_KINDS:
            return NotEntitled(403, f"not allowed: {message} (the plan must include the Cursor SDK and the model; a "
                                    "team's admins may hold models back)")
        if status == 404 or kind in MODEL_KINDS:
            return NotEntitled(status or 404, f"no such model or option: {message} (choose a model from Connect's "
                                              "list)")
        if status == 429 or kind in RATE_KINDS:
            return RateLimited(429, f"rate limited: {message} (Cursor publishes no limits for the SDK: wait a little "
                                    "and try again)", info.get("retry_after"))
        return None

    def final(self, status: int, body) -> bool:
        """A usage limit's 429 is final: the pool or the credit is spent, trying again changes nothing."""
        info = body if isinstance(body, Mapping) else {}
        return status == 429 and str(info.get("kind") or "").lower() in QUOTA_KINDS

    def limits_from(self, headers: Mapping[str, Any]) -> tuple[int | None, int | None]:
        return None, None  # Cursor publishes no rate limits for the SDK, and the SDK passes on no rate-limit headers

    # -- what is refused before anything is sent ---------------------------------------------------------

    def foreign(self) -> str | None:
        """Why the key is not even tried: it is not a Cursor API key (Cursor's begin with crsr_), so it would only
        hand another vendor's secret to Cursor."""
        if not (self.settings.key or "").strip().startswith(KEY_PREFIX):
            return f"{self.name}: not a Cursor API key (Cursor's begin with {KEY_PREFIX}): make {KEY_HELP}"
        return None

    def refusal(self) -> str | None:
        return (self.foreign() if self.settings.has_key else None) or super().refusal()

    def _refuse(self) -> None:
        why = self.foreign() if self.settings.has_key else None
        if why:
            raise Unauthorized(0, why)
        super()._refuse()

    def _key(self) -> None:
        if not self.settings.has_key:
            raise Unauthorized(0, f"{self.name}: no key ({self.plugin.key_names[0]} is not set)")
        why = self.foreign()
        if why:
            raise Unauthorized(0, why)

    def _count(self) -> None:
        """One request counted as it goes, as the contract's client counts its own: the plan's window (none
        published: no wait), the machine's daily cap (BudgetExhausted once reached)."""
        limiter = getattr(self.client, "_limiter", None)
        if limiter is not None:
            limiter.acquire()
        if self.client.take_day is not None and not self.client.take_day():
            raise BudgetExhausted("the daily request cap is reached on this machine (all its databases together)")
        self.client.requests_made += 1

    def refused(self, e: CursorError) -> SourceError:
        """The runtime's refusal as the contract's error, in words, scrubbed of the key and the account, with the
        request id Cursor gave (for its support)."""
        message = self.client.scrub(e.message)
        if e.request_id:
            message += f" (request {e.request_id})"
        body = {"kind": e.kind, "code": e.code, "retry_after": e.retry_after}
        return self.error(e.status, body, message) or SourceError(e.status, message)

    # -- what every assistant does, through the runtime --------------------------------------------------

    def ask_of(self, prompt: Prompt, model: str, timeout: float) -> Ask:
        return Ask(timeout=timeout, **self.body(prompt, model, self.settings.user_id))

    def models(self) -> list[dict]:
        """The models the key's catalog lists (one request)."""
        self._key()
        self._count()
        try:
            with self.runtime.open() as rt:
                return self.parse_models(rt.models())
        except CursorError as e:
            raise self.refused(e) from None

    def answer(self, prompt: Prompt, model: str, timeout: float = ANSWER_SECONDS) -> tuple[Parsed, dict, float]:
        """One answer to a prompt from a model, the bridge started for it and stopped after it: (what it holds, no
        headers, the answer's seconds)."""
        ask = self.ask_of(prompt, model, timeout)
        self._count()
        try:
            with self.runtime.open() as rt:
                started = time.monotonic()
                raw = rt.ask(ask)
                seconds = round(time.monotonic() - started, 3)
        except CursorError as e:
            raise self.refused(e) from None
        parsed = self.parse(raw)
        self.tokens.charge_day(parsed.usage.total, self.now())
        return parsed, {}, seconds

    def connect(self, light: bool = False) -> Scanned:
        """The capability scan (see the module's docstring): one bridge for every step, each step's refusal a row of
        its own."""
        s = self.settings
        if not s.has_key:
            raise Unauthorized(0, f"{self.name}: no key ({self.plugin.key_names[0]} is not set)")
        rows: list[tuple[str, bool, str]] = []
        limits: dict = {"seen": {}, "perMinute": None, "kept": list(self.window())}
        why = self.foreign()
        if why:
            rows.append(("the key", False, f"not sent: {why}"))
            return Scanned(tuple(rows), {}, {}, limits)
        plan = self.plugin.plan_of(s.plan)
        if plan is not None and not plan.api_access:
            rows.append(("its plan", False, f"the {plan.title} plan does not include the Cursor SDK: nothing sent "
                                            "(choose the plan your account is on)"))
            return Scanned(tuple(rows), {}, {}, limits)
        try:
            with self.runtime.open() as rt:
                rows.append(sdk_row(str(getattr(rt, "version", "") or ""), str(getattr(rt, "bridge", "") or "")))
                try:
                    self._count()
                    me = rt.me()
                except CursorError as e:
                    rows.append(("the key", False, f"refused: {self.refused(e).message}"))
                    return Scanned(tuple(rows), {}, {}, limits)
                rows += self.key_rows(me)
                try:
                    self._count()
                    listed = self.parse_models(rt.models())
                except CursorError as e:
                    rows.append(("the models", False, f"not listed: {self.refused(e).message}"))
                    return Scanned(tuple(rows), {}, {}, limits)
                rows += self.model_rows(listed, plan)
                if not light and plan is not None and plan.api_access:
                    rows.append(self.probe(rt))
        except CursorError as e:
            err = self.refused(e)
            rows.append(("the Cursor SDK", False, err.message) if e.kind == "setup" else ("the key", False,
                                                                                         f"refused: {err.message}"))
        return Scanned(tuple(rows), {}, {}, limits)

    def key_rows(self, me: Mapping[str, Any]) -> list[tuple[str, bool, str]]:
        """Connect's rows on the key (its name, a user's or a service account's) and on the account it names."""
        s, var = self.settings, self.plugin.account_var
        email = str(me.get("email") or "")
        kind = "a user's key" if email or me.get("user_id") else "a service account's key"
        out = [("the key", True, f"accepted: {kind}" + (f", named {me['name']}" if me.get("name") else ""))]
        account = (s.account or "").strip()
        if account and email:
            same = account.lower() == email.lower()
            out.append(("the account", same, f"the key is the Cursor account {var} names" if same else
                        f"the key belongs to another Cursor account than {var} names: check the key or the account"))
        return out

    def model_rows(self, listed: list[dict], plan) -> list[tuple[str, bool, str]]:
        """Connect's rows on the models: the model chosen (listed? at standard speed?), the table's models against
        the ones listed (those the plan reaches), the ones not in the table."""
        s = self.settings
        by_id: dict[str, dict] = {}
        for m in listed:
            for name in (m["id"], *m.get("aliases", ())):
                by_id.setdefault(str(name), m)
        ids = {m["id"] for m in listed}
        m = by_id.get(s.model)
        out = [(f"the model {s.model}", m is not None, "listed" if m is not None else
                "not listed by the key's catalog: choose another model (the ones listed are in the scan's rows below)")]
        if m is not None and s.model in self.plugin.standard_speed:
            params = {p.get("id"): [str(v) for v in p.get("values", ())] for p in m.get("parameters", ())}
            if "fast" in params and STANDARD not in params["fast"]:
                out.append(("its speed", False, "the catalog offers it at Fast speed only: the plugin asks for standard "
                                                "speed and would be refused"))
            elif params and "fast" not in params:
                out.append(("its speed", False, "the catalog lists no speed for it: the plugin asks for standard speed "
                                                "(fast=false) and may be refused: update the plugin"))
            elif "fast" in params:
                out.append(("its speed", True, "asked at standard speed (fast=false): Fast costs more and draws the "
                                               "pool faster"))
        reach = set(self.plugin.reach(plan)) if plan is not None else set()
        gone = sorted(r for r in reach if r not in by_id)
        if gone:
            out.append(("the table's models", False, f"not listed by the key's catalog: {', '.join(gone)} (the table is "
                                                     "stale, or your plan or your team leaves them out: update the "
                                                     "plugin, or choose the plan you are on)"))
        new = sorted(ids - {x.id for x in self.plugin.models})
        if new:
            out.append(("models not in the table", True, ", ".join(new[:12]) + (" ..." if len(new) > 12 else "")))
        return out

    def probe(self, rt) -> tuple[str, bool, str]:
        """Connect's one answer of a few tokens, with what it cost by the table's prices."""
        s = self.settings
        probe = Prompt("Reply with the single word OK.", "Are you there?", self.probe_tokens)
        try:
            self._count()
            ask = self.ask_of(probe, s.model, PROBE_SECONDS)
            started = time.monotonic()
            raw = rt.ask(ask)
            seconds = round(time.monotonic() - started, 3)
        except CursorError as e:
            return ("an answer", False, f"refused: {self.refused(e).message}")
        parsed = self.parse(raw)
        self.tokens.charge_day(parsed.usage.total, self.now())
        detail = f"{parsed.model or s.model} answered in {seconds:g} s: {parsed.usage.total} tokens"
        cost = self.plugin.cost(parsed.model or s.model, parsed.usage)
        if cost is not None:
            detail += f" (${cost:.6f} by the table's prices, were it beyond the plan's pool)"
        return ("an answer", True, detail)


def sdk_row(version: str, bridge: str = "") -> tuple[str, bool, str]:
    """Connect's row on the SDK: its release and its bridge's, and whether it is the major release this plugin was
    written for."""
    ok = not version or version.split(".")[0] == SDK_WRITTEN_FOR.split(".")[0]
    said = f"{SDK_PACKAGE} {version or '(its release not said)'}" + (f", its bridge {bridge}" if bridge else "")
    return ("the Cursor SDK", ok, said if ok else f"{said}: this plugin was written for {SDK_WRITTEN_FOR}: update the plugin")
