"""Child Pi RPC framing. Stdout splits on LF only; stderr stays outside this reader."""

from __future__ import annotations

import json
from codecs import getincrementaldecoder
from pathlib import Path

WORKER_TOOLS = ("compile", "goal", "search", "read", "scratch")


class FrameReader:
    """One JSON value per LF-terminated record. U+2028 and U+2029 stay inside strings."""

    def __init__(self) -> None:
        self._decoder = getincrementaldecoder("utf-8")()
        self._pending = ""

    def feed(self, chunk: bytes) -> list[dict]:
        if not isinstance(chunk, bytes):
            raise TypeError("chunk")
        self._pending += self._decoder.decode(chunk)
        records = []
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("rpc record")
            records.append(record)
        return records


def cancel_lines(command_id: str) -> bytes:
    """Drop queued prompts, then abort the live turn. Exit is a separate process event."""
    records = (
        {"type": "abort", "id": command_id, "queued": True},
        {"type": "abort", "id": command_id},
    )
    return b"".join(
        (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode() for record in records
    )


def prompt_line(command_id: str, task: str, anchor: dict) -> bytes:
    """Pi 1.3.0 prompt has no tools field. The allowlist is the process launch, not this record."""
    message = task + "\n\n" + json.dumps({"anchor": anchor}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record = {"type": "prompt", "id": command_id, "message": message}
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def worker_launch(
    directory,
    *,
    run_id: str,
    worker_actor_id: str,
    worker_session_id: str,
    job_id: str,
    activation_id: str,
    anchor: dict,
    model: str = "deepseek-v4.1-flash",
) -> dict:
    """Fresh RPC launch. The adapter merges env overrides over os.environ to retain provider auth."""
    from arena.models import load, pi_json, pi_model, provider

    config = load()
    model_config = config["models"][model]
    run_config = json.loads((directory / "run-config.json").read_text())
    theorem = run_config.get("theorem")
    if not isinstance(theorem, str) or not theorem.strip():
        raise ValueError("worker launch requires a saved theorem")
    root = Path(__file__).resolve().parents[1]
    session_dir = directory / "sessions" / worker_session_id
    tools = ",".join(WORKER_TOOLS)
    return {
        "argv": [
            "pi",
            "--mode",
            "rpc",
            "--offline",
            "--approve",
            "--no-builtin-tools",
            "--no-context-files",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--extension",
            str(root / "packages/arena-pi/extensions/arena.ts"),
            "--tools",
            tools,
            "--model",
            pi_model(model, config),
            "--session-dir",
            str(session_dir),
            "--session-id",
            worker_session_id,
        ],
        "env": {
            "ARENA_RUN_ID": run_id,
            "ARENA_ACTOR_ID": worker_actor_id,
            "ARENA_SESSION_ID": worker_session_id,
            "ARENA_JOB_ID": job_id,
            "ARENA_ACTIVATION_ID": activation_id,
            "ARENA_RUN_DIR": str(directory),
            "ARENA_WORKER_THEOREM": theorem,
            "ARENA_MODEL": model,
            "ARENA_PI_MODEL_ID": model_config.get("id", model),
            "ARENA_MODELS_JSON": pi_json(config),
            "ARENA_REQUEST_OUTPUT_TOKENS": str(model_config["request_output_tokens"]),
            "ARENA_BUDGET_REQUIRED": "1",
            "ARENA_AUTOCONTINUE": "0",
            "ARENA_BUDGET_REPORT_PATH": str(directory / "cost.json"),
            "ARENA_ANCHOR": json.dumps(anchor, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        },
        "model": model,
        "provider": provider(model, config),
        "session_dir": str(session_dir),
        "actor_id": worker_actor_id,
        "tools": list(WORKER_TOOLS),
    }
