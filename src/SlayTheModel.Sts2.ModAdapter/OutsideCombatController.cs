using Godot;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Relics;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Nodes.TreasureRooms;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Deterministic outside-combat integration policy. It acts through the game's
/// native controls rather than screen coordinates, and only on known run screens.
/// Main-menu and character-selection controls are deliberately outside its scope.
/// </summary>
internal static class OutsideCombatController
{
    private static readonly HashSet<ulong> AttemptedOnSurface = [];
    private static readonly object MerchantGate = new();
    private static readonly object PendingActionGate = new();
    private static readonly FieldInfo? DeckSelectorPrefsField =
        typeof(NDeckCardSelectScreen).GetField(
            "_prefs",
            BindingFlags.Instance | BindingFlags.NonPublic);
    private static readonly FieldInfo? DeckSelectedCardsField =
        typeof(NDeckCardSelectScreen).GetField(
            "_selectedCards",
            BindingFlags.Instance | BindingFlags.NonPublic);
    private static readonly FieldInfo? CrystalSphereEntityField =
        typeof(NCrystalSphereScreen).GetField(
            "_entity",
            BindingFlags.Instance | BindingFlags.NonPublic);
    private static bool _enabled;
    private static ulong _surfaceId;
    private static ulong _completedSingleChoiceSurfaceId;
    private static ulong _merchantOpenedInRoom;
    private static ulong _merchantCardRemovalAttemptedInRoom;
    private static bool _awaitingMerchantCardRemoval;
    private static long _merchantCardRemovalStartedAt;
    private static long _merchantCardRemovalGeneration;
    private static long _nextActionAt;
    private static long _surfaceReadyAt;
    private static long _mapReadyAt;
    private static long _nextMapWaitLogAt;
    private static bool _faulted;
    private static bool _clicking;
    private static IOutsideCombatPolicy? _policy;
    private static Task<bool>? _merchantCardRemovalTask;
    private static OutsideCombatDecisionSample? _merchantCardRemovalSample;
    private static RunState? _merchantCardRemovalRun;
    private static PendingOutsideAction? _pendingOutsideAction;

    private const int ActionCooldownMilliseconds = 350;
    private const int SurfaceSettleMilliseconds = 450;
    private const int MapSettleMilliseconds = 1000;
    private const int OutsideTransitionTimeoutMilliseconds = 15_000;
    private const int MerchantCardRemovalTimeoutMilliseconds = 30_000;

    internal static void Initialize(AdapterConfiguration configuration)
    {
        if (configuration.RunMode == AdapterRunMode.Train)
        {
            Console.WriteLine("[SlayTheModel] train mode is declared but no trainer is connected yet; live policies are disabled");
            return;
        }

        if (configuration.OutsideCombatPolicy != OutsideCombatPolicyKind.FirstLegal)
        {
            return;
        }

        _policy = new FirstLegalOutsideCombatPolicy();
        _enabled = true;
        Callable.From(() =>
        {
            var tree = (SceneTree)Engine.GetMainLoop();
            tree.ProcessFrame += Tick;
            tree.Root.TreeExiting += Stop;
        }).CallDeferred();
        Console.WriteLine(
            "[SlayTheModel] OUTSIDE CONTROL ENABLED policy=first-legal; "
            + "the adapter will choose the first enabled option on supported run screens");
    }

    private static void Stop()
    {
        _enabled = false;
        AttemptedOnSurface.Clear();
        _surfaceId = 0;
        _completedSingleChoiceSurfaceId = 0;
        _merchantOpenedInRoom = 0;
        _merchantCardRemovalAttemptedInRoom = 0;
        lock (MerchantGate)
        {
            _awaitingMerchantCardRemoval = false;
            _merchantCardRemovalStartedAt = 0;
            _merchantCardRemovalGeneration++;
            _merchantCardRemovalTask = null;
            _merchantCardRemovalSample = null;
            _merchantCardRemovalRun = null;
        }
        lock (PendingActionGate)
        {
            _pendingOutsideAction = null;
        }
        _policy = null;
        OutsideCombatCaptureService.Reset();
    }

    private static void Tick()
    {
        var runManager = RunManager.Instance;
        var state = runManager.IsInProgress
            ? runManager.DebugOnlyGetState()
            : null;
        if (_enabled
            && !_faulted
            && _awaitingMerchantCardRemoval
            && _merchantCardRemovalRun is { } transactionRun)
        {
            if (!ReferenceEquals(transactionRun, state))
            {
                var generation = _merchantCardRemovalGeneration;
                if (TryCompleteMerchantCardRemoval(
                        generation,
                        expectedOperation: null,
                        out var abandonedSample))
                {
                    if (abandonedSample is not null)
                    {
                        OutsideCombatCaptureService.RecordExecution(
                            abandonedSample,
                            OutsideCombatExecutionStatus.Cancelled,
                            "run state changed while the native transaction was pending");
                    }

                    _merchantCardRemovalAttemptedInRoom = 0;
                }
            }
        }

        if (_enabled
            && !_faulted
            && _awaitingMerchantCardRemoval
            && _merchantCardRemovalStartedAt > 0
            && System.Environment.TickCount64 - _merchantCardRemovalStartedAt
                >= MerchantCardRemovalTimeoutMilliseconds)
        {
            // Do not click through a lost selector. Disable automation so the
            // player can recover manually, and invalidate the old observer so
            // a very late completion cannot mutate a later transaction.
            var generation = _merchantCardRemovalGeneration;
            if (TryCompleteMerchantCardRemoval(
                    generation,
                    expectedOperation: null,
                    out var timedOutSample))
            {
                if (timedOutSample is not null)
                {
                    OutsideCombatCaptureService.RecordExecution(
                        timedOutSample,
                        OutsideCombatExecutionStatus.TimedOut,
                        "native merchant card-removal task exceeded 30 seconds");
                }

                _faulted = true;
                GD.PushError(
                    "[SlayTheModel] merchant card removal timed out after 30 seconds; "
                    + "outside policy disabled so the screen can be handled manually");
                return;
            }
        }

        if (ResolvePendingOutsideAction(state is not null))
        {
            return;
        }

        if (!_enabled || _faulted || _clicking || CombatManager.Instance.IsInProgress
            || System.Environment.TickCount64 < _nextActionAt)
        {
            return;
        }

        // The state itself is the readiness signal. Never scan residual room or
        // map nodes after a run ended, and keep one snapshot throughout this
        // frame so capture and native bindings refer to the same run.
        if (state is null || state.Players.Count != 1)
        {
            return;
        }

        try
        {
            var candidates = FindDecisions();
            if (candidates.Count == 0)
            {
                return;
            }

            var surface = candidates[0].Surface;

            // The map can open underneath a rewards overlay that remains mounted
            // during its outro. Alternating discovery between those two nodes
            // must not restart the generic surface timer forever; map travel has
            // its own one-second quiet-window readiness check.
            var isMapDecision = surface is NMapScreen;
            if (!isMapDecision)
            {
                SetSurface(surface);
            }

            if (!isMapDecision && System.Environment.TickCount64 < _surfaceReadyAt)
            {
                return;
            }

            if (_policy is null)
            {
                return;
            }

            // Assign semantic IDs only after native discovery is complete. The
            // resulting decision can be serialized, sent to a learned policy,
            // or replayed without exposing Godot object identities.
            var actions = candidates
                .Select((candidate, ordinal) => candidate.ToDescriptor(ordinal, state))
                .ToArray();
            var choiceContext = BuildChoiceContext(
                surface,
                candidates[0].SurfaceKind,
                actions);
            var decisionPoint = OutsideCombatCaptureService.BuildDecisionPoint(
                state,
                candidates[0].SurfaceKind,
                choiceContext,
                actions);
            if (WaitForPendingOutsideAction(decisionPoint.StateFingerprint))
            {
                return;
            }

            var selectedAction = _policy.SelectAction(decisionPoint);
            if (selectedAction.Ordinal < 0
                || selectedAction.Ordinal >= candidates.Count
                || !string.Equals(
                    actions[selectedAction.Ordinal].ActionId,
                    selectedAction.ActionId,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"Policy selected an action outside the current native binding: "
                    + selectedAction.ActionId);
            }

            var decision = candidates[selectedAction.Ordinal];

            var targetId = decision.Target.GetInstanceId();
            var submissionSurfaceId = decision.Surface.GetInstanceId();
            var step = new OutsideCombatStepRequest(
                Guid.NewGuid(),
                decisionPoint.StateFingerprint,
                selectedAction.ActionId);
            _ = OutsideCombatStepGuard.RequireCurrentAction(step, decisionPoint);
            var sample = OutsideCombatCaptureService.RecordSelection(
                _policy,
                decisionPoint,
                step);

            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            if (decision.StartsMerchantCardRemoval)
            {
                // Keep this room-scoped marker separate from the generic
                // surface attempt set. Opening the deck overlay changes the
                // active surface and clears that generic set; a cancelled or
                // failed purchase must still leave the shop instead of looping.
                _merchantCardRemovalAttemptedInRoom = _surfaceId;
                lock (MerchantGate)
                {
                    _awaitingMerchantCardRemoval = true;
                    _merchantCardRemovalStartedAt = System.Environment.TickCount64;
                    _merchantCardRemovalGeneration++;
                    _merchantCardRemovalSample = sample;
                    _merchantCardRemovalRun = state;
                }
            }

            _clicking = true;
            _ = ClickAsync(
                decision,
                sample,
                _merchantCardRemovalGeneration,
                submissionSurfaceId,
                targetId);
        }
        catch (Exception exception)
        {
            _faulted = true;
            Console.Error.WriteLine($"[SlayTheModel] outside first-legal failed: {exception}");
            Console.Error.WriteLine("[SlayTheModel] outside policy disabled after failure; restart to retry.");
        }
    }

