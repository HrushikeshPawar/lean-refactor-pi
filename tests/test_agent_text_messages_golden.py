"""Golden checks for model-facing text captured before ticket 05b moves it."""

import contextlib
import copy
import json
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import campaign, context, engine, merges, routes
from arena import profile as profiler
from tests.pi_support import PI_AVAILABLE, FakeRun
from tests.slow import slow

ROOT = Path(__file__).resolve().parents[1]


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class ToolDefinitionsGoldenTests(unittest.TestCase):
    def test_registered_tool_definitions_are_the_five_public_tools(self):
        run = FakeRun([{"text": "done"}]).run()
        try:
            assert run.result is not None
            self.assertEqual(run.result.returncode, 0, run.result.stderr + run.result.stdout[-2_000:])
            definitions = run.requests[0]["tool_definitions"]
            self.assertEqual({tool["name"] for tool in definitions}, {"compile", "goal", "search", "read", "finish"})
            schemas = {tool["name"]: tool["parameters"] for tool in definitions}
            self.assertTrue(all(schema["type"] == "object" for schema in schemas.values()))
        finally:
            run.cleanup()


CASES: dict[str, Callable[[], object]] = {}
CALLS: dict[str, str] = {}


def case(case_id: str, call: str):
    """Register a function that reproduces one moved message and returns what the code produced."""

    def register(func: Callable[[], object]) -> Callable[[], object]:
        CASES[case_id] = func
        CALLS[case_id] = call
        return func

    return register


def raised(func, *args, **kwargs) -> str:
    """The message of the exception `func` raises; a return value is reported so a lost raise shows up."""
    try:
        result = func(*args, **kwargs)
    except Exception as error:
        return str(error)
    return f"<no exception, returned {result!r}>"


CID = "a" * 64
STATEMENT = "theorem t : True"
ROW = {
    "name": "nm",
    "source": "s",
    "statement": STATEMENT,
    "src": STATEMENT + " := trivial",
    "file_path": "A.lean",
    "start_line": 1,
    "end_line": 1,
    "proof_length": 5,
    "version_info": [{"v1": "c1"}],
}
INIT = {"kind": "init", "theorem": "nm", "versions": [["v", "c"]]}
CANDIDATE = {"kind": "candidate", "candidate_id": CID, "parents": [], "origin": "model"}
PASSING = {"ok": True, "mode": "fast", "tokens": None, "heartbeat": None, "compat": {"v": {"passed": True}}}
FAILING = {"ok": True, "mode": "fast", "tokens": None, "heartbeat": None, "compat": {"v": {"passed": False}}}


class _Run:
    """A throwaway run directory with the Lean-facing collaborators of `arena.campaign` patched out."""

    def __init__(self, versions=(("v", "c"),), real_validate=False, compiled=None):
        self.versions = list(versions)
        self.real_validate = real_validate
        self.compiled = compiled or PASSING

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.directory = self.root / "run"
        patches = {
            "run_dir": lambda run_id: self.root / run_id,
            "problem": lambda name: ROW,
            "versions": lambda row: list(self.versions),
            "_check_breaker": lambda directory: None,
            "lean_lock": lambda *args, **kwargs: contextlib.nullcontext(),
            "_evaluate": lambda *args, **kwargs: copy.deepcopy(self.compiled),
            "_compile_probe": lambda *args, **kwargs: copy.deepcopy(self.compiled),
            "_has_hole": lambda row, proof: False,
        }
        if not self.real_validate:
            patches["validate_proof"] = lambda *args, **kwargs: 1
        for name, replacement in patches.items():
            self.stack.enter_context(patch.object(campaign, name, replacement))
        self.stack.enter_context(patch.object(campaign.lean_health, "tripped", lambda directory: False))
        self.directory.mkdir()
        return self

    def __exit__(self, *exc):
        self.stack.close()

    def seed(self, *events: dict) -> None:
        for event in events:
            campaign._append(self.directory, event)

    def text(self, value: str) -> str:
        return value.replace(str(self.root), "<tmp>")


