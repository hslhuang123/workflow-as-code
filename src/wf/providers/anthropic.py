from __future__ import annotations

import inspect
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import fields, is_dataclass
from typing import Any, Callable, get_args, get_origin, get_type_hints

from wf.ir import Node
from wf.providers.base import AgentResult
from wf.registries import Registries, to_plain, validate_call_inputs

DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
FUELIX_BASE_URL = "https://api.fuelix.ai"
FUELIX_API_URL = f"{FUELIX_BASE_URL}/v1/messages"

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
        api_url: str = ANTHROPIC_API_URL,
        provider_name: str = "anthropic",
        auth_mode: str = "x-api-key",
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL
        self.api_url = api_url
        self.provider_name = provider_name
        self.auth_mode = auth_mode
        self.transport = transport or self._http_transport

    def run_agent(self, *, node: Node, inputs: dict[str, Any], registries: Registries) -> AgentResult:
        if not self.api_key and self.transport == self._http_transport:
            raise AnthropicProviderError(f"API key is required for provider {self.provider_name!r}")
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
            "system": _system_prompt(node, registries),
            "messages": messages,
            "tools": [_tool_schema(registries.tool(name)) for name in node.tools],
        }

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "user-agent": "workflow-as-code/0.1.0",
        }
        if self.auth_mode == "bearer":
            headers["authorization"] = f"Bearer {self.api_key or ''}"
        else:
            headers["x-api-key"] = self.api_key or ""
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AnthropicProviderError(f"{self.provider_name} API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise AnthropicProviderError(f"{self.provider_name} API request failed: {exc.reason}") from exc


class FuelIXAgentProvider(AnthropicAgentProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        transport: Transport | None = None,
        api_url: str | None = None,
    ):
        base_url = os.environ.get("FUELIX_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or FUELIX_BASE_URL
        resolved_url = api_url or _messages_url(base_url)
        token = api_key or os.environ.get("FUELIX_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        super().__init__(
            api_key=token,
            model=model,
            transport=transport,
            api_url=resolved_url,
            provider_name="fuelix",
            auth_mode="bearer",
        )


def _messages_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/v1/messages"):
        return cleaned
    return f"{cleaned}/v1/messages"


def _system_prompt(node: Node, registries: Registries) -> str:
    instructions = node.instructions or ""
    schema_text = _output_schema_text(node, registries)
    return (
        f"{instructions}\n\n"
        f"Output schema:\n{schema_text}\n\n"
        "Return exactly one JSON object matching the output schema. "
        "Include every required field. Do not wrap it in Markdown. "
        "Do not include commentary outside JSON."
    )


def _output_schema_text(node: Node, registries: Registries) -> str:
    if not node.output_schema:
        return "No named output schema. Return a JSON object."
    schema = registries.schema(node.output_schema)
    if not is_dataclass(schema):
        return f"{node.output_schema}: JSON value"
    lines = [f"{node.output_schema} object with required fields:"]
    type_hints = get_type_hints(schema)
    for field in fields(schema):
        annotation = type_hints.get(field.name, field.type)
        lines.append(f"- {field.name}: {_type_name(annotation)}")
    return "\n".join(lines)


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        inner = _type_name(args[0]) if args else "any"
        return f"list[{inner}]"
    if origin is dict:
        return "object"
    if origin is not None and str(origin).endswith("Literal"):
        return " | ".join(repr(arg) for arg in args)
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation)


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