    private static async Task ClickAsync(
        OutsideDecision decision,
        OutsideCombatDecisionSample sample,
        long merchantGeneration,
        ulong submissionSurfaceId,
        ulong targetId)
    {
        try
        {
            GD.Print(
                $"[SlayTheModel] outside first-legal: {decision.Description} "
                + $"node={decision.Target.GetPath()}");
            if (decision.MerchantCardRemoval is not null
                && decision.MerchantInventory is not null)
            {
                // Merchant slots do not handle NClickableControl.Released, so
                // UiHelper.ForceClick never starts this transaction. Invoke the
                // same purchase method as the native slot and observe it without
                // awaiting: the task remains pending while its deck-selection
                // overlay is waiting for our next outside-combat decision.
                var entry = (MerchantCardRemovalEntry)decision.MerchantCardRemoval.Entry;
                Task<bool> operation;
                try
                {
                    operation = entry.OnTryPurchaseWrapper(
                        decision.MerchantInventory.Inventory,
                        ignoreCost: false,
                        cancelable: true);
                }
                catch (Exception exception)
                {
                    // The native call can reject synchronously before there is
                    // a task for the observer to clean up. Keep the room marker
                    // so the next decision leaves the shop instead of retrying.
                    if (TryCompleteMerchantCardRemoval(
                            merchantGeneration,
                            expectedOperation: null,
                            out var failedSample))
                    {
                        OutsideCombatCaptureService.RecordExecution(
                            failedSample ?? sample,
                            OutsideCombatExecutionStatus.Failed,
                            $"native purchase start failed: {exception.GetType().Name}: "
                            + exception.Message);
                    }
                    GD.PushError(
                        $"[SlayTheModel] merchant card removal could not start: {exception}");
                    return;
                }

                lock (MerchantGate)
                {
                    if (merchantGeneration != _merchantCardRemovalGeneration
                        || !_awaitingMerchantCardRemoval)
                    {
                        return;
                    }

                    _merchantCardRemovalTask = operation;
                }
                _ = ObserveMerchantCardRemovalAsync(
                    operation,
                    sample,
                    merchantGeneration);
                await Task.Delay(100);
            }
            else if (decision.CardHolder is not null)
            {
                // NCardHolder listens for its own Pressed signal. ForceClick on
                // its child hitbox only emits NClickableControl.Released, which
                // does not select the card. Match the game's AutoSlay handlers by
                // emitting the holder signal directly.
                decision.CardHolder.EmitSignal(
                    NCardHolder.SignalName.Pressed,
                    decision.CardHolder);
                await Task.Delay(100);
            }
            else
            {
                // Use the same input helper as the game's built-in AutoSlay. Its
                // delay lets signal handlers push the next choice screen before
                // we enumerate again.
                await UiHelper.Click(decision.Control!, 100);
            }

            if (decision.MerchantCardRemoval is null)
            {
                // Most Godot controls have no success result. Delay the one
                // terminal result until a different observed state proves that
                // the signal transitioned, or the watchdog reports failure.
                RegisterPendingOutsideAction(
                    sample,
                    decision.Target,
                    submissionSurfaceId,
                    targetId,
                    decision.ResetsSelectionAttempts,
                    decision.CompletesSingleChoice,
                    decision.MarksMerchantOpened);
            }
        }
        catch (Exception exception)
        {
            OutsideCombatCaptureService.RecordExecution(
                sample,
                OutsideCombatExecutionStatus.Failed,
                $"native input failed: {exception.GetType().Name}: {exception.Message}");
            _faulted = true;
            GD.PushError($"[SlayTheModel] outside first-legal click failed: {exception}");
        }
        finally
        {
            _clicking = false;
            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            // Reward collection may open another choice screen asynchronously,
            // while the map can already be visible underneath it. Require one
            // quiet second after every outside action before selecting a route.
            _mapReadyAt = System.Environment.TickCount64 + MapSettleMilliseconds;
        }
    }

