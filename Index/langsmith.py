from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PREFERRED_PYTHON = (SCRIPT_DIR.parent / ".venv" / "Scripts" / "python.exe").resolve()


def ensure_preferred_python() -> None:
	if not PREFERRED_PYTHON.exists():
		return

	current_python = Path(sys.executable).resolve()
	if current_python == PREFERRED_PYTHON:
		return

	if os.environ.get("SINOCLASS_LANGSMITH_REEXEC") == "1":
		return

	env = os.environ.copy()
	env["SINOCLASS_LANGSMITH_REEXEC"] = "1"
	completed = subprocess.run([str(PREFERRED_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
	raise SystemExit(completed.returncode)


ensure_preferred_python()


def import_langsmith_sdk() -> tuple[Any, Any, Any, str | None]:
	removed_entries: list[tuple[int, str]] = []
	for index in range(len(sys.path) - 1, -1, -1):
		entry = sys.path[index]
		resolved_entry = str(Path(entry or ".").resolve())
		if resolved_entry == str(SCRIPT_DIR):
			removed_entries.append((index, entry))
			sys.path.pop(index)

	try:
		from langsmith import Client as imported_client
		from langsmith.run_helpers import trace as imported_trace
		from langsmith.run_helpers import tracing_context as imported_tracing_context

		return imported_client, imported_trace, imported_tracing_context, None
	except ImportError as exc:
		return None, None, None, str(exc)
	finally:
		for index, entry in sorted(removed_entries, key=lambda item: item[0]):
			sys.path.insert(index, entry)


Client, trace, tracing_context, LANGSMITH_IMPORT_ERROR = import_langsmith_sdk()


DEFAULT_CONFIG_CANDIDATES = (
	"config-langsmith.txt",
	"../Index/config-langsmith.txt",
)


@dataclass
class LogEvent:
	timestamp: str
	stream: str
	message: str


@dataclass
class ExecutionResult:
	command: list[str]
	cwd: str
	started_at: str
	finished_at: str
	duration_seconds: float
	return_code: int
	stdout: str
	stderr: str
	events: list[LogEvent]


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


def resolve_relative_path(base_dir: Path, raw_path: str | None, default_path: str) -> Path:
	path = Path(raw_path or default_path)
	if not path.is_absolute():
		path = (base_dir / path).resolve()
	return path


def resolve_output_path(config_path: Path, config: dict[str, str]) -> Path:
	return resolve_relative_path(config_path.parent, config.get("output"), "log-langsmith.txt")


def resolve_python_executable(script_dir: Path) -> str:
	if PREFERRED_PYTHON.exists():
		return str(PREFERRED_PYTHON)
	return sys.executable


def resolve_command(config_path: Path, config: dict[str, str]) -> list[str]:
	raw_command = config.get("execute")
	if not raw_command:
		raise ValueError("Missing required config key: execute")

	parts = shlex.split(raw_command, posix=False)
	if not parts:
		raise ValueError("Config key execute must not be empty")

	command_path = Path(parts[0])
	if not command_path.is_absolute():
		command_path = (config_path.parent / command_path).resolve()

	if not command_path.exists():
		raise FileNotFoundError(f"Execute target not found: {command_path}")

	resolved_first = str(command_path)
	if command_path.suffix.lower() == ".py":
		return [resolve_python_executable(config_path.parent), resolved_first, *parts[1:]]

	return [resolved_first, *parts[1:]]


def utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def read_stream(stream_name: str, pipe: Any, queue: Queue[LogEvent]) -> None:
	try:
		for raw_line in iter(pipe.readline, ""):
			queue.put(
				LogEvent(
					timestamp=utc_now_iso(),
					stream=stream_name,
					message=raw_line.rstrip("\r\n"),
				)
			)
	finally:
		pipe.close()


def run_monitored_process(command: list[str], cwd: Path) -> ExecutionResult:
	started_monotonic = time.perf_counter()
	started_at = utc_now_iso()
	environment = os.environ.copy()
	environment.setdefault("PYTHONUTF8", "1")
	environment.setdefault("PYTHONIOENCODING", "utf-8")
	process = subprocess.Popen(
		command,
		cwd=str(cwd),
		env=environment,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
		bufsize=1,
	)

	event_queue: Queue[LogEvent] = Queue()
	threads = [
		threading.Thread(
			target=read_stream,
			args=("stdout", process.stdout, event_queue),
			daemon=True,
		),
		threading.Thread(
			target=read_stream,
			args=("stderr", process.stderr, event_queue),
			daemon=True,
		),
	]
	for thread in threads:
		thread.start()

	events: list[LogEvent] = []
	stdout_lines: list[str] = []
	stderr_lines: list[str] = []

	while True:
		try:
			event = event_queue.get(timeout=0.1)
			events.append(event)
			if event.stream == "stdout":
				stdout_lines.append(event.message)
			else:
				stderr_lines.append(event.message)
			print(f"[{event.stream}] {event.message}")
		except Empty:
			if process.poll() is not None and all(not thread.is_alive() for thread in threads):
				break

	for thread in threads:
		thread.join(timeout=1)

	while True:
		try:
			event = event_queue.get_nowait()
			events.append(event)
			if event.stream == "stdout":
				stdout_lines.append(event.message)
			else:
				stderr_lines.append(event.message)
			print(f"[{event.stream}] {event.message}")
		except Empty:
			break

	finished_at = utc_now_iso()
	duration_seconds = round(time.perf_counter() - started_monotonic, 3)
	return ExecutionResult(
		command=command,
		cwd=str(cwd),
		started_at=started_at,
		finished_at=finished_at,
		duration_seconds=duration_seconds,
		return_code=process.wait(),
		stdout="\n".join(stdout_lines),
		stderr="\n".join(stderr_lines),
		events=events,
	)


def build_langsmith_context(config: dict[str, str], command: list[str], output_path: Path) -> dict[str, Any]:
	has_api_key = bool(os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"))
	project_name = config.get("project", f"sino-class-{Path(command[1] if len(command) > 1 else command[0]).stem}")
	context: dict[str, Any] = {
		"available": trace is not None and tracing_context is not None and Client is not None,
		"has_api_key": has_api_key,
		"project_name": project_name,
		"tracing_enabled": False,
		"tracing_mode": "disabled",
		"client_error": None,
		"import_error": LANGSMITH_IMPORT_ERROR,
		"run_id": None,
		"trace_id": None,
		"session_name": None,
		"output_path": str(output_path),
	}

	if not context["available"]:
		return context

	context["tracing_mode"] = "langsmith" if has_api_key else "local"
	context["tracing_enabled"] = True

	if has_api_key:
		try:
			context["client"] = Client()
		except Exception as exc:
			context["client"] = None
			context["client_error"] = str(exc)
			context["tracing_mode"] = "local"
	else:
		context["client"] = None

	return context


def run_with_langsmith(
	config: dict[str, str],
	command: list[str],
	cwd: Path,
	config_path: Path,
	output_path: Path,
) -> tuple[ExecutionResult, dict[str, Any]]:
	langsmith_context = build_langsmith_context(config, command, output_path)
	metadata = {
		"config_path": str(config_path),
		"execute": command,
		"cwd": str(cwd),
		"output_path": str(output_path),
	}

	if not langsmith_context["available"]:
		return run_monitored_process(command, cwd), langsmith_context

	client = langsmith_context.get("client")
	with tracing_context(
		project_name=langsmith_context["project_name"],
		tags=["sino-class", "subprocess"],
		metadata=metadata,
		client=client,
		enabled=langsmith_context["tracing_mode"],
	):
		with trace(
			name=f"execute:{Path(command[1] if len(command) > 1 else command[0]).name}",
			run_type="tool",
			inputs={"command": command, "cwd": str(cwd)},
			project_name=langsmith_context["project_name"],
			tags=["wrapper", "subprocess"],
			metadata=metadata,
			client=client,
		) as run_tree:
			result = run_monitored_process(command, cwd)
			run_tree.add_metadata(
				{
					"return_code": result.return_code,
					"duration_seconds": result.duration_seconds,
					"stdout_lines": len(result.stdout.splitlines()) if result.stdout else 0,
					"stderr_lines": len(result.stderr.splitlines()) if result.stderr else 0,
				}
			)
			run_tree.add_outputs(
				{
					"return_code": result.return_code,
					"stdout": result.stdout,
					"stderr": result.stderr,
				}
			)
			langsmith_context["run_id"] = str(getattr(run_tree, "id", "")) or None
			langsmith_context["trace_id"] = str(getattr(run_tree, "trace_id", "")) or None
			langsmith_context["session_name"] = getattr(run_tree, "session_name", None)

	if client is not None:
		try:
			client.flush()
		except Exception as exc:
			langsmith_context["client_error"] = str(exc)

	langsmith_context.pop("client", None)
	return result, langsmith_context


def format_events(events: list[LogEvent]) -> str:
	if not events:
		return "(no output)"
	return "\n".join(f"[{event.timestamp}] [{event.stream}] {event.message}" for event in events)


def write_log(
	output_path: Path,
	config_path: Path,
	result: ExecutionResult,
	langsmith_context: dict[str, Any],
) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	serializable_context = {key: value for key, value in langsmith_context.items() if key != "client"}
	content = (
		"LangSmith subprocess monitor\n\n"
		f"config_path={config_path}\n"
		f"cwd={result.cwd}\n"
		f"command={json.dumps(result.command, ensure_ascii=False)}\n"
		f"started_at={result.started_at}\n"
		f"finished_at={result.finished_at}\n"
		f"duration_seconds={result.duration_seconds}\n"
		f"return_code={result.return_code}\n\n"
		"[langsmith]\n"
		f"{json.dumps(serializable_context, ensure_ascii=False, indent=2)}\n\n"
		"[timeline]\n"
		f"{format_events(result.events)}\n\n"
		"[stdout]\n"
		f"{result.stdout or '(empty)'}\n\n"
		"[stderr]\n"
		f"{result.stderr or '(empty)'}\n\n"
		"[json]\n"
		f"{json.dumps({'execution': asdict(result), 'langsmith': serializable_context}, ensure_ascii=False, indent=2)}\n"
	)
	output_path.write_text(content, encoding="utf-8")


def main() -> int:
	result: ExecutionResult | None = None
	langsmith_context: dict[str, Any] = {}
	try:
		script_dir = Path(__file__).resolve().parent
		config_path = resolve_config_path(script_dir)
		config = parse_config(config_path)
		output_path = resolve_output_path(config_path, config)
		command = resolve_command(config_path, config)
		result, langsmith_context = run_with_langsmith(
			config=config,
			command=command,
			cwd=config_path.parent,
			config_path=config_path,
			output_path=output_path,
		)
		write_log(output_path, config_path, result, langsmith_context)
		print(f"Log written to: {output_path}")
		return result.return_code
	except Exception as exc:
		fallback_output = output_path if "output_path" in locals() else (Path(__file__).resolve().parent / "log-langsmith.txt")
		payload = {
			"error": str(exc),
			"langsmith": {key: value for key, value in langsmith_context.items() if key != "client"},
		}
		fallback_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
		print(f"Error: {exc}", file=sys.stderr)
		print(f"Failure log written to: {fallback_output}")
		return 1


if __name__ == "__main__":
	raise SystemExit(main())