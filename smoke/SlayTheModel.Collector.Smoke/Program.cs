using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

var temporaryRoot = Path.Combine(
    Path.GetTempPath(),
    $"SlayTheModel-Collector-Smoke-{Guid.NewGuid():N}");

try
{
    var mismatch = JsonSerializer.SerializeToElement(
        new ResumeCheckpointMismatch(true, 5, 12, false), CollectorJson.Options);
    Assert(mismatch.GetProperty("checkpoint_event_sequence").GetInt64() == 5
           && mismatch.GetProperty("journal_event_sequence").GetInt64() == 12,
        "Resume mismatch must preserve both cursors without JSON name collisions.");
    AssertThrows<InvalidOperationException>(() => CollectorJson.Options.WriteIndented = true);
    AssertThrows<JsonException>(() => JsonSerializer.Deserialize<PolicyTrace>(
        "{\"policy_id\":\"missing-actor\"}",
        CollectorJson.Options));
    AssertThrows<JsonException>(() => JsonSerializer.Deserialize<PolicyTrace>(
        "{\"actor\":\"human\",\"unknown_field\":1}",
        CollectorJson.Options));
    var legacyGap = JsonSerializer.Deserialize<CoverageGapPayload>(
        JsonSerializer.Serialize(new
        {
            reason = "legacy_gap",
            invalidated_decision_id = (Guid?)null,
            invalidated_global_step = (long?)null,
            invalidated_phase = EpisodePhase.Ready,
            invalidates_pending_decision = false,
        }, CollectorJson.Options),
        CollectorJson.Options);
    Assert(legacyGap is { RelatedDecisionId: null, RelatedAttemptId: null },
        "Legacy coverage gaps must remain readable after adding related IDs.");
    var legacyFinish = JsonSerializer.Deserialize<EpisodeFinishedPayload>(
        JsonSerializer.Serialize(new
        {
            outcome = "victory",
            termination_reason = "legacy",
            completeness = EpisodeCompleteness.Complete,
            contains_save_load = false,
            save_load_count = 0,
            unknown_save_load_count = 0,
            rewind_count = 0,
            invalidated_pending_count = 0,
            uncertain_execution_count = 0,
            coverage_gap_count = 0,
            value_target_valid = true,
            incomplete_decision_id = (Guid?)null,
            previous_phase = EpisodePhase.Ready,
            summary = (object?)null,
        }, CollectorJson.Options),
        CollectorJson.Options);
    Assert(legacyFinish is
        {
            ManualCombatInputCount: 0,
            UnresolvedManualCombatInputCount: 0,
            UnstructuredManualCombatInputCount: 0,
        }, "Legacy schema-v1 finish payload must remain readable.");
    var oldDecisionInput = DecisionInput.FromCombat(
        Guid.NewGuid(), CreateCombatDecision(0, 'a'), InformationRegime.NoSl);
    var oldDecisionPayload = new DecisionPayload(
        oldDecisionInput.EventId,
        oldDecisionInput.Domain,
        oldDecisionInput.InformationRegime,
        oldDecisionInput.SourceDecisionIndex,
        oldDecisionInput.StateFingerprint,
        oldDecisionInput.Observation,
        oldDecisionInput.LegalActions,
        oldDecisionInput.ActionKeys,
        oldDecisionInput.Build,
        oldDecisionInput.Context);
    var oldDecisionJson = JsonNode.Parse(JsonSerializer.Serialize(
        oldDecisionPayload, CollectorJson.Options))!.AsObject();
    oldDecisionJson.Remove("queued_outside_input");
    var restoredOldDecision = JsonSerializer.Deserialize<DecisionPayload>(
        oldDecisionJson.ToJsonString(), CollectorJson.Options);
    Assert(restoredOldDecision is { QueuedOutsideInput: false },
        "Old decision rows without the outside queue marker must remain readable.");
    var legacyCombatNode = JsonNode.Parse(JsonSerializer.Serialize(
        CreateCombatDecision(0, 'a').Observation,
        CollectorJson.Options))!.AsObject();
    var priorCombatNode = legacyCombatNode.DeepClone().AsObject();
    priorCombatNode["schema_version"] = 2;
    foreach (var priorPlayer in priorCombatNode["players"]!.AsArray())
    {
        foreach (var priorRelic in priorPlayer!["relics"]!.AsArray())
        {
            priorRelic!.AsObject().Remove("display");
        }
    }
    JsonSerializer.Deserialize<CombatObservation>(
        priorCombatNode.ToJsonString(), CollectorJson.Options)!.Validate();
    legacyCombatNode["schema_version"] = 1;
    legacyCombatNode.Remove("enemy_intents");
    legacyCombatNode.Remove("companions");
    foreach (var legacyPlayer in legacyCombatNode["players"]!.AsArray())
    {
        var playerObject = legacyPlayer!.AsObject();
        playerObject.Remove("gold");
        playerObject.Remove("orb_capacity");
        foreach (var legacyRelic in playerObject["relics"]!.AsArray())
        {
            legacyRelic!.AsObject().Remove("display");
        }
        foreach (var pile in playerObject["piles"]!.AsArray())
        {
            foreach (var legacyCard in pile!["cards"]!.AsArray())
            {
                var cardObject = legacyCard!.AsObject();
                cardObject.Remove("upgrade_level");
                cardObject.Remove("enchantment_id");
                cardObject.Remove("enchantment_amount");
                cardObject.Remove("display");
            }
        }
    }
    var parsedLegacyCombat = JsonSerializer.Deserialize<CombatObservation>(
        legacyCombatNode.ToJsonString(),
        CollectorJson.Options);
    Assert(parsedLegacyCombat is { SchemaVersion: 1 },
        "Legacy combat observation must remain readable without v2 fields.");
    parsedLegacyCombat!.Validate();
    var oldPotionDecision = CreateCombatDecision(0, 'c');
    oldPotionDecision = oldPotionDecision with
    {
        Observation = oldPotionDecision.Observation with
        {
            Players = oldPotionDecision.Observation.Players
                .Select(player => player with
                {
                    Potions = [new PotionObservation(0, "BLOCK_POTION")],
                })
                .ToArray(),
        },
        LegalActions =
        [
            new CombatActionDescriptor(
                CombatActionKind.UsePotion, ActorPlayerId: 1, PotionIndex: 2),
        ],
    };
    oldPotionDecision.Validate();
    AssertThrows<InvalidDataException>(() => DecisionInput.FromCombat(
        Guid.NewGuid(), oldPotionDecision, InformationRegime.NoSl));
    var clock = new AdvancingClock(
        new DateTimeOffset(2026, 9, 24, 12, 0, 0, TimeSpan.Zero));
    var store = new CollectorStore(temporaryRoot, clock);
    RunResumeMismatchSmoke(store);
    RunPublicationNamingSmoke(store);
    RunCompactJournalSmoke(store);
    RunHpAnchorPayloadSmoke(store);
    RunCompletedEpisodeSmoke(store);
    RunExplicitResumeSmoke(store);
    RunQueuedManualCombatInputSmoke(store);
    RunStructuredQueuedCombatSmoke(store);
    RunStructuredQueuedOutsideSmoke(store);
    RunOutOfOrderNestedQueuedCombatSmoke(store);
    RunGeneratedCardChoiceContractSmoke();
    RunOutsideCardSetTemplateSmoke(store);
    RunCombatCardSetContractSmoke(store);
    RunLegacySingleChoiceKeySmoke();
    RunQueuedRecoveryAndInvalidationSmoke(store);
    RunCancelledUnstructuredInputSmoke(store);
    RunQueuedCoverageGapSmoke(store);
    RunTargetedQueuedCoverageGapSmoke(store);
    RunTamperDetectionSmoke(store);
    RunRewindSemanticsSmoke(store);
    RunPendingGapSemanticsSmoke(store);
    RunStaleGapSemanticsSmoke(store);
    RunCoverageGapSemanticsSmoke(store);
    RunDetachedCoverageGapSemanticsSmoke(store);
    RunCombatNestedChoiceBoundarySmoke(store);
    RunCombatNestedChoiceLateFailureSmoke(store);
    RunUnknownLoadSemanticsSmoke(store);
    RunAbandonedCompletenessSmoke(store);
    RunInterruptedPublicationSmoke(store);
    Console.WriteLine("collector_smoke=ok");
}
finally
{
    if (Directory.Exists(temporaryRoot))
    {
        Directory.Delete(temporaryRoot, recursive: true);
    }
}

static void RunHpAnchorPayloadSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var start = CreateStart(episodeId) with
    {
        Metadata = new Dictionary<string, string>
        {
            ["observed_from_run_start"] = "True",
            ["episode_start_current_hp"] = "80",
            ["episode_start_max_hp"] = "80",
            ["run_start_current_hp"] = "80",
            ["run_start_max_hp"] = "80",
        },
    };
    using (var session = store.StartEpisode(start))
    {
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "win",
            "native_run_history",
            EpisodeCompleteness.Complete,
            JsonSerializer.SerializeToElement(new
            {
                terminal_current_hp = 43,
                terminal_max_hp = 80,
                terminal_hp_status = "available",
            }, CollectorJson.Options)));
    }

    var events = store.ReadEpisode(episodeId);
    var started = events[0].Payload.Deserialize<EpisodeStartedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Start payload is absent.");
    Assert(started.Metadata["run_start_current_hp"] == "80"
           && started.Metadata["run_start_max_hp"] == "80",
        "Run-start HP metadata did not survive journal publication.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.Summary is { } summary
           && summary.GetProperty("terminal_current_hp").GetInt32() == 43
           && summary.GetProperty("terminal_max_hp").GetInt32() == 80
           && summary.GetProperty("terminal_hp_status").GetString() == "available",
        "Terminal HP summary did not survive journal publication.");
}

