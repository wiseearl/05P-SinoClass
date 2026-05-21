from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal
from urllib import error, request

import chromadb
import hnswlib


DEFAULT_CONFIG_CANDIDATES = (
	"config-rrf.txt",
	"../Index/config-rrf.txt",
)

HnswSpace = Literal["l2", "ip", "cosine"]


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


def resolve_chapter_index_path(config_path: Path, config: dict[str, str]) -> Path:
	index_path = resolve_relative_path(config_path.parent, config.get("index_path"), "./db/chapter-index.json")
	if not index_path.exists():
		raise FileNotFoundError(f"Chapter index not found: {index_path}")
	return index_path


def resolve_hnsw_index_path(config_path: Path, config: dict[str, str]) -> Path:
	index_path = resolve_relative_path(config_path.parent, config.get("hnsw_index_path"), "./db/hnsw-index.bin")
	if not index_path.exists():
		raise FileNotFoundError(f"HNSW index not found: {index_path}")
	return index_path


def resolve_hnsw_manifest_path(config_path: Path, config: dict[str, str]) -> Path:
	manifest_path = resolve_relative_path(config_path.parent, config.get("manifest_path"), "./db/hnsw-manifest.json")
	if not manifest_path.exists():
		raise FileNotFoundError(f"HNSW manifest not found: {manifest_path}")
	return manifest_path


def resolve_output_path(script_dir: Path, config: dict[str, str]) -> Path:
	return resolve_relative_path(script_dir, config.get("output"), "output-rrf.txt")


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


def load_hnsw_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	label_lookup: dict[int, dict[str, Any]] = {}
	for item in manifest.get("items", []):
		label = item.get("label")
		if isinstance(label, int):
			label_lookup[label] = item
	return manifest, label_lookup


def normalize_hnsw_space(raw_space: Any) -> HnswSpace:
	if raw_space in ("l2", "ip", "cosine"):
		return raw_space
	return "cosine"


def cosine_similarity_from_distance(distance: float | None) -> float | None:
	if distance is None:
		return None
	return 1.0 - distance


