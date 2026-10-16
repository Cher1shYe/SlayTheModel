using System.Diagnostics;
using System.Text.Json;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Models;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Saves.Validation;
using MegaCrit.Sts2.Core.Timeline;
using MegaCrit.Sts2.Core.Unlocks;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static partial class WholeRunSpeedProbe
{
    private sealed record CollectorStep(int GlobalStep, string Domain,
        JsonElement Observation, JsonElement Action, string ExecutionStatus);

    private static async Task RunCollectorReplayAsync(Node host, string output, string journalPath)
    {
        var decisions = new Dictionary<int, JsonElement>();
        var submissions = new Dictionary<int, (int Index, JsonElement? ConcreteAction)>();
        var executionStatuses = new Dictionary<int, string>();
        var recordedEncounters = new List<string>();
        var coverageGaps = new List<(int? EntryStep, JsonElement Payload)>();
        JsonElement episodeStarted = default;
        JsonElement episodeFinished = default;
        foreach (string line in File.ReadLines(journalPath))
        {
            using var document = JsonDocument.Parse(line);
            var entry = document.RootElement;
            string eventType = entry.GetProperty("event_type").GetString() ?? "";
            if (eventType == "episode_started")
                episodeStarted = entry.GetProperty("payload").Clone();
            else if (eventType == "decision")
                decisions[entry.GetProperty("global_step").GetInt32()] = entry.GetProperty("payload").Clone();
            else if (eventType == "action_submitted")
            {
                var payload = entry.GetProperty("payload");
                submissions[entry.GetProperty("global_step").GetInt32()] = (
                    payload.GetProperty("selected_action_index").GetInt32(),
                    payload.TryGetProperty("selected_action", out var concrete)
                        ? concrete.Clone()
                        : null);
            }
            else if (eventType == "execution_result")
                executionStatuses[entry.GetProperty("global_step").GetInt32()] =
                    entry.GetProperty("payload").GetProperty("status").GetString() ?? "";
            else if (eventType == "diagnostic"
                && entry.GetProperty("payload").GetProperty("code").GetString() == "combat_started")
                recordedEncounters.Add(entry.GetProperty("payload").GetProperty("data")
                    .GetProperty("encounter_id").GetString() ?? "");
            else if (eventType == "coverage_gap")
            {
                int? entryStep = entry.TryGetProperty("global_step", out var gapStep)
                    && gapStep.ValueKind == JsonValueKind.Number ? gapStep.GetInt32() : null;
                coverageGaps.Add((entryStep, entry.GetProperty("payload").Clone()));
            }
            else if (eventType == "episode_finished")
                episodeFinished = entry.GetProperty("payload").Clone();
        }
        if (episodeStarted.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Collector journal has no episode_started event.");
        var decisionStepsById = decisions
            .Where(pair => pair.Value.TryGetProperty("decision_id", out var decisionId)
                && decisionId.ValueKind == JsonValueKind.String)
            .ToDictionary(pair => pair.Value.GetProperty("decision_id").GetString() ?? "",
                pair => pair.Key,
                StringComparer.Ordinal);
        var resolvedGapSteps = new List<int>();
        int unresolvedCoverageGaps = 0;
        foreach (var gap in coverageGaps)
        {
            var candidates = new List<int>();
            if (gap.EntryStep is { } entryStep) candidates.Add(entryStep);
            AddCollectorGapNumber(gap.Payload, "invalidated_global_step", candidates);
            if (gap.Payload.TryGetProperty("invalidated_decisions", out var invalidated)
                && invalidated.ValueKind == JsonValueKind.Array)
                foreach (var item in invalidated.EnumerateArray())
                    AddCollectorGapNumber(item, "global_step", candidates);
            foreach (string property in new[] { "related_decision_id", "target_decision_id",
                         "invalidated_decision_id" })
            {
                string decisionId = StringProperty(gap.Payload, property);
                if (decisionStepsById.TryGetValue(decisionId, out int decisionStep))
                    candidates.Add(decisionStep);
            }
            if (candidates.Count == 0)
                unresolvedCoverageGaps++;
            else
                resolvedGapSteps.Add(candidates.Min());
        }
        int? firstGapStep = resolvedGapSteps.Count == 0 ? null : resolvedGapSteps.Min();
        string recordedOutcome = episodeFinished.ValueKind == JsonValueKind.Object
            ? StringProperty(episodeFinished, "outcome") : "";
        var steps = decisions.OrderBy(pair => pair.Key)
            .Where(pair => submissions.ContainsKey(pair.Key))
            .Select(pair =>
            {
                var payload = pair.Value;
                var submission = submissions[pair.Key];
                int selectedIndex = submission.Index;
                var actions = payload.GetProperty("legal_actions").EnumerateArray().ToArray();
                if (selectedIndex < 0 || selectedIndex >= actions.Length)
                    throw new InvalidOperationException("Collector selected action index is out of range at step "
                        + pair.Key);
                return new CollectorStep(pair.Key,
                    payload.GetProperty("domain").GetString() ?? "",
                    payload.GetProperty("observation").Clone(),
                    submission.ConcreteAction ?? actions[selectedIndex].Clone(),
                    executionStatuses.TryGetValue(pair.Key, out string? executionStatus)
                        ? executionStatus : "missing");
            }).ToArray();
        if (steps.Any(step => step.ExecutionStatus is not "observed_transition" and not "cancelled"))
            throw new InvalidDataException("Collector journal has a submitted action without a supported native result.");
        var metadata = episodeStarted.GetProperty("metadata");
        string inputSeed = metadata.GetProperty("run_seed").GetString()
            ?? throw new InvalidOperationException("Collector journal has no run seed.");
        string character = metadata.GetProperty("character_id").GetString() ?? "";
        if (character != "CHARACTER.IRONCLAD")
            throw new NotSupportedException("Initial collector replay supports the Ironclad only.");
        if (metadata.GetProperty("ascension").GetString() != "0")
            throw new NotSupportedException("Initial collector replay supports ascension zero only.");

        var stages = new List<object>();
        string? error = null;
        int matchedCombatDecisions = 0;
        int matchedOutsideDecisions = 0;
        int verifiedThroughGlobalStep = 1;
        bool gapBoundaryVerified = false;
        bool terminalOutcomeVerified = false;
        int? priorRunsOverride = int.TryParse(
            System.Environment.GetEnvironmentVariable("STS2_PROBE_COLLECTOR_PRIOR_RUNS"),
            out int configuredPriorRuns) ? configuredPriorRuns : null;
        if (priorRunsOverride < 0)
            throw new ArgumentOutOfRangeException("STS2_PROBE_COLLECTOR_PRIOR_RUNS");
        string[] seenEncounterOverrides = (System.Environment.GetEnvironmentVariable(
                "STS2_PROBE_COLLECTOR_SEEN_ENCOUNTERS") ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Distinct(StringComparer.Ordinal).ToArray();
        int nativeUnlockNumberOfRuns = 0;
        var timer = Stopwatch.StartNew();
        try
        {
            if (MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
                throw new InvalidOperationException("Collector replay must not load NGame.");
            string seed = SeedHelper.CanonicalizeSeed(inputSeed);
            string? progressSavePath = System.Environment.GetEnvironmentVariable("STS2_PROBE_PROGRESS_SAVE");
            if (!string.IsNullOrWhiteSpace(progressSavePath))
            {
                var parsed = SaveManager.FromJson<SerializableProgress>(
                    File.ReadAllText(progressSavePath));
                if (!parsed.Success || parsed.SaveData is null)
                    throw new InvalidDataException("Could not read collector source progress snapshot: "
                        + parsed.ErrorMessage);
                var context = new DeserializationContext();
                SaveManager.Instance.Progress = ProgressState.FromSerializable(parsed.SaveData, context);
                if (context.HasFatal)
                    throw new InvalidDataException("Collector source progress snapshot has fatal validation errors.");
            }
            else
            {
                foreach (string epoch in EpochModel.AllEpochIds)
                    SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
            }
            var unlockState = SaveManager.Instance.GenerateUnlockStateFromProgress();
            if (string.IsNullOrWhiteSpace(progressSavePath)
                && (priorRunsOverride is not null || seenEncounterOverrides.Length > 0))
            {
                var generated = unlockState.ToSerializable();
                var seen = generated.EncountersSeen.ToHashSet();
                foreach (string encounter in seenEncounterOverrides)
                    seen.Add(ModelId.Deserialize(encounter));
                unlockState = new UnlockState(generated.UnlockedEpochs,
                    seen, priorRunsOverride ?? generated.NumberOfRuns);
            }
            nativeUnlockNumberOfRuns = unlockState.NumberOfRuns;
            var player = Player.CreateForNewRun<Ironclad>(unlockState, 1);
            var actRng = new MegaCrit.Sts2.Core.Random.Rng(
                StringHelper.GetDeterministicHashCode(seed), "act_selection");
            var acts = ActModel.GetRandomList(actRng, unlockState, false)
                .Select(act => act.ToMutable()).ToList();
            var run = RunState.CreateForNewRun([player], acts, [], GameMode.Standard, 0, seed);
            RunManager.Instance.ForceDiscoveryOrderModifications = true;
            RunManager.Instance.SetUpNewSingleplayer(run, false, null);
            var selector = new AutoProbeCardSelector();
            using var selectorScope = CardSelectCmd.PushSelector(selector);
            await RunManager.Instance.EnterAct(0, false).WaitAsync(TimeSpan.FromSeconds(5));

            if (steps.Length == 0 || steps[0].GlobalStep != 0)
                throw new InvalidOperationException("Collector replay has no initial Neow decision.");
            var neowStep = steps[0];
            VerifyCollectorOutsidePlayer(neowStep.Observation, run, player, "before Neow");
            var nativeEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent
                ?? throw new InvalidOperationException("Collector replay did not open Neow.");
            string optionKey = neowStep.Action.GetProperty("target_id").GetString() ?? "";
            var neowOption = nativeEvent.CurrentOptions.SingleOrDefault(option => option.TextKey == optionKey)
                ?? throw new InvalidOperationException("Collector Neow option is unavailable: " + optionKey);
            int replayStartIndex = 1;
            string[] bundle = [];
            IDisposable? bundleScope = null;
            if (steps.Length > 1 && CollectorSurface(steps[1]) == "card_bundle_choice")
            {
                bundle = steps[1].Action.GetProperty("bundle_cards").EnumerateArray()
                    .Select(card => card.GetProperty("model_id").GetString() ?? "").ToArray();
                bundleScope = CollectorBundleChoicePatch.Push(bundle);
                replayStartIndex++;
            }
            try
            {
                await neowOption.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
            }
            finally
            {
                bundleScope?.Dispose();
            }
            if (!nativeEvent.IsFinished)
                throw new InvalidOperationException("Collector Neow choice did not finish.");
            if (replayStartIndex >= steps.Length)
                throw new InvalidOperationException("Collector journal ends immediately after Neow.");
            VerifyCollectorOutsidePlayer(steps[replayStartIndex].Observation,
                run, player, "after Neow");
            stages.Add(new { stage = "collector-neow", option = optionKey, bundle,
                deckCount = player.Deck.Cards.Count, relics = player.Relics.Select(relic => relic.Id.ToString()) });

            int configuredMaxStep = int.TryParse(
                System.Environment.GetEnvironmentVariable("STS2_PROBE_COLLECTOR_MAX_STEP"),
                out int parsedMaxStep) ? parsedMaxStep : int.MaxValue;
            int replayMaxStep = Math.Min(configuredMaxStep,
                firstGapStep is { } gap ? gap - 1 : steps[^1].GlobalStep);
            var prefix = await ReplayCollectorPrefixAsync(host, run, player, selector, steps,
                recordedEncounters, replayStartIndex, replayMaxStep, recordedOutcome, stages);
            matchedCombatDecisions = prefix.CombatDecisions;
            matchedOutsideDecisions = prefix.OutsideDecisions + replayStartIndex;
            verifiedThroughGlobalStep = prefix.VerifiedThroughGlobalStep;
            if (firstGapStep is { } boundaryStep && verifiedThroughGlobalStep == boundaryStep - 1
                && decisions.TryGetValue(boundaryStep, out var gapDecision))
            {
                VerifyCollectorOutsidePlayer(gapDecision.GetProperty("observation"), run, player,
                    "at first coverage gap boundary");
                gapBoundaryVerified = true;
            }
            if (firstGapStep is null && verifiedThroughGlobalStep == steps[^1].GlobalStep
                && recordedOutcome == "defeat")
            {
                if (!player.Creature.IsDead || !run.IsGameOver)
                    throw new InvalidOperationException("Collector journal ended in defeat but native run did not.");
                terminalOutcomeVerified = true;
            }
        }
        catch (Exception exception)
        {
            error = exception.ToString();
            stages.Add(new { stage = "collector-mismatch", message = exception.Message });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(new
        {
            journalFile = Path.GetFileName(journalPath), inputSeed,
            sourceProgressLoaded = !string.IsNullOrWhiteSpace(
                System.Environment.GetEnvironmentVariable("STS2_PROBE_PROGRESS_SAVE")),
            priorRunsOverride, seenEncounterOverrides, nativeUnlockNumberOfRuns,
            replayScope = firstGapStep is null ? "submitted-journal" : "continuous-prefix-before-first-gap",
            sourceDecisions = decisions.Count, sourceSubmittedDecisions = steps.Length,
            sourceCancelledActions = steps.Count(step => step.ExecutionStatus == "cancelled"),
            sourceCoverageGaps = coverageGaps.Count,
            resolvedCoverageGapSteps = resolvedGapSteps.Distinct().Order().ToArray(),
            unresolvedCoverageGaps,
            cancelledBeforeFirstGap = steps.Count(step => step.ExecutionStatus == "cancelled"
                && (firstGapStep is null || step.GlobalStep < firstGapStep)),
            recordedOutcome, firstGapStep, verifiedThroughGlobalStep, gapBoundaryVerified,
            terminalOutcomeVerified,
            matchedCombatDecisions, matchedOutsideDecisions,
            elapsedMs = timer.Elapsed.TotalMilliseconds,
            stages, error, gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null,
        }, new JsonSerializerOptions { WriteIndented = true }));
        GD.Print("WHOLE_RUN_COLLECTOR_REPLAY " + (error is null ? "prefix-complete" : "mismatch")
            + " output=" + output);
        if (error is not null)
            throw new InvalidOperationException("Collector replay diverged: " + error);
    }

    private static void QueueCollectorRewardSelections(IEnumerable<CollectorStep> rewardSteps,
        AutoProbeCardSelector selector)
    {
        foreach (var step in rewardSteps.Where(step =>
                     step.Observation.TryGetProperty("surface", out var surface)
                     && surface.GetString() == "card_reward"))
        {
            string kind = step.Action.GetProperty("kind").GetString() ?? "";
            if (kind == "choose_card")
                selector.ForcedRewardCardModelSelections.Enqueue(
                    step.Action.GetProperty("target_id").GetString() ?? "");
            else if (kind == "skip")
                selector.ForcedRewardCardModelSelections.Enqueue(AutoProbeCardSelector.SkipRewardSelection);
        }
    }

    private sealed record CollectorPrefixResult(
        int CombatDecisions,
        int OutsideDecisions,
        int VerifiedThroughGlobalStep);

    private static async Task<CollectorPrefixResult> ReplayCollectorPrefixAsync(
        Node host,
        RunState run,
        Player player,
        AutoProbeCardSelector selector,
        IReadOnlyList<CollectorStep> steps,
        IReadOnlyList<string> recordedEncounters,
        int replayStartIndex,
        int maxStep,
        string recordedOutcome,
        List<object> stages)
    {
        int cursor = replayStartIndex;
        if (cursor < 1 || cursor >= steps.Count)
            throw new InvalidOperationException("Collector replay has no first post-Neow step.");
        int combatDecisions = 0;
        int outsideDecisions = 0;
        int verifiedThrough = steps[cursor - 1].GlobalStep;
        int encounterIndex = 0;
        CombatRoom? pendingRewards = null;

        while (cursor < steps.Count && steps[cursor].GlobalStep <= maxStep)
        {
            var step = steps[cursor];
            if (step.Domain == "combat")
            {
                var combat = run.CurrentRoom as CombatRoom
                    ?? throw new InvalidOperationException("Collector expected combat at step "
                        + step.GlobalStep + ", native room is " + run.CurrentRoom?.GetType().Name);
                if (encounterIndex >= recordedEncounters.Count)
                    throw new InvalidOperationException("Collector encounter diagnostics ended before combat step "
                        + step.GlobalStep);
                RequireCollectorEncounter(combat, recordedEncounters[encounterIndex], encounterIndex);
                int end = cursor;
                while (end < steps.Count && steps[end].Domain == "combat"
                    && steps[end].GlobalStep <= maxStep) end++;
                var combatSteps = steps.Skip(cursor).Take(end - cursor).ToArray();
                int matched = await ReplayCollectorCombatAsync(host, combat, run, player,
                    combatSteps, selector);
                combatDecisions += matched;
                verifiedThrough = combatSteps[^1].GlobalStep;
                bool terminalDefeat = end == steps.Count && recordedOutcome == "defeat"
                    && player.Creature.IsDead && run.IsGameOver;
                if (!terminalDefeat && (!combat.IsPreFinished || player.Creature.IsDead))
                    throw new InvalidOperationException("Collector combat did not end in victory at step "
                        + verifiedThrough + ": " + combat.Encounter.Id);
                if (terminalDefeat)
                {
                    stages.Add(new { stage = "collector-combat", encounterIndex,
                        encounter = combat.Encounter.Id.Entry, firstStep = combatSteps[0].GlobalStep,
                        lastStep = combatSteps[^1].GlobalStep, matchedCombatDecisions = matched,
                        terminalDefeat = true, hp = player.Creature.CurrentHp,
                        gold = player.Gold, floor = run.TotalFloor });
                    encounterIndex++;
                    pendingRewards = null;
                    cursor = end;
                    continue;
                }
                bool resumedParentEvent = combat.ParentEventId is not null
                    && combat.ShouldResumeParentEventAfterCombat;
                if (resumedParentEvent)
                {
                    await RunManager.Instance.ProceedFromTerminalRewardsScreen()
                        .WaitAsync(TimeSpan.FromSeconds(10));
                    if (run.CurrentRoom is not EventRoom)
                        throw new InvalidOperationException("Collector event combat did not resume its parent event at step "
                            + verifiedThrough + ": " + combat.Encounter.Id);
                }
                if (end < steps.Count && steps[end].Domain == "outside_combat")
                    VerifyCollectorOutsidePlayer(steps[end].Observation, run, player,
                        "after combat " + combat.Encounter.Id.Entry);
                stages.Add(new { stage = "collector-combat", encounterIndex,
                    encounter = combat.Encounter.Id.Entry, firstStep = combatSteps[0].GlobalStep,
                    lastStep = combatSteps[^1].GlobalStep, matchedCombatDecisions = matched,
                    resumedParentEvent,
                    hp = player.Creature.CurrentHp, gold = player.Gold, floor = run.TotalFloor });
                encounterIndex++;
                pendingRewards = resumedParentEvent || !combat.Encounter.ShouldGiveRewards
                    ? null
                    : combat;
                cursor = end;
                continue;
            }

            string surface = step.Observation.GetProperty("surface").GetString() ?? "";
            string kind = step.Action.GetProperty("kind").GetString() ?? "";
            if (surface is "rewards" or "card_reward")
            {
                if (pendingRewards is null)
                    throw new InvalidOperationException("Collector rewards have no completed combat at step "
                        + step.GlobalStep);
                int end = cursor;
                while (end < steps.Count && steps[end].GlobalStep <= maxStep
                    && steps[end].Domain == "outside_combat"
                    && (CollectorSurface(steps[end]) is "rewards" or "card_reward")) end++;
                var rewardSteps = steps.Skip(cursor).Take(end - cursor).ToArray();
                QueueCollectorRewardSelections(rewardSteps, selector);
                using var rewardScope = CollectorRewardSelectionScope.Push(rewardSteps);
                await pendingRewards.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
                await rewardScope.Completion.WaitAsync(TimeSpan.FromSeconds(10));
                string[] skipped = rewardScope.SkippedRewardTypes;
                outsideDecisions += rewardSteps.Length;
                verifiedThrough = rewardSteps[^1].GlobalStep;
                if (end < steps.Count && steps[end].Domain == "outside_combat")
                    VerifyCollectorOutsidePlayer(steps[end].Observation, run, player,
                        "after rewards at step " + verifiedThrough);
                stages.Add(new { stage = "collector-rewards", firstStep = rewardSteps[0].GlobalStep,
                    lastStep = rewardSteps[^1].GlobalStep, skipped,
                    hp = player.Creature.CurrentHp, gold = player.Gold,
                    potions = player.PotionSlots.Select(potion => potion?.Id.ToString()).ToArray() });
                pendingRewards = null;
                cursor = end;
                continue;
            }

            switch (kind)
            {
                case "travel":
                {
                    var target = await FindCollectorMapTargetAsync(run, step, stages);
                    VerifyCollectorOutsidePlayer(step.Observation, run, player,
                        "before map step " + step.GlobalStep);
                    await RunManager.Instance.EnterMapCoord(target.coord)
                        .WaitAsync(TimeSpan.FromSeconds(10));
                    if (run.CurrentMapPoint != target)
                        throw new InvalidOperationException("Collector map move did not reach its target at step "
                            + step.GlobalStep);
                    if (run.CurrentRoom is MerchantRoom merchant)
                        ApplyCollectorMerchantPotionCosts(player, merchant);
                    var enteredEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent;
                    stages.Add(new { stage = "collector-map", step = step.GlobalStep,
                        actIndex = run.CurrentActIndex, floor = run.TotalFloor,
                        row = target.coord.row, col = target.coord.col,
                        pointType = target.PointType.ToString(), roomType = run.CurrentRoom?.GetType().Name,
                        eventId = enteredEvent?.Id.Entry,
                        eventOptions = enteredEvent?.CurrentOptions.Select(option => new {
                            option.TextKey, option.IsLocked, option.WasChosen }).ToArray() });
                    outsideDecisions++;
                    verifiedThrough = step.GlobalStep;
                    cursor++;
                    break;
                }
                case "choose_event_option":
                {
                    VerifyCollectorOutsidePlayer(step.Observation, run, player,
                        "before event step " + step.GlobalStep);
                    var eventRoom = run.CurrentRoom as EventRoom
                        ?? throw new InvalidOperationException("Collector expected an event at step "
                            + step.GlobalStep);
                    var nativeEvent = eventRoom.LocalMutableEvent
                        ?? throw new InvalidOperationException("Collector event has no mutable model.");
                    string key = StringProperty(step.Action, "target_id");
                    var option = nativeEvent.CurrentOptions.SingleOrDefault(candidate =>
                            candidate.TextKey == key && !candidate.IsLocked && !candidate.WasChosen)
                        ?? throw new InvalidOperationException("Collector event option is unavailable at step "
                            + step.GlobalStep + ": " + key);
                    if (nativeEvent.Id.Entry == "CRYSTAL_SPHERE")
                    {
                        int consumed = await ReplayCollectorCrystalSphereAsync(option, nativeEvent,
                            run, player, selector, steps, cursor, maxStep, stages);
                        outsideDecisions += consumed;
                        verifiedThrough = steps[cursor + consumed - 1].GlobalStep;
                        cursor += consumed;
                        break;
                    }
                    int selections = QueueFollowingOutsideSelections(steps, cursor + 1, maxStep,
                        player, selector);
                    if (nativeEvent.Id.Entry == "DENSE_VEGETATION"
                        && key == "DENSE_VEGETATION.pages.INITIAL.options.REST")
                    {
                        using var restScope = CollectorDenseVegetationRestPatch.Push();
                        await option.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                    }
                    else if (nativeEvent.Id.Entry == "AMALGAMATOR")
                    {
                        using var amalgamatorScope = CollectorAmalgamatorPatch.Push();
                        await option.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                    }
                    else
                    {
                        await option.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                    }
                    outsideDecisions += 1 + selections;
                    verifiedThrough = steps[cursor + selections].GlobalStep;
                    stages.Add(new { stage = "collector-event", step = step.GlobalStep,
                        eventId = nativeEvent.Id.Entry, option = key, selections,
                        finished = nativeEvent.IsFinished, roomType = run.CurrentRoom?.GetType().Name });
                    cursor += 1 + selections;
                    break;
                }
                case "choose_rest_site_option":
                {
                    VerifyCollectorOutsidePlayer(step.Observation, run, player,
                        "before rest step " + step.GlobalStep);
                    var rest = run.CurrentRoom as RestSiteRoom
                        ?? throw new InvalidOperationException("Collector expected a rest site at step "
                            + step.GlobalStep);
                    string optionId = StringProperty(step.Action, "target_id");
                    int optionIndex = rest.Options.ToList().FindIndex(option =>
                        option.OptionId.ToString() == optionId
                        || option.OptionId.ToString().EndsWith("." + optionId, StringComparison.Ordinal));
                    if (optionIndex < 0 || !rest.Options[optionIndex].IsEnabled)
                        throw new InvalidOperationException("Collector rest option is unavailable at step "
                            + step.GlobalStep + ": " + optionId);
                    int selections = QueueFollowingOutsideSelections(steps, cursor + 1, maxStep,
                        player, selector);
                    bool applied = await RunManager.Instance.RestSiteSynchronizer
                        .ChooseLocalOption(optionIndex).WaitAsync(TimeSpan.FromSeconds(10));
                    if (!applied) throw new InvalidOperationException("Native rest option was rejected at step "
                        + step.GlobalStep);
                    outsideDecisions += 1 + selections;
                    verifiedThrough = steps[cursor + selections].GlobalStep;
                    stages.Add(new { stage = "collector-rest", step = step.GlobalStep,
                        option = optionId, selections, hp = player.Creature.CurrentHp });
                    cursor += 1 + selections;
                    break;
                }
                case "open_chest":
                {
                    int consumed = await ReplayCollectorTreasureAsync(host, run, player, steps,
                        cursor, maxStep);
                    outsideDecisions += consumed;
                    verifiedThrough = steps[cursor + consumed - 1].GlobalStep;
                    stages.Add(new { stage = "collector-treasure", firstStep = step.GlobalStep,
                        lastStep = verifiedThrough, relics = player.Relics.Select(relic => relic.Id.Entry).ToArray() });
                    cursor += consumed;
                    break;
                }
                case "open_card_removal":
                case "buy_card":
                case "buy_relic":
                case "buy_potion":
                case "leave_merchant":
                {
                    int consumed = await ReplayCollectorMerchantAsync(run, player, selector, steps,
                        cursor, maxStep);
                    outsideDecisions += consumed;
                    verifiedThrough = steps[cursor + consumed - 1].GlobalStep;
                    stages.Add(new { stage = "collector-merchant", firstStep = step.GlobalStep,
                        lastStep = verifiedThrough, action = kind, hp = player.Creature.CurrentHp,
                        gold = player.Gold, deckCount = player.Deck.Cards.Count,
                        relicCount = player.Relics.Count });
                    cursor += consumed;
                    break;
                }
                default:
                    throw new NotSupportedException("Collector outside action is not implemented at step "
                        + step.GlobalStep + ": " + surface + "/" + kind);
            }
        }

        return new CollectorPrefixResult(combatDecisions, outsideDecisions, verifiedThrough);
    }

    private static string CollectorSurface(CollectorStep step) =>
        step.Observation.GetProperty("surface").GetString() ?? "";

    private static string StringProperty(JsonElement element, string property) =>
        element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? "" : "";

    private static void AddCollectorGapNumber(JsonElement element, string property,
        ICollection<int> destination)
    {
        if (element.TryGetProperty(property, out var value)
            && value.ValueKind == JsonValueKind.Number)
            destination.Add(value.GetInt32());
    }

    private static async Task<int> ReplayCollectorCrystalSphereAsync(
        MegaCrit.Sts2.Core.Events.EventOption option,
        EventModel nativeEvent,
        RunState run,
        Player player,
        AutoProbeCardSelector selector,
        IReadOnlyList<CollectorStep> steps,
        int cursor,
        int maxStep,
        List<object> stages)
    {
        int minigameStart = cursor + 1;
        int rewardStart = minigameStart;
        while (rewardStart < steps.Count && steps[rewardStart].GlobalStep <= maxStep
            && CollectorSurface(steps[rewardStart]) == "crystal_sphere"
            && StringProperty(steps[rewardStart].Action, "kind") == "choose_minigame_option")
            rewardStart++;
        if (rewardStart == minigameStart)
            throw new InvalidOperationException("Collector Crystal Sphere event has no minigame actions.");

        int crystalProceed = rewardStart;
        while (crystalProceed < steps.Count && steps[crystalProceed].GlobalStep <= maxStep
            && steps[crystalProceed].Domain == "outside_combat"
            && CollectorSurface(steps[crystalProceed]) is "rewards" or "card_reward")
            crystalProceed++;
        if (crystalProceed >= steps.Count || steps[crystalProceed].GlobalStep > maxStep
            || CollectorSurface(steps[crystalProceed]) != "crystal_sphere"
            || StringProperty(steps[crystalProceed].Action, "kind") != "proceed")
            throw new InvalidOperationException(
                "Collector Crystal Sphere sequence is incomplete before the replay boundary.");

        var minigameSteps = steps.Skip(minigameStart).Take(rewardStart - minigameStart).ToArray();
        var rewardSteps = steps.Skip(rewardStart).Take(crystalProceed - rewardStart).ToArray();
        QueueCollectorRewardSelections(rewardSteps, selector);
        using var minigameScope = CollectorCrystalSpherePatch.Push();
        using var rewardScope = CollectorRewardSelectionScope.Push(rewardSteps);
        Task optionTask = option.Chosen();
        CrystalSphereMinigame game = await minigameScope.Captured.WaitAsync(TimeSpan.FromSeconds(10));

        foreach (CollectorStep minigameStep in minigameSteps)
        {
            VerifyCollectorOutsidePlayer(minigameStep.Observation, run, player,
                "before Crystal Sphere step " + minigameStep.GlobalStep);
            string target = StringProperty(minigameStep.Action, "target_id");
            if (target.StartsWith("cell:", StringComparison.Ordinal))
            {
                string[] coordinates = target[5..].Split(',');
                if (coordinates.Length != 2 || !int.TryParse(coordinates[0], out int x)
                    || !int.TryParse(coordinates[1], out int y)
                    || x < 0 || x >= game.GridSize.X || y < 0 || y >= game.GridSize.Y)
                    throw new InvalidOperationException("Collector Crystal Sphere cell is invalid at step "
                        + minigameStep.GlobalStep + ": " + target);
                var cell = game.cells[x, y];
                game.SetHoveredCell(cell);
                VerifyCollectorCrystalSphere(minigameStep.Observation, game,
                    minigameStep.GlobalStep);
                await game.CellClicked(cell).WaitAsync(TimeSpan.FromSeconds(10));
                game.UnsetHoveredCell();
            }
            else if (target is "tool:small" or "tool:big")
            {
                VerifyCollectorCrystalSphere(minigameStep.Observation, game,
                    minigameStep.GlobalStep);
                game.SetTool(target == "tool:small"
                    ? CrystalSphereMinigame.CrystalSphereToolType.Small
                    : CrystalSphereMinigame.CrystalSphereToolType.Big);
            }
            else
            {
                throw new NotSupportedException("Collector Crystal Sphere action is unsupported at step "
                    + minigameStep.GlobalStep + ": " + target);
            }
        }

        await rewardScope.Completion.WaitAsync(TimeSpan.FromSeconds(10));
        await optionTask.WaitAsync(TimeSpan.FromSeconds(10));
        var proceed = steps[crystalProceed];
        VerifyCollectorOutsidePlayer(proceed.Observation, run, player,
            "before Crystal Sphere proceed step " + proceed.GlobalStep);
        VerifyCollectorCrystalSphere(proceed.Observation, game, proceed.GlobalStep);
        if (!game.IsFinished || !nativeEvent.IsFinished)
            throw new InvalidOperationException("Collector Crystal Sphere did not finish natively.");

        int consumed = crystalProceed - cursor + 1;
        if (cursor + consumed < steps.Count && steps[cursor + consumed].Domain == "outside_combat")
            VerifyCollectorOutsidePlayer(steps[cursor + consumed].Observation, run, player,
                "after Crystal Sphere step " + proceed.GlobalStep);
        stages.Add(new { stage = "collector-crystal-sphere",
            eventStep = steps[cursor].GlobalStep,
            firstMinigameStep = minigameSteps[0].GlobalStep,
            lastMinigameStep = minigameSteps[^1].GlobalStep,
            rewardFirstStep = rewardSteps.Length == 0 ? (int?)null : rewardSteps[0].GlobalStep,
            rewardLastStep = rewardSteps.Length == 0 ? (int?)null : rewardSteps[^1].GlobalStep,
            proceedStep = proceed.GlobalStep,
            divinations = minigameSteps.Length,
            skippedRewards = rewardScope.SkippedRewardTypes,
            hp = player.Creature.CurrentHp, gold = player.Gold,
            deckCount = player.Deck.Cards.Count });
        return consumed;
    }

    private static void VerifyCollectorCrystalSphere(JsonElement observation,
        CrystalSphereMinigame game, int step)
    {
        if (!observation.TryGetProperty("crystal_sphere", out var recorded))
            throw new InvalidOperationException("Collector Crystal Sphere observation is absent at step " + step);
        string nativeTool = game.CrystalSphereTool.ToString().ToLowerInvariant();
        if (recorded.GetProperty("width").GetInt32() != game.GridSize.X
            || recorded.GetProperty("height").GetInt32() != game.GridSize.Y
            || recorded.GetProperty("divinations_remaining").GetInt32() != game.DivinationCount
            || StringProperty(recorded, "selected_tool") != nativeTool
            || recorded.GetProperty("is_finished").GetBoolean() != game.IsFinished)
            throw new InvalidOperationException("Collector Crystal Sphere summary differs at step " + step);

        var recordedCells = recorded.GetProperty("cells").EnumerateArray()
            .ToDictionary(cell => (cell.GetProperty("x").GetInt32(), cell.GetProperty("y").GetInt32()));
        if (recordedCells.Count != game.GridSize.X * game.GridSize.Y)
            throw new InvalidOperationException("Collector Crystal Sphere cell count differs at step " + step);
        for (int x = 0; x < game.GridSize.X; x++)
        for (int y = 0; y < game.GridSize.Y; y++)
        {
            if (!recordedCells.TryGetValue((x, y), out var expected))
                throw new InvalidOperationException("Collector Crystal Sphere cell is missing at step "
                    + step + ": " + x + "," + y);
            var actual = game.cells[x, y];
            if (expected.GetProperty("is_hidden").GetBoolean() != actual.IsHidden
                || expected.GetProperty("is_highlighted").GetBoolean() != actual.IsHighlighted)
                throw new InvalidOperationException("Collector Crystal Sphere cell state differs at step "
                    + step + ": " + x + "," + y);
            string recordedKind = StringProperty(expected, "revealed_item_kind");
            string nativeKind = actual.IsHidden ? "" : actual.Item?.GetType().Name ?? "";
            if (recordedKind != nativeKind)
                throw new InvalidOperationException("Collector Crystal Sphere revealed item differs at step "
                    + step + ": " + x + "," + y + "; native=" + nativeKind
                    + ", recorded=" + recordedKind);
            string recordedVisual = StringProperty(expected, "revealed_visual_id");
            string nativeVisual = actual.IsHidden || actual.Item is null
                ? "" : CollectorCrystalVisualId(actual.Item);
            if (recordedVisual != nativeVisual)
                throw new InvalidOperationException("Collector Crystal Sphere item visual differs at step "
                    + step + ": " + x + "," + y + "; native=" + nativeVisual
                    + ", recorded=" + recordedVisual);
        }
    }

    private static string CollectorCrystalVisualId(CrystalSphereItem item)
    {
        var property = AccessTools.Property(item.GetType(), "TexturePath")
            ?? AccessTools.Property(typeof(CrystalSphereItem), "TexturePath")
            ?? throw new InvalidOperationException("Native Crystal Sphere item has no texture path.");
        return "icon:" + (property.GetValue(item) as string
            ?? throw new InvalidOperationException("Native Crystal Sphere item texture path is null."));
    }

    private static void RequireCollectorEncounter(CombatRoom combat, string expected, int index)
    {
        if (combat.Encounter.Id.ToString() != expected
            && combat.Encounter.Id.Entry != expected
            && "ENCOUNTER." + combat.Encounter.Id.Entry != expected)
            throw new InvalidOperationException("Collector encounter " + index + " differs: native "
                + combat.Encounter.Id + ", recorded " + expected);
    }

    private static async Task<MapPoint> FindCollectorMapTargetAsync(
        RunState run, CollectorStep step, List<object> stages)
    {
        var coordinate = step.Action.GetProperty("map_coordinate");
        int row = coordinate.GetProperty("row").GetInt32();
        int col = coordinate.GetProperty("column").GetInt32();
        MapPoint? NavigationPoint() => run.CurrentMapPoint
            ?? (run.CurrentRoom is MapRoom ? run.Map.StartingMapPoint : null);
        var target = NavigationPoint()?.Children.SingleOrDefault(point =>
            point.coord.row == row && point.coord.col == col);
        if (target is null && NavigationPoint()?.Children.Count == 0
            && run.CurrentActIndex + 1 < run.Acts.Count)
        {
            int fromAct = run.CurrentActIndex;
            await RunManager.Instance.EnterNextAct().WaitAsync(TimeSpan.FromSeconds(15));
            stages.Add(new { stage = "collector-enter-next-act", fromActIndex = fromAct,
                toActIndex = run.CurrentActIndex, floor = run.TotalFloor,
                roomType = run.CurrentRoom?.GetType().Name });
            target = run.Map.StartingMapPoint.coord.row == row
                && run.Map.StartingMapPoint.coord.col == col
                    ? run.Map.StartingMapPoint
                    : run.Map.StartingMapPoint.Children.SingleOrDefault(point =>
                        point.coord.row == row && point.coord.col == col);
        }
        return target ?? throw new InvalidOperationException("Collector map coordinate is not reachable at step "
            + step.GlobalStep + ": " + row + "," + col
            + "; act=" + run.CurrentActIndex
            + "; current=" + (run.CurrentMapPoint?.coord.ToString() ?? "null")
            + "; start=" + run.Map.StartingMapPoint.coord
            + "; startChildren=" + string.Join(',', run.Map.StartingMapPoint.Children
                .Select(point => point.coord + ":" + point.PointType)));
    }

    private static int QueueFollowingOutsideSelections(
        IReadOnlyList<CollectorStep> steps,
        int start,
        int maxStep,
        Player player,
        AutoProbeCardSelector selector)
    {
        int count = 0;
        while (start + count < steps.Count && steps[start + count].GlobalStep <= maxStep
            && steps[start + count].Domain == "outside_combat"
            && CollectorSurface(steps[start + count]) is "card_grid_choice" or "merchant_card_removal")
        {
            QueueCollectorOutsideSelection(steps[start + count], player, selector);
            count++;
        }
        return count;
    }

    private static void QueueCollectorOutsideSelection(
        CollectorStep step, Player player, AutoProbeCardSelector selector)
    {
        string kind = StringProperty(step.Action, "kind");
        var indexes = new List<int>();
        if (kind == "choose_card" || kind == "remove_card")
        {
            if (!step.Action.TryGetProperty("target_deck_index", out var target)
                || target.ValueKind != JsonValueKind.Number)
                throw new InvalidOperationException("Collector card selection has no deck index at step "
                    + step.GlobalStep);
            indexes.Add(target.GetInt32());
        }
        else if (kind is "choose_card_set" or "remove_card_set")
        {
            if (!step.Action.TryGetProperty("selected_cards", out var selected)
                || selected.ValueKind != JsonValueKind.Array)
                throw new InvalidOperationException("Collector set selection has no concrete cards at step "
                    + step.GlobalStep);
            indexes.AddRange(selected.EnumerateArray()
                .Select(card => card.GetProperty("deck_index").GetInt32()));
        }
        else
        {
            throw new NotSupportedException("Collector card-grid action is not implemented at step "
                + step.GlobalStep + ": " + kind);
        }
        if (indexes.Any(index => index < 0 || index >= player.Deck.Cards.Count))
            throw new InvalidOperationException("Collector deck index is out of native range at step "
                + step.GlobalStep);
        selector.ForcedExactCardSelections.Enqueue(indexes.Select(index => player.Deck.Cards[index]).ToArray());
    }

    private static async Task<int> ReplayCollectorTreasureAsync(
        Node host,
        RunState run,
        Player player,
        IReadOnlyList<CollectorStep> steps,
        int cursor,
        int maxStep)
    {
        var open = steps[cursor];
        VerifyCollectorOutsidePlayer(open.Observation, run, player,
            "before treasure step " + open.GlobalStep);
        if (run.CurrentRoom is not TreasureRoom treasure)
            throw new InvalidOperationException("Collector expected treasure at step " + open.GlobalStep);
        await InvokeNativeTaskAsync(treasure, "DoNormalRewards");
        await InvokeNativeTaskAsync(treasure, "DoExtraRewardsIfNeeded");
        var synchronizer = RunManager.Instance.TreasureRoomRelicSynchronizer;
        var offered = synchronizer.CurrentRelics?.ToArray() ?? [];
        if (cursor + 1 >= steps.Count || steps[cursor + 1].GlobalStep > maxStep)
            throw new InvalidOperationException("Collector treasure ends before its recorded follow-up.");
        var followUp = steps[cursor + 1];
        string followUpKind = StringProperty(followUp.Action, "kind");
        if (followUpKind == "proceed")
        {
            string target = StringProperty(followUp.Action, "target_id");
            if (offered.Length > 0 && target != "skip")
                throw new InvalidOperationException("Collector skipped a native treasure offer without a skip action.");
            return 2;
        }
        if (followUpKind != "take_treasure_relic")
            throw new InvalidOperationException("Collector treasure follow-up is unsupported: " + followUpKind);
        if (offered.Length == 0)
            throw new InvalidOperationException("Collector treasure has no native relic offer.");
        string targetId = StringProperty(followUp.Action, "target_id");
        int relicIndex = Array.FindIndex(offered, relic => relic.Id.ToString() == targetId
            || relic.Id.Entry == targetId || "RELIC." + relic.Id.Entry == targetId);
        if (relicIndex < 0)
            throw new InvalidOperationException("Collector treasure relic is absent: " + targetId);
        object? awardResult = null;
        synchronizer.RelicsAwarded += result => awardResult = result;
        synchronizer.PickRelicLocally(relicIndex);
        var timer = Stopwatch.StartNew();
        while (awardResult is null && timer.Elapsed < TimeSpan.FromSeconds(2))
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        if (awardResult is not System.Collections.IEnumerable results)
            throw new InvalidOperationException("Collector treasure emitted no relic award.");
        var award = results.Cast<object>().Single();
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance
            | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
        var relic = award.GetType().GetField("relic", flags)?.GetValue(award) as RelicModel
            ?? throw new InvalidOperationException("Collector treasure award has no relic.");
        var awardedPlayer = award.GetType().GetField("player", flags)?.GetValue(award) as Player
            ?? throw new InvalidOperationException("Collector treasure award has no player.");
        if (!ReferenceEquals(awardedPlayer, player) || relic.Id != offered[relicIndex].Id)
            throw new InvalidOperationException("Collector treasure award differs from its recorded selection.");
        await RelicCmd.Obtain(relic.ToMutable(), player, 0).WaitAsync(TimeSpan.FromSeconds(10));
        int consumed = 2;
        if (cursor + consumed < steps.Count && steps[cursor + consumed].GlobalStep <= maxStep
            && StringProperty(steps[cursor + consumed].Action, "kind") == "proceed") consumed++;
        return consumed;
    }

    private static async Task<int> ReplayCollectorMerchantAsync(
        RunState run,
        Player player,
        AutoProbeCardSelector selector,
        IReadOnlyList<CollectorStep> steps,
        int cursor,
        int maxStep)
    {
        var step = steps[cursor];
        VerifyCollectorOutsidePlayer(step.Observation, run, player,
            "before merchant step " + step.GlobalStep);
        if (run.CurrentRoom is not MerchantRoom merchant)
            throw new InvalidOperationException("Collector expected merchant at step " + step.GlobalStep);
        string kind = StringProperty(step.Action, "kind");
        if (kind == "leave_merchant") return 1;
        var inventory = merchant.GetLocalInventory();
        int selections = QueueFollowingOutsideSelections(steps, cursor + 1, maxStep, player, selector);
        int recordedCost = step.Action.TryGetProperty("cost", out var cost)
            && cost.ValueKind == JsonValueKind.Number ? cost.GetInt32() : -1;
        string targetId = StringProperty(step.Action, "target_id");
        bool purchased;
        switch (kind)
        {
            case "open_card_removal":
            {
                if (selections != 1 || StringProperty(steps[cursor + 1].Action, "kind") != "remove_card")
                    throw new InvalidOperationException("Collector merchant removal lacks its card selection.");
                var entry = inventory.AllEntries.OfType<MerchantCardRemovalEntry>()
                    .Single(candidate => candidate.IsStocked && candidate.EnoughGold);
                if (entry.Cost != recordedCost)
                    throw new InvalidOperationException("Collector merchant removal cost differs at step "
                        + step.GlobalStep + ": native " + entry.Cost + ", recorded " + recordedCost);
                purchased = await entry.OnTryPurchaseWrapper(inventory, ignoreCost: false, cancelable: true)
                    .WaitAsync(TimeSpan.FromSeconds(10));
                if (purchased && !entry.Used) entry.SetUsed();
                break;
            }
            case "buy_card":
            {
                var cardEntries = inventory.AllEntries.OfType<MerchantCardEntry>().ToArray();
                var entry = cardEntries.SingleOrDefault(candidate =>
                    candidate.IsStocked && candidate.CreationResult is { Card: { } offered }
                    && (offered.Id.ToString() == targetId
                        || offered.Id.Entry == targetId
                        || "CARD." + offered.Id.Entry == targetId))
                    ?? throw new InvalidOperationException("Recorded merchant card is absent at step "
                        + step.GlobalStep + ": " + targetId + "; native="
                        + string.Join(',', cardEntries.Select(candidate =>
                            (candidate.CreationResult?.Card.Id.ToString() ?? "null") + ":"
                            + candidate.Cost + ":" + candidate.IsStocked)));
                if (entry.Cost != recordedCost)
                    throw new InvalidOperationException("Collector merchant card cost differs at step "
                        + step.GlobalStep);
                purchased = await entry.OnTryPurchaseWrapper(inventory, ignoreCost: false)
                    .WaitAsync(TimeSpan.FromSeconds(10));
                break;
            }
            case "buy_relic":
            {
                var entry = inventory.AllEntries.OfType<MerchantRelicEntry>().Single(candidate =>
                    candidate.IsStocked && candidate.Model is { } offered
                    && (offered.Id.ToString() == targetId
                        || offered.Id.Entry == targetId
                        || "RELIC." + offered.Id.Entry == targetId));
                if (entry.Cost != recordedCost)
                    throw new InvalidOperationException("Collector merchant relic cost differs at step "
                        + step.GlobalStep);
                purchased = await entry.OnTryPurchaseWrapper(inventory, ignoreCost: false)
                    .WaitAsync(TimeSpan.FromSeconds(10));
                break;
            }
            case "buy_potion":
            {
                var entry = inventory.AllEntries.OfType<MerchantPotionEntry>().Single(candidate =>
                    candidate.IsStocked && candidate.Model is { } offered
                    && (offered.Id.ToString() == targetId
                        || offered.Id.Entry == targetId
                        || "POTION." + offered.Id.Entry == targetId));
                if (entry.Cost != recordedCost)
                    throw new InvalidOperationException("Collector merchant potion cost differs at step "
                        + step.GlobalStep);
                purchased = await entry.OnTryPurchaseWrapper(inventory, ignoreCost: false)
                    .WaitAsync(TimeSpan.FromSeconds(10));
                break;
            }
            default:
                throw new NotSupportedException("Collector merchant action is not implemented: " + kind);
        }
        if (!purchased)
            throw new InvalidOperationException("Native merchant rejected recorded purchase at step "
                + step.GlobalStep + ": " + kind + "/" + targetId);
        return 1 + selections;
    }

    private static void ApplyCollectorMerchantPotionCosts(Player player, MerchantRoom merchant)
    {
        if (!MegaCrit.Sts2.Core.TestSupport.TestMode.IsOn
            || MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
            return;
        var costField = AccessTools.Field(typeof(MerchantEntry), "_cost")
            ?? throw new InvalidOperationException("Native merchant cost field is unavailable.");
        foreach (MerchantPotionEntry entry in merchant.GetLocalInventory().PotionEntries)
        {
            int baseCost = entry.Model?.Rarity switch
            {
                MegaCrit.Sts2.Core.Entities.Potions.PotionRarity.Rare => 100,
                MegaCrit.Sts2.Core.Entities.Potions.PotionRarity.Uncommon => 75,
                _ => 50,
            };
            int normalCost = Mathf.RoundToInt(baseCost * player.PlayerRng.Shops.NextFloat(0.95f, 1.05f));
            costField.SetValue(entry, normalCost);
        }
    }

    private static async Task<int> ReplayCollectorCombatAsync(Node host, CombatRoom room,
        RunState run, Player player, IReadOnlyList<CollectorStep> steps,
        AutoProbeCardSelector selector)
    {
        await WaitForCombatDecisionAsync(host, room, player, null);
        int matched = 0;
        for (int index = 0; index < steps.Count; index++)
        {
            var step = steps[index];
            if (step.ExecutionStatus == "cancelled")
            {
                if (step.Observation.TryGetProperty("pending_manual_actions", out var pending)
                    && pending.ValueKind != JsonValueKind.Array)
                    throw new InvalidDataException("Cancelled combat input has no pending-action audit state at step "
                        + step.GlobalStep);
                continue;
            }
            if (room.IsPreFinished || player.Creature.IsDead)
                throw new InvalidOperationException("Collector has an action after native combat terminal at step "
                    + step.GlobalStep);
            VerifyCollectorCombat(step.Observation, room, run, player, step.GlobalStep,
                strictBoundary: matched == 0);
            string kind = step.Action.GetProperty("kind").GetString() ?? "";
            var actions = CombatCaptureService.GetLegalActions(room.CombatState);
            CombatActionDescriptor action;
            if (kind == "end_turn")
            {
                action = actions.Single(candidate => candidate.Kind == CombatActionKind.EndTurn);
            }
            else if (kind == "play_card")
            {
                int recordedIndex = step.Action.GetProperty("combat_card_index").GetInt32();
                var recordedHand = CollectorPile(step.Observation, "Hand").ToArray();
                int recordedPosition = Array.FindIndex(recordedHand,
                    card => card.GetProperty("combat_card_index").GetInt32() == recordedIndex);
                if (recordedPosition < 0)
                    throw new InvalidOperationException("Collector card is not in hand at step " + step.GlobalStep);
                var recordedCard = recordedHand[recordedPosition];
                string model = recordedCard.GetProperty("model_id").GetString() ?? "";
                int upgrade = recordedCard.GetProperty("upgrade_level").GetInt32();
                string enchantment = NullableString(recordedCard, "enchantment_id");
                int ordinal = recordedHand.Take(recordedPosition).Count(card =>
                    (card.GetProperty("model_id").GetString() ?? "") == model
                    && card.GetProperty("upgrade_level").GetInt32() == upgrade
                    && NullableString(card, "enchantment_id") == enchantment);
                var nativeCard = player.PlayerCombatState!.Hand.Cards.Where(card =>
                        card.Id.ToString() == model && card.CurrentUpgradeLevel == upgrade
                        && (card.Enchantment?.Id.ToString() ?? "") == enchantment)
                    .Skip(ordinal).FirstOrDefault()
                    ?? throw new InvalidOperationException("Collector hand identity differs at step "
                        + step.GlobalStep + ": " + model);
                uint? targetId = MapCollectorTarget(step, room, player);
                uint cardIndex = NetCombatCard.FromModel(nativeCard).CombatCardIndex;
                action = actions.Single(candidate => candidate.Kind == CombatActionKind.PlayCard
                    && candidate.CombatCardIndex == cardIndex && candidate.TargetCreatureId == targetId);
            }
            else if (kind == "use_potion")
            {
                uint slot = step.Action.GetProperty("potion_index").GetUInt32();
                uint? targetId = MapCollectorTarget(step, room, player);
                action = GetNativePotionActions(room.CombatState, player).Single(candidate =>
                    candidate.PotionIndex == slot && candidate.TargetCreatureId == targetId);
            }
            else
            {
                throw new NotSupportedException("Collector combat action is not implemented at step "
                    + step.GlobalStep + ": " + kind);
            }

            int choiceCount = 0;
            while (index + 1 + choiceCount < steps.Count
                && StringProperty(steps[index + 1 + choiceCount].Action, "kind") == "resolve_choice")
            {
                QueueCollectorCombatChoice(steps[index + 1 + choiceCount], player, selector);
                choiceCount++;
            }
            var nativeAction = CombatActionExecutor.CreateGameAction(room.CombatState, action);
            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(nativeAction);
            matched += 1 + choiceCount;
            await WaitForCombatDecisionAsync(host, room, player, nativeAction);
            index += choiceCount;
        }
        return matched;
    }

    private static uint? MapCollectorTarget(CollectorStep step, CombatRoom room, Player player)
    {
        if (!step.Action.TryGetProperty("target_creature_id", out var target)
            || target.ValueKind != JsonValueKind.Number)
            return null;
        int recordedTarget = target.GetInt32();
        var recordedCreatures = step.Observation.GetProperty("creatures").EnumerateArray().ToArray();
        var recorded = recordedCreatures.SingleOrDefault(creature =>
            creature.GetProperty("combat_id").GetInt32() == recordedTarget);
        if (recorded.ValueKind == JsonValueKind.Undefined)
            throw new InvalidOperationException("Collector target is absent at step " + step.GlobalStep);
        if (recorded.GetProperty("player_id").ValueKind == JsonValueKind.Number)
            return player.Creature.CombatId;
        string recordedModel = recorded.GetProperty("monster_id").GetString() ?? "";
        var recordedSameModel = recordedCreatures.Where(creature =>
            creature.GetProperty("monster_id").ValueKind == JsonValueKind.String
            && creature.GetProperty("current_hp").GetInt32() > 0
            && creature.GetProperty("monster_id").GetString() == recordedModel).ToArray();
        int targetOrdinal = Array.FindIndex(recordedSameModel, creature =>
            creature.GetProperty("combat_id").GetInt32() == recordedTarget);
        var nativeSameModel = room.CombatState.Enemies.Where(enemy => enemy.IsAlive
            && enemy.ModelId.ToString() == recordedModel).ToArray();
        if (targetOrdinal < 0 || targetOrdinal >= nativeSameModel.Length)
            throw new InvalidOperationException("Collector target differs at step " + step.GlobalStep
                + ": model=" + recordedModel + ", ordinal=" + targetOrdinal
                + ", native=" + string.Join(',', room.CombatState.Enemies.Where(enemy => enemy.IsAlive)
                    .Select(enemy => enemy.ModelId.ToString())));
        return nativeSameModel[targetOrdinal].CombatId;
    }

    private static void QueueCollectorCombatChoice(
        CollectorStep choiceStep, Player player, AutoProbeCardSelector selector)
    {
        var choice = choiceStep.Observation.GetProperty("active_choice");
        var candidates = choice.GetProperty("cards").EnumerateArray().ToArray();
        if (choiceStep.Action.TryGetProperty("selected_combat_card_ids", out var selectedIds)
            && selectedIds.ValueKind == JsonValueKind.Array)
        {
            var recordedCardsById = choiceStep.Observation.GetProperty("players").EnumerateArray().Single()
                .GetProperty("piles").EnumerateArray()
                .SelectMany(pile => pile.GetProperty("cards").EnumerateArray().Select(card => card.Clone()))
                .Where(card => card.GetProperty("combat_card_index").ValueKind == JsonValueKind.Number)
                .ToDictionary(card => card.GetProperty("combat_card_index").GetUInt32());
            (string Model, int Upgrade, string Enchantment) Signature(JsonElement candidate)
            {
                uint id = candidate.GetProperty("combat_card_index").GetUInt32();
                var detailed = recordedCardsById.TryGetValue(id, out var pileCard) ? pileCard : candidate;
                return (StringProperty(detailed, "model_id"),
                    detailed.GetProperty("upgrade_level").GetInt32(),
                    NullableString(detailed, "enchantment_id"));
            }
            var selected = selectedIds.EnumerateArray().Select(id => id.GetUInt32()).ToArray();
            var identities = selected.Select(id =>
            {
                int position = Array.FindIndex(candidates, candidate =>
                    candidate.GetProperty("combat_card_index").ValueKind == JsonValueKind.Number
                    && candidate.GetProperty("combat_card_index").GetUInt32() == id);
                if (position < 0)
                    throw new InvalidOperationException("Collector selected choice card is absent at step "
                        + choiceStep.GlobalStep + ": " + id);
                var signature = Signature(candidates[position]);
                int ordinal = candidates.Take(position).Count(previous =>
                    Signature(previous) == signature);
                return new ProbeCardSelectionIdentity(signature.Model, signature.Upgrade,
                    signature.Enchantment, ordinal);
            }).ToArray();
            selector.ForcedCardIdentitySelections.Enqueue(identities);
            return;
        }
        if (choiceStep.Action.TryGetProperty("option_index", out var optionIndex)
            && optionIndex.ValueKind == JsonValueKind.Number)
        {
            int index = optionIndex.GetInt32();
            var candidate = candidates.Single(card => card.GetProperty("option_index").GetInt32() == index);
            selector.ForcedCardModelSelections.Enqueue([
                candidate.GetProperty("model_id").GetString() ?? ""]);
            return;
        }
        throw new InvalidOperationException("Collector choice has no concrete selection at step "
            + choiceStep.GlobalStep);
    }

    private static void VerifyCollectorCombat(JsonElement observation, CombatRoom room,
        RunState run, Player player, int step, bool strictBoundary)
    {
        if (observation.GetProperty("round_number").GetInt32() != room.CombatState.RoundNumber)
            throw new InvalidOperationException("Collector combat round differs at step " + step);
        // The live journal records click-time state and permits another click
        // while earlier cards or the turn-start draw are still animating. The
        // headless executor settles those native actions immediately, so only
        // the first decision of each combat has an identical pile boundary.
        // Later steps are checked by native legality/action identity and the
        // exact post-combat outside state.
        if (!strictBoundary)
            return;
        var recordedPlayer = observation.GetProperty("players").EnumerateArray().Single();
        var recordedCreature = observation.GetProperty("creatures").EnumerateArray()
            .Single(creature => creature.GetProperty("player_id").ValueKind == JsonValueKind.Number);
        if (recordedPlayer.GetProperty("energy").GetInt32() != player.PlayerCombatState!.Energy
            || recordedCreature.GetProperty("current_hp").GetInt32() != player.Creature.CurrentHp
            || recordedCreature.GetProperty("block").GetInt32() != player.Creature.Block
            )
            throw new InvalidOperationException("Collector combat scalar state differs at step " + step);
        bool hasPendingManualActions = observation.GetProperty("pending_manual_actions")
            .GetArrayLength() > 0;
        var recordedHand = CollectorPile(observation, "Hand").Select(CardSignature).Order().ToArray();
        var recordedDraw = CollectorPile(observation, "Draw").Select(CardSignature).Order().ToArray();
        var nativeHand = player.PlayerCombatState.AllPiles.Single(pile =>
                pile.Type.ToString().Equals("Hand", StringComparison.OrdinalIgnoreCase))
            .Cards.Select(NativeCardSignature).Order().ToArray();
        var nativeDraw = player.PlayerCombatState.AllPiles.Single(pile =>
                pile.Type.ToString().Equals("Draw", StringComparison.OrdinalIgnoreCase))
            .Cards.Select(NativeCardSignature).Order().ToArray();
        if (!recordedHand.SequenceEqual(nativeHand) || !recordedDraw.SequenceEqual(nativeDraw))
        {
            var recordedCombined = recordedHand.Concat(recordedDraw).Order().ToArray();
            var nativeCombined = nativeHand.Concat(nativeDraw).Order().ToArray();
            bool nativeAdvancedPendingDraw = recordedCombined.SequenceEqual(nativeCombined)
                && IsMultisetSubset(recordedHand, nativeHand);
            if (!nativeAdvancedPendingDraw)
                throw new InvalidOperationException("Collector hand/draw piles differ at step " + step
                    + ": recordedHand=" + string.Join(',', recordedHand)
                    + "; nativeHand=" + string.Join(',', nativeHand));
        }
        string[] resolvedPileNames = ["Discard", "Exhaust", "Play"];
        if (hasPendingManualActions)
        {
            var recorded = resolvedPileNames.SelectMany(name => CollectorPile(observation, name))
                .Select(CardSignature).Order().ToArray();
            var native = player.PlayerCombatState.AllPiles
                .Where(pile => resolvedPileNames.Contains(pile.Type.ToString(),
                    StringComparer.OrdinalIgnoreCase))
                .SelectMany(pile => pile.Cards).Select(card => card.Id.ToString() + ":"
                    + card.CurrentUpgradeLevel + ":" + (card.Enchantment?.Id.ToString() ?? ""))
                .Order().ToArray();
            if (!recorded.SequenceEqual(native))
                throw new InvalidOperationException("Collector pending resolved piles differ at step " + step);
        }
        else
        {
            foreach (string pileName in resolvedPileNames)
            {
                var recorded = CollectorPile(observation, pileName)
                    .Select(CardSignature).Order().ToArray();
                var nativePile = player.PlayerCombatState.AllPiles.Single(pile =>
                    pile.Type.ToString().Equals(pileName, StringComparison.OrdinalIgnoreCase));
                var native = nativePile.Cards.Select(card => card.Id.ToString() + ":"
                        + card.CurrentUpgradeLevel + ":" + (card.Enchantment?.Id.ToString() ?? ""))
                    .Order().ToArray();
                if (!recorded.SequenceEqual(native))
                    throw new InvalidOperationException("Collector " + pileName + " pile differs at step " + step);
            }
        }
        var recordedEnemies = observation.GetProperty("creatures").EnumerateArray()
            .Where(creature => creature.GetProperty("monster_id").ValueKind == JsonValueKind.String
                && creature.GetProperty("current_hp").GetInt32() > 0)
            .Select(creature => (creature.GetProperty("monster_id").GetString() ?? "",
                creature.GetProperty("current_hp").GetInt32(), creature.GetProperty("block").GetInt32())).ToArray();
        var nativeEnemies = room.CombatState.Enemies.Where(enemy => enemy.IsAlive)
            .Select(enemy => (enemy.ModelId.ToString(), enemy.CurrentHp, enemy.Block)).ToArray();
        if (!hasPendingManualActions && !recordedEnemies.SequenceEqual(nativeEnemies))
            throw new InvalidOperationException("Collector enemies differ at step " + step
                + ": recorded=" + string.Join(',', recordedEnemies)
                + "; native=" + string.Join(',', nativeEnemies));
    }

    private static IEnumerable<JsonElement> CollectorPile(JsonElement observation, string pileName)
    {
        var player = observation.GetProperty("players").EnumerateArray().Single();
        return player.GetProperty("piles").EnumerateArray()
            .Single(pile => (pile.GetProperty("pile_type").GetString() ?? "") == pileName)
            .GetProperty("cards").EnumerateArray().Select(card => card.Clone());
    }

    private static string CardSignature(JsonElement card) =>
        (card.GetProperty("model_id").GetString() ?? "") + ":"
        + card.GetProperty("upgrade_level").GetInt32() + ":"
        + NullableString(card, "enchantment_id");

    private static string NativeCardSignature(CardModel card) => card.Id.ToString() + ":"
        + card.CurrentUpgradeLevel + ":" + (card.Enchantment?.Id.ToString() ?? "");

    private static bool IsMultisetSubset(IEnumerable<string> subset, IEnumerable<string> superset)
    {
        var counts = superset.GroupBy(value => value).ToDictionary(group => group.Key,
            group => group.Count(), StringComparer.Ordinal);
        foreach (string value in subset)
        {
            if (!counts.TryGetValue(value, out int count) || count == 0)
                return false;
            counts[value] = count - 1;
        }
        return true;
    }

    private static string NullableString(JsonElement element, string property)
        => element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? "" : "";

    private static void VerifyCollectorOutsidePlayer(JsonElement observation, RunState run,
        Player player, string where)
    {
        var recorded = observation.GetProperty("players").EnumerateArray().Single();
        if (recorded.GetProperty("current_hp").GetInt32() != player.Creature.CurrentHp
            || recorded.GetProperty("max_hp").GetInt32() != player.Creature.MaxHp
            || recorded.GetProperty("gold").GetInt32() != player.Gold
            || observation.GetProperty("total_floor").GetInt32() != run.TotalFloor)
            throw new InvalidOperationException("Collector player scalar state differs " + where + ".");
        var recordedDeck = recorded.GetProperty("deck").EnumerateArray().Select(CardSignature).Order().ToArray();
        var nativeDeck = player.Deck.Cards.Select(card => card.Id.ToString() + ":"
                + card.CurrentUpgradeLevel + ":" + (card.Enchantment?.Id.ToString() ?? ""))
            .Order().ToArray();
        if (!recordedDeck.SequenceEqual(nativeDeck))
            throw new InvalidOperationException("Collector deck differs " + where + ": recorded="
                + string.Join(',', recordedDeck) + "; native=" + string.Join(',', nativeDeck));
        var recordedRelics = recorded.GetProperty("relics").EnumerateArray()
            .Select(relic => relic.GetProperty("model_id").GetString() ?? "").Order().ToArray();
        var nativeRelics = player.Relics.Select(relic => relic.Id.ToString()).Order().ToArray();
        if (!recordedRelics.SequenceEqual(nativeRelics))
            throw new InvalidOperationException("Collector relics differ " + where + ".");
        var recordedPotions = recorded.GetProperty("potions").EnumerateArray()
            .Select(potion => potion.GetProperty("slot_index").GetInt32() + ":"
                + (potion.GetProperty("model_id").GetString() ?? "")).Order().ToArray();
        var nativePotions = player.PotionSlots.Select((potion, index) => (potion, index))
            .Where(entry => entry.potion is not null)
            .Select(entry => entry.index + ":" + entry.potion!.Id.ToString()).Order().ToArray();
        if (!recordedPotions.SequenceEqual(nativePotions))
            throw new InvalidOperationException("Collector potion slots differ " + where
                + ": recorded=" + string.Join(',', recordedPotions)
                + "; native=" + string.Join(',', nativePotions));
    }

    private sealed class CollectorRewardSelectionScope : IDisposable
    {
        private static CollectorRewardSelectionScope? _active;
        private readonly IReadOnlyList<CollectorStep> _recordedSteps;
        private readonly Func<RewardsSet, Task>? _previousSelector;
        private readonly TaskCompletionSource _completion = new(
            TaskCreationOptions.RunContinuationsAsynchronously);

        private CollectorRewardSelectionScope(IReadOnlyList<CollectorStep> recordedSteps)
        {
            _recordedSteps = recordedSteps;
            _previousSelector = RewardsSet.testSelector;
        }

        internal Task Completion => _completion.Task;
        internal string[] SkippedRewardTypes { get; private set; } = [];

        internal static CollectorRewardSelectionScope Push(IReadOnlyList<CollectorStep> recordedSteps)
        {
            if (_active is not null)
                throw new InvalidOperationException("A collector reward selector is already active.");
            var scope = new CollectorRewardSelectionScope(recordedSteps);
            _active = scope;
            RewardsSet.testSelector = SelectActiveAsync;
            return scope;
        }

        private static Task SelectActiveAsync(RewardsSet rewardsSet) =>
            (_active ?? throw new InvalidOperationException("Collector reward selector is inactive."))
            .SelectAsync(rewardsSet);

        private async Task SelectAsync(RewardsSet rewardsSet)
        {
            try
            {
                var synchronizer = RunManager.Instance.RewardsSetSynchronizer;
                foreach (CollectorStep step in _recordedSteps)
                {
                    string kind = StringProperty(step.Action, "kind");
                    if (kind == "discard_potion")
                    {
                        int slot = step.Action.TryGetProperty("potion_slot_index", out var slotElement)
                            && slotElement.ValueKind == JsonValueKind.Number
                            ? slotElement.GetInt32() : -1;
                        if (slot < 0 || slot >= rewardsSet.Player.PotionSlots.Count
                            || rewardsSet.Player.PotionSlots[slot] is not { } potion
                            || !ModelMatches(potion.Id.ToString(), potion.Id.Entry,
                                StringProperty(step.Action, "target_id")))
                            throw new InvalidOperationException("Recorded reward-screen potion discard differs at step "
                                + step.GlobalStep);
                        await PotionCmd.Discard(potion);
                        if (rewardsSet.Player.PotionSlots[slot] is not null)
                            throw new InvalidOperationException("Native reward-screen potion discard did not clear slot "
                                + slot + " at step " + step.GlobalStep);
                        continue;
                    }
                    if (kind != "claim_reward") continue;
                    string target = StringProperty(step.Action, "target_id");
                    Reward? reward = rewardsSet.Rewards.FirstOrDefault(candidate =>
                        !candidate.SuccessfullySelected && RewardMatches(candidate, target));
                    if (reward is null)
                        throw new InvalidOperationException("Recorded reward is absent from the native set at step "
                            + step.GlobalStep + ": " + target);
                    await synchronizer.SelectLocalReward(reward);
                    bool resultDiffers = step.ExecutionStatus == "cancelled"
                        ? reward.SuccessfullySelected
                        : reward is not CardReward && !reward.SuccessfullySelected;
                    if (resultDiffers)
                        throw new InvalidOperationException("Native reward result differs at step "
                            + step.GlobalStep + ": status=" + step.ExecutionStatus
                            + ", rewardType=" + reward.GetType().Name
                            + ", selected=" + reward.SuccessfullySelected);
                }

                Reward[] pending = rewardsSet.Rewards
                    .Where(reward => !reward.SuccessfullySelected).ToArray();
                if (pending.Length > 0)
                {
                    bool recordedCardSkip = _recordedSteps.Any(step =>
                        step.Domain == "outside_combat"
                        && CollectorSurface(step) == "card_reward"
                        && StringProperty(step.Action, "kind") == "skip");
                    if (pending.Any(reward => reward is not PotionReward and not CardReward)
                        || pending.Any(reward => reward is CardReward) && !recordedCardSkip
                        || pending.Any(reward => reward is PotionReward)
                            && rewardsSet.Player.PotionSlots.Any(slot => slot is null))
                    {
                        throw new InvalidOperationException(
                            "Native reward set has an unrecorded pending reward: "
                            + string.Join(", ", pending.Select(reward => reward.GetType().Name)));
                    }
                    SkippedRewardTypes = pending.Select(reward => reward.GetType().Name).ToArray();
                    synchronizer.SkipLocalRewardsSet();
                }
                if (!synchronizer.IsRewardsSetCompleted(rewardsSet))
                    throw new InvalidOperationException("Native reward set did not complete after recorded actions.");
                _completion.TrySetResult();
            }
            catch (Exception exception)
            {
                _completion.TrySetException(exception);
                throw;
            }
        }

        private static bool RewardMatches(Reward reward, string target) => reward switch
        {
            GoldReward gold => target == "gold:" + gold.Amount,
            PotionReward potion => ModelMatches(potion.Potion?.Id.ToString(),
                potion.Potion?.Id.Entry, target),
            RelicReward relic => ModelMatches(relic.Relic?.Id.ToString(), relic.Relic?.Id.Entry, target),
            CardReward => target == "card_reward",
            _ => false,
        };

        private static bool ModelMatches(string? fullId, string? entry, string target) =>
            fullId == target || entry == target;

        public void Dispose()
        {
            RewardsSet.testSelector = _previousSelector;
            if (ReferenceEquals(_active, this))
                _active = null;
        }
    }
}

internal static class CollectorCrystalSpherePatch
{
    private const string HarmonyId = "SlayTheModel.NativeWorker.CollectorCrystalSphere";
    private static Scope? _active;

    internal static Scope Push()
    {
        if (_active is not null)
            throw new InvalidOperationException("A Crystal Sphere override is already active.");
        var harmony = new Harmony(HarmonyId);
        var scope = new Scope(harmony);
        _active = scope;
        harmony.Patch(AccessTools.Method(typeof(CrystalSphereMinigame),
                nameof(CrystalSphereMinigame.PlayMinigame)),
            prefix: new HarmonyMethod(typeof(CollectorCrystalSpherePatch), nameof(Prefix)));
        return scope;
    }

    private static bool Prefix(CrystalSphereMinigame __instance, ref Task __result)
    {
        if (_active is null || MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
            return true;
        _active.Capture(__instance);
        __result = PlayWithoutSceneAsync(__instance);
        return false;
    }

    private static async Task PlayWithoutSceneAsync(CrystalSphereMinigame game)
    {
        var completion = AccessTools.Field(typeof(CrystalSphereMinigame), "_completionSource")
            ?.GetValue(game) as TaskCompletionSource
            ?? throw new InvalidOperationException("Native Crystal Sphere completion source is unavailable.");
        await completion.Task;
        var completeMethod = AccessTools.Method(typeof(CrystalSphereMinigame), "CompleteMinigame")
            ?? throw new InvalidOperationException("Native Crystal Sphere completion method is unavailable.");
        var completeTask = completeMethod.Invoke(game, null) as Task
            ?? throw new InvalidOperationException("Native Crystal Sphere completion returned no task.");
        await completeTask;
    }

    internal sealed class Scope(Harmony harmony) : IDisposable
    {
        private readonly TaskCompletionSource<CrystalSphereMinigame> _captured = new(
            TaskCreationOptions.RunContinuationsAsynchronously);

        internal Task<CrystalSphereMinigame> Captured => _captured.Task;

        internal void Capture(CrystalSphereMinigame game)
        {
            if (!_captured.TrySetResult(game))
                throw new InvalidOperationException("Collector Crystal Sphere captured more than one minigame.");
        }

        public void Dispose()
        {
            harmony.UnpatchAll(HarmonyId);
            if (ReferenceEquals(_active, this))
                _active = null;
        }
    }
}

internal static class CollectorBundleChoicePatch
{
    private const string HarmonyId = "SlayTheModel.NativeWorker.CollectorBundleChoice";
    private static string[]? _selectedModelIds;

    internal static IDisposable Push(string[] selectedModelIds)
    {
        if (_selectedModelIds is not null)
            throw new InvalidOperationException("A collector bundle override is already active.");
        _selectedModelIds = selectedModelIds;
        var harmony = new Harmony(HarmonyId);
        harmony.Patch(AccessTools.Method(typeof(CardSelectCmd), nameof(CardSelectCmd.FromChooseABundleScreen)),
            prefix: new HarmonyMethod(typeof(CollectorBundleChoicePatch), nameof(Prefix)));
        return new Scope(harmony);
    }

    private static bool Prefix(Player player,
        IReadOnlyList<IReadOnlyList<CardModel>> bundles,
        ref Task<IEnumerable<CardModel>> __result)
    {
        string[] selected = _selectedModelIds
            ?? throw new InvalidOperationException("Collector bundle override has no selection.");
        int bundleIndex = bundles.ToList().FindIndex(bundle =>
            bundle.Select(card => card.Id.ToString()).SequenceEqual(selected)
            || bundle.Select(card => card.Id.Entry).SequenceEqual(selected));
        if (bundleIndex < 0)
            throw new InvalidOperationException("Recorded collector bundle is absent from native choices: "
                + string.Join(',', selected));
        uint choiceId = RunManager.Instance.PlayerChoiceSynchronizer.ReserveChoiceId(player);
        var result = MegaCrit.Sts2.Core.GameActions.PlayerChoiceResult.FromIndex(bundleIndex);
        RunManager.Instance.PlayerChoiceSynchronizer.SyncLocalChoice(player, choiceId, result);
        __result = Task.FromResult<IEnumerable<CardModel>>(bundles[bundleIndex]);
        return false;
    }

    private sealed class Scope(Harmony harmony) : IDisposable
    {
        public void Dispose()
        {
            harmony.UnpatchAll(HarmonyId);
            _selectedModelIds = null;
        }
    }
}

internal static class CollectorDenseVegetationRestPatch
{
    private const string HarmonyId = "SlayTheModel.NativeWorker.CollectorDenseVegetationRest";
    private static bool _active;

    internal static IDisposable Push()
    {
        if (_active)
            throw new InvalidOperationException("A Dense Vegetation rest override is already active.");
        _active = true;
        var harmony = new Harmony(HarmonyId);
        harmony.Patch(AccessTools.Method(
                typeof(MegaCrit.Sts2.Core.Models.Events.DenseVegetation), "Rest"),
            prefix: new HarmonyMethod(typeof(CollectorDenseVegetationRestPatch), nameof(Prefix)));
        return new Scope(harmony);
    }

    private static bool Prefix(MegaCrit.Sts2.Core.Models.Events.DenseVegetation __instance,
        ref Task __result)
    {
        if (!_active || MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
            return true;
        __result = RestWithoutSceneAsync(__instance);
        return false;
    }

    private static async Task RestWithoutSceneAsync(
        MegaCrit.Sts2.Core.Models.Events.DenseVegetation denseVegetation)
    {
        var owner = denseVegetation.Owner
            ?? throw new InvalidOperationException("Dense Vegetation has no owner.");
        await PlayerCmd.MimicRestSiteHeal(owner, playSfx: false);

        var fightMethod = AccessTools.Method(denseVegetation.GetType(), "Fight")
            ?? throw new InvalidOperationException("Dense Vegetation Fight method is unavailable.");
        Task Fight() => (Task)(fightMethod.Invoke(denseVegetation, null)
            ?? throw new InvalidOperationException("Dense Vegetation Fight returned no task."));
        var fightOption = new MegaCrit.Sts2.Core.Events.EventOption(denseVegetation, Fight,
            "DENSE_VEGETATION.pages.REST.options.FIGHT");
        var description = new MegaCrit.Sts2.Core.Localization.LocString(
            denseVegetation.LocTable, "DENSE_VEGETATION.pages.REST.description");
        var setState = AccessTools.Method(typeof(EventModel), "SetEventState")
            ?? throw new InvalidOperationException("Native event state method is unavailable.");
        setState.Invoke(denseVegetation, [description, new[] { fightOption }]);
    }

    private sealed class Scope(Harmony harmony) : IDisposable
    {
        public void Dispose()
        {
            harmony.UnpatchAll(HarmonyId);
            _active = false;
        }
    }
}

internal static class CollectorAmalgamatorPatch
{
    private const string HarmonyId = "SlayTheModel.NativeWorker.CollectorAmalgamator";
    private static bool _active;

    internal static IDisposable Push()
    {
        if (_active)
            throw new InvalidOperationException("An Amalgamator override is already active.");
        _active = true;
        var harmony = new Harmony(HarmonyId);
        var type = typeof(MegaCrit.Sts2.Core.Models.Events.Amalgamator);
        harmony.Patch(AccessTools.Method(type, "CombineStrikes"),
            prefix: new HarmonyMethod(typeof(CollectorAmalgamatorPatch), nameof(StrikesPrefix)));
        harmony.Patch(AccessTools.Method(type, "CombineDefends"),
            prefix: new HarmonyMethod(typeof(CollectorAmalgamatorPatch), nameof(DefendsPrefix)));
        return new Scope(harmony);
    }

    private static bool StrikesPrefix(MegaCrit.Sts2.Core.Models.Events.Amalgamator __instance,
        ref Task __result)
    {
        if (!_active || MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
            return true;
        __result = CombineWithoutSceneAsync(__instance, CardTag.Strike, strike: true);
        return false;
    }

    private static bool DefendsPrefix(MegaCrit.Sts2.Core.Models.Events.Amalgamator __instance,
        ref Task __result)
    {
        if (!_active || MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
            return true;
        __result = CombineWithoutSceneAsync(__instance, CardTag.Defend, strike: false);
        return false;
    }

    private static async Task CombineWithoutSceneAsync(
        MegaCrit.Sts2.Core.Models.Events.Amalgamator amalgamator, CardTag tag, bool strike)
    {
        var owner = amalgamator.Owner
            ?? throw new InvalidOperationException("Amalgamator has no owner.");
        var prefs = new MegaCrit.Sts2.Core.CardSelection.CardSelectorPrefs(
            MegaCrit.Sts2.Core.CardSelection.CardSelectorPrefs.RemoveSelectionPrompt, 2);
        IEnumerable<CardModel> selected = await CardSelectCmd.FromDeckForRemoval(owner, prefs,
            card => card.Tags.Contains(tag) && card.Rarity == CardRarity.Basic && card.IsRemovable);
        await CardPileCmd.RemoveFromDeck(selected.ToList());
        CardModel combined = strike
            ? owner.RunState.CreateCard<MegaCrit.Sts2.Core.Models.Cards.UltimateStrike>(owner)
            : owner.RunState.CreateCard<MegaCrit.Sts2.Core.Models.Cards.UltimateDefend>(owner);
        await CardPileCmd.Add(combined, PileType.Deck);
        var description = new MegaCrit.Sts2.Core.Localization.LocString(amalgamator.LocTable,
            strike ? "AMALGAMATOR.pages.COMBINE_STRIKES.description"
                : "AMALGAMATOR.pages.COMBINE_DEFENDS.description");
        var setFinished = AccessTools.Method(typeof(EventModel), "SetEventFinished")
            ?? throw new InvalidOperationException("Native event finish method is unavailable.");
        setFinished.Invoke(amalgamator, [description]);
    }

    private sealed class Scope(Harmony harmony) : IDisposable
    {
        public void Dispose()
        {
            harmony.UnpatchAll(HarmonyId);
            _active = false;
        }
    }
}
