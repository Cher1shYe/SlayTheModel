using System.Text.Json;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Actions;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Potions;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.TreasureRooms;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed class NativeActionCapture(
    CollectorActionDraft draft,
    string description,
    long runtimeGeneration)
{
    private int _completed;
    private int _accepted;
    private int _nestedSelectorObserved;

    internal CollectorActionDraft Draft { get; } = draft;
    internal string Description { get; } = description;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal bool IsCompleted => Volatile.Read(ref _completed) != 0;
    internal bool IsAccepted => Volatile.Read(ref _accepted) != 0;
    internal bool NestedSelectorObserved =>
        Volatile.Read(ref _nestedSelectorObserved) != 0;
    internal void MarkAccepted() => Volatile.Write(ref _accepted, 1);
    internal void MarkNestedSelectorObserved() =>
        Volatile.Write(ref _nestedSelectorObserved, 1);
    internal bool TryMarkCompleted() => Interlocked.Exchange(ref _completed, 1) == 0;
}

internal sealed class PendingUnmatchedMerchantClick(
    MerchantEntry selectedEntry,
    MerchantInventory inventory,
    RunState runState,
    string beforeState,
    MerchantEntryEvidence selectedEntryEvidence,
    bool stableAtClick,
    long runtimeGeneration)
{
    private int _completed;

    internal MerchantEntry SelectedEntry { get; } = selectedEntry;
    internal MerchantInventory Inventory { get; } = inventory;
    internal RunState RunState { get; } = runState;
    internal string BeforeState { get; } = beforeState;
    internal MerchantEntryEvidence SelectedEntryEvidence { get; } = selectedEntryEvidence;
    internal bool StableAtClick { get; } = stableAtClick;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal bool TryMarkCompleted() => Interlocked.Exchange(ref _completed, 1) == 0;
}

internal sealed record PendingCardSelection(
    PreparedOutsideDecision Prepared,
    IReadOnlyList<CardModel> Options,
    int? CancelOrdinal,
    string Description,
    long RuntimeGeneration)
{
    internal Task<IEnumerable<CardModel>>? CompletionTask { get; set; }
}

internal sealed record PendingRelicSelection(
    PreparedOutsideDecision Prepared,
    IReadOnlyList<RelicModel> Options,
    int? SkipOrdinal,
    string Description,
    long RuntimeGeneration)
{
    internal Task<IEnumerable<RelicModel>>? CompletionTask { get; set; }
}

internal sealed record PendingCardRewardSelection(
    PreparedOutsideDecision Prepared,
    IReadOnlyList<CardModel> Options,
    IReadOnlyList<CardRewardExtraOption> ExtraOptions,
    string Description,
    long RuntimeGeneration)
{
    internal Task<int?>? CompletionTask { get; set; }
}

internal sealed record CardRewardExtraOption(string OptionId, bool IsSkip);

/// <summary>
/// Main-thread bridge from STS2 semantic inputs to the game-independent
/// episode journal. It observes but never enqueues actions or clicks UI nodes.
/// </summary>
internal static partial class CollectorRuntime
{
    private static readonly Dictionary<GameAction, CollectorActionDraft> PendingCombatActions = [];
    private static readonly Dictionary<GameAction, CollectorActionDraft> PendingOutsidePotionActions = [];
    private static readonly HashSet<object> PendingOutsideOperations =
        new(ReferenceEqualityComparer.Instance);
    private static CollectorConfiguration? _configuration;
    private static CollectorEpisodeCoordinator? _episodes;
    private static RunStartEvidence? _preparedRun;
    private static ActionQueueSet? _actionQueue;
    private static ActionExecutor? _actionExecutor;
    private static PlayerChoiceSynchronizer? _choiceSynchronizer;
    private static CardReward? _activeCardReward;
    private static PendingCardRewardSelection? _pendingCardRewardSelection;
    private static Guid? _combatId;
    private static CombatState? _activeCombatState;
    private static bool _merchantRemovalSelectionPending;
    private static NativeActionCapture? _merchantRemovalParent;
    private static RunHistory? _pendingRunHistory;
    private static bool _initialized;
    private static bool _stopping;
    private static long _runGeneration;
    private static bool _drainingSelectors;

    internal static void Initialize(CollectorConfiguration configuration)
    {
        if (_initialized)
        {
            return;
        }

        _initialized = true;
        _configuration = configuration;
        _episodes = new CollectorEpisodeCoordinator(configuration);
        CollectorHarmony.Install();
        CollectorManualCombatInput.Install();
        CollectorPolicyTelemetry.Install();

        var runManager = RunManager.Instance;
        runManager.RunStarted += OnRunStarted;
        var combatManager = CombatManager.Instance;
        combatManager.CombatBegan += OnCombatBegan;
        combatManager.CombatWon += OnActRewardCombatWon;
        combatManager.CombatEnded += OnCombatEnded;
        combatManager.StateTracker.CombatStateChanged += OnCombatStateChanged;

        Callable.From(() =>
        {
            if (Engine.GetMainLoop() is SceneTree tree)
            {
                tree.Root.TreeExiting += OnTreeExiting;
            }
        }).CallDeferred();

        Console.WriteLine(
            $"[SlayTheModel/Collector] enabled dataset={configuration.DatasetRoot} "
            + $"information_mode={configuration.InformationMode.ToString().ToLowerInvariant()} "
            + $"actor={configuration.Actor} upload=false");
    }

    internal static void PrepareNewRun(RunState state, DateTimeOffset? dailyTime)
    {
        DrainCompletedSelectors();
        ResetActRewardCapture();
        // The native argument is the daily-run date, not SerializableRun's
        // unique start timestamp. OnRunStarted reads the latter after setup.
        _preparedRun = new RunStartEvidence(
            state,
            false,
            StartTime: null,
            0,
            NativeSaveFingerprint: null,
            NewRunObserved: true);
    }

    internal static void PrepareLoadedRun(RunState state, SerializableRun save)
    {
        DrainCompletedSelectors();
        ResetActRewardCapture();
        _preparedRun = new RunStartEvidence(
            state,
            true,
            save.StartTime,
            save.NumReloads,
            CollectorEpisodeCoordinator.TryFingerprintNativeSave(save),
            NewRunObserved: false);
    }

    internal static NativeSaveCheckpoint? PrepareNativeSaveCheckpoint(
        SerializableRun save)
    {
        try
        {
            DrainCompletedSelectors();
            if (HasPendingSelector())
            {
                RecordDiagnostic(
                    "native_save_checkpoint_skipped_for_pending_selector",
                    new { pending_selector_count = PendingSelectorCount() });
                return null;
            }

            // A native save may run before map travel advances the floor.
            // Mark accepted parents, then let the coordinator settle only if
            // the live metrics match the save and the action is finished.
            CompleteAcceptedParentActions("native_save");
            return _episodes?.PrepareNativeSaveCheckpoint(
                save,
                RunManager.Instance.ActionExecutor.IsRunning);
        }
        catch (Exception exception)
        {
            RecordDiagnostic(
                "native_save_checkpoint_prepare_failed",
                new { error = exception.ToString() });
            return null;
        }
    }

    internal static void CompleteNativeSaveCheckpoint(
        NativeSaveCheckpoint? checkpoint,
        Exception? exception = null)
    {
        if (checkpoint is null)
        {
            return;
        }

        if (exception is not null)
        {
            RecordDiagnostic(
                "native_save_failed",
                new { error = exception.ToString() });
            return;
        }

        try
        {
            _episodes?.CommitNativeSaveCheckpoint(checkpoint);
        }
        catch (Exception checkpointError)
        {
            RecordDiagnostic(
                "native_save_checkpoint_commit_failed",
                new { error = checkpointError.ToString() });
        }
    }

    internal static void FinishRun(RunHistory history)
    {
        CaptureActRewardTerminalBoundary(history);
        // SaveRunHistory can run inside the terminal GameAction, before
        // ActionExecutor emits AfterActionExecuted. Keep the episode open
        // until that final observed action has been committed.
        DrainCompletedSelectors();
        _pendingRunHistory = history;
        CompleteKnownAcceptedActions("run_finished");
        if (HasPendingOperations())
        {
            return;
        }

        FinishPendingRun();
    }

    private static void FinishPendingRun()
    {
        var history = _pendingRunHistory;
        if (history is null || HasPendingOperations())
        {
            return;
        }

        _pendingRunHistory = null;
        try
        {
            _episodes?.Finish(history);
        }
        catch (Exception exception)
        {
            DisableAfterFailure("finish run", exception);
        }
        finally
        {
            DetachRunInputs();
        }
    }

