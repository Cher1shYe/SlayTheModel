using System.Reflection;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Actions;
using MegaCrit.Sts2.Core.Entities.Rewards;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.Events.Custom;
using MegaCrit.Sts2.Core.Nodes.Ftue;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Saves.Managers;
using SlayTheModel.Collector;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Hooks native semantic entry points, not mouse coordinates. Prefixes freeze
/// the observation before the game mutates it; postfixes/continuations record
/// whether the corresponding native operation actually completed.
/// </summary>
internal static class CollectorHarmony
{
    private static readonly Harmony Patcher = new("SlayTheModel.DataCollector.v1");
    [ThreadStatic] private static NativeActionCapture? _merchantLeaveInFlight;
    [ThreadStatic] private static NativeActionCapture? _rewardsProceedInFlight;
    private static bool _installed;

    internal static void Install()
    {
        if (_installed)
        {
            return;
        }

        _installed = true;

        PatchRequired(
            Method(typeof(RunManager), nameof(RunManager.SetUpNewSingleplayer),
                typeof(RunState), typeof(bool), typeof(DateTimeOffset?)),
            prefix: nameof(NewRunPrefix));
        PatchRequired(
            Method(typeof(RunManager), nameof(RunManager.SetUpSavedSingleplayer),
                typeof(RunState), typeof(SerializableRun)),
            prefix: nameof(LoadedRunPrefix));
        PatchRequired(
            Method(typeof(SaveManager), nameof(SaveManager.SaveRunHistory),
                typeof(RunHistory)),
            postfix: nameof(RunHistoryPostfix));
        PatchObserved(
            Method(typeof(RunSaveManager), nameof(RunSaveManager.SaveRun),
                typeof(SerializableRun), typeof(bool)),
            nameof(NativeSavePrefix),
            nameof(NativeSavePostfix),
            nameof(NativeSaveFinalizer));
        PatchRequired(
            Method(typeof(PlayerChoiceSynchronizer),
                nameof(PlayerChoiceSynchronizer.ReserveChoiceId), typeof(Player)),
            postfix: nameof(NativeChoiceIdReservedPostfix));
        PatchRequired(
            Method(typeof(GameAction), nameof(GameAction.Cancel)),
            prefix: nameof(GameActionCancelPrefix),
            postfix: nameof(GameActionCancelPostfix));

        PatchObserved(
            Method(typeof(EventSynchronizer), nameof(EventSynchronizer.ChooseLocalOption),
                typeof(int)),
            nameof(EventPrefix), nameof(VoidPostfix), nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(RestSiteSynchronizer), nameof(RestSiteSynchronizer.ChooseLocalOption),
                typeof(int)),
            nameof(RestPrefix), nameof(BoolTaskPostfix), nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(MapSelectionSynchronizer),
                nameof(MapSelectionSynchronizer.PlayerVotedForMapCoord),
                typeof(Player), typeof(MapLocation), typeof(MapVote?)),
            nameof(MapPrefix), nameof(VoidPostfix), nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(TreasureRoomRelicSynchronizer),
                nameof(TreasureRoomRelicSynchronizer.PickRelicLocally), typeof(int?)),
            nameof(TreasurePrefix), nameof(VoidPostfix), nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(RewardsSetSynchronizer),
                nameof(RewardsSetSynchronizer.SelectLocalReward), typeof(Reward)),
            nameof(RewardPrefix), nameof(BoolTaskPostfix), nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NCardRewardSelectionScreen), "OptionSelected"),
            nameof(CardRewardSelectionPrefix),
            nameof(CardRewardSelectionPostfix),
            nameof(CardRewardSelectionFinalizer));
        PatchRequired(
            Method(typeof(NCardRewardSelectionScreen),
                "OnAlternateRewardSelected", typeof(int)),
            prefix: nameof(CardRewardAlternativePrefix));

        PatchObserved(
            Method(typeof(MerchantEntry), nameof(MerchantEntry.OnTryPurchaseWrapper),
                typeof(MerchantInventory), typeof(bool)),
            nameof(MerchantPrefix), nameof(MerchantTaskPostfix),
            nameof(MerchantFinalizer));
        PatchObserved(
            Method(typeof(MerchantCardRemovalEntry),
                nameof(MerchantCardRemovalEntry.OnTryPurchaseWrapper),
                typeof(MerchantInventory), typeof(bool), typeof(bool)),
            nameof(MerchantRemovalPrefix),
            nameof(MerchantTaskPostfix),
            nameof(MerchantFinalizer));
        PatchObserved(
            Method(typeof(NMerchantRoom), "HideScreen", typeof(NButton)),
            nameof(MerchantRoomLeavePrefix),
            nameof(MerchantRoomLeavePostfix),
            nameof(MerchantRoomLeaveFinalizer));
        PatchRequired(
            Method(typeof(NMerchantFtue), nameof(NMerchantFtue.Create),
                typeof(NMerchantRoom)),
            prefix: nameof(MerchantFtueCreatePrefix));
        PatchObserved(
            Method(typeof(NFakeMerchant), "HideScreen", typeof(NButton)),
            nameof(FakeMerchantLeavePrefix),
            nameof(VoidPostfix),
            nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NRewardsScreen), "OnProceedButtonPressed", typeof(NButton)),
            nameof(RewardsProceedPrefix),
            nameof(RewardsProceedPostfix),
            nameof(RewardsProceedFinalizer));
        PatchRequired(
            Method(typeof(NCombatRewardFtue), nameof(NCombatRewardFtue.Create),
                typeof(Control)),
            prefix: nameof(CombatRewardFtueCreatePrefix));
        PatchObserved(
            Method(typeof(NTreasureRoom), "OnChestButtonReleased", typeof(NButton)),
            nameof(TreasureOpenPrefix),
            nameof(VoidPostfix),
            nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NTreasureRoom), "OnProceedButtonPressed", typeof(NButton)),
            nameof(TreasureProceedPrefix),
            nameof(VoidPostfix),
            nameof(NativeFinalizer));

        PatchRequired(
            Method(typeof(NSimpleCardSelectScreen), nameof(NSimpleCardSelectScreen.Create),
                typeof(IReadOnlyList<CardModel>), typeof(CardSelectorPrefs)),
            prefix: nameof(SimpleGridCardsCreatePrefix),
            postfix: nameof(SimpleGridCreatePostfix));
        PatchRequired(
            Method(typeof(NSimpleCardSelectScreen), nameof(NSimpleCardSelectScreen.Create),
                typeof(IReadOnlyList<CardCreationResult>), typeof(CardSelectorPrefs)),
            prefix: nameof(SimpleGridRewardsCreatePrefix),
            postfix: nameof(SimpleGridCreatePostfix));
        PatchObserved(
            Method(typeof(NCardGridSelectionScreen),
                nameof(NCardGridSelectionScreen.CardsSelected)),
            nameof(CardGridPrefix), nameof(CardGridPostfix), nameof(CardGridFinalizer));
        PatchObserved(
            Method(typeof(NChooseACardSelectionScreen),
                nameof(NChooseACardSelectionScreen.CardsSelected)),
            nameof(SingleCardPrefix), nameof(CardGridPostfix), nameof(CardGridFinalizer));
        PatchRequired(
            AccessTools.Method(typeof(NPlayerHand), nameof(NPlayerHand.SelectCards))
            ?? throw new MissingMethodException(typeof(NPlayerHand).FullName, nameof(NPlayerHand.SelectCards)),
            postfix: nameof(HandCardSelectionPostfix));
        PatchRequired(
            Method(typeof(NCombatPileCardSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(CombatPileCardClickedPrefix));
        PatchRequired(
            Method(typeof(NSimpleCardSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(SimpleCardClickedPrefix),
            postfix: nameof(MultiCardClickedPostfix));
        PatchRequired(
            Method(typeof(NDeckCardSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(MultiCardClickedPrefix),
            postfix: nameof(MultiCardClickedPostfix));
        PatchRequired(
            Method(typeof(NDeckCardSelectScreen), "CloseSelection", typeof(NButton)),
            prefix: nameof(MultiCardCancelPrefix));
        PatchRequired(
            Method(typeof(NDeckCardSelectScreen), "CancelSelection", typeof(NButton)),
            postfix: nameof(MultiCardPreviewBackPostfix));
        PatchRequired(
            Method(typeof(NDeckTransformSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(TransformCardClickedPrefix),
            postfix: nameof(MultiCardClickedPostfix));
        PatchRequired(
            Method(typeof(NDeckTransformSelectScreen), "CloseSelection", typeof(NButton)),
            prefix: nameof(TransformClosePrefix));
        PatchRequired(
            Method(typeof(NDeckTransformSelectScreen), "CancelSelection", typeof(NButton)),
            postfix: nameof(TransformPreviewBackPostfix));
        PatchRequired(
            Method(typeof(NDeckTransformSelectScreen), "CompleteSelection", typeof(NButton)),
            prefix: nameof(TransformCompletePrefix));
        PatchRequired(
            Method(typeof(NDeckEnchantSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(EnchantCardClickedPrefix),
            postfix: nameof(MultiCardClickedPostfix));
        PatchRequired(
            Method(typeof(NDeckEnchantSelectScreen), "CloseSelection", typeof(NButton)),
            prefix: nameof(EnchantClosePrefix));
        PatchRequired(
            Method(typeof(NDeckEnchantSelectScreen), "CancelSelection", typeof(NButton)),
            postfix: nameof(EnchantPreviewBackPostfix));
        PatchRequired(
            Method(typeof(NDeckEnchantSelectScreen), "ConfirmSelection", typeof(NButton)),
            prefix: nameof(EnchantConfirmPrefix));
        PatchRequired(
            Method(typeof(NDeckUpgradeSelectScreen), "OnCardClicked", typeof(CardModel)),
            prefix: nameof(UpgradeCardClickedPrefix),
            postfix: nameof(MultiCardClickedPostfix));
        PatchRequired(
            Method(typeof(NDeckUpgradeSelectScreen), "CloseSelection", typeof(NButton)),
            prefix: nameof(UpgradeClosePrefix));
        PatchRequired(
            Method(typeof(NDeckUpgradeSelectScreen), "CancelSelection", typeof(NButton)),
            postfix: nameof(UpgradePreviewBackPostfix));
        PatchRequired(
            Method(typeof(NDeckUpgradeSelectScreen), "ConfirmSelection", typeof(NButton)),
            prefix: nameof(UpgradeConfirmPrefix));
        PatchRequired(
            Method(typeof(NChooseACardSelectionScreen), "SelectHolder", typeof(NCardHolder)),
            prefix: nameof(SingleCardClickedPrefix));
        PatchRequired(
            Method(typeof(NChooseACardSelectionScreen), "OnSkipButtonReleased", typeof(NButton)),
            prefix: nameof(SingleCardSkippedPrefix));
        PatchRequired(
            Method(typeof(NPlayerHand), "SelectCardInSimpleMode", typeof(NHandCardHolder)),
            prefix: nameof(HandCardSelectedPrefix));
        PatchRequired(
            Method(typeof(NPlayerHand), "SelectCardInUpgradeMode", typeof(NHandCardHolder)),
            prefix: nameof(HandCardSelectedPrefix));
        PatchRequired(
            Method(typeof(NPlayerHand), "OnSelectModeConfirmButtonPressed", typeof(NButton)),
            prefix: nameof(HandCardSelectionConfirmPrefix));
        PatchObserved(
            Method(typeof(NChooseABundleSelectionScreen),
                nameof(NChooseABundleSelectionScreen.CardsSelected)),
            nameof(BundleSelectionPrefix),
            nameof(BundleSelectionPostfix),
            nameof(BundleSelectionFinalizer));
        PatchRequired(
            Method(typeof(NChooseABundleSelectionScreen), "OnBundleClicked",
                typeof(NCardBundle)),
            prefix: nameof(BundleClickedPrefix));
        PatchRequired(
            Method(typeof(NChooseABundleSelectionScreen), "CancelSelection",
                typeof(NButton)),
            prefix: nameof(BundlePreviewBackPrefix));
        PatchRequired(
            Method(typeof(NChooseABundleSelectionScreen), "ConfirmSelection",
                typeof(NButton)),
            prefix: nameof(BundleConfirmPrefix));
        PatchObserved(
            Method(typeof(NChooseARelicSelection),
                nameof(NChooseARelicSelection.RelicsSelected)),
            nameof(RelicSelectionPrefix),
            nameof(RelicSelectionPostfix),
            nameof(RelicSelectionFinalizer));
        PatchObserved(
            Method(typeof(NCrystalSphereScreen), "SetSmallDivination", typeof(NButton)),
            nameof(CrystalSphereSmallPrefix),
            nameof(CrystalSphereSmallPostfix),
            nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NCrystalSphereScreen), "SetBigDivination", typeof(NButton)),
            nameof(CrystalSphereBigPrefix),
            nameof(CrystalSphereBigPostfix),
            nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NCrystalSphereScreen), "OnCellClicked",
                typeof(NCrystalSphereCell)),
            nameof(CrystalSphereCellPrefix),
            nameof(CrystalSphereCellPostfix),
            nameof(NativeFinalizer));
        PatchObserved(
            Method(typeof(NCrystalSphereScreen), "OnProceedButtonPressed", typeof(NButton)),
            nameof(CrystalSphereProceedPrefix),
            nameof(VoidPostfix),
            nameof(NativeFinalizer));

        Console.WriteLine("[SlayTheModel/Collector] native observation hooks installed");
    }

    private static MethodInfo Method(Type type, string name, params Type[] parameters) =>
        AccessTools.Method(type, name, parameters)
        ?? throw new MissingMethodException(type.FullName, name);

    private static void PatchRequired(
        MethodInfo original,
        string? prefix = null,
        string? postfix = null) =>
        Patcher.Patch(
            original,
            HarmonyMethod(prefix),
            HarmonyMethod(postfix));

    private static void PatchObserved(
        MethodInfo original,
        string prefix,
        string postfix,
        string finalizer) => Patcher.Patch(
        original,
        HarmonyMethod(prefix),
        HarmonyMethod(postfix),
        finalizer: HarmonyMethod(finalizer));

    private static HarmonyMethod? HarmonyMethod(string? name) => name is null
        ? null
        : new HarmonyMethod(typeof(CollectorHarmony), name);

    private static void NewRunPrefix(RunState state, DateTimeOffset? dailyTime) =>
        CollectorRuntime.PrepareNewRun(state, dailyTime);

    private static void LoadedRunPrefix(RunState state, SerializableRun save) =>
        CollectorRuntime.PrepareLoadedRun(state, save);

    private static void RunHistoryPostfix(RunHistory history) =>
        CollectorRuntime.FinishRun(history);

    private static void NativeSavePrefix(
        SerializableRun save,
        out NativeSaveCheckpoint? __state) =>
        __state = CollectorRuntime.PrepareNativeSaveCheckpoint(save);

    private static void NativeSavePostfix(
        Task __result,
        NativeSaveCheckpoint? __state)
    {
        if (__state is null)
        {
            return;
        }

        if (__result.IsCompleted)
        {
            CollectorRuntime.CompleteNativeSaveCheckpoint(
                __state,
                __result.IsCompletedSuccessfully
                    ? null
                    : __result.Exception?.GetBaseException()
                      ?? new TaskCanceledException(__result));
            return;
        }

        _ = __result.ContinueWith(
            completed => CollectorRuntime.CompleteNativeSaveCheckpoint(
                __state,
                completed.Status == TaskStatus.RanToCompletion
                    ? null
                    : completed.Exception?.GetBaseException()
                      ?? new TaskCanceledException(completed)),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private static Exception? NativeSaveFinalizer(
        Exception? __exception,
        NativeSaveCheckpoint? __state)
    {
        if (__exception is not null)
        {
            CollectorRuntime.CompleteNativeSaveCheckpoint(__state, __exception);
        }

        return __exception;
    }

    private static void EventPrefix(
        EventSynchronizer __instance,
        int index,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureEventChoice(__instance, index);

    private static void RestPrefix(
        RestSiteSynchronizer __instance,
        int index,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureRestSiteChoice(__instance, index);

    private static void MapPrefix(
        Player player,
        MapVote? destination,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureMapChoice(player, destination);

    private static void TreasurePrefix(
        TreasureRoomRelicSynchronizer __instance,
        int? index,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureTreasureChoice(__instance, index);

    private static void RewardPrefix(
        Reward reward,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureRewardChoice(reward);

    private static void CardRewardSelectionPrefix(
        NCardRewardSelectionScreen __instance,
        out PendingCardRewardSelection? __state)
    {
        CollectorRuntime.DrainCompletedSelectors();
        var alternatives = ReadField<IReadOnlyList<CardRewardAlternative>>(
            __instance,
            "_extraOptions");
        var nativeOptions = ReadField<IReadOnlyList<CardCreationResult>>(
            __instance,
            "_options");
        __state = CollectorRuntime.PrepareCardRewardSelection(
            nativeOptions?.Select(option => option.Card).ToArray(),
            alternatives?.Select(alternative => new CardRewardExtraOption(
                alternative.OptionId,
                alternative.OptionId == "Skip"
                && alternative.AfterSelected
                    == PostAlternateCardRewardAction.EndSelectionAndDoNotCompleteReward))
                .ToArray());
    }

    private static void CardRewardSelectionPostfix(
        Task<int?> __result,
        PendingCardRewardSelection? __state)
        => CollectorRuntime.AttachCardRewardSelectionTask(__state, __result);

    private static Exception? CardRewardSelectionFinalizer(
        Exception? __exception,
        PendingCardRewardSelection? __state)
    {
        if (__exception is not null)
        {
            CollectorRuntime.CompleteCardRewardSelection(
                __state,
                null,
                __exception);
        }

        return __exception;
    }

    private static void CardRewardAlternativePrefix(int index) =>
        CollectorRuntime.CaptureCardRewardAlternative(index);

    private static void MerchantPrefix(
        MerchantEntry __instance,
        MerchantInventory inventory,
        out object? __state) =>
        __state = CollectorRuntime.CaptureMerchantChoice(__instance, inventory);

    private static void MerchantRemovalPrefix(
        MerchantCardRemovalEntry __instance,
        MerchantInventory inventory,
        out object? __state) =>
        __state = CollectorRuntime.CaptureMerchantChoice(__instance, inventory);

    private static void MerchantTaskPostfix(Task<bool> __result, object? __state)
    {
        if (__state is NativeActionCapture capture)
        {
            BoolTaskPostfix(__result, capture);
            return;
        }

        if (__state is not PendingUnmatchedMerchantClick pending)
        {
            return;
        }

        if (__result.IsCompleted)
        {
            CollectorRuntime.CompleteUnmatchedMerchantClick(pending, __result);
            return;
        }

        _ = __result.ContinueWith(
            completed => CollectorRuntime.ScheduleOnMainThread(() =>
                CollectorRuntime.CompleteUnmatchedMerchantClick(pending, completed)),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private static Exception? MerchantFinalizer(
        Exception? __exception,
        object? __state)
    {
        if (__exception is not null)
        {
            if (__state is NativeActionCapture capture)
            {
                CollectorRuntime.CompleteNativeAction(capture, __exception);
            }
            else if (__state is PendingUnmatchedMerchantClick pending)
            {
                CollectorRuntime.CompleteUnmatchedMerchantClick(
                    pending, nativeTask: null, nativeException: __exception);
            }
        }

        return __exception;
    }

    private static void MerchantRoomLeavePrefix(
        NMerchantRoom __instance,
        out NativeActionCapture? __state)
    {
        __state = CollectorRuntime.CaptureMerchantLeave(__instance.Inventory);
        _merchantLeaveInFlight = __state;
    }

    private static void MerchantRoomLeavePostfix(NativeActionCapture? __state)
    {
        if (ReferenceEquals(_merchantLeaveInFlight, __state))
        {
            _merchantLeaveInFlight = null;
        }
        VoidPostfix(__state);
    }

    private static Exception? MerchantRoomLeaveFinalizer(
        Exception? __exception,
        NativeActionCapture? __state)
    {
        if (ReferenceEquals(_merchantLeaveInFlight, __state))
        {
            _merchantLeaveInFlight = null;
        }
        return NativeFinalizer(__exception, __state);
    }

    private static void MerchantFtueCreatePrefix()
    {
        // The first press of the merchant room's Proceed button can be
        // consumed solely by the tutorial. It did not leave the room, so keep
        // the attempted action as a clean cancellation rather than a false
        // successful leave label.
        CollectorRuntime.CompleteNativeAction(
            _merchantLeaveInFlight,
            CollectorExecutionStatus.Cancelled,
            "merchant tutorial intercepted the leave request");
    }

    private static void FakeMerchantLeavePrefix(
        NFakeMerchant __instance,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureMerchantLeave(__instance.Inventory);

    private static void RewardsProceedPrefix(
        NRewardsScreen __instance,
        out NativeActionCapture? __state)
    {
        __state = CollectorRuntime.CaptureRewardsProceed(__instance);
        _rewardsProceedInFlight = __state;
    }

    private static void RewardsProceedPostfix(NativeActionCapture? __state)
    {
        if (ReferenceEquals(_rewardsProceedInFlight, __state))
        {
            _rewardsProceedInFlight = null;
        }
        VoidPostfix(__state);
    }

    private static Exception? RewardsProceedFinalizer(
        Exception? __exception,
        NativeActionCapture? __state)
    {
        if (ReferenceEquals(_rewardsProceedInFlight, __state))
        {
            _rewardsProceedInFlight = null;
        }
        return NativeFinalizer(__exception, __state);
    }

    private static void CombatRewardFtueCreatePrefix()
    {
        // Likewise, the first attempt to skip remaining combat rewards can
        // only open the FTUE. The run stays on the reward screen.
        CollectorRuntime.CompleteNativeAction(
            _rewardsProceedInFlight,
            CollectorExecutionStatus.Cancelled,
            "combat reward tutorial intercepted the proceed request");
    }

    private static void TreasureOpenPrefix(
        NTreasureRoom __instance,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureTreasureRoomAction(
            __instance,
            SlayTheModel.Sts2.Protocol.OutsideCombatActionKind.OpenChest);

    private static void TreasureProceedPrefix(
        NTreasureRoom __instance,
        out NativeActionCapture? __state)
    {
        // In skip mode this callback synchronously delegates to
        // PickRelicLocally(null), whose semantic hook records the skip. Do not
        // also emit a second treasure-room Proceed for the same click.
        __state = __instance.ProceedButton is { IsSkip: true }
            ? null
            : CollectorRuntime.CaptureTreasureRoomAction(
                __instance,
                SlayTheModel.Sts2.Protocol.OutsideCombatActionKind.Proceed);
    }

    private static void VoidPostfix(NativeActionCapture? __state)
    {
        // These native entry points commonly enqueue one or more GameActions;
        // returning from the void method is not an effect-completion signal.
        // CollectorRuntime resolves the capture at the next stable semantic
        // boundary (next decision, combat start, native save, or run finish).
        CollectorRuntime.MarkNativeActionAccepted(__state);
    }

    private static void BoolTaskPostfix(
        Task<bool> __result,
        NativeActionCapture? __state)
    {
        if (__state is null)
        {
            return;
        }

        if (__result.IsCompleted)
        {
            CompleteBoolTask(__state, __result);
            return;
        }

        _ = __result.ContinueWith(
            completed => CollectorRuntime.ScheduleOnMainThread(() =>
                CompleteBoolTask(__state, completed)),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private static void CompleteBoolTask(
        NativeActionCapture capture,
        Task<bool> completed)
    {
        if (!CollectorRuntime.IsCurrentCapture(capture))
        {
            return;
        }

        var succeeded = completed.Status == TaskStatus.RanToCompletion
                        && completed.Result;
        if (capture.IsCompleted)
        {
            if (!succeeded
                && !(capture.NestedSelectorObserved
                     && completed.Status is TaskStatus.RanToCompletion
                         or TaskStatus.Canceled))
            {
                var detail = completed.Exception?.GetBaseException().ToString()
                             ?? $"Native parent task ended with {completed.Status}"
                             + (completed.Status == TaskStatus.RanToCompletion
                                 ? $" result={completed.Result}"
                                 : string.Empty);
                var failedBeforeSettlement =
                    CollectorRuntime.FailStagedAcceptedAction(capture, detail);
                CollectorRuntime.RecordCoverageGap(
                    "accepted_parent_task_later_failed",
                    new
                    {
                        capture.Description,
                        decision_id = capture.Draft.Receipt.DecisionId,
                        attempt_id = capture.Draft.AttemptId,
                        failed_before_settlement = failedBeforeSettlement,
                        status = completed.Status.ToString(),
                        result = completed.Status == TaskStatus.RanToCompletion
                            ? completed.Result
                            : (bool?)null,
                        error = completed.Exception?.GetBaseException().ToString(),
                    },
                    invalidatePendingDecision: false,
                    relatedDecisionId: capture.Draft.Receipt.DecisionId,
                    relatedAttemptId: capture.Draft.AttemptId);
            }
            return;
        }

        if (succeeded)
        {
            // A successful Task<bool> confirms acceptance, but some native
            // paths still enqueue their actual effects. Defer execution and
            // reward until CollectorRuntime observes a stable boundary.
            CollectorRuntime.MarkNativeActionAccepted(capture);
            return;
        }

        CollectorRuntime.CompleteNativeAction(
            capture,
            succeeded
                ? CollectorExecutionStatus.Applied
                : completed.Status == TaskStatus.RanToCompletion || completed.IsCanceled
                    ? CollectorExecutionStatus.Cancelled
                    : CollectorExecutionStatus.Failed,
            succeeded
                ? null
                : completed.Status == TaskStatus.RanToCompletion
                    ? "native task returned false"
                    : completed.Exception?.GetBaseException().Message
                      ?? "native task cancelled");
    }

    private static Exception? NativeFinalizer(
        Exception? __exception,
        NativeActionCapture? __state)
    {
        if (__exception is not null)
        {
            CollectorRuntime.CompleteNativeAction(__state, __exception);
        }

        return __exception;
    }

    private static void CardGridPrefix(
        NCardGridSelectionScreen __instance,
        out object? __state)
    {
        CollectorRuntime.DrainCompletedSelectors();
        var prefs = ReadValueField<CardSelectorPrefs>(__instance, "_prefs");
        var contextId = SelectorContext(__instance, prefs);
        if (prefs is null)
        {
            if (CombatManager.Instance.IsInProgress)
            {
                CollectorRuntime.NoteUncapturedCombatCardSelector();
            }

            CollectorRuntime.RecordCoverageGap(
                "card_selector_preferences_unavailable",
                new { contextId });
            __state = null;
            return;
        }

        if (CombatManager.Instance.IsInProgress)
        {
            IReadOnlyList<CardModel> cards;
            if (__instance is NCombatPileCardSelectScreen pileScreen)
            {
                if (!CollectorCombatChoiceOptions.TryFreezePile(
                        pileScreen, out cards, out var reason)
                    && reason != "combat_choice_has_no_legal_cards")
                {
                    CollectorRuntime.NoteUncapturedCombatCardSelector();
                    CollectorRuntime.RecordCoverageGap(
                        "combat_choice_options_unavailable",
                        new { contextId, reason },
                        invalidatePendingDecision: false);
                    __state = null;
                    return;
                }
            }
            else
            {
                cards = ReadField<IReadOnlyList<CardModel>>(__instance, "_cards") ?? [];
            }

            __state = CollectorRuntime.PrepareCombatCardChoice(
                __instance,
                cards,
                prefs.Value.MinSelect,
                prefs.Value.MaxSelect,
                prefs.Value.Cancelable,
                expectsNativeCombatCardResult: __instance is NCombatPileCardSelectScreen,
                contextId,
                requiresManualConfirmation: prefs.Value.RequireManualConfirmation);
            return;
        }

        if (__instance is NDeckEnchantSelectScreen enchantScreen)
        {
            if (!TryVisibleEnchantmentContext(
                    enchantScreen, out var enchantmentContext, out var reason))
            {
                CollectorRuntime.RecordCoverageGap(
                    "enchantment_choice_effect_unavailable",
                    new { contextId, reason },
                    invalidatePendingDecision: false);
                __state = null;
                return;
            }

            contextId = $"{contextId}:{enchantmentContext}";
        }

        var outsideCards = ReadField<IReadOnlyList<CardModel>>(__instance, "_cards") ?? [];
        var removalSelection = __instance is not NDeckEnchantSelectScreen
            && contextId.Contains(
            "remove",
            StringComparison.OrdinalIgnoreCase);
        __state = (prefs.Value.MaxSelect > 1
                   || __instance is NDeckEnchantSelectScreen)
            ? CollectorRuntime.PrepareMultiCardSelection(
                __instance,
                outsideCards,
                prefs.Value.MinSelect,
                prefs.Value.MaxSelect,
                prefs.Value.RequireManualConfirmation,
                prefs.Value.Cancelable,
                removalSelection,
                contextId)
            : CollectorRuntime.PrepareCardSelection(
                outsideCards,
                prefs.Value.MinSelect,
                prefs.Value.MaxSelect,
                prefs.Value.RequireManualConfirmation,
                prefs.Value.Cancelable,
                removalSelection,
                contextId);
    }

    private static void SimpleGridCardsCreatePrefix(
        IReadOnlyList<CardModel> __0,
        out CardModel[] __state) =>
        __state = __0.ToArray();

    private static void SimpleGridRewardsCreatePrefix(
        IReadOnlyList<CardCreationResult> __0,
        out CardModel[] __state) =>
        __state = __0.Select(result => result.Card).ToArray();

    private static void SimpleGridCreatePostfix(
        NSimpleCardSelectScreen __result,
        CardModel[] __state) =>
        CollectorRuntime.RegisterSimpleGridOriginalOrder(__result, __state);

    private static void SingleCardPrefix(
        NChooseACardSelectionScreen __instance,
        out object? __state)
    {
        CollectorRuntime.DrainCompletedSelectors();
        var cards = ReadField<IReadOnlyList<CardModel>>(__instance, "_cards") ?? [];
        var canSkip = ReadField<object>(__instance, "_canSkip") is true;
        if (CombatManager.Instance.IsInProgress)
        {
            __state = CollectorRuntime.PrepareCombatCardChoice(
                __instance,
                cards,
                canSkip ? 0 : 1,
                1,
                canSkip,
                expectsNativeCombatCardResult: false,
                $"card_choice:{__instance.GetType().FullName}");
            return;
        }

        __state = CollectorRuntime.PrepareSingleCardSelection(
            cards,
            canSkip,
            $"card_choice:{__instance.GetType().FullName}");
    }

    private static void BundleSelectionPrefix(
        NChooseABundleSelectionScreen __instance,
        out PendingBundleSelection? __state) =>
        __state = CollectorRuntime.BeginBundleSelection(__instance);

    private static void BundleSelectionPostfix(
        Task<IEnumerable<IReadOnlyList<CardModel>>> __result,
        PendingBundleSelection? __state) =>
        CollectorRuntime.AttachBundleSelectionTask(__state, __result);

    private static Exception? BundleSelectionFinalizer(
        Exception? __exception,
        PendingBundleSelection? __state)
    {
        if (__exception is not null)
        {
            CollectorRuntime.CompleteBundleSelection(__state, null, __exception);
        }

        return __exception;
    }

    private static void BundleClickedPrefix(
        NChooseABundleSelectionScreen __instance,
        NCardBundle bundleNode) =>
        CollectorRuntime.ObserveBundleClicked(
            __instance,
            bundleNode,
            ReadField<IReadOnlyList<IReadOnlyList<CardModel>>>(__instance, "_bundles"),
            ReadField<Control>(__instance, "_bundleRow"));

    private static void BundlePreviewBackPrefix(
        NChooseABundleSelectionScreen __instance) =>
        CollectorRuntime.ObserveBundlePreviewBack(__instance);

    private static void BundleConfirmPrefix(
        NChooseABundleSelectionScreen __instance) =>
        CollectorRuntime.ObserveBundleConfirmed(
            __instance,
            ReadField<NCardBundle>(__instance, "_selectedBundle"));

    private static void CardGridPostfix(
        Task<IEnumerable<CardModel>> __result,
        object? __state)
    {
        switch (__state)
        {
            case PendingCardSelection outside:
                CollectorRuntime.AttachCardSelectionTask(outside, __result);
                break;
            case PendingMultiCardSelection multi:
                CollectorRuntime.AttachMultiCardSelectionTask(multi, __result);
                break;
            case PendingCombatCardChoice combat:
                CollectorRuntime.AttachCombatChoiceTask(combat, __result);
                break;
        }
    }

    private static Exception? CardGridFinalizer(
        Exception? __exception,
        object? __state)
    {
        if (__exception is not null)
        {
            switch (__state)
            {
                case PendingCardSelection outside:
                    CollectorRuntime.CompleteCardSelection(outside, null, __exception);
                    break;
                case PendingMultiCardSelection multi:
                    CollectorRuntime.CompleteMultiCardSelection(multi, null, __exception);
                    break;
                case PendingCombatCardChoice combat:
                    CollectorRuntime.CompleteCombatChoice(combat, null, __exception);
                    break;
            }
        }

        return __exception;
    }

    private static void HandCardSelectionPostfix(
        NPlayerHand __instance,
        CardSelectorPrefs __0,
        Func<CardModel, bool> __1,
        AbstractModel __2,
        NPlayerHand.Mode __3,
        Task<IEnumerable<CardModel>> __result)
    {
        if (!CombatManager.Instance.IsInProgress)
        {
            return;
        }

        if (!CollectorCombatChoiceOptions.TryFreezeHand(
                __instance, __1, out var options, out var reason)
            && reason != "combat_choice_has_no_legal_cards")
        {
            CollectorRuntime.NoteUncapturedCombatCardSelector();
            CollectorRuntime.RecordCoverageGap(
                "combat_hand_choice_options_unavailable",
                new { reason },
                invalidatePendingDecision: false);
            return;
        }

        var pending = CollectorRuntime.PrepareCombatCardChoice(
            __instance,
            options,
            __0.MinSelect,
            __0.MaxSelect,
            __0.Cancelable,
            expectsNativeCombatCardResult: true,
            $"combat_hand_card_selection:{__2?.Id}:{__3}",
            requiresManualConfirmation: __0.RequireManualConfirmation);
        CollectorRuntime.AttachCombatChoiceTask(pending, __result);
    }

    private static void CombatPileCardClickedPrefix(NCombatPileCardSelectScreen __instance) =>
        CollectorRuntime.MarkCombatChoiceManualInput(__instance);

    private static void SimpleCardClickedPrefix(
        NSimpleCardSelectScreen __instance,
        CardModel __0)
    {
        CollectorRuntime.MarkCombatChoiceManualInput(__instance);
        CollectorRuntime.VerifyMultiCardVisibleClick(__instance, __0);
        CollectorRuntime.ObserveMultiCardClickBefore(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));
    }

    private static void MultiCardClickedPrefix(
        NDeckCardSelectScreen __instance,
        CardModel __0)
    {
        CollectorRuntime.VerifyMultiCardVisibleClick(__instance, __0);
        CollectorRuntime.ObserveMultiCardClickBefore(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));
    }

    private static void EnchantCardClickedPrefix(
        NDeckEnchantSelectScreen __instance,
        CardModel __0)
    {
        CollectorRuntime.VerifyMultiCardVisibleClick(__instance, __0);
        CollectorRuntime.ObserveMultiCardClickBefore(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));
    }

    private static void TransformCardClickedPrefix(
        NDeckTransformSelectScreen __instance,
        CardModel __0) =>
        CollectorRuntime.ObserveMultiCardClickBefore(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void MultiCardClickedPostfix(
        NCardGridSelectionScreen __instance,
        CardModel __0) =>
        CollectorRuntime.ObserveMultiCardClick(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void MultiCardCancelPrefix(NDeckCardSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardCancel(__instance);

    private static void MultiCardPreviewBackPostfix(NDeckCardSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardPreviewBack(
            __instance,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void TransformClosePrefix(NDeckTransformSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardInternalCancel(__instance);

    private static void TransformPreviewBackPostfix(NDeckTransformSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardPreviewBack(
            __instance,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void TransformCompletePrefix(NDeckTransformSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardInternalConfirm(
            __instance,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void EnchantClosePrefix(NDeckEnchantSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardCancel(__instance);

    private static void EnchantPreviewBackPostfix(NDeckEnchantSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardPreviewBack(
            __instance,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void EnchantConfirmPrefix(
        NDeckEnchantSelectScreen __instance,
        NButton __0) =>
        CollectorRuntime.ObserveMultiCardManualConfirm(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void UpgradeCardClickedPrefix(
        NDeckUpgradeSelectScreen __instance,
        CardModel __0)
    {
        CollectorRuntime.VerifyMultiCardVisibleClick(__instance, __0);
        CollectorRuntime.ObserveMultiCardClickBefore(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));
    }

    private static void UpgradeClosePrefix(NDeckUpgradeSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardCancel(__instance);

    private static void UpgradePreviewBackPostfix(NDeckUpgradeSelectScreen __instance) =>
        CollectorRuntime.ObserveMultiCardPreviewBack(
            __instance,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void UpgradeConfirmPrefix(
        NDeckUpgradeSelectScreen __instance,
        NButton __0) =>
        CollectorRuntime.ObserveMultiCardManualConfirm(
            __instance,
            __0,
            ReadField<HashSet<CardModel>>(__instance, "_selectedCards"));

    private static void SingleCardClickedPrefix(NChooseACardSelectionScreen __instance) =>
        CollectorRuntime.MarkCombatChoiceManualInput(__instance);

    private static void SingleCardSkippedPrefix(NChooseACardSelectionScreen __instance) =>
        CollectorRuntime.MarkCombatChoiceManualInput(__instance);

    private static void HandCardSelectedPrefix(NPlayerHand __instance) =>
        CollectorRuntime.MarkCombatChoiceManualInput(__instance);

    private static void HandCardSelectionConfirmPrefix(NPlayerHand __instance) =>
        CollectorRuntime.ObserveHandChoiceConfirmation(
            __instance,
            ReadField<IReadOnlyList<CardModel>>(__instance, "_selectedCards"));

    private static void NativeChoiceIdReservedPostfix(Player player, uint __result)
    {
        CollectorRuntime.NoteReservedNativeChoiceId(player, __result);
        CollectorRuntime.NoteReservedBundleChoiceId(player, __result);
        CollectorRuntime.NoteReservedMultiCardChoiceId(player, __result);
    }

    private static void GameActionCancelPrefix(
        GameAction __instance,
        out GameActionState __state) =>
        __state = __instance.State;

    private static void GameActionCancelPostfix(
        GameAction __instance,
        GameActionState __state) =>
        CollectorRuntime.OnNativeCombatActionCancelled(__instance, __state);

    private static void RelicSelectionPrefix(
        NChooseARelicSelection __instance,
        out PendingRelicSelection? __state)
    {
        CollectorRuntime.DrainCompletedSelectors();
        var relics = ReadField<IReadOnlyList<RelicModel>>(__instance, "_relics") ?? [];
        var skip = ReadField<object>(__instance, "_skipButton") is CanvasItem
        {
            Visible: true,
        };
        __state = CollectorRuntime.PrepareRelicSelection(
            relics,
            skip,
            $"relic_choice:{__instance.GetType().FullName}");
    }

    private static void RelicSelectionPostfix(
        Task<IEnumerable<RelicModel>> __result,
        PendingRelicSelection? __state)
        => CollectorRuntime.AttachRelicSelectionTask(__state, __result);

    private static Exception? RelicSelectionFinalizer(
        Exception? __exception,
        PendingRelicSelection? __state)
    {
        if (__exception is not null)
        {
            CollectorRuntime.CompleteRelicSelection(__state, null, __exception);
        }

        return __exception;
    }

    private static void CrystalSphereSmallPrefix(
        NCrystalSphereScreen __instance,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureCrystalSphereTool(__instance, big: false);

    private static void CrystalSphereSmallPostfix(
        NCrystalSphereScreen __instance,
        NativeActionCapture? __state) =>
        CollectorRuntime.CompleteCrystalSphereTool(__state, __instance, big: false);

    private static void CrystalSphereBigPrefix(
        NCrystalSphereScreen __instance,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureCrystalSphereTool(__instance, big: true);

    private static void CrystalSphereBigPostfix(
        NCrystalSphereScreen __instance,
        NativeActionCapture? __state) =>
        CollectorRuntime.CompleteCrystalSphereTool(__state, __instance, big: true);

    private static void CrystalSphereCellPrefix(
        NCrystalSphereScreen __instance,
        NCrystalSphereCell cell,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureCrystalSphereCell(__instance, cell);

    private static void CrystalSphereCellPostfix(
        Task __result,
        NativeActionCapture? __state) =>
        CollectorRuntime.AttachCrystalSphereCellTask(__state, __result);

    private static void CrystalSphereProceedPrefix(
        NCrystalSphereScreen __instance,
        out NativeActionCapture? __state) =>
        __state = CollectorRuntime.CaptureCrystalSphereProceed(__instance);

    private static string SelectorContext(Node screen, CardSelectorPrefs? prefs)
    {
        var prompt = prefs?.Prompt;
        return prompt is not null
               && !string.IsNullOrWhiteSpace(prompt.LocTable)
               && !string.IsNullOrWhiteSpace(prompt.LocEntryKey)
            ? $"card_selection:{prompt.LocTable}:{prompt.LocEntryKey}"
            : $"card_selection:{screen.GetType().FullName}";
    }

    private static bool TryVisibleEnchantmentContext(
        NDeckEnchantSelectScreen screen,
        out string context,
        out string reason)
    {
        context = string.Empty;
        reason = "enchantment_ui_unavailable";
        try
        {
            if (!GodotObject.IsInstanceValid(screen) || !screen.IsInsideTree()
                || !screen.IsVisibleInTree()
                || ReadField<EnchantmentModel>(screen, "_enchantment")
                    is not { } enchantment
                || ReadValueField<int>(screen, "_enchantmentAmount")
                    is not { } amount
                || ReadField<Control>(screen, "_enchantmentTitle")
                    is not { } title
                || !title.IsVisibleInTree()
                || ReadField<Control>(screen, "_enchantmentDescription")
                    is not { } description
                || !description.IsVisibleInTree()
                || ReadField<TextureRect>(screen, "_enchantmentIcon")
                    is not { } icon
                || !icon.IsVisibleInTree() || icon.Texture is null)
            {
                return false;
            }

            // The native screen renders these three UI fields from a mutable
            // copy of the same enchantment and amount in _Ready. Check the
            // actual visible text and image before exposing their semantic ID.
            var displayed = enchantment.ToMutable();
            displayed.Amount = amount;
            displayed.RecalculateValues();
            var titleText = title.Get("text").AsString();
            var descriptionText = description.Get("text").AsString();
            var displayedIcon = displayed.Icon;
            var iconMatches = ReferenceEquals(icon.Texture, displayedIcon)
                || !string.IsNullOrWhiteSpace(icon.Texture.ResourcePath)
                   && string.Equals(icon.Texture.ResourcePath,
                       displayedIcon?.ResourcePath, StringComparison.Ordinal);
            if (!string.Equals(titleText, displayed.Title.GetFormattedText(),
                    StringComparison.Ordinal)
                || !string.Equals(descriptionText,
                    displayed.DynamicDescription.GetFormattedText(),
                    StringComparison.Ordinal)
                || !iconMatches)
            {
                reason = "enchantment_ui_does_not_match_native_effect";
                return false;
            }

            // All native enchantments use this screen and the same visible
            // title/description/icon rendering path. The raw Amount is not
            // necessarily shown: some enchantments ignore it altogether.
            // Only include its exact value when the visible text directly
            // substitutes that integer. A change between adjacent amounts
            // alone could instead expose only a range or a derived effect.
            var amountContext = "unobserved";
            try
            {
                bool ShowsExactAmountComparedWith(int otherAmount)
                {
                    var alternate = enchantment.ToMutable();
                    alternate.Amount = otherAmount;
                    alternate.RecalculateValues();
                    var visibleText = titleText + "\n" + descriptionText;
                    var alternateText = alternate.Title.GetFormattedText()
                        + "\n" + alternate.DynamicDescription.GetFormattedText();
                    var currentNumber = amount.ToString(
                        System.Globalization.CultureInfo.InvariantCulture);
                    var otherNumber = otherAmount.ToString(
                        System.Globalization.CultureInfo.InvariantCulture);
                    var currentPattern = $@"(?<!\d){currentNumber}(?!\d)";
                    var otherPattern = $@"(?<!\d){otherNumber}(?!\d)";
                    return !string.Equals(visibleText, alternateText,
                               StringComparison.Ordinal)
                        && System.Text.RegularExpressions.Regex.IsMatch(
                            visibleText, currentPattern)
                        && System.Text.RegularExpressions.Regex.IsMatch(
                            alternateText, otherPattern)
                        && string.Equals(
                            System.Text.RegularExpressions.Regex.Replace(
                                visibleText, currentPattern, "{amount}"),
                            System.Text.RegularExpressions.Regex.Replace(
                                alternateText, otherPattern, "{amount}"),
                            StringComparison.Ordinal);
                }

                var visibleAtLowerAmount = amount == int.MinValue
                    || ShowsExactAmountComparedWith(amount - 1);
                var visibleAtHigherAmount = amount == int.MaxValue
                    || ShowsExactAmountComparedWith(amount + 1);
                if (visibleAtLowerAmount && visibleAtHigherAmount)
                {
                    amountContext = amount.ToString(System.Globalization.CultureInfo.InvariantCulture);
                }
            }
            catch (Exception exception) when (exception is not OutOfMemoryException)
            {
                // Failed counterfactual rendering does not invalidate the
                // already checked live UI, but cannot justify exposing Amount.
            }

            // Keep the actual localized UI text even when its numeric effect
            // cannot be reduced to the native Amount. This also preserves
            // visible differences between effects sharing the same ID.
            context = $"enchantment:{enchantment.Id}:amount:{amountContext}"
                + $":visible_title:{Uri.EscapeDataString(titleText)}"
                + $":visible_description:{Uri.EscapeDataString(descriptionText)}";
            reason = string.Empty;
            return true;
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            reason = $"enchantment_ui_check_failed:{exception.GetType().Name}";
            return false;
        }
    }

    private static T? ReadField<T>(object instance, string name) where T : class
    {
        for (var type = instance.GetType(); type is not null; type = type.BaseType)
        {
            var field = type.GetField(
                name,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.DeclaredOnly);
            if (field?.GetValue(instance) is T value)
            {
                return value;
            }
        }

        return null;
    }

    private static T? ReadValueField<T>(object instance, string name) where T : struct
    {
        for (var type = instance.GetType(); type is not null; type = type.BaseType)
        {
            var field = type.GetField(
                name,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.DeclaredOnly);
            if (field?.GetValue(instance) is T value)
            {
                return value;
            }
        }

        return null;
    }
}
