using System.Security.Cryptography;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed record CapturedCombatDecision(
    CombatDecisionPoint Decision,
    string ObservationFingerprint,
    string ExecutionGuardFingerprint,
    JsonElement RunContext);

/// <summary>
/// Builds a no-hidden-order combat observation and augments the adapter's v1
/// action set with native potion actions. The full native snapshot fingerprint
/// is retained only as an execution guard and is never a policy feature.
/// </summary>
internal static class CollectorCombatProjector
{
    /// <summary>
    /// Best-effort internal combat state at a manual input boundary. During a
    /// queued action there may be no stable legal set, so this audit snapshot
    /// must never become a behavior-cloning label by itself.
    /// </summary>
    internal static CombatObservation CaptureInternalObservation(CombatState state)
    {
        return Canonicalize(EnrichLiveObservation(
            state,
            CombatCaptureService.BuildObservation(state, decisionIndex: 0)));
    }

    internal static CapturedCombatDecision WithPendingManualActions(
        CapturedCombatDecision captured,
        IReadOnlyList<CombatActionDescriptor> queuedActions)
    {
        ArgumentNullException.ThrowIfNull(captured);
        ArgumentNullException.ThrowIfNull(queuedActions);
        var observation = captured.Decision.Observation with
        {
            PendingManualActions = queuedActions.ToArray(),
        };
        // A submitted card can remain in the native Hand until its queued
        // GameAction starts. It is no longer a second clickable hand action,
        // even when native CanPlay still reports it as playable.
        var queuedCards = queuedActions
            .Where(action => action.Kind == CombatActionKind.PlayCard
                             && action.CombatCardIndex is not null)
            .Select(action => (action.ActorPlayerId, action.CombatCardIndex!.Value))
            .ToHashSet();
        var legalActions = captured.Decision.LegalActions
            .Where(action => action.Kind != CombatActionKind.PlayCard
                             || action.CombatCardIndex is not { } cardIndex
                             || !queuedCards.Contains((action.ActorPlayerId, cardIndex)))
            .ToArray();
        var fingerprint = Fingerprint(observation, legalActions);
        var decision = captured.Decision with
        {
            Observation = observation,
            StateFingerprint = fingerprint,
            LegalActions = legalActions,
        };
        decision.ValidatePotionActionReferences();
        return captured with
        {
            Decision = decision,
            ObservationFingerprint = fingerprint,
        };
    }

    internal static CapturedCombatDecision WithChoiceDisplays(
        CapturedCombatDecision captured,
        object selector,
        IReadOnlyList<CardModel> offeredCards)
    {
        ArgumentNullException.ThrowIfNull(captured);
        ArgumentNullException.ThrowIfNull(selector);
        ArgumentNullException.ThrowIfNull(offeredCards);
        var choice = captured.Decision.Observation.ActiveChoice;
        if (choice is null || choice.Cards.Count != offeredCards.Count)
        {
            return captured;
        }

        var visible = CollectorCombatChoiceDisplayProjector.Capture(
            selector, offeredCards);
        var cards = choice.Cards.Select((candidate, index) =>
        {
            var card = offeredCards[index];
            return candidate with
            {
                Display = string.Equals(candidate.ModelId, card.Id.ToString(),
                              StringComparison.Ordinal)
                          && candidate.UpgradeLevel == card.CurrentUpgradeLevel
                          && visible.TryGetValue(card, out var display)
                    ? display
                    : null,
            };
        }).ToArray();
        var observation = captured.Decision.Observation with
        {
            ActiveChoice = choice with { Cards = cards },
        };
        var fingerprint = Fingerprint(observation, captured.Decision.LegalActions);
        var decision = captured.Decision with
        {
            Observation = observation,
            StateFingerprint = fingerprint,
        };
        return captured with
        {
            Decision = decision,
            ObservationFingerprint = fingerprint,
        };
    }

    internal static CapturedCombatDecision Capture(
        CombatState state,
        long sourceDecisionIndex)
    {
        var searchPoint = CombatCaptureService.BuildSearchPoint(state, sourceDecisionIndex);
        var observation = Canonicalize(EnrichLiveObservation(
            state,
            searchPoint.Decision.Observation));

        var actions = OrderActions(searchPoint.Decision.LegalActions
            .Concat(GetPotionActions(state)));
        var observationFingerprint = Fingerprint(observation, actions);
        var decision = new CombatDecisionPoint(
            CombatDecisionPoint.CurrentSchemaVersion,
            sourceDecisionIndex,
            observationFingerprint,
            observation,
            actions);
        decision.ValidatePotionActionReferences();
        return new CapturedCombatDecision(
            decision,
            observationFingerprint,
            searchPoint.Decision.StateFingerprint,
            CollectorRunContextProjector.Capture(
                RunManager.Instance.DebugOnlyGetState()
                ?? throw new InvalidOperationException(
                    "Native run state is unavailable during combat capture.")));
    }

