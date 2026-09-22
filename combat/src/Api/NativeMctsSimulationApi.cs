using MegaCrit.Sts2.Core.Combat;
using System.Security.Cryptography;
using System.Text;

namespace CombatSolver.Api;

public sealed record NativeMctsSelectedCard(string CardId, int UpgradeLevel, string StateKey, int OptionOccurrence);

public sealed record NativeMctsAction(
    string Key,
    string Kind,
    string CardId,
    int CardOccurrence,
    string CardStateKey,
    int CardStateOccurrence,
    int CardUpgradeLevel,
    string CardEnchantmentId,
    uint? TargetCombatId,
    string CardType = "",
    bool GainsBlock = false,
    decimal Damage = 0,
    int? TargetHp = null,
    string? ChoiceKey = null,
    IReadOnlyList<NativeMctsSelectedCard>? SelectedCards = null);

public sealed record NativeMctsState(
    string Key,
    bool Terminal,
    bool Won,
    int PlayerHp,
    int IncomingDamage,
    bool PendingChoice,
    IReadOnlyList<NativeMctsAction> LegalActions);

/// <summary>Prediction-only API for an external MCTS host. It never runs Combat Solver's Beam search.</summary>
public sealed class NativeMctsSimulationSession : IDisposable
{
    private readonly CombatBeamSolver driver;
    private readonly CombatRootSnapshot capturedRoot;
    private SimulationSnapshot root;
    private SimulationSnapshot current;
    private readonly NativeMctsState rootDescription;
    private NativeMctsState currentDescription;
    private readonly List<SimulationSnapshot> transient = [];
    private Dictionary<string, (PlanAction Action, SimulationSnapshot Snapshot)>? pendingChoices;
    private int actionCount;
    private bool disposed;

    internal NativeMctsSimulationSession(CombatRootSnapshot capturedRoot)
    {
        this.capturedRoot = capturedRoot;
        driver = NativeMctsSimulation.CreateDriver(capturedRoot);
        root = driver.NativeMctsCreateRoot();
        current = root;
        rootDescription = driver.NativeMctsDescribe(root, 0);
        currentDescription = rootDescription;
    }

    public NativeMctsState RestoreRoot()
    {
        ThrowIfDisposed();
        ReleasePendingChoices();
        ReleaseTransient();
        current = root;
        actionCount = 0;
        currentDescription = rootDescription;
        return currentDescription;
    }

    public NativeMctsState Apply(NativeMctsAction action)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(action);
        if (pendingChoices != null)
        {
            if (!pendingChoices.TryGetValue(action.Key, out var selected))
                throw new InvalidOperationException($"Unknown prediction choice action {action.Key}.");
            foreach (var candidate in pendingChoices.Values)
            {
                if (!ReferenceEquals(candidate.Snapshot, selected.Snapshot))
                    candidate.Snapshot.ReleaseSimulator();
            }
            pendingChoices = null;
            current = selected.Snapshot;
            transient.Add(current);
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var expansion = driver.NativeMctsExpand(current, action, actionCount);
        if (expansion.Resolved.Count == 0)
            throw new InvalidOperationException($"Prediction action {action.Key} produced no resolved state.");
        if (expansion.Resolved.Count == 1 && expansion.Resolved[0].Action.Choice == null
            && expansion.Resolved[0].Action.NestedChoices is not { Count: > 0 }
            && expansion.Resolved[0].Action.TurnStartChoices is not { Count: > 0 })
        {
            current = expansion.Resolved[0].Snapshot;
            transient.Add(current);
            actionCount++;
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        pendingChoices = expansion.Resolved.ToDictionary(
            item => NativeMctsSimulation.ChoiceKey(expansion.BaseAction, item.Action),
            item => item,
            StringComparer.Ordinal);
        actionCount++;
        currentDescription = BuildPendingDescription();
        return currentDescription;
    }

    public NativeMctsState DescribeCurrent()
    {
        ThrowIfDisposed();
        return currentDescription;
    }

    public string ContinuationKey
    {
        get
        {
            var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)current.Simulator;
            string text = ContinuationStamp.CapturePredicted(
                capturedRoot.PlayerIdentity,
                simulator,
                current.Turn,
                capturedRoot.Forecast,
                capturedRoot.StartTurnNumber).StateText;
            return Hash(text);
        }
    }

