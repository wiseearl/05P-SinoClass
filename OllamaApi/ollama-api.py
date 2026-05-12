from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_CONFIG_CANDIDATES = (
    "config-ollama-api.txt",
    "config-ollama-apy.txt",
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


def resolve_config_path() -> Path:
    script_dir = Path(__file__).resolve().parent
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        path = script_dir / candidate
        if path.exists():
            return path
    raise FileNotFoundError(
        "No config file found. Expected one of: "
        + ", ".join(DEFAULT_CONFIG_CANDIDATES)
    )


def fetch_available_models(base_url: str, timeout_seconds: int) -> list[str]:
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    http_request = request.Request(tags_url, method="GET")

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


def select_model_for_endpoint(
    config: dict[str, str], endpoint: str, base_url: str, timeout_seconds: int
) -> str:
    is_embedding_endpoint = endpoint in {"/api/embed", "/api/embeddings"}
    config_key = "embedding_model" if is_embedding_endpoint else "model"
    configured_model = config.get(config_key)
    if configured_model:
        return configured_model

    available_models = fetch_available_models(base_url, timeout_seconds)
    if not available_models:
        raise RuntimeError(
            "No Ollama models are installed. Add model=<name> or embedding_model=<name> to the config or pull a model first."
        )

    if is_embedding_endpoint:
        for model_name in available_models:
            lower_name = model_name.lower()
            if "embed" in lower_name or "embedding" in lower_name:
                return model_name
    else:
        for model_name in available_models:
            lower_name = model_name.lower()
            if "embed" not in lower_name and "embedding" not in lower_name:
                return model_name

    return available_models[0]


def build_request_payload(config: dict[str, str]) -> tuple[str, dict[str, Any], int]:
    question = config.get("question")
    if not question:
        raise ValueError('Missing required config key: question')

    base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
    endpoint = config.get("endpoint", "/api/generate")
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"

    stream = get_bool(config.get("stream"), default=False)
    timeout_seconds = get_int(config.get("timeout"), default=60)
    model = select_model_for_endpoint(config, endpoint, base_url, timeout_seconds)

    if endpoint == "/api/chat":
        payload: dict[str, Any] = {
            "model": model,
            "stream": stream,
        }
        payload["messages"] = [{"role": "user", "content": question}]
        if config.get("system"):
            payload["messages"].insert(0, {"role": "system", "content": config["system"]})
    elif endpoint == "/api/embed":
        payload = {
            "model": model,
            "input": question,
        }
    elif endpoint == "/api/embeddings":
        payload = {
            "model": model,
            "prompt": question,
        }
    else:
        payload = {
            "model": model,
            "stream": stream,
        }
        payload["prompt"] = question
        if config.get("system"):
            payload["system"] = config["system"]

    return f"{base_url}{endpoint}", payload, timeout_seconds


def extract_response_text(endpoint: str, response_json: dict[str, Any]) -> str:
    if endpoint.endswith("/api/chat"):
        return str(response_json.get("message", {}).get("content", "")).strip()
    return str(response_json.get("response", "")).strip()


def call_ollama_api(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
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


def write_output(output_path: Path, response_text: str, response_json: dict[str, Any]) -> None:
    content = response_text or json.dumps(response_json, ensure_ascii=False, indent=2)
    output_path.write_text(content + "\n", encoding="utf-8")


def main() -> int:
    try:
        script_dir = Path(__file__).resolve().parent
        config_path = resolve_config_path()
        config = parse_config(config_path)
        url, payload, timeout_seconds = build_request_payload(config)
        response_json = call_ollama_api(url, payload, timeout_seconds)
        response_text = extract_response_text(url, response_json)
        output_path = script_dir / "output.txt"
        write_output(output_path, response_text, response_json)

        print(f"Config file: {config_path.name}")
        print(f"Request URL: {url}")
        print(f"Question: {config['question']}")
        print(f"Output file: {output_path.name}")
        print("Response:")
        print(response_text or json.dumps(response_json, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())