using System.Text.Json;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

var root = Path.Combine(
    Path.GetTempPath(),
    $"SlayTheModel-HeadlessCollector-Smoke-{Guid.NewGuid():N}");
try
{
    var store = new CollectorStore(root);
    var build = new BuildIdentity(
        "v0.111.0",
        new string('a', 64),
        Guid.Empty.ToString("D"));
    var combat = CreateCombatDecision();
    var outside = CreateOutsideDecision(build);
    var crystalSphere = CreateCrystalSphereDecision(build);
    var start = CreateStart(build);
    var policy = new PolicyTrace(
        ActionActor.Policy,
        PolicyId: "headless-smoke-policy",
        MctsVisitCounts: [3, 1]);
    var humanInput = new PolicyTrace(
        ActionActor.Human,
        PolicyId: "headless-ui-human");

    using (var recorder = new HeadlessEpisodeRecorder(store, start))
    {
        var combatStep = recorder.BeginCombat(
            combat, InformationRegime.NoSl, selectedActionIndex: 0, policy);
        Assert(combatStep.GlobalStep == 0, "Combat should be the first global step.");
        recorder.RecordExecution(
            combatStep,
            CollectorExecutionStatus.Applied,
            nextStateFingerprint: new string('c', 64));
        recorder.RecordWholeRunV2Reward(
            combatStep,
            Metrics(hp: 80, gold: 99),
            Metrics(hp: 78, gold: 99));

        var outsideStep = recorder.BeginOutside(
            outside,
            InformationRegime.NoSl,
            selectedActionIndex: 1,
            humanInput);
        Assert(outsideStep.GlobalStep == 1, "Outside combat must continue the same step sequence.");
        Assert(outsideStep.SelectedActionKey == outside.LegalActions[1].ActionId,
            "The selected key must come from the protocol action set.");
        recorder.RecordExecution(
            outsideStep,
            CollectorExecutionStatus.ObservedTransition,
            nextStateFingerprint: new string('d', 64));
        recorder.RecordWholeRunV2Reward(
            outsideStep,
            Metrics(hp: 78, gold: 99),
            Metrics(hp: 78, gold: 124));
        var crystalStep = recorder.BeginOutside(
            crystalSphere,
            InformationRegime.NoSl,
            selectedActionIndex: 1,
            humanInput);
        Assert(crystalStep.GlobalStep == 2,
            "A headless Crystal Sphere decision must share the global sequence.");
        recorder.RecordExecution(
            crystalStep,
            CollectorExecutionStatus.ObservedTransition,
            nextStateFingerprint: new string('f', 64));
        recorder.RecordWholeRunV2Reward(
            crystalStep,
            Metrics(hp: 78, gold: 124),
            Metrics(hp: 78, gold: 124));
        recorder.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "terminal", EpisodeCompleteness.Complete));
    }

    var events = store.ReadEpisode(start.EpisodeId);
    var timestamp = events[0].RecordedAtUtc.ToUniversalTime()
        .ToString("yyyyMMdd'T'HHmmssfff'Z'", System.Globalization.CultureInfo.InvariantCulture);
    Assert(Path.GetFileName(store.GetCompletedEpisodePath(start.EpisodeId))
           == $"steam-unavailable_unknown_Aunknown_{timestamp}_{start.EpisodeId:N}.jsonl",
        "Headless episodes without player metadata need a stable, explicit filename fallback.");
    Assert(File.Exists(Path.Combine(root, "dataset-manifest.json")),
        "Headless and live should share the dataset-root manifest.");
    Assert(events.Count == 14, "Expected start, three four-event steps, and finish.");
    Assert(events.Select(e => e.EventSequence).SequenceEqual(Enumerable.Range(0, 14).Select(i => (long)i)),
        "Event sequence should be gapless.");
    Assert(events.All(e => e.Source == CollectorSource.Headless),
        "All events must retain the headless source.");
    Assert(events.Where(e => e.EventType == CollectorEventType.Decision)
            .Select(e => e.GlobalStep)
            .SequenceEqual(new long?[] { 0, 1, 2 }),
        "Combat and outside decisions must share one global-step sequence.");
    var decisionJson = events.Where(e => e.EventType == CollectorEventType.Decision)
        .Select(e => e.Payload.GetRawText()).ToArray();
    Assert(decisionJson.All(json => json.Contains("\"visible_counter\":0", StringComparison.Ordinal))
           && decisionJson.All(json => !json.Contains("stack_count", StringComparison.Ordinal)
                                      && !json.Contains("display_amount", StringComparison.Ordinal)
                                      && !json.Contains("is_used_up", StringComparison.Ordinal)),
        "Headless decisions must preserve visible relic zero without native relic fields.");
    Assert(decisionJson[2].Contains("\"crystal_sphere\"", StringComparison.Ordinal)
           && decisionJson[2].Contains("\"revealed_visual_id\"", StringComparison.Ordinal)
           && !decisionJson[2].Contains("\"hidden_reward\"", StringComparison.Ordinal),
        "The shared headless writer must preserve visible Crystal Sphere v3 fields.");
    Assert(events.Where(e => e.EventType == CollectorEventType.ActionSubmitted)
            .Select(e => e.Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options)?.Policy.Actor)
            .SequenceEqual(new ActionActor?[]
                { ActionActor.Policy, ActionActor.Human, ActionActor.Human }),
        "The headless source must preserve whether a policy or a UI human acted.");
    var rewards = events.Where(e => e.EventType == CollectorEventType.Reward)
        .Select(e => e.Payload.Deserialize<RewardPayload>(CollectorJson.Options)
                     ?? throw new InvalidOperationException("Missing reward payload."))
        .ToArray();
    Assert(rewards.Length == 3
           && rewards.All(reward => reward.RewardVersion == WholeRunV2RewardCalculator.Version
                                    && reward.Components.Count == 8)
           && rewards[0].Components["hp_delta"] == -2
           && rewards[1].Components["gold_delta"] == 25,
        "The shared whole-run-v2 calculator must preserve the expected deltas.");
    var finished = events[^1].Payload.Deserialize<EpisodeFinishedPayload>(CollectorJson.Options)
        ?? throw new InvalidOperationException("Missing finish payload.");
    Assert(finished.ValueTargetValid, "A clean complete run should have a valid value target.");
    Assert(finished.Completeness == EpisodeCompleteness.Complete,
        "A clean run should remain complete.");

    var strictStart = CreateStart(build);
    using (var recorder = new HeadlessEpisodeRecorder(store, strictStart))
    {
        AssertThrows<ArgumentOutOfRangeException>(() => recorder.BeginCombat(
            combat, InformationRegime.NoSl, selectedActionIndex: 2, policy));
        AssertThrows<ArgumentException>(() => recorder.BeginCombat(
            combat,
            InformationRegime.NoSl,
            selectedActionIndex: 0,
            policy with { MctsVisitCounts = [1] }));
        Assert(recorder.Snapshot.NextEventSequence == 1,
            "Invalid action or policy must not append a partial decision.");

        var step = recorder.BeginCombat(
            combat, InformationRegime.NoSl, selectedActionIndex: 0, policy);
        recorder.RecordExecution(step, CollectorExecutionStatus.Applied);
        AssertThrows<InvalidOperationException>(() => recorder.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "missing_reward", EpisodeCompleteness.Complete)));
        AssertThrows<InvalidOperationException>(() => recorder.BeginOutside(
            outside, InformationRegime.NoSl, selectedActionIndex: 0, policy));
        AssertThrows<InvalidDataException>(() => recorder.RecordReward(
            step, new Dictionary<string, double> { ["hp_delta"] = double.NaN }));
        AssertThrows<InvalidDataException>(() => recorder.RecordWholeRunV2Reward(
            step,
            Metrics(hp: null, gold: 99),
            Metrics(hp: 78, gold: 99)));
        Assert(recorder.Snapshot.Phase == EpisodePhase.AwaitingReward,
            "An invalid reward must leave the transaction open for a valid reward.");
        recorder.RecordWholeRunV2Reward(
            step,
            Metrics(hp: 80, gold: 99),
            Metrics(hp: 80, gold: 99));
        recorder.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "terminal", EpisodeCompleteness.Complete));
    }

    Assert(store.ReadEpisode(strictStart.EpisodeId)[^1].EventType
           == CollectorEventType.EpisodeFinished,
        "The strictness fixture should still publish after correcting its reward.");

    var setStart = CreateStart(build);
    var setDecision = CreateCardSetDecision(build);
    var chosenCards = new[] { 0, 4, 11, 18 }
        .Select(index => setDecision.Observation.CardSelectionOptions![index])
        .ToArray();
    var selectedSet = setDecision.LegalActions[0] with
    {
        IsSelectionTemplate = false,
        SelectedCards = chosenCards,
    };
    using (var recorder = new HeadlessEpisodeRecorder(store, setStart))
    {
        AssertThrows<InvalidDataException>(() => recorder.BeginOutside(
            setDecision, InformationRegime.NoSl, 0, humanInput));
        Assert(recorder.Snapshot.NextEventSequence == 1,
            "Missing concrete set must be rejected before writing a decision.");
        var step = recorder.BeginOutside(
            setDecision,
            InformationRegime.NoSl,
            0,
            humanInput,
            selectedAction: JsonSerializer.SerializeToElement(
                selectedSet, CollectorJson.Options));
        recorder.RecordExecution(
            step, CollectorExecutionStatus.Applied,
            nextStateFingerprint: new string('9', 64));
        recorder.RecordWholeRunV2Reward(
            step, Metrics(hp: 80, gold: 99), Metrics(hp: 80, gold: 99));
        recorder.Finish(new EpisodeFinishInput(
            Guid.NewGuid(), "victory", "terminal", EpisodeCompleteness.Complete));
    }
    var setEvents = store.ReadEpisode(setStart.EpisodeId);
    var setPayload = setEvents.Single(item =>
        item.EventType == CollectorEventType.ActionSubmitted)
        .Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options);
    Assert(setPayload?.SelectedAction?
               .Deserialize<OutsideCombatActionDescriptor>(CollectorJson.Options)?
               .SelectedCards?.Select(card => card.OptionIndex)
               .SequenceEqual([0, 4, 11, 18]) == true,
        "Headless and live must preserve the same concrete set label.");
    Console.WriteLine("headless_collector_smoke=ok");
}
finally
{
    if (Directory.Exists(root))
    {
        Directory.Delete(root, recursive: true);
    }
}

