"""Gate tests for the LLM contract: JSON parsing and the fake client."""
import pytest

from llm.service import complete_json, parse_json_object, JSONError, LLMError
from llm.fake import ScriptedClient


def test_parse_plain_object():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_strips_code_fence():
    text = '```json\n{"decision": "include"}\n```'
    assert parse_json_object(text) == {"decision": "include"}


def test_parse_extracts_object_amid_prose():
    text = 'Sure, here it is: {"decision": "exclude"} hope that helps'
    assert parse_json_object(text) == {"decision": "exclude"}


def test_parse_rejects_non_object():
    with pytest.raises(JSONError):
        parse_json_object("[1, 2, 3]")


def test_parse_rejects_garbage():
    with pytest.raises(JSONError):
        parse_json_object("not json at all")


def test_complete_json_roundtrip():
    client = ScriptedClient(mapping={"TITLE": '{"decision": "include"}'})
    obj = complete_json(client, "some prompt with TITLE marker")
    assert obj["decision"] == "include"


def test_complete_json_empty_raises():
    client = ScriptedClient(responder=lambda p, s, m: "")
    with pytest.raises(LLMError):
        complete_json(client, "prompt")


def test_scripted_client_records_calls():
    client = ScriptedClient(mapping={"x": "{}"})
    client.complete("xyz")
    client.complete("xyz", system="sys", model="opus")
    assert client.call_count == 2
    assert client.calls[1] == ("xyz", "sys", "opus")
