from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from Metadata.metadata import (
	build_segments,
	chunk_segments,
	extract_pdf_pages,
	fetch_embeddings,
	get_int,
	parse_config,
	reset_directory,
	resolve_source_path,
	sanitize_collection_name,
	write_database,
)


DEFAULT_CONFIG_CANDIDATES = (
	"config-metadata.txt",
	"../Metadata/config-metadata.txt",
)

def resolve_config_path(script_dir: Path) -> Path:
	for candidate in DEFAULT_CONFIG_CANDIDATES:
		candidate_path = (script_dir / candidate).resolve()
		if candidate_path.exists():
			return candidate_path
	raise FileNotFoundError(
		"No config file found. Expected one of: " + ", ".join(DEFAULT_CONFIG_CANDIDATES)
	)


def is_table_of_contents_chunk(chunk: dict[str, Any]) -> bool:
	page = int(chunk["page"])
	return page <= 2


def build_chapter_index(source_path: Path, chunks: list[dict[str, Any]]) -> dict[str, Any]:
	chapter_map: dict[str, dict[str, Any]] = {}

	for chunk in chunks:
		if is_table_of_contents_chunk(chunk):
			continue

		chapter = str(chunk["chapter"])
		entry = chapter_map.setdefault(
			chapter,
			{
				"chapter": chapter,
				"source": str(source_path),
				"file_name": source_path.name,
				"pages": [],
				"chunk_ids": [],
				"chunk_count": 0,
				"preview": str(chunk["text"]).splitlines()[-1][:200],
			},
		)

		page = int(chunk["page"])
		if page not in entry["pages"]:
			entry["pages"].append(page)

		entry["chunk_ids"].append(f"{source_path.stem}-{int(chunk['chunk_index']):05d}")
		entry["chunk_count"] += 1

	ordered_chapters: list[dict[str, Any]] = []
	for order, chapter in enumerate(chapter_map, start=1):
		entry = chapter_map[chapter]
		entry["index_order"] = order
		entry["pages"].sort()
		ordered_chapters.append(entry)

	return {
		"source": str(source_path),
		"file_name": source_path.name,
		"chapter_count": len(ordered_chapters),
		"chapters": ordered_chapters,
	}


def write_chapter_index(index_path: Path, chapter_index: dict[str, Any]) -> None:
	index_path.write_text(
		json.dumps(chapter_index, ensure_ascii=False, indent=2),
		encoding="utf-8",
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
			config.get("collection", f"{source_path.stem}-chapter-index")
		)
		persist_path = (script_dir / "db" / "data.db").resolve()
		chapter_index_path = (script_dir / "db" / "chapter-index.json").resolve()

		pages = extract_pdf_pages(source_path)
		segments = build_segments(pages)
		chunks = chunk_segments(segments, chunk_size, chunk_overlap)
		embeddings = fetch_embeddings(
			[str(chunk["text"]) for chunk in chunks],
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
		write_chapter_index(chapter_index_path, build_chapter_index(source_path, chunks))

		print(f"Config file: {config_path}")
		print(f"Source PDF: {source_path}")
		print(f"Collection: {collection_name}")
		print(f"Segments: {len(segments)}")
		print(f"Chunks: {len(chunks)}")
		print(f"Database path: {persist_path}")
		print(f"Chapter index path: {chapter_index_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())