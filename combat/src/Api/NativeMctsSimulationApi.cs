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
    int PotionSlot = -1,
    string PotionId = "",
    string CardType = "",
    bool GainsBlock = false,
    decimal Damage = 0,
    int? TargetHp = null,
    string? ChoiceKey = null,
    IReadOnlyList<NativeMctsSelectedCard>? SelectedCards = null,
    int? KnowledgeCurseCounter = null);

public sealed record NativeMctsState(
    string Key,
    bool Terminal,
    bool Won,
    int PlayerHp,
    int IncomingDamage,
    bool PendingChoice,
    IReadOnlyList<NativeMctsAction> LegalActions,
    int PlayerMaxHp);

/// <summary>Prediction-only API for an external MCTS host. It never runs Combat Solver's Beam search.</summary>
public sealed partial class NativeMctsSimulationSession : IDisposable
{
    private readonly CombatBeamSolver driver;
    private readonly CombatRootSnapshot capturedRoot;
    private SimulationSnapshot root;
    private SimulationSnapshot current;
    private NativeMctsState rootDescription;
    private int rootActionCount;
    private NativeMctsState currentDescription;
    private readonly List<SimulationSnapshot> transient = [];
    private sealed record PendingChoiceBranch(PlanAction Action, SimulationSnapshot Snapshot);
    private sealed record PendingChoiceGroup(IReadOnlyList<PendingChoiceBranch> Branches, int ChoiceIndex);
    private Dictionary<string, PendingChoiceGroup>? pendingChoices;
    private Dictionary<string, PendingChoiceGroup>? openingChoices;
    private readonly HashSet<SimulationSnapshot> persistent = new(ReferenceEqualityComparer.Instance);
    private IReadOnlyList<string> choiceDiagnostics = [];
    private int actionCount;
    private bool disposed;
    private readonly int genericPotionSlots;
    private readonly (MegaCrit.Sts2.Core.Entities.Creatures.Creature Identity, int MaxHp)[] rewardEnemies;

