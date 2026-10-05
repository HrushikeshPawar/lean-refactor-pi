"""Export a self-contained, static snapshot of an Arena candidate graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.serve_candidate_graph import graph_payload

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tools" / "graph_viewer"


def build_snapshot(run_id: str, output: Path) -> Path:
    payload = graph_payload(run_id)
    markup = (ASSETS / "index.html").read_text()
    style = (ASSETS / "style.css").read_text()
    script = (ASSETS / "app.js").read_text()
    markup = markup.replace('<link rel="stylesheet" href="/style.css">', f"<style>{style}</style>")
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    markup = markup.replace('<script src="/app.js" defer></script>',
                            f"<script>window.GRAPH_SNAPSHOT={embedded};</script>\n<script>{script}</script>")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(markup)
    temporary.replace(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "runs" / "analysis" / f"{args.run_id}-graph.html"
    print(build_snapshot(args.run_id, output))


if __name__ == "__main__":
    main()