    /// <summary>
    /// Freeze only commands available at the manual click during the player's
    /// turn-start animation. This is a collector-only decision surface: the
    /// normal policy/search legal set remains restricted to the Play phase.
    /// Native v0.111.0 enables EndTurn only after Phase becomes Play and
    /// TurnStarted fires, so Start has card and potion candidates only.
    /// </summary>
    internal static CapturedCombatDecision CaptureQueuedTurnStart(
        CombatState state,
        long sourceDecisionIndex)
    {
        ArgumentNullException.ThrowIfNull(state);
        var manager = CombatManager.Instance;
        if (!manager.IsInProgress
            || manager.IsOverOrEnding
            || manager.PlayerActionsDisabled
            || state.CurrentSide != MegaCrit.Sts2.Core.Combat.CombatSide.Player
            || state.Players.Count != 1
            || state.Players[0].PlayerCombatState?.Phase != PlayerTurnPhase.Start)
        {
            throw new InvalidOperationException(
                "Turn-start queued capture requires an active, enabled single-player turn start.");
        }

        var player = state.Players[0];
        var candidates = GetTurnStartCardActions(state, player)
            .Concat(GetPotionActions(state, allowTurnStart: true))
            .ToList();
        var actions = OrderActions(candidates);
        var snapshot = CombatCaptureService.BuildSnapshot(state, sourceDecisionIndex);
        var observation = Canonicalize(EnrichLiveObservation(
            state,
            DecisionObservationProjector.ToCombat(snapshot)));

        var fingerprint = Fingerprint(observation, actions);
        var decision = new CombatDecisionPoint(
            CombatDecisionPoint.CurrentSchemaVersion,
            sourceDecisionIndex,
            fingerprint,
            observation,
            actions);
        decision.ValidatePotionActionReferences();
        return new CapturedCombatDecision(
            decision,
            fingerprint,
            ProtocolJson.ComputeStateFingerprint(snapshot),
            CollectorRunContextProjector.Capture(
                RunManager.Instance.DebugOnlyGetState()
                ?? throw new InvalidOperationException(
                    "Native run state is unavailable during turn-start capture.")));
    }

    internal static CapturedCombatDecision CaptureCardChoice(
        CombatState state,
        IReadOnlyList<CardModel> offeredCards,
        int minSelections,
        int maxSelections,
        bool canCancel,
        string source,
        long sourceDecisionIndex,
        uint? nativeChoiceId = null,
        bool requiresNativeCombatCardIds = false)
    {
        if (offeredCards.Count == 0)
        {
            throw new InvalidDataException("A card choice without visible options is not a decision.");
        }

        // Native preferences may use a very large maximum to mean "any number".
        // The frozen interface cannot offer more cards than it displays.
        var effectiveMaxSelections = Math.Min(maxSelections, offeredCards.Count);
        if (minSelections < 0 || maxSelections < minSelections
            || minSelections > effectiveMaxSelections)
        {
            throw new InvalidDataException("Card choice selection bounds are invalid.");
        }

        var player = state.Players.Single();
        var choiceId = nativeChoiceId ?? checked((uint)(sourceDecisionIndex + 1));
        var cards = offeredCards
            .Select((card, optionIndex) =>
            {
                uint? nativeCardId = NetCombatCardDb.Instance.TryGetCardId(card, out var value)
                    ? value
                    : null;
                if (requiresNativeCombatCardIds && nativeCardId is null)
                {
                    throw new InvalidDataException(
                        $"Native combat-card ID missing for offered card at option {optionIndex}.");
                }

                return new CombatChoiceCardObservation(
                    nativeCardId,
                    card.Id.ToString(),
                    card.CurrentUpgradeLevel,
                    optionIndex);
            })
            .ToArray();
        var choice = new CombatChoiceObservation(
            choiceId,
            source,
            MinSelections: minSelections,
            MaxSelections: effectiveMaxSelections,
            CanCancel: canCancel,
            cards);
        var observation = Canonicalize(EnrichLiveObservation(
            state,
            CombatCaptureService.BuildObservation(state, sourceDecisionIndex))) with
        {
            ActiveChoice = choice,
        };
        var actions = CombatChoiceActionBuilder.Build(player.NetId, choice);

        var fingerprint = Fingerprint(observation, actions);
        var decision = new CombatDecisionPoint(
            CombatDecisionPoint.CurrentSchemaVersion,
            sourceDecisionIndex,
            fingerprint,
            observation,
            actions);
        decision.ValidatePotionActionReferences();
        return new CapturedCombatDecision(
            decision,
            fingerprint,
            fingerprint,
            CollectorRunContextProjector.Capture(
                RunManager.Instance.DebugOnlyGetState()
                ?? throw new InvalidOperationException("Run state is unavailable during combat choice.")));
    }

