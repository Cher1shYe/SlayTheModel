using System.Security.Cryptography;
using System.Text;
using CombatSolver.Api;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Entities.Creatures;

namespace CombatSolver;

internal sealed partial class CombatBeamSolver
{
    // Native MCTS normally suppresses CombatSolver's verbose search log because every rollout
    // reconstructs the same prefixes many times. Keep only the diagnostics for the expansion
    // currently being materialized; the worker prints them if native and predicted choice
    // boundaries disagree.
    private List<string>? _nativeMctsChoiceDiagnostics;

    internal SimulationSnapshot NativeMctsCreateRoot() => Replay([]);

    internal int NativeMctsInitialEnemyHp => root.InitialEnemyEffectiveHp;

    internal NativeMctsState NativeMctsDescribe(SimulationSnapshot snapshot, int actionCount)
    {
        // Explicit choices are described by NativeMctsSimulationSession from the
        // resolved branch groups, not by treating a suspended probe as a terminal.
        if (snapshot.BoundaryReason == SearchBoundaryReason.PendingChoice)
            throw new InvalidOperationException("Unresolved choice probe escaped Native MCTS branch expansion.");
        if (snapshot.BoundaryReason is SearchBoundaryReason.UnsupportedEffect
            or SearchBoundaryReason.DynamicResolution)
        {
            throw new PredictionUnsupportedException(
                $"Native MCTS reached unsupported prediction boundary {snapshot.BoundaryReason}.");
        }
        bool terminal = snapshot.PlayerDead || snapshot.AllEnemiesDead
            || snapshot.BoundaryReason != SearchBoundaryReason.None;
        int incomingDamage = 0;
        NativeMctsAction[] actions = terminal ? [] : NativeMctsPreparedPublicActions(snapshot, actionCount, out incomingDamage);
        return new NativeMctsState(
            NativeMctsSimulation.DecisionStateKey(snapshot.StateKey, actions),
            terminal,
            snapshot.TerminalStamp is { Outcome: CombatTerminalOutcome.Victory },
            snapshot.TerminalStamp is { Outcome: CombatTerminalOutcome.Defeat },
            snapshot.TerminalStamp.HasValue,
            snapshot.PlayerHp,
            ((SimulatedCombatState)((CombatPredictionSimulator)snapshot.Simulator).State.CombatState)
                .KnownEnemies.Sum(enemy => ((SimulatedCombatState)((CombatPredictionSimulator)snapshot.Simulator)
                    .State.CombatState).GetMctsCumulativeEnemyHpLost(enemy)),
            NativeMctsInitialEnemyHp,
            incomingDamage,
            false,
            actions);
    }