    public string ContinuationStateText
    {
        get
        {
            var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)current.Simulator;
            return ContinuationStamp.CapturePredicted(
                capturedRoot.PlayerIdentity,
                simulator,
                current.Turn,
                capturedRoot.Forecast,
                capturedRoot.StartTurnNumber).StateText;
        }
    }

    private NativeMctsState BuildPendingDescription()
    {
        var actions = pendingChoices!.Select(pair =>
            NativeMctsSimulation.ToPublicAction(pair.Value.Action, pair.Key, choiceKey: pair.Key)).ToArray();
        return new NativeMctsState(
            NativeMctsSimulation.PendingStateKey(current.StateKey, actions),
            false, false, current.PlayerHp, 0, true, actions);
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        ReleasePendingChoices();
        ReleaseTransient();
        root.ReleaseSimulator();
    }

    private void ReleaseTransient()
    {
        HashSet<SimulationSnapshot> unique = new(transient, ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique)
            snapshot.ReleaseSimulator();
        transient.Clear();
    }

    private void ReleasePendingChoices()
    {
        if (pendingChoices == null) return;
        HashSet<SimulationSnapshot> unique = new(
            pendingChoices.Values.Select(candidate => candidate.Snapshot),
            ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique) snapshot.ReleaseSimulator();
        pendingChoices = null;
    }

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(disposed, this);

    private static string Hash(string value)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
}

public static class NativeMctsSimulationApi
{
    private static int initialized;

    public static void Initialize()
    {
        if (Interlocked.Exchange(ref initialized, 1) != 0) return;
        Entry.InitializeSimulationRuntime();
    }

    public static NativeMctsSimulationSession Capture(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        Initialize();
        return new NativeMctsSimulationSession(CombatRootSnapshot.Capture(state));
    }

    public static MegaCrit.Sts2.Core.Models.CardModel ResolveLiveCard(
        CombatState state, NativeMctsAction action)
    {
        var player = MegaCrit.Sts2.Core.Context.LocalContext.GetMe(state)
            ?? throw new InvalidOperationException("Local player is unavailable.");
        var hand = player.PlayerCombatState?.Hand.Cards
            ?? throw new InvalidOperationException("Live hand is unavailable.");
        int occurrence = action.CardStateOccurrence;
        foreach (var card in hand)
        {
            if (!string.Equals(CardChoiceSupport.ChoiceCardKey(card), action.CardStateKey, StringComparison.Ordinal))
                continue;
            if (occurrence-- == 0) return card;
        }
        throw new InvalidOperationException($"Live card identity {action.CardStateKey}#{action.CardStateOccurrence} is unavailable.");
    }

    public static int[] ResolveLiveSelection(
        IReadOnlyList<MegaCrit.Sts2.Core.Models.CardModel> options, NativeMctsAction action)
    {
        var result = new List<int>();
        foreach (NativeMctsSelectedCard selected in action.SelectedCards ?? [])
        {
            int occurrence = selected.OptionOccurrence;
            int found = -1;
            for (int index = 0; index < options.Count; index++)
            {
                if (!string.Equals(CardChoiceSupport.ChoiceCardKey(options[index]), selected.StateKey, StringComparison.Ordinal))
                    continue;
                if (occurrence-- == 0) { found = index; break; }
            }
            if (found < 0) throw new InvalidOperationException($"Live choice identity {selected.StateKey} is unavailable.");
            result.Add(found);
        }
        return result.ToArray();
    }

    public static string CaptureLiveContinuationKey(CombatState state)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            ContinuationStamp.CaptureLive(state).StateText)));

    public static string CaptureLiveContinuationStateText(CombatState state)
        => ContinuationStamp.CaptureLive(state).StateText;
}