# --- arena/campaign.py -------------------------------------------------------------------------


@case("errors.invalid_run_id", "campaign.run_dir with a run id that has a slash")
def _():
    return raised(campaign.run_dir, "bad/id")


@case("errors.ambiguous_symbol", "str(campaign.AmbiguousDeclaration('foo', ['A.foo', 'B.foo']))")
def _():
    return str(campaign.AmbiguousDeclaration("foo", ["A.foo", "B.foo"]))


@case("errors.pinned_project_path@git_source", "campaign._git_source with a path that leaves the project")
def _():
    return raised(campaign._git_source, Path("."), "c", "../x.lean")


@case("errors.pinned_project_path@canonical", "campaign._canonical_source_path with an absolute path")
def _():
    return raised(campaign._canonical_source_path, ROW, "/abs.lean")


def _source_range(read, **kwargs):
    with (
        patch.object(campaign, "problem", lambda name: ROW),
        patch.object(campaign, "measure_version", lambda row: ("v1", "c1")),
        patch.object(campaign, "workspace", lambda row, version, commit: Path(".")),
        patch.object(campaign, "_source_target", lambda project, commit, path: (project, commit, path)),
        patch.object(campaign, "_git_source", read),
    ):
        return raised(campaign._source_range, "nm", "A.lean", kwargs.get("first"), kwargs.get("last"))


def _missing(*args):
    raise subprocess.CalledProcessError(1, "git")


@case("errors.project_file_missing", "campaign._source_range when git cannot show the file")
def _():
    return _source_range(_missing)


@case("errors.source_line_range", "campaign._source_range with first beyond the file")
def _():
    return _source_range(lambda *args: "a\nb\nc", first=5)


@case("errors.source_range_order", "campaign._source_range with last before first")
def _():
    return _source_range(lambda *args: "a\nb\nc", first=3, last=1)


@case("errors.source_commit_mismatch", "campaign._split_source_handle with another commit in the handle")
def _():
    return raised(campaign._split_source_handle, "src@abcdef1234567890:foo.lean", "0123456789abcdef")


@case("errors.library_path", "campaign._stdlib_source with a path that leaves the library")
def _():
    return raised(campaign._stdlib_source, "4.0.0", ".lean-stdlib/lean/../x.lean")


@case("errors.library_file_missing", "campaign._stdlib_source for a toolchain that is not installed")
def _():
    return raised(campaign._stdlib_source, "0.0.0-none", ".lean-stdlib/lean/Nope.lean")


@case("errors.source_path_missing", "campaign._source_target for a project that does not exist")
def _():
    return raised(campaign._source_target, Path("/nonexistent-project"), "c", "a.lean")


@case("errors.source_search_failed", "campaign._declaration_hits with a git grep that fails silently")
def _():
    failed = subprocess.CompletedProcess([], 2, stdout="", stderr="")
    with patch.object(campaign.subprocess, "run", lambda *args, **kwargs: failed):
        return raised(campaign._declaration_hits, [(Path("."), "pin", "n")], ["foo"])


@case("errors.invalid_declaration@resolve", "campaign._resolve_declaration_source with a malformed name")
def _():
    return raised(campaign._resolve_declaration_source, "nm", "1bad")


def _resolve(module, scanned=None):
    with (
        patch.object(campaign, "problem", lambda name: ROW),
        patch.object(campaign, "measure_version", lambda row: ("v1", "c1")),
        patch.object(campaign, "workspace", lambda row, version, commit: Path(".")),
        patch.object(campaign, "_roots", lambda project, commit: [(project, commit, "n")]),
        patch.object(campaign, "_module_file", lambda roots, module: None),
        patch.object(campaign, "_scan", lambda root, pin, path: scanned),
    ):
        return raised(campaign._resolve_declaration_source, "nm", "foo", module)


@case("errors.module_missing", "campaign._resolve_declaration_source for a module no root holds")
def _():
    return _resolve("Foo.Bar")