static void RunCompactJournalSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var firstPoint = CreateCombatDecision(0, 'a');
    var secondPoint = CreateCombatDecision(1, 'b');
    secondPoint = secondPoint with
    {
        Observation = secondPoint.Observation with
        {
            Players = secondPoint.Observation.Players
                .Select(player => player with { Energy = 2, Gold = 98 })
                .ToArray(),
            Creatures = secondPoint.Observation.Creatures
                .Select(creature => creature with { CurrentHp = 39 })
                .ToArray(),
        },
    };

    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        RecordStep(
            session,
            firstPoint,
            selectedActionIndex: 0,
            recordManualEvidence: true,
            JsonSerializer.SerializeToElement(new
            {
                run_context = new { floor = 1, gold = 99 },
                audit = new { input_surface = "combat" },
            }, CollectorJson.Options));
        RecordStep(
            session,
            secondPoint,
            selectedActionIndex: 1,
            recordManualEvidence: false,
            JsonSerializer.SerializeToElement(new
            {
                run_context = new { floor = 1, gold = 98 },
                audit = new { input_surface = "combat" },
            }, CollectorJson.Options));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "compact_fixture", EpisodeCompleteness.Complete));
        Assert(session.CompactViewError is null,
            $"Automatic compact export failed: {session.CompactViewError}");
    }

    var compactPath = store.GetCompactEpisodePath(episodeId);
    Assert(File.Exists(compactPath), "Finishing an episode did not publish its compact view.");
    var rows = ReadJournalLines(compactPath)
        .Select(line => JsonNode.Parse(line)?.AsObject()
            ?? throw new InvalidDataException("Compact fixture contains a null row."))
        .ToArray();
    var decisions = rows
        .Where(row => row["t"]?.GetValue<string>() == "decision")
        .ToArray();
    Assert(decisions.Length == 2, "Compact fixture lost a decision.");
    Assert(decisions[0]["observation"]?["mode"]?.GetValue<string>() == "full",
        "The first compact observation must be a full checkpoint.");
    Assert(decisions[1]["observation"]?["mode"]?.GetValue<string>() == "delta",
        "The second compact observation must be encoded as a delta.");
    var observationSet = decisions[1]["observation"]?["set"]?.AsObject();
    Assert(observationSet?.ContainsKey("/players/0/energy") == true
           && observationSet.ContainsKey("/players/0/gold")
           && observationSet.ContainsKey("/creatures/0/current_hp"),
        "Compact observation delta did not retain changed combat collections.");
    var contextSet = decisions[1]["context"]?["set"]?.AsObject();
    Assert(contextSet?.ContainsKey("/run_context/gold") == true,
        "Compact context delta did not retain the changed public gold value.");
    Assert(decisions.All(row => row["legal_actions"] is JsonArray),
        "Compact decisions must keep each click-time legal action set explicit.");

    var actions = rows
        .Where(row => row["t"]?.GetValue<string>() == "action")
        .ToArray();
    Assert(actions.Length == 2
           && actions.All(row => row["attempt"]?.GetValue<int>() == 1),
        "Compact action rows did not retain stable per-decision attempt ordinals.");
    Assert(actions[0]["selected_action_index"]?.GetValue<int>() == 0
           && actions[1]["selected_action_index"]?.GetValue<int>() == 1,
        "Compact action rows lost their selected legal-action indexes.");

    var manualInput = rows.Single(row =>
        row["t"]?.GetValue<string>() == "manual_input");
    Assert(manualInput["decision_evidence"]?.GetValue<string>() == "exact"
           && manualInput["action_evidence"]?.GetValue<string>() == "selected"
           && manualInput["data"]?["click_observation"] is null
           && manualInput["data"]?["click_legal_actions"] is null,
        "Compact manual input did not replace exact duplicate evidence with references.");
    var manualResult = rows.Single(row =>
        row["t"]?.GetValue<string>() == "manual_result");
    Assert(manualResult["data"]?["execution_start_observation"]?["mode"]
               ?.GetValue<string>() == "delta"
           && manualResult["data"]?["execution_end_observation"]?["mode"]
               ?.GetValue<string>() == "delta",
        "Compact manual result did not retain execution observations as reversible deltas.");

    var finish = rows.Single(row => row["t"]?.GetValue<string>() == "finish");
    Assert(finish["delta_round_trip_verified"]?.GetValue<bool>() == true,
        "Compact publication did not record delta round-trip verification.");
    var regenerated = store.ExportCompactEpisode(episodeId, overwrite: true);
    Assert(regenerated.DecisionCount == 2
           && regenerated.FullObservationCount == 1
           && regenerated.SourceSha256.Length == 64
           && regenerated.CompactSha256.Length == 64,
        "Explicit compact backfill returned an invalid export summary.");

    static void RecordStep(
        EpisodeSession session,
        CombatDecisionPoint point,
        int selectedActionIndex,
        bool recordManualEvidence,
        JsonElement context)
    {
        var receipt = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), point, InformationRegime.NoSl) with { Context = context });
        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            selectedActionIndex,
            receipt.ActionKeys[selectedActionIndex],
            new PolicyTrace(ActionActor.Human, "compact-smoke")));
        Guid? manualIntentId = null;
        if (recordManualEvidence)
        {
            manualIntentId = Guid.NewGuid();
            session.RecordManualCombatInput(new ManualCombatInputInput(
                Guid.NewGuid(),
                manualIntentId.Value,
                NativeActionId: 17,
                ActionKind: "PlayCard",
                JsonSerializer.SerializeToElement(new
                {
                    input_at_utc = "2026-10-12T12:00:00Z",
                    action = point.LegalActions[selectedActionIndex],
                    click_observation = point.Observation,
                    click_legal_actions = point.LegalActions,
                    click_observation_fingerprint = point.StateFingerprint,
                    click_observation_status = "structured_legal_set",
                    capture_failure = (string?)null,
                    queued_at_click = false,
                    native_action_state_at_enqueue = "WaitingForExecution",
                    overlaps_decision_id = (string?)null,
                    overlaps_attempt_id = (string?)null,
                }, CollectorJson.Options),
                receipt.DecisionId,
                attemptId));
        }

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            selectedActionIndex,
            receipt.ActionKeys[selectedActionIndex],
            point.StateFingerprint,
            CollectorExecutionStatus.Applied,
            Fingerprint(selectedActionIndex == 0 ? 'b' : 'c')));
        if (manualIntentId is { } intentId)
        {
            var executionEnd = point.Observation with
            {
                Players = point.Observation.Players
                    .Select(player => player with { Energy = 2 })
                    .ToArray(),
            };
            session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
                Guid.NewGuid(),
                intentId,
                NativeActionId: 17,
                CollectorExecutionStatus.ObservedTransition,
                Data: JsonSerializer.SerializeToElement(new
                {
                    execution_started_at_utc = "2026-10-12T12:00:00Z",
                    execution_start_observation = point.Observation,
                    execution_start_capture_failure = (string?)null,
                    execution_finished_at_utc = "2026-10-12T12:00:01Z",
                    execution_end_observation = executionEnd,
                    execution_end_capture_failure = (string?)null,
                }, CollectorJson.Options)));
        }

        session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0.0 }));
    }
}

static void RunCompletedEpisodeSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var decision = CreateCombatDecision(decisionIndex: 7, fingerprintCharacter: 'b');
    var decisionInput = DecisionInput.FromCombat(
        Guid.NewGuid(),
        decision,
        InformationRegime.NoSl) with
    {
        Context = JsonSerializer.SerializeToElement(new
        {
            run_context = new { floor = 1, gold = 99 },
            audit = new { input_surface = "combat" },
        }),
    };
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var ready = session.Snapshot;
        Assert(ready.Phase == EpisodePhase.Ready, "A new episode must be ready.");
        Assert(ready.NextEventSequence == 1, "episode_started must be sequence zero.");

        session.RecordDiagnostic(
            "native_player_choice",
            JsonSerializer.SerializeToElement(new { choice_id = 42, raw = "smoke" }));
        Assert(
            session.Snapshot.Phase == EpisodePhase.Ready,
            "A diagnostic must not alter policy state.");

        var beforeForgedDecision = ReadJournalLines(
            store.GetOpenEpisodePath(episodeId)).Count();
        AssertThrows<InvalidDataException>(() => session.RecordDecision(
            decisionInput with { ActionKeys = ["forged:0", "forged:1"] }));
        Assert(
            ReadJournalLines(store.GetOpenEpisodePath(episodeId)).Count()
                == beforeForgedDecision,
            "Forged action keys must be rejected before durable append.");

        var receipt = session.RecordDecision(decisionInput);
        Assert(receipt.GlobalStep == 0, "The first decision must use global step zero.");
        Assert(receipt.ActionKeys.Count == 2, "The fixture must expose two actions.");

        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            SelectedActionIndex: 0,
            receipt.ActionKeys[0],
            new PolicyTrace(
                ActionActor.Policy,
                "first-legal",
                Logits: [1.0, 0.0],
                MctsVisitCounts: [5, 1])));

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.Rejected,
            Detail: "Native guard rejected the first attempt."));
        Assert(
            session.Snapshot.Phase == EpisodePhase.AwaitingAction
            && session.Snapshot.PendingDecisionId == receipt.DecisionId,
            "Rejected attempt must preserve the decision for retry.");

        var acceptedAttemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            acceptedAttemptId,
            SelectedActionIndex: 0,
            receipt.ActionKeys[0],
            new PolicyTrace(ActionActor.Policy, "first-legal-retry")));

        var committedBeforeRejectedReward = ReadJournalLines(
            store.GetOpenEpisodePath(episodeId)).Count();
        AssertThrows<InvalidDataException>(() => session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0.0 })));
        Assert(
            ReadJournalLines(store.GetOpenEpisodePath(episodeId)).Count()
                == committedBeforeRejectedReward,
            "An invalid transition must be rejected before durable append.");

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            acceptedAttemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.Applied,
            NextStateFingerprint: Fingerprint('c')));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            "reward-v1",
            new Dictionary<string, double>
            {
                ["hp_delta"] = 0.0,
                ["terminal"] = 0.0,
            }));

        // A normal quit/continue is factual reload evidence, but is not SL and
        // must not invalidate a value target.
        session.MarkSaveLoad(new SaveLoadInput(
            Guid.NewGuid(),
            SaveLoadKind.Resume,
            "normal_continue",
            BeforeStateFingerprint: Fingerprint('c'),
            RestoredStateFingerprint: Fingerprint('c'),
            CheckpointSha256: Fingerprint('d')));
        Assert(session.Snapshot.TimelineGeneration == 1, "Reload must advance timeline.");
        Assert(session.Snapshot.SaveLoadCount == 1, "Reload count must be retained.");
        Assert(session.Snapshot.RewindCount == 0, "Resume must not be classified as rewind.");

        session.RecordDiagnostic(new DiagnosticInput(
            Guid.NewGuid(),
            "unmapped_native_input",
            JsonSerializer.SerializeToElement(new { native_type = "PlayerChoice" })));

        var secondPoint = CreateCombatDecision(decisionIndex: 0, fingerprintCharacter: 'e');
        var second = session.RecordDecision(
            DecisionInput.FromCombat(
                Guid.NewGuid(),
                secondPoint,
                InformationRegime.NoSl));
        Assert(second.GlobalStep == 1, "Source indices may reset; global steps must not.");
        var secondAttempt = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            second.DecisionId,
            secondAttempt,
            1,
            second.ActionKeys[1],
            new PolicyTrace(ActionActor.Script, "scripted")));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            second.DecisionId,
            secondAttempt,
            1,
            second.ActionKeys[1],
            secondPoint.StateFingerprint,
            CollectorExecutionStatus.Cancelled,
            Detail: "Fixture cancellation."));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "smoke_complete",
            EpisodeCompleteness.Complete,
            JsonSerializer.SerializeToElement(new { floors = 1 })));
        Assert(session.Snapshot.IsPublished, "Finish must atomically publish the episode.");
    }

    var openPath = store.GetOpenEpisodePath(episodeId);
    var completedPath = store.GetCompletedEpisodePath(episodeId);
    Assert(!File.Exists(openPath), "Published episode must leave no .partial path.");
    Assert(File.Exists(completedPath), "Published episode file is missing.");

    var events = store.ReadEpisode(episodeId);
    Assert(events.Count == 14, "Completed fixture has an unexpected event count.");
    for (var index = 0; index < events.Count; index++)
    {
        Assert(events[index].EventSequence == index, "Event sequence is not contiguous.");
        var expectedPrevious = index == 0
            ? CollectorJson.InitialPreviousHash
            : events[index - 1].EventSha256;
        Assert(
            events[index].PreviousEventSha256 == expectedPrevious,
            "Event hash chain is not contiguous.");
    }

    var action = events.First(item => item.EventType == CollectorEventType.ActionSubmitted);
    var actionPayload = action.Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Action payload is absent.");
    var execution = events.First(item => item.EventType == CollectorEventType.ExecutionResult);
    var executionPayload = execution.Payload.Deserialize<ExecutionResultPayload>(
        CollectorJson.Options)
        ?? throw new InvalidOperationException("Execution payload is absent.");
    Assert(
        actionPayload.AttemptId == executionPayload.AttemptId,
        "Execution must reference the submitted attempt, not just the decision.");

    var storedDecision = events.First(item => item.EventType == CollectorEventType.Decision)
        .Payload.Deserialize<DecisionPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Decision payload is absent.");
    Assert(
        storedDecision.Context is { ValueKind: JsonValueKind.Object } context
        && context.GetProperty("run_context").GetProperty("gold").GetInt32() == 99,
        "Decision context was not durably preserved beside the domain observation.");

    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.ContainsSaveLoad, "Finish must retain reload evidence.");
    Assert(finished.SaveLoadCount == 1, "Finish has the wrong reload count.");
    Assert(finished.RewindCount == 0, "Normal resume was incorrectly marked as rewind.");
    Assert(finished.InvalidatedPendingCount == 0, "Ready resume invented a data gap.");
    Assert(finished.UncertainExecutionCount == 0, "Clean execution invented uncertainty.");
    Assert(finished.CoverageGapCount == 0, "Clean episode invented a coverage gap.");
    Assert(finished.ValueTargetValid, "Normal resume must preserve value-target validity.");
}

