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
	"config-metadata.txt",
)

CHINESE_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
TRAILING_PAGE_REF_PATTERN = re.compile(r"\s+\d+[A-Z]?(?:-\d+)+$")
PART_PATTERN = re.compile(r"^第\s*[0-9A-Za-z一二三四五六七八九十百零]+\s*部(?:\s*[-—]{1,2}\s*.+)?$")
DIVISION_PATTERN = re.compile(r"^第\s*[0-9A-Za-z一二三四五六七八九十百零]+\s*分部(?:\s*[-—]{1,2}\s*.+)?$")
SCHEDULE_PATTERN = re.compile(r"^附表\s*\d+")
SECTION_PATTERN = re.compile(r"^\d+[A-Z]?\.\s*第.+")
BRACKET_TITLE_PATTERN = re.compile(r"^[\[(（【].+[\])）】]$")

NOISE_PATTERNS = (
	re.compile(r"^經核證文本$"),
	re.compile(r"^最後更新日期$"),
	re.compile(r"^版本日期$"),
	re.compile(r"^條次\s*頁次$"),
	re.compile(r"^條文\s*Provision\s*頁數\s*Page number$"),
	re.compile(r"^《個人資料\s*\(\s*私隱\s*\)\s*條例》.*$"),
	re.compile(r"^第\s*486\s*章.*$"),
	re.compile(r"^尚未實施的條文/修訂.*$"),
	re.compile(r"^附註\s*[—-]+$"),
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
		return "pdf-metadata"
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


def normalize_line(value: str) -> str:
	value = value.replace("\u3000", " ")
	value = re.sub(r"\s+", " ", value)
	if contains_chinese(value):
		first_ascii_match = re.search(r"[A-Za-z]", value)
		first_chinese_match = CHINESE_PATTERN.search(value)
		if first_ascii_match and first_chinese_match:
			if first_ascii_match.start() == 0:
				return ""
			if first_ascii_match.start() > first_chinese_match.start():
				value = value[:first_ascii_match.start()].rstrip(" -—")
	value = TRAILING_PAGE_REF_PATTERN.sub("", value)
	return value.strip()


def contains_chinese(value: str) -> bool:
	return bool(CHINESE_PATTERN.search(value))


def should_skip_line(line: str) -> bool:
	if not line:
		return True
	if not contains_chinese(line):
		return True
	if "Personal Data (Privacy) Ordinance" in line:
		return True
	if "Provision" in line or "Page number" in line:
		return True
	if "Last updated date" in line or "Version date" in line:
		return True
	if "https://www.elegislation.gov.hk" in line:
		return True
	for pattern in NOISE_PATTERNS:
		if pattern.match(line):
			return True
	return False


def clean_page_lines(page_text: str) -> list[str]:
	cleaned_lines: list[str] = []
	for raw_line in page_text.splitlines():
		line = normalize_line(raw_line)
		if should_skip_line(line):
			continue
		cleaned_lines.append(line)
	return cleaned_lines


def is_heading_line(line: str) -> bool:
	return bool(
		PART_PATTERN.match(line)
		or DIVISION_PATTERN.match(line)
		or SCHEDULE_PATTERN.match(line)
		or SECTION_PATTERN.match(line)
	)


def next_title_line(lines: list[str], index: int) -> str | None:
	for offset in (1, 2):
		next_index = index + offset
		if next_index >= len(lines):
			return None
		candidate = lines[next_index]
		if BRACKET_TITLE_PATTERN.match(candidate):
			continue
		if is_heading_line(candidate):
			return None
		if len(candidate) <= 40:
			return candidate
		return None
	return None


def combine_heading(base: str, title: str | None) -> str:
	if not title:
		return base
	if title in base:
		return base
	return f"{base} {title}"


def update_chapter_context(
	lines: list[str],
	index: int,
	context: dict[str, str | None],
) -> dict[str, str | None]:
	line = lines[index]
	updated = dict(context)

	if SCHEDULE_PATTERN.match(line):
		updated["schedule"] = combine_heading(line, next_title_line(lines, index))
		updated["part"] = None
		updated["division"] = None
		updated["section"] = None
		return updated

	if PART_PATTERN.match(line):
		updated["part"] = combine_heading(line, next_title_line(lines, index))
		updated["schedule"] = None
		updated["division"] = None
		updated["section"] = None
		return updated

	if DIVISION_PATTERN.match(line):
		updated["division"] = combine_heading(line, next_title_line(lines, index))
		updated["section"] = None
		return updated

	if SECTION_PATTERN.match(line):
		updated["section"] = line

	return updated


def format_chapter_label(context: dict[str, str | None]) -> str:
	parts: list[str] = []
	if context.get("schedule"):
		parts.append(str(context["schedule"]))
	else:
		if context.get("part"):
			parts.append(str(context["part"]))
		if context.get("division"):
			parts.append(str(context["division"]))
	if context.get("section"):
		parts.append(str(context["section"]))
	if not parts:
		return "未分類章節"
	return " > ".join(parts)


def build_segments(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
	segments: list[dict[str, Any]] = []
	context: dict[str, str | None] = {
		"schedule": None,
		"part": None,
		"division": None,
		"section": None,
	}
	seen_heading = False

	for page_number, page_text in pages:
		lines = clean_page_lines(page_text)
		for index, line in enumerate(lines):
			if is_heading_line(line):
				seen_heading = True
			if not seen_heading:
				continue
			context = update_chapter_context(lines, index, context)
			chapter = format_chapter_label(context)
			if not segments or segments[-1]["page"] != page_number or segments[-1]["chapter"] != chapter:
				segments.append(
					{
						"page": page_number,
						"chapter": chapter,
						"lines": [line],
					}
				)
			else:
				segments[-1]["lines"].append(line)

	for segment in segments:
		segment["text"] = "\n".join(segment.pop("lines"))

	if not segments:
		raise ValueError("Unable to extract usable Chinese text from the PDF.")

	return segments


def chunk_segments(
	segments: list[dict[str, Any]],
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

	for segment in segments:
		segment_text = str(segment["text"]).strip()
		if not segment_text:
			continue

		start = 0
		while start < len(segment_text):
			end = min(start + chunk_size, len(segment_text))
			body = segment_text[start:end].strip()
			if body:
				chapter = str(segment["chapter"])
				prefix = f"[法規章節] {chapter}\n"
				chunks.append(
					{
						"page": int(segment["page"]),
						"chapter": chapter,
						"chunk_index": chunk_index,
						"start_char": start,
						"end_char": end,
						"text": prefix + body,
					}
				)
				chunk_index += 1

			if end >= len(segment_text):
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
		return [list(vector) for vector in raw_embeddings]
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
	documents = [str(chunk["text"]) for chunk in chunks]
	metadatas = [
		{
			"source": str(source_path),
			"file_name": source_path.name,
			"page": int(chunk["page"]),
			"chapter": str(chunk["chapter"]),
			"chunk_index": int(chunk["chunk_index"]),
			"start_char": int(chunk["start_char"]),
			"end_char": int(chunk["end_char"]),
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
			config.get("collection", f"{source_path.stem}-metadata")
		)
		persist_path = (script_dir / "db" / "data.db").resolve()

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

		print(f"Config file: {config_path.name}")
		print(f"Source PDF: {source_path}")
		print(f"Collection: {collection_name}")
		print(f"Segments: {len(segments)}")
		print(f"Chunks: {len(chunks)}")
		print(f"Database path: {persist_path}")
		print("Status: completed")
		return 0
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())