@case("errors.declaration_missing", "campaign._resolve_declaration_source when the file has no such declaration")
def _():
    return _resolve("this file", scanned=([], []))


def _():
    def not_found(*args):
        raise ValueError("not found")

    with (
        patch.object(campaign, "_source_hint", lambda name, symbol: (symbol, None, None)),
        patch.object(campaign, "_resolve_declaration_source", not_found),
        patch.object(campaign, "_indexed_entry", lambda name, symbol: None),
    ):
        return campaign._source_declaration("nm", "foo")["hint"]


def _():
    built = {"text": "text", "head": 0, "path": Path("."), "start_line": 1}
    with (
        patch.object(campaign, "problem", lambda name: ROW),
        patch.object(campaign, "measure_version", lambda row: ("v1", "c1")),
        patch.object(engine, "candidate_file", lambda *args, **kwargs: built),
        patch.object(engine, "run_lean", lambda *args, **kwargs: None),
    ):
        return raised(campaign._declaration_in_lean, "nm", "foo")


def _():
    built = {"text": "text", "head": 0, "path": Path("."), "start_line": 1}
    with (
        patch.object(campaign, "problem", lambda name: ROW),
        patch.object(campaign, "measure_version", lambda row: ("v1", "c1")),
        patch.object(engine, "candidate_file", lambda *args, **kwargs: built),
        patch.object(engine, "run_lean", lambda *args, **kwargs: (0, "")),
    ):
        return campaign._declaration_in_lean("nm", "foo")["hint"]


def _():
    with patch.object(campaign.lean_health, "tripped", lambda directory: True):
        return raised(campaign._refuse_if_tripped, Path("."))


@case("errors.run_exists", "campaign.init on a run directory that already holds a ledger")
def _():
    with _Run() as run:
        run.seed(INIT)
        return run.text(raised(campaign.init, "nm", "run"))


@case("candidate.original_reference", "campaign.init on a fresh run, reading the reference candidate event")
def _():
    with _Run() as run:
        run.directory.rmdir()

        def copy_tracked(project, shadow):
            shadow.mkdir(parents=True)

        (run.root / "project" / ".lake").mkdir(parents=True)
        with (
            patch.object(campaign, "workspace", lambda row, version, commit: run.root / "project"),
            patch.object(campaign, "packet", lambda name: "packet"),
            patch.object(campaign, "_copy_tracked", copy_tracked),
            patch.object(campaign, "materialize", lambda *args: {}),
        ):
            campaign.init("nm", "run")
        events = campaign.events(run.directory)
        return next(event["hypothesis"] for event in events if event["kind"] == "candidate")


@case("errors.unknown_candidate", "campaign.resolve_candidate_ref for a number beyond the candidates")
def _():
    return raised(campaign.resolve_candidate_ref, [CANDIDATE], "#7")


@case("errors.unknown_probe", "campaign.resolve_probe_ref with no probes")
def _():
    return raised(campaign.resolve_probe_ref, [], "p3")


@case("errors.probe_parent_missing", "campaign.resolve_parent_ref for a probe with no parent")
def _():
    return raised(campaign.resolve_parent_ref, [{"kind": "probe", "proof_id": "x"}], "p1")


def _advisory_rows(score):
    rows = [{"id": "ref", "n": 1, "origin": "reference", "evaluated": True, "parents": [], "score": None}]
    rows.append({"id": "root", "n": 2, "origin": "model", "evaluated": True, "parents": ["ref"], "score": score})
    rows.extend(
        {"id": f"m{n}", "n": n, "origin": "model", "evaluated": True, "parents": ["root"], "score": score}
        for n in range(3, 7)
    )
    return rows


@case("state.advisory@scored", "campaign._advisory over four stalled descendants of a scored node")
def _():
    return campaign._advisory(_advisory_rows(10.5))


@case("state.advisory@unscored", "campaign._advisory over four stalled descendants of an unscored node")
def _():
    return campaign._advisory(_advisory_rows(None))