    private static async Task ObserveMerchantCardRemovalAsync(
        Task<bool> operation,
        OutsideCombatDecisionSample sample,
        long merchantGeneration)
    {
        try
        {
            var applied = await operation;
            if (!TryCompleteMerchantCardRemoval(
                    merchantGeneration,
                    operation,
                    out var completedSample))
            {
                return;
            }

            OutsideCombatCaptureService.RecordExecution(
                completedSample ?? sample,
                applied
                    ? OutsideCombatExecutionStatus.Applied
                    : OutsideCombatExecutionStatus.Cancelled,
                applied ? null : "native transaction closed without applying a card");
            GD.Print(
                applied
                    ? "[SlayTheModel] merchant card removal completed"
                    : "[SlayTheModel] merchant card removal closed without a card");
        }
        catch (OperationCanceledException)
        {
            if (TryCompleteMerchantCardRemoval(
                    merchantGeneration,
                    operation,
                    out var cancelledSample))
            {
                OutsideCombatCaptureService.RecordExecution(
                    cancelledSample ?? sample,
                    OutsideCombatExecutionStatus.Cancelled,
                    "native merchant card-removal task was cancelled");
            }
            GD.Print("[SlayTheModel] merchant card removal was cancelled");
        }
        catch (Exception exception)
        {
            // A failed purchase should not disable every outside-combat screen.
            // Mark this slot attempted and let the policy leave the shop.
            if (TryCompleteMerchantCardRemoval(
                    merchantGeneration,
                    operation,
                    out var failedSample))
            {
                OutsideCombatCaptureService.RecordExecution(
                    failedSample ?? sample,
                    OutsideCombatExecutionStatus.Failed,
                    $"native transaction failed: {exception.GetType().Name}: "
                    + exception.Message);
            }
            GD.PushError($"[SlayTheModel] merchant card removal failed: {exception}");
        }
    }

    private static bool TryCompleteMerchantCardRemoval(
        long merchantGeneration,
        Task<bool>? expectedOperation,
        out OutsideCombatDecisionSample? sample)
    {
        lock (MerchantGate)
        {
            if (merchantGeneration != _merchantCardRemovalGeneration
                || !_awaitingMerchantCardRemoval
                || (expectedOperation is not null
                    && !ReferenceEquals(_merchantCardRemovalTask, expectedOperation)))
            {
                sample = null;
                return false;
            }

            sample = _merchantCardRemovalSample;
            _merchantCardRemovalTask = null;
            _merchantCardRemovalSample = null;
            _merchantCardRemovalRun = null;
            _awaitingMerchantCardRemoval = false;
            _merchantCardRemovalStartedAt = 0;
            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            _merchantCardRemovalGeneration++;
            return true;
        }
    }

    private static void RegisterPendingOutsideAction(
        OutsideCombatDecisionSample sample,
        Node target,
        ulong surfaceId,
        ulong targetId,
        bool resetsSelectionAttempts,
        bool completesSingleChoice,
        bool marksMerchantOpened)
    {
        lock (PendingActionGate)
        {
            if (_pendingOutsideAction is not null)
            {
                throw new InvalidOperationException(
                    "Cannot submit a new outside action while the previous state transition "
                    + "is still pending.");
            }

            _pendingOutsideAction = new PendingOutsideAction(
                sample,
                target,
                surfaceId,
                targetId,
                resetsSelectionAttempts,
                completesSingleChoice,
                marksMerchantOpened,
                System.Environment.TickCount64);
        }
    }

    /// <summary>
    /// Resolves transitions that no longer have a decision surface to compare.
    /// Returns true only when automation was faulted and this Tick must stop.
    /// </summary>
    private static bool ResolvePendingOutsideAction(bool runIsActive)
    {
        PendingOutsideAction? pending;
        lock (PendingActionGate)
        {
            pending = _pendingOutsideAction;
        }

        if (pending is null)
        {
            return false;
        }

        if (!runIsActive)
        {
            if (TryClaimPendingOutsideAction(pending))
            {
                OutsideCombatCaptureService.RecordExecution(
                    pending.Sample,
                    OutsideCombatExecutionStatus.Cancelled,
                    "run ended before the adapter could attribute a native transition");
            }
            return false;
        }

        if (CombatManager.Instance.IsInProgress
            || !IsActive(pending.Target)
            || (pending.Target is NClickableControl clickable && !clickable.IsEnabled))
        {
            if (TryClaimPendingOutsideAction(pending))
            {
                CommitPendingOutsideAction(pending);
                OutsideCombatCaptureService.RecordExecution(
                    pending.Sample,
                    OutsideCombatExecutionStatus.ObservedTransition,
                    "native target left the active surface or became disabled");
            }
            return false;
        }

        if (System.Environment.TickCount64 - pending.StartedAt
            < OutsideTransitionTimeoutMilliseconds)
        {
            return false;
        }

        if (!TryClaimPendingOutsideAction(pending))
        {
            return false;
        }

        OutsideCombatCaptureService.RecordExecution(
            pending.Sample,
            OutsideCombatExecutionStatus.Failed,
            "no native state transition was observed within 15 seconds");

        // If the failed action belonged to the merchant selector, invalidate
        // that enclosing task too. Its eventual completion is now stale.
        var merchantGeneration = _merchantCardRemovalGeneration;
        if (TryCompleteMerchantCardRemoval(
                merchantGeneration,
                expectedOperation: null,
                out var merchantSample)
            && merchantSample is not null)
        {
            OutsideCombatCaptureService.RecordExecution(
                merchantSample,
                OutsideCombatExecutionStatus.Failed,
                "a dependent card-selection action did not transition");
        }

        _faulted = true;
        GD.PushError(
            "[SlayTheModel] outside action produced no state transition for 15 seconds; "
            + "outside policy disabled so the screen can be handled manually");
        return true;
    }

    /// <summary>
    /// Blocks a duplicate submission while the fingerprint is unchanged. A new
    /// fingerprint proves the previous native input changed the observed state.
    /// This method also ends the current Tick after committing local bookkeeping,
    /// so the next action is rebuilt from that committed state on the next frame.
    /// </summary>
    private static bool WaitForPendingOutsideAction(string currentFingerprint)
    {
        PendingOutsideAction? pending;
        lock (PendingActionGate)
        {
            pending = _pendingOutsideAction;
            if (pending is null)
            {
                return false;
            }

            if (string.Equals(
                    pending.Sample.Decision.StateFingerprint,
                    currentFingerprint,
                    StringComparison.Ordinal))
            {
                return true;
            }

            _pendingOutsideAction = null;
        }

        OutsideCombatCaptureService.RecordExecution(
            pending.Sample,
            OutsideCombatExecutionStatus.ObservedTransition,
            $"next outside state observed: {currentFingerprint}");
        CommitPendingOutsideAction(pending);
        return true;
    }

    /// <summary>
    /// Applies controller-only progress markers only after a native transition
    /// has been observed. Keeping these markers out of the pending fingerprint
    /// prevents the adapter from mistaking its own bookkeeping for game output.
    /// </summary>
    private static void CommitPendingOutsideAction(PendingOutsideAction pending)
    {
        if (_surfaceId != pending.SurfaceId)
        {
            return;
        }

        if (pending.ResetsSelectionAttempts)
        {
            // PreviewCancel clears the native selected-card set without
            // replacing the screen node. Allow the same cards again.
            AttemptedOnSurface.Clear();
        }
        else
        {
            AttemptedOnSurface.Add(pending.TargetId);
        }

        if (pending.CompletesSingleChoice)
        {
            _completedSingleChoiceSurfaceId = pending.SurfaceId;
        }

        if (pending.MarksMerchantOpened)
        {
            _merchantOpenedInRoom = pending.SurfaceId;
        }
    }

    private static bool TryClaimPendingOutsideAction(PendingOutsideAction expected)
    {
        lock (PendingActionGate)
        {
            if (!ReferenceEquals(_pendingOutsideAction, expected))
            {
                return false;
            }

            _pendingOutsideAction = null;
            return true;
        }
    }

