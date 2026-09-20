using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

public sealed record NativeMctsRequest(Guid Id, NativeCombatCheckpoint Checkpoint,
    IReadOnlyList<SearchAction> Prefix, string StateKey, int EntryHp);
public sealed record NativeMctsResponse(Guid Id, SearchAction? Action, string? Error,
    int Simulations = 0, int RetainedVisits = 0, double SearchMilliseconds = 0, bool Rebuilt = false);