@case("errors.cold_session_unavailable", "campaign._model_view of a compile that fell back to a cold run")
def _():
    lean = {"path": "cold-fallback", "reason": "busy"}
    view = campaign._model_view({"compat": {"v": {"passed": True, "lean": lean}}})
    return view["compat"]["v"]["lean"]


@case("errors.evaluation_mode", "campaign.record_evaluation with an unknown mode")
def _():
    return raised(campaign.record_evaluation, "nm", "run", "p", "bogus")


@case("errors.run_theorem_mismatch", "campaign.record_evaluation against a ledger for another theorem")
def _():
    with _Run() as run:
        run.seed({"kind": "init", "theorem": "other"})
        return raised(campaign.record_evaluation, "nm", "run", STATEMENT + " := trivial", "fast")


@case("errors.source_versions_changed", "campaign.record_evaluation when the pinned versions moved")
def _():
    with _Run(versions=(("w", "d"),)) as run:
        run.seed(INIT)
        return raised(campaign.record_evaluation, "nm", "run", STATEMENT + " := trivial", "fast")


@case("errors.parent_ignored@evaluation", "campaign.record_evaluation with a parent that does not exist")
def _():
    with _Run() as run:
        run.seed(INIT)
        return campaign.record_evaluation("nm", "run", STATEMENT + " := trivial", "fast", parents=["#9"])["notes"]


@case("errors.evaluation_reference", "campaign.evaluate_request with nothing to evaluate")
def _():
    return raised(campaign.evaluate_request, "nm", "run")


@case("errors.evaluation_proof_missing", "campaign.evaluate_request for a candidate whose proof file is empty")
def _():
    with _Run() as run:
        run.seed(INIT, CANDIDATE)
        (run.directory / "proofs").mkdir()
        (run.directory / "proofs" / f"{CID}.lean").write_text("")
        return raised(campaign.evaluate_request, "nm", "run", candidate_ref="#1")


@case("errors.probe_forbidden", "campaign.evaluate_request with a proof containing sorry")
def _():
    with _Run(real_validate=True) as run:
        run.seed(INIT)
        return raised(campaign.evaluate_request, "nm", "run", STATEMENT + " := by sorry")


@case("check.queued", "campaign._full_check_status for a primary pass with two versions")
def _():
    history = [
        {"kind": "init", "theorem": "nm", "versions": [["v", "c"], ["w", "d"]]},
        CANDIDATE,
        {"kind": "evaluation", "candidate_id": CID, "key": "k", "mode": "fast", "result": PASSING},
    ]
    return campaign._full_check_status(history, CID)


@case("errors.parent_ignored@probe", "campaign.probe with a parent that does not exist")
def _():
    with _Run(compiled=FAILING) as run:
        run.seed(INIT)
        return campaign.probe("nm", "run", STATEMENT + " := by simp", parent="#9")["notes"]


@case("probe.complete_candidate", "campaign.probe of a complete draft that compiles")
def _():
    with _Run() as run:
        run.seed(INIT)
        return campaign.probe("nm", "run", STATEMENT + " := by simp")["notes"]


@case("errors.draft_missing", "campaign.normalize_draft with a blank draft")
def _():
    return raised(campaign.normalize_draft, "nm", "  ")


@case("errors.draft_limit", "campaign.probe_batch with no drafts")
def _():
    return raised(campaign.probe_batch, "nm", "run", [])


def _merge_hypotheses():
    calls = []

    def record(*args, **kwargs):
        calls.append(args[5])
        return {"candidate_id": "x", "node_number": 3, "compat": {"v": {"passed": True}}}

    nodes = [
        {"id": name, "status": "full", "decision": None, "parents": [], "origin": "model", "proof": name}
        for name in ("a", "b")
    ]
    merged = {"left_edits": [], "right_edits": [], "text": "T", "reason": None}
    with (
        _Run(),
        patch.object(campaign, "common_base", lambda *args: {"base": "a", "reason": None}),
        patch.object(campaign, "merge_text", lambda *args: merged),
        patch.object(campaign, "record_evaluation", record),
    ):
        campaign.merge_once("run", {"theorem": "nm", "nodes": nodes, "merge_checks": []})
    return calls


