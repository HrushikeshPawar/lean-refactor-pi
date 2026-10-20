"""Child Pi RPC framing. Stdout splits on LF only; stderr stays outside this reader."""

from __future__ import annotations

import json
from codecs import getincrementaldecoder

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


def prompt_line(command_id: str, task: str) -> bytes:
    record = {"type": "prompt", "id": command_id, "message": task, "tools": list(WORKER_TOOLS)}
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