static void RunExplicitResumeSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    DecisionReceipt receipt;
    var decision = CreateCombatDecision(decisionIndex: 3, fingerprintCharacter: 'f');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        receipt = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(),
            decision,
            InformationRegime.NoSl));
    }

    var partialPath = store.GetOpenEpisodePath(episodeId);
    using (var tornAppend = new FileStream(
               partialPath,
               FileMode.Append,
               FileAccess.Write,
               FileShare.Read))
    {
        tornAppend.Write(Encoding.UTF8.GetBytes("{\"torn\":"));
        tornAppend.Flush(flushToDisk: true);
    }

    // CollectorStore construction did not inspect or mutate this file. Only
    // this known-ID ResumeEpisode call may truncate and replay it.
    using (var resumed = store.ResumeEpisode(episodeId))
    {
        Assert(
            resumed.Snapshot.Phase == EpisodePhase.AwaitingAction,
            "Explicit resume did not reconstruct the pending decision.");
        Assert(resumed.Snapshot.NextEventSequence == 2, "Torn tail was not discarded.");
        Assert(
            !string.Join("\n", ReadJournalLines(partialPath)).Contains("torn", StringComparison.Ordinal),
            "Resume retained an uncommitted torn tail.");

        resumed.RecordDiagnostic(
            "resume_probe",
            JsonSerializer.SerializeToElement(new { recovered = true }));
        Assert(
            resumed.Snapshot.Phase == EpisodePhase.AwaitingAction,
            "Diagnostic changed a restored pending state.");

        var attemptId = Guid.NewGuid();
        resumed.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            new PolicyTrace(ActionActor.Policy, "resume-smoke")));
        resumed.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.Cancelled,
            Detail: "Recovered fixture cancellation."));
        resumed.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "abandoned",
            "smoke_recovered",
            EpisodeCompleteness.Incomplete));
    }

    var events = store.ReadEpisode(episodeId);
    Assert(events.Count == 6, "Recovered fixture has an unexpected event count.");
    Assert(
        events.Count(item => item.EventType == CollectorEventType.EpisodeFinished) == 1,
        "Resume must not synthesize a crash finish event.");
}

static void RunQueuedManualCombatInputSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var point = CreateCombatDecision(decisionIndex: 10, fingerprintCharacter: 'a');
    var structuredIntent = Guid.NewGuid();
    var queuedIntent = Guid.NewGuid();
    var unresolvedIntent = Guid.NewGuid();
    DecisionReceipt receipt;
    Guid attemptId;
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        receipt = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), point, InformationRegime.NoSl));
        attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), receipt.DecisionId, attemptId, 0,
            receipt.ActionKeys[0], new PolicyTrace(ActionActor.Human)));

        session.RecordManualCombatInput(new ManualCombatInputInput(
            Guid.NewGuid(), structuredIntent, 101, "play_card",
            JsonSerializer.SerializeToElement(new { card = "first" }),
            receipt.DecisionId, attemptId));
        session.RecordManualCombatInput(new ManualCombatInputInput(
            Guid.NewGuid(), queuedIntent, 102, "play_card",
            JsonSerializer.SerializeToElement(new
            {
                card = "second",
                parent_decision_id = receipt.DecisionId,
                parent_attempt_id = attemptId,
            })));
        session.RecordManualCombatInput(new ManualCombatInputInput(
            Guid.NewGuid(), unresolvedIntent, 103, "use_potion",
            JsonSerializer.SerializeToElement(new { potion = "pending" })));
        Assert(session.Snapshot.Phase == EpisodePhase.AwaitingExecution,
            "Queued manual inputs must leave the structured pending action intact.");
        Assert(session.Snapshot.ManualCombatInputCount == 3
               && session.Snapshot.UnresolvedManualCombatInputCount == 3
               && session.Snapshot.UnstructuredManualCombatInputCount == 2,
            "Manual input integrity counts were not updated.");

        session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
            Guid.NewGuid(), queuedIntent, 102,
            CollectorExecutionStatus.ObservedTransition,
            Data: JsonSerializer.SerializeToElement(new { executed_after = 101 })));
        var beforeDuplicate = ReadJournalLines(store.GetOpenEpisodePath(episodeId)).Count();
        AssertThrows<InvalidDataException>(() => session.RecordManualCombatInputOutcome(
            new ManualCombatInputOutcomeInput(
                Guid.NewGuid(), queuedIntent, 102, CollectorExecutionStatus.Applied)));
        Assert(ReadJournalLines(store.GetOpenEpisodePath(episodeId)).Count() == beforeDuplicate,
            "A duplicate manual outcome must be rejected before durable append.");
        session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
            Guid.NewGuid(), structuredIntent, 101, CollectorExecutionStatus.Applied));

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), receipt.DecisionId, attemptId, 0,
            receipt.ActionKeys[0], point.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            NextStateFingerprint: Fingerprint('b')));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), receipt.DecisionId, "reward-v1",
            new Dictionary<string, double> { ["terminal"] = 0 }));
    }

    using (var resumed = store.ResumeEpisode(episodeId))
    {
        Assert(resumed.Snapshot.Phase == EpisodePhase.Ready,
            "Replay lost the settled structured decision.");
        Assert(resumed.Snapshot.ManualCombatInputCount == 3
               && resumed.Snapshot.UnresolvedManualCombatInputCount == 1
               && resumed.Snapshot.UnstructuredManualCombatInputCount == 2
               && resumed.Snapshot.UnstructuredUnsafeManualCombatInputCount == 1,
            "Replay lost manual input intent/outcome correlation.");
        resumed.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "smoke_queue",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    for (var index = 0; index < events.Count; index++)
    {
        Assert(events[index].EventSequence == index, "Queued event sequence is discontinuous.");
        Assert(events[index].PreviousEventSha256 == (index == 0
                ? CollectorJson.InitialPreviousHash
                : events[index - 1].EventSha256),
            "Queued input broke the durable hash chain.");
    }

    Assert(events.Where(item => item.EventType is
            CollectorEventType.ManualCombatInput or CollectorEventType.ManualCombatInputOutcome)
        .All(item => item.GlobalStep is null),
        "Raw manual input events must not create a policy global step.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.Completeness == EpisodeCompleteness.Incomplete
           && !finished.ValueTargetValid
           && finished.UnresolvedManualCombatInputCount == 1
           && finished.UnstructuredManualCombatInputCount == 2
           && finished.UnstructuredUnsafeManualCombatInputCount == 1,
        "Unstructured or unfinished manual inputs cannot produce a complete value target.");
}

static void RunStructuredQueuedCombatSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var points = new[]
    {
        CreateCombatDecision(20, '1'),
        CreateCombatDecision(21, '2'),
        CreateCombatDecision(22, '3'),
        CreateCombatDecision(23, '4'),
    };
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var decisions = new DecisionReceipt[3];
        var attempts = new Guid[3];
        var intents = new Guid[3];
        for (var index = 0; index < 3; index++)
        {
            var input = DecisionInput.FromCombat(
                Guid.NewGuid(), points[index], InformationRegime.NoSl);
            decisions[index] = index == 0
                ? session.RecordDecision(input)
                : session.RecordQueuedCombatDecision(input);
            attempts[index] = Guid.NewGuid();
            session.SubmitAction(new ActionSubmissionInput(
                Guid.NewGuid(), decisions[index].DecisionId, attempts[index],
                0, decisions[index].ActionKeys[0], new PolicyTrace(ActionActor.Human)));
            intents[index] = Guid.NewGuid();
            session.RecordManualCombatInput(new ManualCombatInputInput(
                Guid.NewGuid(), intents[index], 200 + index, "play_card",
                JsonSerializer.SerializeToElement(new { click_order = index }),
                decisions[index].DecisionId, attempts[index]));
            Assert(decisions[index].GlobalStep == index,
                "Queued combat global steps must follow click order.");
        }

        Assert(session.Snapshot.PendingDecisionCount == 3
               && session.Snapshot.PendingDecisions!.Select(item => item.GlobalStep)
                   .SequenceEqual([0L, 1L, 2L]),
            "The three in-flight decisions were not retained in order.");
        AssertThrows<InvalidDataException>(() => session.RecordDecision(
            DecisionInput.FromCombat(Guid.NewGuid(), points[3], InformationRegime.NoSl)));
        AssertThrows<InvalidDataException>(() => session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), decisions[1].DecisionId, attempts[0], 0,
            decisions[1].ActionKeys[0], points[1].StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            NextStateFingerprint: Fingerprint('5'))));

        // A queued click can be cancelled before the earlier native actions
        // finish; the other decisions must remain in flight.
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), decisions[2].DecisionId, attempts[2], 0,
            decisions[2].ActionKeys[0], points[2].StateFingerprint,
            CollectorExecutionStatus.Cancelled));
        session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
            Guid.NewGuid(), intents[2], 202, CollectorExecutionStatus.Cancelled));
        Assert(session.Snapshot.PendingDecisionCount == 2,
            "Cancelling one queued action invalidated the whole queue.");

        for (var index = 0; index < 2; index++)
        {
            session.RecordExecution(new ExecutionInput(
                Guid.NewGuid(), decisions[index].DecisionId, attempts[index], 0,
                decisions[index].ActionKeys[0], points[index].StateFingerprint,
                CollectorExecutionStatus.ObservedTransition,
                NextStateFingerprint: Fingerprint(index == 0 ? '6' : '7')));
            session.RecordReward(new RewardInput(
                Guid.NewGuid(), decisions[index].DecisionId, "reward-v1",
                new Dictionary<string, double> { ["hp_delta"] = -index }));
            session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
                Guid.NewGuid(), intents[index], 200 + index,
                CollectorExecutionStatus.ObservedTransition));
        }

        // The queued API also works when the core is Ready but a producer is
        // still draining native raw-input evidence.
        var readyQueued = session.RecordQueuedCombatDecision(
            DecisionInput.FromCombat(Guid.NewGuid(), points[3], InformationRegime.NoSl));
        var readyAttempt = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), readyQueued.DecisionId, readyAttempt, 0,
            readyQueued.ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), readyQueued.DecisionId, readyAttempt, 0,
            readyQueued.ActionKeys[0], points[3].StateFingerprint,
            CollectorExecutionStatus.Cancelled));
        Assert(session.Snapshot.PendingDecisionCount == 0
               && session.Snapshot.Phase == EpisodePhase.Ready,
            "The queued sequence did not fully settle.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "defeat", "queued_structured_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var decisionsInFile = events.Where(item => item.EventType == CollectorEventType.Decision)
        .ToArray();
    Assert(decisionsInFile.Select(item => item.GlobalStep)
        .SequenceEqual(new long?[] { 0, 1, 2, 3 }),
        "Structured queued decisions did not preserve monotone global_step.");
    Assert(decisionsInFile.Skip(1).All(item =>
        item.Payload.Deserialize<DecisionPayload>(CollectorJson.Options)!.QueuedCombatInput),
        "Queued decision marker was lost from the journal.");
    Assert(events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options) is
        { Completeness: EpisodeCompleteness.Complete, ValueTargetValid: true },
        "Fully paired queued combat decisions must remain trainable.");
}

static void RunStructuredQueuedOutsideSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var start = CreateStart(episodeId);
    var points = new[]
    {
        CreateOutsideRewardDecision(start.Build, 40, '1'),
        CreateOutsideRewardDecision(start.Build, 41, '2'),
        CreateOutsideRewardDecision(start.Build, 42, '3'),
    };
    var receipts = new DecisionReceipt[3];
    var attempts = new Guid[3];
    using (var session = store.StartEpisode(start))
    {
        var firstInput = DecisionInput.FromOutside(
            Guid.NewGuid(), points[0], InformationRegime.NoSl);
        AssertThrows<InvalidDataException>(() =>
            session.RecordQueuedOutsideDecision(firstInput));
        receipts[0] = session.RecordDecision(firstInput);
        AssertThrows<InvalidDataException>(() =>
            session.RecordQueuedOutsideDecision(DecisionInput.FromOutside(
                Guid.NewGuid(), points[1], InformationRegime.NoSl)));

        for (var index = 0; index < points.Length; index++)
        {
            if (index > 0)
            {
                receipts[index] = session.RecordQueuedOutsideDecision(
                    DecisionInput.FromOutside(
                        Guid.NewGuid(), points[index], InformationRegime.NoSl));
            }

            attempts[index] = Guid.NewGuid();
            session.SubmitAction(new ActionSubmissionInput(
                Guid.NewGuid(), receipts[index].DecisionId, attempts[index],
                0, receipts[index].ActionKeys[0],
                new PolicyTrace(ActionActor.Human)));
            if (index == 1)
            {
                // A native operation may finish before its stable reward
                // boundary while another outside click is already accepted.
                session.RecordExecution(new ExecutionInput(
                    Guid.NewGuid(), receipts[index].DecisionId, attempts[index],
                    0, receipts[index].ActionKeys[0],
                    points[index].StateFingerprint,
                    CollectorExecutionStatus.ObservedTransition,
                    NextStateFingerprint: Fingerprint('5')));
            }
            Assert(receipts[index].GlobalStep == index,
                "Queued outside global steps must follow native input order.");
        }

        AssertThrows<InvalidDataException>(() =>
            session.RecordQueuedOutsideDecision(DecisionInput.FromCombat(
                Guid.NewGuid(), CreateCombatDecision(43, '4'),
                InformationRegime.NoSl)));
        AssertThrows<InvalidDataException>(() =>
            session.RecordQueuedCombatDecision(DecisionInput.FromOutside(
                Guid.NewGuid(), points[2], InformationRegime.NoSl)));
        Assert(session.Snapshot.PendingDecisionCount == 3,
            "Queued outside decisions must remain pending independently.");
    }

    using (var resumed = store.ResumeEpisode(episodeId))
    {
        Assert(resumed.Snapshot.PendingDecisions!.Select(item => item.DecisionId)
                   .SequenceEqual(receipts.Select(item => item.DecisionId)),
            "Partial replay lost queued outside decisions.");
        foreach (var index in new[] { 2, 0, 1 })
        {
            if (index != 1)
            {
                resumed.RecordExecution(new ExecutionInput(
                    Guid.NewGuid(), receipts[index].DecisionId, attempts[index],
                    0, receipts[index].ActionKeys[0],
                    points[index].StateFingerprint,
                    CollectorExecutionStatus.ObservedTransition,
                    NextStateFingerprint: Fingerprint('5')));
            }
            resumed.RecordReward(new RewardInput(
                Guid.NewGuid(), receipts[index].DecisionId, "reward-v1",
                new Dictionary<string, double> { ["hp_delta"] = index }));
        }

        Assert(resumed.Snapshot.PendingDecisionCount == 0
               && resumed.Snapshot.Phase == EpisodePhase.Ready,
            "Out-of-order outside completion left a pending decision.");
        AssertThrows<InvalidDataException>(() =>
            resumed.RecordQueuedOutsideDecision(DecisionInput.FromOutside(
                Guid.NewGuid(), points[2], InformationRegime.NoSl)));
        resumed.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "queued_outside_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var decisions = events.Where(item => item.EventType == CollectorEventType.Decision)
        .ToArray();
    Assert(decisions.Select(item => item.GlobalStep)
               .SequenceEqual(new long?[] { 0, 1, 2 })
           && !decisions[0].Payload.Deserialize<DecisionPayload>(
               CollectorJson.Options)!.QueuedOutsideInput
           && decisions.Skip(1).All(item =>
               item.Payload.Deserialize<DecisionPayload>(
                   CollectorJson.Options)!.QueuedOutsideInput),
        "Queued outside marker or ordered global steps were lost from the journal.");
    Assert(events.Where(item => item.EventType == CollectorEventType.ExecutionResult)
               .Select(item => item.Payload.Deserialize<ExecutionResultPayload>(
                   CollectorJson.Options)!.DecisionId)
               .SequenceEqual(new[]
               {
                   receipts[1].DecisionId,
                   receipts[2].DecisionId,
                   receipts[0].DecisionId,
               }),
        "Outside execution results did not retain independent decision IDs.");
    Assert(events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options) is
        { Completeness: EpisodeCompleteness.Complete, ValueTargetValid: true },
        "Fully paired queued outside decisions must remain trainable.");
}

static OutsideCombatDecisionPoint CreateOutsideRewardDecision(
    BuildIdentity build,
    long decisionIndex,
    char fingerprintCharacter)
{
    var actions = new[]
    {
        new OutsideCombatActionDescriptor(
            "claim_reward:0:gold:37", OutsideCombatActionKind.ClaimReward,
            0, "gold:37"),
        new OutsideCombatActionDescriptor(
            "proceed:1:proceed", OutsideCombatActionKind.Proceed,
            1, "proceed"),
    };
    var observation = new OutsideCombatObservation(
        OutsideCombatObservation.CurrentSchemaVersion,
        OutsideCombatSurfaceKind.Rewards,
        new OutsideCombatChoiceContext(
            "rewards", Fingerprint(fingerprintCharacter),
            OutsideCombatChoicePhase.Default, null, null, 0, false, false),
        1, 1, 1, 0, "Monster", null, null,
        [new OutsideRunPlayerObservation(
            1, "IRONCLAD", 70, 80, 99, 3, [], [],
            [new PotionObservation(0, "POTION.AMBERGRIS")])],
        []);
    return new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        build,
        decisionIndex,
        ProtocolJson.ComputeOutsideStateFingerprint(build, observation, actions),
        observation,
        actions);
}

static void RunQueuedRecoveryAndInvalidationSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var firstPoint = CreateCombatDecision(30, '8');
    var secondPoint = CreateCombatDecision(31, '9');
    DecisionReceipt first;
    DecisionReceipt second;
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        first = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), firstPoint, InformationRegime.NoSl));
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), first.DecisionId, Guid.NewGuid(), 0,
            first.ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        second = session.RecordQueuedCombatDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), secondPoint, InformationRegime.NoSl));
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), second.DecisionId, Guid.NewGuid(), 0,
            second.ActionKeys[0], new PolicyTrace(ActionActor.Human)));
    }

    var partialPath = store.GetOpenEpisodePath(episodeId);
    using (var tornAppend = new FileStream(
               partialPath, FileMode.Append, FileAccess.Write, FileShare.Read))
    {
        tornAppend.Write(Encoding.UTF8.GetBytes("{\"torn\":"));
        tornAppend.Flush(flushToDisk: true);
    }

    using (var resumed = store.ResumeEpisode(episodeId))
    {
        Assert(resumed.Snapshot.PendingDecisionCount == 2
               && resumed.Snapshot.PendingDecisions!.Select(item => item.DecisionId)
                   .SequenceEqual([first.DecisionId, second.DecisionId]),
            "Partial replay lost the ordered in-flight decisions.");
        resumed.MarkSaveLoad(new SaveLoadInput(
            Guid.NewGuid(), SaveLoadKind.Resume, "queue_resume_fixture"));
        Assert(resumed.Snapshot.InvalidatedPendingCount == 2
               && resumed.Snapshot.PendingDecisionCount == 0,
            "Save/load did not explicitly invalidate both in-flight decisions.");
        resumed.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "abandoned", "queue_resume_fixture",
            EpisodeCompleteness.Incomplete));
    }

    var events = store.ReadEpisode(episodeId);
    var load = events.Single(item => item.EventType == CollectorEventType.SaveLoad)
        .Payload.Deserialize<SaveLoadPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Save/load payload is absent.");
    Assert(load.InvalidatedDecisions is { Count: 2 }
           && load.InvalidatedDecisions[0].DecisionId == first.DecisionId
           && load.InvalidatedDecisions[1].DecisionId == second.DecisionId,
        "Save/load omitted the exact decisions it invalidated.");
    for (var index = 0; index < events.Count; index++)
    {
        Assert(events[index].EventSequence == index
               && events[index].PreviousEventSha256 == (index == 0
                   ? CollectorJson.InitialPreviousHash
                   : events[index - 1].EventSha256),
            "Queued partial recovery broke the event hash chain.");
    }
}

static void RunOutOfOrderNestedQueuedCombatSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var points = new[]
    {
        CreateCombatDecision(50, '1'),
        CreateCombatDecision(51, '2'),
        CreateCombatDecision(52, '3'),
    };
    DecisionReceipt[] decisions = new DecisionReceipt[3];
    Guid[] attempts = new Guid[3];
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        for (var index = 0; index < 2; index++)
        {
            var input = DecisionInput.FromCombat(
                Guid.NewGuid(), points[index], InformationRegime.NoSl);
            decisions[index] = index == 0
                ? session.RecordDecision(input)
                : session.RecordQueuedCombatDecision(input);
            attempts[index] = Guid.NewGuid();
            session.SubmitAction(new ActionSubmissionInput(
                Guid.NewGuid(), decisions[index].DecisionId, attempts[index],
                0, decisions[index].ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        }

        // A is the older native action. Its effect opens a child choice C,
        // while B was already clicked and waits in the action queue.
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), decisions[0].DecisionId, attempts[0], 0,
            decisions[0].ActionKeys[0], points[0].StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            NextStateFingerprint: Fingerprint('4')));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), decisions[0].DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0 }));

        decisions[2] = session.RecordQueuedCombatDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), points[2], InformationRegime.NoSl));
        attempts[2] = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), decisions[2].DecisionId, attempts[2], 0,
            decisions[2].ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        Assert(session.Snapshot.PendingDecisionId == decisions[1].DecisionId
               && session.Snapshot.PendingDecisionCount == 2,
            "The older queued action B was lost when child choice C appeared.");

        foreach (var index in new[] { 2, 1 })
        {
            session.RecordExecution(new ExecutionInput(
                Guid.NewGuid(), decisions[index].DecisionId, attempts[index], 0,
                decisions[index].ActionKeys[0], points[index].StateFingerprint,
                CollectorExecutionStatus.ObservedTransition,
                NextStateFingerprint: Fingerprint(index == 2 ? '5' : '6')));
            session.RecordReward(new RewardInput(
                Guid.NewGuid(), decisions[index].DecisionId, "reward-v1",
                new Dictionary<string, double> { ["hp_delta"] = 0 }));
        }

        Assert(session.Snapshot.PendingDecisionCount == 0,
            "Out-of-order native settlement left a hidden pending decision.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "defeat", "nested_queue_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    Assert(events.Where(item => item.EventType == CollectorEventType.Decision)
            .Select(item => item.GlobalStep).SequenceEqual(new long?[] { 0, 1, 2 }),
        "A/B/C click order changed in the journal.");
    var resultIds = events.Where(item => item.EventType == CollectorEventType.ExecutionResult)
        .Select(item => item.Payload.Deserialize<ExecutionResultPayload>(CollectorJson.Options)!
            .DecisionId).ToArray();
    Assert(resultIds.SequenceEqual(new[]
        { decisions[0].DecisionId, decisions[2].DecisionId, decisions[1].DecisionId }),
        "A/C/B native result order did not survive replay.");
    Assert(events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options) is
        { ValueTargetValid: true },
        "A fully paired nested queue was misclassified as incomplete.");
}

static void RunCancelledUnstructuredInputSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var intentId = Guid.NewGuid();
        session.RecordManualCombatInput(new ManualCombatInputInput(
            Guid.NewGuid(), intentId, 300, "play_card",
            JsonSerializer.SerializeToElement(new { click_order = 0 })));
        session.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
            Guid.NewGuid(), intentId, 300, CollectorExecutionStatus.Cancelled));
        Assert(session.Snapshot.UnstructuredManualCombatInputCount == 1
               && session.Snapshot.UnstructuredUnsafeManualCombatInputCount == 0
               && session.Snapshot.UnresolvedManualCombatInputCount == 0,
            "A cleanly cancelled raw click was counted as an unsafe transition.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "defeat", "clean_cancel_fixture",
            EpisodeCompleteness.Complete));
    }

    var finished = store.ReadEpisode(episodeId)[^1].Payload
        .Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.Completeness == EpisodeCompleteness.Complete
           && finished.ValueTargetValid
           && finished.UnstructuredManualCombatInputCount == 1
           && finished.UnstructuredUnsafeManualCombatInputCount == 0,
        "A cancelled input without effects must remain audit-only.");
}

static void RunQueuedCoverageGapSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var firstPoint = CreateCombatDecision(40, 'a');
    var secondPoint = CreateCombatDecision(41, 'b');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var first = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), firstPoint, InformationRegime.NoSl));
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), first.DecisionId, Guid.NewGuid(), 0,
            first.ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        var second = session.RecordQueuedCombatDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), secondPoint, InformationRegime.NoSl));
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), second.DecisionId, Guid.NewGuid(), 0,
            second.ActionKeys[0], new PolicyTrace(ActionActor.Human)));

        session.RecordCoverageGap(new CoverageGapInput(
            Guid.NewGuid(), "unverifiable_native_batch"));
        Assert(session.Snapshot.PendingDecisionCount == 0
               && session.Snapshot.CoverageGapCount == 1,
            "A coverage gap failed to invalidate the whole affected queue.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "defeat", "queued_gap_fixture",
            EpisodeCompleteness.Incomplete));
    }

    var events = store.ReadEpisode(episodeId);
    var gap = events.Single(item => item.EventType == CollectorEventType.CoverageGap)
        .Payload.Deserialize<CoverageGapPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Coverage gap payload is absent.");
    Assert(gap.InvalidatedDecisions is { Count: 2 }
           && gap.InvalidatedDecisions[0].GlobalStep == 0
           && gap.InvalidatedDecisions[1].GlobalStep == 1,
        "Coverage gap did not identify every invalidated queued step.");
    Assert(events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options) is
        { ValueTargetValid: false },
        "A queued coverage gap was accepted as a complete value target.");
}

static void RunTargetedQueuedCoverageGapSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var points = new[]
    {
        CreateCombatDecision(60, '1'),
        CreateCombatDecision(61, '2'),
        CreateCombatDecision(62, '3'),
    };
    DecisionReceipt[] decisions = new DecisionReceipt[3];
    Guid[] attempts = new Guid[3];
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        for (var index = 0; index < 2; index++)
        {
            var input = DecisionInput.FromCombat(
                Guid.NewGuid(), points[index], InformationRegime.NoSl);
            decisions[index] = index == 0
                ? session.RecordDecision(input)
                : session.RecordQueuedCombatDecision(input);
            attempts[index] = Guid.NewGuid();
            session.SubmitAction(new ActionSubmissionInput(
                Guid.NewGuid(), decisions[index].DecisionId, attempts[index], 0,
                decisions[index].ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        }

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), decisions[0].DecisionId, attempts[0], 0,
            decisions[0].ActionKeys[0], points[0].StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            NextStateFingerprint: Fingerprint('4')));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), decisions[0].DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0 }));

        decisions[2] = session.RecordQueuedCombatDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), points[2], InformationRegime.NoSl));
        attempts[2] = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), decisions[2].DecisionId, attempts[2], 0,
            decisions[2].ActionKeys[0], new PolicyTrace(ActionActor.Human)));
        Assert(session.Snapshot.PendingDecisionCount == 2,
            "B and child C should both be pending before the selector failure.");

        var countBeforeInvalidTarget = ReadJournalLines(
            store.GetOpenEpisodePath(episodeId)).Count();
        AssertThrows<InvalidDataException>(() => session.RecordCoverageGap(
            new CoverageGapInput(Guid.NewGuid(), "invalid_target",
                TargetDecisionId: Guid.NewGuid())));
        Assert(ReadJournalLines(store.GetOpenEpisodePath(episodeId)).Count()
               == countBeforeInvalidTarget,
            "An invalid target gap must be rejected before durable append.");

        session.RecordCoverageGap(new CoverageGapInput(
            Guid.NewGuid(), "nested_selector_task_failed",
            TargetDecisionId: decisions[2].DecisionId));
        Assert(session.Snapshot.PendingDecisionCount == 1
               && session.Snapshot.PendingDecisionId == decisions[1].DecisionId,
            "Targeting C incorrectly invalidated the queued native action B.");

        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), decisions[1].DecisionId, attempts[1], 0,
            decisions[1].ActionKeys[0], points[1].StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            NextStateFingerprint: Fingerprint('5')));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), decisions[1].DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0 }));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "defeat", "targeted_gap_fixture",
            EpisodeCompleteness.Incomplete));
    }

    var events = store.ReadEpisode(episodeId);
    var gap = events.Single(item => item.EventType == CollectorEventType.CoverageGap)
        .Payload.Deserialize<CoverageGapPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Targeted gap payload is absent.");
    Assert(gap.TargetDecisionId == decisions[2].DecisionId
           && gap.InvalidatedDecisionId == decisions[2].DecisionId
           && gap.InvalidatedDecisions is { Count: 1 }
           && gap.InvalidatedDecisions[0].DecisionId == decisions[2].DecisionId,
        "Targeted gap failed to identify only child C.");
    Assert(events.Any(item => item.EventType == CollectorEventType.Reward
        && item.Payload.Deserialize<RewardPayload>(CollectorJson.Options)!.DecisionId
            == decisions[1].DecisionId),
        "Queued native action B did not survive the child C gap.");
}

static void RunTamperDetectionSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (store.StartEpisode(CreateStart(episodeId)))
    {
    }

    var partialPath = store.GetOpenEpisodePath(episodeId);
    var jsonl = File.ReadAllText(partialPath);
    var tampered = jsonl.Replace(
        "\"collector_revision\":\"smoke-revision\"",
        "\"collector_revision\":\"tampered-revision\"",
        StringComparison.Ordinal);
    Assert(tampered != jsonl, "Tamper fixture did not alter the persisted event.");
    File.WriteAllText(partialPath, tampered, new UTF8Encoding(false));

    AssertThrows<InvalidDataException>(() =>
    {
        using var ignored = store.ResumeEpisode(episodeId);
    });
}

static void RunRewindSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        session.MarkSaveLoad(new SaveLoadInput(
            Guid.NewGuid(),
            SaveLoadKind.Rewind,
            "explicit_user_sl"));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "rewind_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.RewindCount == 1, "Explicit rewind count was lost.");
    Assert(!finished.ValueTargetValid, "Explicit rewind must invalidate the value target.");
}

static void RunPendingGapSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var decision = CreateCombatDecision(decisionIndex: 9, fingerprintCharacter: '9');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var receipt = session.RecordDecision(
            DecisionInput.FromCombat(
                Guid.NewGuid(),
                decision,
                InformationRegime.NoSl));
        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            new PolicyTrace(ActionActor.Policy, "gap-smoke")));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.Applied,
            NextStateFingerprint: Fingerprint('8')));

        // A normal continue is not SL, but crossing it with an unresolved
        // decision creates a factual training-data gap (the reward is lost).
        session.MarkSaveLoad(new SaveLoadInput(
            Guid.NewGuid(),
            SaveLoadKind.Resume,
            "resume_before_reward"));
        Assert(
            session.Snapshot.InvalidatedPendingCount == 1,
            "Reload must retain evidence that it invalidated a pending label.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "pending_gap_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.RewindCount == 0, "Normal resume was incorrectly marked as rewind.");
    Assert(finished.InvalidatedPendingCount == 1, "Pending data gap was lost.");
    Assert(!finished.ValueTargetValid, "A trajectory with a pending gap is not value-complete.");
}

static void RunInterruptedPublicationSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "abandoned",
            "publication_fixture",
            EpisodeCompleteness.Incomplete));
    }

    var completed = store.GetCompletedEpisodePath(episodeId);
    var partial = store.GetOpenEpisodePath(episodeId);
    File.Move(completed, partial);

    using var recovered = store.ResumeEpisode(episodeId);
    Assert(!recovered.CanAppend, "Recovered finished episode must not appear writable.");
    Assert(!recovered.Snapshot.CanAppend, "Snapshot must expose the finished recovery state.");
    Assert(recovered.Snapshot.IsPublished, "Recovery did not complete interrupted publication.");
    Assert(File.Exists(completed), "Recovered finish was not republished.");
    Assert(!File.Exists(partial), "Recovered finish left a partial file behind.");
}

static void RunResumeMismatchSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
        session.RecordDiagnostic("segment_ended", JsonSerializer.SerializeToElement(new { reason = "process_exit" }));
    using (var resumed = store.ResumeEpisode(episodeId))
    {
        var details = new ResumeCheckpointMismatch(true, 1, resumed.Snapshot.NextEventSequence, false);
        resumed.RecordDiagnostic("interrupted_episode", JsonSerializer.SerializeToElement(
            new { reason = "resume_checkpoint_mismatch", details }, CollectorJson.Options));
        resumed.RecordCoverageGap(new CoverageGapInput(Guid.NewGuid(), "resume_checkpoint_mismatch"));
        resumed.Finish(new EpisodeFinishInput(Guid.NewGuid(), "interrupted", "resume_checkpoint_mismatch",
            EpisodeCompleteness.Incomplete, JsonSerializer.SerializeToElement(details, CollectorJson.Options)));
    }
    var finished = store.ReadEpisode(episodeId)[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)!;
    Assert(finished.Completeness == EpisodeCompleteness.Incomplete && !finished.ValueTargetValid,
        "A mismatched checkpoint must publish an explicitly incomplete segment.");
    RunCompletedEpisodeSmoke(store);
}

