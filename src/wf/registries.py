from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


class RegistryError(ValueError):
    pass


class ValidationError(ValueError):
    pass


class Registries:
    def __init__(self, tasks: ModuleType, tools: ModuleType, schemas: ModuleType):
        self.tasks = tasks
        self.tools = tools
        self.schemas = schemas

    @classmethod
    def load(cls, registry_paths: dict[str, str]) -> "Registries":
        missing = [name for name in ("tasks", "tools", "schemas") if name not in registry_paths]
        if missing:
            raise RegistryError(f"missing registries: {', '.join(missing)}")
        return cls(
            tasks=_import(registry_paths["tasks"]),
            tools=_import(registry_paths["tools"]),
            schemas=_import(registry_paths["schemas"]),
        )

    def task(self, name: str) -> Any:
        return _get_callable(self.tasks, name, "task")

    def tool(self, name: str) -> Any:
        return _get_callable(self.tools, name, "tool")

    def schema(self, name: str) -> type:
        obj = getattr(self.schemas, name, None)
        if obj is None or not isinstance(obj, type):
            raise RegistryError(f"unknown schema {name!r} in {self.schemas.__name__}")
        return obj

    def has_task(self, name: str) -> bool:
        return callable(getattr(self.tasks, name, None))

    def has_tool(self, name: str) -> bool:
        return callable(getattr(self.tools, name, None))

    def has_schema(self, name: str) -> bool:
        return isinstance(getattr(self.schemas, name, None), type)

    def task_names(self) -> list[str]:
        return _public_callables(self.tasks)

    def tool_names(self) -> list[str]:
        return _public_callables(self.tools)

    def schema_names(self) -> list[str]:
        return sorted(
            name for name, obj in vars(self.schemas).items() if not name.startswith("_") and isinstance(obj, type)
        )


def _public_callables(module: ModuleType) -> list[str]:
    return sorted(
        name
        for name, obj in vars(module).items()
        if not name.startswith("_") and callable(obj) and getattr(obj, "__module__", None) == module.__name__
    )


def _import(path: str) -> ModuleType:
    try:
        return importlib.import_module(path)
    except Exception as first_exc:
        cwd = str(Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        try:
            return importlib.import_module(path)
        except Exception as exc:
            raise RegistryError(f"cannot import registry {path!r}: {exc}") from first_exc


def _get_callable(module: ModuleType, name: str, kind: str) -> Any:
    obj = getattr(module, name, None)
    if not callable(obj):
        raise RegistryError(f"unknown {kind} {name!r} in {module.__name__}")
    return obj


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_plain(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain(item) for item in value]
    return value


def validate_value(schema: type, value: Any, *, context: str) -> Any:
    if is_dataclass(schema):
        if is_dataclass(value):
            if isinstance(value, schema):
                return value
            value = to_plain(value)
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: expected object for {schema.__name__}, got {type(value).__name__}")
        type_hints = get_type_hints(schema)
        dataclass_fields = fields(schema)
        field_names = {field.name for field in dataclass_fields}
        missing = [field.name for field in dataclass_fields if field.name not in value]
        extra = sorted(set(value) - field_names)
        if missing:
            raise ValidationError(f"{context}: missing fields for {schema.__name__}: {', '.join(missing)}")
        if extra:
            raise ValidationError(f"{context}: unknown fields for {schema.__name__}: {', '.join(extra)}")
        kwargs: dict[str, Any] = {}
        for field in dataclass_fields:
            expected = type_hints.get(field.name, field.type)
            kwargs[field.name] = _validate_type(expected, value[field.name], f"{context}.{field.name}")
        return schema(**kwargs)
    if isinstance(value, schema):
        return value
    raise ValidationError(f"{context}: expected {schema.__name__}, got {type(value).__name__}")


def validate_call_inputs(func: Any, values: dict[str, Any], *, context: str) -> dict[str, Any]:
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    missing = [
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty and name not in values
    ]
    extra = sorted(set(values) - set(signature.parameters))
    if missing:
        raise ValidationError(f"{context}: missing inputs: {', '.join(missing)}")
    if extra:
        raise ValidationError(f"{context}: unknown inputs: {', '.join(extra)}")
    checked: dict[str, Any] = {}
    for name, value in values.items():
        annotation = type_hints.get(name, signature.parameters[name].annotation)
        if annotation is inspect.Parameter.empty:
            checked[name] = value
        else:
            checked[name] = _validate_type(annotation, value, f"{context}.{name}")
    return checked


def validate_return(func: Any, value: Any, *, context: str) -> Any:
    annotation = get_type_hints(func).get("return", inspect.signature(func).return_annotation)
    if annotation is inspect.Signature.empty or annotation is None:
        return value
    return _validate_type(annotation, value, context)


def _validate_type(expected: Any, value: Any, context: str) -> Any:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is Literal:
        if value not in args:
            allowed = ", ".join(repr(arg) for arg in args)
            raise ValidationError(f"{context}: expected one of {allowed}, got {value!r}")
        return value
    if origin in (list, list):
        if not isinstance(value, list):
            raise ValidationError(f"{context}: expected list, got {type(value).__name__}")
        inner = args[0] if args else Any
        return [_validate_type(inner, item, f"{context}[]") for item in value]
    if origin in (dict, dict):
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: expected object, got {type(value).__name__}")
        key_type = args[0] if args else Any
        val_type = args[1] if len(args) > 1 else Any
        return {
            _validate_type(key_type, key, f"{context}.key"): _validate_type(val_type, val, f"{context}[{key!r}]")
            for key, val in value.items()
        }
    if origin is Union:
        errors = []
        for option in args:
            try:
                return _validate_type(option, value, context)
            except ValidationError as exc:
                errors.append(str(exc))
        raise ValidationError(f"{context}: did not match any union option: {'; '.join(errors)}")
    if expected is Any:
        return value
    if expected is None or expected is type(None):
        if value is not None:
            raise ValidationError(f"{context}: expected null, got {type(value).__name__}")
        return value
    if is_dataclass(expected):
        return validate_value(expected, value, context=context)
    if expected in (str, int, float, bool):
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ValidationError(f"{context}: expected {expected.__name__}, got {type(value).__name__}")
        return value
    return value