@case("merge.hypothesis@fast", "campaign.merge_once, the hypothesis of the fast evaluation")
def _():
    return _merge_hypotheses()[0]


@case("merge.hypothesis@full", "campaign.merge_once, the hypothesis of the full evaluation")
def _():
    return _merge_hypotheses()[1]


@case("check.could_not_run", "campaign._check_text for a check that never ran")
def _():
    return campaign._check_text(3, {"ok": False, "error": "boom"}, 2)


@case("check.passed", "campaign._check_text for a check that passed every version")
def _():
    return campaign._check_text(3, {"compat": {"v": {"passed": True}}, "local_proxy": 42.5}, 1)


@case("check.failed", "campaign._check_text for a check that failed one version")
def _():
    compat = {"v": {"passed": True}, "w": {"passed": False, "error_headlines": ["bad line"]}}
    return campaign._check_text(3, {"compat": compat}, 2)


@case("errors.run_uninitialized@state", "campaign.state on an empty ledger")
def _():
    with _Run():
        return raised(campaign.state, "run")


@case("errors.cold_verification_paused", "campaign.cold_verify while the Lean breaker is tripped")
def _():
    with _Run(), patch.object(campaign.lean_health, "tripped", lambda directory: True):
        return campaign.cold_verify("run", {"id": "x", "heartbeats": 1})["error"]


def _submission(session, cold=None, candidate=True):
    lean = {"path": "session" if session else "cold"}
    result = {"ok": True, "tokens": 10, "heartbeat": 100, "compat": {"v": {"passed": True, "lean": lean}}}
    result["metrics"] = {"proxy": 50.0}
    with _Run() as run:
        run.seed(INIT, CANDIDATE)
        if candidate:
            run.seed({"kind": "evaluation", "candidate_id": CID, "key": "k", "mode": "full", "result": result})
        (run.directory / "proofs").mkdir()
        (run.directory / "proofs" / f"{CID}.lean").write_text("proof")
        with patch.object(campaign, "cold_verify", lambda run_id, row: cold):
            return campaign.submission("run")


@case("state.no_candidate_passed", "campaign.submission when no candidate passed every version")
def _():
    return _submission(False, candidate=False)["reason"]


@case("state.no_candidate_cold_passed", "campaign.submission when the only candidate fails the cold compile")
def _():
    return _submission(True, cold={"confirmed": False, "recorded_heartbeats": 100})["reason"]


@case("state.cold_compile_without_session", "campaign.submission for a candidate that never used a session")
def _():
    return _submission(False)["verified_by"]


@case("errors.run_uninitialized@frontier", "campaign.frontier on an empty ledger")
def _():
    with _Run():
        return raised(campaign.frontier, "run")


# --- arena/engine.py ---------------------------------------------------------------------------


@case("errors.proof_utility_parse", "engine._proof_length when the pinned utility cannot parse")
def _():
    with patch.object(engine.vendor, "checker", lambda: SimpleNamespace(_proof_length=lambda proof: 10**9)):
        return raised(engine._proof_length, "theorem x : True := trivial")


@case("errors.statement_modified_first", "engine.validate_proof with an edited statement")
def _():
    return raised(engine.validate_proof, ROW, "theorem t : Truf := trivial")


@case("errors.statement_modified_suffix", "engine.validate_proof with no `:=` after the statement")
def _():
    return raised(engine.validate_proof, ROW, STATEMENT + " x")


@case("errors.extra_command", "engine.validate_proof with a second top-level command")
def _():
    return raised(engine.validate_proof, ROW, STATEMENT + " := by\n  simp\nend")


@case("errors.forbidden_construct", "engine.validate_proof with sorry")
def _():
    return raised(engine.validate_proof, ROW, STATEMENT + " := by sorry")


