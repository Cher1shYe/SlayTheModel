using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed record CapturedCombatDecision(CombatDecisionPoint Decision);
internal sealed record PreparedCombatChoice(DecisionReceipt Receipt);
internal sealed record CollectorActionDraft(DecisionReceipt Receipt, Guid AttemptId);
internal sealed record TestPending(Guid DecisionId, EpisodePhase Phase);
internal sealed record TestSnapshot(IReadOnlyList<TestPending> PendingDecisions);
internal static class CollectorPolicyTelemetry { internal static string AdapterRevision => "smoke-adapter"; }

internal sealed class TestEpisodeSink
{
    internal bool HasActiveEpisode => true;
    internal TestSnapshot Snapshot => new([]);
    internal long NextSourceDecisionIndex() => 0;
    internal PreparedCombatChoice PrepareCombatChoice(CapturedCombatDecision captured, string description) =>
        new(new DecisionReceipt(Guid.NewGuid(), 0, []));
    internal CollectorActionDraft ResolveCombatChoice(PreparedCombatChoice prepared, int ordinal,
        JsonElement? selectedAction, PolicyTrace? policy)
    {
        CollectorRuntime.Commits.Add(policy);
        return new(prepared.Receipt, Guid.NewGuid());
    }
    internal void Commit(CollectorActionDraft draft, CollectorExecutionStatus status, string? detail = null) { }
    internal void ResolveAtCurrentBoundary() { }
    internal bool FailStagedExecution(CollectorActionDraft draft, string detail) => true;
}

internal static class CollectorCombatProjector
{
    internal static CapturedCombatDecision WithChoiceDisplays(CapturedCombatDecision captured, object selector, IReadOnlyList<CardModel> options) => captured;
    internal static CapturedCombatDecision WithPendingManualActions(CapturedCombatDecision captured, IReadOnlyList<CombatActionDescriptor> actions) => captured;
    internal static CapturedCombatDecision CaptureCardChoice(CombatState state, IReadOnlyList<CardModel> options,
        int min, int max, bool canCancel, string description, long index, uint? id, bool requiresNativeCombatCardIds) =>
        throw new NotSupportedException("Projection is outside this smoke's boundary.");
}

internal static partial class CollectorRuntime
{
    private static readonly TestEpisodeSink _episodes = new();
    private static bool _stopping => false;
    private static readonly long _runGeneration = 1;
    private static readonly Guid? _combatId = Guid.NewGuid();
    private static readonly Dictionary<GameAction, CollectorActionDraft> PendingCombatActions = [];
    internal static List<string> Gaps { get; } = [];
    internal static List<PolicyTrace?> Commits { get; } = [];
    private static void RecordCoverageGap(string reason, object? data = null, bool invalidatePendingDecision = true,
        Guid? relatedDecisionId = null, Guid? relatedAttemptId = null, Guid? targetDecisionId = null) => Gaps.Add(reason);
    private static void RecordDiagnostic(string code, object data) { }
    private static bool IsLocalSinglePlayer(Player player) => true;
    private static IReadOnlyList<CombatActionDescriptor> PendingManualActionsAtClick() => [];
    private static void ObserveSelectorTask(Task task) { }
    private static void DrainCompletedSelectors() => DrainCompletedCombatChoices();
    private static Exception? SelectorTaskException(Task task) => task.Exception;
    private static void FinishPendingRun() { }
    internal static void TestCombatEnd() => CloseNativeChoiceTicketsAtCombatEnd();
    internal static void TestConfirmPrefix(NSimpleCardSelectScreen __instance) { }

    internal static PendingCombatCardChoice TestBegin(CardModel[] options, bool mcts = true)
    {
        ClearCombatChoiceState();
        Gaps.Clear();
        Commits.Clear();
        var choice = new CombatChoiceObservation(1, "card_selector", 0, options.Length, false,
            options.Select((_, index) => new CombatChoiceCardObservation((uint)(index + 10), "CARD.STRIKE_IRONCLAD", 0, index)).ToArray());
        var observation = new CombatObservation(5, 1, SlayTheModel.Sts2.Protocol.CombatSide.Player, [], []) { ActiveChoice = choice };
        var captured = new CapturedCombatDecision(new CombatDecisionPoint(1, 0, new string('a', 64), observation,
            CombatChoiceActionBuilder.Build(1, choice)));
        var pending = new PendingCombatCardChoice(new object(), options, captured, false, true, false,
            "card_selector", _runGeneration, _combatId)
        {
            IsMctsRequest = mcts,
            PolicyOverride = mcts ? new PolicyTrace(ActionActor.Policy, "native-mcts", "smoke-adapter",
                TeacherInformation: "native_checkpoint_privileged") : null,
        };
        PendingCombatChoices.Add(pending.Selector, pending);
        if (!mcts) NativeCombatChoiceTickets.Add(pending);
        return pending;
    }
}