    internal static CombatActionDescriptor? Describe(GameAction action) => action switch
    {
        PlayCardAction play => new CombatActionDescriptor(
            CombatActionKind.PlayCard,
            play.OwnerId,
            CombatCardIndex: play.NetCombatCard.CombatCardIndex,
            TargetCreatureId: play.TargetId),
        UsePotionAction potion => new CombatActionDescriptor(
            CombatActionKind.UsePotion,
            potion.OwnerId,
            PotionIndex: potion.PotionIndex,
            TargetCreatureId: potion.TargetId),
        EndPlayerTurnAction end => new CombatActionDescriptor(
            CombatActionKind.EndTurn,
            end.OwnerId),
        _ => null,
    };

    internal static int FindAction(
        IReadOnlyList<CombatActionDescriptor> legalActions,
        CombatActionDescriptor submitted)
    {
        for (var index = 0; index < legalActions.Count; index++)
        {
            var legal = legalActions[index];
            if (legal == submitted)
            {
                return index;
            }

            // Native self-targeting potion actions may retain the player's
            // creature ID even though the policy action needs no target cursor.
            if (submitted.Kind == CombatActionKind.UsePotion
                && legal.Kind == submitted.Kind
                && legal.ActorPlayerId == submitted.ActorPlayerId
                && legal.PotionIndex == submitted.PotionIndex
                && legal.TargetCreatureId is null)
            {
                return index;
            }
        }

        return -1;
    }

    private static CombatObservation Canonicalize(CombatObservation observation)
    {
        var players = observation.Players
            .Select(player => player with
            {
                Piles = player.Piles
                    .Select(pile => pile with
                    {
                        // Raw no-SL data must not preserve the native draw or
                        // discard array order. CombatCardIndex remains only an
                        // entity reference for matching legal actions.
                        Cards = pile.Cards
                            .OrderBy(card => card.ModelId, StringComparer.Ordinal)
                            .ThenBy(card => card.AfflictionId, StringComparer.Ordinal)
                            .ThenBy(card => card.EnergyCost)
                            .ThenBy(card => card.CombatCardIndex)
                            .ToArray(),
                    })
                    .OrderBy(pile => pile.PileType, StringComparer.Ordinal)
                    .ToArray(),
                Relics = player.Relics
                    .OrderBy(relic => relic.ModelId, StringComparer.Ordinal)
                    .ToArray(),
                Potions = player.Potions
                    .OrderBy(potion => potion.SlotIndex)
                    .ToArray(),
            })
            .OrderBy(player => player.PlayerId)
            .ToArray();
        return observation with
        {
            Players = players,
            Creatures = observation.Creatures
                .OrderBy(creature => creature.CombatId)
                .ToArray(),
        };
    }

    private static CombatObservation EnrichLiveObservation(
        CombatState state,
        CombatObservation observation)
    {
        var withCards = CollectorCardDisplayProjector.Capture(state, observation);
        var capacityByPlayer = state.Players.ToDictionary(
            player => player.NetId,
            player => player.PlayerCombatState?.OrbQueue?.Capacity);
        var nativePlayers = state.Players.ToDictionary(player => player.NetId);
        var enriched = withCards with
        {
            Players = withCards.Players
                .Select(player =>
                {
                    if (!nativePlayers.TryGetValue(player.PlayerId, out var nativePlayer))
                    {
                        throw new InvalidDataException(
                            $"Combat observation player {player.PlayerId} has no native state.");
                    }

                    VerifyPotionSlots(player.Potions, nativePlayer);

                    return player with
                    {
                        OrbCapacity = capacityByPlayer[player.PlayerId],
                        Relics = CaptureVisibleRelics(player.Relics, nativePlayer),
                    };
                })
                .ToArray(),
            EnemyIntents = CollectorVisibleIntentProjector.Capture(state),
            Companions = CollectorCompanionProjector.Capture(state),
        };
        enriched.Validate();
        return enriched;
    }

    private static void VerifyPotionSlots(
        IReadOnlyList<PotionObservation> observedPotions,
        Player nativePlayer)
    {
        var visibleSlots = nativePlayer.PotionSlots
            .Select((potion, slot) => new { potion, slot })
            .Where(item => item.potion is not null)
            .Select(item => new PotionObservation(
                item.slot,
                item.potion!.Id.ToString()))
            .ToArray();
        if (!observedPotions.SequenceEqual(visibleSlots))
        {
            throw new InvalidDataException(
                $"Combat observation potion slots differ from native player {nativePlayer.NetId}.");
        }
    }

