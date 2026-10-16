from __future__ import annotations

import inspect
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import is_dataclass
from typing import Any, Callable, get_args, get_origin, get_type_hints

from wf.ir import Node
from wf.providers.base import AgentResult
from wf.registries import Registries, to_plain, validate_call_inputs

DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProviderError(ValueError):
    pass


Transport = Callable[[dict[str, Any]], dict[str, Any]]


class AnthropicAgentProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        transport: Transport | None = None,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL
        self.transport = transport or self._http_transport

    def run_agent(self, *, node: Node, inputs: dict[str, Any], registries: Registries) -> AgentResult:
        if not self.api_key and self.transport == self._http_transport:
            raise AnthropicProviderError("ANTHROPIC_API_KEY is required for provider 'anthropic'")
        allowed_tools = set(node.tools)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps({"inputs": to_plain(inputs)}, sort_keys=True),
            }
        ]
        max_steps = int(node.policy.get("max_steps", 4) or 4)
        tokens = 0
        tool_calls: list[dict[str, Any]] = []
        for _ in range(max_steps):
            response = self.transport(self._payload(node=node, messages=messages, registries=registries))
            tokens += _tokens(response)
            content = response.get("content", [])
            if not isinstance(content, list):
                raise AnthropicProviderError("Anthropic response field 'content' must be a list")
            tool_uses = [block for block in content if block.get("type") == "tool_use"]
            if tool_uses:
                messages.append({"role": "assistant", "content": content})
                tool_results: list[dict[str, Any]] = []
                for block in tool_uses:
                    name = str(block.get("name", ""))
                    if name not in allowed_tools:
                        raise AnthropicProviderError(f"agent node {node.id!r} tried undeclared tool {name!r}")
                    func = registries.tool(name)
                    raw_input = block.get("input") or {}
                    if not isinstance(raw_input, dict):
                        raise AnthropicProviderError(f"tool {name!r} input must be an object")
                    checked_input = validate_call_inputs(func, raw_input, context=f"agent {node.id}.tool {name}")
                    result = func(**checked_input)
                    tool_calls.append({"tool": name, "status": "succeeded"})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.get("id"),
                            "content": json.dumps(to_plain(result), sort_keys=True),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
                continue
            text = _text_from_content(content)
            return AgentResult(output=_parse_json_output(text, node_id=node.id), tokens=tokens, tool_calls=tool_calls)
        raise AnthropicProviderError(f"agent node {node.id!r} exceeded max_steps={max_steps}")

    def _payload(self, *, node: Node, messages: list[dict[str, Any]], registries: Registries) -> dict[str, Any]:
        model = self.model or node.model or DEFAULT_ANTHROPIC_MODEL
        max_tokens = int(node.policy.get("max_tokens", 1024) or 1024)
        return {
            "model": model,
            "max_tokens": max_tokens,
            "system": _system_prompt(node),
            "messages": messages,
            "tools": [_tool_schema(registries.tool(name)) for name in node.tools],
        }

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AnthropicProviderError(f"Anthropic API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise AnthropicProviderError(f"Anthropic API request failed: {exc.reason}") from exc


def _system_prompt(node: Node) -> str:
    instructions = node.instructions or ""
    return (
        f"{instructions}\n\n"
        "Return exactly one JSON object matching the node output schema. "
        "Do not wrap it in Markdown. Do not include commentary outside JSON."
    )


def _tool_schema(func: Any) -> dict[str, Any]:
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        properties[name] = _json_schema(type_hints.get(name, parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "name": func.__name__,
        "description": inspect.getdoc(func) or f"Tool {func.__name__}",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _json_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if origin is list:
        return {"type": "array", "items": _json_schema(args[0] if args else Any)}
    if origin is dict:
        return {"type": "object"}
    if is_dataclass(annotation):
        return {"type": "object"}
    return {"type": "string"}


def _text_from_content(content: list[dict[str, Any]]) -> str:
    parts = [str(block.get("text", "")) for block in content if block.get("type") == "text"]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise AnthropicProviderError("Anthropic response did not contain final text output")
    return text


def _parse_json_output(text: str, *, node_id: str) -> Any:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnthropicProviderError(f"agent node {node_id!r} returned invalid JSON: {exc.msg}") from exc


def _tokens(response: dict[str, Any]) -> int:
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
