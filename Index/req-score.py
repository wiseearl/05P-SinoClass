from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

import chromadb


DEFAULT_CONFIG_CANDIDATES = (
	"config-req-score.txt",
	"../Index/config-req-score.txt",
)


def parse_config(config_path: Path) -> dict[str, str]:
	config: dict[str, str] = {}
	for raw_line in config_path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#"):
			continue

		separator = "="
		if "=" not in line:
			if ":" not in line:
				raise ValueError(f"Invalid config line: {raw_line}")
			separator = ":"

		key, value = line.split(separator, 1)
		key = key.strip()
		value = value.strip()

		if value.startswith(('"', "'")) and value.endswith(('"', "'")):
			value = value[1:-1]

		config[key] = value

	return config


def resolve_config_path(script_dir: Path) -> Path:
	for candidate in DEFAULT_CONFIG_CANDIDATES:
		candidate_path = (script_dir / candidate).resolve()
		if candidate_path.exists():
			return candidate_path
	raise FileNotFoundError(
		"No config file found. Expected one of: " + ", ".join(DEFAULT_CONFIG_CANDIDATES)
	)


def get_int(value: str | None, default: int) -> int:
	if value is None or not value.strip():
		return default
	return int(value)


def resolve_relative_path(base_dir: Path, raw_path: str | None, default_path: str) -> Path:
	path = Path(raw_path or default_path)
	if not path.is_absolute():
		path = (base_dir / path).resolve()
	return path


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

	try:
		response_json = post_json(
			primary_url,
			{"model": embedding_model, "input": texts},
			timeout_seconds,
		)
		raw_embeddings = response_json.get("embeddings")
		if not isinstance(raw_embeddings, list) or not raw_embeddings:
			raise RuntimeError("Ollama /api/embed returned no embeddings.")
		return [list(vector) for vector in raw_embeddings]
	except RuntimeError as exc:
		if "/api/embed" not in str(exc):
			raise

	fallback_url = f"{base_url.rstrip('/')}/api/embeddings"
	embeddings: list[list[float]] = []
	for text in texts:
		response_json = post_json(
			fallback_url,
			{"model": embedding_model, "prompt": text},
			timeout_seconds,
		)
		vector = response_json.get("embedding")
		if not isinstance(vector, list) or not vector:
			raise RuntimeError("Ollama /api/embeddings returned no embedding.")
		embeddings.append(vector)

	return embeddings


def resolve_database_path(config_path: Path, config: dict[str, str]) -> Path:
	database_path = resolve_relative_path(config_path.parent, config.get("database_path"), "./db/data.db")
	if not database_path.exists():
		raise FileNotFoundError(f"ChromaDB path not found: {database_path}")
	return database_path


def resolve_index_path(config_path: Path, config: dict[str, str]) -> Path:
	index_path = resolve_relative_path(
		config_path.parent,
		config.get("index_path"),
		"./db/chapter-index.json",
	)
	if not index_path.exists():
		raise FileNotFoundError(f"Chapter index not found: {index_path}")
	return index_path


def resolve_output_path(script_dir: Path, config: dict[str, str]) -> Path:
	return resolve_relative_path(script_dir, config.get("output"), "output.txt")


def resolve_collection_name(client: Any, config: dict[str, str]) -> str:
	configured = config.get("collection")
	if configured:
		try:
			client.get_collection(name=configured)
			return configured
		except Exception:
			pass

	collections = client.list_collections()
	if not collections:
		raise RuntimeError("No ChromaDB collections found in the database.")
	return collections[0].name


def load_chapter_index(index_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
	chapter_index = json.loads(index_path.read_text(encoding="utf-8"))
	chunk_lookup: dict[str, dict[str, Any]] = {}
	for chapter in chapter_index.get("chapters", []):
		for chunk_id in chapter.get("chunk_ids", []):
			chunk_lookup[str(chunk_id)] = chapter
	return chapter_index, chunk_lookup


def query_context(
	client: Any,
	collection_name: str,
	question: str,
	base_url: str,
	embedding_model: str,
	top_k: int,
	timeout_seconds: int,
	chunk_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
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
		include=["documents", "metadatas", "distances"],
	)

	ids = results.get("ids", [[]])[0]
	documents = results.get("documents", [[]])[0]
	metadatas = results.get("metadatas", [[]])[0]
	distances = results.get("distances", [[]])[0]
	if not documents:
		raise RuntimeError("No matching context was found in the vector database.")

	hits: list[dict[str, Any]] = []
	for index, document in enumerate(documents, start=1):
		metadata = metadatas[index - 1] if index - 1 < len(metadatas) else {}
		chunk_id = str(ids[index - 1]) if index - 1 < len(ids) else ""
		distance = distances[index - 1] if index - 1 < len(distances) else None
		chapter = chunk_lookup.get(chunk_id, {})
		hits.append(
			{
				"rank": index,
				"chunk_id": chunk_id,
				"document": document,
				"metadata": metadata,
				"distance": float(distance) if isinstance(distance, (int, float)) else None,
				"chapter": chapter,
			}
		)

	return hits


def build_prompt(question: str, hits: list[dict[str, Any]]) -> str:
	context_blocks: list[str] = []
	for hit in hits:
		metadata = hit["metadata"]
		chapter = hit["chapter"]
		page = metadata.get("page", "?")
		file_name = metadata.get("file_name", "unknown")
		chapter_name = chapter.get("chapter", "未對應章節")
		context_blocks.append(
			f"[Context {hit['rank']}] chunk_id={hit['chunk_id']}, file={file_name}, page={page}, chapter={chapter_name}\n{hit['document']}"
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
			"think": False,
		},
		timeout_seconds,
	)
	answer = str(response_json.get("response", "")).strip()
	if not answer:
		raise RuntimeError("Ollama returned an empty answer.")
	return answer