@case("errors.measure_version_missing", "engine.measure_version with an override naming an unlisted version")
def _():
    with tempfile.TemporaryDirectory() as directory:
        overrides = Path(directory) / "measure.json"
        overrides.write_text(json.dumps({"nm": "9.9"}))
        with patch.object(engine, "_MEASURE_OVERRIDES", overrides):
            return raised(engine.measure_version, ROW)


@case("errors.pinned_statement_missing", "engine.locate_source with a source that lacks the statement")
def _():
    return raised(engine.locate_source, "abc", "zzz", "v1")


@case("errors.standalone_row", "engine.candidate_file for a standalone row with no header")
def _():
    row = {"name": "nm", "statement": "", "header": ""}
    with patch.object(engine, "workspace", lambda *args: Path(".")):
        return raised(engine.candidate_file, row, "p", "v", "c")


@case("errors.theorem_location_missing", "engine.candidate_file for a file row with no line span")
def _():
    row = {"name": "nm", "statement": "s", "header": "h", "file_path": "A.lean"}
    with patch.object(engine, "workspace", lambda *args: Path(".")):
        return raised(engine.candidate_file, row, "p", "v", "c")


@case("evaluate.diagnostic_headline", "engine.structure_diagnostics for one Lean error inside the target")
def _():
    return engine.structure_diagnostics("A.lean:2:3: error: boom\nmore", "l1\nl2\nl3\n", 1, 3)["error_headlines"]


@case("errors.lean_timeout", "engine.compile_version when Lean times out")
def _():
    built = {"text": "t", "offset": 0, "head": 0, "start_line": 1, "end_line": 1, "path": Path(".")}
    with (
        patch.object(engine, "candidate_file", lambda *args, **kwargs: built),
        patch.object(engine, "lean_timeout", lambda: 7),
        patch.object(engine, "run_lean", lambda *args, **kwargs: None),
        patch.object(engine, "last_lean_run", lambda: {}),
    ):
        return engine.compile_version(ROW, "p", "v", "c")["error"]


@case("errors.mode_invalid", "engine.evaluate with an unknown mode")
def _():
    return raised(engine.evaluate, "nm", "p", "bogus")


@case("errors.toolchains_missing", "engine.evaluate for a row that lists no toolchain")
def _():
    with (
        patch.object(engine, "problem", lambda name: ROW),
        patch.object(engine, "validate_proof", lambda *args, **kwargs: 5),
        patch.object(engine, "versions", lambda row: []),
    ):
        return raised(engine.evaluate, "nm", "p")


@case("evaluate.calibration_pending", "engine.evaluate of one proof with the compile and scoring patched out")
def _():
    from arena import scoring

    with (
        patch.object(engine, "problem", lambda name: ROW),
        patch.object(engine, "validate_proof", lambda *args, **kwargs: 5),
        patch.object(engine, "versions", lambda row: [("v1", "c1")]),
        patch.object(engine, "measure_version", lambda row: ("v1", "c1")),
        patch.object(engine, "compile_version", lambda *args, **kwargs: {"passed": True, "heartbeats": 3}),
        patch.object(scoring, "metrics", lambda *args, **kwargs: {}),
    ):
        return engine.evaluate("nm", "p")["calibration"]


# --- arena/profile.py --------------------------------------------------------------------------


@case("profile.hotspot_label", "profile.summarize of an empty profile, the hotspot label")
def _():
    return profiler.summarize([], [], measured=None, instrumented=None)["hotspot_label"]


@case("profile.unit", "profile.summarize of an empty profile, the unit")
def _():
    return profiler.summarize([], [], measured=None, instrumented=None)["unit"]


def _instrument(ran, parsed=None):
    built = {"text": "t", "head": 0, "start_line": 1, "path": Path(".")}
    with (
        patch.object(profiler, "candidate_file", lambda *args, **kwargs: built),
        patch.object(profiler, "preamble", lambda depth: ""),
        patch.object(profiler, "run_lean", lambda *args, **kwargs: ran),
        patch.object(profiler, "parse_profile", lambda *args: parsed),
    ):
        return raised(profiler._instrumented, ROW, "p", "v", "c", 1)


