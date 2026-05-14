from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_CONFIG_CANDIDATES = (
    "config-apikeyhidding.txt",
)


def parse_config(config_path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Invalid config line: {raw_line}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value.startswith(('"', "'")) and value.endswith(('"', "'")):
            value = value[1:-1]

        config[key] = value

    return config


def get_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def resolve_config_path(script_dir: Path) -> Path:
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        candidate_path = script_dir / candidate
        if candidate_path.exists():
            return candidate_path
    raise FileNotFoundError(
        "No config file found. Expected one of: " + ", ".join(DEFAULT_CONFIG_CANDIDATES)
    )


def resolve_relative_path(base_dir: Path, raw_path: str | None, label: str) -> Path:
    if not raw_path:
        raise ValueError(f"Missing required config key: {label}")

    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def read_api_key(config_path: Path, config: dict[str, str]) -> str:
    key_path = resolve_relative_path(config_path.parent, config.get("keyfile"), "keyfile")
    if not key_path.exists():
        raise FileNotFoundError(f"API key file not found: {key_path}")

    api_key = key_path.read_text(encoding="utf-8").strip()
    if not api_key:
        raise ValueError(f"API key file is empty: {key_path}")

    return api_key


def build_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def fetch_available_models(base_url: str, timeout_seconds: int, headers: dict[str, str]) -> list[str]:
    tags_url = f"{base_url.rstrip('/')}/tags"
    http_request = request.Request(tags_url, headers=headers, method="GET")

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Unable to read Ollama model list: HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to connect to Ollama API: {exc.reason}") from exc

    models = payload.get("models", [])
    return [str(model.get("name", "")).strip() for model in models if model.get("name")]


def select_model(config: dict[str, str], base_url: str, timeout_seconds: int, headers: dict[str, str]) -> str:
    configured_model = config.get("model")
    if configured_model:
        return configured_model

    available_models = fetch_available_models(base_url, timeout_seconds, headers)
    if not available_models:
        raise RuntimeError(
            "No Ollama models are available for this API key. Add model=<name> to the config or enable a cloud model first."
        )

    for model_name in available_models:
        lower_name = model_name.lower()
        if "embed" not in lower_name and "embedding" not in lower_name:
            return model_name

    return available_models[0]


def build_request(config: dict[str, str], headers: dict[str, str]) -> tuple[str, dict[str, Any], int, str, dict[str, str]]:
    user_request = config.get("request")
    if not user_request:
        raise ValueError('Missing required config key: request')

    base_url = config.get("base_url", "https://ollama.com/api").rstrip("/")
    endpoint = config.get("endpoint", "/chat")
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"

    timeout_seconds = get_int(config.get("timeout"), 60)
    stream = get_bool(config.get("stream"), default=False)
    model = select_model(config, base_url, timeout_seconds, headers)

    if endpoint == "/chat":
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": user_request}],
            "stream": stream,
        }
        if config.get("system"):
            payload["messages"].insert(0, {"role": "system", "content": config["system"]})
    elif endpoint == "/generate":
        payload = {
            "model": model,
            "prompt": user_request,
            "stream": stream,
        }
        if config.get("system"):
            payload["system"] = config["system"]
    else:
        raise ValueError("endpoint must be /chat or /generate")

    return f"{base_url}{endpoint}", payload, timeout_seconds, model, headers


def call_ollama_api(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    headers: dict[str, str],
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama API HTTP error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to connect to Ollama API: {exc.reason}") from exc


def extract_response_text(endpoint: str, response_json: dict[str, Any]) -> str:
    if endpoint.endswith("/chat"):
        return str(response_json.get("message", {}).get("content", "")).strip()
    return str(response_json.get("response", "")).strip()


def resolve_output_path(config_path: Path, config: dict[str, str]) -> Path:
    return resolve_relative_path(config_path.parent, config.get("output", "./output.txt"), "output")


def write_output(output_path: Path, response_text: str, response_json: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = response_text or json.dumps(response_json, ensure_ascii=False, indent=2)
    output_path.write_text(content + "\n", encoding="utf-8")


def main() -> int:
    try:
        script_dir = Path(__file__).resolve().parent
        config_path = resolve_config_path(script_dir)
        config = parse_config(config_path)
        api_key = read_api_key(config_path, config)
        headers = build_headers(api_key)
        url, payload, timeout_seconds, model, request_headers = build_request(config, headers)
        response_json = call_ollama_api(url, payload, timeout_seconds, request_headers)
        response_text = extract_response_text(url, response_json)
        output_path = resolve_output_path(config_path, config)
        write_output(output_path, response_text, response_json)

        print(f"Config file: {config_path.name}")
        print(f"Request URL: {url}")
        print(f"Model: {model}")
        print(f"Request: {config['request']}")
        print(f"Output file: {output_path}")
        print("Response:")
        print(response_text or json.dumps(response_json, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())