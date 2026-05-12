from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

import chromadb
from pypdf import PdfReader


DEFAULT_CONFIG_CANDIDATES = (
	"config-pdf2embedding.txt",
	"config-pdf2embedding.py",
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


def sanitize_collection_name(value: str) -> str:
	cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
	if not cleaned:
		return "pdf-embedding"
	if len(cleaned) < 3:
		cleaned = f"pdf-{cleaned}"
	return cleaned[:63]


def resolve_source_path(config_path: Path, raw_source: str | None) -> Path:
	if not raw_source:
		raise ValueError("Missing required config key: source")

	source_path = Path(raw_source)
	if not source_path.is_absolute():
		source_path = (config_path.parent / source_path).resolve()

	if not source_path.exists():
		raise FileNotFoundError(f"PDF source file not found: {source_path}")

	return source_path


def extract_pdf_pages(source_path: Path) -> list[tuple[int, str]]:
	reader = PdfReader(str(source_path))
	pages: list[tuple[int, str]] = []
	for index, page in enumerate(reader.pages, start=1):
		text = (page.extract_text() or "").strip()
		if text:
			pages.append((index, text))

	if not pages:
		raise ValueError("No extractable text found in the PDF.")

	return pages


def normalize_text(value: str) -> str:
	return re.sub(r"\s+", " ", value).strip()


def chunk_pages(
	pages: list[tuple[int, str]],
	chunk_size: int,
	chunk_overlap: int,
) -> list[dict[str, Any]]:
	if chunk_size <= 0:
		raise ValueError("chunk_size must be greater than 0")
	if chunk_overlap < 0:
		raise ValueError("chunk_overlap must be 0 or greater")
	if chunk_overlap >= chunk_size:
		raise ValueError("chunk_overlap must be smaller than chunk_size")

	chunks: list[dict[str, Any]] = []
	step = chunk_size - chunk_overlap
	chunk_index = 0

	for page_number, page_text in pages:
		normalized = normalize_text(page_text)
		if not normalized:
			continue

		start = 0
		while start < len(normalized):
			end = min(start + chunk_size, len(normalized))
			chunk_text = normalized[start:end].strip()
			if chunk_text:
				chunks.append(
					{
						"page": page_number,
						"chunk_index": chunk_index,
						"start_char": start,
						"end_char": end,
						"text": chunk_text,
					}
				)
				chunk_index += 1

			if end >= len(normalized):
				break
			start += step

	if not chunks:
		raise ValueError("Unable to create chunks from PDF text.")

	return chunks


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


def fetch_embeddings(
	texts: list[str],
	base_url: str,
	model: str,
	timeout_seconds: int,
) -> list[list[float]]:
	primary_url = f"{base_url.rstrip('/')}/api/embed"
	primary_payload = {
		"model": model,
		"input": texts,
	}

	try:
		response_json = post_json(primary_url, primary_payload, timeout_seconds)
		raw_embeddings = response_json.get("embeddings")
		if not isinstance(raw_embeddings, list) or not raw_embeddings:
			raise RuntimeError("Ollama /api/embed returned no embeddings.")
		embeddings = [list(vector) for vector in raw_embeddings]
		return embeddings
	except RuntimeError as exc:
		if "/api/embed" not in str(exc):
			raise

	fallback_url = f"{base_url.rstrip('/')}/api/embeddings"
	embeddings: list[list[float]] = []
	for text in texts:
		response_json = post_json(
			fallback_url,
			{"model": model, "prompt": text},
			timeout_seconds,
		)
		vector = response_json.get("embedding")
		if not isinstance(vector, list) or not vector:
			raise RuntimeError("Ollama /api/embeddings returned no embedding.")
		embeddings.append(vector)

	return embeddings


def reset_directory(path: Path) -> None:
	if path.exists():
		shutil.rmtree(path)
	path.mkdir(parents=True, exist_ok=True)


def write_database(
	persist_path: Path,
	collection_name: str,
	source_path: Path,
	chunks: list[dict[str, Any]],
	embeddings: list[list[float]],
) -> None:
	client = chromadb.PersistentClient(path=str(persist_path))
	collection = client.get_or_create_collection(name=collection_name)

	ids = [f"{source_path.stem}-{chunk['chunk_index']:05d}" for chunk in chunks]
	documents = [chunk["text"] for chunk in chunks]
	metadatas = [
		{
			"source": str(source_path),
			"file_name": source_path.name,
			"page": chunk["page"],
			"chunk_index": chunk["chunk_index"],
			"start_char": chunk["start_char"],
			"end_char": chunk["end_char"],
		}
		for chunk in chunks
	]

	collection.add(
		ids=ids,
		documents=documents,
		metadatas=metadatas,
		embeddings=embeddings,
	)


def main() -> int:
	try:
		script_dir = Path(__file__).resolve().parent
		config_path = resolve_config_path(script_dir)
		config = parse_config(config_path)
		source_path = resolve_source_path(config_path, config.get("source"))

		base_url = config.get("base_url", "http://localhost:11434")
		model = config.get("model", "nomic-embed-text")
		timeout_seconds = get_int(config.get("timeout"), 120)
		chunk_size = get_int(config.get("chunk_size"), 1000)
		chunk_overlap = get_int(config.get("chunk_overlap"), 150)
		collection_name = sanitize_collection_name(
			config.get("collection", source_path.stem)
		)
		persist_path = (script_dir / "db" / "data.db").resolve()

		pages = extract_pdf_pages(source_path)
		chunks = chunk_pages(pages, chunk_size, chunk_overlap)
		embeddings = fetch_embeddings(
			[chunk["text"] for chunk in chunks],
			base_url=base_url,
			model=model,
			timeout_seconds=timeout_seconds,
		)

		if len(embeddings) != len(chunks):
			raise RuntimeError(
				f"Embedding count mismatch: expected {len(chunks)}, got {len(embeddings)}"
			)

		reset_directory(persist_path)
		write_database(persist_path, collection_name, source_path, chunks, embeddings)

		print(f"Config file: {config_path.name}")
		print(f"Source PDF: {source_path}")
		print(f"Collection: {collection_name}")
		print(f"Chunks: {len(chunks)}")
		print(f"Database path: {persist_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
