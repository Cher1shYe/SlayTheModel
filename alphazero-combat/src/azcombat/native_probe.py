"""Run one isolated headless NativeWorker regression and audit its actual trajectory."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from .experiments import REGISTERED_ENCOUNTERS, checked_model, sha256
from .promotion import ASSEMBLY, EXPORT_OUT
from .reward import Outcome, TerminalResult, score_result
from .samples import read_jsonl
from .versions import REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION


def _write_new(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


def _selected_candidate_indices(choice: dict, payload: dict) -> list[int]:
    selected = payload.get("SelectedCards")
    if not isinstance(selected, list):
        raise ValueError("choice action lacks selected-card identities")
    indices = []
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get("CardId"), str) \
                or type(item.get("UpgradeLevel")) is not int \
                or type(item.get("OptionOccurrence")) is not int:
            raise ValueError("selected-card identity is malformed")
        candidates = [candidate for candidate in choice["candidates"]
                      if candidate["modelId"] == "CARD." + item["CardId"]
                      and candidate["upgradeLevel"] == item["UpgradeLevel"]]
        occurrence = item["OptionOccurrence"]
        if occurrence < 0 or occurrence >= len(candidates):
            raise ValueError("selected-card occurrence is not in the choice candidates")
        indices.append(candidates[occurrence]["combatCardIndex"])
    if len(indices) != len(set(indices)):
        raise ValueError("choice selected the same card instance twice")
    return indices


def _audit_generated_deck(provenance: dict, expected: dict) -> None:
    spec_path = expected.get("generatedScenarioPath")
    actual = provenance.get("generatedDeck")
    if spec_path is None:
        if actual is not None:
            raise ValueError("Native used an unrequested generated deck")
        return
    path = Path(spec_path).resolve(strict=True)
    digest = expected.get("generatedScenarioSha256")
    if sha256(path).lower() != str(digest).lower():
        raise ValueError("generated scenario file changed after launch")
    spec = json.loads(path.read_text(encoding="utf-8"))
    cards = spec["characterCards"]["ids"]
    empty = {"count": 0, "ids": [], "upgradeLevels": 0}
    if spec.get("schemaVersion") != 1 or spec.get("mode") != "Setup" \
            or spec.get("seed") != expected["seed"] or spec.get("encounterId") != expected["encounter"] \
            or spec.get("characterId") != "IRONCLAD" or spec.get("ascension") != 0 \
            or spec.get("includeStartingDeck") is not False \
            or spec.get("includeStartingRelics") is not True \
            or spec.get("includeAscendersBane") is not False \
            or type(cards) is not list or any(type(card) is not str for card in cards) \
            or spec["characterCards"].get("count") != len(cards) \
            or spec["characterCards"].get("upgradeLevels") != 0 \
            or any(spec.get(name) != empty for name in ("colorlessCards", "relics", "potions")):
        raise ValueError("generated deck specification is not the frozen A0 character-only setup")
    if not isinstance(actual, dict) or actual.get("specSha256", "").lower() != str(digest).lower() \
            or Path(str(actual.get("specPath", ""))).resolve() != path \
            or actual.get("characterId") != "IRONCLAD" \
            or actual.get("encounterId") != expected["encounter"] \
            or not isinstance(actual.get("resolverEncounterId"), str) \
            or not actual["resolverEncounterId"] \
            or actual.get("ascension") != 0 or actual.get("includeStartingDeck") is not False \
            or actual.get("requestedCards") != cards or actual.get("resolvedCards") != cards \
            or actual.get("actualDeck") != [{"id": card, "upgradeLevel": 0} for card in cards] \
            or not isinstance(actual.get("catalogFingerprint"), str) \
            or re.fullmatch(r"[0-9a-fA-F]{64}", actual["catalogFingerprint"]) is None:
        raise ValueError("Native generated deck provenance or actual card order differs from request")


def _enemy_roster(value: object, *, transition: int, boundary: str) -> dict[int, tuple[str, int]]:
    if not isinstance(value, list):
        raise ValueError(f"native transition {transition} {boundary} roster is missing")
    roster: dict[int, tuple[str, int]] = {}
    for enemy in value:
        if not isinstance(enemy, dict) or type(enemy.get("combatId")) is not int \
                or not 0 <= enemy["combatId"] <= 0xFFFFFFFF \
                or not isinstance(enemy.get("monsterId"), str) \
                or not enemy["monsterId"].startswith("MONSTER.") \
                or type(enemy.get("hp")) is not int or enemy["hp"] < 0:
            raise ValueError(f"native transition {transition} {boundary} roster has an invalid enemy")
        combat_id = enemy["combatId"]
        if combat_id in roster:
            raise ValueError(f"native transition {transition} {boundary} roster repeats a combatId")
        roster[combat_id] = (enemy["monsterId"], enemy["hp"])
    return roster


def _audit_reward_ledger(provenance: dict, metrics: list[dict], *,
                         final_outcome: str, final_value: float) -> dict:
    """Reconcile every Capture against independently recorded native damage events.

    An ordinary decision creates a new Capture; its following choice rows use
    that Capture and each still produces one native transition. Summed roster
    HP is diagnostic only: spawning, departure, and healing are not damage.
    The predicted reward input never supplies expected damage for this check.
    """
    denominator = provenance.get("trajectoryInitialEnemyEffectiveHp")
    transitions = provenance.get("enemyHpTransitions")
    audits = provenance.get("rewardAudits")
    if type(denominator) is not int or denominator < 1:
        raise ValueError("trajectoryInitialEnemyEffectiveHp is missing or invalid")
    if not isinstance(transitions, list) or len(transitions) != len(metrics) \
            or not isinstance(audits, list):
        raise ValueError("native reward ledger has missing transitions or Capture audits")
    prior_roster: dict[int, tuple[str, int]] | None = None
    prior_history_end: int | None = None
    identities: dict[int, str] = {}
    total_damage_events = 0
    for index, item in enumerate(transitions):
        if not isinstance(item, dict) or any(type(item.get(key)) is not int
                                             or item[key] < 0
                                             for key in ("before", "after", "damage",
                                                         "historyStartIndex", "historyEndIndex")):
            raise ValueError(f"native enemy HP transition {index} is malformed")
        history_start = item["historyStartIndex"]
        history_end = item["historyEndIndex"]
        history_reset = item.get("historyReset", False)
        capture_source = item.get("damageCaptureSource", "legacy-history-slice")
        if capture_source not in {"legacy-history-slice", "native-damage-command-v1"}:
            raise ValueError(f"native transition {index} unknown damage capture source")
        retained = capture_source == "native-damage-command-v1"
        if retained and history_reset and (index != len(transitions) - 1 or final_outcome == "unresolved"):
            raise ValueError(f"native transition {index} unexpected nonterminal history reset")
        if type(history_reset) is not bool:
            raise ValueError(f"native transition {index} historyReset is missing")
        if history_end < history_start or (prior_history_end is not None
                                           and history_start != prior_history_end):
            raise ValueError(f"native transition {index} history indices are discontinuous")
        before_roster = _enemy_roster(item.get("enemyRosterBefore"),
                                      transition=index, boundary="before")
        after_roster = _enemy_roster(item.get("enemyRosterAfter"),
                                     transition=index, boundary="after")
        if sum(hp for _, hp in before_roster.values()) != item["before"] \
                or sum(hp for _, hp in after_roster.values()) != item["after"]:
            raise ValueError(f"native transition {index} roster HP differs from diagnostic totals")
        if prior_roster is not None and before_roster != prior_roster:
            raise ValueError(f"native transition {index} enemy roster is discontinuous")
        for roster in (before_roster, after_roster):
            for combat_id, (monster_id, _) in roster.items():
                if combat_id in identities and identities[combat_id] != monster_id:
                    raise ValueError(f"native transition {index} combatId changed monster identity")
                identities[combat_id] = monster_id
        events = item.get("enemyDamageEvents")
        if not isinstance(events, list) or not retained and len(events) > history_end - history_start:
            raise ValueError(f"native transition {index} damage events exceed history slice")
        if history_reset and events and not retained:
            raise ValueError(f"native transition {index} history reset cannot carry damage events")
        credited_total = 0
        for event in events:
            if not isinstance(event, dict) or type(event.get("combatId")) is not int \
                    or not 0 <= event["combatId"] <= 0xFFFFFFFF \
                    or not isinstance(event.get("monsterId"), str) \
                    or not event["monsterId"].startswith("MONSTER.") \
                    or any(type(event.get(key)) is not int or event[key] < 0
                           for key in ("unblockedDamage", "overkillDamage", "creditedDamage")):
                raise ValueError(f"native transition {index} has a malformed damage event")
            combat_id = event["combatId"]
            monster_id = event["monsterId"]
            if combat_id in identities and identities[combat_id] != monster_id:
                raise ValueError(f"native transition {index} damage event targets a different monster")
            identities[combat_id] = monster_id
            # Native UnblockedDamage is the actual HP loss, already excluding
            # OverkillDamage. A 1-HP enemy can lose 1 HP with 8 overkill; the
            # diagnostic overkill has no ordering constraint against HP loss.
            credited = event["unblockedDamage"]
            if event["creditedDamage"] != credited:
                raise ValueError(f"native transition {index} damage event credit differs from actual HP loss")
            credited_total += credited
        expected_damage = (max(0, item["before"] - item["after"])
                           if history_reset and not retained else credited_total)
        if item["damage"] != expected_damage:
            raise ValueError(f"native transition {index} damage differs from damage events")
        total_damage_events += len(events)
        prior_roster = after_roster
        prior_history_end = history_end
    if not transitions or transitions[0]["before"] != denominator \
            or any(left["after"] != right["before"]
                   for left, right in zip(transitions, transitions[1:])):
        raise ValueError("native enemy HP transitions are discontinuous or have a wrong denominator")
    if sum(item["damage"] for item in transitions) != provenance.get("enemyDamageLost"):
        raise ValueError("total native enemy damage differs from actual transitions")
    roots = [index for index, metric in enumerate(metrics)
             if isinstance(metric, dict) and metric.get("choiceLayer") == 0]
    if not roots or roots[0] != 0 or len(roots) != len(audits):
        raise ValueError("reward audits must match ordinary decision Captures")
    entry_hp = provenance.get("entryHp")
    if type(entry_hp) is not int or entry_hp < 0:
        raise ValueError("native entry HP is missing or invalid")
    trajectory_id = None
    capture_ledger = []
    for capture_number, (start, audit) in enumerate(zip(roots, audits, strict=True), 1):
        end = roots[capture_number] if capture_number < len(roots) else len(metrics)
        if not isinstance(audit, dict):
            raise ValueError(f"capture {capture_number} reward audit is malformed")
        if metrics[start].get("parentDecision") != capture_number - 1 \
                or any(metric.get("parentDecision") != capture_number - 1
                       for metric in metrics[start:end]) \
                or [metric.get("choiceLayer") for metric in metrics[start:end]] \
                != list(range(end - start)):
            raise ValueError(f"capture {capture_number} decision/choice sequence differs")
        prefix = sum(item["damage"] for item in transitions[:start])
        branch = sum(item["damage"] for item in transitions[start:end])
        total = prefix + branch
        if audit.get("CapturedEnemyDamagePrefix") != prefix:
            raise ValueError(f"capture {capture_number} damage prefix differs from native transitions")
        if audit.get("EnemyHpLost") != branch:
            raise ValueError(f"capture {capture_number} branch damage differs from native transitions")
        if audit.get("TotalEnemyHpLost") != total:
            raise ValueError(f"capture {capture_number} total damage differs from native transitions")
        if audit.get("TrajectoryInitialEnemyHp") != denominator \
                or audit.get("EnemyHpTotal") != transitions[start]["before"]:
            raise ValueError(f"capture {capture_number} root/trajectory denominator differs")
        if audit.get("CaptureId") != capture_number or audit.get("EntryHp") != entry_hp:
            raise ValueError(f"capture {capture_number} identity or entry HP differs")
        current_id = audit.get("TrajectoryId")
        if not isinstance(current_id, str) or not current_id.startswith(provenance["seed"] + "#"):
            raise ValueError(f"capture {capture_number} trajectoryId is missing or invalid")
        if trajectory_id is None:
            trajectory_id = current_id
        elif current_id != trajectory_id:
            raise ValueError(f"capture {capture_number} trajectoryId changed")
        boundary_key = audit.get("CaptureBoundaryKey")
        if not isinstance(boundary_key, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", boundary_key) is None:
            raise ValueError(f"capture {capture_number} boundary hash is missing or invalid")
        outcome = final_outcome if capture_number == len(roots) else "unresolved"
        if audit.get("Outcome") != outcome:
            raise ValueError(f"capture {capture_number} outcome differs from actual trajectory")
        progress = min(total / denominator, 1.0)
        if type(audit.get("EnemyDamageProgress")) not in (int, float) \
                or not math.isclose(audit["EnemyDamageProgress"], progress, abs_tol=1e-9):
            raise ValueError(f"capture {capture_number} damage progress differs")
        combat_hp = audit.get("CombatFinalHp")
        settled_hp = audit.get("SettledFinalHp")
        applied_heal = audit.get("AppliedPostCombatHeal")
        if any(type(value) is not int or value < 0 for value in
               (combat_hp, settled_hp, applied_heal)) or settled_hp != combat_hp + applied_heal:
            raise ValueError(f"capture {capture_number} combat/settled HP accounting differs")
        unconditional = audit.get("UnconditionalRelicHeal")
        wounded = audit.get("WoundedRelicHeal")
        wounded_percent = audit.get("WoundedHpPercent")
        if any(type(value) is not int or value < 0 for value in
               (unconditional, wounded, wounded_percent)):
            raise ValueError(f"capture {capture_number} post-combat healing profile is invalid")
        if outcome != "win":
            if any((applied_heal, unconditional, wounded, wounded_percent)):
                raise ValueError(f"capture {capture_number} non-win applied post-combat healing")
        else:
            max_hp = audit.get("CombatFinalMaxHp")
            if type(max_hp) is not int or max_hp < 1 or settled_hp > max_hp:
                raise ValueError(f"capture {capture_number} settled HP exceeds max HP")
            heal_capacity = unconditional + (wounded if combat_hp <= max_hp * wounded_percent // 100 else 0)
            if applied_heal != min(heal_capacity, max(0, max_hp - combat_hp)):
                raise ValueError(f"capture {capture_number} post-combat heal differs from profile/cap")
        if capture_number == len(roots) and settled_hp != provenance.get("playerHp"):
            raise ValueError(f"capture {capture_number} settled HP differs from real final HP")
        # The final label uses native post-combat HP; intermediate unresolved
        # reward depends only on progress and is recomputed from live transitions.
        value_hp = provenance["playerHp"] if capture_number == len(roots) else 0
        expected_reward = score_result(TerminalResult(
            Outcome(outcome), entry_hp, value_hp, total, denominator))
        reward = audit.get("Reward")
        if type(reward) not in (int, float) or not math.isfinite(reward) \
                or not math.isclose(reward, expected_reward, abs_tol=1e-6):
            raise ValueError(f"capture {capture_number} reward differs from actual result")
        capture_ledger.append({"captureId": capture_number, "trajectoryId": trajectory_id,
                               "captureBoundaryKey": boundary_key,
                               "trajectoryInitialEnemyHp": denominator,
                               "capturedPrefix": prefix, "branchDamage": branch,
                               "totalEnemyHpLost": total, "rootEnemyHp": transitions[start]["before"],
                               "outcome": outcome, "reward": reward})
    if not math.isclose(capture_ledger[-1]["reward"], final_value, abs_tol=1e-6):
        raise ValueError("final value target differs from the last Capture reward")
    return {"captures": len(audits), "trajectoryId": trajectory_id,
            "trajectoryInitialEnemyHp": denominator,
            "totalEnemyHpLost": sum(item["damage"] for item in transitions),
            "nativeDamageEvents": total_damage_events,
            "captureLedger": capture_ledger}


def _audit_tree_parity(path: Path, raw: list[dict], metrics: list[dict]) -> dict:
    """Read the actual evaluator callback, not an outside-search re-inference."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != len(raw) or any(not line.strip() for line in lines):
        raise ValueError("actual tree evaluator parity must have one row per saved decision")
    seen: set[tuple[int, int, str]] = set()
    choice_roots = 0
    for index, (line, sample, metric) in enumerate(zip(lines, raw, metrics, strict=True)):
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("actualTreeEvaluator") is not True \
                or "outsideSearch" in row:
            raise ValueError(f"tree parity row {index} is not an actual evaluator call")
        key = (row.get("decision"), row.get("choiceLayer"), row.get("stateKey"))
        if key in seen:
            raise ValueError(f"tree parity row {index} duplicates a decision root")
        seen.add(key)
        if row.get("seed") != sample.get("seed") or key != (
                metric.get("parentDecision"), metric.get("choiceLayer"), sample.get("stateKey")):
            raise ValueError(f"tree parity row {index} seed/decision/state differs")
        observation_json = row.get("observationJson")
        if not isinstance(observation_json, str) or json.loads(observation_json) != row.get("observation") \
                or row["observation"] != sample.get("observation") \
                or sha256_bytes(observation_json.encode("utf-8")) != \
                str(row.get("observationSha256", "")).lower():
            raise ValueError(f"tree parity row {index} actual input differs from saved observation")
        ordered = [item.get("actionId") for item in sample["legalActions"]]
        payloads = [item.get("payload") for item in sample["legalActions"]]
        if row.get("orderedActionIds") != ordered or row.get("legalActions") != payloads:
            raise ValueError(f"tree parity row {index} actual legal actions/order differ")
        logits = row.get("logits")
        value = row.get("value")
        if not isinstance(logits, list) or len(logits) != len(ordered) \
                or any(type(item) not in (int, float) or not math.isfinite(item) for item in logits) \
                or type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"tree parity row {index} evaluator output is malformed")
        if sample["observation"].get("choice", sample["observation"].get("Choice")) is not None:
            choice_roots += 1
    return {"actualTreeEvaluatorRoots": len(lines), "actualTreeChoiceRoots": choice_roots,
            "actualTreeParitySha256": sha256(path)}