    internal NativeMctsExpansion NativeMctsExpand(
        SimulationSnapshot snapshot, NativeMctsAction requested, int actionCount)
    {
        List<string> diagnostics = [];
        List<string>? previousDiagnostics = _nativeMctsChoiceDiagnostics;
        _nativeMctsChoiceDiagnostics = diagnostics;
        try
        {
            SearchNode node = NativeMctsNode(snapshot, actionCount);
            PlanAction action = new(
                Enum.Parse<PlanActionKind>(requested.Kind),
                snapshot.Turn,
                requested.CardId,
                requested.CardOccurrence,
                TargetCombatId: requested.TargetCombatId,
                CardStateKey: requested.CardStateKey,
                CardStateOccurrence: requested.CardStateOccurrence,
                CardUpgradeLevel: requested.CardUpgradeLevel,
                CardEnchantmentId: requested.CardEnchantmentId);
            if (action.Kind == PlanActionKind.EndTurn)
            {
                var endTurnResolved = BuildEndTurnBranches(node, []).ToArray();
                return new NativeMctsExpansion(action, endTurnResolved, diagnostics.ToArray());
            }

            CombatPredictionSimulator simulator = (CombatPredictionSimulator)snapshot.Simulator;
            SimPlayerCombatState playerState = simulator.State.GetPlayerCombatState(_player);
            PredictedCard card = FindCardForReplay(playerState.Hand.Cards, action)
                ?? throw new InvalidOperationException($"Prediction card {requested.Key} is no longer in hand.");
            PreparedCardAction prepared = new(
                action,
                card.Preview.Type,
                action.TargetCombatId,
                CardChoiceSupport.RequiresUnsupportedExistingChoice(card.Preview),
                CardChoiceSupport.BuildRequiredEmptyChoice(card.Preview));
            using CardChoiceReplayCapture? capture = PrepareCardChoiceCapture(node, action);
            SimulationSnapshot probe = ReplayAction(node, action, cardChoiceCapture: capture);
            CardChoiceSpec? choiceSpec = BuildPrimaryCardChoiceSpec(probe);
            if (choiceSpec == null && prepared.RequiresUnsupportedExistingChoice)
            {
                probe.ReleaseSimulator();
                throw new PredictionUnsupportedException($"Card {action.CardId} has an unsupported existing choice.");
            }
            CardChoiceSpec? primaryChoiceSpec = choiceSpec
                ?? BuildRequiredEmptyChoiceSpec(prepared.RequiredEmptyChoice);
            IEnumerable<(PlanAction Action, SimulationSnapshot Snapshot)> branches =
                HasChoiceBeforePrimary(probe, primaryChoiceSpec)
                    ? ResolveRoundChoiceBranches(node, action, probe,
                        BuildPrimaryChoiceMatch(primaryChoiceSpec), budgetPrimaryChoiceSpec: primaryChoiceSpec)
                    : ResolvePrimaryCardChoiceBranches(node, action, probe, choiceSpec, prepared.RequiredEmptyChoice);
            (PlanAction Action, SimulationSnapshot Snapshot)[] resolved =
                WithCardChoiceCheckpoint(capture?.Take(), branches).ToArray();
            RecordNativeMctsResolvedChoiceBranches(resolved);
            return new NativeMctsExpansion(action, resolved, diagnostics.ToArray());
        }
        finally
        {
            _nativeMctsChoiceDiagnostics = previousDiagnostics;
        }
    }

    private void RecordNativeMctsChoiceLayer(
        CardChoiceSpec spec,
        IReadOnlyList<PlanCardChoice> generated)
    {
        if (_nativeMctsChoiceDiagnostics == null)
            return;

        const int itemLimit = 128;
        string options = FormatDiagnosticItems(
            spec.Options.Select(card =>
                $"{card.Preview.Id.Entry}+{card.Preview.CurrentUpgradeLevel}" +
                $"@{CardChoiceSupport.ChoiceCardKey(card)}"),
            spec.Options.Count,
            itemLimit);
        string sourceCards = FormatDiagnosticItems(
            spec.SourceCards.Select(card =>
                $"{card.Preview.Id.Entry}+{card.Preview.CurrentUpgradeLevel}" +
                $"@{CardChoiceSupport.ChoiceCardKey(card)}"),
            spec.SourceCards.Count,
            itemLimit);
        string branches = FormatDiagnosticItems(
            generated.Select(choice => choice.Cards.Count == 0
                ? "<skip>"
                : string.Join('+', choice.Cards.Select(card =>
                    $"{card.CardId}+{card.UpgradeLevel}#{card.SourceOccurrence}/{card.OptionOccurrence}"))),
            generated.Count,
            itemLimit);
        _nativeMctsChoiceDiagnostics.Add(
            $"CHOICE_SPEC effect={spec.Effect} source={spec.SourcePile} " +
            $"min={spec.MinCount} max={spec.MaxCount} optionCount={spec.Options.Count} " +
            $"options=[{options}] sourceCount={spec.SourceCards.Count} sourceCards=[{sourceCards}]");
        _nativeMctsChoiceDiagnostics.Add(
            $"CHOICE_GENERATED count={generated.Count} branches=[{branches}]");
    }

    private void RecordNativeMctsChoiceReplayPruned(PlanAction action, Exception error)
        => _nativeMctsChoiceDiagnostics?.Add(
            $"CHOICE_REPLAY_PRUNED action={PolicyActionToken(action)} " +
            $"reason={error.GetType().Name}: {error.Message}");

