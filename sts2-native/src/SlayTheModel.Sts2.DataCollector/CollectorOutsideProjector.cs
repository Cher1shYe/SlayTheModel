using System.Security.Cryptography;
using System.Text;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Potions;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed record MerchantEntryEvidence(
    string NativeType,
    string? ActionKind,
    string? Target,
    int Cost,
    bool IsStocked,
    bool EnoughGold);

/// <summary>
/// Converts native outside-combat state into the same stable DTOs used by a
/// future learned policy. All Godot controls and mutable game objects remain on
/// the game thread and never cross the JSONL boundary.
/// </summary>
internal static class CollectorOutsideProjector
{
    internal static OutsideCombatDecisionPoint ForEvent(
        RunState state,
        EventSynchronizer synchronizer,
        int selectedNativeIndex,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        var eventModel = synchronizer.GetLocalEvent();
        var bindings = eventModel.CurrentOptions
            .Select((option, nativeIndex) => new { Option = option, NativeIndex = nativeIndex })
            .Where(binding => !binding.Option.IsLocked && !binding.Option.WasChosen)
            .ToArray();
        selectedOrdinal = Array.FindIndex(
            bindings,
            binding => binding.NativeIndex == selectedNativeIndex);
        var actions = bindings
            .Select((binding, ordinal) => Action(
                OutsideCombatActionKind.ChooseEventOption,
                ordinal,
                binding.Option.TextKey))
            .ToArray();
        return Build(
            state,
            OutsideCombatSurfaceKind.Event,
            $"event:{eventModel.Id}",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForRestSite(
        RunState state,
        RestSiteSynchronizer synchronizer,
        int selectedNativeIndex,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        var options = synchronizer.GetLocalOptions();
        var bindings = options
            .Select((option, nativeIndex) => new { Option = option, NativeIndex = nativeIndex })
            .Where(binding => binding.Option.IsEnabled)
            .ToArray();
        selectedOrdinal = Array.FindIndex(
            bindings,
            binding => binding.NativeIndex == selectedNativeIndex);
        var actions = bindings
            .Select((binding, ordinal) => Action(
                OutsideCombatActionKind.ChooseRestSiteOption,
                ordinal,
                binding.Option.OptionId))
            .ToArray();
        return Build(
            state,
            OutsideCombatSurfaceKind.RestSite,
            "rest_site",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForMap(
        RunState state,
        MapCoord selectedCoordinate,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        IEnumerable<MapPoint> reachable;
        if (state.VisitedMapCoords.Count == 0)
        {
            reachable = EnumerateMap(state)
                .Where(point => point.coord.row == 0);
        }
        else
        {
            reachable = state.CurrentMapPoint?.Children ?? [];
        }

        var bindings = reachable
            .OrderBy(point => point.coord.row)
            .ThenBy(point => point.coord.col)
            .ToArray();
        selectedOrdinal = Array.FindIndex(
            bindings,
            point => point.coord.Equals(selectedCoordinate));
        var actions = bindings
            .Select((point, ordinal) => new OutsideCombatActionDescriptor(
                $"travel:{ordinal}:{point.coord.row},{point.coord.col}",
                OutsideCombatActionKind.Travel,
                ordinal,
                point.PointType.ToString(),
                new OutsideMapCoordinate(point.coord.row, point.coord.col)))
            .ToArray();
        return Build(
            state,
            OutsideCombatSurfaceKind.Map,
            "map_travel",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForTreasureRelic(
        RunState state,
        TreasureRoomRelicSynchronizer synchronizer,
        int? selectedNativeIndex,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        var relics = synchronizer.CurrentRelics ?? [];
        var actions = relics
            .Select((relic, ordinal) => Action(
                OutsideCombatActionKind.TakeTreasureRelic,
                ordinal,
                relic.Id.ToString()))
            .Concat(
            [
                Action(
                    OutsideCombatActionKind.Proceed,
                    relics.Count,
                    "skip"),
            ])
            .ToArray();
        selectedOrdinal = selectedNativeIndex is { } index
            ? index
            : actions.Length - 1;
        return Build(
            state,
            OutsideCombatSurfaceKind.Treasure,
            "treasure_relic",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForMerchant(
        RunState state,
        MerchantInventory inventory,
        MerchantEntry? selectedEntry,
        long sourceDecisionIndex,
        out int selectedOrdinal,
        bool includePotionActions = false)
    {
        var bindings = inventory.AllEntries
            .Where(entry => entry.IsStocked && entry.EnoughGold)
            .Select(entry => new
            {
                Entry = entry,
                Kind = MerchantKind(entry),
                Target = MerchantTarget(entry),
            })
            .Where(binding => binding.Kind is not null && binding.Target is not null)
            .ToArray();
        var merchantActions = bindings
            .Select((binding, ordinal) => new OutsideCombatActionDescriptor(
                $"{binding.Kind!.Value.ToString().ToLowerInvariant()}:{ordinal}:{binding.Target}",
                binding.Kind.Value,
                ordinal,
                binding.Target,
                Cost: binding.Entry.Cost))
            .Append(Action(
                OutsideCombatActionKind.LeaveMerchant,
                bindings.Length,
                "leave"))
            .ToArray();
        var actions = includePotionActions
            ? merchantActions.Concat(RewardPotionActions(state, merchantActions.Length)).ToArray()
            : merchantActions;
        selectedOrdinal = selectedEntry is null
            ? merchantActions.Length - 1
            : Array.FindIndex(
                bindings,
                binding => ReferenceEquals(binding.Entry, selectedEntry));
        return Build(
            state,
            OutsideCombatSurfaceKind.Merchant,
            "merchant_inventory",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForMerchantPotion(
        RunState state,
        MerchantInventory inventory,
        OutsideCombatActionKind selectedKind,
        int potionSlotIndex,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        if (selectedKind is not (OutsideCombatActionKind.UsePotion
            or OutsideCombatActionKind.DiscardPotion))
        {
            throw new ArgumentOutOfRangeException(nameof(selectedKind));
        }

        var decision = ForMerchant(
            state,
            inventory,
            selectedEntry: null,
            sourceDecisionIndex,
            out _,
            includePotionActions: true);
        selectedOrdinal = decision.LegalActions
            .Select((action, index) => (action, index))
            .Where(entry => entry.action.Kind == selectedKind
                            && entry.action.PotionSlotIndex == potionSlotIndex)
            .Select(entry => entry.index)
            .DefaultIfEmpty(-1)
            .Single();
        if (selectedOrdinal < 0)
        {
            throw new InvalidOperationException(
                "The native potion slot is absent from the frozen Merchant legal set.");
        }

        return decision;
    }

    internal static bool IsLegalMerchantEntry(
        MerchantInventory inventory,
        MerchantEntry selectedEntry) =>
        inventory.AllEntries.Any(entry =>
            ReferenceEquals(entry, selectedEntry)
            && entry.IsStocked
            && entry.EnoughGold
            && MerchantKind(entry) is not null
            && MerchantTarget(entry) is not null);

    internal static MerchantEntryEvidence DescribeMerchantEntry(MerchantEntry entry) =>
        new(
            entry.GetType().Name,
            MerchantKind(entry)?.ToString(),
            MerchantTarget(entry),
            entry.Cost,
            entry.IsStocked,
            entry.EnoughGold);

    internal static OutsideCombatDecisionPoint ForReward(
        RunState state,
        IReadOnlyList<Reward> legalRewards,
        Reward? selectedReward,
        bool canProceed,
        long sourceDecisionIndex,
        out int selectedOrdinal,
        bool includePotionActions)
    {
        var bindings = legalRewards
            .Where(reward => !reward.SuccessfullySelected)
            .ToArray();
        var rewardActions = bindings
            .Select((reward, ordinal) => Action(
                OutsideCombatActionKind.ClaimReward,
                ordinal,
                RewardTarget(reward)))
            .Concat(canProceed
                ?
                [
                    Action(
                        OutsideCombatActionKind.Proceed,
                        bindings.Length,
                        "proceed"),
                ]
                : [])
            .ToArray();
        // Potion actions are appended so reward and Proceed ordinals remain
        // stable. The caller must verify that the native belt is interactable
        // on this exact Rewards screen before requesting these actions.
        var actions = includePotionActions
            ? rewardActions.Concat(RewardPotionActions(state, rewardActions.Length)).ToArray()
            : rewardActions;
        selectedOrdinal = selectedReward is null
            ? canProceed ? rewardActions.Length - 1 : -1
            : Array.FindIndex(
                bindings,
                reward => ReferenceEquals(reward, selectedReward));
        return Build(
            state,
            OutsideCombatSurfaceKind.Rewards,
            "rewards",
            actions,
            sourceDecisionIndex);
    }

    /// <summary>
    /// Freeze the same Rewards legal set used by ordinary claim/proceed input,
    /// then locate the native potion slot. The caller must first verify that
    /// Rewards is the top overlay and the potion belt is interactable.
    /// </summary>
    internal static OutsideCombatDecisionPoint ForRewardPotion(
        RunState state,
        IReadOnlyList<Reward> legalRewards,
        bool canProceed,
        OutsideCombatActionKind selectedKind,
        int potionSlotIndex,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        if (selectedKind is not (OutsideCombatActionKind.UsePotion
            or OutsideCombatActionKind.DiscardPotion))
        {
            throw new ArgumentOutOfRangeException(nameof(selectedKind));
        }

        var decision = ForReward(
            state,
            legalRewards,
            selectedReward: null,
            canProceed,
            sourceDecisionIndex,
            out _,
            includePotionActions: true);
        selectedOrdinal = decision.LegalActions
            .Select((action, index) => (action, index))
            .Where(entry => entry.action.Kind == selectedKind
                            && entry.action.PotionSlotIndex == potionSlotIndex)
            .Select(entry => entry.index)
            .DefaultIfEmpty(-1)
            .Single();
        if (selectedOrdinal < 0)
        {
            throw new InvalidDataException(
                $"{selectedKind} at potion slot {potionSlotIndex} is not legal "
                + "at the frozen Rewards boundary.");
        }

        return decision;
    }

    private static IReadOnlyList<OutsideCombatActionDescriptor> RewardPotionActions(
        RunState state,
        int firstOrdinal)
    {
        if (state.Players.Count != 1)
        {
            return [];
        }

        var player = state.Players[0];
        if (player.Creature.IsDead || !player.CanUseOrRemovePotions)
        {
            return [];
        }

        var actions = new List<OutsideCombatActionDescriptor>();
        for (var slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            var potion = player.PotionSlots[slot];
            if (potion is null || potion.IsQueued || potion.HasBeenRemovedFromState
                || !ReferenceEquals(potion.Owner, player))
            {
                continue;
            }

            if (potion.Usage == PotionUsage.AnyTime
                && potion.PassesCustomUsabilityCheck
                && (potion.TargetType == TargetType.AnyPlayer
                    && potion.IsValidTarget(player.Creature)
                    || potion.TargetType == TargetType.TargetedNoCreature
                    && potion.IsValidTarget(null)))
            {
                actions.Add(PotionAction(
                    OutsideCombatActionKind.UsePotion,
                    firstOrdinal + actions.Count,
                    slot,
                    potion.Id.ToString()));
            }

            // The native popup permits discarding any held potion regardless
            // of its combat-only or automatic usage category.
            actions.Add(PotionAction(
                OutsideCombatActionKind.DiscardPotion,
                firstOrdinal + actions.Count,
                slot,
                potion.Id.ToString()));
        }

        return actions;
    }

    private static OutsideCombatActionDescriptor PotionAction(
        OutsideCombatActionKind kind,
        int ordinal,
        int slot,
        string modelId) => new(
            $"{kind.ToString().ToLowerInvariant()}:{ordinal}:{slot}:{modelId}",
            kind,
            ordinal,
            modelId)
        {
            PotionSlotIndex = slot,
        };

    internal static OutsideCombatDecisionPoint ForTreasureRoom(
        RunState state,
        bool canOpenChest,
        bool canProceed,
        OutsideCombatActionKind selectedKind,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        var actions = new List<OutsideCombatActionDescriptor>(2);
        if (canOpenChest)
        {
            actions.Add(Action(
                OutsideCombatActionKind.OpenChest,
                actions.Count,
                "chest"));
        }
        if (canProceed)
        {
            actions.Add(Action(
                OutsideCombatActionKind.Proceed,
                actions.Count,
                "proceed"));
        }

        selectedOrdinal = actions.FindIndex(action => action.Kind == selectedKind);
        return Build(
            state,
            OutsideCombatSurfaceKind.Treasure,
            "treasure_room",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForCardChoice(
        RunState state,
        IReadOnlyList<CardModel> cards,
        CardModel? selectedCard,
        bool canSkip,
        OutsideCombatSurfaceKind surface,
        string contextId,
        long sourceDecisionIndex,
        out int selectedOrdinal)
    {
        var actions = cards
            .Select((card, ordinal) => Action(
                OutsideCombatActionKind.ChooseCard,
                ordinal,
                card.Id.ToString()))
            .ToList();
        if (canSkip)
        {
            actions.Add(Action(OutsideCombatActionKind.Skip, actions.Count, "skip"));
        }

        selectedOrdinal = selectedCard is null
            ? canSkip ? actions.Count - 1 : -1
            : cards.ToList().FindIndex(card => ReferenceEquals(card, selectedCard));
        return Build(state, surface, contextId, actions, sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForCardRewardChoice(
        RunState state,
        IReadOnlyList<CardModel> cards,
        IReadOnlyList<CardRewardExtraOption> extraOptions,
        long sourceDecisionIndex)
    {
        // Native OptionSelected returns the card index, or cards.Count plus
        // the index in _extraOptions. Match those indexes exactly.
        var actions = cards
            .Select((card, ordinal) => Action(
                OutsideCombatActionKind.ChooseCard,
                ordinal,
                card.Id.ToString()))
            .ToList();
        foreach (var option in extraOptions)
        {
            actions.Add(Action(
                option.IsSkip
                    ? OutsideCombatActionKind.Skip
                    : OutsideCombatActionKind.ChooseRewardAlternative,
                actions.Count,
                option.OptionId));
        }

        return Build(
            state,
            OutsideCombatSurfaceKind.CardReward,
            "card_reward",
            actions,
            sourceDecisionIndex);
    }

    internal static OutsideCombatDecisionPoint ForCardGridChoice(
        RunState state,
        IReadOnlyList<CardModel> cards,
        bool cancelable,
        bool removalSelection,
        bool merchantRemoval,
        int minSelections,
        int maxSelections,
        bool requiresConfirmation,
        string contextId,
        long sourceDecisionIndex)
    {
        var deck = state.Players.Single().Deck.Cards.ToArray();
        var actions = new List<OutsideCombatActionDescriptor>(
            cards.Count + (cancelable ? 1 : 0));
        for (var ordinal = 0; ordinal < cards.Count; ordinal++)
        {
            var card = cards[ordinal];
            var deckIndex = Array.FindIndex(deck, candidate => ReferenceEquals(candidate, card));
            var kind = removalSelection
                ? OutsideCombatActionKind.RemoveCard
                : OutsideCombatActionKind.ChooseCard;
            if (removalSelection && deckIndex < 0)
            {
                throw new InvalidOperationException(
                    $"Removal option {card.Id} is absent from the observed deck.");
            }

            actions.Add(new OutsideCombatActionDescriptor(
                $"{kind.ToString().ToLowerInvariant()}:{ordinal}:{card.Id}",
                kind,
                ordinal,
                card.Id.ToString(),
                TargetDeckIndex: deckIndex >= 0 ? deckIndex : null));
        }

        if (cancelable)
        {
            actions.Add(new OutsideCombatActionDescriptor(
                $"cancel_selection:{actions.Count}",
                OutsideCombatActionKind.CancelSelection,
                actions.Count,
                "cancel"));
        }

        return Build(
            state,
            merchantRemoval
                ? OutsideCombatSurfaceKind.MerchantCardRemoval
                : OutsideCombatSurfaceKind.CardGridChoice,
            contextId,
            actions,
            sourceDecisionIndex,
            OutsideCombatChoicePhase.Selection,
            minSelections,
            maxSelections,
            cancelable: cancelable,
            requiresConfirmation: requiresConfirmation);
    }

    internal static OutsideCombatDecisionPoint ForRelicChoice(
        RunState state,
        IReadOnlyList<RelicModel> relics,
        bool canSkip,
        string contextId,
        long sourceDecisionIndex)
    {
        var actions = relics
            .Select((relic, ordinal) => Action(
                OutsideCombatActionKind.ChooseRelic,
                ordinal,
                relic.Id.ToString()))
            .ToList();
        if (canSkip)
        {
            actions.Add(Action(OutsideCombatActionKind.Skip, actions.Count, "skip"));
        }

        return Build(
            state,
            OutsideCombatSurfaceKind.RelicChoice,
            contextId,
            actions,
            sourceDecisionIndex,
            OutsideCombatChoicePhase.Selection,
            minSelections: canSkip ? 0 : 1,
            maxSelections: 1,
            cancelable: canSkip);
    }

    internal static OutsideCombatDecisionPoint ForCardBundleChoice(
        RunState state,
        IReadOnlyList<IReadOnlyList<CardModel>> bundles,
        string contextId,
        long sourceDecisionIndex)
    {
        if (bundles.Count == 0 || bundles.Any(bundle => bundle.Count == 0))
        {
            throw new InvalidDataException("A card-bundle choice requires nonempty bundles.");
        }

        var actions = bundles.Select((bundle, ordinal) =>
        {
            var cards = bundle
                .Select(card => new OutsideBundleCardReference(
                    card.Id.ToString(),
                    card.CurrentUpgradeLevel))
                .ToArray();
            var target = string.Join(",", cards.Select(card =>
                $"{card.ModelId}+{card.UpgradeLevel}"));
            return new OutsideCombatActionDescriptor(
                $"choose_card_bundle:{ordinal}",
                OutsideCombatActionKind.ChooseCardBundle,
                ordinal,
                target,
                BundleCards: cards);
        }).ToArray();

        return Build(
            state,
            OutsideCombatSurfaceKind.CardBundleChoice,
            contextId,
            actions,
            sourceDecisionIndex,
            OutsideCombatChoicePhase.Selection,
            minSelections: 1,
            maxSelections: 1,
            requiresConfirmation: true);
    }

    internal static OutsideCombatDecisionPoint ForCrystalSphere(
        RunState state,
        CrystalSphereBoardObservation board,
        IReadOnlyList<OutsideCombatActionDescriptor> legalActions,
        long sourceDecisionIndex) =>
        Build(
            state,
            OutsideCombatSurfaceKind.CrystalSphere,
            "crystal_sphere",
            legalActions,
            sourceDecisionIndex,
            crystalSphere: board);

    internal static OutsideCombatDecisionPoint Build(
        RunState state,
        OutsideCombatSurfaceKind surface,
        string contextId,
        IReadOnlyList<OutsideCombatActionDescriptor> legalActions,
        long sourceDecisionIndex,
        OutsideCombatChoicePhase phase = OutsideCombatChoicePhase.Default,
        int? minSelections = null,
        int? maxSelections = null,
        int selectedCount = 0,
        bool cancelable = false,
        bool requiresConfirmation = false,
        CrystalSphereBoardObservation? crystalSphere = null,
        IReadOnlyList<OutsideSelectedCardReference>? cardSelectionOptions = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentException.ThrowIfNullOrWhiteSpace(contextId);
        if (legalActions.Count == 0)
        {
            throw new InvalidOperationException(
                $"Cannot capture {surface}: no native legal actions were observed.");
        }

        var choiceContext = new OutsideCombatChoiceContext(
            contextId,
            StateToken(contextId, legalActions),
            phase,
            minSelections,
            maxSelections,
            selectedCount,
            cancelable,
            requiresConfirmation);
        var observation = BuildObservation(
            state, surface, choiceContext, crystalSphere, cardSelectionOptions);
        var fingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
            CombatCaptureService.CurrentBuild,
            observation,
            legalActions);
        var decision = new OutsideCombatDecisionPoint(
            OutsideCombatDecisionPoint.CurrentSchemaVersion,
            CombatCaptureService.CurrentBuild,
            sourceDecisionIndex,
            fingerprint,
            observation,
            legalActions);
        decision.Validate();
        return decision;
    }

    private static OutsideCombatObservation BuildObservation(
        RunState state,
        OutsideCombatSurfaceKind surface,
        OutsideCombatChoiceContext choiceContext,
        CrystalSphereBoardObservation? crystalSphere,
        IReadOnlyList<OutsideSelectedCardReference>? cardSelectionOptions)
    {
        var mapPoints = BuildMapObservation(state);
        var knownCoordinates = mapPoints.Select(point => point.Coordinate).ToHashSet();
        var players = state.Players
            .OrderBy(player => player.NetId)
            .Select(player => new OutsideRunPlayerObservation(
                player.NetId,
                player.Character.Id.ToString(),
                player.Creature.CurrentHp,
                player.Creature.MaxHp,
                player.Gold,
                player.MaxPotionCount,
                player.Deck.Cards
                    .Select((card, index) => new OutsideRunCardObservation(
                        index,
                        card.Id.ToString(),
                        card.CurrentUpgradeLevel,
                        card.Enchantment?.Id.ToString(),
                        card.Affliction?.Id.ToString())
                    {
                        EnchantmentDisplay = CollectorEnchantmentDisplayProjector.Capture(card),
                    })
                    .ToArray(),
                player.Relics
                    .Select(relic => new OutsideRunRelicObservation(relic.Id.ToString())
                    {
                        Display = RelicDisplayProjector.Capture(relic),
                    })
                    .ToArray(),
                player.PotionSlots
                    .Select((potion, index) => new { Potion = potion, Index = index })
                    .Where(entry => entry.Potion is not null)
                    .Select(entry => new PotionObservation(
                        entry.Index,
                        entry.Potion!.Id.ToString()))
                    .ToArray()))
            .ToArray();
        var currentCoordinate = state.CurrentMapCoord is { } coordinate
            ? new OutsideMapCoordinate(coordinate.row, coordinate.col)
            : (OutsideMapCoordinate?)null;
        if (currentCoordinate is { } current && !knownCoordinates.Contains(current))
        {
            currentCoordinate = null;
        }

        var observation = new OutsideCombatObservation(
            cardSelectionOptions is null ? 4 : OutsideCombatObservation.CurrentSchemaVersion,
            surface,
            choiceContext,
            state.CurrentActIndex,
            state.ActFloor,
            state.TotalFloor,
            state.AscensionLevel,
            state.CurrentRoom?.RoomType.ToString() ?? "Unknown",
            state.CurrentRoom?.ModelId?.ToString(),
            currentCoordinate,
            players,
            mapPoints)
        {
            CrystalSphere = crystalSphere,
            CardSelectionOptions = cardSelectionOptions,
        };
        observation.Validate();
        return observation;
    }

    private static IReadOnlyList<OutsideMapPointObservation> BuildMapObservation(RunState state) =>
        EnumerateMap(state)
            .Select(point => new OutsideMapPointObservation(
                new OutsideMapCoordinate(point.coord.row, point.coord.col),
                point.PointType.ToString(),
                state.VisitedMapCoords.Contains(point.coord),
                point.Children
                    .Select(child => new OutsideMapCoordinate(child.coord.row, child.coord.col))
                    .OrderBy(child => child.Row)
                    .ThenBy(child => child.Column)
                    .ToArray()))
            .OrderBy(point => point.Coordinate.Row)
            .ThenBy(point => point.Coordinate.Column)
            .ToArray();

    private static IReadOnlyList<MapPoint> EnumerateMap(RunState state)
    {
        if (state.Map?.StartingMapPoint is not { } start)
        {
            return [];
        }

        var result = new List<MapPoint>();
        var pending = new Queue<MapPoint>();
        var seen = new HashSet<MapPoint>();
        pending.Enqueue(start);
        seen.Add(start);
        while (pending.TryDequeue(out var point))
        {
            result.Add(point);
            foreach (var child in point.Children)
            {
                if (seen.Add(child))
                {
                    pending.Enqueue(child);
                }
            }
        }

        return result;
    }

    private static OutsideCombatActionDescriptor Action(
        OutsideCombatActionKind kind,
        int ordinal,
        string target) =>
        new(
            $"{kind.ToString().ToLowerInvariant()}:{ordinal}:{target}",
            kind,
            ordinal,
            target);

    private static OutsideCombatActionKind? MerchantKind(MerchantEntry entry) => entry switch
    {
        MerchantCardEntry => OutsideCombatActionKind.BuyCard,
        MerchantRelicEntry => OutsideCombatActionKind.BuyRelic,
        MerchantPotionEntry => OutsideCombatActionKind.BuyPotion,
        MerchantCardRemovalEntry => OutsideCombatActionKind.OpenCardRemoval,
        _ => null,
    };

    private static string? MerchantTarget(MerchantEntry entry) => entry switch
    {
        MerchantCardEntry card => card.CreationResult?.Card?.Id.ToString(),
        MerchantRelicEntry relic => relic.Model?.Id.ToString(),
        MerchantPotionEntry potion => potion.Model?.Id.ToString(),
        MerchantCardRemovalEntry => "card_removal",
        _ => null,
    };

    private static string RewardTarget(Reward reward) => reward switch
    {
        CardReward => "card_reward",
        RelicReward relic => relic.Relic?.Id.ToString() ?? "relic_reward",
        PotionReward potion => potion.Potion?.Id.ToString() ?? "potion_reward",
        GoldReward gold => $"gold:{gold.Amount}",
        _ => reward.GetType().Name,
    };

    private static string StateToken(
        string contextId,
        IReadOnlyList<OutsideCombatActionDescriptor> actions)
    {
        var semantic = contextId + "\n" + string.Join(
            "\n",
            actions.Select(action => action.ActionId));
        return Convert.ToHexString(
                SHA256.HashData(Encoding.UTF8.GetBytes(semantic)))
            .ToLowerInvariant();
    }
}
