using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Potions;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed record ManualCombatInputEvidence(
    DateTimeOffset InputAtUtc,
    CapturedCombatDecision? PreSubmissionDecision,
    CombatObservation? ClickObservation,
    string? CaptureFailure,
    bool QueuedAtClick = false)
{
    internal OutsideCombatDecisionPoint? OutsideDecision { get; init; }
    internal OutsidePotionCaptureAudit? OutsideCaptureAudit { get; init; }
}

internal sealed record OutsidePotionCaptureAudit(
    int PendingOutsideOperationCount,
    int AcceptedParentCount,
    int PendingSelectorCount,
    int PendingOutsidePotionCount,
    int OtherPendingOperationCount,
    int PendingDecisionCount,
    bool ActionExecutorRunning,
    bool ActionQueueEmpty,
    string TopSurface);

/// <summary>
/// Tracks the exact GameAction created by a native manual combat entry point.
/// RequestEnqueue itself is also used by automatic effects, so patching that
/// method as a source of human labels would be unsound. Each transpiler marks
/// only the action passed to RequestEnqueue by its specific manual caller.
/// </summary>
internal static class CollectorManualCombatInput
{
    private static readonly Harmony Patcher =
        new("SlayTheModel.DataCollector.manual-combat.v1");
    private static readonly object Gate = new();
    private static readonly Dictionary<GameAction, ManualCombatInputEvidence> Submitted =
        new(ReferenceEqualityComparer.Instance);
    [ThreadStatic] private static Stack<ManualCombatInputEvidence>? _inputScopes;
    private static bool _installed;
    private static bool _active;
    private static long _generation;
    private static int _mainThreadId;

    internal static void Install()
    {
        if (_installed)
        {
            return;
        }

        var card = RequiredMethod(
            typeof(CardModel), "EnqueueManualPlay", typeof(Creature));
        var potion = RequiredMethod(
            typeof(PotionModel), "EnqueueManualUse", typeof(Creature));
        var endTurn = RequiredMethod(
            typeof(NEndTurnButton), "CallReleaseLogic");
        // This UI entry constructs one DiscardPotionGameAction. Mark that exact
        // request so a manual discard cannot be mistaken for a reward change.
        var discardPotion = RequiredMethod(
            typeof(NPotionPopup), "OnDiscardButtonPressed",
            typeof(MegaCrit.Sts2.Core.Nodes.GodotExtensions.NButton));
        _ = RequiredMethod(
            typeof(ActionQueueSynchronizer),
            nameof(ActionQueueSynchronizer.RequestEnqueue),
            typeof(GameAction));

        PatchManualMethod(card);
        PatchManualMethod(potion);
        PatchManualMethod(endTurn);
        PatchManualMethod(discardPotion);
        _installed = true;
    }

    private static void PatchManualMethod(
        MethodInfo method,
        string prefixName = nameof(ManualInputPrefix)) => Patcher.Patch(
        method,
        prefix: new HarmonyMethod(typeof(CollectorManualCombatInput), prefixName),
        postfix: new HarmonyMethod(typeof(CollectorManualCombatInput), nameof(ManualInputPostfix)),
        transpiler: new HarmonyMethod(typeof(CollectorManualCombatInput), nameof(MarkManualRequest)),
        finalizer: new HarmonyMethod(typeof(CollectorManualCombatInput), nameof(ManualInputFinalizer)));

    /// <summary>Begin tracking one run; stale action identities are discarded.</summary>
    internal static void StartGeneration(long generation)
    {
        lock (Gate)
        {
            Submitted.Clear();
            _inputScopes?.Clear();
            _generation = generation;
            _mainThreadId = Environment.CurrentManagedThreadId;
            _active = true;
        }
    }

    /// <summary>Discard unconsumed requests from a run that has ended.</summary>
    internal static void EndGeneration(long generation)
    {
        lock (Gate)
        {
            if (!_active || _generation != generation)
            {
                return;
            }

            Submitted.Clear();
            _inputScopes?.Clear();
            _active = false;
            _mainThreadId = 0;
        }
    }

