from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import chromadb
import hnswlib
import numpy as np


DEFAULT_CONFIG_CANDIDATES = (
	"config-hnsw.txt",
	"../Index/config-hnsw.txt",
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


def get_config_value(config: dict[str, str], *keys: str) -> str | None:
	for key in keys:
		value = config.get(key)
		if value is not None:
			return value
	return None


def resolve_database_path(config_path: Path, config: dict[str, str]) -> Path:
	database_path = resolve_relative_path(config_path.parent, config.get("database_path"), "./db/data.db")
	if not database_path.exists():
		raise FileNotFoundError(f"ChromaDB path not found: {database_path}")
	return database_path


def resolve_output_index_path(config_path: Path, config: dict[str, str]) -> Path:
	return resolve_relative_path(config_path.parent, config.get("output_index_path"), "./db/hnsw-index.bin")


def resolve_manifest_path(config_path: Path, config: dict[str, str]) -> Path:
	return resolve_relative_path(config_path.parent, config.get("manifest_path"), "./db/hnsw-manifest.json")


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


def load_collection_vectors(client: Any, collection_name: str) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
	collection = client.get_collection(name=collection_name)
	count = collection.count()
	if count <= 0:
		raise RuntimeError("The selected Chroma collection is empty.")

	result = collection.get(
		limit=count,
		include=["embeddings", "metadatas"],
	)
	raw_ids = result.get("ids", [])
	raw_embeddings = result.get("embeddings", [])
	raw_metadatas = result.get("metadatas", [])

	if len(raw_ids) == 0 or len(raw_embeddings) == 0:
		raise RuntimeError("Embeddings are missing from the vector database.")
	if len(raw_ids) != len(raw_embeddings):
		raise RuntimeError(
			f"Embedding count mismatch: expected {len(raw_ids)}, got {len(raw_embeddings)}"
		)

	vector_array = np.asarray(raw_embeddings, dtype=np.float32)
	if vector_array.ndim != 2 or vector_array.shape[1] <= 0:
		raise RuntimeError("Invalid embedding shape returned from ChromaDB.")

	metadatas: list[dict[str, Any]] = []
	for index, item in enumerate(raw_metadatas):
		if isinstance(item, dict):
			metadatas.append(item)
		else:
			metadatas.append({"row_index": index})

	return [str(item) for item in raw_ids], vector_array, metadatas


def build_hnsw_index(
	vectors: np.ndarray,
	m_value: int,
	ef_construction: int,
	ef_search: int,
) -> hnswlib.Index:
	dimension = int(vectors.shape[1])
	index = hnswlib.Index(space="cosine", dim=dimension)
	index.init_index(
		max_elements=int(vectors.shape[0]),
		ef_construction=ef_construction,
		M=m_value,
		allow_replace_deleted=False,
	)
	labels = np.arange(vectors.shape[0], dtype=np.int32)
	index.add_items(vectors, labels)
	index.set_ef(ef_search)
	return index


def build_manifest(
	config_path: Path,
	database_path: Path,
	collection_name: str,
	ids: list[str],
	metadatas: list[dict[str, Any]],
	vectors: np.ndarray,
	m_value: int,
	ef_construction: int,
	ef_search: int,
	top_k: int,
	self_check_labels: list[int],
	self_check_distances: list[float],
) -> dict[str, Any]:
	items: list[dict[str, Any]] = []
	for index, chunk_id in enumerate(ids):
		metadata = metadatas[index] if index < len(metadatas) else {}
		items.append(
			{
				"label": index,
				"chunk_id": chunk_id,
				"metadata": metadata,
			}
		)

	return {
		"config_file": str(config_path),
		"database_path": str(database_path),
		"collection": collection_name,
		"space": "cosine",
		"count": len(ids),
		"dimension": int(vectors.shape[1]),
		"M": m_value,
		"efConstruction": ef_construction,
		"efSearch": ef_search,
		"top_k": top_k,
		"self_check": [
			{
				"rank": rank,
				"label": label,
				"chunk_id": ids[label],
				"distance": distance,
			}
			for rank, (label, distance) in enumerate(
				zip(self_check_labels, self_check_distances),
				start=1,
			)
		],
		"items": items,
	}


def write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
	manifest_path.parent.mkdir(parents=True, exist_ok=True)
	manifest_path.write_text(
		json.dumps(manifest, ensure_ascii=False, indent=2),
		encoding="utf-8",
	)


def main() -> int:
	try:
		script_dir = Path(__file__).resolve().parent
		config_path = resolve_config_path(script_dir)
		config = parse_config(config_path)

		database_path = resolve_database_path(config_path, config)
		output_index_path = resolve_output_index_path(config_path, config)
		manifest_path = resolve_manifest_path(config_path, config)
		m_value = get_int(get_config_value(config, "M", "m"), 16)
		ef_construction = get_int(
			get_config_value(config, "efConstruction", "ef_construction"),
			150,
		)
		ef_search = get_int(get_config_value(config, "efSearch", "ef_search"), 75)
		top_k = get_int(get_config_value(config, "Top-K", "top_k", "top-k"), 5)

		if m_value <= 0:
			raise ValueError("M must be greater than 0")
		if ef_construction <= 0:
			raise ValueError("efConstruction must be greater than 0")
		if ef_search <= 0:
			raise ValueError("efSearch must be greater than 0")
		if top_k <= 0:
			raise ValueError("Top-K must be greater than 0")

		client = chromadb.PersistentClient(path=str(database_path))
		collection_name = resolve_collection_name(client, config)
		ids, vectors, metadatas = load_collection_vectors(client, collection_name)
		index = build_hnsw_index(vectors, m_value, ef_construction, ef_search)

		query_k = min(top_k, len(ids))
		labels, distances = index.knn_query(vectors[0], k=query_k)
		self_check_labels = [int(item) for item in labels[0].tolist()]
		self_check_distances = [float(item) for item in distances[0].tolist()]

		output_index_path.parent.mkdir(parents=True, exist_ok=True)
		index.save_index(str(output_index_path))
		manifest = build_manifest(
			config_path,
			database_path,
			collection_name,
			ids,
			metadatas,
			vectors,
			m_value,
			ef_construction,
			ef_search,
			top_k,
			self_check_labels,
			self_check_distances,
		)
		write_manifest(manifest_path, manifest)

		print(f"Config file: {config_path}")
		print(f"Database path: {database_path}")
		print(f"Collection: {collection_name}")
		print(f"Vectors: {len(ids)}")
		print(f"Dimension: {vectors.shape[1]}")
		print(f"HNSW index path: {output_index_path}")
		print(f"Manifest path: {manifest_path}")
		print(f"Self-check Top-K: {query_k}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())