static EpisodeStartInput CreateStart(BuildIdentity build) => new(
    Guid.NewGuid(),
    Guid.NewGuid(),
    CollectorSource.Headless,
    build,
    "headless-smoke-revision",
    "whole-run-v2",
    NoSlExpected: true,
    new Dictionary<string, string> { ["purpose"] = "headless-smoke" });

static OutsideCombatDecisionPoint CreateCardSetDecision(BuildIdentity build)
{
    var candidates = Enumerable.Range(0, 19)
        .Select(index => new OutsideSelectedCardReference(
            index, $"CARD_{index}", index)).ToArray();
    var observation = new OutsideCombatObservation(
        OutsideCombatObservation.CurrentSchemaVersion,
        OutsideCombatSurfaceKind.CardGridChoice,
        new OutsideCombatChoiceContext(
            "headless:remove_four", new string('8', 64),
            OutsideCombatChoicePhase.Selection, 4, 4, 0, false, true),
        0, 1, 1, 0, "Event", null, null,
        [new OutsideRunPlayerObservation(
            1, "IRONCLAD", 80, 80, 99, 3,
            candidates.Select(card => new OutsideRunCardObservation(
                card.DeckIndex!.Value, card.ModelId, 0, null, null)).ToArray(),
            [], [])],
        [])
    {
        CardSelectionOptions = candidates,
    };
    var legal = new[]
    {
        new OutsideCombatActionDescriptor(
            "remove_card_set:0:set", OutsideCombatActionKind.RemoveCardSet, 0)
        {
            IsSelectionTemplate = true,
        },
    };
    return new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        build,
        0,
        ProtocolJson.ComputeOutsideStateFingerprint(build, observation, legal),
        observation,
        legal);
}