    /// <summary>
    /// Return pre-submission evidence once for the same GameAction object
    /// submitted by a manual native entry point. The action is not inferred from card IDs,
    /// UI timing, or RequestEnqueue calls made by automatic game effects.
    /// </summary>
    internal static ManualCombatInputEvidence? Consume(GameAction action)
    {
        lock (Gate)
        {
            if (!_active
                || Environment.CurrentManagedThreadId != _mainThreadId
                || !Submitted.Remove(action, out var evidence))
            {
                return null;
            }

            return evidence;
        }
    }

    private static void Mark(GameAction action)
    {
        lock (Gate)
        {
            if (!_active || Environment.CurrentManagedThreadId != _mainThreadId)
            {
                return;
            }
        }

        // PotionModel sets IsQueued before RequestEnqueue. The enclosing
        // manual method's prefix froze the observation before that change.
        var evidence = _inputScopes is { Count: > 0 }
            ? _inputScopes.Peek()
            : new ManualCombatInputEvidence(
                DateTimeOffset.UtcNow,
                null,
                null,
                "Manual input prefix was not observed.");
        lock (Gate)
        {
            if (_active && Environment.CurrentManagedThreadId == _mainThreadId)
            {
                Submitted[action] = evidence;
            }
        }
    }

    private static void ManualInputPrefix(out ManualCombatInputEvidence? __state) =>
        BeginManualInputScope(out __state);

    private static void BeginManualInputScope(out ManualCombatInputEvidence? __state)
    {
        lock (Gate)
        {
            if (!_active || Environment.CurrentManagedThreadId != _mainThreadId)
            {
                __state = null;
                return;
            }
        }

        // The decision's hand and legal actions come from the internal
        // click-time combat state, independent of hand animation. The exact
        // submitted GameAction is bound by the transpiler below.
        __state = CollectorRuntime.CaptureManualCombatPreState();
        (_inputScopes ??= new Stack<ManualCombatInputEvidence>()).Push(__state);
    }

    private static void ManualInputPostfix(ManualCombatInputEvidence? __state) =>
        EndManualInputScope(__state);

    private static Exception? ManualInputFinalizer(
        Exception? __exception,
        ManualCombatInputEvidence? __state)
    {
        EndManualInputScope(__state);
        return __exception;
    }

    private static void EndManualInputScope(ManualCombatInputEvidence? evidence)
    {
        if (evidence is not null
            && _inputScopes is { Count: > 0 } scopes
            && ReferenceEquals(scopes.Peek(), evidence))
        {
            scopes.Pop();
        }
    }

    private static IEnumerable<CodeInstruction> MarkManualRequest(
        IEnumerable<CodeInstruction> instructions,
        MethodBase __originalMethod)
    {
        var request = RequiredMethod(
            typeof(ActionQueueSynchronizer),
            nameof(ActionQueueSynchronizer.RequestEnqueue),
            typeof(GameAction));
        var marker = RequiredMethod(typeof(CollectorManualCombatInput), nameof(Mark),
            typeof(GameAction));
        var source = instructions.ToList();
        var requestCount = source.Count(instruction => Calls(instruction, request));
        var expectedCount = __originalMethod.DeclaringType == typeof(NEndTurnButton)
            ? 2
            : 1;
        if (requestCount != expectedCount)
        {
            throw new InvalidProgramException(
                $"Manual combat input ABI changed: {__originalMethod} has "
                + $"{requestCount} RequestEnqueue calls; expected {expectedCount}.");
        }

        foreach (var instruction in source)
        {
            if (Calls(instruction, request))
            {
                // Native stack: [synchronizer, action]. Mark the duplicate,
                // preserving the original reference for RequestEnqueue.
                var duplicate = new CodeInstruction(OpCodes.Dup);
                // A branch into the original call must also pass the marker.
                duplicate.labels.AddRange(instruction.labels);
                instruction.labels.Clear();
                yield return duplicate;
                yield return new CodeInstruction(OpCodes.Call, marker);
            }

            yield return instruction;
        }
    }

    private static bool Calls(CodeInstruction instruction, MethodInfo method) =>
        (instruction.opcode == OpCodes.Call
         || instruction.opcode == OpCodes.Callvirt)
        && instruction.operand is MethodInfo called
        && called.Equals(method);

    private static MethodInfo RequiredMethod(
        Type type,
        string name,
        params Type[] parameters) =>
        AccessTools.Method(type, name, parameters)
        ?? throw new MissingMethodException(type.FullName, name);
}