    private static IReadOnlyList<RelicObservation> CaptureVisibleRelics(
        IReadOnlyList<RelicObservation> observedRelics,
        Player nativePlayer)
    {
        var displaysByModel = nativePlayer.Relics
            .GroupBy(relic => relic.Id.ToString(), StringComparer.Ordinal)
            .ToDictionary(
                group => group.Key,
                group => new Queue<RelicDisplayObservation>(
                    group.Select(RelicDisplayProjector.Capture)),
                StringComparer.Ordinal);
        var projected = observedRelics.Select(relic =>
        {
            if (!displaysByModel.TryGetValue(relic.ModelId, out var displays)
                || !displays.TryDequeue(out var display))
            {
                throw new InvalidDataException(
                    $"Native relic {relic.ModelId} no longer matches its observation.");
            }

            return relic with { Display = display };
        }).ToArray();
        if (displaysByModel.Values.Any(displays => displays.Count != 0))
        {
            throw new InvalidDataException(
                "Combat observation and native relic counts differ.");
        }

        return projected;
    }

    private static IEnumerable<CombatActionDescriptor> GetTurnStartCardActions(
        CombatState state,
        Player player)
    {
        var actions = new List<CombatActionDescriptor>();
        var hand = player.PlayerCombatState?.Hand
            ?? throw new InvalidDataException("Player hand is unavailable during turn start.");
        foreach (var card in hand.Cards)
        {
            if (!card.CanPlay())
            {
                continue;
            }

            var cardId = NetCombatCard.FromModel(card).CombatCardIndex;
            if (card.TargetType is TargetType.AnyEnemy or TargetType.AnyAlly)
            {
                foreach (var target in state.Creatures)
                {
                    if (target.CombatId is { } targetId && card.CanPlayTargeting(target))
                    {
                        actions.Add(new CombatActionDescriptor(
                            CombatActionKind.PlayCard,
                            player.NetId,
                            cardId,
                            TargetCreatureId: targetId));
                    }
                }
            }
            else
            {
                actions.Add(new CombatActionDescriptor(
                    CombatActionKind.PlayCard,
                    player.NetId,
                    cardId));
            }
        }

        return actions;
    }

    private static CombatActionDescriptor[] OrderActions(
        IEnumerable<CombatActionDescriptor> actions) => actions
        .Distinct()
        .OrderBy(action => action.ActorPlayerId)
        .ThenBy(action => action.Kind)
        .ThenBy(action => action.CombatCardIndex)
        .ThenBy(action => action.PotionIndex)
        .ThenBy(action => action.TargetCreatureId)
        .ToArray();

    private static IReadOnlyList<CombatActionDescriptor> GetPotionActions(
        CombatState state,
        bool allowTurnStart = false)
    {
        var actions = new List<CombatActionDescriptor>();
        foreach (var player in state.Players.OrderBy(player => player.NetId))
        {
            var phase = player.PlayerCombatState?.Phase;
            if ((phase != PlayerTurnPhase.Play
                 && !(allowTurnStart && phase == PlayerTurnPhase.Start))
                || !player.CanUseOrRemovePotions)
            {
                continue;
            }

            for (var slot = 0; slot < player.PotionSlots.Count; slot++)
            {
                var potion = player.PotionSlots[slot];
                if (potion is null
                    || potion.IsQueued
                    || !potion.PassesCustomUsabilityCheck)
                {
                    continue;
                }

                if (RequiresTarget(potion.TargetType))
                {
                    foreach (var target in state.Creatures
                                 .Where(target => target.IsAlive && IsValidTarget(potion, target))
                                 .OrderBy(target => target.CombatId))
                    {
                        if (target.CombatId is { } combatId)
                        {
                            actions.Add(new CombatActionDescriptor(
                                CombatActionKind.UsePotion,
                                player.NetId,
                                PotionIndex: checked((uint)slot),
                                TargetCreatureId: combatId));
                        }
                    }
                }
                else
                {
                    actions.Add(new CombatActionDescriptor(
                        CombatActionKind.UsePotion,
                        player.NetId,
                        PotionIndex: checked((uint)slot)));
                }
            }
        }

        return actions;
    }

    private static bool RequiresTarget(TargetType targetType) => targetType is
        TargetType.AnyEnemy or TargetType.AnyAlly or TargetType.AnyPlayer;

    private static bool IsValidTarget(PotionModel potion, Creature target)
    {
        try
        {
            return potion.IsValidTarget(target);
        }
        catch
        {
            // A modded potion may reject a candidate by throwing from custom
            // targeting code. That candidate is not safe to expose as legal.
            return false;
        }
    }

    private static string Fingerprint(
        CombatObservation observation,
        IReadOnlyList<CombatActionDescriptor> actions)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(
            new { Observation = observation, LegalActions = actions },
            ProtocolJson.Options);
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }
}