static void RunPublicationNamingSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var start = CreateStart(episodeId) with
    {
        Source = CollectorSource.Live,
        Metadata = new Dictionary<string, string>
        {
            ["steam_id64"] = "76561198000000001",
            ["character_id"] = "CHARACTER.IRONCLAD",
            ["ascension"] = "20",
            ["run_started_at_utc"] = "2026-09-27T03:04:05.6780000+00:00",
        },
    };
    var expectedName =
        $"76561198000000001_IRONCLAD_A20_20260927T030405678Z_{episodeId:N}.jsonl";
    var open = store.GetOpenEpisodePath(episodeId);
    using (var session = store.StartEpisode(start))
    {
        Assert(Path.GetFileName(open) == $"{episodeId:N}.jsonl.partial",
            "The active partial path must keep its UUID for sidecar resume.");
        Assert(Path.GetFileName(store.GetCompletedEpisodePath(episodeId)) == expectedName,
            "The planned publication path did not use run metadata.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "abandoned", "naming_fixture", EpisodeCompleteness.Incomplete));
    }

    var completed = Path.Combine(store.RootDirectory, "episodes", expectedName);
    Assert(File.Exists(completed) && !File.Exists(open),
        "The named file was not atomically published from its UUID partial.");
    var reopened = new CollectorStore(store.RootDirectory);
    Assert(reopened.GetCompletedEpisodePath(episodeId) == completed,
        "A new store must resolve the named episode by its ID.");
    Assert(reopened.ReadEpisode(episodeId)[^1].EventType == CollectorEventType.EpisodeFinished,
        "The named episode must remain readable and hash-valid.");

    var fallbackId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(fallbackId)))
    {
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "abandoned", "fallback_fixture", EpisodeCompleteness.Incomplete));
    }

    var fallbackPath = store.GetCompletedEpisodePath(fallbackId);
    var fallbackStart = store.ReadEpisode(fallbackId)[0];
    var fallbackStamp = fallbackStart.RecordedAtUtc.ToUniversalTime()
        .ToString("yyyyMMdd'T'HHmmssfff'Z'", System.Globalization.CultureInfo.InvariantCulture);
    Assert(Path.GetFileName(fallbackPath)
           == $"steam-unavailable_unknown_Aunknown_{fallbackStamp}_{fallbackId:N}.jsonl",
        "Missing headless metadata must use explicit fallback components and first-event UTC.");

    var legacyId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(legacyId)))
    {
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "abandoned", "legacy_fixture", EpisodeCompleteness.Incomplete));
    }

    var legacyPath = Path.Combine(store.RootDirectory, "episodes", $"{legacyId:N}.jsonl");
    File.Move(store.GetCompletedEpisodePath(legacyId), legacyPath);
    Assert(new CollectorStore(store.RootDirectory).GetCompletedEpisodePath(legacyId)
           == legacyPath,
        "A legacy UUID publication must remain discoverable.");
    Assert(store.ReadEpisode(legacyId)[^1].EventType == CollectorEventType.EpisodeFinished,
        "A legacy UUID publication must remain readable.");

    var resumedId = Guid.NewGuid();
    using (store.StartEpisode(CreateStart(resumedId)))
    {
    }

    using (var resumed = new CollectorStore(store.RootDirectory).ResumeEpisode(resumedId))
    {
        resumed.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "abandoned", "resume_fixture", EpisodeCompleteness.Incomplete));
    }

    Assert(File.Exists(store.GetCompletedEpisodePath(resumedId)),
        "A fresh store must reconstruct the named publication path from the UUID partial.");
}

static void RunStaleGapSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var decision = CreateCombatDecision(decisionIndex: 10, fingerprintCharacter: '7');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var receipt = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(),
            decision,
            InformationRegime.NoSl));
        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            new PolicyTrace(ActionActor.Policy, "stale-smoke")));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.Stale,
            Detail: "Expected observation no longer current."));
        Assert(
            session.Snapshot.UncertainExecutionCount == 1,
            "Stale execution must retain an integrity gap.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "stale_gap_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.UncertainExecutionCount == 1, "Stale integrity gap was lost.");
    Assert(!finished.ValueTargetValid, "A trajectory with stale transition is not value-complete.");
}

static void RunCoverageGapSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var decision = CreateCombatDecision(decisionIndex: 11, fingerprintCharacter: '6');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(),
            decision,
            InformationRegime.NoSl));
        session.RecordCoverageGap(new CoverageGapInput(
            Guid.NewGuid(),
            "unsupported_semantic_choice"));
        Assert(
            session.Snapshot.Phase == EpisodePhase.Ready,
            "Coverage gap must invalidate and release a pending decision.");
        Assert(
            session.Snapshot.CoverageGapCount == 1,
            "Coverage gap count was not retained.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "coverage_gap_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var gap = events.Single(item => item.EventType == CollectorEventType.CoverageGap)
        .Payload.Deserialize<CoverageGapPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Coverage-gap payload is absent.");
    Assert(gap.InvalidatesPendingDecision, "Pending decision was not marked invalidated.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.CoverageGapCount == 1, "Finish lost the coverage-gap count.");
    Assert(!finished.ValueTargetValid, "Coverage-gapped episode cannot be value-complete.");
}

static void RunDetachedCoverageGapSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var decision = CreateCombatDecision(decisionIndex: 12, fingerprintCharacter: '5');
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var receipt = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(),
            decision,
            InformationRegime.NoSl));
        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            new PolicyTrace(ActionActor.Human, "detached-gap-smoke")));
        session.RecordCoverageGap(new CoverageGapInput(
            Guid.NewGuid(),
            "late_parent_failure",
            InvalidatePendingDecision: false,
            RelatedDecisionId: receipt.DecisionId,
            RelatedAttemptId: attemptId));
        Assert(
            session.Snapshot.Phase == EpisodePhase.AwaitingExecution,
            "A detached gap must not invalidate an unrelated current decision.");
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            0,
            receipt.ActionKeys[0],
            decision.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            "reward-v1",
            new Dictionary<string, double> { ["terminal"] = 0 }));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "detached_gap_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var gap = events.Single(item => item.EventType == CollectorEventType.CoverageGap)
        .Payload.Deserialize<CoverageGapPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Detached gap payload is absent.");
    Assert(!gap.InvalidatesPendingDecision, "Detached gap unexpectedly invalidated a decision.");
    Assert(gap.InvalidatedDecisionId is null, "Detached gap references an unrelated decision.");
    Assert(gap.RelatedDecisionId is not null && gap.RelatedAttemptId is not null,
        "Detached gap lost its prior-action reference.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(!finished.ValueTargetValid, "Detached integrity gap must invalidate the value target.");
}

static void RunCombatNestedChoiceBoundarySmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var parentDecision = CreateCombatDecision(20, '2');
    var childDecision = CreateCombatChoiceDecision(21, '3');
    Guid parentDecisionId;
    Guid childDecisionId;
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var parent = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), parentDecision, InformationRegime.NoSl));
        parentDecisionId = parent.DecisionId;
        var parentAttemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), parent.DecisionId, parentAttemptId, 0,
            parent.ActionKeys[0], new PolicyTrace(ActionActor.Human, "human-demonstration")));

        // The journal is linear: a nested choice can start only after the
        // accepted parent action has a result and reward at this boundary.
        var eventsBeforeInvalidChild = session.Snapshot.NextEventSequence;
        AssertThrows<InvalidDataException>(() => session.RecordDecision(
            DecisionInput.FromCombat(
                Guid.NewGuid(), childDecision, InformationRegime.NoSl)));
        Assert(session.Snapshot.NextEventSequence == eventsBeforeInvalidChild,
            "A premature child choice must not be appended to the journal.");
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), parent.DecisionId, parentAttemptId, 0,
            parent.ActionKeys[0], parentDecision.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition,
            Detail: "Parent action accepted before its nested choice."));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), parent.DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0 }));

        var child = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), childDecision, InformationRegime.NoSl));
        childDecisionId = child.DecisionId;
        Assert(child.GlobalStep == parent.GlobalStep + 1,
            "Nested choice must follow the parent on the global timeline.");
        var childAttemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), child.DecisionId, childAttemptId, 0,
            child.ActionKeys[0], new PolicyTrace(ActionActor.Human, "human-demonstration")));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), child.DecisionId, childAttemptId, 0,
            child.ActionKeys[0], childDecision.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), child.DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = -1 }));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "nested_choice_boundary_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    Assert(events.Select(item => item.EventType).SequenceEqual(
        [
            CollectorEventType.EpisodeStarted,
            CollectorEventType.Decision,
            CollectorEventType.ActionSubmitted,
            CollectorEventType.ExecutionResult,
            CollectorEventType.Reward,
            CollectorEventType.Decision,
            CollectorEventType.ActionSubmitted,
            CollectorEventType.ExecutionResult,
            CollectorEventType.Reward,
            CollectorEventType.EpisodeFinished,
        ]), "Nested choice events are not paired in parent-then-child order.");
    Assert(events[3].Payload.Deserialize<ExecutionResultPayload>(CollectorJson.Options)
        ?.DecisionId == parentDecisionId,
        "The parent execution result was paired with the wrong decision.");
    Assert(events[7].Payload.Deserialize<ExecutionResultPayload>(CollectorJson.Options)
        ?.DecisionId == childDecisionId,
        "The child execution result was paired with the wrong decision.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.ValueTargetValid && finished.CoverageGapCount == 0,
        "A complete nested-choice trajectory must keep a valid value target.");
}

static void RunCombatNestedChoiceLateFailureSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var parentDecision = CreateCombatDecision(22, '4');
    var childDecision = CreateCombatChoiceDecision(23, '5');
    Guid parentDecisionId;
    Guid parentAttemptId;
    Guid childDecisionId;
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        var parent = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), parentDecision, InformationRegime.NoSl));
        parentDecisionId = parent.DecisionId;
        parentAttemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), parent.DecisionId, parentAttemptId, 0,
            parent.ActionKeys[0], new PolicyTrace(ActionActor.Human, "human-demonstration")));
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), parent.DecisionId, parentAttemptId, 0,
            parent.ActionKeys[0], parentDecision.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), parent.DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = 0 }));

        var child = session.RecordDecision(DecisionInput.FromCombat(
            Guid.NewGuid(), childDecision, InformationRegime.NoSl));
        childDecisionId = child.DecisionId;
        var childAttemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(), child.DecisionId, childAttemptId, 0,
            child.ActionKeys[0], new PolicyTrace(ActionActor.Human, "human-demonstration")));

        // Native parent completion may fail after its accepted result was
        // flushed. Link the gap to that parent without discarding the child.
        session.RecordCoverageGap(new CoverageGapInput(
            Guid.NewGuid(), "accepted_parent_task_later_failed",
            InvalidatePendingDecision: false,
            RelatedDecisionId: parent.DecisionId,
            RelatedAttemptId: parentAttemptId));
        Assert(session.Snapshot.Phase == EpisodePhase.AwaitingExecution
               && session.Snapshot.PendingDecisionId == child.DecisionId,
            "A late parent failure must not invalidate the current child choice.");
        session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(), child.DecisionId, childAttemptId, 0,
            child.ActionKeys[0], childDecision.StateFingerprint,
            CollectorExecutionStatus.ObservedTransition));
        session.RecordReward(new RewardInput(
            Guid.NewGuid(), child.DecisionId, "reward-v1",
            new Dictionary<string, double> { ["hp_delta"] = -1 }));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "nested_choice_late_failure_fixture",
            EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(episodeId);
    var gap = events.Single(item => item.EventType == CollectorEventType.CoverageGap)
        .Payload.Deserialize<CoverageGapPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Coverage-gap payload is absent.");
    Assert(!gap.InvalidatesPendingDecision
           && gap.RelatedDecisionId == parentDecisionId
           && gap.RelatedAttemptId == parentAttemptId
           && gap.InvalidatedDecisionId is null,
        "Late failure must reference the settled parent without invalidating the child.");
    Assert(events.Count(item => item.EventType == CollectorEventType.ExecutionResult
                                && item.Payload.Deserialize<ExecutionResultPayload>(
                                    CollectorJson.Options)?.DecisionId == childDecisionId) == 1,
        "The child choice lost its execution result after the parent failure.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(finished.CoverageGapCount == 1 && !finished.ValueTargetValid,
        "A late parent failure must invalidate the whole-run value target.");
}

static void RunUnknownLoadSemanticsSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        session.MarkSaveLoad(new SaveLoadInput(
            Guid.NewGuid(),
            SaveLoadKind.Unknown,
            "unknown_load_fixture"));
        Assert(
            session.Snapshot.UnknownSaveLoadCount == 1,
            "Unknown load count was not retained.");
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "victory",
            "unknown_load_fixture",
            EpisodeCompleteness.Complete));
    }

    var finished = store.ReadEpisode(episodeId)[^1].Payload
        .Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(!finished.ValueTargetValid, "Unknown load must invalidate the value target.");
}

static void RunAbandonedCompletenessSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    using (var session = store.StartEpisode(CreateStart(episodeId)))
    {
        AssertThrows<InvalidDataException>(() => session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "abandoned",
            "invalid_complete_abandon_fixture",
            EpisodeCompleteness.Complete)));
        session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "abandoned",
            "abandon_fixture",
            EpisodeCompleteness.Incomplete));
    }

    var finished = store.ReadEpisode(episodeId)[^1].Payload
        .Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Finish payload is absent.");
    Assert(!finished.ValueTargetValid, "Abandoned run cannot have a valid value target.");
}

static void RunOutsideCardSetTemplateSmoke(CollectorStore store)
{
    var episodeId = Guid.NewGuid();
    var start = CreateStart(episodeId);
    var candidates = Enumerable.Range(0, 19)
        .Select(index => new OutsideSelectedCardReference(
            index, $"CARD_{index}", index)).ToArray();
    var observation = new OutsideCombatObservation(
        OutsideCombatObservation.CurrentSchemaVersion,
        OutsideCombatSurfaceKind.CardGridChoice,
        new OutsideCombatChoiceContext(
            "event:remove_four", Fingerprint('d'),
            OutsideCombatChoicePhase.Selection, 4, 4, 0, false, true),
        1, 1, 1, 0, "Event", null, null,
        [new OutsideRunPlayerObservation(
            1, "IRONCLAD", 70, 80, 99, 3,
            candidates.Select(card => new OutsideRunCardObservation(
                card.DeckIndex!.Value, card.ModelId, 0, null, null)).ToArray(),
            [], [])],
        [])
    {
        CardSelectionOptions = candidates,
    };
    var template = new OutsideCombatActionDescriptor(
        "remove_card_set:0:set", OutsideCombatActionKind.RemoveCardSet, 0)
    {
        IsSelectionTemplate = true,
    };
    var legal = new[] { template };
    var decision = new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        start.Build,
        0,
        ProtocolJson.ComputeOutsideStateFingerprint(start.Build, observation, legal),
        observation,
        legal);
    decision.Validate();
    Assert(decision.LegalActions.Count == 1
           && decision.Observation.CardSelectionOptions?.Count == 19,
        "Nineteen choose four must remain one set template with nineteen candidates.");
    AssertThrows<InvalidDataException>(() =>
        (observation with
        {
            CardSelectionOptions = candidates.Select((card, index) => index == 1
                ? card with { DeckIndex = 0 } : card).ToArray(),
        }).Validate());

    using var session = store.StartEpisode(start);
    var receipt = session.RecordDecision(DecisionInput.FromOutside(
        Guid.NewGuid(), decision, InformationRegime.NoSl));
    var chosen = new[] { 0, 4, 11, 18 };
    var concrete = template with
    {
        IsSelectionTemplate = false,
        SelectedCards = chosen.Select(index => candidates[index]).ToArray(),
    };
    var policy = new PolicyTrace(ActionActor.Human, "human-demonstration");
    ActionSubmissionInput Submission(OutsideCombatActionDescriptor? action) => new(
        Guid.NewGuid(), receipt.DecisionId, Guid.NewGuid(), 0,
        receipt.ActionKeys[0], policy,
        action is null ? null : JsonSerializer.SerializeToElement(
            action, CollectorJson.Options));
    AssertThrows<InvalidDataException>(() => session.SubmitAction(Submission(null)));
    AssertThrows<InvalidDataException>(() => session.SubmitAction(Submission(
        concrete with { SelectedCards = candidates.Take(5).ToArray() })));
    AssertThrows<InvalidDataException>(() => session.SubmitAction(Submission(
        concrete with
        {
            SelectedCards =
            [candidates[0], candidates[4],
                candidates[11] with { ModelId = "FORGED" }, candidates[18]],
        })));
    var submission = Submission(concrete);
    session.SubmitAction(submission);
    session.RecordExecution(new ExecutionInput(
        Guid.NewGuid(), receipt.DecisionId, submission.AttemptId, 0,
        receipt.ActionKeys[0], decision.StateFingerprint,
        CollectorExecutionStatus.Applied, Fingerprint('e')));
    session.RecordReward(new RewardInput(
        Guid.NewGuid(), receipt.DecisionId, "reward-v1",
        new Dictionary<string, double> { ["step"] = 1 }));
    session.Finish(new EpisodeFinishInput(
        Guid.NewGuid(), "victory", "smoke", EpisodeCompleteness.Complete));
    var recorded = store.ReadEpisode(episodeId)
        .Single(item => item.EventType == CollectorEventType.ActionSubmitted)
        .Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options);
    var restored = recorded?.SelectedAction?.Deserialize<OutsideCombatActionDescriptor>(
        CollectorJson.Options);
    Assert(restored?.SelectedCards?.Select(card => card.OptionIndex)
               .SequenceEqual(chosen) == true,
        "Submitted card-set label must survive journal replay with exact option indexes.");
    var compactAction = ReadJournalLines(store.GetCompactEpisodePath(episodeId))
        .Select(line => JsonNode.Parse(line)?.AsObject())
        .Single(row => row?["t"]?.GetValue<string>() == "action");
    var compactOutside = compactAction?["selected_action"]?.Deserialize<
        OutsideCombatActionDescriptor>(CollectorJson.Options);
    Assert(compactOutside?.SelectedCards?.Select(card => card.OptionIndex)
               .SequenceEqual(chosen) == true,
        "Compact view must preserve the concrete outside card-set label.");
}

static EpisodeStartInput CreateStart(Guid episodeId) => new(
    episodeId,
    Guid.NewGuid(),
    CollectorSource.Headless,
    new BuildIdentity(
        "collector-smoke",
        Fingerprint('a'),
        Guid.Parse("6c7d5bf6-d124-45b1-bef7-64a7aaf9d519").ToString("D")),
    "smoke-revision",
    "reward-v1",
    NoSlExpected: true,
    new Dictionary<string, string> { ["purpose"] = "collector-smoke" });

static CombatDecisionPoint CreateCombatDecision(
    long decisionIndex,
    char fingerprintCharacter)
{
    var observation = new CombatObservation(
        CombatObservation.CurrentSchemaVersion,
        RoundNumber: 1,
        CombatSide.Player,
        [
            new CombatPlayerObservation(
                PlayerId: 1,
                CharacterId: "IRONCLAD",
                Energy: 3,
                Stars: 0,
                TurnNumber: 1,
                Phase: "play",
                Piles:
                [
                    new CombatPileObservation(
                        "hand",
                        [new CombatCardObservation(7, "STRIKE", 1, null, 0, [])
                        {
                            UpgradeLevel = 1,
                            Display = new CombatCardDisplayObservation(
                                "Deal 9 damage.",
                                EnergyCost: 1,
                                StarCost: 0,
                                CostsX: false,
                                DynamicValues:
                                [new CombatCardDynamicValueObservation("Damage", 9)]),
                        }]),
                ],
                Relics: [new RelicObservation("PEN_NIB")
                {
                    Display = new RelicDisplayObservation(
                        "Active", false, false, 0, "Next attack deals double damage."),
                }],
                Potions: [],
                Orbs: [])
            {
                Gold = 99,
                OrbCapacity = 3,
            },
        ],
        [new CreatureSnapshot(100, null, "CULTIST", 48, 48, 0, [])])
    {
        EnemyIntents =
        [
            new CombatEnemyIntentObservation(
                100,
                "visible",
                [new CombatIntentObservation("attack", "6", 6, 1)]),
        ],
        Companions =
        [
            new CombatCompanionObservation(1, "OSTY", 17, 20, 0, []),
        ],
    };
    return new CombatDecisionPoint(
        CombatDecisionPoint.CurrentSchemaVersion,
        decisionIndex,
        Fingerprint(fingerprintCharacter),
        observation,
        [
            new CombatActionDescriptor(
                CombatActionKind.PlayCard,
                ActorPlayerId: 1,
                CombatCardIndex: 7,
                TargetCreatureId: 100),
            new CombatActionDescriptor(CombatActionKind.EndTurn, ActorPlayerId: 1),
        ]);
}

static CombatDecisionPoint CreateCombatChoiceDecision(
    long decisionIndex,
    char fingerprintCharacter) => CreateCombatDecision(
        decisionIndex,
        fingerprintCharacter) with
    {
        Observation = CreateCombatDecision(decisionIndex, fingerprintCharacter).Observation with
        {
            ActiveChoice = new CombatChoiceObservation(
                ChoiceId: 42,
                Source: "nested_choice_fixture",
                MinSelections: 0,
                MaxSelections: 1,
                CanCancel: true,
                Cards: [new CombatChoiceCardObservation(7, "STRIKE", 0)]),
        },
        LegalActions =
        [
            new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                ActorPlayerId: 1,
                ChoiceId: 42,
                SelectedCombatCardIds: [7],
                OptionIndex: 0),
            new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                ActorPlayerId: 1,
                ChoiceId: 42,
                SelectedCombatCardIds: [],
                OptionIndex: 1),
        ],
    };