def sha256_bytes(content: bytes) -> str:
    import hashlib
    return hashlib.sha256(content).hexdigest()


def run_probe(*, output: Path, seed: str, encounter: str, search_mode: str,
              game_dir: Path, ritsu_root: Path, model: Path | None = None,
              fixture_cards: list[str] | None = None, force_card: str | None = None,
              initial_hp: int | None = None, max_decisions: int = 32,
              budget_ms: int = 1000, max_simulations: int | None = None,
              timeout_seconds: int = 700, root_parity_output: Path | None = None,
              generated_scenario: Path | None = None,
              regression_only: bool = False) -> dict:
    if output.suffix != ".jsonl" or output.exists() or output.with_suffix(".probe.json").exists():
        raise FileExistsError("probe requires a new .jsonl output and report path")
    if not seed or encounter not in REGISTERED_ENCOUNTERS:
        raise ValueError("probe requires a seed and a registered encounter")
    if search_mode not in {"pure-mcts", "policy-value-tree-v1"}:
        raise ValueError("unsupported probe search mode")
    if (search_mode == "pure-mcts") != (model is None):
        raise ValueError("pure MCTS cannot load a model; tree mode requires one")
    if root_parity_output is not None and search_mode != "policy-value-tree-v1":
        raise ValueError("root numerical parity requires a tree model")
    if force_card is not None and (not fixture_cards or force_card not in fixture_cards):
        raise ValueError("forced-card regression requires that card in a choice fixture")
    if fixture_cards is not None and not fixture_cards:
        raise ValueError("choice fixture card list is empty")
    if initial_hp is not None and (initial_hp < 1 or fixture_cards is None):
        raise ValueError("low-HP fixture requires a positive HP and a fixture deck")
    if generated_scenario is not None and (fixture_cards is not None or force_card is not None
                                           or initial_hp is not None):
        raise ValueError("generated deck cannot be combined with a regression fixture")
    if max_decisions < 1 or budget_ms < 1000 or max_simulations is not None and max_simulations < 1 \
            or timeout_seconds < 1:
        raise ValueError("probe requires positive decisions/simulations and at least 1000 ms")
    if not game_dir.is_dir() or not ritsu_root.is_dir():
        raise FileNotFoundError("game or RitsuLib directory is missing")
    model_hash = None
    if model is not None:
        model = model.resolve(strict=True)
        model_hash = checked_model(model)
    if generated_scenario is not None:
        generated_scenario = generated_scenario.resolve(strict=True)
        spec = json.loads(generated_scenario.read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or spec.get("seed") != seed or spec.get("encounterId") != encounter \
                or spec.get("characterId") != "IRONCLAD" or spec.get("ascension") != 0 \
                or spec.get("includeStartingDeck") is not False or spec.get("includeAscendersBane") is not False \
                or spec.get("mode") != "Setup":
            raise ValueError("generated scenario does not match this A0 deck-only Native request")
        scenario_hash = sha256(generated_scenario)
    else:
        scenario_hash = None
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None:
        raise FileNotFoundError("PowerShell 7 is required")
    repo = Path(__file__).resolve().parents[3]
    script = repo / "scripts" / "native-worker.ps1"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_suffix(".stage")
    if stage.exists():
        raise FileExistsError(f"probe requires a new isolated stage: {stage}")
    if root_parity_output is not None:
        root_parity_output = root_parity_output.resolve()
        if root_parity_output == output or root_parity_output.exists():
            raise FileExistsError("root parity requires a new output separate from JSONL")
        root_parity_output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("STS2_MCTS_EXPORT_") or name.startswith("STS2_ALPHAZERO_"):
            env.pop(name)
    env.update({"STS2_MCTS_EXPORT_OUT": str(output), "STS2_MCTS_EXPORT_SEED": seed,
                "STS2_MCTS_EXPORT_ENCOUNTER": encounter,
                "STS2_MCTS_EXPORT_MAX_DECISIONS": str(max_decisions)})
    if generated_scenario is not None:
        env["STS2_MCTS_EXPORT_GENERATED_SCENARIO"] = str(generated_scenario)
    if root_parity_output is not None:
        env["STS2_ALPHAZERO_ROOT_PARITY_OUT"] = str(root_parity_output)
    if fixture_cards is not None:
        env["STS2_MCTS_EXPORT_CHOICE_FIXTURE"] = "1"
        env["STS2_MCTS_EXPORT_FIXTURE_CARDS"] = ",".join(fixture_cards)
    if force_card is not None:
        env["STS2_MCTS_EXPORT_FORCE_CARD"] = force_card
    if initial_hp is not None:
        env["STS2_MCTS_EXPORT_INITIAL_HP"] = str(initial_hp)
    if regression_only:
        env["STS2_MCTS_EXPORT_REGRESSION_ONLY"] = "1"
    command = [shell, "-NoProfile", "-File", str(script), "-GameDir", str(game_dir.resolve()),
               "-RitsuLibRoot", str(ritsu_root.resolve()), "-Mode", "solver-mcts-export",
               "-StageRoot", str(stage), "-CleanupInstanceOnExit",
               "-TimeoutSeconds", str(timeout_seconds), "-SearchMode", search_mode,
               "-BudgetMilliseconds", str(budget_ms)]
    if model is not None:
        command.extend(["-OnnxModel", str(model)])
    if max_simulations is not None:
        command.extend(["-MaxSimulations", str(max_simulations)])
    report_path = output.with_suffix(".probe.json")
    report = {"format": "azcombat.native-probe.v1", "output": str(output), "seed": seed,
              "encounter": encounter, "requestedSearchMode": search_mode,
              "modelSha256": model_hash, "fixtureCards": fixture_cards, "forceCard": force_card,
              "initialHp": initial_hp, "maxDecisions": max_decisions,
              "budgetMilliseconds": budget_ms, "maxSimulations": max_simulations,
              "timeoutSeconds": timeout_seconds,
              "rootParityOutput": str(root_parity_output) if root_parity_output else None,
              "generatedScenarioPath": str(generated_scenario) if generated_scenario else None,
              "generatedScenarioSha256": scenario_hash,
              "stageRoot": str(stage),
              "regressionOnly": regression_only or force_card is not None, "status": "started"}
    report["damageCaptureSource"] = "native-damage-command-v1"
    _write_new(report_path, json.dumps(report, indent=2) + "\n")
    try:
        try:
            result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout_seconds + 300,
                                    check=False)
        except subprocess.TimeoutExpired as error:
            for suffix, content in ((".launcher.stdout.txt", error.stdout),
                                    (".launcher.stderr.txt", error.stderr)):
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")
                _write_new(output.with_suffix(suffix), content or "")
            for suffix, source in ((".worker.stdout.txt", stage / "stdout.txt"),
                                   (".worker.stderr.txt", stage / "stderr.txt")):
                if source.is_file():
                    with source.open("rb") as reader, output.with_suffix(suffix).open("xb") as writer:
                        shutil.copyfileobj(reader, writer)
            raise
        report["exitCode"] = result.returncode
        for suffix, content in ((".launcher.stdout.txt", result.stdout),
                                (".launcher.stderr.txt", result.stderr)):
            _write_new(output.with_suffix(suffix), content)
        for suffix, source in ((".worker.stdout.txt", stage / "stdout.txt"),
                               (".worker.stderr.txt", stage / "stderr.txt")):
            destination = output.with_suffix(suffix)
            if not source.is_file():
                if result.returncode != 0:
                    continue
                raise FileNotFoundError(f"worker log missing from isolated stage: {source}")
            with source.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        if result.returncode != 0:
            raise RuntimeError(f"NativeWorker failed; see {output.with_suffix('.worker.stderr.txt')}")
        report.update(audit_probe(output, expected=report))
        report["status"] = "complete"
        return report
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        stage_provenance = stage / "stage_provenance.json"
        report["stageProvenanceSha256"] = sha256(stage_provenance) if stage_provenance.is_file() else None
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def audit_probe(path: Path, *, expected: dict, verify_current_assembly: bool = True) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ValueError("probe JSONL is empty or contains blank lines")
    raw = [json.loads(line) for line in lines]
    provenance = raw[0].get("provenance") if isinstance(raw[0], dict) else None
    if not isinstance(provenance, dict) \
            or provenance.get("rewardLedgerVersion") != REWARD_LEDGER_VERSION:
        raise ValueError("native provenance/reward ledger version is missing or obsolete")
    if any(line.get("provenance") != provenance for line in raw):
        raise ValueError("trajectory provenance differs across samples")
    samples = read_jsonl(path, allow_regression=bool(expected["regressionOnly"]),
                         require_current_search_semantics=True)
    if len(samples) != len(raw):
        raise ValueError("strict/raw sample counts differ")
    if provenance.get("searchSemanticsVersion") != SEARCH_SEMANTICS_VERSION \
            or provenance.get("rewardLedgerVersion") != REWARD_LEDGER_VERSION \
            or provenance.get("regressionOnly") is not expected["regressionOnly"] \
            or provenance.get("forcedFixtureCard") != expected["forceCard"] \
            or provenance.get("requestedSearchMode") != expected["requestedSearchMode"] \
            or provenance.get("searchMode") != expected["requestedSearchMode"] \
            or provenance.get("maxSimulations") != expected["maxSimulations"] \
            or provenance.get("budgetMilliseconds") != expected["budgetMilliseconds"] \
            or provenance.get("maxDecisions") != expected["maxDecisions"] \
            or provenance.get("seed") != expected["seed"] \
            or provenance.get("encounter") != expected["encounter"]:
        raise ValueError("native provenance/search semantics differs from probe request")
    if expected["regressionOnly"] is False and (provenance.get("choiceFixture") is not False
            or provenance.get("startProvenance") is not None
            or expected.get("initialHp") is not None):
        raise ValueError("natural full-combat probe contains a regression/modified start")
    _audit_generated_deck(provenance, expected)
    metrics = provenance.get("decisionMetrics")
    if not isinstance(metrics, list) or len(metrics) != len(samples):
        raise ValueError("decision metrics are not aligned with samples")
    choice_rows = []
    rates = []
    for index, (sample, line, metric) in enumerate(zip(samples, raw, metrics, strict=True)):
        if sample.seed != expected["seed"] or sample.start_type != "full_combat":
            raise ValueError("sample seed/start differs from request")
        legal_ids = {action.action_id for action in sample.legal_actions}
        if metric.get("selectedActionId") not in legal_ids \
                or metric.get("stateKey") != line.get("stateKey") \
                or metric.get("simulations") != line.get("simulations"):
            raise ValueError("selected action or root metrics are misaligned")
        if not isinstance(line.get("visitPolicy"), dict) \
                or any(type(visits) is not int or visits <= 0
                       for visits in line["visitPolicy"].values()) \
                or sum(line["visitPolicy"].values()) <= 0:
            raise ValueError(f"decision {index} has invalid actual root visit statistics")
        simulations = metric.get("simulations")
        elapsed = metric.get("elapsedMilliseconds")
        if type(simulations) is not int or simulations <= 0 \
                or type(elapsed) not in (int, float) or not math.isfinite(elapsed) \
                or elapsed < expected["budgetMilliseconds"] \
                or expected["maxSimulations"] is not None and simulations > expected["maxSimulations"] \
                or metric.get("maxSimulations") != expected["maxSimulations"] \
                or metric.get("budgetMilliseconds") != expected["budgetMilliseconds"] \
                or metric.get("searchMode") != expected["requestedSearchMode"] \
                or metric.get("networkFallbacks") != 0 \
                or metric.get("networkFallbackReason") is not None:
            raise ValueError(f"invalid simulation, budget, mode or fallback at decision {index}")
        prior, value = metric.get("networkPriorCalls"), metric.get("networkValueCalls")
        if expected["requestedSearchMode"] == "pure-mcts":
            if prior != 0 or value != 0:
                raise ValueError("pure MCTS made network calls")
        elif type(prior) is not int or type(value) is not int or prior <= 0 or value <= 0:
            raise ValueError("tree decision did not use prior and value")
        rates.append(simulations / (elapsed / 1000))
        if sample.observation["choice"] is not None:
            if not sample.legal_actions or any(action.kind != "NestedChoice" for action in sample.legal_actions) \
                    or metric.get("choiceLayer", 0) < 1:
                raise ValueError("choice observation is not an actual choice root")
            choice = sample.observation["choice"]
            layer = metric["choiceLayer"]
            if layer == 1:
                if choice["completedSelections"]:
                    raise ValueError("first choice layer contains a future selection")
            else:
                previous = samples[index - 1] if index else None
                previous_metric = metrics[index - 1] if index else None
                previous_choice = previous.observation["choice"] if previous is not None else None
                if previous_choice is None or previous_metric.get("choiceLayer") != layer - 1 \
                        or previous_metric.get("parentDecision") != metric.get("parentDecision") \
                        or previous_metric.get("parentActionId") != metric.get("parentActionId"):
                    raise ValueError("nested choice is not adjacent to its parent layer")
                selected = next((action for action in previous.legal_actions
                                 if action.action_id == previous_metric["selectedActionId"]), None)
                if selected is None or not isinstance(selected.payload, dict):
                    raise ValueError("previous choice selected action cannot be mapped")
                expected_completed = [*previous_choice["completedSelections"],
                                      {"effect": previous_choice["effect"],
                                       "combatCardIndices": _selected_candidate_indices(
                                           previous_choice, selected.payload)}]
                if choice["completedSelections"] != expected_completed:
                    raise ValueError("completedSelections differs from the committed prior choice")
            choice_rows.append({"index": index, "choiceLayer": metric["choiceLayer"],
                                "choice": choice,
                                "simulations": simulations, "elapsedMilliseconds": elapsed,
                                "simulationsPerSecond": rates[-1],
                                "networkPriorCalls": prior, "networkValueCalls": value})
    if provenance.get("modelScored") != sum(item["networkPriorCalls"] for item in metrics) \
            or provenance.get("modelUsed") != sum(item["networkValueCalls"] for item in metrics) \
            or provenance.get("modelFallbacks") != 0:
        raise ValueError("network totals differ from actual per-decision calls")
    status = provenance.get("modelLoadStatus", "")
    if expected["modelSha256"] is None:
        if status != "pure-mcts:no-model-configured":
            raise ValueError("pure baseline attempted to load a model")
    elif not status.startswith("model-ready") or expected["modelSha256"].lower() not in status.lower():
        raise ValueError("Native loaded a different model")
    transitions = provenance.get("enemyHpTransitions")
    outcome = Outcome(samples[0].outcome)
    if expected.get("damageCaptureSource") is not None and (
            not isinstance(transitions, list) or any(
                item.get("damageCaptureSource") != expected["damageCaptureSource"] for item in transitions)):
        raise ValueError("requested damage capture source is missing or mixed")
    if any(sample.outcome != outcome.value or sample.value_target != samples[0].value_target
           for sample in samples):
        raise ValueError("outcome/value was not uniformly backfilled")
    if provenance.get("terminal") is not (outcome is not Outcome.UNRESOLVED):
        raise ValueError("native settlement disagrees with outcome")
    value_target = score_result(TerminalResult(
        outcome, provenance["entryHp"], provenance["playerHp"],
        provenance["enemyDamageLost"], provenance["trajectoryInitialEnemyEffectiveHp"]))
    if abs(value_target - samples[0].value_target) > 1e-6:
        raise ValueError("value target differs from native HP and reward definition")
    reward_ledger = _audit_reward_ledger(provenance, metrics, final_outcome=outcome.value,
                                         final_value=samples[0].value_target)
    if outcome is Outcome.UNRESOLVED and reward_ledger["captures"] != expected["maxDecisions"]:
        raise ValueError("unresolved trajectory did not reach its declared decision limit")
    parity_summary = {}
    parity_path = expected.get("rootParityOutput")
    if parity_path is not None:
        if expected["requestedSearchMode"] != "policy-value-tree-v1":
            raise ValueError("pure MCTS must not have tree evaluator parity")
        parity_summary = _audit_tree_parity(Path(parity_path), raw, metrics)
    worker_log = path.with_suffix(".worker.stdout.txt").read_text(encoding="utf-8")
    worker_err = path.with_suffix(".worker.stderr.txt").read_text(encoding="utf-8")
    if "SLAY_WORKER_FAILED" in worker_log + worker_err or "pure-mcts-fallback" in worker_log + worker_err:
        raise ValueError("worker failure/fallback diagnostic is present")
    loaded = ASSEMBLY.findall(worker_log)
    if len(loaded) != 3 or {item[0] for item in loaded} != {"NativeWorker", "Search", "CombatSolver"}:
        raise ValueError("actual loaded assembly identities are incomplete")
    stage_root = expected.get("stageRoot")
    if stage_root is not None:
        stage = Path(stage_root).resolve(strict=True)
        stage_provenance_path = stage / "stage_provenance.json"
        stage_provenance = json.loads(stage_provenance_path.read_text(encoding="utf-8"))
        staged = stage_provenance.get("assemblies")
        if Path(stage_provenance.get("stageRoot", "")).resolve() != stage \
                or not isinstance(staged, list) or len(staged) != 3 \
                or {item.get("label") for item in staged if isinstance(item, dict)} \
                != {"NativeWorker", "Search", "CombatSolver"}:
            raise ValueError("isolated stage provenance is incomplete or mismatched")
        staged_by_label = {item["label"]: item for item in staged}
    fields = {"NativeWorker": "nativeWorker", "Search": "search", "CombatSolver": "combatSolver"}
    for label, assembly_path, mvid, digest in loaded:
        identity = provenance["assemblies"][fields[label]]
        if Path(identity["path"]).resolve() != Path(assembly_path).resolve() \
                or identity["mvid"].lower() != mvid.lower() \
                or identity["sha256"].lower() != digest.lower() \
                or verify_current_assembly and sha256(Path(assembly_path)).lower() != digest.lower():
            raise ValueError(f"loaded {label} assembly path/MVID/SHA256 differs")
        if stage_root is not None:
            staged_identity = staged_by_label[label]
            if not Path(assembly_path).resolve().is_relative_to(stage / "data_NativeWorker_windows_x86_64") \
                    or Path(staged_identity["path"]).resolve() != Path(assembly_path).resolve() \
                    or staged_identity["mvid"].lower() != mvid.lower() \
                    or staged_identity["sha256"].lower() != digest.lower():
                raise ValueError(f"loaded {label} assembly differs from isolated stage")
    if EXPORT_OUT.findall(worker_log) != [str(path.resolve())]:
        raise ValueError("Native export path differs from requested output")
    diagnostic_files = [str(file) for file in path.parent.glob(path.name + ".*diagnostic.json")]
    if diagnostic_files:
        raise ValueError(f"native diagnostics exist: {diagnostic_files}")
    return {"samples": len(samples), "outcome": outcome.value, "valueTarget": samples[0].value_target,
            "terminal": provenance["terminal"], "entryHp": provenance["entryHp"],
            "playerHp": provenance["playerHp"],
            "trajectoryInitialEnemyEffectiveHp": provenance["trajectoryInitialEnemyEffectiveHp"],
            "enemyDamageLost": provenance["enemyDamageLost"],
            "enemyHpTransitions": len(transitions), "choiceRows": choice_rows,
            "rewardLedger": reward_ledger, **parity_summary,
            "simulations": [item["simulations"] for item in metrics],
            "elapsedMilliseconds": [item["elapsedMilliseconds"] for item in metrics],
            "simulationsPerSecond": rates,
            "priorCalls": provenance["modelScored"], "valueCalls": provenance["modelUsed"],
            "fallbacks": provenance["modelFallbacks"],
            "assemblies": provenance["assemblies"], "jsonlSha256": sha256(path),
            "workerStdoutSha256": sha256(path.with_suffix(".worker.stdout.txt"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--encounter", default="CULTISTS_NORMAL")
    parser.add_argument("--search-mode", choices=("pure-mcts", "policy-value-tree-v1"), required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--fixture-cards", help="Comma-separated registered card IDs")
    parser.add_argument("--force-card")
    parser.add_argument("--initial-hp", type=int)
    parser.add_argument("--max-decisions", type=int, default=32)
    parser.add_argument("--budget-ms", type=int, default=1000)
    parser.add_argument("--max-simulations", type=int, help="Omit for an uncapped time-budgeted search")
    parser.add_argument("--root-parity-output", type=Path,
                        help="Opt-in extra Native root inference sidecar for numeric parity")
    parser.add_argument("--generated-scenario", type=Path,
                        help="Frozen GeneratedCombatScenarioOptions JSON for a natural full combat")
    parser.add_argument("--regression-only", action="store_true",
                        help="Mark a diagnostic fixture as ineligible for training or promotion")
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    args = parser.parse_args()
    report = run_probe(output=args.output, seed=args.seed, encounter=args.encounter,
                       search_mode=args.search_mode, model=args.model,
                       fixture_cards=args.fixture_cards.split(",") if args.fixture_cards else None,
                       force_card=args.force_card, initial_hp=args.initial_hp,
                       max_decisions=args.max_decisions, budget_ms=args.budget_ms,
                       max_simulations=args.max_simulations,
                       root_parity_output=args.root_parity_output,
                       generated_scenario=args.generated_scenario,
                       regression_only=args.regression_only,
                       game_dir=args.game_dir, ritsu_root=args.ritsu_root)
    print(json.dumps({key: report[key] for key in ("status", "output", "samples", "outcome",
                                                   "choiceRows", "priorCalls", "valueCalls",
                                                   "fallbacks")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