    private void RecordNativeMctsResolvedChoiceBranches(
        IReadOnlyList<(PlanAction Action, SimulationSnapshot Snapshot)> resolved)
    {
        if (_nativeMctsChoiceDiagnostics == null)
            return;
        const int itemLimit = 128;
        string branches = FormatDiagnosticItems(
            resolved.Select(item =>
            {
                IReadOnlyList<PlanCardChoice> choices =
                    item.Action.GetActionChoicesInExecutionOrder();
                return choices.Count == 0
                    ? "<no-choice>"
                    : string.Join(" -> ", choices.Select(choice => choice.Cards.Count == 0
                        ? "<skip>"
                        : string.Join('+', choice.Cards.Select(card =>
                            $"{card.CardId}+{card.UpgradeLevel}#{card.SourceOccurrence}/{card.OptionOccurrence}"))));
            }),
            resolved.Count,
            itemLimit);
        _nativeMctsChoiceDiagnostics.Add(
            $"CHOICE_RESOLVED count={resolved.Count} branches=[{branches}]");
    }

    private static string FormatDiagnosticItems(
        IEnumerable<string> items,
        int totalCount,
        int limit)
    {
        string value = string.Join(';', items.Take(limit));
        int omitted = Math.Max(0, totalCount - limit);
        return omitted == 0 ? value : value + $";...(+{omitted})";
    }

    private SearchNode NativeMctsNode(SimulationSnapshot snapshot, int actionCount = 0) => new(
        null,
        actionCount,
        snapshot.PotionUseCount,
        snapshot.PotionStrategicCost,
        snapshot.Turn,
        SearchRouteTraits.None,
        0,
        snapshot.Score,
        snapshot.StateKey,
        snapshot.HasRisk,
        snapshot.BoundaryReason,
        snapshot.PlayerDead || snapshot.AllEnemiesDead || snapshot.BoundaryReason != SearchBoundaryReason.None,
        null,
        snapshot,
        CombatProgressState.Capture(snapshot));

    private IReadOnlyList<PlanAction> NativeMctsPreparedActions(SimulationSnapshot snapshot, int actionCount)
    {
        SearchNode node = NativeMctsNode(snapshot, actionCount);
        var actions = PrepareCardActions(node).Select(prepared => prepared.Action).ToList();
        actions.Add(new PlanAction(PlanActionKind.EndTurn, snapshot.Turn));
        return actions;
    }

    private NativeMctsAction[] NativeMctsPreparedPublicActions(
        SimulationSnapshot snapshot, int actionCount, out int incomingDamage)
    {
        SimulationSnapshot query = Replay([], snapshot, snapshot.Turn, actionCount, countTransition: false);
        try
        {
            SearchNode node = NativeMctsNode(query, actionCount);
            CombatPredictionSimulator simulator = (CombatPredictionSimulator)query.Simulator;
            SimPlayerCombatState playerState = simulator.State.GetPlayerCombatState(_player);
            var result = new List<NativeMctsAction>();
            foreach (PreparedCardAction prepared in PrepareCardActions(node))
            {
                PredictedCard card = FindCardForReplay(playerState.Hand.Cards, prepared.Action)
                    ?? throw new InvalidOperationException($"Could not resolve predicted card {prepared.Action.CardId}.");
                Creature? target = ((SimulatedCombatState)simulator.State.CombatState)
                    .GetCreature(prepared.Action.TargetCombatId);
                decimal damage = card.Preview.DynamicVars.TryGetValue("Damage", out DynamicVar? damageVar)
                    ? damageVar.InvokeCalculate(simulator, card, target)
                    : 0;
                result.Add(NativeMctsSimulation.ToPublicAction(
                    prepared.Action,
                    cardType: prepared.CardType.ToString(),
                    gainsBlock: card.Preview.GainsBlock,
                    damage: damage,
                    targetHp: target == null ? null : simulator.State.GetCreature(target).CurrentHp));
            }
            SimCreatureState player = simulator.State.GetCreature(_player.Creature);
            incomingDamage = Math.Max(0, player.CurrentHp - ProjectHpAfterThreat(simulator, player).Hp);
            PlanAction endTurn = new(PlanActionKind.EndTurn, snapshot.Turn);
            result.Add(NativeMctsSimulation.ToPublicAction(endTurn));
            return result.ToArray();
        }
        finally { query.ReleaseSimulator(); }
    }
}