static void RunGeneratedCardChoiceContractSmoke()
{
    var ordinary = CreateCombatDecision(300, 'e');
    var offered = new CombatChoiceObservation(
        ChoiceId: 82,
        Source: "generated_card_fixture",
        MinSelections: 1,
        MaxSelections: 1,
        CanCancel: false,
        Cards:
        [
            new CombatChoiceCardObservation(null, "CARD.CINDER", 0, OptionIndex: 0),
            new CombatChoiceCardObservation(null, "CARD.CINDER", 0, OptionIndex: 1),
        ]);
    var decision = ordinary with
    {
        Observation = ordinary.Observation with { ActiveChoice = offered },
        LegalActions =
        [
            new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                ActorPlayerId: 1,
                ChoiceId: 82,
                OptionIndex: 0),
            new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                ActorPlayerId: 1,
                ChoiceId: 82,
                OptionIndex: 1),
        ],
    };
    decision.Validate();
    var input = DecisionInput.FromCombat(
        Guid.NewGuid(), decision, InformationRegime.NoSl);
    Assert(input.ActionKeys.Distinct(StringComparer.Ordinal).Count() == 2,
        "Two same-model generated cards need distinct selectable action keys.");
    AssertThrows<InvalidDataException>(() =>
        (decision with
        {
            LegalActions =
            [
                new CombatActionDescriptor(
                    CombatActionKind.ResolveChoice,
                    ActorPlayerId: 1,
                    ChoiceId: 82,
                    OptionIndex: 2),
            ],
        }).Validate());
}

static void RunCombatCardSetContractSmoke(CollectorStore store)
{
    var ordinary = CreateCombatDecision(301, 'f');
    var choice = new CombatChoiceObservation(
        ChoiceId: 83,
        Source: "combat_hand_card_selection:POTION.GAMBLERS_BREW:SimpleSelect",
        MinSelections: 0,
        MaxSelections: 5,
        CanCancel: false,
        Cards:
        [
            new CombatChoiceCardObservation(7, "STRIKE", 0, OptionIndex: 0),
            new CombatChoiceCardObservation(14, "STRIKE", 0, OptionIndex: 1),
            new CombatChoiceCardObservation(4, "DEFEND", 0, OptionIndex: 2),
            new CombatChoiceCardObservation(22, "BASH", 0, OptionIndex: 3),
            new CombatChoiceCardObservation(9, "ANGER", 0, OptionIndex: 4),
        ]);
    var actions = CombatChoiceActionBuilder.Build(actorPlayerId: 1, choice);
    Assert(actions.Count == 1 && actions[0].IsSelectionTemplate
           && actions[0].SelectedCombatCardIds is null,
        "A multi-card selector should expose one set template, not every subset.");
    var decision = ordinary with
    {
        Observation = ordinary.Observation with { ActiveChoice = choice },
        LegalActions = actions,
    };
    decision.Validate();
    var displayedChoice = choice with
    {
        Cards = choice.Cards.Select((card, index) => index == 0
            ? card with
            {
                Display = new CombatCardDisplayObservation(
                    "Visible card text", 1, null, false, []),
            }
            : card).ToArray(),
    };
    var displayedJson = JsonSerializer.Serialize(displayedChoice, CollectorJson.Options);
    var restoredChoice = JsonSerializer.Deserialize<CombatChoiceObservation>(
        displayedJson, CollectorJson.Options);
    Assert(restoredChoice?.Cards[0].Display?.Description == "Visible card text"
           && restoredChoice.Cards.Skip(1).All(card => card.Display is null)
           && !JsonSerializer.Serialize(choice, CollectorJson.Options)
               .Contains("\"display\"", StringComparison.Ordinal),
        "Choice card display must round-trip while older null-display choices stay readable.");
    var input = DecisionInput.FromCombat(
        Guid.NewGuid(), decision, InformationRegime.NoSl);
    Assert(input.ActionKeys.Count == 1,
        "The journal should record one action key for a multi-card template.");
    var template = actions[0];
    var fourCards = template with
    {
        IsSelectionTemplate = false,
        SelectedCombatCardIds = [4, 7, 14, 22],
    };
    CombatDecisionPoint.ValidateSubmittedSetAction(
        decision.Observation, template, fourCards);
    CombatDecisionPoint.ValidateSubmittedSetAction(
        decision.Observation, template,
        fourCards with { SelectedCombatCardIds = [] });
    CombatDecisionPoint.ValidateSubmittedSetAction(
        decision.Observation, template,
        fourCards with { SelectedCombatCardIds = [7, 14] });
    AssertThrows<InvalidDataException>(() =>
        CombatDecisionPoint.ValidateSubmittedSetAction(
            decision.Observation, template,
            fourCards with { SelectedCombatCardIds = [7, 7, 14, 22] }));
    AssertThrows<InvalidDataException>(() =>
        CombatDecisionPoint.ValidateSubmittedSetAction(
            decision.Observation, template,
            fourCards with { SelectedCombatCardIds = [4, 7, 14, 22, 99] }));

    var twelveCards = choice with
    {
        Cards = Enumerable.Range(0, 12)
            .Select(index => new CombatChoiceCardObservation(
                (uint)(index + 1), "STRIKE", 0, OptionIndex: index))
            .ToArray(),
        MaxSelections = 12,
    };
    Assert(CombatChoiceActionBuilder.Build(1, twelveCards).Count == 1,
        "Twelve candidates should still require one set template.");
    var thirteenCards = twelveCards with
    {
        Cards = Enumerable.Range(0, 13)
            .Select(index => new CombatChoiceCardObservation(
                (uint)(index + 1), "STRIKE", 0, OptionIndex: index))
            .ToArray(),
        MaxSelections = 13,
    };
    Assert(CombatChoiceActionBuilder.Build(1, thirteenCards).Count == 1,
        "Thirteen candidates must not trigger combinatorial enumeration.");

    var cancelable = choice with { MinSelections = 1, CanCancel = true };
    var cancelableActions = CombatChoiceActionBuilder.Build(1, cancelable);
    Assert(cancelableActions.Count == 2
           && cancelableActions[0].IsSelectionTemplate
           && cancelableActions[1].SelectedCombatCardIds is { Count: 0 },
        "Cancellation must be a separate action when the set requires cards.");
    (decision with
    {
        Observation = ordinary.Observation with { ActiveChoice = cancelable },
        LegalActions = cancelableActions,
    }).Validate();
    AssertThrows<InvalidDataException>(() =>
        CombatDecisionPoint.ValidateSubmittedSetAction(
            ordinary.Observation with { ActiveChoice = cancelable },
            cancelableActions[0],
            cancelableActions[0] with
            {
                IsSelectionTemplate = false,
                SelectedCombatCardIds = [],
            }));

    var episodeId = Guid.NewGuid();
    using var session = store.StartEpisode(CreateStart(episodeId));
    var receipt = session.RecordDecision(DecisionInput.FromCombat(
        Guid.NewGuid(), decision, InformationRegime.NoSl));
    var policy = new PolicyTrace(ActionActor.Human, "human-demonstration");
    ActionSubmissionInput Submission(CombatActionDescriptor? concrete) => new(
        Guid.NewGuid(), receipt.DecisionId, Guid.NewGuid(), 0,
        receipt.ActionKeys[0], policy,
        concrete is null ? null : JsonSerializer.SerializeToElement(
            concrete, CollectorJson.Options));
    AssertThrows<InvalidDataException>(() => session.SubmitAction(Submission(null)));
    var submission = Submission(fourCards);
    session.SubmitAction(submission);
    session.RecordExecution(new ExecutionInput(
        Guid.NewGuid(), receipt.DecisionId, submission.AttemptId, 0,
        receipt.ActionKeys[0], decision.StateFingerprint,
        CollectorExecutionStatus.Applied, Fingerprint('a')));
    session.RecordReward(new RewardInput(
        Guid.NewGuid(), receipt.DecisionId, "reward-v1",
        new Dictionary<string, double> { ["step"] = 1 }));
    session.Finish(new EpisodeFinishInput(
        Guid.NewGuid(), "victory", "smoke", EpisodeCompleteness.Complete));
    var recorded = store.ReadEpisode(episodeId)
        .Single(item => item.EventType == CollectorEventType.ActionSubmitted)
        .Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options);
    var restored = recorded?.SelectedAction?.Deserialize<CombatActionDescriptor>(
        CollectorJson.Options);
    Assert(restored?.SelectedCombatCardIds?.SequenceEqual([4u, 7u, 14u, 22u]) == true,
        "Combat selected_action must survive journal replay as one card set.");
    var compactAction = ReadJournalLines(store.GetCompactEpisodePath(episodeId))
        .Select(line => JsonNode.Parse(line)?.AsObject())
        .Single(row => row?["t"]?.GetValue<string>() == "action");
    var compactCombat = compactAction?["selected_action"]?.Deserialize<
        CombatActionDescriptor>(CollectorJson.Options);
    Assert(compactCombat?.SelectedCombatCardIds?.SequenceEqual([4u, 7u, 14u, 22u]) == true,
        "Compact view must preserve the concrete combat card-set label.");
}

static void RunLegacySingleChoiceKeySmoke()
{
    // Golden action keys from a published pre-multi-select episode. Only the
    // action descriptor contributes to these hashes; no run metadata is used.
    var ordinary = CreateCombatDecision(302, '6');
    var generatedChoice = new CombatChoiceObservation(
        ChoiceId: 7,
        Source: "legacy_generated_card_choice",
        MinSelections: 1,
        MaxSelections: 1,
        CanCancel: false,
        Cards: [new CombatChoiceCardObservation(
            null, "CARD.CINDER", 0, OptionIndex: 0)]);
    var decision = ordinary with
    {
        Observation = ordinary.Observation with
        {
            ActiveChoice = generatedChoice,
        },
        LegalActions = CombatChoiceActionBuilder.Build(1, generatedChoice),
    };
    decision.Validate();
    var input = DecisionInput.FromCombat(
        Guid.NewGuid(), decision, InformationRegime.NoSl);
    Assert(input.ActionKeys[0]
           == "combat:cdebca1c7e97245c46269f68a2d19b9c9568d330a1fe5fed49d4a9ef0e2dbd56",
        "The existing single-card action key must remain replay-compatible.");

    var indexedChoice = new CombatChoiceObservation(
        ChoiceId: 17,
        Source: "legacy_hand_choice",
        MinSelections: 1,
        MaxSelections: 1,
        CanCancel: false,
        Cards: [new CombatChoiceCardObservation(
            21, "STRIKE", 0, OptionIndex: 0)]);
    var indexedDecision = ordinary with
    {
        Observation = ordinary.Observation with
        {
            ActiveChoice = indexedChoice,
        },
        LegalActions = CombatChoiceActionBuilder.Build(1, indexedChoice),
    };
    indexedDecision.Validate();
    var indexedInput = DecisionInput.FromCombat(
        Guid.NewGuid(), indexedDecision, InformationRegime.NoSl);
    Assert(indexedInput.ActionKeys[0]
           == "combat:49f326c4a9806b3eb56e88680ebc672c9c4b12ee0569415f3b20a852322aad6a",
        "The existing indexed hand-card key must remain replay-compatible.");
}

static IEnumerable<string> ReadJournalLines(string path)
{
    // Active journals retain write access; Windows readers must share it.
    using var stream = new FileStream(
        path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
    using var reader = new StreamReader(stream);
    string? line;
    while ((line = reader.ReadLine()) is not null)
    {
        yield return line;
    }
}
static string Fingerprint(char character) => new(character, 64);

static void Assert(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void AssertThrows<TException>(Action action)
    where TException : Exception
{
    try
    {
        action();
    }
    catch (TException)
    {
        return;
    }

    throw new InvalidOperationException(
        $"Expected exception {typeof(TException).Name} was not thrown.");
}

file sealed class AdvancingClock(DateTimeOffset current) : ICollectorClock
{
    private DateTimeOffset _current = current;

    public DateTimeOffset UtcNow
    {
        get
        {
            var result = _current;
            _current = _current.AddMilliseconds(1);
            return result;
        }
    }
}
