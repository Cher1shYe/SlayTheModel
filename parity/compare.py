#!/usr/bin/env python3
"""Bounded native-vs-C++ diagnostic replay, not a trained game policy.

Default: compare the current host decision against a newly initialized simulator;
do not create a native run or submit actions. --new-run explicitly creates a native
run. --steps plus --diagnostic-policy/--actions explicitly enables test decisions.
Every unsupported decision or mismatch stops the replay. The default compares the
shared public model facts and tensors; --observation-schema subset explicitly
selects the smaller historical contract. Neither proves whole-game equivalence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parity.semantic import (
    ActionKey, ParityMismatch, SimulatorCatalog, UNCOVERED_STATE,
    UnsupportedSemanticState, compare_public_state, native_request_for_candidate,
    pair_actions, project_native, project_simulator,
)
from parity.action_contract import native_navigation_request


class HostError(RuntimeError):
    def __init__(self, message: str, *, details: dict | None = None, last_state: dict | None = None):
        super().__init__(message)
        self.details = details or {}
        self.last_state = last_state


class SimulatorError(RuntimeError):
    """A legal mapped action failed; stop without retrying either engine."""


def decode_json_response(body: bytes, content_type: str, url: str) -> dict:
    text = body.decode("utf-8", errors="replace")
    if "application/json" not in content_type.lower():
        raise HostError(f"{url}: expected application/json, got {content_type!r}",
                        details={"response_excerpt": text[:2000]})
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HostError(f"{url}: malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                        details={"response_excerpt": text[:2000]}) from exc
    if not isinstance(parsed, dict):
        raise HostError(f"{url}: expected a JSON object, got {type(parsed).__name__}",
                        details={"response_excerpt": text[:2000]})
    return parsed


class HostClient:
    def __init__(self, url: str, timeout: float = 10):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("host URL must be an http(s) origin, without query or fragment")
        if parsed.path not in ("", "/") or parsed.username or parsed.password:
            raise ValueError("host URL must be an origin, without path or embedded credentials")
        self.url, self.timeout = url.rstrip("/"), timeout
        self.opener = build_opener(ProxyHandler({}))

    def request(self, method: str, path: str, payload=None, *, timeout: float | None = None) -> dict:
        url = self.url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                body = response.read(32 * 1024 * 1024 + 1)
                if len(body) > 32 * 1024 * 1024:
                    raise HostError(f"{url}: response exceeds 32 MiB limit")
                return decode_json_response(body, response.headers.get("Content-Type", ""), url)
        except HTTPError as exc:
            body = exc.read(2000).decode("utf-8", errors="replace")
            # Preserve HTTP status/body even if the server returned HTML or an
            # empty body. Never turn a transport failure into a JSON exception.
            raise HostError(f"{method} {url}: HTTP {exc.code} {exc.reason}; {body}",
                            details={"http_status": exc.code, "response_excerpt": body}) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise HostError(f"{method} {url}: transport failure: {exc}") from exc

    def state(self, *, timeout: float | None = None) -> dict:
        return self.request("GET", "/api/state", timeout=timeout)


def wait_for_ready(client, *, after_revision: int | None = None, timeout: float = 30,
                   poll_interval: float = 0.15, stable_reads: int = 2,
                   monotonic=time.monotonic, wait=time.sleep) -> dict:
    """Wait for a changed, stable ready frame, bounded by a monotonic deadline.

    No fixed post-action delay is assumed. Poll waits occur only while the
    readiness/revision/stability predicate is false. Failed POSTs are never retried.
    """
    if timeout <= 0 or poll_interval <= 0 or stable_reads < 2:
        raise ValueError("positive timeout/poll interval and at least two stable reads are required")
    deadline = monotonic() + timeout
    signature, equal_reads, latest = None, 0, None
    while monotonic() < deadline:
        try:
            latest = client.state(timeout=max(0.001, min(client.timeout, deadline - monotonic())))
        except HostError as exc:
            if exc.last_state is None:
                exc.last_state = latest
            raise
        if latest.get("error") or latest.get("status") == "error":
            raise HostError(f"native host reported an error: {latest.get('error') or latest}", last_state=latest)
        revision = latest.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise HostError("native state is missing an integer revision", last_state=latest)
        changed = after_revision is None or revision > after_revision
        if latest.get("status") in ("ready", "finished") and changed:
            current = json.dumps(latest, sort_keys=True, separators=(",", ":"))
            equal_reads = equal_reads + 1 if current == signature else 1
            signature = current
            if equal_reads >= stable_reads:
                return latest
        else:
            signature, equal_reads = None, 0
        remaining = deadline - monotonic()
        if remaining > 0:
            wait(min(poll_interval, remaining))
    raise HostError(f"native ready-state timeout after {timeout:g}s (required revision > {after_revision}); "
                    f"last status={None if latest is None else latest.get('status')!r}, "
                    f"revision={None if latest is None else latest.get('revision')!r}", last_state=latest)


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tuple_tree(value):
    return tuple(_tuple_tree(x) for x in value) if isinstance(value, list) else value


def load_actions(path: Path) -> list[ActionKey]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("--actions must contain a JSON array of {kind, args} semantic actions")
    actions = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or set(entry) != {"kind", "args"} or not isinstance(entry["kind"], str) or not isinstance(entry["args"], list):
            raise ValueError(f"--actions entry {i} must contain only string kind and array args")
        actions.append(ActionKey(entry["kind"], _tuple_tree(entry["args"])))
    return actions


PROGRESS_FIELDS = (
    "apply_discovery_order", "number_of_runs", "neow_unlocked", "orobas_unlocked", "darv_unlocked",
    "underdocks_unlocked", "underdocks_discovered", "aeonglass_seen", "wongo_points", "revealed_epochs",
    "event1_epoch_revealed", "event2_epoch_revealed", "event3_epoch_revealed", "seen_encounters",
)
FRESH_UNLOCKED_HOST = dict(apply_discovery_order=True, number_of_runs=0,
                           underdocks_unlocked=True, underdocks_discovered=False,
                           aeonglass_seen=False, seen_encounters=[])


def initialize_simulator(sim, seed: str, ascension: int, profile: str = "default", context: dict | None = None):
    """Explicit progress context; never tune it from the observed choices/results."""
    rc = sim.RunContext()
    first_act = -1
    if profile == "default" and context is None:
        rc.init_seed(seed, ascension)
    else:
        progress = sim.NativeProgressContext()
        overrides = dict(FRESH_UNLOCKED_HOST) if profile == "fresh-unlocked-host" else {}
        if context is not None:
            unknown = context.keys() - set(PROGRESS_FIELDS) - {"first_act"}
            if unknown:
                raise ValueError(f"unknown simulator progress fields: {sorted(unknown)}")
            first_act = context.get("first_act", -1)
            overrides.update({k: v for k, v in context.items() if k != "first_act"})
        for key, value in overrides.items():
            setattr(progress, key, value)
        rc.init_seed_with_context(seed, ascension, first_act, progress)
    effective = {key: getattr(rc.native_progress, key) for key in PROGRESS_FIELDS}
    return rc, {"profile": profile, "first_act": first_act, "effective_progress": effective}


def compare_decision(frame: dict, rc, sim, catalog, *, observation_schema="subset") -> tuple[dict, object, object]:
    result = {"unsupported": {}, "public_state_diff": {}, "action_diff": {},
              "coverage": "partial public-state/action contract; not full observation or rule parity",
              "uncovered_state": UNCOVERED_STATE}
    native, simulator = None, None
    for source, project in (("native", lambda: project_native(frame)),
                             ("simulator", lambda: project_simulator(rc, sim, catalog))):
        try:
            projection = project()
            result[source + "_projection"] = asdict(projection)
            if source == "native":
                native = projection
            else:
                simulator = projection
        except UnsupportedSemanticState as exc:
            result["unsupported"][source] = str(exc)
    if native is not None and simulator is not None:
        result["public_state_diff"] = compare_public_state(simulator, native)
        left, right = simulator.by_key(), native.by_key()
        if left.keys() != right.keys():
            result["action_diff"] = {
                "simulator_only": [asdict(k) for k in sorted(left.keys() - right.keys(), key=repr)],
                "native_only": [asdict(k) for k in sorted(right.keys() - left.keys(), key=repr)],
            }
        try:
            pair_actions(simulator, native)
        except ParityMismatch as exc:
            result["action_mismatch"] = str(exc)
        if observation_schema == "spire.public/1":
            # Both backends pass through the very same policy encoder. Compare
            # facts first, then every tensor and mask the network consumes.
            train_root = str(Path(__file__).resolve().parents[1] / "train")
            if train_root not in sys.path: sys.path.insert(0, train_root)
            from spire_rl import public_obs
            import numpy as np
            states = {}
            for source, make in (("native", lambda: public_obs.from_native(frame, native)),
                                 ("simulator", lambda: public_obs.from_simulator(rc, simulator))):
                try: states[source] = make()
                except public_obs.ObservationCoverageError as exc:
                    result["unsupported"][source + "_observation"] = str(exc)
            result["coverage"] = "spire.public/1 public facts, encoded policy inputs and legal action semantics; not complete game-rule parity"
            result["uncovered_state"] = ["Future transitions and full-game rule equivalence require replay verification."]
            if len(states) == 2:
                result["model_state_diff"] = public_obs.differences(states["simulator"], states["native"])
                result["model_input_diff"] = {}
                encoded = {}
                for source, state in states.items():
                    try: encoded[source] = public_obs.encode(state)
                    except public_obs.ObservationCoverageError as exc:
                        result["unsupported"][source + "_encoder"] = str(exc)
                if len(encoded) == 2:
                    for key, left_value in vars(encoded["simulator"]).items():
                        right_value = getattr(encoded["native"], key)
                        if isinstance(left_value, np.ndarray):
                            if left_value.shape != right_value.shape:
                                result["model_input_diff"][key] = {"simulator_shape": left_value.shape, "native_shape": right_value.shape}
                            elif not np.array_equal(left_value, right_value):
                                indices = np.argwhere(left_value != right_value)
                                result["model_input_diff"][key] = {
                                    "count": len(indices), "first_differences": [
                                        {"index": index.tolist(), "simulator": left_value[tuple(index)].item(),
                                         "native": right_value[tuple(index)].item()} for index in indices[:64]]}
                        elif left_value != right_value:
                            result["model_input_diff"][key] = {"simulator": left_value, "native": right_value}
    result["status"] = ("unsupported" if result["unsupported"] else
                        "mismatch" if result["public_state_diff"] or result["action_diff"] or result.get("action_mismatch")
                            or result.get("model_state_diff") or result.get("model_input_diff") else
                        "aligned_model_interface" if observation_schema == "spire.public/1" else "aligned_supported_subset")
    return result, simulator, native


def verify_native_identity(frame: dict, expected: dict) -> None:
    """Check replay provenance separately from policy-visible observations."""
    actual = frame.get("runIdentity")
    if not isinstance(actual, dict):
        raise HostError("native runIdentity is missing; cannot verify replay context", last_state=frame)
    differences = {key: {"expected": value, "native": actual.get(key)}
                   for key, value in expected.items() if actual.get(key) != value}
    if differences:
        raise HostError("native run identity mismatch", details={"identity_diff": differences}, last_state=frame)


def run_comparison(client, rc, sim, report_dir: Path, *, steps: int = 0,
                   actions: list[ActionKey] | None = None, diagnostic_policy: str | None = None,
                   new_run: dict | None = None, ready_timeout: float = 30,
                   poll_interval: float = 0.15, expected_identity: dict | None = None,
                   observation_schema="subset") -> dict:
    """Save before any mutation and stop at the first unproven correspondence."""
    catalog = SimulatorCatalog.from_repo()
    summary = {"status": "starting", "actions_submitted": 0, "aligned_decisions": 0,
               "report_dir": str(report_dir), "trained_policy": False}
    decision_index = 0
    try:
        after_revision = None
        if new_run is not None:
            previous = client.state()
            after_revision = previous.get("revision")
            response = client.request("POST", "/api/new", new_run)
            _write(report_dir / "new-run-response.json", response)
        frame = wait_for_ready(client, after_revision=after_revision, timeout=ready_timeout,
                               poll_interval=poll_interval)
        while True:
            prefix = f"decision-{decision_index:04d}"
            navigation = native_navigation_request(frame)
            if navigation is not None:
                if expected_identity is not None:
                    verify_native_identity(frame, expected_identity)
                _write(report_dir / (prefix + "-transport-native.json"), frame)
                transport = {"kind": "open_shop", "request": navigation, "game_decision": False}
                _write(report_dir / (prefix + "-transport.json"), transport)
                transport["response"] = client.request("POST", "/api/action", navigation)
                _write(report_dir / (prefix + "-transport.json"), transport)
                frame = wait_for_ready(client, after_revision=navigation["revision"], timeout=ready_timeout,
                                       poll_interval=poll_interval)
                if native_navigation_request(frame) is not None:
                    raise UnsupportedSemanticState("native shop navigation did not open its public inventory")
            _write(report_dir / (prefix + "-native.json"), frame)
            if expected_identity is not None:
                verify_native_identity(frame, expected_identity)
            result, simulator, native = compare_decision(frame, rc, sim, catalog, observation_schema=observation_schema)
            result["decision_index"] = decision_index
            path = report_dir / (prefix + "-comparison.json")
            _write(path, result)
            if result["status"] not in ("aligned_supported_subset", "aligned_model_interface"):
                summary.update(status=result["status"], stopped_at=decision_index)
                break
            summary["aligned_decisions"] += 1
            if decision_index >= steps:
                summary.update(status="limit_reached", stopped_at=decision_index)
                break
            if actions is not None:
                if decision_index >= len(actions):
                    summary.update(status="sequence_exhausted", stopped_at=decision_index)
                    break
                desired = actions[decision_index]
                matches = [i for i, a in enumerate(simulator.actions) if a.key == desired]
                if len(matches) != 1:
                    raise UnsupportedSemanticState(f"explicit action {desired!r} is not uniquely legal at decision {decision_index}")
                candidate_index = matches[0]
            elif diagnostic_policy == "first-legal":
                candidate_index = 0
            else:
                raise UnsupportedSemanticState("advancing needs --actions or --diagnostic-policy first-legal")
            request = native_request_for_candidate(simulator, native, candidate_index)
            selected = simulator.actions[candidate_index]
            result.update(selected_action=asdict(selected), native_request=request,
                          selection="explicit_sequence" if actions is not None else "diagnostic_first_legal")
            _write(path, result)  # Concrete request recorded before the POST.
            response = client.request("POST", "/api/action", request)
            result["native_action_response"] = response
            _write(path, result)
            summary["actions_submitted"] += 1
            try:
                accepted = (rc.step_combat(*selected.handle) if simulator.screen in ("combat", "combat_selection")
                            else rc.step(*selected.handle))
            except (RuntimeError, ValueError) as exc:
                raise SimulatorError(f"simulator failed action {selected.key!r}: {exc}") from exc
            if not accepted:
                raise SimulatorError(f"simulator refused a mapped legal action: {selected.key!r}")
            decision_index += 1
            frame = wait_for_ready(client, after_revision=native.revision, timeout=ready_timeout,
                                   poll_interval=poll_interval)
    except (HostError, SimulatorError, UnsupportedSemanticState, ParityMismatch) as exc:
        summary.update(status="host_error" if isinstance(exc, HostError) else
                       "simulator_error" if isinstance(exc, SimulatorError) else "unsupported",
                       stopped_at=decision_index, error=str(exc))
        if isinstance(exc, HostError):
            summary["error_details"] = exc.details
            if exc.last_state is not None:
                _write(report_dir / f"decision-{decision_index:04d}-native-error.json", exc.last_state)
    finally:
        _write(report_dir / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:18779")
    parser.add_argument("--seed", required=True)
    parser.add_argument("--ascension", type=int, choices=range(11), default=10)
    parser.add_argument("--new-run", action="store_true", help="explicitly create a native run before comparing")
    parser.add_argument("--steps", type=int, default=None, help="maximum diagnostic actions; default 0 or explicit sequence length")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--diagnostic-policy", choices=["first-legal"], help="deterministic interface testing only; not a trained strategy")
    selection.add_argument("--actions", type=Path, help="JSON array of exact {kind,args} action keys from comparison reports")
    parser.add_argument("--sim-profile", choices=["default", "fresh-unlocked-host"], default="default",
                        help="explicit simulator progress; fresh-unlocked-host assumes a new native save with all epochs revealed")
    parser.add_argument("--sim-context", type=Path, help="JSON NativeProgressContext overrides; recorded in the report")
    parser.add_argument("--sim-dir", type=Path, default=Path(__file__).resolve().parent.parent / "sim/build")
    parser.add_argument("--observation-schema", choices=["spire.public/1", "subset"], default="spire.public/1",
                        help="full common model inputs by default; subset is for explicitly limited historical diagnostics")
    parser.add_argument("--reports", type=Path, default=Path(__file__).resolve().parent / "stage/reports")
    parser.add_argument("--ready-timeout", type=float, default=30)
    parser.add_argument("--http-timeout", type=float, default=10)
    parser.add_argument("--poll-interval", type=float, default=0.15)
    args = parser.parse_args(argv)
    try:
        actions = load_actions(args.actions) if args.actions else None
        steps = args.steps if args.steps is not None else len(actions) if actions is not None else 0
        if steps < 0 or steps > 10000:
            raise ValueError("--steps must be between 0 and 10000")
        if steps and actions is None and args.diagnostic_policy is None:
            raise ValueError("--steps requires --actions or --diagnostic-policy")
        if min(args.ready_timeout, args.http_timeout, args.poll_interval) <= 0:
            raise ValueError("timeouts and poll interval must be positive")
        context = json.loads(args.sim_context.read_text()) if args.sim_context else None
        if context is not None and not isinstance(context, dict):
            raise ValueError("--sim-context must be a JSON object")
        client = HostClient(args.url, args.http_timeout)
        sys.path.insert(0, str(args.sim_dir.resolve()))
        sim = importlib.import_module("sts2_sim")
        rc, initialization = initialize_simulator(sim, args.seed, args.ascension, args.sim_profile, context)
    except (ValueError, OSError, ImportError) as exc:
        parser.error(str(exc))
    label = re.sub(r"[^A-Za-z0-9_-]", "_", args.seed)[:40] or "seed"
    report_dir = args.reports.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + label + "-" + uuid.uuid4().hex[:6])
    report_dir.mkdir(parents=True, exist_ok=False)
    _write(report_dir / "config.json", {
        "url": args.url, "seed": args.seed, "ascension": args.ascension,
        "new_native_run": args.new_run, "steps": steps, "diagnostic_policy": args.diagnostic_policy,
        "actions": None if actions is None else [asdict(a) for a in actions],
        "simulator_initialization": initialization, "ruleset": sim.ENGINE_RULESET_ID,
        "target_dll_sha256": sim.TARGET_GAME_DLL_SHA256, "trained_policy": False,
        "observation_schema": args.observation_schema,
        "coverage": "full public model interface" if args.observation_schema == "spire.public/1" else "semantic.py supported public-state subset only",
        "uncovered_state": UNCOVERED_STATE if args.observation_schema == "subset" else ["Full-game transition equivalence remains unproven."],
    })
    summary = run_comparison(client, rc, sim, report_dir, steps=steps, actions=actions,
        diagnostic_policy=args.diagnostic_policy,
        observation_schema=args.observation_schema,
        new_run={"character": "IRONCLAD", "ascension": args.ascension, "seed": args.seed, "language": "eng"} if args.new_run else None,
        ready_timeout=args.ready_timeout, poll_interval=args.poll_interval,
        expected_identity={"seed": args.seed.upper().replace("O", "0").replace("I", "1").strip(),
                           "character": "IRONCLAD", "ascension": args.ascension,
                           "gameVersion": "v0.111.0", "gameCommit": "41cef1ea",
                           "gameDllSha256": sim.TARGET_GAME_DLL_SHA256})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return {"limit_reached": 0, "sequence_exhausted": 0, "mismatch": 2, "unsupported": 3,
            "host_error": 4, "simulator_error": 5}[summary["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