static CombatDecisionPoint CreateCombatDecision() => new(
    CombatDecisionPoint.CurrentSchemaVersion,
    DecisionIndex: 0,
    StateFingerprint: new string('b', 64),
    new CombatObservation(
        CombatObservation.CurrentSchemaVersion,
        RoundNumber: 1,
        CombatSide.Player,
        [new CombatPlayerObservation(
            PlayerId: 1,
            CharacterId: "IRONCLAD",
            Energy: 3,
            Stars: 0,
            TurnNumber: 1,
            Phase: "play",
            Piles: [new CombatPileObservation(
                "hand", [new CombatCardObservation(7, "STRIKE", 1, null, 0, [])])],
            Relics: [new RelicObservation("PEN_NIB")
            {
                Display = new RelicDisplayObservation(
                    "Active", false, false, 0, "Next attack deals double damage."),
            }, new RelicObservation("BURNING_BLOOD")
            {
                Display = new RelicDisplayObservation(
                    "Active", false, false, null, "Heal at the end of combat."),
            }],
            Potions: [],
            Orbs: [])],
        [new CreatureSnapshot(100, null, "CULTIST", 48, 48, 0, [])]),
    [new CombatActionDescriptor(
         CombatActionKind.PlayCard,
         ActorPlayerId: 1,
         CombatCardIndex: 7,
         TargetCreatureId: 100),
     new CombatActionDescriptor(CombatActionKind.EndTurn, ActorPlayerId: 1)]);