@case("errors.profile_timeout", "profile._instrumented when Lean times out")
def _():
    return _instrument(None)


@case("errors.profile_compile_failed", "profile._instrumented when the instrumented file does not compile")
def _():
    return _instrument((1, "x\nerror: bad\n"), ([], None))


def _profile(instrumented, compiled=None, measured=None, proof="by simp"):
    result = {"granularity": 0}
    with (
        patch.object(profiler, "problem", lambda name: ROW),
        patch.object(profiler, "measure_version", lambda row: ("v", "c")),
        patch.object(profiler, "_instrumented", instrumented),
        patch.object(profiler, "compile_version", lambda *args, **kwargs: compiled),
        patch.object(profiler, "_proof_length", lambda *args: 3),
        patch.object(profiler, "_line_token_counts", lambda *args: {}),
        patch.object(profiler, "exchange_rates", lambda *args: {"reference_tokens": 1, "reference_heartbeats": 1}),
        patch.object(profiler, "versions", lambda row: [("v", "c")]),
        patch.object(profiler, "summarize", lambda *args: result),
    ):
        return profiler.profile("nm", proof, measured)


def _always_boom(*args):
    raise ValueError("boom")


@case("errors.profile_requires_complete", "profile.profile of a draft containing sorry")
def _():
    return raised(_profile, _always_boom, proof="by sorry")


@case("errors.profile_proof_compile", "profile.profile of a proof that does not compile")
def _():
    return raised(_profile, _always_boom, {"passed": False, "error_headlines": ["h1"]})


@case("errors.profile_instrumentation_failed", "profile.profile of a proof that compiles but cannot be instrumented")
def _():
    return raised(_profile, _always_boom, {"passed": True})


@case("profile.degraded", "profile.profile when only the outermost tactics can be instrumented")
def _():
    outcomes = iter([ValueError("boom"), ([], 5, {"text": "x", "start_line": 1}, "")])

    def instrumented(*args):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _profile(instrumented, measured=5)["note"]


@case("profile.floor_method", "profile.heartbeat_floor for a row with no cached floor")
def _():
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.object(profiler, "ROOT", Path(directory)),
        patch.object(profiler, "problem", lambda name: ROW),
        patch.object(profiler, "measure_version", lambda row: ("v", "c")),
        patch.object(profiler, "compile_version", lambda *args, **kwargs: {"heartbeats": 3}),
    ):
        return profiler.heartbeat_floor("nm")["method"]


# --- arena/routes.py ---------------------------------------------------------------------------

ROUTE = {"route": "r1", "attempts": 1, "original": False, "best_proxy": None, "best_candidate": None}


@case("routes.original@best", "routes.routes_text for the original's route with a best proxy and one goal state")
def _():
    row = {**ROUTE, "original": True, "best_proxy": 61.2, "best_candidate": "#3", "depth": 1}
    return routes.routes_text([row])


@case("routes.credited@none", "routes.routes_text for a credited route with no scored proof and two goal states")
def _():
    return routes.routes_text([{**ROUTE, "attempts": 3, "credited": True, "depth": 2}])


@case("routes.not_credited", "routes.routes_text for a route that opened but earned no credit")
def _():
    return routes.routes_text([{**ROUTE, "credited": False, "depth": 0}])


@case("routes.plain", "routes.routes_text for a route with no credit or depth fields")
def _():
    return routes.routes_text([ROUTE])


@case("routes.none", "routes.routes_text for an empty table")
def _():
    return routes.routes_text([])


# --- arena/merges.py ---------------------------------------------------------------------------


@case("merge.none_checked", "merges.merge_text with no merge rows")
def _():
    return merges.merge_text([])


@case("merge.summary", "merges.merge_text with one merge that beat neither parent")
def _():
    return merges.merge_text([{"beats_parents": False, "candidate": "#4", "parents": ["#2", "#3"], "proxy": 40.0}])


