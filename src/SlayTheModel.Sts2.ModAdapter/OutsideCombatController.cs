using Godot;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
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
    private static readonly FieldInfo? CardRewardExtraOptionsField =
        typeof(NCardRewardSelectionScreen).GetField("_extraOptions", BindingFlags.Instance | BindingFlags.NonPublic);
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
    private static long _nextDiagnosticAt;
    private static bool _faulted;
    private static bool _clicking;
    private static IOutsideCombatPolicy? _policy;
    private static ArmGOutsidePolicy? _armg;
    private static Task<ArmGResponse>? _armgRequest;
    private static string? _armgRequestFingerprint;
    private static long _armgRequestGeneration;
    private static string? _armgManualFingerprint;
    private static long _armgManualGeneration;
    private static readonly FirstLegalOutsideCombatPolicy FallbackPolicy = new();
    private static Task<bool>? _merchantCardRemovalTask;
    private static OutsideCombatDecisionSample? _merchantCardRemovalSample;
    private static RunState? _merchantCardRemovalRun;
    private static PendingOutsideAction? _pendingOutsideAction;
    private static readonly Dictionary<ulong, OutsideShopItem> MerchantItemCache = [];
    private static ulong _merchantCacheRoom;
    private static CardModel? _plannedMerchantRemoval;
    private static Task<bool>? _merchantPurchaseTask;
    private static long _merchantPurchaseStartedAt;
    private static RunState? _merchantPurchaseRun;
    private static ulong _completedRewardsProceedSurfaceId;
    private static RunState? _completedRewardsProceedRun;
    private static int _completedRewardsProceedFloor;
    private static ulong _openCardRewardButtonId;
    private static readonly HashSet<ulong> SkippedCardRewardButtons = [];
    private static RunState? _cardRewardRun;
    private static int _cardRewardFloor;

    private const int ActionCooldownMilliseconds = 350;
    private const int SurfaceSettleMilliseconds = 450;
    private const int MapSettleMilliseconds = 1000;
    private const int OutsideTransitionTimeoutMilliseconds = 15_000;
    private const int MerchantCardRemovalTimeoutMilliseconds = 30_000;

    internal static void Initialize(AdapterConfiguration configuration)
    {
        ArmGSwitch.Configure(configuration.RunMode == AdapterRunMode.Play
            && configuration.OutsideCombatPolicy == OutsideCombatPolicyKind.ArmG);
        if (configuration.RunMode == AdapterRunMode.Train)
        {
            Console.WriteLine("[SlayTheModel] train mode is declared but no trainer is connected yet; live policies are disabled");
            return;
        }

        if (configuration.OutsideCombatPolicy == OutsideCombatPolicyKind.Manual)
        {
            return;
        }

        if (configuration.OutsideCombatPolicy == OutsideCombatPolicyKind.ArmG)
        {
            try { _armg = new ArmGOutsidePolicy(); }
            catch (Exception exception) when (exception is not OutOfMemoryException)
            {
                Console.Error.WriteLine($"[SlayTheModel] ArmG configuration invalid; using first-legal: {exception.Message}");
                _policy = FallbackPolicy;
                ArmGSwitch.Configure(false);
            }
            if (_armg is not null) _policy = _armg;
        }
        else _policy = new FirstLegalOutsideCombatPolicy();
        _enabled = true;
        Callable.From(() =>
        {
            var tree = (SceneTree)Engine.GetMainLoop();
            tree.ProcessFrame += Tick;
            tree.Root.TreeExiting += Stop;
        }).CallDeferred();
        Console.WriteLine(
            $"[SlayTheModel] OUTSIDE CONTROL ENABLED policy={_policy!.PolicyId}; "
            + (_armg is null ? "first legal" : _armg.AutoMode ? "model auto mode" : "shadow mode; player retains control"));
    }

    private static void Stop()
    {
        ArmGSwitch.Configure(false);
        _enabled = false;
        AttemptedOnSurface.Clear();
        _surfaceId = 0;
        _completedSingleChoiceSurfaceId = 0;
        MerchantItemCache.Clear();
        _merchantCacheRoom = 0;
        _plannedMerchantRemoval = null;
        _merchantPurchaseTask = null;
        _merchantPurchaseRun = null;
        ClearCompletedRewardsProceed();
        ClearSkippedCardRewards();
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
        _armg?.Dispose();
        _armg = null;
        DiscardArmGRequest();
        _armgManualFingerprint = null;
        _policy = null;
        OutsideCombatCaptureService.Reset();
    }

    private static void Tick()
    {
        var runManager = RunManager.Instance;
        var state = runManager.IsInProgress
            ? runManager.DebugOnlyGetState()
            : null;
        if (_merchantPurchaseTask is not null && !ReferenceEquals(_merchantPurchaseRun, state))
        {
            _merchantPurchaseTask = null;
            _merchantPurchaseRun = null;
        }
        if (_merchantPurchaseTask is not null && !_faulted
            && System.Environment.TickCount64 - _merchantPurchaseStartedAt >= 30_000)
        {
            _faulted = true;
            GD.PushError("[SlayTheModel] merchant purchase exceeded 30 seconds; outside policy disabled.");
            return;
        }
        if (_cardRewardRun is not null
            && (!ReferenceEquals(_cardRewardRun, state) || state is null
                || state.TotalFloor != _cardRewardFloor || CombatManager.Instance.IsInProgress))
        {
            ClearSkippedCardRewards();
        }
        if (_completedRewardsProceedRun is not null
            && (!ReferenceEquals(_completedRewardsProceedRun, state)
                || state is null
                || state.TotalFloor != _completedRewardsProceedFloor
                || CombatManager.Instance.IsInProgress))
        {
            ClearCompletedRewardsProceed();
        }
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
            if (state is not null)
            {
                TraceWait($"tick blocked: enabled={_enabled} faulted={_faulted} "
                    + $"clicking={_clicking} combat={CombatManager.Instance.IsInProgress} "
                    + $"cooldown={System.Environment.TickCount64 < _nextActionAt}");
            }
            return;
        }

        // The state itself is the readiness signal. Never scan residual room or
        // map nodes after a run ended, and keep one snapshot throughout this
        // frame so capture and native bindings refer to the same run.
        if (state is null || state.Players.Count != 1)
        {
            if (state is not null) TraceWait($"unexpected player count: {state.Players.Count}");
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
                actions,
                surface is NMerchantRoom merchant && merchant.Inventory is { IsOpen: true } inventory
                    ? CaptureShop(merchant, inventory) : null);
            if (WaitForPendingOutsideAction(decisionPoint.StateFingerprint))
            {
                return;
            }

            var usedFallback = false;
            OutsideCombatActionDescriptor? selectedAction;
            if (_armg is null)
                selectedAction = _policy.SelectAction(decisionPoint);
            else if (!ArmGSwitch.Enabled)
            {
                // A response started under a previous switch generation may
                // never be applied after the user disables the network.
                DiscardArmGRequest();
                _armgManualFingerprint = null;
                _armgManualGeneration = 0;
                selectedAction = FallbackPolicy.SelectAction(decisionPoint);
                usedFallback = true;
            }
            else
                selectedAction = PollArmG(decisionPoint, out usedFallback);
            if (selectedAction is null)
            {
                TraceWait($"policy returned no action: surface={surface.GetType().Name} "
                    + $"armgPending={_armgRequest is not null} armgEnabled={ArmGSwitch.Enabled}");
                return;
            }
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
                usedFallback ? FallbackPolicy : _policy,
                decisionPoint,
                step);

            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            if (decision.StartsMerchantCardRemoval)
            {
                _plannedMerchantRemoval = decision.NativeCard;
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
            GD.PushError($"[SlayTheModel] outside policy failed: {exception}");
            GD.PushError("[SlayTheModel] outside policy disabled after failure; restart to retry.");
        }
    }

    private static void TraceWait(string reason)
    {
        var now = System.Environment.TickCount64;
        if (now < _nextDiagnosticAt) return;
        _nextDiagnosticAt = now + 5000;
        GD.Print($"[SlayTheModel] outside diagnostic: {reason}");
    }

    private static void DiscardArmGRequest()
    {
        var old = _armgRequest;
        _armgRequest = null;
        _armgRequestFingerprint = null;
        _armgRequestGeneration = 0;
        if (old is not null)
            _ = old.ContinueWith(t => { _ = t.Exception; },
                CancellationToken.None, TaskContinuationOptions.OnlyOnFaulted,
                TaskScheduler.Default);
    }

    private static OutsideCombatActionDescriptor? PollArmG(
        OutsideCombatDecisionPoint decision, out bool usedFallback)
    {
        usedFallback = false;
        var policy = _armg ?? throw new InvalidOperationException("ArmG policy is unavailable.");
        if (_armgManualFingerprint == decision.StateFingerprint
            && _armgManualGeneration == ArmGSwitch.Generation) return null;
        _armgManualFingerprint = null;
        if (_armgRequest is not null && _armgRequestGeneration != ArmGSwitch.Generation)
            DiscardArmGRequest();
        if (_armgRequest is null)
        {
            _armgRequestFingerprint = decision.StateFingerprint;
            _armgRequestGeneration = ArmGSwitch.Generation;
            _armgRequest = Task.Run(() => policy.SelectAsync(decision));
            return null;
        }
        if (!_armgRequest.IsCompleted) return null;

        var request = _armgRequest;
        var requestedFingerprint = _armgRequestFingerprint;
        _armgRequest = null;
        _armgRequestFingerprint = null;
        _armgRequestGeneration = 0;
        // A human may have changed the screen while inference was in flight.
        if (requestedFingerprint != decision.StateFingerprint)
        {
            _ = request.ContinueWith(t => { _ = t.Exception; }, CancellationToken.None,
                TaskContinuationOptions.OnlyOnFaulted, TaskScheduler.Default);
            return null;
        }
        ArmGResponse response;
        try { response = request.GetAwaiter().GetResult(); }
        catch (Exception exception) when (policy.AutoMode && exception is not OutOfMemoryException)
        {
            // Select from the *current* legal set; never use the failed reply.
            Console.Error.WriteLine($"[SlayTheModel] ArmG failed, using first-legal: {exception.Message}");
            GD.PushWarning($"[SlayTheModel] ArmG failed, using first-legal: {exception.Message}");
            usedFallback = true;
            return FallbackPolicy.SelectAction(decision);
        }
        PublishArmGSuggestion(decision, response);
        OutsideCombatActionDescriptor? selected;
        try
        {
            selected = ArmGFallbackPolicy.Select(decision, response, policy.AutoMode,
                policy.AllowApproximate, out usedFallback);
        }
        catch (InvalidDataException exception) when (policy.AutoMode)
        {
            // Ignore an invalid/stale response and choose only from the
            // current captured legal set; never execute the worker's action.
            Console.Error.WriteLine($"[SlayTheModel] ArmG response rejected, using first-legal: {exception.Message}");
            usedFallback = true;
            selected = FallbackPolicy.SelectAction(decision);
        }
        if (usedFallback)
        {
            Console.WriteLine($"[SlayTheModel] ArmG fallback to first-legal: {response.Status}: {response.Reason}");
            GD.Print($"[SlayTheModel] ArmG fallback to first-legal: {response.Status}: {response.Reason}");
        }
        if (selected is null)
        {
            _armgManualFingerprint = decision.StateFingerprint;
            _armgManualGeneration = ArmGSwitch.Generation;
            Console.WriteLine($"[SlayTheModel] ArmG shadow suggestion: {response.ActionId}; "
                + $"approximate={response.Approximate}; missing={string.Join(',', response.MissingFeatures ?? [])}; "
                + "handle this screen manually.");
            return null;
        }
        return selected;
    }

    private static void PublishArmGSuggestion(OutsideCombatDecisionPoint decision, ArmGResponse response)
    {
        try
        {
            var directory = CombatCaptureService.GetOutputDirectory();
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "latest-armg-suggestion.json");
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, ProtocolJson.Serialize(new
                {
                    decision.StateFingerprint,
                    decision.DecisionIndex,
                    response.Status,
                    response.ActionId,
                    response.Reason,
                    response.Approximate,
                    response.MissingFeatures,
                    Candidates = decision.LegalActions.Select((action, index) => new
                    {
                        action.ActionId,
                        action.Kind,
                        action.TargetId,
                        action.TargetUpgradeLevel,
                        Logit = response.Scores is { } scores && index < scores.Count ? scores[index] : (float?)null,
                    }).ToArray(),
                }));
                File.Move(temporary, path, overwrite: true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            Console.Error.WriteLine($"[SlayTheModel] ArmG suggestion capture failed: {exception.Message}");
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
            // These specific native actions open the existing map. Capture its
            // closed state before sending the signal so an already-open map
            // cannot be mistaken for a transition caused by the action.
            var opensMap = (decision.ActionKind == OutsideCombatActionKind.Proceed
                    && decision.Surface is NRestSiteRoom or NMerchantRoom or NTreasureRoom)
                || (decision.ActionKind == OutsideCombatActionKind.ChooseEventOption
                    && decision.Target is NEventOptionButton { Option.IsProceed: true });
            var mapBefore = NMapScreen.Instance;
            var closedMapId = opensMap && mapBefore is not null
                && GodotObject.IsInstanceValid(mapBefore) && !mapBefore.IsOpen
                ? mapBefore.GetInstanceId() : 0;
            GD.Print(
                $"[SlayTheModel] outside action: {decision.Description} "
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
            else if (decision.MerchantItem is not null && decision.MerchantInventory is not null)
            {
                var entry = decision.MerchantItem.Entry;
                var currentId = entry switch
                {
                    MerchantCardEntry c => c.CreationResult?.Card.Id.ToString(),
                    MerchantRelicEntry r => r.Model?.Id.ToString(),
                    MerchantPotionEntry p => p.Model?.Id.ToString(),
                    _ => null,
                };
                if (!entry.IsStocked || !entry.EnoughGold || entry.Cost != decision.Cost
                    || !string.Equals(currentId, decision.TargetId, StringComparison.Ordinal)
                    || (entry is MerchantCardEntry cardEntry
                        && !ReferenceEquals(cardEntry.CreationResult?.Card, decision.NativeCard)))
                    throw new InvalidOperationException("Merchant item changed before purchase.");
                var operation = entry.OnTryPurchaseWrapper(decision.MerchantInventory.Inventory);
                _merchantPurchaseTask = operation;
                _merchantPurchaseRun = RunManager.Instance.DebugOnlyGetState();
                _merchantPurchaseStartedAt = System.Environment.TickCount64;
                _ = ObserveMerchantPurchaseAsync(operation, sample, targetId);
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

            if (decision.MerchantCardRemoval is null && decision.MerchantItem is null)
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
                    decision.MarksMerchantOpened,
                    decision.Target is NRewardButton rewardButton && rewardButton.Reward is CardReward,
                    decision.SurfaceKind == OutsideCombatSurfaceKind.CardReward
                        && decision.ActionKind == OutsideCombatActionKind.Skip,
                    decision.Surface is NRewardsScreen
                        && decision.ActionKind == OutsideCombatActionKind.Proceed,
                    closedMapId);
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

    private static async Task ObserveMerchantPurchaseAsync(
        Task<bool> operation, OutsideCombatDecisionSample sample, ulong targetId)
    {
        try
        {
            var success = await operation;
            if (!ReferenceEquals(_merchantPurchaseTask, operation)) return;
            if (!success) AttemptedOnSurface.Add(targetId);
            OutsideCombatCaptureService.RecordExecution(sample,
                success ? OutsideCombatExecutionStatus.ObservedTransition : OutsideCombatExecutionStatus.Failed,
                success ? "native merchant purchase completed" : "native merchant purchase rejected");
        }
        catch (Exception exception)
        {
            if (!ReferenceEquals(_merchantPurchaseTask, operation)) return;
            _faulted = true;
            OutsideCombatCaptureService.RecordExecution(sample, OutsideCombatExecutionStatus.Failed,
                $"native purchase failed: {exception.Message}");
            GD.PushError($"[SlayTheModel] merchant purchase failed: {exception}");
        }
        finally
        {
            if (ReferenceEquals(_merchantPurchaseTask, operation))
            {
                _merchantPurchaseTask = null;
                _merchantPurchaseRun = null;
            }
            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
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
            _plannedMerchantRemoval = null;
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
        bool marksMerchantOpened,
        bool opensCardReward,
        bool skipsCardReward,
        bool isRewardsProceed,
        ulong closedMapId)
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
                opensCardReward,
                skipsCardReward,
                isRewardsProceed,
                closedMapId,
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

        // Native room proceeds can open the map while leaving their button
        // active. Only attribute the transition if this exact map was closed
        // before input; nested treasure rooms may instead resume an event.
        if (pending.ClosedMapId != 0
            && NMapScreen.Instance is { } map
            && IsActive(map)
            && map.GetInstanceId() == pending.ClosedMapId
            && map.IsOpen
            && map.IsTravelEnabled
            && !map.IsTraveling
            && FindActiveChoiceScreen() is null
            && (GetTopOverlay(out var hasOverlay) is NMapScreen || !hasOverlay))
        {
            if (TryClaimPendingOutsideAction(pending))
            {
                CommitPendingOutsideAction(pending);
                OutsideCombatCaptureService.RecordExecution(
                    pending.Sample,
                    OutsideCombatExecutionStatus.ObservedTransition,
                    "room action opened the travel-enabled map");
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
        if (pending.OpensCardReward && RunManager.Instance.IsInProgress
            && RunManager.Instance.DebugOnlyGetState() is { } cardRewardRun)
        {
            _openCardRewardButtonId = pending.TargetId;
            _cardRewardRun = cardRewardRun;
            _cardRewardFloor = cardRewardRun.TotalFloor;
        }
        if (pending.SkipsCardReward && _openCardRewardButtonId != 0)
        {
            SkippedCardRewardButtons.Add(_openCardRewardButtonId);
            _openCardRewardButtonId = 0;
        }
        if (pending.IsRewardsProceed
            && !CombatManager.Instance.IsInProgress
            && RunManager.Instance.IsInProgress
            && RunManager.Instance.DebugOnlyGetState() is { } run)
        {
            _completedRewardsProceedSurfaceId = pending.SurfaceId;
            _completedRewardsProceedRun = run;
            _completedRewardsProceedFloor = run.TotalFloor;
        }

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

    private static void ClearCompletedRewardsProceed()
    {
        _completedRewardsProceedSurfaceId = 0;
        _completedRewardsProceedRun = null;
        _completedRewardsProceedFloor = 0;
    }

    private static void ClearSkippedCardRewards()
    {
        _openCardRewardButtonId = 0;
        SkippedCardRewardButtons.Clear();
        _cardRewardRun = null;
        _cardRewardFloor = 0;
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

            // The reward screen can remain visible in the overlay stack after
            // its proceed button has transitioned and the map is already open.
            // Only bypass that particular screen after our proceed was observed;
            // a new combat, run, or floor invalidates this permission.
            if (overlay is NRewardsScreen
                && overlay.GetInstanceId() == _completedRewardsProceedSurfaceId
                && _completedRewardsProceedRun is not null)
            {
                var activeChoice = FindActiveChoiceScreen();
                var openMap = NMapScreen.Instance;
                if ((activeChoice is null || ReferenceEquals(activeChoice, overlay))
                    && IsActive(openMap)
                    && openMap.IsOpen
                    && openMap.IsTravelEnabled
                    && !openMap.IsTraveling)
                {
                    return FindMapDecisions(openMap);
                }
            }

            // A completed reward/card overlay can remain visible during its
            // outro while the map is already open. Fall through only after a
            // known overlay is no longer visible; a visible known overlay with
            // temporarily disabled controls is still opening/animating and must
            // block clicks into the room beneath it. Unknown overlays always
            // block, visible or not.
            if (IsActive(overlay) || !IsKnownDecisionOverlay(overlay))
            {
                TraceWait($"overlay blocks map: {overlay.GetType().Name} "
                    + $"active={IsActive(overlay)} known={IsKnownDecisionOverlay(overlay)}");
                return [];
            }
        }

        // ScreenCount is authoritative even while Peek() is briefly null. In
        // that transition window, waiting is safer than clicking the room below.
        if (hasStackedScreen && overlay is null)
        {
            TraceWait("overlay stack nonempty but top is null");
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

            if (detachedChoice is NRewardsScreen
                && detachedChoice.GetInstanceId() == _completedRewardsProceedSurfaceId
                && _completedRewardsProceedRun is not null
                && NMapScreen.Instance is { } openMap
                && IsActive(openMap)
                && openMap.IsOpen
                && openMap.IsTravelEnabled
                && !openMap.IsTraveling)
            {
                // FindActiveChoiceScreen searches all other selector types
                // before rewards, so an active picker still takes precedence.
                return FindMapDecisions(openMap);
            }

            // FindActiveChoiceScreen only returns a visible live selector. No
            // actions here means it is still opening or between phases, not
            // that clicks may safely pass through to the room or map below.
            TraceWait($"detached choice blocks map: {detachedChoice.GetType().Name}");
            return [];
        }

        // The native merchant transaction owns the room until its deck picker
        // finishes. A picker can be mounted for a frame before its cards or
        // confirm button become actionable; never click the merchant or map
        // underneath during that window.
        if (_awaitingMerchantCardRemoval)
        {
            TraceWait("merchant card removal pending");
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
        if (IsActive(map) && map.IsOpen) return FindMapDecisions(map);
        TraceWait($"map unavailable: exists={map is not null} active={IsActive(map)} "
            + $"open={(IsActive(map) ? map.IsOpen : false)}");
        return [];
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
                .Where(button => button.Reward is not null && CanClaimReward(button)
                    && !SkippedCardRewardButtons.Contains(button.GetInstanceId())),
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
        // Native card reward buttons are generated in the order of _extraOptions.
        // Skip shares this button type with rerolls and relic alternatives.
        var nativeButtons = Descendants<NCardRewardAlternativeButton>(screen)
            .Where(button => !button.IsQueuedForDeletion()).ToArray();
        var nativeOptions = CardRewardExtraOptionsField?.GetValue(screen)
            as IReadOnlyList<CardRewardAlternative>;
        var skipButton = nativeOptions is not null && nativeOptions.Count == nativeButtons.Length
            ? nativeButtons.Zip(nativeOptions)
                .FirstOrDefault(pair => string.Equals(pair.Second.OptionId, "Skip", StringComparison.OrdinalIgnoreCase)).First
            : null;
        var alternatives = FromControls(
                screen,
                nativeButtons.Where(button => !ReferenceEquals(button, skipButton)),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.ChooseRewardAlternative,
                "card reward alternative",
                requireUnattempted: true)
            .Select(decision => decision with { CompletesSingleChoice = true });
        var skips = FromControls(
                screen,
                Enumerate(skipButton),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.Skip,
                "card reward skip",
                requireUnattempted: true)
            .Concat(FromControls(
                screen,
                Descendants<NChoiceSelectionSkipButton>(screen),
                OutsideCombatSurfaceKind.CardReward,
                OutsideCombatActionKind.Skip,
                "card reward skip"))
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
                    && (_plannedMerchantRemoval is null
                        || ReferenceEquals(candidate.Card, _plannedMerchantRemoval))
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
            if (_merchantPurchaseTask is not null || _awaitingMerchantCardRemoval)
                return [];
            var actions = new List<OutsideDecision>();
            var slots = inventory.GetAllSlots().ToArray();
            AddMerchantItems<NMerchantCard>(actions, room, inventory, slots, OutsideCombatActionKind.BuyCard);
            AddMerchantItems<NMerchantRelic>(actions, room, inventory, slots, OutsideCombatActionKind.BuyRelic);
            AddMerchantItems<NMerchantPotion>(actions, room, inventory, slots, OutsideCombatActionKind.BuyPotion);
            var removal = slots.OfType<NMerchantCardRemoval>().FirstOrDefault();
            if (removal is not null && removal.Entry.IsStocked && removal.Entry.EnoughGold
                && _merchantCardRemovalAttemptedInRoom != _surfaceId && IsUsable(removal.Hitbox))
            {
                var state = RunManager.Instance.DebugOnlyGetState();
                if (state?.Players.Count == 1)
                    foreach (var card in state.Players[0].Deck.Cards.Where(card => card.IsRemovable))
                        actions.Add(new OutsideDecision(room, removal.Hitbox,
                            OutsideCombatSurfaceKind.Merchant, OutsideCombatActionKind.OpenCardRemoval,
                            $"remove merchant card {card.Id.Entry}", TargetId: card.Id.ToString(),
                            Cost: removal.Entry.Cost, NativeCard: card, StartsMerchantCardRemoval: true,
                            MerchantCardRemoval: removal, MerchantInventory: inventory));
            }
            var back = inventory.GetNodeOrNull<NClickableControl>("%BackButton");
            var leave = FromControls(room, Enumerate(back), OutsideCombatSurfaceKind.Merchant,
                OutsideCombatActionKind.LeaveMerchant, "leave merchant", requireUnattempted: true);
            if (leave.Count == 0)
                leave = FromControls(room, Descendants<NBackButton>(inventory), OutsideCombatSurfaceKind.Merchant,
                    OutsideCombatActionKind.LeaveMerchant, "close merchant inventory", requireUnattempted: true);
            // If model inference cannot represent the shop, first-legal must
            // leave rather than spend gold on an arbitrary inventory item.
            actions.InsertRange(0, leave);
            return actions;

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

    private static void AddMerchantItems<T>(List<OutsideDecision> actions, NMerchantRoom room,
        NMerchantInventory inventory, NMerchantSlot[] slots, OutsideCombatActionKind kind)
        where T : NMerchantSlot
    {
        var typed = slots.OfType<T>().ToArray();
        for (var index = 0; index < typed.Length; index++)
        {
            var slot = typed[index];
            var entry = slot.Entry;
            if (!entry.IsStocked || !entry.EnoughGold || !IsUsable(slot.Hitbox)
                || AttemptedOnSurface.Contains(slot.Hitbox.GetInstanceId())) continue;
            if (kind == OutsideCombatActionKind.BuyPotion
                && (inventory.Inventory is null
                    || !inventory.Inventory.Player.PotionSlots.Any(p => p is null))) continue;
            var card = (entry as MerchantCardEntry)?.CreationResult?.Card;
            var id = entry switch
            {
                MerchantCardEntry c => c.CreationResult?.Card.Id.ToString(),
                MerchantRelicEntry r => r.Model?.Id.ToString(),
                MerchantPotionEntry p => p.Model?.Id.ToString(),
                _ => null,
            };
            if (id is null) continue;
            actions.Add(new OutsideDecision(room, slot.Hitbox, OutsideCombatSurfaceKind.Merchant,
                kind, $"buy merchant item {id}", TargetId: id, Cost: entry.Cost,
                NativeCard: card, MerchantInventory: inventory, MerchantItem: slot, ShopIndex: index));
        }
    }

    private static OutsideShopObservation CaptureShop(NMerchantRoom room, NMerchantInventory inventory)
    {
        var roomId = room.GetInstanceId();
        if (_merchantCacheRoom != roomId)
        {
            MerchantItemCache.Clear();
            _merchantCacheRoom = roomId;
        }
        var slots = inventory.GetAllSlots().ToArray();
        OutsideShopItem[] Items<T>() where T : NMerchantSlot => slots.OfType<T>().Select((slot, index) =>
        {
            var entry = slot.Entry;
            var card = (entry as MerchantCardEntry)?.CreationResult?.Card;
            var id = entry switch
            {
                MerchantCardEntry c => c.CreationResult?.Card.Id.ToString(),
                MerchantRelicEntry r => r.Model?.Id.ToString(),
                MerchantPotionEntry p => p.Model?.Id.ToString(),
                _ => null,
            };
            var key = slot.GetInstanceId();
            if (id is not null)
            {
                var item = new OutsideShopItem(index, id, entry.Cost, !entry.IsStocked, card?.CurrentUpgradeLevel);
                MerchantItemCache[key] = item;
                return item;
            }
            return MerchantItemCache.TryGetValue(key, out var previous)
                ? previous with { Sold = true }
                : new OutsideShopItem(index, null, Math.Max(0, entry.Cost), true);
        }).ToArray();
        var removal = slots.OfType<NMerchantCardRemoval>().FirstOrDefault();
        return new OutsideShopObservation(Items<NMerchantCard>(), Items<NMerchantRelic>(),
            Items<NMerchantPotion>(), removal?.Entry.Cost ?? 0, removal?.Entry.IsStocked ?? false);
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
        NMerchantInventory? MerchantInventory = null,
        NMerchantSlot? MerchantItem = null,
        int? ShopIndex = null)
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
                targetDeckIndex)
            {
                TargetUpgradeLevel = ActionKind is OutsideCombatActionKind.ChooseCard
                    or OutsideCombatActionKind.RemoveCard or OutsideCombatActionKind.BuyCard
                    or OutsideCombatActionKind.OpenCardRemoval
                        ? NativeCard?.CurrentUpgradeLevel : null,
                TargetShopIndex = ShopIndex,
            };
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
        bool OpensCardReward,
        bool SkipsCardReward,
        bool IsRewardsProceed,
        ulong ClosedMapId,
        long StartedAt);
}