def fetch_chunk_records(
	client: Any,
	collection_name: str,
	chunk_ids: list[str],
	chunk_lookup: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
	if not chunk_ids:
		return {}

	collection = client.get_collection(name=collection_name)
	result = collection.get(ids=chunk_ids, include=["documents", "metadatas"])
	raw_ids = result.get("ids", [])
	raw_documents = result.get("documents", [])
	raw_metadatas = result.get("metadatas", [])

	records: dict[str, dict[str, Any]] = {}
	for index, chunk_id in enumerate(raw_ids):
		normalized_chunk_id = str(chunk_id)
		metadata = raw_metadatas[index] if index < len(raw_metadatas) and isinstance(raw_metadatas[index], dict) else {}
		document = raw_documents[index] if index < len(raw_documents) else ""
		records[normalized_chunk_id] = {
			"chunk_id": normalized_chunk_id,
			"document": str(document),
			"metadata": metadata,
			"chapter": chunk_lookup.get(normalized_chunk_id, {}),
		}

	return records


def query_chapter_index(
	client: Any,
	collection_name: str,
	question_embedding: list[float],
	top_k: int,
	chunk_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
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
		raise RuntimeError("No matching context was found in the chapter index retrieval.")

	hits: list[dict[str, Any]] = []
	for index, document in enumerate(documents, start=1):
		metadata = metadatas[index - 1] if index - 1 < len(metadatas) and isinstance(metadatas[index - 1], dict) else {}
		chunk_id = str(ids[index - 1]) if index - 1 < len(ids) else ""
		distance_value = distances[index - 1] if index - 1 < len(distances) else None
		distance = float(distance_value) if isinstance(distance_value, (int, float)) else None
		hits.append(
			{
				"rank": index,
				"chunk_id": chunk_id,
				"document": str(document),
				"metadata": metadata,
				"chapter": chunk_lookup.get(chunk_id, {}),
				"distance": distance,
				"score": cosine_similarity_from_distance(distance),
			}
		)

	return hits


def query_hnsw_index(
	client: Any,
	collection_name: str,
	question_embedding: list[float],
	hnsw_index_path: Path,
	manifest: dict[str, Any],
	label_lookup: dict[int, dict[str, Any]],
	chunk_lookup: dict[str, dict[str, Any]],
	top_k: int,
) -> list[dict[str, Any]]:
	dimension = int(manifest.get("dimension", 0))
	count = int(manifest.get("count", 0))
	if dimension <= 0 or count <= 0:
		raise RuntimeError("Invalid HNSW manifest metadata.")
	if len(question_embedding) != dimension:
		raise RuntimeError(
			f"Embedding dimension mismatch: expected {dimension}, got {len(question_embedding)}"
		)

	index = hnswlib.Index(space=normalize_hnsw_space(manifest.get("space")), dim=dimension)
	index.load_index(str(hnsw_index_path), max_elements=count)
	ef_search = int(manifest.get("efSearch", max(top_k * 4, 20)))
	index.set_ef(max(top_k, ef_search))

	query_k = min(top_k, count)
	labels, distances = index.knn_query(question_embedding, k=query_k)

	ordered_items: list[tuple[int, float]] = []
	chunk_ids: list[str] = []
	for label, distance in zip(labels[0].tolist(), distances[0].tolist()):
		normalized_label = int(label)
		item = label_lookup.get(normalized_label)
		if item is None:
			continue
		chunk_id = str(item.get("chunk_id", "")).strip()
		if not chunk_id:
			continue
		ordered_items.append((normalized_label, float(distance)))
		chunk_ids.append(chunk_id)

	record_lookup = fetch_chunk_records(client, collection_name, chunk_ids, chunk_lookup)
	hits: list[dict[str, Any]] = []
	for rank, (label, distance) in enumerate(ordered_items, start=1):
		item = label_lookup[label]
		chunk_id = str(item.get("chunk_id", "")).strip()
		fallback_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
		base_record = record_lookup.get(
			chunk_id,
			{
				"chunk_id": chunk_id,
				"document": "",
				"metadata": fallback_metadata,
				"chapter": chunk_lookup.get(chunk_id, {}),
			},
		)
		hits.append(
			{
				"rank": rank,
				"label": label,
				"chunk_id": chunk_id,
				"document": base_record["document"],
				"metadata": base_record["metadata"],
				"chapter": base_record["chapter"],
				"distance": distance,
				"score": cosine_similarity_from_distance(distance),
			}
		)

	if not hits:
		raise RuntimeError("No matching context was found in the HNSW retrieval.")

	return hits


def fuse_rrf(
	chapter_hits: list[dict[str, Any]],
	hnsw_hits: list[dict[str, Any]],
	rrf_k: int,
	top_k: int,
) -> list[dict[str, Any]]:
	fused: dict[str, dict[str, Any]] = {}

	for source_name, hits in (("chapter", chapter_hits), ("hnsw", hnsw_hits)):
		for hit in hits:
			chunk_id = hit["chunk_id"]
			entry = fused.setdefault(
				chunk_id,
				{
					"chunk_id": chunk_id,
					"document": hit["document"],
					"metadata": hit["metadata"],
					"chapter": hit["chapter"],
					"rrf_score": 0.0,
					"sources": {},
				},
			)
			if hit["document"]:
				entry["document"] = hit["document"]
			if hit["metadata"]:
				entry["metadata"] = hit["metadata"]
			if hit["chapter"]:
				entry["chapter"] = hit["chapter"]
			entry["sources"][source_name] = {
				"rank": hit["rank"],
				"distance": hit["distance"],
				"score": hit["score"],
			}
			entry["rrf_score"] += 1.0 / (rrf_k + hit["rank"])

	fused_hits = sorted(
		fused.values(),
		key=lambda item: (
			item["rrf_score"],
			max(
				(source.get("score") if isinstance(source.get("score"), float) else float("-inf"))
				for source in item["sources"].values()
			),
		),
		reverse=True,
	)

	for index, hit in enumerate(fused_hits[:top_k], start=1):
		hit["rank"] = index

	return fused_hits[:top_k]


def build_prompt(question: str, hits: list[dict[str, Any]]) -> str:
	context_blocks: list[str] = []
	for hit in hits:
		metadata = hit["metadata"]
		chapter = hit["chapter"]
		page = metadata.get("page", "?")
		file_name = metadata.get("file_name", "unknown")
		chapter_name = chapter.get("chapter", "未對應章節")
		context_blocks.append(
			f"[Context {hit['rank']}] chunk_id={hit['chunk_id']}, file={file_name}, page={page}, chapter={chapter_name}, rrf_score={hit['rrf_score']:.6f}\n{hit['document']}"
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


def generate_answer(base_url: str, model: str, prompt: str, timeout_seconds: int) -> str:
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


def format_retrieval_hits(title: str, hits: list[dict[str, Any]]) -> str:
	blocks: list[str] = []
	for hit in hits:
		metadata = hit["metadata"]
		chapter = hit["chapter"]
		distance = hit["distance"]
		score = hit["score"]
		distance_text = f"{distance:.6f}" if isinstance(distance, float) else "N/A"
		score_text = f"{score:.6f}" if isinstance(score, float) else "N/A"
		blocks.append(
			f"[{hit['rank']}] chunk_id={hit['chunk_id']}, score={score_text}, distance={distance_text}, file={metadata.get('file_name', 'unknown')}, page={metadata.get('page', '?')}\n"
			f"章節: {chapter.get('chapter', '未對應章節')}\n"
			f"內容:\n{hit['document']}"
		)
	return f"{title}:\n" + "\n\n".join(blocks)


def format_rrf_hits(hits: list[dict[str, Any]]) -> str:
	blocks: list[str] = []
	for hit in hits:
		metadata = hit["metadata"]
		chapter = hit["chapter"]
		chapter_source = hit["sources"].get("chapter", {})
		hnsw_source = hit["sources"].get("hnsw", {})
		chapter_score = chapter_source.get("score")
		hnsw_score = hnsw_source.get("score")
		chapter_score_text = f"{chapter_score:.6f}" if isinstance(chapter_score, float) else "N/A"
		hnsw_score_text = f"{hnsw_score:.6f}" if isinstance(hnsw_score, float) else "N/A"
		chapter_rank = chapter_source.get("rank", "-")
		hnsw_rank = hnsw_source.get("rank", "-")
		blocks.append(
			f"[{hit['rank']}] chunk_id={hit['chunk_id']}, rrf_score={hit['rrf_score']:.6f}, chapter_rank={chapter_rank}, chapter_score={chapter_score_text}, hnsw_rank={hnsw_rank}, hnsw_score={hnsw_score_text}, file={metadata.get('file_name', 'unknown')}, page={metadata.get('page', '?')}\n"
			f"章節: {chapter.get('chapter', '未對應章節')}\n"
			f"內容:\n{hit['document']}"
		)
	return "RRF Top 4 結果:\n" + "\n\n".join(blocks)


def build_payload(
	config_path: Path,
	chapter_index_path: Path,
	hnsw_index_path: Path,
	hnsw_manifest_path: Path,
	collection_name: str,
	question: str,
	answer: str,
	chapter_hits: list[dict[str, Any]],
	hnsw_hits: list[dict[str, Any]],
	rrf_hits: list[dict[str, Any]],
	base_url: str,
	model: str,
	embedding_model: str,
	rrf_k: int,
) -> dict[str, Any]:
	return {
		"config_path": str(config_path),
		"chapter_index_path": str(chapter_index_path),
		"hnsw_index_path": str(hnsw_index_path),
		"hnsw_manifest_path": str(hnsw_manifest_path),
		"collection": collection_name,
		"question": question,
		"answer": answer,
		"base_url": base_url,
		"model": model,
		"embedding_model": embedding_model,
		"rrf_k": rrf_k,
		"chapter_hits": chapter_hits,
		"hnsw_hits": hnsw_hits,
		"rrf_hits": rrf_hits,
	}


def write_output(
	output_path: Path,
	question: str,
	answer: str,
	chapter_hits: list[dict[str, Any]],
	hnsw_hits: list[dict[str, Any]],
	rrf_hits: list[dict[str, Any]],
	payload: dict[str, Any],
) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	content = (
		f"問題:\n{question}\n\n"
		f"回答:\n{answer}\n\n"
		f"{format_retrieval_hits('chapter-index Top 4 結果', chapter_hits)}\n\n"
		f"{format_retrieval_hits('hnsw-manifest Top 4 結果', hnsw_hits)}\n\n"
		f"{format_rrf_hits(rrf_hits)}\n\n"
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
		rrf_k = get_int(config.get("rrf_k"), 60)
		if top_k <= 0:
			raise ValueError("top_k must be greater than 0")
		if rrf_k <= 0:
			raise ValueError("rrf_k must be greater than 0")

		embedding_model = config.get("embedding_model", "nomic-embed-text")
		generation_model = choose_generation_model(config, base_url, timeout_seconds)
		database_path = resolve_database_path(config_path, config)
		chapter_index_path = resolve_chapter_index_path(config_path, config)
		hnsw_index_path = resolve_hnsw_index_path(config_path, config)
		hnsw_manifest_path = resolve_hnsw_manifest_path(config_path, config)
		output_path = resolve_output_path(script_dir, config)

		chapter_index, chunk_lookup = load_chapter_index(chapter_index_path)
		hnsw_manifest, label_lookup = load_hnsw_manifest(hnsw_manifest_path)
		client = chromadb.PersistentClient(path=str(database_path))
		collection_name = resolve_collection_name(client, config)
		question_embedding = fetch_embeddings(
			[question],
			base_url=base_url,
			embedding_model=embedding_model,
			timeout_seconds=timeout_seconds,
		)[0]

		chapter_hits = query_chapter_index(
			client,
			collection_name=collection_name,
			question_embedding=question_embedding,
			top_k=top_k,
			chunk_lookup=chunk_lookup,
		)
		hnsw_hits = query_hnsw_index(
			client,
			collection_name=collection_name,
			question_embedding=question_embedding,
			hnsw_index_path=hnsw_index_path,
			manifest=hnsw_manifest,
			label_lookup=label_lookup,
			chunk_lookup=chunk_lookup,
			top_k=top_k,
		)
		rrf_hits = fuse_rrf(chapter_hits, hnsw_hits, rrf_k=rrf_k, top_k=top_k)

		prompt = build_prompt(question, rrf_hits)
		answer = generate_answer(
			base_url=base_url,
			model=generation_model,
			prompt=prompt,
			timeout_seconds=timeout_seconds,
		)
		payload = build_payload(
			config_path=config_path,
			chapter_index_path=chapter_index_path,
			hnsw_index_path=hnsw_index_path,
			hnsw_manifest_path=hnsw_manifest_path,
			collection_name=collection_name,
			question=question,
			answer=answer,
			chapter_hits=chapter_hits,
			hnsw_hits=hnsw_hits,
			rrf_hits=rrf_hits,
			base_url=base_url,
			model=generation_model,
			embedding_model=embedding_model,
			rrf_k=rrf_k,
		)
		write_output(output_path, question, answer, chapter_hits, hnsw_hits, rrf_hits, payload)

		print(f"Config file: {config_path}")
		print(f"Database path: {database_path}")
		print(f"Chapter index path: {chapter_index_path}")
		print(f"HNSW index path: {hnsw_index_path}")
		print(f"HNSW manifest path: {hnsw_manifest_path}")
		print(f"Collection: {collection_name}")
		print(f"Question: {question}")
		print(f"Chapter count: {chapter_index.get('chapter_count', 0)}")
		print(f"chapter-index hits: {len(chapter_hits)}")
		print(f"hnsw hits: {len(hnsw_hits)}")
		print(f"rrf hits: {len(rrf_hits)}")
		print(f"Output: {output_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())