    private static OutsideCombatChoiceContext BuildChoiceContext(
        Node surface,
        OutsideCombatSurfaceKind surfaceKind,
        IReadOnlyList<OutsideCombatActionDescriptor> actions)
    {
        var contextId = $"{surfaceKind}:{surface.GetType().FullName ?? surface.GetType().Name}";
        var phase = OutsideCombatChoicePhase.Default;
        int? minSelections = null;
        int? maxSelections = null;
        var selectedCount = 0;
        var cancelable = actions.Any(action => action.Kind is
            OutsideCombatActionKind.CancelSelection
            or OutsideCombatActionKind.BackToSelection
            or OutsideCombatActionKind.Skip);
        var requiresConfirmation = actions.Any(action =>
            action.Kind == OutsideCombatActionKind.Confirm);
        var stateParts = new List<string> { contextId };

        if (surface is NDeckCardSelectScreen deckScreen
            && DeckSelectorPrefsField?.GetValue(deckScreen) is CardSelectorPrefs prefs)
        {
            var prompt = prefs.Prompt;
            if (prompt is not null
                && !string.IsNullOrWhiteSpace(prompt.LocTable)
                && !string.IsNullOrWhiteSpace(prompt.LocEntryKey))
            {
                // Localization keys distinguish remove/upgrade/transform/etc.
                // The rendered localized text never crosses the protocol.
                contextId = $"card_selection:{prompt.LocTable}:{prompt.LocEntryKey}";
            }

            var preview = deckScreen.GetNodeOrNull<Control>("%PreviewContainer");
            phase = preview is { Visible: true } && preview.IsVisibleInTree()
                ? OutsideCombatChoicePhase.Preview
                : OutsideCombatChoicePhase.Selection;
            minSelections = prefs.MinSelect;
            maxSelections = prefs.MaxSelect;
            selectedCount = DeckSelectedCardsField?.GetValue(deckScreen)
                is IReadOnlyCollection<CardModel> selectedCards
                    ? selectedCards.Count
                    : 0;
            cancelable = prefs.Cancelable;
            requiresConfirmation = prefs.RequireManualConfirmation || requiresConfirmation;
        }
        else if (surfaceKind is OutsideCombatSurfaceKind.CardReward
                 or OutsideCombatSurfaceKind.CardChoice
                 or OutsideCombatSurfaceKind.CardBundleChoice
                 or OutsideCombatSurfaceKind.RelicChoice
                 or OutsideCombatSurfaceKind.CardGridChoice
                 or OutsideCombatSurfaceKind.MerchantCardRemoval)
        {
            phase = OutsideCombatChoicePhase.Selection;
            selectedCount = AttemptedOnSurface.Count;
        }

        stateParts.Add(contextId);
        stateParts.Add(phase.ToString());
        stateParts.Add(minSelections?.ToString() ?? "-");
        stateParts.Add(maxSelections?.ToString() ?? "-");
        stateParts.Add(selectedCount.ToString());
        stateParts.Add(cancelable.ToString());
        stateParts.Add(requiresConfirmation.ToString());

        if (surface is NCrystalSphereScreen crystalScreen)
        {
            var entity = CrystalSphereEntityField?.GetValue(crystalScreen);
            stateParts.Add(ReadStableProperty(entity, "DivinationCount"));
            stateParts.Add(ReadStableProperty(entity, "CrystalSphereTool"));
            stateParts.Add(ReadStableProperty(entity, "PlacedAllItems"));
            stateParts.Add(ReadStableProperty(entity, "IsFinished"));
        }

        var crystalCells = Descendants<NCrystalSphereCell>(surface)
            .Select(cell => cell.Entity)
            .OrderBy(cell => cell.Y)
            .ThenBy(cell => cell.X)
            .Select(cell =>
                $"{cell.X},{cell.Y}:{cell.IsHidden}:{cell.IsHighlighted}:"
                + (cell.Item?.GetType().FullName ?? "-"))
            .ToArray();
        stateParts.AddRange(crystalCells);

        // Ancient dialogue and event minigames can reuse one clickable node for
        // several phases without changing their action shape. Hash visible text
        // locally as a transition token, but never export localized content.
        if (surfaceKind == OutsideCombatSurfaceKind.Event
            && (Descendants<NAncientDialogueHitbox>(surface).Any()
                || Descendants<NDivinationButton>(surface).Any()
                || crystalCells.Length > 0))
        {
            stateParts.Add(ComputeVisibleTextToken(surface));
        }

        return new OutsideCombatChoiceContext(
            contextId,
            ComputeStableToken(stateParts),
            phase,
            minSelections,
            maxSelections,
            selectedCount,
            cancelable,
            requiresConfirmation);
    }

    private static string ReadStableProperty(object? instance, string name) =>
        instance?.GetType().GetProperty(
            name,
            BindingFlags.Instance | BindingFlags.Public)?.GetValue(instance)?.ToString()
        ?? "-";

    private static string ComputeVisibleTextToken(Node surface)
    {
        var text = Descendants<Label>(surface)
            .Where(IsActive)
            .Select(label => label.Text)
            .Concat(Descendants<RichTextLabel>(surface)
                .Where(IsActive)
                .Select(label => label.Text))
            .Where(value => !string.IsNullOrWhiteSpace(value));
        return ComputeStableToken(text);
    }

