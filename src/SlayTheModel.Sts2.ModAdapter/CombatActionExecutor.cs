using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Converts protocol actions back into the game's deterministic player-input actions.
/// Waits through mid-action choices. The caller supplies a scoped live card selector
/// or leaves native manual selection active; headless branching is a separate concern.
/// </summary>
public static class CombatActionExecutor
{
    public static GameAction CreateGameAction(
        CombatState state,
        CombatActionDescriptor action)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(action);
        action.Validate();

        var player = FindPlayer(state, action.ActorPlayerId);
        return action.Kind switch
        {
            CombatActionKind.PlayCard => CreatePlayCardAction(state, player, action),
            CombatActionKind.UsePotion => CreateUsePotionAction(state, player, action),
            CombatActionKind.EndTurn => new EndPlayerTurnAction(
                player,
                RequireCombatState(player).TurnNumber),
            CombatActionKind.ResolveChoice => throw new NotSupportedException(
                "Mid-action choices are resolved by the headless branching choice context, not a GameAction."),
            _ => throw new ArgumentOutOfRangeException(nameof(action), action.Kind, null),
        };
    }

    public static async Task ExecuteAsync(
        CombatState state,
        CombatActionDescriptor action)
    {
        var gameAction = CreateGameAction(state, action);
        var runManager = RunManager.Instance;
        var queue = runManager.ActionQueueSet
            ?? throw new InvalidOperationException("The run action queue is unavailable.");
        var executor = runManager.ActionExecutor
            ?? throw new InvalidOperationException("The run action executor is unavailable.");

        queue.EnqueueWithoutSynchronizing(gameAction);
        // Queue idle also means "paused for a player choice". It does not mean
        // the card finished. Keep the live controller busy until the action really
        // completes, then wait for queue bookkeeping on the game's main context.
        await NativeActionCompletion.WaitAsync(gameAction.CompletionTask, executor.FinishedExecutingActions);
        if (gameAction.Exception is { } exception)
        {
            throw new InvalidOperationException("The native game action failed.", exception);
        }
    }

    private static PlayCardAction CreatePlayCardAction(
        CombatState state,
        Player player,
        CombatActionDescriptor action)
    {
        var cardIndex = action.CombatCardIndex
            ?? throw new InvalidDataException("PlayCard has no combat card index.");
        var card = RequireCombatState(player).Hand.Cards.SingleOrDefault(candidate =>
            NetCombatCard.FromModel(candidate).CombatCardIndex == cardIndex)
            ?? throw new InvalidDataException(
                $"Combat card {cardIndex} is not in player {player.NetId}'s hand.");
        var target = FindOptionalTarget(state, action.TargetCreatureId);

        if (!card.CanPlay())
        {
            throw new InvalidOperationException($"Combat card {cardIndex} is no longer playable.");
        }

        if (target is not null && !card.CanPlayTargeting(target))
        {
            throw new InvalidOperationException(
                $"Combat card {cardIndex} cannot target creature {target.CombatId}.");
        }

        return new PlayCardAction(card, target);
    }

    private static UsePotionAction CreateUsePotionAction(
        CombatState state,
        Player player,
        CombatActionDescriptor action)
    {
        var potionIndex = checked((int)(action.PotionIndex
            ?? throw new InvalidDataException("UsePotion has no potion index.")));
        var potion = player.GetPotionAtSlotIndex(potionIndex)
            ?? throw new InvalidDataException(
                $"Player {player.NetId} has no potion in slot {potionIndex}.");
        var target = FindOptionalTarget(state, action.TargetCreatureId);
        return new UsePotionAction(potion, target, true);
    }

    private static Player FindPlayer(CombatState state, ulong playerId) =>
        state.Players.SingleOrDefault(player => player.NetId == playerId)
        ?? throw new InvalidDataException($"Unknown player {playerId}.");

    private static Creature? FindOptionalTarget(CombatState state, uint? combatId) =>
        combatId is null
            ? null
            : state.Creatures.SingleOrDefault(creature => creature.CombatId == combatId)
                ?? throw new InvalidDataException($"Unknown target creature {combatId}.");

    private static PlayerCombatState RequireCombatState(Player player) =>
        player.PlayerCombatState
        ?? throw new InvalidDataException($"Player {player.NetId} has no combat state.");
}
