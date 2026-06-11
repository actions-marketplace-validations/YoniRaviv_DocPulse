import json

from docpulse.models import Index
from docpulse.verification.prompts import SYSTEM_PROMPT, build_user_message
from docpulse.verification.verifier import VerifyBundle, verify


def test_system_prompt_forbids_guessing_stale():
    lowered = SYSTEM_PROMPT.lower()
    assert "unverified" in lowered
    assert "stale" in lowered


def test_user_message_includes_all_bundle_parts():
    bundle = VerifyBundle(
        section_id="docs/auth.md#login",
        doc_content="Call AuthService.login(user).",
        old_code="def login(self, user): ...",
        new_code="def login(self, username): ...",
        intent="Rename user -> username for clarity.",
    )
    msg = build_user_message(bundle)
    assert msg["role"] == "user"
    body = msg["content"]
    assert "docs/auth.md#login" in body
    assert "AuthService.login(user)" in body          # doc content
    assert "def login(self, user)" in body            # old code
    assert "def login(self, username)" in body        # new code
    assert "Rename user -> username" in body           # intent


def test_user_message_handles_empty_intent():
    bundle = VerifyBundle(
        section_id="s", doc_content="d", old_code="o", new_code="n", intent=""
    )
    body = build_user_message(bundle)["content"]
    assert "(no intent provided)" in body


class FakeToolCall:
    def __init__(self, name, args, call_id="c1"):
        self.id = call_id
        self.type = "function"

        class Fn:
            pass

        self.function = Fn()
        self.function.name = name
        self.function.arguments = json.dumps(args)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeClient:
    """Returns scripted messages; records how many times complete() was called."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.calls = 0

    def complete(self, messages, tools=None):
        self.calls += 1
        return self._messages.pop(0)


def _empty_index():
    return Index(version=1, base_commit="x", chunks=[], sections=[], links=[])


def _bundle():
    return VerifyBundle(
        section_id="docs/auth.md#login", doc_content="d",
        old_code="o", new_code="n", intent="",
    )


def test_submit_verdict_first_call_returns_verdict(tmp_path):
    client = FakeClient([
        FakeMessage(tool_calls=[FakeToolCall(
            "submit_verdict",
            {"status": "stale", "confidence": 0.9, "diagnosis": "param renamed",
             "evidence": ["src/auth.py:10"]},
        )]),
    ])
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=5)
    assert verdict.status == "stale"
    assert verdict.section_id == "docs/auth.md#login"  # injected, not trusted from model
    assert verdict.confidence == 0.9
    assert client.calls == 1


def test_read_tool_then_verdict(tmp_path):
    (tmp_path / "auth.py").write_text("def login(self, username): ...\n")
    client = FakeClient([
        FakeMessage(tool_calls=[FakeToolCall("read_file",
                    {"path": "auth.py", "start": 1, "end": 1})]),
        FakeMessage(tool_calls=[FakeToolCall(
            "submit_verdict",
            {"status": "accurate", "confidence": 0.2, "diagnosis": "fine",
             "evidence": []},
        )]),
    ])
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=5)
    assert verdict.status == "accurate"
    assert client.calls == 2


def test_exhausting_budget_yields_unverified(tmp_path):
    # model keeps calling read_file forever, never submits
    forever = [FakeMessage(tool_calls=[FakeToolCall("read_file",
               {"path": "x.py", "start": 1, "end": 1})]) for _ in range(20)]
    client = FakeClient(forever)
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=3)
    assert verdict.status == "unverified"
    assert client.calls == 3  # capped


def test_malformed_verdict_args_never_returns_stale(tmp_path):
    class BadCall(FakeToolCall):
        def __init__(self):
            super().__init__("submit_verdict", {})
            self.function.arguments = "{not valid json"

    client = FakeClient([
        FakeMessage(tool_calls=[BadCall()]),
        FakeMessage(tool_calls=[BadCall()]),  # retry also bad
    ])
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=3)
    assert verdict.status == "unverified"


def test_llm_error_yields_unverified(tmp_path):
    from docpulse.llm import LLMError

    class BoomClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools=None):
            raise LLMError("boom")

    verdict = verify(BoomClient(), tmp_path, _empty_index(), _bundle(), max_tool_calls=3)
    assert verdict.status == "unverified"


def test_plain_text_response_gets_nudged_then_unverified(tmp_path):
    client = FakeClient([
        FakeMessage(content="I think it's fine."),   # no tool call -> nudge
        FakeMessage(content="Still just talking."),  # still none -> nudge again
        FakeMessage(content="Yet more talk."),       # budget gone
    ])
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=3)
    assert verdict.status == "unverified"


def test_multi_call_turn_responds_to_every_tool_call(tmp_path):
    # A turn where submit_verdict (malformed) is NOT last must still produce a
    # role:tool response for every tool_call id, so the retry message list is valid.
    (tmp_path / "x.py").write_text("hello\n")

    class BadVerdict(FakeToolCall):
        def __init__(self):
            super().__init__("submit_verdict", {}, call_id="sv1")
            self.function.arguments = "{bad json"

    captured = {}

    class CapturingClient:
        def __init__(self, scripted):
            self._scripted = list(scripted)
            self.calls = 0

        def complete(self, messages, tools=None):
            self.calls += 1
            if self.calls == 2:
                captured["messages"] = list(messages)
            return self._scripted.pop(0)

    turn1 = FakeMessage(tool_calls=[
        BadVerdict(),
        FakeToolCall("read_file", {"path": "x.py", "start": 1, "end": 1}, call_id="rf1"),
    ])
    turn2 = FakeMessage(tool_calls=[FakeToolCall(
        "submit_verdict",
        {"status": "accurate", "confidence": 0.1, "diagnosis": "ok", "evidence": []},
    )])
    client = CapturingClient([turn1, turn2])
    verdict = verify(client, tmp_path, _empty_index(), _bundle(), max_tool_calls=5)
    assert verdict.status == "accurate"

    msgs = captured["messages"]
    tool_ids = {c.id for m in msgs if getattr(m, "tool_calls", None) for c in m.tool_calls}
    responded = {m["tool_call_id"] for m in msgs
                 if isinstance(m, dict) and m.get("role") == "tool"}
    assert tool_ids == {"sv1", "rf1"}
    assert tool_ids <= responded  # every tool_call got a response -> valid protocol
