import json

from docpulse.models import Repair
from docpulse.repair.prompts import build_validation_user_message
from docpulse.repair.repairer import RepairBundle
from docpulse.repair.validator import preservation_ratio, validate


def test_identical_text_is_fully_preserved():
    text = "Para one.\n\nPara two.\n\nPara three."
    assert preservation_ratio(text, text) == 1.0


def test_one_changed_block_of_three():
    original = "Keep A.\n\nChange B.\n\nKeep C."
    new = "Keep A.\n\nChanged B entirely.\n\nKeep C."
    assert preservation_ratio(original, new) == 2 / 3


def test_empty_original_is_fully_preserved():
    assert preservation_ratio("", "anything") == 1.0


def test_whitespace_only_separators_split_blocks():
    # A blank line containing spaces/tabs still separates paragraphs.
    original = "Block one.\n \t\nBlock two."
    new = "Block one.\n\nBlock two REWRITTEN."
    assert preservation_ratio(original, new) == 0.5


def test_byte_identical_required_trailing_space_differs():
    # A trailing space makes the block non-identical -> not preserved.
    original = "exact line"
    new = "exact line "
    assert preservation_ratio(original, new) == 0.0


def test_duplicate_blocks_counted_with_multiplicity():
    original = "dup\n\ndup\n\nunique"
    new = "dup\n\nunique"  # only one 'dup' survives
    assert preservation_ratio(original, new) == 2 / 3


class FakeToolCall:
    def __init__(self, name, args, call_id="v1"):
        self.id = call_id
        self.type = "function"

        class Fn:
            pass

        self.function = Fn()
        self.function.name = name
        self.function.arguments = (
            args if isinstance(args, str) else json.dumps(args)
        )


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeClient:
    def __init__(self, messages):
        self._messages = list(messages)
        self.calls = 0

    def complete(self, messages, tools=None):
        self.calls += 1
        return self._messages.pop(0)


def _bundle():
    return RepairBundle(
        section_id="s", doc_content="Keep A.\n\nOld B.", diagnosis="B wrong",
        evidence=[], old_code="o", new_code="n", intent="",
    )


def _repair(new_content):
    return Repair(
        section_id="s", new_content=new_content, confidence=0.9,
        validation_passed=False, rationale="r",
    )


def _validation(accurate, style, notes="ok"):
    return FakeMessage(tool_calls=[FakeToolCall("submit_validation", {
        "accurate_vs_code": accurate, "style_consistent": style, "notes": notes,
    })])


def test_validate_passes_when_accurate_style_and_preserved():
    rep = _repair("Keep A.\n\nNew B.")  # preserves 1/2 blocks (>= default 0.5)
    out = validate(FakeClient([_validation(True, True)]), rep, _bundle())
    assert out.validation_passed is True
    assert out.section_id == "s"          # returns an updated Repair
    assert out.new_content == rep.new_content


def test_validate_fails_when_llm_says_inaccurate():
    rep = _repair("Keep A.\n\nNew B.")
    out = validate(FakeClient([_validation(False, True)]), rep, _bundle())
    assert out.validation_passed is False


def test_validate_fails_when_style_inconsistent():
    rep = _repair("Keep A.\n\nNew B.")
    out = validate(FakeClient([_validation(True, False)]), rep, _bundle())
    assert out.validation_passed is False


def test_validate_fails_when_preservation_below_min():
    # Rewrites both blocks -> preservation 0.0 < min_preservation 0.5.
    rep = _repair("All\n\nNew.")
    out = validate(FakeClient([_validation(True, True)]), rep, _bundle())
    assert out.validation_passed is False


def test_validate_llm_error_fails_safe():
    from docpulse.llm import LLMError

    class BoomClient:
        def complete(self, messages, tools=None):
            raise LLMError("boom")

    out = validate(BoomClient(), _repair("Keep A.\n\nNew B."), _bundle())
    assert out.validation_passed is False


def test_validate_malformed_response_fails_safe():
    bad = FakeMessage(tool_calls=[FakeToolCall("submit_validation", "{bad json")])
    out = validate(FakeClient([bad]), _repair("Keep A.\n\nNew B."), _bundle())
    assert out.validation_passed is False


def test_validation_message_includes_original_rewrite_and_new_code():
    msg = build_validation_user_message("ORIG TEXT", "NEW TEXT", "code here")
    body = msg["content"]
    assert msg["role"] == "user"
    assert "ORIG TEXT" in body
    assert "NEW TEXT" in body
    assert "code here" in body
