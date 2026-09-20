using MegaCrit.Sts2.Core.Combat;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Opt-in live integration smoke test. This is deliberately a tiny deterministic
/// policy, not the MCTS player: its purpose is to prove that observation, decision,
/// stale-state validation, and native action execution form a working loop.
/// </summary>
internal static class LiveCombatController
{
    private const string PolicyVariable = "SLAY_THE_MODEL_LIVE_POLICY";
    private const string FirstLegalPolicy = "first-legal";
    private static readonly object Gate = new();
    private static bool _enabled;
    private static bool _executing;
    private static long _decisionIndex;
    private static long _combatGeneration;

    public static void Initialize()
    {
        var configuredPolicy = Environment.GetEnvironmentVariable(PolicyVariable);
        if (string.IsNullOrWhiteSpace(configuredPolicy))
        {
            Console.WriteLine(
                $"[SlayTheModel] live policy disabled; set {PolicyVariable}={FirstLegalPolicy} to enable it");
            return;
        }

        if (!string.Equals(configuredPolicy, FirstLegalPolicy, StringComparison.OrdinalIgnoreCase))
        {
            Console.Error.WriteLine(
                $"[SlayTheModel] unknown live policy '{configuredPolicy}'; expected '{FirstLegalPolicy}'");
            return;
        }

        _enabled = true;
        Console.WriteLine(
            "[SlayTheModel] LIVE CONTROL ENABLED policy=first-legal; "
            + "the adapter will play cards and end turns automatically");
    }

    public static void Reset()
    {
        lock (Gate)
        {
            _decisionIndex = 0;
            _combatGeneration++;
        }
    }

    public static void TrySchedule(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        if (!_enabled || !IsStablePlayerDecision(state))
        {
            return;
        }

        CombatSearchPoint searchPoint;
        long generation;
        lock (Gate)
        {
            if (_executing)
            {
                return;
            }

            _executing = true;
            generation = _combatGeneration;
            searchPoint = CombatCaptureService.BuildSearchPoint(state, _decisionIndex++);
        }

        var action = SelectAction(searchPoint.Decision);
        _ = ExecuteAsync(state, searchPoint, action, generation);
    }

    internal static CombatActionDescriptor SelectAction(CombatDecisionPoint decision)
    {
        ArgumentNullException.ThrowIfNull(decision);
        decision.Validate();

        // GetLegalActions is stably ordered. Prefer making progress with any playable
        // card, then a potion once potion enumeration is added, and end the turn last.
        return decision.LegalActions
            .OrderBy(action => action.Kind == CombatActionKind.EndTurn ? 1 : 0)
            .ThenBy(action => action.ActorPlayerId)
            .ThenBy(action => action.Kind)
            .ThenBy(action => action.CombatCardIndex)
            .ThenBy(action => action.PotionIndex)
            .ThenBy(action => action.TargetCreatureId)
            .First();
    }

    private static async Task ExecuteAsync(
        CombatState state,
        CombatSearchPoint searchPoint,
        CombatActionDescriptor action,
        long generation)
    {
        try
        {
            var request = new CombatStepRequest(
                Guid.NewGuid(),
                searchPoint.Decision.StateFingerprint,
                action);
            CombatStepGuard.RequireExpectedState(request, searchPoint.SimulatorState);

            Console.WriteLine(
                $"[SlayTheModel] live decision={searchPoint.Decision.DecisionIndex} "
                + $"action={Describe(action)} fingerprint={request.ExpectedStateFingerprint[..12]}");
            await CombatActionExecutor.ExecuteAsync(state, action);
        }
        catch (StaleCombatStateException exception)
        {
            Console.WriteLine($"[SlayTheModel] skipped stale live decision: {exception.Message}");
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[SlayTheModel] live decision failed: {exception}");
        }
        finally
        {
            var shouldContinue = false;
            lock (Gate)
            {
                _executing = false;
                shouldContinue = generation == _combatGeneration;
            }

            if (shouldContinue)
            {
                TrySchedule(state);
            }
        }
    }

    private static bool IsStablePlayerDecision(CombatState state)
    {
        var manager = CombatManager.Instance;
        return manager.IsInProgress
            && !manager.IsOverOrEnding
            && !manager.PlayerActionsDisabled
            && state.CurrentSide == MegaCrit.Sts2.Core.Combat.CombatSide.Player
            && CombatCaptureService.GetLegalActions(state).Count > 0;
    }

    private static string Describe(CombatActionDescriptor action) => action.Kind switch
    {
        CombatActionKind.PlayCard =>
            $"play_card:{action.CombatCardIndex}:target:{action.TargetCreatureId?.ToString() ?? "none"}",
        CombatActionKind.UsePotion =>
            $"use_potion:{action.PotionIndex}:target:{action.TargetCreatureId?.ToString() ?? "none"}",
        CombatActionKind.EndTurn => $"end_turn:player:{action.ActorPlayerId}",
        CombatActionKind.ResolveChoice => $"resolve_choice:{action.ChoiceId}",
        _ => action.Kind.ToString(),
    };
}
