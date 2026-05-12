from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

import chromadb


DEFAULT_CONFIG_CANDIDATES = (
	"config-rag-request.txt",
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


def resolve_config_path(script_dir: Path) -> Path:
	for candidate in DEFAULT_CONFIG_CANDIDATES:
		candidate_path = script_dir / candidate
		if candidate_path.exists():
			return candidate_path
	raise FileNotFoundError(
		"No config file found. Expected one of: " + ", ".join(DEFAULT_CONFIG_CANDIDATES)
	)


def get_int(value: str | None, default: int) -> int:
	if value is None or not value.strip():
		return default
	return int(value)


def post_json(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
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
		raise RuntimeError(f"HTTP {exc.code} calling {url}: {detail}") from exc
	except error.URLError as exc:
		raise RuntimeError(f"Unable to connect to Ollama API: {exc.reason}") from exc


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


def choose_generation_model(config: dict[str, str], base_url: str, timeout_seconds: int) -> str:
	configured = config.get("model")
	if configured:
		return configured

	available_models = fetch_available_models(base_url, timeout_seconds)
	if not available_models:
		raise RuntimeError(
			"No Ollama models are installed. Add model=<name> to the config or pull a chat model first."
		)

	for model_name in available_models:
		lower_name = model_name.lower()
		if "embed" not in lower_name and "embedding" not in lower_name:
			return model_name

	return available_models[0]


def fetch_embeddings(
	texts: list[str],
	base_url: str,
	embedding_model: str,
	timeout_seconds: int,
) -> list[list[float]]:
	primary_url = f"{base_url.rstrip('/')}/api/embed"
	response_json = post_json(
		primary_url,
		{"model": embedding_model, "input": texts},
		timeout_seconds,
	)
	raw_embeddings = response_json.get("embeddings")
	if not isinstance(raw_embeddings, list) or not raw_embeddings:
		raise RuntimeError("Ollama /api/embed returned no embeddings.")
	return [list(vector) for vector in raw_embeddings]


def resolve_database_path(script_dir: Path, config: dict[str, str]) -> Path:
	raw_path = config.get("database_path", "./db/data.db")
	database_path = Path(raw_path)
	if not database_path.is_absolute():
		database_path = (script_dir / database_path).resolve()
	if not database_path.exists():
		raise FileNotFoundError(f"ChromaDB path not found: {database_path}")
	return database_path


def resolve_collection_name(client: chromadb.PersistentClient, config: dict[str, str]) -> str:
	configured = config.get("collection")
	if configured:
		return configured

	collections = client.list_collections()
	if not collections:
		raise RuntimeError("No ChromaDB collections found in the database.")
	return collections[0].name


def query_context(
	client: chromadb.PersistentClient,
	collection_name: str,
	question: str,
	base_url: str,
	embedding_model: str,
	top_k: int,
	timeout_seconds: int,
) -> tuple[list[str], list[dict[str, Any]]]:
	question_embedding = fetch_embeddings(
		[question],
		base_url=base_url,
		embedding_model=embedding_model,
		timeout_seconds=timeout_seconds,
	)[0]

	collection = client.get_collection(name=collection_name)
	results = collection.query(
		query_embeddings=[question_embedding],
		n_results=top_k,
	)

	documents = results.get("documents", [[]])[0]
	metadatas = results.get("metadatas", [[]])[0]
	if not documents:
		raise RuntimeError("No matching context was found in the vector database.")
	return documents, metadatas


def build_prompt(question: str, documents: list[str], metadatas: list[dict[str, Any]]) -> str:
	context_blocks: list[str] = []
	for index, document in enumerate(documents, start=1):
		metadata = metadatas[index - 1] if index - 1 < len(metadatas) else {}
		page = metadata.get("page", "?")
		file_name = metadata.get("file_name", "unknown")
		context_blocks.append(
			f"[Context {index}] file={file_name}, page={page}\n{document}"
		)

	joined_context = "\n\n".join(context_blocks)
	return (
		"你是一個根據文件內容回答問題的助理。"
		"請只根據提供的上下文回答。"
		"如果上下文不足以支持答案，請明確回答「資料中沒有足夠資訊」。"
		"回答請使用繁體中文。\n\n"
		f"上下文：\n{joined_context}\n\n"
		f"問題：\n{question}\n\n"
		"請給出精簡且直接的答案。"
	)


def generate_answer(
	base_url: str,
	model: str,
	prompt: str,
	timeout_seconds: int,
) -> str:
	url = f"{base_url.rstrip('/')}/api/generate"
	response_json = post_json(
		url,
		{
			"model": model,
			"prompt": prompt,
			"stream": False,
		},
		timeout_seconds,
	)
	answer = str(response_json.get("response", "")).strip()
	if not answer:
		raise RuntimeError("Ollama returned an empty answer.")
	return answer


def write_output(output_path: Path, answer: str) -> None:
	output_path.write_text(answer + "\n", encoding="utf-8")


def main() -> int:
	try:
		script_dir = Path(__file__).resolve().parent
		config_path = resolve_config_path(script_dir)
		config = parse_config(config_path)

		question = config.get("question")
		if not question:
			raise ValueError("Missing required config key: question")

		base_url = config.get("base_url", "http://localhost:11434")
		timeout_seconds = get_int(config.get("timeout"), 120)
		top_k = get_int(config.get("top_k"), 4)
		embedding_model = config.get("embedding_model", "nomic-embed-text")
		generation_model = choose_generation_model(config, base_url, timeout_seconds)
		database_path = resolve_database_path(script_dir, config)

		client = chromadb.PersistentClient(path=str(database_path))
		collection_name = resolve_collection_name(client, config)
		documents, metadatas = query_context(
			client,
			collection_name=collection_name,
			question=question,
			base_url=base_url,
			embedding_model=embedding_model,
			top_k=top_k,
			timeout_seconds=timeout_seconds,
		)
		prompt = build_prompt(question, documents, metadatas)
		answer = generate_answer(
			base_url=base_url,
			model=generation_model,
			prompt=prompt,
			timeout_seconds=timeout_seconds,
		)

		output_path = script_dir / "output.txt"
		write_output(output_path, answer)

		print(f"Config file: {config_path.name}")
		print(f"Question: {question}")
		print(f"Collection: {collection_name}")
		print(f"Retrieved chunks: {len(documents)}")
		print(f"Output file: {output_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())