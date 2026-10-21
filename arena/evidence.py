"""Shared packet and cost evidence. Display budgets never replace exact profile rows."""

from __future__ import annotations

from arena.prices import fmt_hb, snippet_tokens
from arena.steps import split_steps
from arena.text import render

PAGE_SIZE = 30
HOTSPOTS_SHOWN = 1


def metric_state(value: object, *, pending: bool = False) -> str:
    """Missing, zero, pending, and a positive measurement are different facts."""
    if pending:
        return "pending"
    if value is None:
        return "missing"
    if value == 0:
        return "zero"
    return "measured"


def show_metric(value: object, *, pending: bool = False) -> str:
    state = metric_state(value, pending=pending)
    if state == "measured":
        return fmt_hb(value) if isinstance(value, (int, float)) else str(value)
    if state == "zero":
        return "0"
    return state


def _parent_step(steps, entry: dict):
    line = entry.get("proof_line")
    if not isinstance(line, int):
        return None
    return next((step for step in steps if step.first_line <= line <= step.last_line), None)


def _range(entry: dict) -> str:
    start = entry.get("proof_line")
    end = entry.get("end_proof_line") or start
    return f"{start}-{end}"


def _span_tokens(proof: str, entry: dict) -> int | None:
    """Tokens of this span alone. Callers must not add overlapping spans together."""
    start = entry.get("proof_line")
    end = entry.get("end_proof_line") or start
    lines = proof.splitlines()
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return None
    chunk = "\n".join(lines[start - 1 : end])
    if not chunk.strip():
        return None
    return snippet_tokens(chunk)


def _preview(text: str, limit: int = 60) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "… (clipped)"