internal sealed record NativeMctsExpansion(
    PlanAction BaseAction,
    IReadOnlyList<(PlanAction Action, SimulationSnapshot Snapshot)> Resolved,
    IReadOnlyList<string> ChoiceDiagnostics);

internal static class NativeMctsSimulation
{
    internal static CombatBeamSolver CreateDriver(CombatRootSnapshot root)
    {
        var profile = SolverSearchProfile.Default with
        {
            BeamWidth = 1,
            MaxExpandedNodes = 1,
            MaxCardBranchesPerNode = 4096,
            MaxPileChoiceBranchesPerAction = 4096,
            MaxHandChoiceBranchesPerAction = 4096,
            SoftTimeBudgetMilliseconds = int.MaxValue,
        };
        var policy = new SearchPolicySnapshot(
            profile, SolverPotionPolicy.Disabled,
            new PotionStrategySnapshot(SolverPotionPolicy.Disabled, []),
            false, false, true, false, 1, null, false, null,
            BossHpStrategy.ProgressionFirst, BossHpStrategy.ProgressionFirst, 0,
            new SearchDiagnosticsSink(static _ => { }, static _ => { }),
            new SearchFramePressureSignal(), new SearchMemoryPressureSignal());
        return new CombatBeamSolver(root, SolverDisplayNames.EmptyForHeadlessHost(),
            new BattleDamageSnapshot(0, 0, 0, []), policy);
    }

    internal static NativeMctsAction ToPublicAction(PlanAction action, string? key = null,
        string cardType = "", bool gainsBlock = false, decimal damage = 0,
        int? targetHp = null, string? choiceKey = null, int choiceIndex = 0) => new(
        key ?? ActionKey(action), action.Kind.ToString(), action.CardId, action.CardOccurrence,
        action.CardStateKey, action.CardStateOccurrence, action.CardUpgradeLevel,
        action.CardEnchantmentId, action.TargetCombatId, cardType, gainsBlock, damage, targetHp, choiceKey,
        action.GetActionChoicesInExecutionOrder().ElementAtOrDefault(choiceIndex)?.Cards.Select(card => new NativeMctsSelectedCard(
            card.CardId, card.UpgradeLevel, card.StateKey, card.OptionOccurrence)).ToArray());

    internal static string ActionKey(PlanAction action) => string.Join(':',
        action.Kind, action.CardId, action.CardOccurrence, action.CardStateKey,
        action.CardStateOccurrence, action.CardUpgradeLevel, action.CardEnchantmentId,
        action.TargetCombatId?.ToString() ?? "-");

    internal static string ChoiceKey(PlanAction baseAction, PlanAction resolved, int choiceIndex = -1)
    {
        var choices = resolved.GetActionChoicesInExecutionOrder();
        if (choiceIndex >= 0 && choiceIndex < choices.Count)
        {
            string step = System.Text.Json.JsonSerializer.Serialize(choices[choiceIndex]);
            return $"choice:{ActionKey(baseAction)}:{choiceIndex}:"
                + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(step)));
        }
        string payload = System.Text.Json.JsonSerializer.Serialize(new
        {
            resolved.Choice,
            resolved.NestedChoices,
            resolved.TurnStartChoices,
        });
        string digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload)));
        return $"choice:{ActionKey(baseAction)}:{digest}";
    }

    internal static string StateKey(StateFingerprint key) => $"{key.First:X16}{key.Second:X16}";

    internal static string DecisionStateKey(StateFingerprint state, IReadOnlyList<NativeMctsAction> actions)
    {
        string payload = StateKey(state) + "\n" + string.Join('\n', actions.Select(action => action.Key));
        return StateKey(state) + ":" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload)));
    }

    internal static string PendingStateKey(StateFingerprint parent, IReadOnlyList<NativeMctsAction> actions)
    {
        string payload = StateKey(parent) + "\n" + string.Join('\n', actions.Select(action => action.Key));
        return "pending:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload)));
    }
}
