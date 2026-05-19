from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_CANDIDATES = (
    "config-ragas.txt",
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


def read_text_file(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"{label} is empty: {path}")
    return content


def import_external_module(module_name: str):
    script_dir = Path(__file__).resolve().parent
    removed_entry: str | None = None

    if sys.path:
        try:
            if Path(sys.path[0]).resolve() == script_dir:
                removed_entry = sys.path.pop(0)
        except OSError:
            removed_entry = None

    try:
        return importlib.import_module(module_name)
    finally:
        if removed_entry is not None:
            sys.path.insert(0, removed_entry)


def load_target_sample(config_path: Path, config: dict[str, str]) -> dict[str, Any]:
    target_config_path = resolve_relative_path(
        config_path.parent,
        config.get("target_config", "../ApikeyHidding/config-apikeyhidding.txt"),
        "target_config",
    )
    target_output_path = resolve_relative_path(
        config_path.parent,
        config.get("target_output", "../ApikeyHidding/output.txt"),
        "target_output",
    )

    target_config = parse_config(target_config_path)
    user_input = config.get("user_input") or target_config.get("request")
    if not user_input:
        raise ValueError(
            "Missing user_input. Add user_input to config-ragas.txt or request to the target config."
        )

    response = read_text_file(target_output_path, "Target output")

    return {
        "user_input": user_input,
        "response": response,
        "target_config_path": target_config_path,
        "target_output_path": target_output_path,
    }


def build_evaluation_dataset(sample: dict[str, Any]):
    ragas_module = import_external_module("ragas")

    record: dict[str, Any] = {
        "user_input": sample["user_input"],
        "response": sample["response"],
    }

    return ragas_module.EvaluationDataset.from_list([record])


def build_metrics():
    metrics_module = import_external_module("ragas.metrics")
    AspectCritic = metrics_module.AspectCritic
    ResponseRelevancy = metrics_module.ResponseRelevancy

    metrics: list[Any] = [ResponseRelevancy()]

    metrics.append(
        AspectCritic(
            name="conversation_quality",
            definition="回覆是否切題、清楚、自然且有幫助。",
        )
    )
    return metrics


def evaluate_sample(config: dict[str, str], sample: dict[str, Any]) -> dict[str, Any]:
    try:
        from langchain_ollama import ChatOllama, OllamaEmbeddings

        ragas_module = import_external_module("ragas")
        ragas_embeddings_module = import_external_module("ragas.embeddings")
        ragas_llms_module = import_external_module("ragas.llms")
        ragas_run_config_module = import_external_module("ragas.run_config")
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependencies. Install ragas and langchain-ollama in the project virtual environment."
        ) from exc

    evaluate = ragas_module.evaluate
    LangchainEmbeddingsWrapper = ragas_embeddings_module.LangchainEmbeddingsWrapper
    LangchainLLMWrapper = ragas_llms_module.LangchainLLMWrapper
    RunConfig = ragas_run_config_module.RunConfig

    base_url = config.get("base_url", "http://localhost:11434")
    evaluator_model = config.get("model", "qwen3.5:4b")
    embedding_model = config.get("embedding_model", "nomic-embed-text")
    timeout_seconds = get_int(config.get("timeout"), 300)
    max_workers = get_int(config.get("max_workers"), 1)
    num_predict = get_int(config.get("num_predict"), 128)

    llm = ChatOllama(
        model=evaluator_model,
        base_url=base_url,
        temperature=0,
        num_predict=num_predict,
        reasoning=False,
        format="json",
    )
    embeddings = OllamaEmbeddings(
        model=embedding_model,
        base_url=base_url,
    )

    dataset = build_evaluation_dataset(sample)
    embedding_wrapper = LangchainEmbeddingsWrapper(embeddings)
    metrics = build_metrics()
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=LangchainLLMWrapper(llm),
        embeddings=embedding_wrapper,
        run_config=RunConfig(timeout=timeout_seconds, max_workers=max_workers),
    )

    row = result.scores[0] if result.scores else {}
    numeric_scores = [
        float(value)
        for value in row.values()
        if isinstance(value, (int, float, bool))
        and math.isfinite(float(value))
    ]
    if not numeric_scores:
        raise RuntimeError(
            "RAGAS evaluation did not produce numeric scores. Increase timeout or use a faster local model."
        )

    overall_score = sum(numeric_scores) / len(numeric_scores)

    return {
        "overall_score": overall_score,
        "metrics": row,
        "model": evaluator_model,
        "embedding_model": embedding_model,
        "base_url": base_url,
        "max_workers": max_workers,
        "num_predict": num_predict,
        "timeout": timeout_seconds,
    }


def resolve_output_path(config_path: Path, config: dict[str, str]) -> Path:
    return resolve_relative_path(config_path.parent, config.get("output", "./output.txt"), "output")


def format_report(sample: dict[str, Any], evaluation: dict[str, Any]) -> str:
    metric_lines = []
    for name, value in evaluation["metrics"].items():
        if isinstance(value, float):
            metric_lines.append(f"- {name}: {value:.4f}")
        else:
            metric_lines.append(f"- {name}: {value}")

    return (
        "RAGAS 評估結果\n"
        f"整體分數: {evaluation['overall_score']:.4f}\n"
        f"評估模型: {evaluation['model']}\n"
        f"Embedding 模型: {evaluation['embedding_model']}\n"
        f"評估端點: {evaluation['base_url']}\n"
        f"原始問題: {sample['user_input']}\n"
        f"模型回答: {sample['response']}\n\n"
        "各項指標:\n"
        f"{'\n'.join(metric_lines)}\n"
    )


def write_output(output_path: Path, report_text: str, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report_text + "\nJSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        script_dir = Path(__file__).resolve().parent
        config_path = resolve_config_path(script_dir)
        config = parse_config(config_path)
        sample = load_target_sample(config_path, config)
        evaluation = evaluate_sample(config, sample)
        output_path = resolve_output_path(config_path, config)

        payload = {
            "sample": {
                "user_input": sample["user_input"],
                "response": sample["response"],
                "target_config_path": str(sample["target_config_path"]),
                "target_output_path": str(sample["target_output_path"]),
            },
            "evaluation": evaluation,
        }
        report_text = format_report(sample, evaluation)
        write_output(output_path, report_text, payload)

        print(f"Config file: {config_path}")
        print(f"Target config: {sample['target_config_path']}")
        print(f"Target output: {sample['target_output_path']}")
        print(f"Evaluation output: {output_path}")
        print(f"Overall score: {evaluation['overall_score']:.4f}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())