@case("merge.entry", "merges.merge_text with one merge that beat both parents")
def _():
    return merges.merge_text([{"beats_parents": True, "candidate": "#4", "parents": ["#2", "#3"], "proxy": 70.5}])


# --- arena/context.py --------------------------------------------------------------------------


@case("errors.lean_context_timeout", "context.lean_context when Lean times out")
def _():
    built = {"text": "t", "head": 0, "start_line": 1, "path": Path(".")}
    with tempfile.TemporaryDirectory() as directory:
        lean_file = Path(directory) / "context.lean"
        lean_file.write_text("x")
        with (
            patch.object(context, "problem", lambda name: ROW),
            patch.object(context, "measure_version", lambda row: ("v1", "c1")),
            patch.object(context, "LEAN_FILE", lean_file),
            patch.object(context, "_cache", lambda *args: Path(directory) / "none.json"),
            patch.object(context, "is_standalone", lambda row: True),
            patch.object(context, "candidate_file", lambda *args, **kwargs: built),
            patch.object(context, "run_lean", lambda *args, **kwargs: None),
        ):
            return context.lean_context("nm")["error"]


@case("packet.profile_span", "context._profile_section with one hotspot that has one tactic span")
def _():
    span = {"proof_line": 2, "end_proof_line": 3, "file_line": 12, "end_file_line": 13, "depth": 1}
    hotspot = {**span, "tactic_spans": [span], "self_hb": 5, "tokens": 4, "baseline_cost_points": 1.5}
    profile = {
        "granularity": "tactic",
        "entries": [],
        "top_self_cost": [],
        "hotspots": [hotspot],
        "token_attribution_available": True,
        "measured_total": 10,
        "profiled_total": 8,
    }
    return "\n".join(context._profile_section(profile))


@case("packet.budget_certification_failed", "context._fit with a section that cannot shrink below the limit")
def _():
    return raised(context._fit, [("T", ["x" * 50])], 10)


def _render_packet(certification):
    seen = {}

    def manifest(parts, inventory):
        seen["pins"] = parts[1][1][1]
        return {}

    with contextlib.ExitStack() as stack:
        for name, replacement in {
            "problem": lambda name: ROW,
            "versions": lambda row: [("v1", "c1"), ("v2", "c2")],
            "lean_context": lambda name: {},
            "reference_profile": lambda name: {},
            "_rates": lambda *args: "rates",
            "_profile_section": lambda prof: [],
            "packet_manifest": manifest,
            "certify_manifest": lambda manifest: certification,
        }.items():
            stack.enter_context(patch.object(context, name, replacement))
        for name in ("_types_section", "_scope_section", "_goal_section", "_used_section", "_dependency_section"):
            stack.enter_context(patch.object(context, name, lambda *args: []))
        for name in ("_local_section", "_library_section", "_earlier_section", "_imports"):
            stack.enter_context(patch.object(context, name, lambda *args: []))
        message = raised(context.render_packet, "nm")
    return message, seen.get("pins")


@case("packet.pin", "context.render_packet, the line that lists the pinned toolchains")
def _():
    return _render_packet({"certified": False, "reasons": ["a"]})[1]


@case("packet.packet_not_certifiable", "context.render_packet when certification fails")
def _():
    return _render_packet({"certified": False, "reasons": ["a", "b"]})[0]


class MovedMessagesGoldenTests(unittest.TestCase):
    """Replays the model-facing text that ticket 05b moved into templates against the pre-move bytes."""

    @classmethod
    def setUpClass(cls):
        cls.entries = json.loads((ROOT / "tests/fixtures/agent_text_messages_golden.json").read_text())

    def test_every_case_has_a_golden_entry_and_the_reverse(self):
        self.assertEqual(sorted(CASES), sorted(entry["id"] for entry in self.entries))

    def test_each_moved_message_matches_the_pre_move_bytes(self):
        for entry in self.entries:
            with self.subTest(entry["id"]):
                actual = json.loads(json.dumps(CASES[entry["id"]]()))
                self.assertEqual(actual, entry["expected"])