    internal NativeMctsSimulationSession(CombatRootSnapshot capturedRoot, bool includeTurnSetup = false)
    {
        this.capturedRoot = capturedRoot;
        genericPotionSlots = capturedRoot.PlayerIdentity.PotionSlots.Count;
        driver = NativeMctsSimulation.CreateDriver(capturedRoot, includeTurnSetup);
        root = includeTurnSetup ? driver.NativeMctsCreateSetupRoot() : driver.NativeMctsCreateRoot();
        current = root;
        var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)root.Simulator;
        rewardEnemies = capturedRoot.Enemies
            .Select(enemy => (Identity: enemy, State: simulator.State.GetCreature(enemy)))
            // Keep zero-HP enemies still in the roster (pending revival), too.
            .Where(enemy => enemy.State.MaxHp > 0)
            .Select(enemy => (enemy.Identity, enemy.State.MaxHp)).ToArray();
        if (includeTurnSetup && root.BoundaryReason == SearchBoundaryReason.PendingChoice)
        {
            var branches = driver.NativeMctsSetupBranches()
                .Select(item => new PendingChoiceBranch(item.Action, item.Snapshot)).ToArray();
            foreach (var branch in branches) persistent.Add(branch.Snapshot);
            openingChoices = branches.GroupBy(branch => NativeMctsSimulation.ChoiceKey(branch.Action, branch.Action, 0), StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => new PendingChoiceGroup(group.ToArray(), 0), StringComparer.Ordinal);
            pendingChoices = new(openingChoices, StringComparer.Ordinal);
            rootDescription = BuildPendingDescription();
        }
        else rootDescription = driver.NativeMctsDescribe(root, 0);
        currentDescription = rootDescription;
    }

    public NativeMctsState RestoreRoot()
    {
        ThrowIfDisposed();
        ReleasePendingChoices();
        ReleaseTransient();
        pendingChoices = openingChoices == null ? null : new(openingChoices, StringComparer.Ordinal);
        current = root;
        actionCount = rootActionCount;
        choiceDiagnostics = [];
        currentDescription = rootDescription;
        return currentDescription;
    }

    /// <summary>
    /// Retain the completed decision snapshot as the rollout root. Pending selectors keep
    /// their existing replay path; no suspended transaction is cloned or recaptured live.
    /// Absolute action count and the battle's original reward roster remain unchanged.
    /// </summary>
    public bool CommitDecisionRoot()
    {
        ThrowIfDisposed();
        if (pendingChoices != null || currentDescription.PendingChoice) return false;
        var obsolete = new HashSet<SimulationSnapshot>(transient, ReferenceEqualityComparer.Instance);
        obsolete.UnionWith(persistent);
        obsolete.Add(root);
        obsolete.Remove(current);
        root = current;
        rootDescription = currentDescription;
        rootActionCount = actionCount;
        transient.Clear();
        persistent.Clear();
        openingChoices = null;
        choiceDiagnostics = [];
        foreach (var snapshot in obsolete) snapshot.ReleaseSimulator();
        return true;
    }

    /// <summary>
    /// Diagnostics for the expansion that produced the current pending choice. The native worker
    /// reads this only when its real selector disagrees with the predicted choice boundary.
    /// </summary>
    public IReadOnlyList<string> ChoiceDiagnostics => choiceDiagnostics;

    public NativeMctsState Apply(NativeMctsAction action)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(action);
        if (pendingChoices != null)
        {
            if (!pendingChoices.TryGetValue(action.Key, out var selectedGroup))
                throw new InvalidOperationException($"Unknown prediction choice action {action.Key}.");
            foreach (var group in pendingChoices.Values.Where(group => !ReferenceEquals(group, selectedGroup)))
                ReleaseBranches(group.Branches);
            pendingChoices = null;

            int nextIndex = selectedGroup.ChoiceIndex + 1;
            var withMoreChoices = selectedGroup.Branches
                .Where(branch => ChoiceCount(branch.Action) > nextIndex)
                .GroupBy(branch => NativeMctsSimulation.ChoiceKey(
                    branch.Action, branch.Action, nextIndex), StringComparer.Ordinal)
                .ToDictionary(group => group.Key,
                    group => new PendingChoiceGroup(group.ToArray(), nextIndex),
                    StringComparer.Ordinal);
            if (withMoreChoices.Count > 0)
            {
                ReleaseBranches(selectedGroup.Branches
                    .Where(branch => ChoiceCount(branch.Action) <= nextIndex));
                pendingChoices = withMoreChoices;
                currentDescription = BuildPendingDescription();
                return currentDescription;
            }

            PendingChoiceBranch final = selectedGroup.Branches
                .Single(branch => ChoiceCount(branch.Action) == nextIndex);
            ReleaseBranches(selectedGroup.Branches.Where(branch => !ReferenceEquals(branch, final)));
            current = final.Snapshot;
            transient.Add(current);
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var expansion = driver.NativeMctsExpand(current, action, actionCount);
        choiceDiagnostics = expansion.ChoiceDiagnostics;
        if (expansion.Resolved.Count == 0)
            throw new InvalidOperationException($"Prediction action {action.Key} produced no resolved state.");
        bool hasNoChoices = expansion.Resolved.Count == 1
            && expansion.Resolved[0].Action.Choice == null
            && expansion.Resolved[0].Action.NestedChoices is not { Count: > 0 }
            && expansion.Resolved[0].Action.TurnStartChoices is not { Count: > 0 };
        // A mandatory selector with one actual option is auto-completed by native
        // STS2. Do not infer this from one semantic branch alone: two identical
        // card instances can collapse to one prediction branch while the native
        // selector still requires the player to choose an instance.
        if (expansion.Resolved.Count == 1
            && (hasNoChoices || expansion.AutoResolveSingleBranch))
        {
            current = expansion.Resolved[0].Snapshot;
            transient.Add(current);
            actionCount++;
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var branches = expansion.Resolved
            .Select(item => new PendingChoiceBranch(item.Action, item.Snapshot))
            .ToArray();
        pendingChoices = branches
            .GroupBy(branch => NativeMctsSimulation.ChoiceKey(
                expansion.BaseAction, branch.Action, 0), StringComparer.Ordinal)
            .ToDictionary(group => group.Key,
                group => new PendingChoiceGroup(group.ToArray(), 0),
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

    /// <summary>Endpoint HP deficit of the captured roster, including minions and reviving enemies. Never accumulated damage.</summary>
    public double EnemyDamageFraction
    {
        get
        {
            ThrowIfDisposed();
            var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)current.Simulator;
            double total = 0, lost = 0;
            foreach (var enemy in rewardEnemies)
            {
                total += enemy.MaxHp;
                lost += enemy.MaxHp - Math.Clamp(simulator.State.GetCreature(enemy.Identity).CurrentHp, 0, enemy.MaxHp);
            }
            return total == 0 ? 0 : Math.Clamp(lost / total, 0, 1);
        }
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
        {
            PendingChoiceBranch branch = pair.Value.Branches[0];
            return NativeMctsSimulation.ToPublicAction(branch.Action, pair.Key,
                choiceKey: pair.Key, choiceIndex: pair.Value.ChoiceIndex);
        }).ToArray();
        return new NativeMctsState(
            NativeMctsSimulation.PendingStateKey(current.StateKey, actions),
            false, false, current.PlayerHp, 0, true, actions, current.PlayerMaxHp);
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        ReleasePendingChoices();
        ReleaseTransient();
        root.ReleaseSimulator();
        foreach (var snapshot in persistent) snapshot.ReleaseSimulator();
        persistent.Clear();
    }

    private void ReleaseTransient()
    {
        HashSet<SimulationSnapshot> unique = new(transient, ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique.Where(snapshot => !persistent.Contains(snapshot)))
            snapshot.ReleaseSimulator();
        transient.Clear();
    }

    private void ReleasePendingChoices()
    {
        if (pendingChoices == null) return;
        HashSet<SimulationSnapshot> unique = new(
            pendingChoices.Values.SelectMany(candidate => candidate.Branches).Select(candidate => candidate.Snapshot),
            ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique.Where(snapshot => !persistent.Contains(snapshot))) snapshot.ReleaseSimulator();
        pendingChoices = null;
    }

    private static int ChoiceCount(PlanAction action)
        => NativeMctsSimulation.ExecutionChoices(action).Count;

    private void ReleaseBranches(IEnumerable<PendingChoiceBranch> branches)
    {
        var unique = new HashSet<SimulationSnapshot>(
            branches.Select(branch => branch.Snapshot), ReferenceEqualityComparer.Instance);
        foreach (SimulationSnapshot snapshot in unique.Where(snapshot => !persistent.Contains(snapshot)))
            snapshot.ReleaseSimulator();
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

    // Called before native SetupPlayerTurn begins, never from a suspended selector.
    public static Func<NativeMctsSimulationSession> FreezeTurnSetupRoot(CombatState state)
    {
        Initialize();
        var root = CombatRootSnapshot.Capture(state);
        return () => new NativeMctsSimulationSession(root, includeTurnSetup: true);
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
                // PlanCardToken.OptionOccurrence counts model + upgrade, not
                // full state keys (see CardChoiceSupport.CountTokenOccurrence).
                // Locate that instance first, then verify its semantic state.
                if (options[index].Id.Entry != selected.CardId
                    || options[index].CurrentUpgradeLevel != selected.UpgradeLevel)
                    continue;
                if (occurrence-- == 0) { found = index; break; }
            }
            if (found < 0) throw new InvalidOperationException($"Live choice identity {selected.StateKey} is unavailable.");
            bool knowledgeToken = selected.StateKey.Length == 0 && action.KnowledgeCurseCounter is { } counter
                && counter is >= 0 and <= 2
                && options[found] is MegaCrit.Sts2.Core.Models.Monsters.KnowledgeDemon.IChoosable
                && (selected.CardId == "DISINTEGRATION"
                    ? options[found].DynamicVars["DisintegrationPower"].BaseValue == 6 + counter
                    : selected.CardId == new[] { "MIND_ROT", "SLOTH", "WASTE_AWAY" }[counter]);
            if (!knowledgeToken && !string.Equals(CardChoiceSupport.ChoiceCardKey(options[found]), selected.StateKey, StringComparison.Ordinal))
                throw new InvalidOperationException($"Live choice state differs for {selected.CardId}+{selected.UpgradeLevel}#{selected.OptionOccurrence}.");
            if (result.Contains(found))
                throw new InvalidOperationException("A live choice cannot select the same card twice.");
            result.Add(found);
        }
        return result.ToArray();
    }

    public static string CaptureLiveContinuationKey(CombatState state)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            ContinuationStamp.CaptureLive(state).StateText)));

    public static string LiveSelectionSemanticKey(IReadOnlyList<MegaCrit.Sts2.Core.Models.CardModel> options, IEnumerable<int> selected)
        => System.Text.Json.JsonSerializer.Serialize(selected.Select(i => CardChoiceSupport.ChoiceCardKey(options[i]))
            .Order(StringComparer.Ordinal).ToArray());

    public static string CaptureLiveContinuationStateText(CombatState state)
        => ContinuationStamp.CaptureLive(state).StateText;
}