def format_hits(hits: list[dict[str, Any]]) -> str:
	blocks: list[str] = []
	for hit in hits:
		metadata = hit["metadata"]
		chapter = hit["chapter"]
		distance = hit["distance"]
		pages = chapter.get("pages") or ([metadata.get("page")] if metadata.get("page") else [])
		page_text = ", ".join(str(page) for page in pages if page is not None) or "?"
		distance_text = f"{distance:.6f}" if isinstance(distance, float) else "N/A"
		blocks.append(
			f"[{hit['rank']}] chunk_id={hit['chunk_id']}, distance={distance_text}, file={metadata.get('file_name', 'unknown')}, page={metadata.get('page', '?')}\n"
			f"章節: {chapter.get('chapter', '未對應章節')}\n"
			f"章節頁碼: {page_text}\n"
			f"章節預覽: {chapter.get('preview', 'N/A')}\n"
			f"內容:\n{hit['document']}"
		)
	return "\n\n".join(blocks)


def build_payload(
	config_path: Path,
	index_path: Path,
	collection_name: str,
	question: str,
	answer: str,
	hits: list[dict[str, Any]],
	base_url: str,
	model: str,
	embedding_model: str,
) -> dict[str, Any]:
	return {
		"config_path": str(config_path),
		"index_path": str(index_path),
		"collection": collection_name,
		"question": question,
		"answer": answer,
		"base_url": base_url,
		"model": model,
		"embedding_model": embedding_model,
		"top_hits": [
			{
				"rank": hit["rank"],
				"chunk_id": hit["chunk_id"],
				"distance": hit["distance"],
				"metadata": hit["metadata"],
				"chapter": hit["chapter"],
				"document": hit["document"],
			}
			for hit in hits
		],
	}


def write_output(
	output_path: Path,
	question: str,
	answer: str,
	hits: list[dict[str, Any]],
	payload: dict[str, Any],
) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	content = (
		f"問題:\n{question}\n\n"
		f"回答:\n{answer}\n\n"
		"RAG Top 4 結果:\n"
		f"{format_hits(hits)}\n\n"
		"JSON:\n"
		f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
	)
	output_path.write_text(content, encoding="utf-8")


def main() -> int:
	try:
		script_dir = Path(__file__).resolve().parent
		config_path = resolve_config_path(script_dir)
		config = parse_config(config_path)

		question = config.get("question")
		if not question:
			raise ValueError("Missing required config key: question")

		base_url = config.get("base_url", "http://localhost:11434")
		timeout_seconds = get_int(config.get("timeout"), 300)
		top_k = get_int(config.get("top_k"), 4)
		embedding_model = config.get("embedding_model", "nomic-embed-text")
		generation_model = choose_generation_model(config, base_url, timeout_seconds)
		database_path = resolve_database_path(config_path, config)
		index_path = resolve_index_path(config_path, config)
		output_path = resolve_output_path(script_dir, config)

		chapter_index, chunk_lookup = load_chapter_index(index_path)
		client = chromadb.PersistentClient(path=str(database_path))
		collection_name = resolve_collection_name(client, config)
		hits = query_context(
			client,
			collection_name=collection_name,
			question=question,
			base_url=base_url,
			embedding_model=embedding_model,
			top_k=top_k,
			timeout_seconds=timeout_seconds,
			chunk_lookup=chunk_lookup,
		)
		prompt = build_prompt(question, hits)
		answer = generate_answer(
			base_url=base_url,
			model=generation_model,
			prompt=prompt,
			timeout_seconds=timeout_seconds,
		)
		payload = build_payload(
			config_path=config_path,
			index_path=index_path,
			collection_name=collection_name,
			question=question,
			answer=answer,
			hits=hits,
			base_url=base_url,
			model=generation_model,
			embedding_model=embedding_model,
		)
		write_output(output_path, question, answer, hits, payload)

		print(f"Config file: {config_path}")
		print(f"Database path: {database_path}")
		print(f"Chapter index path: {index_path}")
		print(f"Collection: {collection_name}")
		print(f"Question: {question}")
		print(f"Chapter count: {chapter_index.get('chapter_count', 0)}")
		print(f"Top hits: {len(hits)}")
		print(f"Output: {output_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())