    internal static NativeActionCapture? CaptureEventChoice(
        EventSynchronizer synchronizer,
        int selectedIndex)
    {
        return CaptureOutside(
            "event_option",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForEvent(
                    state,
                    synchronizer,
                    selectedIndex,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static NativeActionCapture? CaptureRestSiteChoice(
        RestSiteSynchronizer synchronizer,
        int selectedIndex)
    {
        return CaptureOutside(
            "rest_site_option",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForRestSite(
                    state,
                    synchronizer,
                    selectedIndex,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static NativeActionCapture? CaptureMapChoice(
        Player player,
        MapVote? vote)
    {
        if (vote is not { } selected
            || !IsLocalSinglePlayer(player))
        {
            return null;
        }

        return CaptureOutside(
            "map_travel",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForMap(
                    state,
                    selected.coord,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static NativeActionCapture? CaptureTreasureChoice(
        TreasureRoomRelicSynchronizer synchronizer,
        int? selectedIndex)
    {
        return CaptureOutside(
            "treasure_relic",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForTreasureRelic(
                    state,
                    synchronizer,
                    selectedIndex,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static object? CaptureMerchantChoice(
        MerchantEntry selectedEntry,
        MegaCrit.Sts2.Core.Entities.Merchant.MerchantInventory inventory)
    {
        try
        {
            if (!CollectorOutsideProjector.IsLegalMerchantEntry(inventory, selectedEntry))
            {
                return CaptureUnmatchedMerchantClick(selectedEntry, inventory);
            }
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "merchant_entry_legality_check_failed",
                new { error = exception.ToString() },
                invalidatePendingDecision: false);
            return null;
        }

        var capture = CaptureOutside(
            "merchant_purchase",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForMerchant(
                    state,
                    inventory,
                    selectedEntry,
                    sourceIndex,
                    out var selectedOrdinal,
                    includePotionActions: CanExposeMerchantPotionActions(state, inventory));
                return (decision, selectedOrdinal);
            });
        if (capture is not null && selectedEntry is MerchantCardRemovalEntry)
        {
            _merchantRemovalSelectionPending = true;
            _merchantRemovalParent = capture;
        }

        return capture;
    }

    private static PendingUnmatchedMerchantClick? CaptureUnmatchedMerchantClick(
        MerchantEntry selectedEntry,
        MerchantInventory inventory)
    {
        try
        {
            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress
                || CombatManager.Instance.IsInProgress
                || RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1)
            {
                return null;
            }

            DrainCompletedSelectors();
            var pendingOperations = PendingOutsideOperations.ToArray();
            var acceptedParents = pendingOperations
                .OfType<NativeActionCapture>()
                .Where(capture => capture.IsAccepted
                                  && !capture.IsCompleted
                                  && capture.RuntimeGeneration == _runGeneration)
                .ToArray();
            var episodeSnapshot = _episodes.Snapshot;
            var uniquelyAcceptedParent = pendingOperations.Length == 1
                                         && acceptedParents.Length == 1
                                         && episodeSnapshot.PendingDecisions is { Count: 1 } decisions
                                         && decisions[0].DecisionId
                                             == acceptedParents[0].Draft.Receipt.DecisionId
                                         && decisions[0].Phase == EpisodePhase.AwaitingExecution;
            var priorOperationProven = pendingOperations.Length == 0
                                       || uniquelyAcceptedParent;
            var nativeBoundaryStable = priorOperationProven
                                       && !HasPendingSelector()
                                       && PendingOutsidePotionActions.Count == 0
                                       && PendingCombatActions.Count == 0
                                       && PendingManualCombatIntents.Count == 0
                                       && PendingCrystalSphereCellTasks.Count == 0
                                       && !RunManager.Instance.ActionExecutor.IsRunning
                                       && RunManager.Instance.ActionQueueSet.IsEmpty;
            if (nativeBoundaryStable && uniquelyAcceptedParent)
            {
                CompleteAcceptedParentActions("merchant_rejected_click");
            }

            if (nativeBoundaryStable)
            {
                _episodes.ResolveAtCurrentBoundary();
            }

            var stableAtClick = nativeBoundaryStable
                                && PendingOutsideOperations.Count == 0
                                && _episodes.Snapshot.PendingDecisionCount == 0;
            var pending = new PendingUnmatchedMerchantClick(
                selectedEntry,
                inventory,
                state,
                MerchantStateSnapshot(state, inventory, selectedEntry),
                CollectorOutsideProjector.DescribeMerchantEntry(selectedEntry),
                stableAtClick,
                _runGeneration);
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "merchant_unmatched_click_capture_failed",
                new { error = exception.ToString() },
                invalidatePendingDecision: false);
            return null;
        }
    }

    internal static void CompleteUnmatchedMerchantClick(
        PendingUnmatchedMerchantClick? pending,
        Task<bool>? nativeTask,
        Exception? nativeException = null)
    {
        if (pending is null || !pending.TryMarkCompleted())
        {
            return;
        }

        try
        {
            if (pending.RuntimeGeneration != _runGeneration
                || !PendingOutsideOperations.Contains(pending))
            {
                return;
            }

            string? afterState = null;
            string? snapshotError = null;
            try
            {
                if (RunManager.Instance.IsInProgress
                    && ReferenceEquals(
                        RunManager.Instance.DebugOnlyGetState(), pending.RunState))
                {
                    afterState = MerchantStateSnapshot(
                        pending.RunState, pending.Inventory, pending.SelectedEntry);
                }
            }
            catch (Exception exception)
            {
                snapshotError = exception.ToString();
            }

            var taskReturnedFalse = nativeException is null
                                    && nativeTask is { Status: TaskStatus.RanToCompletion,
                                        Result: false };
            var noOtherOperation = PendingOutsideOperations.Count == 1
                                   && !HasPendingSelector()
                                   && PendingOutsidePotionActions.Count == 0
                                   && PendingCombatActions.Count == 0
                                   && PendingManualCombatIntents.Count == 0
                                   && PendingCrystalSphereCellTasks.Count == 0
                                   && !RunManager.Instance.ActionExecutor.IsRunning
                                   && RunManager.Instance.ActionQueueSet.IsEmpty
                                   && _episodes?.Snapshot.PendingDecisionCount == 0;
            var unchanged = afterState is not null
                            && StringComparer.Ordinal.Equals(
                                pending.BeforeState, afterState);
            var evidence = new
            {
                selected_entry = pending.SelectedEntryEvidence,
                selected_in_inventory = pending.Inventory.AllEntries.Any(entry =>
                    ReferenceEquals(entry, pending.SelectedEntry)),
                native_task_status = nativeTask?.Status.ToString(),
                native_result = nativeTask is { Status: TaskStatus.RanToCompletion }
                    ? nativeTask.Result
                    : (bool?)null,
                native_error = nativeException?.ToString()
                               ?? nativeTask?.Exception?.GetBaseException().ToString(),
                pending.StableAtClick,
                no_other_operation = noOtherOperation,
                state_unchanged = unchanged,
                snapshot_error = snapshotError,
            };
            if (taskReturnedFalse && pending.StableAtClick
                && noOtherOperation && unchanged)
            {
                RecordDiagnostic("merchant_native_rejected_unavailable_click", evidence);
            }
            else
            {
                RecordCoverageGap(
                    "merchant_unmatched_click_unverified",
                    evidence,
                    invalidatePendingDecision: false);
            }
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "merchant_unmatched_click_audit_failed",
                new { error = exception.ToString() },
                invalidatePendingDecision: false);
        }
        finally
        {
            PendingOutsideOperations.Remove(pending);
            FinishPendingRun();
        }
    }

    private static string MerchantStateSnapshot(
        RunState state,
        MerchantInventory inventory,
        MerchantEntry selectedEntry) =>
        JsonSerializer.Serialize(new
        {
            run_context = CollectorRunContextProjector.Capture(state),
            merchant_entries = inventory.AllEntries.Select((entry, index) => new
            {
                index,
                selected = ReferenceEquals(entry, selectedEntry),
                entry = CollectorOutsideProjector.DescribeMerchantEntry(entry),
            }).ToArray(),
            selected_entry = CollectorOutsideProjector.DescribeMerchantEntry(selectedEntry),
        }, ProtocolJson.Options);

    internal static NativeActionCapture? CaptureMerchantLeave(
        NMerchantInventory inventoryScreen)
    {
        if (inventoryScreen.Inventory is not { } inventory)
        {
            return null;
        }

        return CaptureOutside(
            "merchant_leave",
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForMerchant(
                    state,
                    inventory,
                    selectedEntry: null,
                    sourceIndex,
                    out var selectedOrdinal,
                    includePotionActions: CanExposeMerchantPotionActions(state, inventory));
                return (decision, selectedOrdinal);
            });
    }

    internal static NativeActionCapture? CaptureRewardChoice(Reward selectedReward)
    {
        var capture = CaptureOutside(
            "reward_claim",
            (state, sourceIndex) =>
            {
                var topRewards = TryGetInteractableTopRewards(state);
                if (topRewards is null && HasPotentialOutsidePotionAction(state))
                {
                    throw new InvalidOperationException(
                        "Rewards potion belt could not be verified at reward click.");
                }

                var legal = topRewards is null
                    ? FindVisibleRewards()
                    : FindVisibleRewards(topRewards);
                if (!legal.Contains(selectedReward, ReferenceEqualityComparer.Instance))
                {
                    legal = [.. legal, selectedReward];
                }

                var decision = CollectorOutsideProjector.ForReward(
                    state,
                    legal,
                    selectedReward,
                    CanProceedRewards(topRewards),
                    sourceIndex,
                    out var selectedOrdinal,
                    includePotionActions: topRewards is not null);
                return (decision, selectedOrdinal);
            });
        if (capture is not null && selectedReward is CardReward cardReward)
        {
            // CaptureOutside first drains any selector that completed on the
            // preceding reward. Install this parent only afterwards so that
            // the old selector's cleanup cannot erase the new reward context.
            _activeCardReward = cardReward;
        }

        return capture;
    }

    internal static NativeActionCapture? CaptureRewardsProceed(NRewardsScreen screen)
    {
        return CaptureOutside(
            "rewards_proceed",
            (state, sourceIndex) =>
            {
                var topRewards = TryGetInteractableTopRewards(state, screen);
                if (topRewards is null && HasPotentialOutsidePotionAction(state))
                {
                    throw new InvalidOperationException(
                        "Rewards potion belt could not be verified at Proceed click.");
                }

                var decision = CollectorOutsideProjector.ForReward(
                    state,
                    topRewards is null
                        ? FindVisibleRewards()
                        : FindVisibleRewards(topRewards),
                    selectedReward: null,
                    canProceed: true,
                    sourceIndex,
                    out var selectedOrdinal,
                    includePotionActions: topRewards is not null);
                return (decision, selectedOrdinal);
            });
    }

    internal static NativeActionCapture? CaptureTreasureRoomAction(
        NTreasureRoom room,
        OutsideCombatActionKind selectedKind)
    {
        return CaptureOutside(
            selectedKind == OutsideCombatActionKind.OpenChest
                ? "treasure_open_chest"
                : "treasure_proceed",
            (state, sourceIndex) =>
            {
                var canOpenChest = Descendants<NTreasureButton>(room)
                    .Any(button => button.IsEnabled && button.IsVisibleInTree());
                var canProceed = room.ProceedButton is { IsEnabled: true } proceed
                                 && proceed.IsVisibleInTree();
                // The prefix itself is authoritative even if native focus
                // state changed in the same input callback.
                canOpenChest |= selectedKind == OutsideCombatActionKind.OpenChest;
                canProceed |= selectedKind == OutsideCombatActionKind.Proceed;
                var decision = CollectorOutsideProjector.ForTreasureRoom(
                    state,
                    canOpenChest,
                    canProceed,
                    selectedKind,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static PendingCardRewardSelection? PrepareCardRewardSelection(
        IReadOnlyList<CardModel>? nativeOptions,
        IReadOnlyList<CardRewardExtraOption>? extraOptions)
    {
        try
        {
            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress)
            {
                return null;
            }

            // A native selector Task can complete immediately before another
            // selector is opened. Close its label before any early-return gap
            // below, otherwise the new gap could invalidate the old decision.
            DrainCompletedSelectors();
            var active = _activeCardReward;
            if (CombatManager.Instance.IsInProgress)
            {
                RecordCoverageGap(
                    "combat_card_reward_selection_not_supported",
                    new { extra_option_count = extraOptions?.Count },
                    invalidatePendingDecision: false);
                return null;
            }
            if (active is null)
            {
                RecordCoverageGap(
                    "card_reward_parent_unavailable",
                    new { extra_option_count = extraOptions?.Count });
                return null;
            }
            if (RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1)
            {
                RecordCoverageGap(
                    "card_reward_run_state_unavailable",
                    new { extra_option_count = extraOptions?.Count });
                return null;
            }

            // CardReward.OnSelect awaits this screen. Its opening proves the
            // parent reward_claim was accepted; the Task<int?> result is the
            // actual human card-or-skip label.
            CompleteAcceptedParentActions(
                "card_reward_selection",
                nestedSelectorObserved: true);
            _episodes.ResolveAtCurrentBoundary();
            if (extraOptions is null
                || nativeOptions is null
                || extraOptions.Any(option => string.IsNullOrWhiteSpace(option.OptionId)))
            {
                _activeCardReward = null;
                RecordCoverageGap(
                    "card_reward_native_options_unavailable",
                    new
                    {
                        native_option_count = nativeOptions?.Count,
                        extra_option_count = extraOptions?.Count,
                    });
                return null;
            }

            var cards = active.Cards?.ToArray() ?? [];
            if (cards.Length == 0)
            {
                _activeCardReward = null;
                RecordCoverageGap(
                    "card_reward_options_unavailable",
                    new { extra_option_count = extraOptions.Count });
                return null;
            }
            if (nativeOptions.Count != cards.Length
                || cards.Where((card, index) =>
                    !ReferenceEquals(card, nativeOptions[index])).Any())
            {
                _activeCardReward = null;
                RecordCoverageGap(
                    "card_reward_screen_options_mismatch",
                    new
                    {
                        reward_option_count = cards.Length,
                        native_option_count = nativeOptions.Count,
                    });
                return null;
            }

            var decision = CollectorOutsideProjector.ForCardRewardChoice(
                state,
                cards,
                extraOptions,
                _episodes.NextSourceDecisionIndex());
            var pending = new PendingCardRewardSelection(
                _episodes.PrepareOutside(decision, "card_reward_selection"),
                cards,
                extraOptions.ToArray(),
                "card_reward_selection",
                _runGeneration);
            _pendingCardRewardSelection = pending;
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            _activeCardReward = null;
            RecordCoverageGap(
                "card_reward_selection_prepare_failed",
                new { error = exception.ToString() });
            return null;
        }
    }

    internal static void CompleteCardRewardSelection(
        PendingCardRewardSelection? pending,
        int? selectedIndex,
        Exception? exception = null)
    {
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !ReferenceEquals(_pendingCardRewardSelection, pending)
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        try
        {
            if (exception is not null)
            {
                RecordCoverageGap(
                    "card_reward_selection_failed",
                    new { error = exception.ToString() });
                return;
            }

            var ordinal = selectedIndex is { } index
                          && index >= 0
                          && index < pending.Options.Count + pending.ExtraOptions.Count
                ? index
                : -1;
            if (ordinal < 0)
            {
                RecordCoverageGap(
                    "card_reward_result_unmatched",
                    new
                    {
                        selectedIndex,
                        option_count = pending.Options.Count,
                        extra_option_count = pending.ExtraOptions.Count,
                    });
                return;
            }

            if (ordinal >= pending.Options.Count
                && !pending.ExtraOptions[ordinal - pending.Options.Count].IsSkip)
            {
                RecordCoverageGap(
                    "card_reward_alternative_not_supported",
                    new
                    {
                        selectedIndex,
                        option_id = pending.ExtraOptions[
                            ordinal - pending.Options.Count].OptionId,
                    });
                return;
            }

            var draft = _episodes?.ResolveOutside(pending.Prepared, ordinal);
            if (draft is not null)
            {
                var capture = new NativeActionCapture(
                    draft,
                    pending.Description,
                    _runGeneration);
                PendingOutsideOperations.Add(capture);
                MarkNativeActionAccepted(capture);
            }
        }
        finally
        {
            _activeCardReward = null;
            _pendingCardRewardSelection = null;
            CompletePendingOutsideOperation(pending);
        }
    }

    internal static void CaptureCardRewardAlternative(int alternativeIndex)
    {
        var pending = _pendingCardRewardSelection;
        if (pending is null || pending.RuntimeGeneration != _runGeneration)
        {
            return;
        }

        if (alternativeIndex >= 0
            && alternativeIndex < pending.ExtraOptions.Count
            && pending.ExtraOptions[alternativeIndex].IsSkip)
        {
            // Native Skip is an extra option, not a card index. The selector
            // task reports cards.Count + alternativeIndex after this callback.
            return;
        }

        // Rerolls and other alternatives can replace the visible card set.
        // Keep the legal action in the observation, but mark its unstructured
        // transition as a gap instead of labeling a later card against it.
        _pendingCardRewardSelection = null;
        _activeCardReward = null;
        RecordCoverageGap(
            "card_reward_alternative_not_supported",
            new
            {
                alternative_index = alternativeIndex,
                option_id = alternativeIndex >= 0
                            && alternativeIndex < pending.ExtraOptions.Count
                    ? pending.ExtraOptions[alternativeIndex].OptionId
                    : null,
            });
        CompletePendingOutsideOperation(pending);
    }

    internal static NativeActionCapture? CaptureGenericCardChoice(
        IReadOnlyList<CardModel> cards,
        CardModel? selectedCard,
        bool canSkip,
        string contextId)
    {
        return CaptureOutside(
            contextId,
            (state, sourceIndex) =>
            {
                var decision = CollectorOutsideProjector.ForCardChoice(
                    state,
                    cards,
                    selectedCard,
                    canSkip,
                    OutsideCombatSurfaceKind.CardGridChoice,
                    contextId,
                    sourceIndex,
                    out var selectedOrdinal);
                return (decision, selectedOrdinal);
            });
    }

    internal static PendingCardSelection? PrepareCardSelection(
        IReadOnlyList<CardModel> cards,
        int minSelections,
        int maxSelections,
        bool requiresConfirmation,
        bool cancelable,
        bool removalSelection,
        string contextId)
    {
        try
        {
            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress)
            {
                return null;
            }

            DrainCompletedSelectors();
            if (CombatManager.Instance.IsInProgress)
            {
                RecordCoverageGap(
                    "combat_nested_card_selection_not_supported",
                    new { contextId, option_count = cards.Count },
                    invalidatePendingDecision: false);
                return null;
            }
            if (RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1
                || cards.Count == 0)
            {
                CompleteAcceptedParentActions(
                    contextId, nestedSelectorObserved: true);
                _episodes.ResolveAtCurrentBoundary();
                RecordCoverageGap(
                    "card_selection_options_unavailable",
                    new { contextId, option_count = cards.Count },
                    invalidatePendingDecision: false);
                return null;
            }

            var inheritedMerchantRemoval = _merchantRemovalSelectionPending;
            if (inheritedMerchantRemoval)
            {
                _merchantRemovalSelectionPending = false;
                _merchantRemovalParent = null;
            }
            var merchantRemoval = inheritedMerchantRemoval;
            removalSelection |= merchantRemoval;
            CompleteAcceptedParentActions(
                contextId,
                nestedSelectorObserved: true);
            if (minSelections is < 0 or > 1
                || maxSelections != 1
                || minSelections > maxSelections)
            {
                _episodes.ResolveAtCurrentBoundary();
                RecordCoverageGap(
                    "unsupported_multi_card_selection",
                    new
                    {
                        contextId,
                        min_selections = minSelections,
                        max_selections = maxSelections,
                        requires_confirmation = requiresConfirmation,
                    },
                    invalidatePendingDecision: false);
                return null;
            }

            var decision = CollectorOutsideProjector.ForCardGridChoice(
                state,
                cards,
                cancelable,
                removalSelection,
                merchantRemoval,
                minSelections,
                maxSelections,
                requiresConfirmation,
                contextId,
                _episodes.NextSourceDecisionIndex());
            var audit = JsonSerializer.SerializeToElement(
                new
                {
                    during_combat = CombatManager.Instance.IsInProgress,
                    combat_id = _combatId,
                    parent_action_id = RunManager.Instance.ActionExecutor
                        .CurrentlyRunningAction?.Id,
                });
            var prepared = _episodes.PrepareOutside(decision, contextId, audit);
            var pending = new PendingCardSelection(
                prepared,
                cards.ToArray(),
                cancelable ? decision.LegalActions.Count - 1 : null,
                contextId,
                _runGeneration);
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "card_selection_prepare_failed",
                new { contextId, error = exception.ToString() });
            return null;
        }
    }

    internal static PendingCardSelection? PrepareSingleCardSelection(
        IReadOnlyList<CardModel> cards,
        bool canSkip,
        string contextId)
    {
        try
        {
            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress)
            {
                return null;
            }

            DrainCompletedSelectors();
            if (CombatManager.Instance.IsInProgress)
            {
                RecordCoverageGap(
                    "combat_nested_single_card_selection_not_supported",
                    new { contextId, option_count = cards.Count },
                    invalidatePendingDecision: false);
                return null;
            }
            if (RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1
                || cards.Count == 0)
            {
                CompleteAcceptedParentActions(
                    contextId, nestedSelectorObserved: true);
                _episodes.ResolveAtCurrentBoundary();
                RecordCoverageGap(
                    "single_card_selection_options_unavailable",
                    new { contextId, option_count = cards.Count },
                    invalidatePendingDecision: false);
                return null;
            }

            CompleteAcceptedParentActions(
                contextId,
                nestedSelectorObserved: true);
            var decision = CollectorOutsideProjector.ForCardChoice(
                state,
                cards,
                selectedCard: null,
                canSkip,
                OutsideCombatSurfaceKind.CardChoice,
                contextId,
                _episodes.NextSourceDecisionIndex(),
                out _);
            var audit = JsonSerializer.SerializeToElement(
                new
                {
                    during_combat = CombatManager.Instance.IsInProgress,
                    combat_id = _combatId,
                    parent_action_id = RunManager.Instance.ActionExecutor
                        .CurrentlyRunningAction?.Id,
                });
            var pending = new PendingCardSelection(
                _episodes.PrepareOutside(decision, contextId, audit),
                cards.ToArray(),
                canSkip ? decision.LegalActions.Count - 1 : null,
                contextId,
                _runGeneration);
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "single_card_selection_prepare_failed",
                new { contextId, error = exception.ToString() });
            return null;
        }
    }

    internal static void CompleteCardSelection(
        PendingCardSelection? pending,
        IReadOnlyList<CardModel>? selected,
        Exception? exception = null)
    {
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        try
        {
            if (exception is not null)
            {
                RecordCoverageGap(
                    "card_selection_failed",
                    new { pending.Description, error = exception.ToString() });
                return;
            }

            var chosen = selected ?? [];
            int ordinal;
            if (chosen.Count == 0 && pending.CancelOrdinal is { } cancelOrdinal)
            {
                ordinal = cancelOrdinal;
            }
            else if (chosen.Count == 1)
            {
                ordinal = IndexOfReferenceOrIdentity(pending.Options, chosen[0]);
            }
            else
            {
                RecordCoverageGap(
                    "unsupported_multi_card_selection",
                    new { pending.Description, selected_count = chosen.Count });
                return;
            }

            if (ordinal < 0)
            {
                RecordCoverageGap(
                    "card_selection_result_unmatched",
                    new
                    {
                        pending.Description,
                        selected = chosen.Select(card => card.Id.ToString()).ToArray(),
                    });
                return;
            }

            var draft = _episodes?.ResolveOutside(pending.Prepared, ordinal);
            if (draft is not null)
            {
                var capture = new NativeActionCapture(
                    draft,
                    pending.Description,
                    _runGeneration);
                PendingOutsideOperations.Add(capture);
                MarkNativeActionAccepted(capture);
            }
        }
        finally
        {
            CompletePendingOutsideOperation(pending);
        }
    }

    internal static PendingRelicSelection? PrepareRelicSelection(
        IReadOnlyList<RelicModel> relics,
        bool canSkip,
        string contextId)
    {
        try
        {
            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress)
            {
                return null;
            }

            DrainCompletedSelectors();
            if (CombatManager.Instance.IsInProgress)
            {
                RecordCoverageGap(
                    "combat_nested_relic_selection_not_supported",
                    new { contextId, option_count = relics.Count },
                    invalidatePendingDecision: false);
                return null;
            }
            if (RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1
                || relics.Count == 0)
            {
                RecordCoverageGap(
                    "relic_selection_options_unavailable",
                    new { contextId, option_count = relics.Count });
                return null;
            }

            CompleteAcceptedParentActions(
                contextId,
                nestedSelectorObserved: true);
            var decision = CollectorOutsideProjector.ForRelicChoice(
                state,
                relics,
                canSkip,
                contextId,
                _episodes.NextSourceDecisionIndex());
            var pending = new PendingRelicSelection(
                _episodes.PrepareOutside(decision, contextId),
                relics.ToArray(),
                canSkip ? decision.LegalActions.Count - 1 : null,
                contextId,
                _runGeneration);
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "relic_selection_prepare_failed",
                new { contextId, error = exception.ToString() });
            return null;
        }
    }

    internal static void CompleteRelicSelection(
        PendingRelicSelection? pending,
        IReadOnlyList<RelicModel>? selected,
        Exception? exception = null)
    {
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        try
        {
            if (exception is not null)
            {
                RecordCoverageGap(
                    "relic_selection_failed",
                    new { pending.Description, error = exception.ToString() });
                return;
            }

            var chosen = selected ?? [];
            var ordinal = chosen.Count switch
            {
                0 when pending.SkipOrdinal is { } skip => skip,
                1 => IndexOfReferenceOrIdentity(pending.Options, chosen[0]),
                _ => -1,
            };
            if (ordinal < 0)
            {
                RecordCoverageGap(
                    "relic_selection_result_unmatched",
                    new { pending.Description, selected_count = chosen.Count });
                return;
            }

            var draft = _episodes?.ResolveOutside(pending.Prepared, ordinal);
            if (draft is not null)
            {
                var capture = new NativeActionCapture(
                    draft,
                    pending.Description,
                    _runGeneration);
                PendingOutsideOperations.Add(capture);
                MarkNativeActionAccepted(capture);
            }
        }
        finally
        {
            CompletePendingOutsideOperation(pending);
        }
    }

    internal static void CompleteNativeAction(
        NativeActionCapture? capture,
        Exception? exception = null,
        string? detail = null)
        => CompleteNativeAction(
            capture,
            exception is null
                ? CollectorExecutionStatus.Applied
                : CollectorExecutionStatus.Failed,
            detail ?? exception?.Message);

    internal static void CompleteNativeAction(
        NativeActionCapture? capture,
        CollectorExecutionStatus status,
        string? detail = null)
    {
        if (!IsCurrentCapture(capture) || !capture!.TryMarkCompleted())
        {
            return;
        }

        if (ReferenceEquals(_merchantRemovalParent, capture))
        {
            _merchantRemovalParent = null;
            _merchantRemovalSelectionPending = false;
        }

        try
        {
            _episodes?.Commit(
                capture.Draft,
                status,
                detail);
        }
        catch (Exception collectorError)
        {
            DisableAfterFailure($"commit {capture.Description}", collectorError);
        }
        finally
        {
            CompletePendingOutsideOperation(capture);
        }
    }

    internal static bool IsCurrentCapture(NativeActionCapture? capture) =>
        capture is not null && capture.RuntimeGeneration == _runGeneration;

    internal static void MarkNativeActionAccepted(NativeActionCapture? capture)
    {
        if (!IsCurrentCapture(capture) || capture!.IsCompleted)
        {
            return;
        }

        capture.MarkAccepted();
        if (_pendingRunHistory is not null)
        {
            CompleteNativeAction(
                capture,
                CollectorExecutionStatus.ObservedTransition,
                "native operation completed at run finish boundary");
        }
    }

    internal static void RecordDiagnostic(string code, object data)
    {
        try
        {
            _episodes?.RecordDiagnostic(code, data);
        }
        catch (Exception exception)
        {
            DisableAfterFailure($"diagnostic {code}", exception);
        }
    }

    internal static bool FailStagedAcceptedAction(
        NativeActionCapture capture,
        string detail)
    {
        try
        {
            return IsCurrentCapture(capture)
                   && _episodes?.FailStagedExecution(capture.Draft, detail) == true;
        }
        catch (Exception exception)
        {
            DisableAfterFailure("late accepted-parent failure", exception);
            return false;
        }
    }

    internal static void RecordCoverageGap(
        string reason,
        object data,
        bool invalidatePendingDecision = true,
        Guid? relatedDecisionId = null,
        Guid? relatedAttemptId = null,
        Guid? targetDecisionId = null)
    {
        try
        {
            _episodes?.RecordCoverageGap(
                reason,
                data,
                invalidatePendingDecision,
                relatedDecisionId,
                relatedAttemptId,
                targetDecisionId);
        }
        catch (Exception exception)
        {
            DisableAfterFailure($"coverage gap {reason}", exception);
        }
    }

    internal static void RecordUnsupportedBundleSelection(string contextId)
    {
        if (_episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress)
        {
            return;
        }

        DrainCompletedSelectors();
        CompleteAcceptedParentActions(
            contextId,
            nestedSelectorObserved: true);
        _episodes?.ResolveAtCurrentBoundary();
        RecordCoverageGap(
            "card_bundle_selection_not_supported",
            new
            {
                contextId,
                during_combat = CombatManager.Instance.IsInProgress,
            },
            invalidatePendingDecision: false);
    }

    internal static void RecordUnsupportedMinigameInteraction(string contextId)
    {
        if (_episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress)
        {
            return;
        }

        // Unknown minigames must still make the episode truthfully incomplete.
        // Crystal Sphere uses its own structured path. Drain a just-finished
        // selector first so this gap cannot invalidate its label.
        DrainCompletedSelectors();
        CompleteAcceptedParentActions(
            contextId,
            nestedSelectorObserved: true);
        _episodes?.ResolveAtCurrentBoundary();
        RecordCoverageGap(
            "event_minigame_interaction_not_supported",
            new { contextId });
    }

    internal static void ScheduleOnMainThread(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        Callable.From(action).CallDeferred();
    }

    internal static void AttachCardRewardSelectionTask(
        PendingCardRewardSelection? pending,
        Task<int?> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    internal static void AttachCardSelectionTask(
        PendingCardSelection? pending,
        Task<IEnumerable<CardModel>> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    internal static void AttachRelicSelectionTask(
        PendingRelicSelection? pending,
        Task<IEnumerable<RelicModel>> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    private static void ObserveSelectorTask(Task task)
    {
        if (task.IsCompleted)
        {
            DrainCompletedSelectors();
            return;
        }

        _ = task.ContinueWith(
            _ => ScheduleOnMainThread(DrainCompletedSelectors),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    internal static void DrainCompletedSelectors()
    {
        if (_drainingSelectors)
        {
            return;
        }

        _drainingSelectors = true;
        try
        {
            // This method always executes on the game thread: either directly
            // from a Harmony boundary or through CallDeferred. It closes selector
            // tasks before a subsequent decision/save can overtake their label.
            DrainCompletedCombatChoices();
            DrainCompletedBundleSelections();
            DrainCompletedMultiCardSelections();
            foreach (var pending in PendingOutsideOperations
                         .OfType<PendingCardRewardSelection>()
                         .Where(item => item.CompletionTask?.IsCompleted == true)
                         .ToArray())
            {
                var task = pending.CompletionTask!;
                CompleteCardRewardSelection(
                    pending,
                    task.Status == TaskStatus.RanToCompletion ? task.Result : null,
                    SelectorTaskException(task));
            }

            foreach (var pending in PendingOutsideOperations
                         .OfType<PendingCardSelection>()
                         .Where(item => item.CompletionTask?.IsCompleted == true)
                         .ToArray())
            {
                var task = pending.CompletionTask!;
                CompleteCardSelection(
                    pending,
                    task.Status == TaskStatus.RanToCompletion
                        ? task.Result.ToArray()
                        : null,
                    SelectorTaskException(task));
            }

            foreach (var pending in PendingOutsideOperations
                         .OfType<PendingRelicSelection>()
                         .Where(item => item.CompletionTask?.IsCompleted == true)
                         .ToArray())
            {
                var task = pending.CompletionTask!;
                CompleteRelicSelection(
                    pending,
                    task.Status == TaskStatus.RanToCompletion
                        ? task.Result.ToArray()
                        : null,
                    SelectorTaskException(task));
            }
        }
        finally
        {
            _drainingSelectors = false;
        }
    }

    private static Exception? SelectorTaskException(Task task) => task.Status switch
    {
        TaskStatus.RanToCompletion => null,
        TaskStatus.Canceled => new TaskCanceledException(task),
        _ => task.Exception?.GetBaseException()
             ?? new InvalidOperationException(
                 $"Selector task ended with status {task.Status}."),
    };

    private static bool HasPendingSelector() =>
        PendingCombatChoices.Count != 0
        || PendingOutsideOperations.Any(operation => operation is
            PendingCardRewardSelection or PendingCardSelection or PendingRelicSelection
                or PendingBundleSelection or PendingMultiCardSelection);

    private static int PendingSelectorCount() =>
        PendingCombatChoices.Count + PendingOutsideOperations.Count(operation => operation is
            PendingCardRewardSelection or PendingCardSelection or PendingRelicSelection
                or PendingBundleSelection or PendingMultiCardSelection);

    private static bool HasPendingOperations() =>
        PendingCombatActions.Count != 0
        || PendingOutsidePotionActions.Count != 0
        || PendingManualCombatIntents.Count != 0
        || PendingCombatChoices.Count != 0
        || PendingCrystalSphereCellTasks.Count != 0
        || PendingOutsideOperations.Count != 0;

    private static void CompleteAcceptedParentActions(
        string childContext,
        bool nestedSelectorObserved = false)
    {
        // Several native async methods open their selector synchronously,
        // before the outer Task<T> is returned and Harmony can run its
        // postfix. Opening a child selector is already proof that the parent
        // action was accepted, so close that parent step before recording the
        // child decision. The eventual Task result is still audited by its
        // continuation and TryMarkCompleted prevents a duplicate commit.
        foreach (var parent in PendingOutsideOperations
                     .OfType<NativeActionCapture>()
                     .ToArray())
        {
            parent.MarkAccepted();
            if (nestedSelectorObserved)
            {
                parent.MarkNestedSelectorObserved();
            }
            CompleteNativeAction(
                parent,
                CollectorExecutionStatus.ObservedTransition,
                $"native action accepted before nested selector {childContext}");
        }
    }

    private static void CompleteKnownAcceptedActions(string boundary)
    {
        foreach (var capture in PendingOutsideOperations
                     .OfType<NativeActionCapture>()
                     .Where(capture => capture.IsAccepted)
                     .ToArray())
        {
            CompleteNativeAction(
                capture,
                CollectorExecutionStatus.ObservedTransition,
                $"accepted native action reached {boundary}");
        }
    }

    private static void CompletePendingOutsideOperation(object operation)
    {
        PendingOutsideOperations.Remove(operation);
        FinishPendingRun();
    }

    private static NativeActionCapture? CaptureOutside(
        string description,
        Func<RunState, long, (OutsideCombatDecisionPoint Decision, int SelectedOrdinal)> capture)
    {
        try
        {
            // A last Crystal Sphere reveal may overlap a newly opened outside
            // surface. No outside action may use that animation's partial
            // board/run state as its pre-state.
            if (!CrystalSpherePriorTaskSettled())
            {
                return null;
            }

            if (_stopping
                || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress
                || CombatManager.Instance.IsInProgress
                || RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1)
            {
                return null;
            }

            DrainCompletedSelectors();
            if (PendingOutsideOperations.Any(operation =>
                    operation is PendingUnmatchedMerchantClick))
            {
                RecordCoverageGap(
                    "outside_action_overlapped_unresolved_merchant_click",
                    new { description },
                    invalidatePendingDecision: false);
                return null;
            }
            // Reaching the next semantic decision is the most reliable
            // generic indication that the preceding native request and its
            // queued GameActions have settled. This also measures reward
            // deltas from the stable post-action state.
            CompleteAcceptedParentActions(description);
            _episodes.ResolveAtCurrentBoundary();
            var (decision, selectedOrdinal) = capture(
                state,
                _episodes.NextSourceDecisionIndex());
            var draft = _episodes.DraftOutside(decision, selectedOrdinal, description);
            if (draft is null)
            {
                return null;
            }

            var pending = new NativeActionCapture(
                draft,
                description,
                _runGeneration);
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "outside_capture_failed",
                new { description, error = exception.ToString() });
            return null;
        }
    }

    private static void OnRunStarted(RunState state)
    {
        try
        {
            var nativeSave = TryGetNativeSave();
            var evidence = _preparedRun is { } prepared
                           && ReferenceEquals(prepared.State, state)
                ? prepared with
                {
                    StartTime = nativeSave?.StartTime ?? prepared.StartTime,
                    NativeReloadCount = nativeSave?.NumReloads
                                        ?? prepared.NativeReloadCount,
                    NativeSaveFingerprint = prepared.NativeSaveFingerprint
                                            ?? (nativeSave is null
                                                ? null
                                                : CollectorEpisodeCoordinator
                                                    .TryFingerprintNativeSave(nativeSave)),
                }
                : new RunStartEvidence(
                    state,
                    LoadedFromSave: false,
                    nativeSave?.StartTime,
                    nativeSave?.NumReloads ?? 0,
                    nativeSave is null
                        ? null
                        : CollectorEpisodeCoordinator.TryFingerprintNativeSave(nativeSave),
                    NewRunObserved: false);
            _preparedRun = null;
            _episodes?.BeginRun(evidence);
            AttachRunInputs();
        }
        catch (Exception exception)
        {
            DisableAfterFailure("start run", exception);
        }
    }

    private static void AttachRunInputs()
    {
        DetachRunInputs();
        CollectorManualCombatInput.StartGeneration(_runGeneration);
        var manager = RunManager.Instance;
        _actionQueue = manager.ActionQueueSet;
        _actionQueue.ActionEnqueued += OnActionEnqueued;
        _actionExecutor = manager.ActionExecutor;
        _actionExecutor.BeforeActionExecuted += OnPolicyActionStarting;
        _actionExecutor.BeforeActionExecuted += OnManualCombatActionStarting;
        _actionExecutor.AfterActionExecuted += OnActionExecuted;
        _choiceSynchronizer = manager.PlayerChoiceSynchronizer;
        _choiceSynchronizer.PlayerChoiceReceived += OnPlayerChoiceReceived;
    }

    private static void DetachRunInputs()
    {
        ResetActRewardCapture();
        CollectorManualCombatInput.EndGeneration(_runGeneration);
        _runGeneration++;
        if (_actionQueue is not null)
        {
            _actionQueue.ActionEnqueued -= OnActionEnqueued;
            _actionQueue = null;
        }

        if (_actionExecutor is not null)
        {
            _actionExecutor.BeforeActionExecuted -= OnPolicyActionStarting;
            _actionExecutor.BeforeActionExecuted -= OnManualCombatActionStarting;
            _actionExecutor.AfterActionExecuted -= OnActionExecuted;
            _actionExecutor = null;
        }

        if (_choiceSynchronizer is not null)
        {
            _choiceSynchronizer.PlayerChoiceReceived -= OnPlayerChoiceReceived;
            _choiceSynchronizer = null;
        }

        PendingCombatActions.Clear();
        ClearPolicyActionInputs();
        PendingOutsidePotionActions.Clear();
        PendingManualCombatIntents.Clear();
        ClearCombatChoiceState();
        PendingBundleSelections.Clear();
        PendingCrystalSphereCellTasks.Clear();
        ClearSimpleGridOriginalOrders();
        _lastReservedBundleChoice = null;
        _lastReservedMultiCardChoice = null;
        PendingOutsideOperations.Clear();
        _activeCardReward = null;
        _pendingCardRewardSelection = null;
        _merchantRemovalSelectionPending = false;
        _merchantRemovalParent = null;
        _pendingRunHistory = null;
    }

    private static void OnCombatBegan(CombatState state)
    {
        _lastReservedNativeChoice = null;
        DrainCompletedSelectors();
        CompleteAcceptedParentActions("combat_started");
        _combatId = ActRewardCombatId(state) ?? Guid.NewGuid();
        _activeCombatState = state;
        ResolveStableCombatBoundary(state);
        RecordDiagnostic(
            "combat_started",
            new
            {
                combat_id = _combatId,
                encounter_id = state.Encounter?.Id.ToString(),
                round = state.RoundNumber,
            });
    }

    private static void OnCombatEnded(CombatRoom room)
    {
        CaptureActRewardCombatEnded(room);
        CloseNativeChoiceTicketsAtCombatEnd();
        _lastReservedNativeChoice = null;
        var state = _activeCombatState;
        RecordDiagnostic(
            "combat_ended",
            new
            {
                combat_id = _combatId,
                round = state?.RoundNumber,
                player_alive = state?.Players.All(player => player.Creature.IsAlive),
            });
        _combatId = null;
        _activeCombatState = null;
    }

    private static void OnCombatStateChanged(CombatState state) =>
        ResolveStableCombatBoundary(state);

    private static void ResolveStableCombatBoundary(CombatState state)
    {
        try
        {
            DrainCompletedSelectors();
            var manager = CombatManager.Instance;
            if (_episodes?.HasActiveEpisode != true
                || !manager.IsInProgress
                || manager.IsOverOrEnding
                || manager.PlayerActionsDisabled
                || state.CurrentSide != MegaCrit.Sts2.Core.Combat.CombatSide.Player
                || RunManager.Instance.ActionExecutor.IsRunning
                || PendingCombatActions.Count != 0
                || PendingManualCombatIntents.Count != 0
                || PendingCombatChoices.Count != 0)
            {
                return;
            }

            // CombatStateChanged also fires during start/end-turn transitions.
            // Those states have no player decision and are expected, not an
            // exceptional capture failure.
            if (CombatCaptureService.GetLegalActions(state).Count == 0)
            {
                return;
            }

            _episodes.ResolveAtCurrentBoundary();
        }
        catch (Exception exception)
        {
            RecordDiagnostic(
                "combat_boundary_settlement_failed",
                new { error = exception.ToString() });
        }
    }

    internal static ManualCombatInputEvidence CaptureManualCombatPreState()
    {
        var inputAtUtc = DateTimeOffset.UtcNow;
        try
        {
            DrainCompletedSelectors();
            var combatManager = CombatManager.Instance;
            if (!combatManager.IsInProgress)
            {
                return CaptureManualOutsidePotionPreState(inputAtUtc);
            }

            var state = combatManager.DebugOnlyGetState();
            if (_stopping || _episodes?.HasActiveEpisode != true
                || state is null)
            {
                return new ManualCombatInputEvidence(
                    inputAtUtc,
                    null,
                    null,
                    "No active combat episode at the manual input boundary.");
            }

            var pendingActions = PendingManualActionsAtClick();
            var stable = !combatManager.IsOverOrEnding
                         && !combatManager.PlayerActionsDisabled
                         && state.CurrentSide ==
                             MegaCrit.Sts2.Core.Combat.CombatSide.Player
                         && !RunManager.Instance.ActionExecutor.IsRunning
                         && PendingCombatActions.Count == 0
                         && PendingManualCombatIntents.Count == 0
                         && PendingCombatChoices.Count == 0
                         && CombatCaptureService.GetLegalActions(state).Count > 0;
            if (stable)
            {
                _episodes.ResolveAtCurrentBoundary();
            }

            string? captureFailure = null;
            if (!combatManager.IsOverOrEnding
                && PendingCombatChoices.Count == 0
                && state.CurrentSide == MegaCrit.Sts2.Core.Combat.CombatSide.Player)
            {
                try
                {
                    // A native manual entry point is the click boundary. The
                    // executor may be busy; freeze the internal Hand and the
                    // native legal set before this GameAction is enqueued.
                    var sourceDecisionIndex = _episodes.NextSourceDecisionIndex();
                    // Native manual input can be queued while the next turn is
                    // still drawing. Freeze that click-time Start observation
                    // with the collector's manual-input action set; ordinary
                    // adapter policies still require the Play phase.
                    var captured = state.Players.Count == 1
                                   && state.Players[0].PlayerCombatState?.Phase
                                       == PlayerTurnPhase.Start
                        ? CollectorCombatProjector.CaptureQueuedTurnStart(
                            state,
                            sourceDecisionIndex)
                        : CollectorCombatProjector.Capture(
                            state,
                            sourceDecisionIndex);
                    captured = CollectorCombatProjector.WithPendingManualActions(
                        captured,
                        pendingActions);
                    return new ManualCombatInputEvidence(
                        inputAtUtc,
                        captured,
                        captured.Decision.Observation,
                        null,
                        QueuedAtClick: !stable);
                }
                catch (Exception exception)
                {
                    captureFailure = exception.ToString();
                }
            }

            CombatObservation? clickObservation = null;
            try
            {
                clickObservation = CollectorCombatProjector.CaptureInternalObservation(state) with
                {
                    PendingManualActions = pendingActions,
                };
            }
            catch (Exception exception)
            {
                captureFailure = captureFailure is null
                    ? exception.ToString()
                    : captureFailure + " Internal capture: " + exception;
            }

            return new ManualCombatInputEvidence(
                inputAtUtc,
                null,
                clickObservation,
                captureFailure ?? "No verified player legal set at the manual input boundary.",
                QueuedAtClick: !stable);
        }
        catch (Exception exception)
        {
            return new ManualCombatInputEvidence(
                inputAtUtc,
                null,
                null,
                exception.ToString());
        }
    }

    private static ManualCombatInputEvidence CaptureManualOutsidePotionPreState(
        DateTimeOffset inputAtUtc)
    {
        if (_stopping || _episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress
            || RunManager.Instance.DebugOnlyGetState() is not { } state
            || state.Players.Count != 1)
        {
            return new ManualCombatInputEvidence(
                inputAtUtc, null, null, "No active single-player outside episode.");
        }

        var rewards = TryGetInteractableTopRewards(state);
        var merchant = rewards is null ? TryGetInteractableTopMerchant(state) : null;
        var pendingOperations = PendingOutsideOperations.ToArray();
        var acceptedParents = pendingOperations
            .OfType<NativeActionCapture>()
            .Where(capture => capture.IsAccepted
                              && !capture.IsCompleted
                              && capture.RuntimeGeneration == _runGeneration)
            .ToArray();
        var snapshot = _episodes.Snapshot;
        var stack = NOverlayStack.Instance;
        var topSurface = rewards is not null ? "rewards"
            : merchant is not null ? "merchant"
            : stack is not null && GodotObject.IsInstanceValid(stack)
              && stack.IsInsideTree() && stack.ScreenCount > 0
                ? stack.Peek()?.GetType().Name ?? "unknown_overlay"
                : "unverified";
        var audit = new OutsidePotionCaptureAudit(
            pendingOperations.Length,
            acceptedParents.Length,
            PendingSelectorCount(),
            PendingOutsidePotionActions.Count,
            PendingCombatActions.Count + PendingManualCombatIntents.Count
            + PendingCrystalSphereCellTasks.Count,
            snapshot.PendingDecisionCount,
            RunManager.Instance.ActionExecutor.IsRunning,
            RunManager.Instance.ActionQueueSet.IsEmpty,
            topSurface);

        ManualCombatInputEvidence Fail(string reason) =>
            new(inputAtUtc, null, null, reason) { OutsideCaptureAudit = audit };

        if (rewards is null && merchant is null)
        {
            return Fail("The click-time outside surface or potion belt was not verified.");
        }

        // An accepted native parent can be settled here only when all of its
        // queued GameActions have drained. This click is then the next stable
        // semantic decision, just like CaptureOutside. A still-running task,
        // selector, or queue cannot safely separate the two rewards.
        if (audit.PendingSelectorCount != 0
            || audit.ActionExecutorRunning
            || !audit.ActionQueueEmpty
            || audit.PendingOutsidePotionCount != 0
            || audit.OtherPendingOperationCount != 0)
        {
            return Fail("The prior outside selector, executor, or action queue is still active.");
        }

        NativeActionCapture? parent = null;
        if (pendingOperations.Length != 0)
        {
            if (pendingOperations.Length != 1 || acceptedParents.Length != 1)
            {
                return Fail("The prior outside action has not been uniquely accepted.");
            }

            parent = acceptedParents[0];
            var pending = snapshot.PendingDecisions;
            if (pending is null || pending.Count != 1
                || pending[0].DecisionId != parent.Draft.Receipt.DecisionId
                || pending[0].Phase != EpisodePhase.AwaitingExecution)
            {
                return Fail("The accepted outside action does not match the pending decision.");
            }
        }

        try
        {
            if (parent is not null)
            {
                CompleteAcceptedParentActions("outside_potion_click");
            }

            _episodes.ResolveAtCurrentBoundary();
            if (_episodes.Snapshot.PendingDecisionCount != 0)
            {
                return Fail("The prior outside decision has not reached a stable boundary.");
            }

            if (parent is not null)
            {
                RecordDiagnostic(
                    "outside_potion_click_settled_accepted_parent",
                    new
                    {
                        parent_decision_id = parent.Draft.Receipt.DecisionId,
                        parent_attempt_id = parent.Draft.AttemptId,
                        capture_audit = audit,
                    });
            }

            var decision = rewards is not null
                ? CollectorOutsideProjector.ForReward(
                    state,
                    FindVisibleRewards(rewards),
                    selectedReward: null,
                    CanProceedRewards(rewards),
                    _episodes.NextSourceDecisionIndex(),
                    out _,
                    includePotionActions: true)
                : CollectorOutsideProjector.ForMerchant(
                    state,
                    merchant!,
                    selectedEntry: null,
                    _episodes.NextSourceDecisionIndex(),
                    out _,
                    includePotionActions: true);
            return new ManualCombatInputEvidence(
                inputAtUtc, null, null, null)
            {
                OutsideDecision = decision,
                OutsideCaptureAudit = audit,
            };
        }
        catch (Exception exception)
        {
            return Fail(exception.ToString());
        }
    }

    private static bool TryRecordStructuredOutsidePotion(
        GameAction action,
        ManualCombatInputEvidence? manualInput,
        OutsideCombatActionKind kind,
        int? potionSlotIndex,
        ulong ownerId,
        string inputKind)
    {
        if (_episodes?.HasActiveEpisode != true
            || manualInput?.OutsideDecision is not { } decision
            || potionSlotIndex is not { } slot
            || decision.Observation.Players.Count != 1
            || decision.Observation.Players[0].PlayerId != ownerId)
        {
            return false;
        }

        var matches = decision.LegalActions
            .Select((candidate, index) => (candidate, index))
            .Where(item => item.candidate.Kind == kind
                           && item.candidate.PotionSlotIndex == slot)
            .ToArray();
        if (matches.Length != 1)
        {
            return false;
        }

        var pendingBefore = _episodes.Snapshot.PendingDecisions?
            .Select(pending => pending.DecisionId).ToHashSet() ?? [];
        try
        {
            var draft = _episodes.DraftOutside(
                decision, matches[0].index, inputKind);
            if (draft is null)
            {
                return false;
            }

            PendingOutsidePotionActions.Add(action, draft);
            return true;
        }
        catch (Exception exception)
        {
            var newDecisionId = _episodes.HasActiveEpisode
                ? _episodes.Snapshot.PendingDecisions?
                    .Select(pending => pending.DecisionId)
                    .Where(id => !pendingBefore.Contains(id))
                    .Cast<Guid?>()
                    .FirstOrDefault()
                : null;
            RecordCoverageGap(
                "outside_potion_decision_failed",
                new { kind, potion_slot_index = slot, error = exception.ToString() },
                invalidatePendingDecision: newDecisionId is not null,
                targetDecisionId: newDecisionId);
            // The native request remains visible as a gap even when journaling
            // failed after opening its decision. Do not emit a second gap.
            return true;
        }
    }

    private static void OnActionEnqueued(GameAction action)
    {
        DrainCompletedSelectors();
        var manualInput = CollectorManualCombatInput.Consume(action);
        if (TryCapturePolicyAction(action, manualInput is not null))
        {
            return;
        }
        // PotionModel.EnqueueManualUse and the discard popup are native manual
        // entry points outside combat. Record an independent action only when
        // their click-time surface and legal set were frozen; otherwise keep
        // the exact native request as a gap instead of silently charging its
        // effect to an adjacent screen action.
        var relatedOutsideAction = _episodes?.StagedActionAwaitingBoundary is
            { Decision.Domain: CollectorDecisionDomain.OutsideCombat } outsideDraft
            ? outsideDraft
            : null;
        if (action is UsePotionAction outsidePotion
            && !outsidePotion.WasEnqueuedInCombat)
        {
            var slot = outsidePotion.PotionIndex <= int.MaxValue
                ? (int?)outsidePotion.PotionIndex
                : null;
            if (TryRecordStructuredOutsidePotion(
                    action, manualInput, OutsideCombatActionKind.UsePotion,
                    slot, outsidePotion.OwnerId, "outside_potion_use"))
            {
                return;
            }

            RecordCoverageGap(
                manualInput is null
                    ? "outside_potion_use_without_manual_input_evidence"
                    : "outside_manual_potion_use_not_structured",
                new
                {
                    actor_player_id = outsidePotion.OwnerId,
                    potion_slot_index = outsidePotion.PotionIndex,
                    manual_input_observed = manualInput is not null,
                    capture_failure = manualInput?.CaptureFailure,
                    outside_decision_frozen = manualInput?.OutsideDecision is not null,
                    outside_capture_audit = manualInput?.OutsideCaptureAudit,
                },
                invalidatePendingDecision: false,
                relatedDecisionId: relatedOutsideAction?.Receipt.DecisionId,
                relatedAttemptId: relatedOutsideAction?.AttemptId);
            return;
        }

        if (action is DiscardPotionGameAction discardPotion
            && (!discardPotion.WasEnqueuedInCombat || manualInput is not null))
        {
            var slot = discardPotion.ToNetAction() is NetDiscardPotionGameAction net
                ? net.potionSlotIndex
                : (uint?)null;
            if (!discardPotion.WasEnqueuedInCombat
                && TryRecordStructuredOutsidePotion(
                    action, manualInput, OutsideCombatActionKind.DiscardPotion,
                    slot is <= int.MaxValue ? (int?)slot : null,
                    discardPotion.OwnerId, "outside_potion_discard"))
            {
                return;
            }

            RecordCoverageGap(
                manualInput is null
                    ? "outside_potion_discard_without_manual_input_evidence"
                    : discardPotion.WasEnqueuedInCombat
                        ? "combat_manual_potion_discard_not_structured"
                        : "outside_manual_potion_discard_not_structured",
                new
                {
                    actor_player_id = discardPotion.OwnerId,
                    potion_slot_index = slot,
                    manual_input_observed = manualInput is not null,
                    was_enqueued_in_combat = discardPotion.WasEnqueuedInCombat,
                    capture_failure = manualInput?.CaptureFailure,
                    outside_decision_frozen = manualInput?.OutsideDecision is not null,
                    outside_capture_audit = manualInput?.OutsideCaptureAudit,
                },
                invalidatePendingDecision: false,
                relatedDecisionId: relatedOutsideAction?.Receipt.DecisionId,
                relatedAttemptId: relatedOutsideAction?.AttemptId);
            return;
        }

        var descriptor = CollectorCombatProjector.Describe(action);
        if (descriptor is null || !CombatManager.Instance.IsInProgress)
        {
            return;
        }

        var pendingDecisionIdsBeforeCapture = _episodes?.HasActiveEpisode == true
            ? _episodes.Snapshot.PendingDecisions?
                .Select(pending => pending.DecisionId).ToHashSet() ?? []
            : new HashSet<Guid>();
        try
        {
            // Only a native manual-play/end-turn/potion entry point proves a
            // human submission. Card effects can enqueue the same action
            // classes while their parent is still resolving.
            if (manualInput is null)
            {
                var evidence = new
                {
                    action = action.ToString(),
                    type = action.GetType().FullName,
                    executor_running = RunManager.Instance.ActionExecutor.IsRunning,
                    parent_action_count = PendingCombatActions.Count,
                };
                if (!evidence.executor_running && evidence.parent_action_count == 0)
                {
                    RecordCoverageGap(
                        "combat_action_without_manual_input_evidence",
                        evidence,
                        invalidatePendingDecision: false);
                }
                else
                {
                    RecordDiagnostic("automatic_or_unproven_combat_action", evidence);
                }
                return;
            }

            var overlappingParent = PendingCombatActions.Values.FirstOrDefault()
                                    ?? _episodes?.StagedActionAwaitingBoundary;
            // Native GameAction.OnEnqueued runs before this event, so use the
            // observation frozen immediately before RequestEnqueue.
            var captured = manualInput.PreSubmissionDecision;
            if (captured is null)
            {
                TrackManualCombatInput(
                    action,
                    descriptor,
                    manualInput,
                    overlappingParent: overlappingParent,
                    unstructuredGapReason: overlappingParent is null
                        ? "combat_action_without_stable_pre_state"
                        : "manual_combat_action_during_pending");
                return;
            }

            var index = CollectorCombatProjector.FindAction(
                captured.Decision.LegalActions,
                descriptor);
            if (index < 0)
            {
                TrackManualCombatInput(
                    action,
                    descriptor,
                    manualInput,
                    overlappingParent: overlappingParent,
                    unstructuredGapReason: "combat_action_not_in_legal_set");
                return;
            }

            var inputKind = action switch
                {
                    PlayCardAction => "play_card",
                    UsePotionAction => "use_potion",
                    EndPlayerTurnAction => "end_turn",
                    _ => "combat_action",
                };
            var draft = overlappingParent is not null || manualInput.QueuedAtClick
                ? _episodes!.DraftQueuedCombat(captured, index, inputKind)
                : _episodes!.DraftCombat(captured, index, inputKind);
            PendingCombatActions[action] = draft;
            TrackManualCombatInput(action, descriptor, manualInput, ownDraft: draft);
        }
        catch (Exception exception)
        {
            if (manualInput is not null
                && !PendingManualCombatIntents.ContainsKey(action))
            {
                try
                {
                    TrackManualCombatInput(action, descriptor, manualInput);
                }
                catch (Exception captureException)
                {
                    RecordDiagnostic(
                        "manual_combat_input_journal_failed",
                        new { error = captureException.ToString() });
                }
            }

            var newDecisionId = _episodes?.HasActiveEpisode == true
                ? _episodes.Snapshot.PendingDecisions?
                    .Select(pending => pending.DecisionId)
                    .Where(id => !pendingDecisionIdsBeforeCapture.Contains(id))
                    .Cast<Guid?>()
                    .FirstOrDefault()
                : null;
            RecordCoverageGap(
                "combat_action_capture_failed",
                new { action = action.ToString(), error = exception.ToString() },
                invalidatePendingDecision: newDecisionId is not null,
                targetDecisionId: newDecisionId);
        }
    }

    private static void OnActionExecuted(GameAction action)
    {
        CapturedPolicyActions.Remove(action);
        try
        {
            // Native CombatCard callbacks are synchronous and precede action
            // completion. Audit any missing callback before FinishPendingRun
            // can publish and detach this episode.
            CloseNativeChoiceTicketsForAction(action);
            var hadManualInput = FinishManualCombatInput(
                action,
                action.Exception is null
                    ? CollectorExecutionStatus.ObservedTransition
                    : CollectorExecutionStatus.Failed,
                action.Exception?.ToString());
            if (PendingOutsidePotionActions.Remove(action, out var outsidePotionDraft))
            {
                _episodes?.Commit(
                    outsidePotionDraft,
                    action.Exception is null
                        ? CollectorExecutionStatus.ObservedTransition
                        : CollectorExecutionStatus.Failed,
                    action.Exception?.ToString());
                FinishPendingRun();
                return;
            }

            if (!PendingCombatActions.Remove(action, out var draft))
            {
                if (hadManualInput)
                {
                    FinishPendingRun();
                }
                return;
            }

            if (CompleteEarlySettledCombatAction(action, draft))
            {
                return;
            }

            _episodes?.Commit(
                draft,
                action.Exception is null
                    ? CollectorExecutionStatus.ObservedTransition
                    : CollectorExecutionStatus.Failed,
                action.Exception?.ToString());
            FinishPendingRun();
        }
        catch (Exception exception)
        {
            DisableAfterFailure("native action execution", exception);
        }
        finally
        {
            var generation = _runGeneration;
            ScheduleOnMainThread(() =>
            {
                if (generation == _runGeneration
                    && CombatManager.Instance.DebugOnlyGetState() is { } state)
                {
                    ResolveStableCombatBoundary(state);
                }
            });
        }
    }

    internal static void OnNativeCombatActionCancelled(
        GameAction action,
        GameActionState previousState)
    {
        if (action.State != GameActionState.Canceled)
        {
            return;
        }

        CapturedPolicyActions.Remove(action);

        try
        {
            CloseNativeChoiceTicketsForAction(action);
            var cleanCancel = previousState == GameActionState.WaitingForExecution;
            var hadManualInput = FinishManualCombatInput(
                action,
                cleanCancel
                    ? CollectorExecutionStatus.Cancelled
                    : CollectorExecutionStatus.Failed,
                $"Native action cancelled from {previousState}.");
            if (PendingOutsidePotionActions.Remove(action, out var outsidePotionDraft))
            {
                _episodes?.Commit(
                    outsidePotionDraft,
                    cleanCancel
                        ? CollectorExecutionStatus.Cancelled
                        : CollectorExecutionStatus.Failed,
                    $"Native potion action cancelled from {previousState}.");
                FinishPendingRun();
                return;
            }

            if (!PendingCombatActions.Remove(action, out var draft))
            {
                if (hadManualInput)
                {
                    FinishPendingRun();
                }
                return;
            }

            if (EarlySettledCombatActions.Remove(action))
            {
                RecordCoverageGap(
                    "combat_parent_cancelled_after_nested_choice",
                    new { action = action.ToString(), previous_state = previousState.ToString() },
                    invalidatePendingDecision: false,
                    relatedDecisionId: draft.Receipt.DecisionId,
                    relatedAttemptId: draft.AttemptId);
            }
            else
            {
                _episodes?.Commit(
                    draft,
                    cleanCancel
                        ? CollectorExecutionStatus.Cancelled
                        : CollectorExecutionStatus.Failed,
                    $"Native action cancelled from {previousState}.");
            }

            FinishPendingRun();
        }
        catch (Exception exception)
        {
            DisableAfterFailure("combat cancellation", exception);
        }
        finally
        {
            var generation = _runGeneration;
            ScheduleOnMainThread(() =>
            {
                if (generation == _runGeneration
                    && CombatManager.Instance.DebugOnlyGetState() is { } state)
                {
                    ResolveStableCombatBoundary(state);
                }
            });
        }
    }

    private static void OnPlayerChoiceReceived(
        Player player,
        uint choiceId,
        NetPlayerChoiceResult result)
    {
        if (!IsLocalSinglePlayer(player))
        {
            return;
        }

        RecordDiagnostic(
            "native_player_choice",
            new
            {
                combat_id = _combatId,
                choice_id = choiceId,
                choice_type = result.type.ToString(),
                indexes = result.indexes?.ToArray() ?? [],
                deck_indexes = result.deckCards?
                    .Select(card => card.DeckIndex).ToArray() ?? [],
                combat_card_ids = result.combatCards?
                    .Select(card => card.CombatCardIndex).ToArray() ?? [],
                during_action_id = RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id,
            });
        if (!CombatManager.Instance.IsInProgress)
        {
            if (result.type.ToString() is "Index" or "Indexes"
                && ObserveNativeBundleChoice(choiceId, result))
            {
                return;
            }

            ObserveNativeMultiCardChoice(
                choiceId,
                result,
                RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id);
            return;
        }

        if (CombatManager.Instance.IsInProgress
            && string.Equals(result.type.ToString(), "CombatCard", StringComparison.Ordinal))
        {
            var selectedIds = result.combatCards?
                .Select(card => card.CombatCardIndex).ToArray() ?? [];
            if (!ObserveNativeCombatCardChoice(
                    choiceId,
                    selectedIds,
                    RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id))
            {
                RecordCoverageGap(
                    "combat_card_choice_without_selector",
                    new { combat_id = _combatId, choice_id = choiceId, selected_card_ids = selectedIds },
                    invalidatePendingDecision: false);
            }
        }
        else if (CombatManager.Instance.IsInProgress
                 && (result.type.ToString() is "Index" or "Indexes"))
        {
            // Generated options can have no combat-card database ID. Match
            // their native index receipt only to a selector ticket reserved
            // under this exact choice ID and running parent action.
            var selectedIndexes = result.indexes?.ToArray() ?? [];
            if (!ObserveNativeCombatIndexChoice(
                    choiceId,
                    selectedIndexes,
                    RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id))
            {
                // A PlayerChoiceReceived receipt without a frozen selector
                // cannot silently certify a complete combat trajectory. It
                // also cannot become a human label without input evidence.
                RecordCoverageGap(
                    "combat_index_choice_without_selector",
                    new
                    {
                        combat_id = _combatId,
                        choice_id = choiceId,
                        selected_option_indexes = selectedIndexes,
                    },
                    invalidatePendingDecision: false);
            }
        }
    }

    private static bool IsLocalSinglePlayer(Player player)
    {
        var state = RunManager.Instance.DebugOnlyGetState();
        return state is not null
               && state.Players.Count == 1
               && ReferenceEquals(state.Players[0], player);
    }

    private static int IndexOfReferenceOrIdentity(
        IReadOnlyList<CardModel> options,
        CardModel selected)
    {
        for (var index = 0; index < options.Count; index++)
        {
            if (ReferenceEquals(options[index], selected))
            {
                return index;
            }
        }

        var matches = options
            .Select((card, index) => new { card, index })
            .Where(entry => entry.card.Id == selected.Id
                            && entry.card.CurrentUpgradeLevel == selected.CurrentUpgradeLevel)
            .ToArray();
        return matches.Length == 1 ? matches[0].index : -1;
    }

    private static int IndexOfReferenceOrIdentity(
        IReadOnlyList<RelicModel> options,
        RelicModel selected)
    {
        for (var index = 0; index < options.Count; index++)
        {
            if (ReferenceEquals(options[index], selected))
            {
                return index;
            }
        }

        var matches = options
            .Select((relic, index) => new { relic, index })
            .Where(entry => entry.relic.Id == selected.Id)
            .ToArray();
        return matches.Length == 1 ? matches[0].index : -1;
    }

    private static IReadOnlyList<Reward> FindVisibleRewards()
    {
        var rewards = FindActiveNodes<NRewardButton>()
            .Where(button => button.IsEnabled && button.Reward is not null)
            .Select(button => button.Reward!)
            .Distinct<Reward>(ReferenceEqualityComparer.Instance)
            .ToArray();
        return rewards;
    }

    private static IReadOnlyList<Reward> FindVisibleRewards(NRewardsScreen screen) =>
        Descendants<NRewardButton>(screen)
            .Where(button => GodotObject.IsInstanceValid(button)
                             && button.IsInsideTree()
                             && button.IsVisibleInTree()
                             && button.IsEnabled
                             && button.Reward is not null)
            .Select(button => button.Reward!)
            .Distinct<Reward>(ReferenceEqualityComparer.Instance)
            .ToArray();

    private static NRewardsScreen? TryGetInteractableTopRewards(
        RunState state,
        NRewardsScreen? expected = null)
    {
        var stack = NOverlayStack.Instance;
        if (stack is null || !GodotObject.IsInstanceValid(stack)
            || !stack.IsInsideTree() || stack.ScreenCount == 0
            || stack.Peek() is not NRewardsScreen rewards
            || !GodotObject.IsInstanceValid(rewards)
            || !rewards.IsInsideTree() || !rewards.IsVisibleInTree()
            || expected is not null && !ReferenceEquals(expected, rewards))
        {
            return null;
        }

        return HasVerifiedVisiblePotionBelt(state) ? rewards : null;
    }

    private static MerchantInventory? TryGetInteractableTopMerchant(RunState state)
    {
        // Merchant is a room, whereas selectors and rewards are overlays.
        // An overlay above it makes the merchant's visible legal set invalid.
        if (NOverlayStack.Instance is { ScreenCount: > 0 })
        {
            return null;
        }

        var rooms = FindActiveNodes<NMerchantRoom>().ToArray();
        if (rooms.Length != 1
            || rooms[0].Inventory is not { } inventoryScreen
            || !GodotObject.IsInstanceValid(inventoryScreen)
            || !inventoryScreen.IsInsideTree()
            || inventoryScreen is not CanvasItem inventoryCanvas
            || !inventoryCanvas.IsVisibleInTree()
            || inventoryScreen.Inventory is not { } inventory
            || !HasVerifiedVisiblePotionBelt(state))
        {
            return null;
        }

        return inventory;
    }

    private static bool CanExposeMerchantPotionActions(
        RunState state,
        MerchantInventory inventory) =>
        ReferenceEquals(TryGetInteractableTopMerchant(state), inventory);

    private static bool HasVerifiedVisiblePotionBelt(RunState state)
    {
        var belt = NRun.Instance?.GlobalUi?.TopBar?.PotionContainer;
        if (belt is null || !GodotObject.IsInstanceValid(belt)
            || !belt.IsInsideTree() || !belt.IsVisibleInTree()
            || state.Players.Count != 1)
        {
            return false;
        }

        var holders = Descendants<NPotionHolder>(belt)
            .Where(holder => GodotObject.IsInstanceValid(holder)
                             && holder.IsInsideTree()
                             && holder.IsVisibleInTree())
            .ToArray();
        foreach (var potion in state.Players[0].PotionSlots.Where(potion => potion is not null))
        {
            if (holders.Count(holder => ReferenceEquals(holder.Potion?.Model, potion)) != 1)
            {
                return false;
            }
        }

        return true;
    }

    private static bool HasPotentialOutsidePotionAction(RunState state) =>
        state.Players.Count == 1
        && !state.Players[0].Creature.IsDead
        && state.Players[0].CanUseOrRemovePotions
        && state.Players[0].PotionSlots.Any(potion =>
            potion is not null && !potion.IsQueued
            && !potion.HasBeenRemovedFromState);

    private static bool CanProceedRewards(NRewardsScreen? onlyScreen = null)
    {
        var screens = onlyScreen is null
            ? FindActiveNodes<NRewardsScreen>()
            : [onlyScreen];
        return screens
            .Where(screen => GodotObject.IsInstanceValid(screen) && screen.IsInsideTree())
            .SelectMany(Descendants<NProceedButton>)
            .Any(button => button.IsEnabled && button.IsVisibleInTree());
    }

    private static IReadOnlyList<CardModel> FindVisibleCardChoices() =>
        FindActiveNodes<NCardHolder>()
            .Select(holder => holder.CardNode?.Model)
            .Where(card => card is not null)
            .Cast<CardModel>()
            .Distinct<CardModel>(ReferenceEqualityComparer.Instance)
            .ToArray();

    internal static IReadOnlyList<T> FindActiveNodes<T>() where T : Node
    {
        if (Engine.GetMainLoop() is not SceneTree tree)
        {
            return [];
        }

        return Descendants<T>(tree.Root)
            .Where(node => GodotObject.IsInstanceValid(node)
                           && node.IsInsideTree()
                           && (node is not CanvasItem item || item.IsVisibleInTree()))
            .ToArray();
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

    private static SerializableRun? TryGetNativeSave()
    {
        try
        {
            return RunManager.Instance.IsInProgress
                ? RunManager.Instance.ToSave(null)
                : null;
        }
        catch
        {
            return null;
        }
    }

    private static void OnTreeExiting()
    {
        _stopping = true;
        try
        {
            DrainCompletedSelectors();
            _episodes?.EndProcessSegment("process_exit");
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] process-exit flush failed: {exception}");
        }
        finally
        {
            DetachRunInputs();
            _episodes?.Dispose();
        }
    }

    private static void DisableAfterFailure(string operation, Exception exception)
    {
        _stopping = true;
        Console.Error.WriteLine(
            $"[SlayTheModel/Collector] {operation} failed; collector stopped: {exception}");
        GD.PushError($"[SlayTheModel/Collector] {operation} failed: {exception}");
        try
        {
            _episodes?.RecordDiagnostic("collector_failure", new
            {
                operation,
                error = exception.ToString(),
            });
            _episodes?.EndProcessSegment("collector_error");
        }
        catch (Exception flushError)
        {
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] error flush also failed: {flushError}");
        }
    }
}
