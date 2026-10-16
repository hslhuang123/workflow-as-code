from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class YamlError(ValueError):
    pass


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    text: str


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    data = loads(text)
    if not isinstance(data, dict):
        raise YamlError("workflow YAML must contain a top-level mapping")
    return data


def loads(text: str) -> Any:
    lines = _prepare(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines):
        line = lines[index]
        raise YamlError(f"line {line.number}: unexpected content")
    return value


def _prepare(text: str) -> list[_Line]:
    prepared: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if "\t" in raw[:indent]:
            raise YamlError(f"line {number}: tabs are not allowed for indentation")
        text_part = raw[indent:].rstrip()
        prepared.append(_Line(number, indent, text_part))
    return prepared


def _parse_block(lines: list[_Line], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    line = lines[index]
    if line.indent < indent:
        return {}, index
    if line.indent != indent:
        raise YamlError(f"line {line.number}: expected indent {indent}, got {line.indent}")
    if line.text.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_dict(lines: list[_Line], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent != indent:
            raise YamlError(f"line {line.number}: expected indent {indent}, got {line.indent}")
        if line.text.startswith("- "):
            break
        key, marker, raw_value = line.text.partition(":")
        if marker != ":" or not key.strip():
            raise YamlError(f"line {line.number}: expected 'key: value'")
        key = key.strip()
        raw_value = raw_value.strip()
        if key in result:
            raise YamlError(f"line {line.number}: duplicate key {key!r}")
        if raw_value == "":
            if index + 1 >= len(lines) or lines[index + 1].indent <= indent:
                result[key] = {}
                index += 1
            else:
                result[key], index = _parse_block(lines, index + 1, lines[index + 1].indent)
        elif raw_value in {"|", ">"}:
            result[key], index = _parse_block_scalar(lines, index + 1, indent, folded=(raw_value == ">"))
        else:
            result[key] = _parse_scalar(raw_value)
            index += 1
    return result, index


def _parse_list(lines: list[_Line], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent != indent or not line.text.startswith("- "):
            break
        raw_item = line.text[2:].strip()
        if raw_item == "":
            if index + 1 >= len(lines) or lines[index + 1].indent <= indent:
                result.append(None)
                index += 1
            else:
                item, index = _parse_block(lines, index + 1, lines[index + 1].indent)
                result.append(item)
            continue
        if _looks_like_inline_mapping(raw_item):
            key, _, raw_value = raw_item.partition(":")
            item: dict[str, Any] = {}
            key = key.strip()
            raw_value = raw_value.strip()
            if raw_value == "":
                item[key] = {}
            elif raw_value in {"|", ">"}:
                item[key], index = _parse_block_scalar(lines, index + 1, indent, folded=(raw_value == ">"))
                result.append(item)
                continue
            else:
                item[key] = _parse_scalar(raw_value)
            index += 1
            if index < len(lines) and lines[index].indent > indent:
                extra, index = _parse_dict(lines, index, lines[index].indent)
                item.update(extra)
            result.append(item)
        else:
            result.append(_parse_scalar(raw_item))
            index += 1
    return result, index


def _parse_block_scalar(
    lines: list[_Line], index: int, parent_indent: int, *, folded: bool
) -> tuple[str, int]:
    scalar_lines: list[str] = []
    block_indent: int | None = None
    while index < len(lines):
        line = lines[index]
        if line.indent <= parent_indent:
            break
        if block_indent is None:
            block_indent = line.indent
        if line.indent < block_indent:
            raise YamlError(f"line {line.number}: inconsistent block scalar indentation")
        scalar_lines.append(" " * (line.indent - block_indent) + line.text)
        index += 1
    if folded:
        return " ".join(part.strip() for part in scalar_lines).rstrip() + "\n", index
    return "\n".join(scalar_lines).rstrip() + "\n", index


def _looks_like_inline_mapping(value: str) -> bool:
    if ":" not in value:
        return False
    before, after = value.split(":", 1)
    return bool(before.strip()) and (after == "" or after.startswith(" "))


def _parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        try:
            return ast.literal_eval(value)
        except Exception as exc:  # pragma: no cover - exact parser message not important
            raise YamlError(f"invalid quoted scalar {value!r}: {exc}") from exc
    if value.startswith("[") or value.startswith("{"):
        try:
            return ast.literal_eval(value)
        except Exception as exc:
            raise YamlError(f"invalid inline collection {value!r}: {exc}") from exc
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