    private static string ComputeStableToken(IEnumerable<string> values)
    {
        var bytes = Encoding.UTF8.GetBytes(string.Join("\n", values));
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    private static IReadOnlyList<OutsideDecision> FindDecisions()
    {
        var overlay = GetTopOverlay(out var hasStackedScreen);
        // Card removal is a native purchase task that deliberately remains
        // pending while NDeckCardSelectScreen awaits input. Use a scene-tree
        // fallback only while overlay-stack bookkeeping is empty; an unrelated
        // top overlay (for example a pause dialog) must still block input.
        if (_awaitingMerchantCardRemoval
            && !hasStackedScreen
            && FindActiveNode<NDeckCardSelectScreen>() is { } removalScreen)
        {
            var removalDecisions = FindDeckGridDecisions(removalScreen);
            if (removalDecisions.Count > 0)
            {
                return removalDecisions;
            }
        }

        if (overlay is not null)
        {
            var overlayDecisions = FindOverlayDecisions(overlay);
            if (overlayDecisions.Count > 0)
            {
                return overlayDecisions;
            }

            // A completed reward/card overlay can remain visible during its
            // outro while the map is already open. Fall through only after a
            // known overlay is no longer visible; a visible known overlay with
            // temporarily disabled controls is still opening/animating and must
            // block clicks into the room beneath it. Unknown overlays always
            // block, visible or not.
            if (IsActive(overlay) || !IsKnownDecisionOverlay(overlay))
            {
                return [];
            }
        }

        // ScreenCount is authoritative even while Peek() is briefly null. In
        // that transition window, waiting is safer than clicking the room below.
        if (hasStackedScreen && overlay is null)
        {
            return [];
        }

        // A few choice screens are pushed while an action is awaiting input and
        // can briefly precede NOverlayStack bookkeeping. Falling back to the live
        // scene tree prevents the policy from deadlocking on that synchronization
        // window without clicking through a different top overlay.
        var detachedChoice = !hasStackedScreen ? FindActiveChoiceScreen() : null;
        if (detachedChoice is not null)
        {
            var detachedDecisions = FindOverlayDecisions(detachedChoice);
            if (detachedDecisions.Count > 0)
            {
                return detachedDecisions;
            }

            // FindActiveChoiceScreen only returns a visible live selector. No
            // actions here means it is still opening or between phases, not
            // that clicks may safely pass through to the room or map below.
            return [];
        }

        // The native merchant transaction owns the room until its deck picker
        // finishes. A picker can be mounted for a frame before its cards or
        // confirm button become actionable; never click the merchant or map
        // underneath during that window.
        if (_awaitingMerchantCardRemoval)
        {
            return [];
        }

        var eventRoom = NEventRoom.Instance;
        if (IsActive(eventRoom))
        {
            var eventDecisions = FindEventDecisions(eventRoom);
            if (eventDecisions.Count > 0)
            {
                return eventDecisions;
            }
        }

        var restSite = NRestSiteRoom.Instance;
        if (IsActive(restSite))
        {
            var restDecisions = FindRestSiteDecisions(restSite);
            if (restDecisions.Count > 0)
            {
                return restDecisions;
            }
        }

        var merchant = NMerchantRoom.Instance;
        if (IsActive(merchant))
        {
            var merchantDecisions = FindMerchantDecisions(merchant);
            if (merchantDecisions.Count > 0)
            {
                return merchantDecisions;
            }
        }

        var tree = (SceneTree)Engine.GetMainLoop();
        var treasure = tree.Root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom")
            ?? FindActiveNode<NTreasureRoom>();
        if (treasure is not null)
        {
            var treasureDecisions = FindTreasureDecisions(treasure);
            if (treasureDecisions.Count > 0)
            {
                return treasureDecisions;
            }
        }

        // Room and overlay decisions always take priority. Only choose a route
        // after every currently actionable outside-combat decision is drained.
        var map = NMapScreen.Instance;
        return IsActive(map) && map.IsOpen ? FindMapDecisions(map) : [];
    }

    private static Node? FindActiveChoiceScreen()
    {
        Node? screen = FindActiveNode<NCardRewardSelectionScreen>();
        screen ??= FindActiveNode<NChooseACardSelectionScreen>();
        screen ??= FindActiveNode<NChooseABundleSelectionScreen>();
        screen ??= FindActiveNode<NChooseARelicSelection>();
        screen ??= FindActiveNode<NDeckCardSelectScreen>();
        screen ??= FindActiveNode<NCardGridSelectionScreen>();
        screen ??= FindActiveNode<NCrystalSphereScreen>();
        screen ??= FindActiveNode<NRewardsScreen>();
        return screen;
    }

    private static Node? GetTopOverlay(out bool hasStackedScreen)
    {
        var stack = NOverlayStack.Instance;
        if (stack is null
            || !GodotObject.IsInstanceValid(stack)
            || !stack.IsInsideTree()
            || stack.ScreenCount == 0)
        {
            hasStackedScreen = false;
            return null;
        }

        // Keep stack occupancy separate from the top node's visibility. Closed
        // known screens may fall through to the map during their outro, but a
        // hidden/opening screen must never be mistaken for an empty stack by
        // the detached merchant-selector fallback.
        hasStackedScreen = true;
        return stack.Peek() as Node;
    }

    private static IReadOnlyList<OutsideDecision> FindOverlayDecisions(Node screen) => screen switch
    {
        NRewardsScreen rewards => FindRewardDecisions(rewards),
        NCardRewardSelectionScreen cardReward => FindCardRewardDecisions(cardReward),
        NChooseACardSelectionScreen chooseCard => FindSingleCardDecisions(chooseCard),
        NChooseABundleSelectionScreen chooseBundle => FindBundleDecisions(chooseBundle),
        NChooseARelicSelection chooseRelic => FindSingleRelicDecisions(chooseRelic),
        NDeckCardSelectScreen deckGrid => FindDeckGridDecisions(deckGrid),
        NCardGridSelectionScreen grid => FindGridDecisions(grid),
        NCrystalSphereScreen crystalSphere => FindCrystalSphereDecisions(crystalSphere),
        NMapScreen map => FindMapDecisions(map),
        _ => [],
    };

    private static bool IsKnownDecisionOverlay(Node screen) => screen is
        NRewardsScreen
        or NCardRewardSelectionScreen
        or NChooseACardSelectionScreen
        or NChooseABundleSelectionScreen
        or NChooseARelicSelection
        or NDeckCardSelectScreen
        or NCardGridSelectionScreen
        or NCrystalSphereScreen
        or NMapScreen;

    private static IReadOnlyList<OutsideDecision> FindRewardDecisions(NRewardsScreen screen)
    {
        var rewards = FromControls(
            screen,
            Descendants<NRewardButton>(screen)
                .Where(button => button.Reward is not null && CanClaimReward(button)),
            OutsideCombatSurfaceKind.Rewards,
            OutsideCombatActionKind.ClaimReward,
            "reward",
            requireUnattempted: true,
            targetId: button => button.Reward!.GetType().Name);
        return rewards.Count > 0
            ? rewards
            : FromControls(
                screen,
                Descendants<NProceedButton>(screen),
                OutsideCombatSurfaceKind.Rewards,
                OutsideCombatActionKind.Proceed,
                "rewards proceed",
                requireUnattempted: true);
    }

    private static IReadOnlyList<OutsideDecision> FindMapDecisions(NMapScreen map)
    {
        // Map travel can itself be the input awaited by a running game action, so
        // gating on ActionExecutor.IsRunning deadlocks. The game's own AutoSlay
        // handler uses the map's travel flags and the selected point's enabled
        // state as the readiness contract.
        var now = System.Environment.TickCount64;
        if (now < _mapReadyAt)
        {
            return WaitForMap(map, $"settling outside choices ({_mapReadyAt - now}ms remaining)");
        }

        if (!map.IsOpen || !map.IsTravelEnabled || map.IsTraveling)
        {
            return WaitForMap(map, "travel flags not ready");
        }

        var state = RunManager.Instance.DebugOnlyGetState();
        if (state is null)
        {
            return WaitForMap(map, "run state not ready");
        }

        var points = Descendants<NMapPoint>(map).ToArray();
        IEnumerable<NMapPoint> nextPoints;
        if (state.VisitedMapCoords.Count == 0)
        {
            // This matches the game's AutoSlay policy for the first floor.
            nextPoints = points.Where(point => point.Point.coord.row == 0);
        }
        else
        {
            // Do not take the first clickable node in scene-tree order. Follow
            // the actual graph from the most recently visited map coordinate.
            var last = state.VisitedMapCoords[^1];
            var current = points.FirstOrDefault(point => point.Point.coord.Equals(last));
            var children = current?.Point.Children
                ?? state.CurrentMapPoint?.Children
                ?? [];
            var childCoordinates = children.Select(child => child.coord).ToHashSet();
            nextPoints = points.Where(point => childCoordinates.Contains(point.Point.coord));
        }

        var usable = nextPoints
            .Where(next => GodotObject.IsInstanceValid(next)
                && next.IsInsideTree()
                && next.IsEnabled)
            .OrderBy(next => next.Point.coord.row)
            .ThenBy(next => next.Point.coord.col)
            .ToArray();
        if (usable.Length == 0)
        {
            return WaitForMap(map, "no enabled graph child node found");
        }

        // Visibility is intentionally not required: clipped map controls remain
        // valid native targets. Expose every reachable child to future policies;
        // first-legal deterministically picks the lowest coordinate.
        return usable
            .Select(next =>
            {
                var coordinate = new OutsideMapCoordinate(
                    next.Point.coord.row,
                    next.Point.coord.col);
                return new OutsideDecision(
                    map,
                    next,
                    OutsideCombatSurfaceKind.Map,
                    OutsideCombatActionKind.Travel,
                    $"map point {coordinate}",
                    TargetId: next.Point.PointType.ToString(),
                    MapCoordinate: coordinate);
            })
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> WaitForMap(NMapScreen map, string reason)
    {
        var now = System.Environment.TickCount64;
        if (now >= _nextMapWaitLogAt)
        {
            _nextMapWaitLogAt = now + 3000;
            GD.Print(
                $"[SlayTheModel] outside first-legal waiting for map: {reason}; "
                + $"open={map.IsOpen} travelEnabled={map.IsTravelEnabled} traveling={map.IsTraveling}");
        }

        return [];
    }

    private static IReadOnlyList<OutsideDecision> FindCardRewardDecisions(
        NCardRewardSelectionScreen screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return [];
        }

        var cards = FromCards(
                screen,
                GetCardHolders(screen),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.ChooseCard,
                "card reward")
            .Select(decision => decision with { CompletesSingleChoice = true });
        var alternatives = FromControls(
                screen,
                Descendants<NCardRewardAlternativeButton>(screen),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.ChooseRewardAlternative,
                "card reward alternative",
                requireUnattempted: true)
            .Select(decision => decision with { CompletesSingleChoice = true });
        var skips = FromControls(
                screen,
                Descendants<NChoiceSelectionSkipButton>(screen),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.Skip,
                "card reward skip")
            .Select(decision => decision with { CompletesSingleChoice = true });
        return cards.Concat(alternatives).Concat(skips).ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindSingleCardDecisions(
        NChooseACardSelectionScreen screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return [];
        }

        return FromCards(
                screen,
                Descendants<NCardHolder>(screen),
                OutsideCombatSurfaceKind.CardChoice,
                OutsideCombatActionKind.ChooseCard,
                "card choice")
            .Concat(FromControls(
                screen,
                Descendants<NChoiceSelectionSkipButton>(screen),
                OutsideCombatSurfaceKind.CardChoice,
                OutsideCombatActionKind.Skip,
                "card choice skip"))
            .Select(decision => decision with { CompletesSingleChoice = true })
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindSingleRelicDecisions(
        NChooseARelicSelection screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return [];
        }

        return FromControls(
                screen,
                Descendants<NRelicBasicHolder>(screen),
                OutsideCombatSurfaceKind.RelicChoice,
                OutsideCombatActionKind.ChooseRelic,
                "relic choice",
                targetId: holder => holder.Relic.Model.Id.ToString())
            .Concat(FromControls(
                screen,
                Descendants<NChoiceSelectionSkipButton>(screen),
                OutsideCombatSurfaceKind.RelicChoice,
                OutsideCombatActionKind.Skip,
                "relic choice skip"))
            .Select(decision => decision with { CompletesSingleChoice = true })
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindBundleDecisions(
        NChooseABundleSelectionScreen screen)
    {
        SetSurface(screen);
        var bundleNodes = Descendants<NCardBundle>(screen).ToArray();
        var bundles = FromControls(
            screen,
            bundleNodes.Select(bundle => bundle.Hitbox),
            OutsideCombatSurfaceKind.CardBundleChoice,
            OutsideCombatActionKind.ChooseCardBundle,
            "card bundle",
            targetId: hitbox => string.Join(
                "|",
                bundleNodes
                    .First(bundle => ReferenceEquals(bundle.Hitbox, hitbox))
                    .Bundle
                    .Select(card => $"{card.Id}+{card.CurrentUpgradeLevel}")));
        var confirm = FromControls(
            screen,
            Descendants<NConfirmButton>(screen),
            OutsideCombatSurfaceKind.CardBundleChoice,
            OutsideCombatActionKind.Confirm,
            "confirm first card bundle");
        return (AttemptedOnSurface.Count > 0
                ? confirm.Concat(bundles)
                : bundles.Concat(confirm))
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindGridDecisions(
        NCardGridSelectionScreen screen)
    {
        SetSurface(screen);
        const OutsideCombatSurfaceKind surfaceKind = OutsideCombatSurfaceKind.CardGridChoice;
        var cards = FromCards(
            screen,
            GetCardHolders(screen),
            surfaceKind,
            OutsideCombatActionKind.ChooseCard,
            "card selection",
            requireUnattempted: true);
        var confirm = FromControls(
            screen,
            Descendants<NConfirmButton>(screen),
            surfaceKind,
            OutsideCombatActionKind.Confirm,
            "confirm first card selection");
        return (AttemptedOnSurface.Count > 0
                ? confirm.Concat(cards)
                : cards.Concat(confirm))
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindDeckGridDecisions(
        NDeckCardSelectScreen screen)
    {
        SetSurface(screen);
        var surfaceKind = _awaitingMerchantCardRemoval
            ? OutsideCombatSurfaceKind.MerchantCardRemoval
            : OutsideCombatSurfaceKind.CardGridChoice;

        // NDeckCardSelectScreen has two distinct phases. The main %Confirm
        // opens a preview; %PreviewConfirm completes the task, while
        // %PreviewCancel only returns to the still-pending grid. The main
        // confirm remains enabled in preview for some selector preferences, so
        // enumerating all descendant confirm buttons is not phase-safe.
        var preview = screen.GetNodeOrNull<Control>("%PreviewContainer");
        var inPreview = preview is { Visible: true } && preview.IsVisibleInTree();
        if (inPreview)
        {
            var commit = FromControls(
                screen,
                Enumerate(preview!.GetNodeOrNull<NConfirmButton>("%PreviewConfirm")),
                surfaceKind,
                OutsideCombatActionKind.Confirm,
                "confirm card selection preview");
            var back = FromControls(
                    screen,
                    Enumerate(preview.GetNodeOrNull<NBackButton>("%PreviewCancel")),
                    surfaceKind,
                    OutsideCombatActionKind.BackToSelection,
                    "return from card selection preview")
                .Select(decision => decision with { ResetsSelectionAttempts = true });
            return commit.Concat(back).ToArray();
        }

        IReadOnlyList<OutsideDecision> cards;
        if (_awaitingMerchantCardRemoval)
        {
            cards = GetCardHolders(screen)
                .Select((holder, index) => new
                {
                    Holder = holder,
                    Card = holder.CardNode?.Model,
                    Index = index,
                })
                .Where(candidate => IsActive(candidate.Holder)
                    && IsUsable(candidate.Holder.Hitbox)
                    && candidate.Card is not null
                    && !AttemptedOnSurface.Contains(candidate.Holder.GetInstanceId()))
                .OrderBy(candidate => candidate.Index)
                .Select(candidate => new OutsideDecision(
                    screen,
                    candidate.Holder,
                    surfaceKind,
                    OutsideCombatActionKind.RemoveCard,
                    $"merchant remove card {candidate.Card!.Id.Entry}",
                    TargetId: candidate.Card.Id.ToString(),
                    CardHolder: candidate.Holder,
                    NativeCard: candidate.Card))
                .ToArray();
        }
        else
        {
            cards = FromCards(
                screen,
                GetCardHolders(screen),
                surfaceKind,
                OutsideCombatActionKind.ChooseCard,
                "card selection",
                requireUnattempted: true);
        }

        var confirm = FromControls(
            screen,
            Enumerate(screen.GetNodeOrNull<NConfirmButton>("%Confirm")),
            surfaceKind,
            OutsideCombatActionKind.Confirm,
            "preview card selection");
        var close = FromControls(
            screen,
            Enumerate(screen.GetNodeOrNull<NBackButton>("%Close")),
            surfaceKind,
            OutsideCombatActionKind.CancelSelection,
            "cancel card selection");

        // Preserve first-legal's existing behavior: once it has selected the
        // minimum number of cards, prefer the enabled confirm over selecting
        // more. All other native legal actions still remain visible to a future
        // learned policy.
        var primary = AttemptedOnSurface.Count > 0
            ? confirm.Concat(cards)
            : cards.Concat(confirm);
        return primary.Concat(close).ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FindCrystalSphereDecisions(
        NCrystalSphereScreen screen)
    {
        var divinations = FromControls(
            screen,
            Descendants<NDivinationButton>(screen),
            OutsideCombatSurfaceKind.CrystalSphere,
            OutsideCombatActionKind.ChooseMinigameOption,
            "crystal sphere divination");
        if (divinations.Count > 0)
        {
            return divinations;
        }

        var cells = FromControls(
            screen,
            Descendants<NCrystalSphereCell>(screen),
            OutsideCombatSurfaceKind.CrystalSphere,
            OutsideCombatActionKind.ChooseMinigameOption,
            "crystal sphere cell",
            targetId: CrystalCellTargetId);
        return cells.Count > 0
            ? cells
            : FromControls(
                screen,
                Descendants<NProceedButton>(screen),
                OutsideCombatSurfaceKind.CrystalSphere,
                OutsideCombatActionKind.Proceed,
                "crystal sphere proceed");
    }

    private static IReadOnlyList<OutsideDecision> FindEventDecisions(NEventRoom room)
    {
        // NEventRoom creates the buttons in semantic option order. The model
        // flags let us skip locked and already-consumed choices instead of
        // getting stuck on the first rendered button.
        var options = FromControls(
            room,
            Descendants<NEventOptionButton>(room)
            .Where(button => IsUsable(button)
                && button.Option is not null
                && !button.Option.IsLocked
                && !button.Option.WasChosen),
            OutsideCombatSurfaceKind.Event,
            OutsideCombatActionKind.ChooseEventOption,
            "event option",
            targetId: button => button.Option.TextKey);
        if (options.Count > 0)
        {
            return options;
        }

        var ancient = FromControls(
            room,
            Descendants<NAncientDialogueHitbox>(room),
            OutsideCombatSurfaceKind.Event,
            OutsideCombatActionKind.ChooseEventOption,
            "ancient event option");
        if (ancient.Count > 0)
        {
            return ancient;
        }

        var divinations = FromControls(
            room,
            Descendants<NDivinationButton>(room),
            OutsideCombatSurfaceKind.Event,
            OutsideCombatActionKind.ChooseMinigameOption,
            "event divination");
        return divinations.Count > 0
            ? divinations
            : FromControls(
                room,
                Descendants<NCrystalSphereCell>(room),
                OutsideCombatSurfaceKind.Event,
                OutsideCombatActionKind.ChooseMinigameOption,
                "event minigame choice",
                targetId: CrystalCellTargetId);
    }

    private static IReadOnlyList<OutsideDecision> FindRestSiteDecisions(NRestSiteRoom room)
    {
        var options = FromControls(
            room,
            Descendants<NRestSiteButton>(room),
            OutsideCombatSurfaceKind.RestSite,
            OutsideCombatActionKind.ChooseRestSiteOption,
            "rest-site option",
            requireUnattempted: true,
            targetId: button => button.Option.OptionId);
        return options.Count > 0
            ? options
            : FromControls(
                room,
                Enumerate(room.ProceedButton),
                OutsideCombatSurfaceKind.RestSite,
                OutsideCombatActionKind.Proceed,
                "rest-site proceed",
                requireUnattempted: true);
    }

    private static IReadOnlyList<OutsideDecision> FindMerchantDecisions(NMerchantRoom room)
    {
        SetSurface(room);
        var inventory = room.Inventory;
        if (IsActive(inventory) && inventory.IsOpen)
        {
            _merchantOpenedInRoom = _surfaceId;
            var removal = inventory.GetAllSlots().OfType<NMerchantCardRemoval>().FirstOrDefault();
            if (removal is not null && removal.Entry.IsStocked && removal.Entry.EnoughGold)
            {
                if (_awaitingMerchantCardRemoval)
                {
                    return [];
                }

                if (_merchantCardRemovalAttemptedInRoom != _surfaceId
                    && IsUsable(removal.Hitbox))
                {
                    return
                    [
                        new OutsideDecision(
                        room,
                        removal.Hitbox,
                        OutsideCombatSurfaceKind.Merchant,
                        OutsideCombatActionKind.OpenCardRemoval,
                        "open merchant card removal",
                        Cost: removal.Entry.Cost,
                        StartsMerchantCardRemoval: true,
                        MerchantCardRemoval: removal,
                        MerchantInventory: inventory),
                    ];
                }
            }

            // Do not buy arbitrary inventory items. If removal is absent, used,
            // or unaffordable, first-legal deliberately leaves the shop.
            var back = inventory.GetNodeOrNull<NClickableControl>("%BackButton");
            var leave = FromControls(
                    room,
                    Enumerate(back),
                    OutsideCombatSurfaceKind.Merchant,
                    OutsideCombatActionKind.LeaveMerchant,
                    "leave merchant (card removal unavailable or unaffordable)",
                    requireUnattempted: true);
            return leave.Count > 0
                ? leave
                : FromControls(
                    room,
                    Descendants<NBackButton>(inventory),
                    OutsideCombatSurfaceKind.Merchant,
                    OutsideCombatActionKind.LeaveMerchant,
                    "close merchant inventory",
                    requireUnattempted: true);
        }

        if (_merchantOpenedInRoom != _surfaceId)
        {
            return FromControls(
                    room,
                    Enumerate(room.MerchantButton),
                    OutsideCombatSurfaceKind.Merchant,
                    OutsideCombatActionKind.OpenMerchant,
                    "open merchant inventory")
                .Select(decision => decision with { MarksMerchantOpened = true })
                .ToArray();
        }

        return FromControls(
            room,
            Enumerate(room.ProceedButton),
            OutsideCombatSurfaceKind.Merchant,
            OutsideCombatActionKind.Proceed,
            "merchant-room proceed",
            requireUnattempted: true);
    }

    private static IReadOnlyList<OutsideDecision> FindTreasureDecisions(NTreasureRoom room)
    {
        SetSurface(room);
        var chest = FromControls(
            room,
            Enumerate(room.GetNodeOrNull<NClickableControl>("Chest")),
            OutsideCombatSurfaceKind.Treasure,
            OutsideCombatActionKind.OpenChest,
            "open treasure chest",
            requireUnattempted: true);
        if (chest.Count > 0)
        {
            return chest;
        }

        var buttons = FromControls(
            room,
            Descendants<NTreasureButton>(room),
            OutsideCombatSurfaceKind.Treasure,
            OutsideCombatActionKind.OpenChest,
            "open treasure chest",
            requireUnattempted: true);
        if (buttons.Count > 0)
        {
            return buttons;
        }

        var relics = FromControls(
            room,
            Descendants<NTreasureRoomRelicHolder>(room),
            OutsideCombatSurfaceKind.Treasure,
            OutsideCombatActionKind.TakeTreasureRelic,
            "treasure relic",
            requireUnattempted: true,
            targetId: holder => holder.Relic.Model.Id.ToString());
        return relics.Count > 0
            ? relics
            : FromControls(
                room,
                Enumerate(room.ProceedButton),
                OutsideCombatSurfaceKind.Treasure,
                OutsideCombatActionKind.Proceed,
                "treasure-room proceed",
                requireUnattempted: true);
    }

    private static IReadOnlyList<OutsideDecision> FromControls<T>(
        Node surface,
        IEnumerable<T> controls,
        OutsideCombatSurfaceKind surfaceKind,
        OutsideCombatActionKind actionKind,
        string description,
        bool requireUnattempted = false,
        Func<T, string?>? targetId = null)
        where T : NClickableControl
    {
        SetSurface(surface);
        return controls
            .Where(control => IsUsable(control)
                && (!requireUnattempted
                    || !AttemptedOnSurface.Contains(control.GetInstanceId())))
            .Select(control => new OutsideDecision(
                surface,
                control,
                surfaceKind,
                actionKind,
                description,
                TargetId: targetId?.Invoke(control)))
            .ToArray();
    }

    private static IReadOnlyList<OutsideDecision> FromCards(
        Node surface,
        IEnumerable<NCardHolder> holders,
        OutsideCombatSurfaceKind surfaceKind,
        OutsideCombatActionKind actionKind,
        string description,
        bool requireUnattempted = false)
    {
        SetSurface(surface);
        return holders
            .Select(holder => new { Holder = holder, Card = holder.CardNode?.Model })
            .Where(candidate => IsActive(candidate.Holder)
                && IsUsable(candidate.Holder.Hitbox)
                && candidate.Card is not null
                && (!requireUnattempted
                    || !AttemptedOnSurface.Contains(candidate.Holder.GetInstanceId())))
            .Select(candidate => new OutsideDecision(
                surface,
                candidate.Holder,
                surfaceKind,
                actionKind,
                description,
                TargetId: candidate.Card!.Id.ToString(),
                CardHolder: candidate.Holder,
                NativeCard: candidate.Card))
            .ToArray();
    }

    private static IEnumerable<T> Enumerate<T>(T? value) where T : class
    {
        if (value is not null)
        {
            yield return value;
        }
    }

    private static IReadOnlyList<NCardHolder> GetCardHolders(Node screen) =>
        Descendants<NCardGrid>(screen)
            .SelectMany(grid => grid.CurrentlyDisplayedCardHolders)
            .Cast<NCardHolder>()
            .Concat(Descendants<NCardHolder>(screen))
            .GroupBy(holder => holder.GetInstanceId())
            .Select(group => group.First())
            .ToArray();

    private static bool CanClaimReward(NRewardButton button)
    {
        if (button.Reward is not PotionReward)
        {
            return true;
        }

        var state = RunManager.Instance.DebugOnlyGetState();
        return state is not null
            && state.Players.Count == 1
            && state.Players[0].HasOpenPotionSlots;
    }

    private static T? FindActiveNode<T>() where T : Node
    {
        var tree = Engine.GetMainLoop() as SceneTree;
        return tree is null
            ? null
            : Descendants<T>(tree.Root).FirstOrDefault(IsActive);
    }

    private static IEnumerable<T> Descendants<T>(Node root) where T : Node
    {
        foreach (var child in root.GetChildren())
        {
            if (child is T match)
            {
                yield return match;
            }

            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }

    private static bool IsUsable(NClickableControl control) =>
        IsActive(control) && control.IsEnabled;

    private static string CrystalCellTargetId(NCrystalSphereCell cell)
    {
        var entity = cell.Entity;
        return $"{entity.X},{entity.Y}:{entity.IsHidden}:{entity.IsHighlighted}:"
            + (entity.Item?.GetType().FullName ?? "-");
    }

    private static bool IsActive([NotNullWhen(true)] Node? node) =>
        node is not null
        && GodotObject.IsInstanceValid(node)
        && node.IsInsideTree()
        && (node is not CanvasItem canvasItem || canvasItem.IsVisibleInTree());

    private static void SetSurface(Node surface)
    {
        var id = surface.GetInstanceId();
        if (_surfaceId == id)
        {
            return;
        }

        _surfaceId = id;
        _completedSingleChoiceSurfaceId = 0;
        AttemptedOnSurface.Clear();
        _surfaceReadyAt = System.Environment.TickCount64 + SurfaceSettleMilliseconds;
    }

    private sealed record OutsideDecision(
        Node Surface,
        Node Target,
        OutsideCombatSurfaceKind SurfaceKind,
        OutsideCombatActionKind ActionKind,
        string Description,
        string? TargetId = null,
        OutsideMapCoordinate? MapCoordinate = null,
        int? Cost = null,
        bool MarksMerchantOpened = false,
        NCardHolder? CardHolder = null,
        CardModel? NativeCard = null,
        bool CompletesSingleChoice = false,
        bool ResetsSelectionAttempts = false,
        bool StartsMerchantCardRemoval = false,
        NMerchantCardRemoval? MerchantCardRemoval = null,
        NMerchantInventory? MerchantInventory = null)
    {
        internal NClickableControl? Control => Target as NClickableControl;

        internal OutsideCombatActionDescriptor ToDescriptor(int ordinal, RunState state)
        {
            var targetDeckIndex = NativeCard is null
                ? null
                : FindDeckIndex(state, NativeCard);
            var semanticTarget = MapCoordinate is { } coordinate
                ? $"{coordinate.Row},{coordinate.Column}"
                : TargetId ?? "-";
            if (targetDeckIndex is { } deckIndex)
            {
                semanticTarget += $"@deck:{deckIndex}";
            }

            return new OutsideCombatActionDescriptor(
                $"{ActionKind.ToString().ToLowerInvariant()}:{ordinal}:{semanticTarget}",
                ActionKind,
                ordinal,
                TargetId,
                MapCoordinate,
                Cost,
                targetDeckIndex);
        }

        private static int? FindDeckIndex(RunState state, CardModel target)
        {
            // Live outside control is deliberately single-player. Reference
            // identity maps duplicate cards to the exact deck entry represented
            // by OutsideRunCardObservation.DeckIndex.
            if (state.Players.Count != 1)
            {
                return null;
            }

            var cards = state.Players[0].Deck.Cards;
            for (var index = 0; index < cards.Count; index++)
            {
                if (ReferenceEquals(cards[index], target))
                {
                    return index;
                }
            }

            return null;
        }
    }

    private sealed record PendingOutsideAction(
        OutsideCombatDecisionSample Sample,
        Node Target,
        ulong SurfaceId,
        ulong TargetId,
        bool ResetsSelectionAttempts,
        bool CompletesSingleChoice,
        bool MarksMerchantOpened,
        long StartedAt);
}
