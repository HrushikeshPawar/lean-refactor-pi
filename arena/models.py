"""Load and validate the central model configuration, models.yaml.

Only the YAML subset that file uses is parsed (nested maps, flow lists and maps, scalars,
comments), so the harness needs no YAML dependency. `pi_json` is what the Arena extension and the offline test
provider read: the models, and the providers the extension registers with Pi.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "models.yaml"
PRICE_KEYS = ("input", "output", "cache_read", "cache_write")
POSITIVE = ("context_window", "max_tokens", "request_output_tokens")


class ModelConfigError(ValueError):
    pass


def _scalar(text: str):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d*|-?\.\d+", text):
        return float(text)
    return {"true": True, "false": False, "null": None}.get(text, text)


def _split_flow(text: str) -> list[str]:
    parts, depth, quote, start = [], 0, "", 0
    for index, char in enumerate(text):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _value(text: str):
    text = text.strip()
    if text.startswith("["):
        return [_value(part) for part in _split_flow(text[1:-1])]
    if text.startswith("{"):
        out = {}
        for part in _split_flow(text[1:-1]):
            key, _, rest = part.partition(":")
            out[key.strip()] = _value(rest)
        return out
    return _scalar(text)


def _strip_comment(line: str) -> str:
    quote = ""
    for index, char in enumerate(line):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def parse(text: str) -> dict:
    lines = [
        (len(raw) - len(raw.lstrip(" ")), raw.strip()) for raw in map(_strip_comment, text.splitlines()) if raw.strip()
    ]
    root: dict = {}
    stack = [(-1, root)]
    for index, (indent, line) in enumerate(lines):
        key, colon, rest = line.partition(":")
        if not colon:
            raise ModelConfigError(f"models.yaml: cannot read line {line!r}")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if rest.strip():
            parent[key.strip()] = _value(rest)
        else:
            if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                raise ModelConfigError(f"models.yaml: {key.strip()!r} has no value")
            child: dict = {}
            parent[key.strip()] = child
            stack.append((indent, child))
    return root


def _number(owner: str, key: str, value, integer: bool = False) -> None:
    ok = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not ok or value <= 0:
        raise ModelConfigError(
            f"models.yaml: {owner}.{key} must be a positive {'integer' if integer else 'number'}, got {value!r}"
        )


def _price(owner: str, price) -> None:
    if not isinstance(price, dict) or set(price) != set(PRICE_KEYS):
        raise ModelConfigError(f"models.yaml: {owner} needs exactly {', '.join(PRICE_KEYS)}")
    for key, value in price.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ModelConfigError(f"models.yaml: {owner}.{key} must be a non-negative number, got {value!r}")


def validate(config: dict) -> dict:
    for key in ("provider", "models", "thinking", "provider_timeout_ms", "outage_limit_ms", "retry"):
        if key not in config:
            raise ModelConfigError(f"models.yaml: missing {key}")
    _number("", "provider_timeout_ms", config["provider_timeout_ms"], integer=True)
    _number("", "outage_limit_ms", config["outage_limit_ms"], integer=True)
    retry = config["retry"]
    if not isinstance(retry, dict):
        raise ModelConfigError("models.yaml: retry must be a map")
    for key in ("max_retries", "base_delay_ms", "max_delay_ms"):
        _number("retry", key, retry.get(key), integer=True)
    thinking = config["thinking"]
    if not isinstance(thinking, dict) or thinking.get("default") not in (thinking.get("levels") or ()):
        raise ModelConfigError("models.yaml: thinking.default must be one of thinking.levels")
    models = config["models"]
    if not isinstance(models, dict) or not models:
        raise ModelConfigError("models.yaml: models must list at least one model")
    for name, model in models.items():
        if not isinstance(model, dict):
            raise ModelConfigError(f"models.yaml: {name} must be a map")
        if "tool_turn_reasoning_effort" in model and (
            not isinstance(model["tool_turn_reasoning_effort"], str) or not model["tool_turn_reasoning_effort"]
        ):
            raise ModelConfigError(f"models.yaml: {name}.tool_turn_reasoning_effort must be a non-empty string")
        _price(f"{name}.price", model.get("price"))
        for key in POSITIVE:
            _number(name, key, model.get(key), integer=True)
        if model["request_output_tokens"] > model["max_tokens"]:
            raise ModelConfigError(f"models.yaml: {name}.request_output_tokens exceeds max_tokens")
        if ("high_price" in model) != ("high_context_threshold" in model):
            raise ModelConfigError(f"models.yaml: {name} needs high_price and high_context_threshold together")
        if "high_price" in model:
            _price(f"{name}.high_price", model["high_price"])
            _number(name, "high_context_threshold", model["high_context_threshold"], integer=True)
        compaction = model.get("compaction")
        if not isinstance(compaction, dict):
            raise ModelConfigError(f"models.yaml: {name}.compaction is required")
        for key in ("at_tokens", "keep_recent_tokens"):
            _number(f"{name}.compaction", key, compaction.get(key), integer=True)
        if compaction["at_tokens"] >= model["context_window"]:
            raise ModelConfigError(f"models.yaml: {name}.compaction.at_tokens must be below context_window")
    providers = config.get("providers") or {}
    for name, provider in providers.items():
        for key in ("base_url", "api", "api_key_env"):
            if not isinstance(provider, dict) or not isinstance(provider.get(key), str):
                raise ModelConfigError(f"models.yaml: providers.{name}.{key} is required")
    for name, model in models.items():
        provider = model.get("provider", config["provider"])
        builtin = config.get("builtin_providers") or []
        if provider != config["provider"] and provider not in providers and provider not in builtin:
            raise ModelConfigError(f"models.yaml: {name}.provider {provider!r} is neither the default, in providers, nor in builtin_providers")
        if provider in providers and not isinstance(model.get("reasoning"), bool):
            raise ModelConfigError(f"models.yaml: {name}.reasoning (true/false) is required for a registered provider")
    for name, preset in (config.get("presets") or {}).items():
        unknown = [model for model in preset.get("models", []) if model not in models]
        if unknown:
            raise ModelConfigError(f"models.yaml: preset {name} names unknown models {unknown}")
    return config


@cache
def load(path: Path = PATH) -> dict:
    try:
        return validate(parse(path.read_text()))
    except OSError as error:
        raise ModelConfigError(f"cannot read {path}: {error}") from error


def models() -> tuple[str, ...]:
    return tuple(load()["models"])


def _camel(key: str) -> str:
    head, *tail = key.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _camelize(value):
    if isinstance(value, dict):
        return {_camel(key): _camelize(item) for key, item in value.items()}
    return value


def provider(name: str, config: dict | None = None) -> str:
    config = config or load()
    return config["models"][name].get("provider", config["provider"])


def pi_model(name: str, config: dict | None = None) -> str:
    """The `provider/id` Pi selects for one models.yaml entry."""
    config = config or load()
    return f"{provider(name, config)}/{config['models'][name].get('id', name)}"


def pi_providers(config: dict | None = None) -> dict:
    """`pi.registerProvider` arguments for every provider Pi does not ship, with the models that name it."""
    config = config or load()
    out = {}
    for key, row in (config.get("providers") or {}).items():
        models = [
            {
                "id": model.get("id", name),
                "name": model.get("name", name),
                "reasoning": model["reasoning"],
                "input": ["text"],
                "cost": _camelize(model["price"]),
                "contextWindow": model["context_window"],
                "maxTokens": model["max_tokens"],
                **({"compat": _camelize(model["compat"])} if "compat" in model else {}),
            }
            for name, model in config["models"].items()
            if model.get("provider") == key
        ]
        out[key] = {"baseUrl": row["base_url"], "api": row["api"], "apiKey": f"${row['api_key_env']}", "models": models}
    return out


def pi_json(config: dict | None = None) -> str:
    """The ARENA_MODELS_JSON shape: camelCase models plus the providers the extension registers."""
    config = config or load()
    return json.dumps(
        {"provider": config["provider"], "models": _camelize(config["models"]), "providers": pi_providers(config)},
        separators=(",", ":"),
    )


def pi_catalog(provider_name: str, home: Path | None = None) -> dict[str, dict]:
    """The installed Pi's built-in catalog for one provider, by model id; empty when Pi is not installed."""
    home = home or Path.home()
    install = home / ".pi/agent/install"
    try:
        version = (install / "current-version").read_text().strip()
        data = json.loads(
            (
                install
                / "releases"
                / version
                / "node_modules/@earendil-works/pi-ai/dist/providers/data"
                / f"{provider_name}.json"
            ).read_text()
        )
    except (OSError, ValueError):
        return {}
    return {row["id"]: row for rows in data.values() for row in rows.values() if isinstance(row, dict) and "id" in row}


def catalog_price_problems(config: dict | None = None, home: Path | None = None) -> list[str]:
    """Models whose models.yaml price differs from the price Pi charges them at.

    Pi computes each call's cost from its own catalog for the providers it ships, and the spend stop sums those
    costs, so a catalog price that drifted from the provider's bill makes the stop wrong. Registered providers are
    priced from models.yaml itself and cannot drift. A model missing from an installed catalog is a problem too.
    """
    home = home or Path.home()
    config = config or load()
    problems = []
    for name, model in config["models"].items():
        provider_name = provider(name, config)
        if provider_name in (config.get("providers") or {}):
            continue
        catalog = pi_catalog(provider_name, home)
        if not catalog:
            continue  # Pi is not installed here
        row = catalog.get(model.get("id", name))
        if row is None:
            problems.append(f"{name}: not in Pi's {provider_name} catalog")
            continue
        expected = _camelize(model["price"])
        actual = {key: row.get("cost", {}).get(key) for key in expected}
        if any(actual[key] is None or abs(actual[key] - value) > 1e-9 for key, value in expected.items()):
            problems.append(f"{name}: models.yaml price {expected} but Pi charges {actual}")
    return problems
