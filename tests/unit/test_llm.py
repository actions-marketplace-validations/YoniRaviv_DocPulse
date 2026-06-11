from unittest.mock import patch

import pytest

from docpulse.llm import LLMClient, LLMError


def _response(content=None, tool_calls=None, total_tokens=10):
    class Msg:
        pass

    msg = Msg()
    msg.content = content
    msg.tool_calls = tool_calls

    class Choice:
        pass

    choice = Choice()
    choice.message = msg

    class Usage:
        pass

    usage = Usage()
    usage.total_tokens = total_tokens

    class Resp:
        pass

    resp = Resp()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def test_requires_a_model():
    with pytest.raises(ValueError):
        LLMClient(model=None)
    with pytest.raises(ValueError):
        LLMClient(model="")


def test_complete_returns_message_and_counts_tokens():
    client = LLMClient(model="anthropic/claude-haiku-4-5")
    with patch("docpulse.llm.litellm.completion") as mock:
        mock.side_effect = [_response(content="hi", total_tokens=12),
                            _response(content="bye", total_tokens=8)]
        first = client.complete([{"role": "user", "content": "x"}])
        second = client.complete([{"role": "user", "content": "y"}])
    assert first.content == "hi"
    assert second.content == "bye"
    assert client.tokens_used == 20  # 12 + 8 accumulated


def test_passes_tools_through():
    client = LLMClient(model="m")
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    with patch("docpulse.llm.litellm.completion") as mock:
        mock.return_value = _response(content="ok")
        client.complete([{"role": "user", "content": "x"}], tools=tools)
    _, kwargs = mock.call_args
    assert kwargs["tools"] == tools
    assert kwargs["model"] == "m"


def test_provider_error_is_wrapped():
    client = LLMClient(model="m")
    with patch("docpulse.llm.litellm.completion") as mock:
        mock.side_effect = RuntimeError("503 from provider")
        with pytest.raises(LLMError):
            client.complete([{"role": "user", "content": "x"}])


def test_missing_usage_does_not_crash():
    client = LLMClient(model="m")
    resp = _response(content="ok")
    del resp.usage  # provider omitted usage
    with patch("docpulse.llm.litellm.completion") as mock:
        mock.return_value = resp
        client.complete([{"role": "user", "content": "x"}])
    assert client.tokens_used == 0
