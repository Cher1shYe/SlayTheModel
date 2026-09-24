using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

public sealed record NativeMctsRequest(Guid Id, NativeCombatCheckpoint Checkpoint,
    IReadOnlyList<SearchAction> Prefix, string StateKey, int EntryHp,
    SearchAction? PreviousAction = null, int BudgetMilliseconds = 1000);
public sealed record NativeMctsResponse(Guid Id, SearchAction? Action, string? Error,
    int Simulations = 0, int RetainedVisits = 0, double SearchMilliseconds = 0, bool Rebuilt = false,
    string? NextStateKey = null, long StateTransitions = 0, long SimulatorForks = 0,
    string SimulatorBackend = "native", string SearchMode = "pure-mcts",
    int NetworkPriorCalls = 0, int NetworkValueCalls = 0, int NetworkFallbacks = 0,
    string? NetworkFallbackReason = null);