static OutsideCombatDecisionPoint CreateOutsideDecision(BuildIdentity build)
{
    var observation = new OutsideCombatObservation(
        2, // Headless's ordinary event fixture retains the v2 observation contract.
        OutsideCombatSurfaceKind.Event,
        new OutsideCombatChoiceContext(
            "event:headless-smoke",
            new string('e', 64),
            OutsideCombatChoicePhase.Default,
            MinSelections: null,
            MaxSelections: null,
            SelectedCount: 0,
            Cancelable: false,
            RequiresConfirmation: false),
        ActIndex: 0,
        ActFloor: 1,
        TotalFloor: 1,
        AscensionLevel: 0,
        RoomType: "Event",
        RoomModelId: null,
        CurrentMapCoordinate: null,
        Players: [new OutsideRunPlayerObservation(
            PlayerId: 1,
            CharacterId: "IRONCLAD",
            CurrentHp: 78,
            MaxHp: 80,
            Gold: 99,
            MaxPotionCount: 3,
            Deck: [],
            Relics: [new OutsideRunRelicObservation("PEN_NIB")
            {
                Display = new RelicDisplayObservation(
                    "Active", false, false, 0, "Next attack deals double damage."),
            }, new OutsideRunRelicObservation("BURNING_BLOOD")
            {
                Display = new RelicDisplayObservation(
                    "Active", false, false, null, "Heal at the end of combat."),
            }],
            Potions: [])],
        MapPoints: []);
    OutsideCombatActionDescriptor[] actions =
    [
        new("event:0", OutsideCombatActionKind.ChooseEventOption, 0, "OPTION_A"),
        new("event:1", OutsideCombatActionKind.ChooseEventOption, 1, "OPTION_B"),
    ];
    return new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        build,
        DecisionIndex: 1,
        ProtocolJson.ComputeOutsideStateFingerprint(build, observation, actions),
        observation,
        actions);
}

static OutsideCombatDecisionPoint CreateCrystalSphereDecision(BuildIdentity build)
{
    var ordinary = CreateOutsideDecision(build);
    var observation = ordinary.Observation with
    {
        SchemaVersion = 3,
        Surface = OutsideCombatSurfaceKind.CrystalSphere,
        ChoiceContext = ordinary.Observation.ChoiceContext with
        {
            ContextId = "crystal_sphere:headless-smoke",
        },
        CrystalSphere = new CrystalSphereBoardObservation(
            Width: 2,
            Height: 1,
            DivinationsRemaining: 1,
            SelectedTool: "small",
            IsFinished: false,
            Cells:
            [
                new CrystalSphereCellObservation(0, 0, true, false),
                new CrystalSphereCellObservation(1, 0, false, true,
                    "Gold", "icon:res://visible-gold.png"),
            ]),
    };
    OutsideCombatActionDescriptor[] actions =
    [
        new("crystal_sphere:tool:0", OutsideCombatActionKind.ChooseMinigameOption,
            0, "tool:small"),
        new("crystal_sphere:cell:1", OutsideCombatActionKind.ChooseMinigameOption,
            1, "cell:0,0"),
    ];
    return new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        build,
        DecisionIndex: 2,
        ProtocolJson.ComputeOutsideStateFingerprint(build, observation, actions),
        observation,
        actions);
}

static WholeRunV2Metrics Metrics(int? hp, int? gold) => new(
    CurrentHp: hp,
    Gold: gold,
    ActIndex: 0,
    TotalFloor: 1,
    DeckSize: 10,
    RelicCount: 1,
    PotionCount: 0);

static void Assert(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void AssertThrows<TException>(Action action) where TException : Exception
{
    try
    {
        action();
    }
    catch (TException)
    {
        return;
    }

    throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
}
