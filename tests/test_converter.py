import pytest
from providers.utils.message_converter import AnthropicToOpenAIConverter


def test_convert_system_prompt_str():
    system = "You are a helpful assistant."
    result = AnthropicToOpenAIConverter.convert_system_prompt(system)
    assert result == {"role": "system", "content": system}


def test_convert_messages_basic():
    class SimpleMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    messages = [SimpleMessage("user", "Hello")]
    result = AnthropicToOpenAIConverter.convert_messages(messages)
    assert len(result) == 1
    assert result[0] == {"role": "user", "content": "Hello"}


def test_convert_tools():
    class SimpleTool:
        def __init__(self, name, description, input_schema):
            self.name = name
            self.description = description
            self.input_schema = input_schema

    tools = [
        SimpleTool("get_weather", "Get weather", {"type": "object", "properties": {}})
    ]
    result = AnthropicToOpenAIConverter.convert_tools(tools)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "get_weather"
    assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}