def cost_evidence(
    proof: str,
    profile: dict | None,
    *,
    proof_id: str,
    total_tokens: int | None,
    published_score: object,
    versions: str | None,
    local_hb: object,
    node_label: str = "n1",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Proof totals, top-level edit ranges, nested measured spans, and a paged full tree.

    Inclusive heartbeats are not added together. Indentation is not a splice id.
    """
    pending = profile is None
    entries = list((profile or {}).get("entries") or [])
    steps = split_steps(proof) if proof else []
    structural = [
        {
            "id": step.id,
            "first_line": step.first_line,
            "last_line": step.last_line,
            "splice_target": True,
        }
        for step in steps
    ]
    nested = [entry for entry in entries if int(entry.get("depth") or 0) > 0 and entry.get("hb") is not None]
    ranked = sorted(nested, key=lambda entry: (-int(entry.get("hb") or 0), entry.get("proof_line") or 0))
    shown = ranked[:HOTSPOTS_SHOWN]
    hotspots = []
    for entry in shown:
        parent = _parent_step(steps, entry)
        hotspots.append(
            {
                "parent": parent.id if parent else "none",
                "parent_range": f"{parent.first_line}-{parent.last_line}" if parent else "missing",
                "range": _range(entry),
                "proof_id": proof_id,
                "incl_hb": show_metric(entry.get("hb"), pending=pending),
                "tokens": show_metric(_span_tokens(proof, entry)),
                "text": _preview(str(entry.get("text") or "")),
                "splice_target": False,
            }
        )
    detail = [
        {
            "range": _range(entry),
            "depth": int(entry.get("depth") or 0),
            "kind": entry.get("kind", "tactic"),
            "self_hb": show_metric(entry.get("self_hb"), pending=pending),
            "self_state": metric_state(entry.get("self_hb"), pending=pending),
            "incl_hb": show_metric(entry.get("hb"), pending=pending),
            "incl_state": metric_state(entry.get("hb"), pending=pending),
            "tokens": show_metric(_span_tokens(proof, entry)),
            "text": _preview(str(entry.get("text") or "")),
            "splice_target": False,
        }
        for entry in entries
    ]
    page = max(1, page)
    start_at = (page - 1) * page_size
    page_rows = detail[start_at : start_at + page_size]
    page_count = max(1, (len(detail) + page_size - 1) // page_size) if detail else 1
    zeros = [row for row in detail if row["self_state"] == "zero"]
    published = "missing" if published_score is None else published_score
    if pending:
        local_state = "pending"
    elif local_hb is None:
        local_state = "missing"
    else:
        local_state = metric_state(local_hb)
    return {
        "proof_id": proof_id,
        "summary": {
            "tokens": show_metric(total_tokens),
            "published_score": published,
            "local_hb": show_metric(local_hb, pending=local_state == "pending"),
            "local_state": local_state,
            "versions": versions or "missing",
        },
        "structural_ids": [row["id"] for row in structural],
        "hotspots": hotspots,
        "omitted_hotspots": len(nested) - len(shown),
        "detail": detail,
        "page": page_rows,
        "page_index": page,
        "page_count": page_count,
        "omitted_on_page": max(0, len(detail) - page * page_size),
        "zero_example": zeros[0] if zeros else None,
        "retrieval": f"read(node={node_label}, view=tree:{page + 1}) proof={proof_id}"
        if page < page_count
        else f"read(node={node_label}, view=tree) proof={proof_id}",
    }


def render_cost_overview(table: dict, evidence: dict) -> list[str]:
    """Default text: separate totals, inclusive structural rows, one nested hotspot, full-detail pointer."""
    rows = table.get("rows") or []
    show_hb = any(row.get("incl_hb") is not None for row in rows)
    lines = [render("packet/price-table").strip()] if show_hb else [render("packet/price-table.no_hb").strip()]
    for row in rows:
        values = {
            "step": row["id"],
            "lines": f"{row['first_line']}-{row['last_line']}",
            "tokens": row["tokens"],
            "text": row["text"],
        }
        if show_hb:
            values["incl_hb"] = show_metric(row.get("incl_hb"))
            lines.append(render("packet/price-table.row", **values))
        else:
            lines.append(render("packet/price-table.row_no_hb", **values))
    summary = evidence["summary"]
    lines.append(
        render(
            "packet/price-table.summary",
            tokens=summary["tokens"],
            score=summary["published_score"],
            heartbeats=summary["local_hb"],
            measurement=summary["local_state"],
            versions=summary["versions"],
        )
    )
    if show_hb:
        lines.extend(render("packet/price-table.legend").strip().splitlines())
    else:
        lines.append(render("packet/price-table.missing_hb").strip())
    lines.extend(
        render(
            "packet/price-table.hotspot",
            parent=hotspot["parent"],
            parent_range=hotspot["parent_range"],
            range=hotspot["range"],
            proof=hotspot["proof_id"],
            incl_hb=hotspot["incl_hb"],
            tokens=hotspot["tokens"],
            text=hotspot["text"],
        )
        for hotspot in evidence["hotspots"]
    )
    if evidence["omitted_hotspots"]:
        lines.append(render("packet/price-table.hotspot_omitted", count=evidence["omitted_hotspots"]))
    zero = evidence.get("zero_example")
    if zero:
        lines.append(render("packet/price-table.zero", range=zero["range"]))
    lines.append(render("packet/price-table.detail", retrieval=evidence["retrieval"]))
    return lines


def render_cost_detail(evidence: dict) -> list[str]:
    """Paged measured spans with self heartbeats. No attributed-points column, so no pts legend."""
    lines = [
        render(
            "packet/price-table.detail_head",
            page=evidence["page_index"],
            pages=evidence["page_count"],
            omitted=evidence["omitted_on_page"],
        ),
    ]
    lines.extend(
        render(
            "packet/price-table.detail_row",
            range=row["range"],
            depth=row["depth"],
            self_hb=row["self_hb"],
            incl_hb=row["incl_hb"],
            text=row["text"],
        )
        for row in evidence["page"]
    )
    return lines
