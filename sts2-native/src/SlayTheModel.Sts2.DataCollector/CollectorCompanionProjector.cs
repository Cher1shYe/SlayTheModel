using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Captures current player-owned companions. Osty is kept separately in the
/// player's pet collection, which can briefly differ from the combat roster.
/// A pet outside the roster is included only when it is still alive, hittable,
/// visibly rendered, and attached to this combat; dead or escaped references
/// are not exposed.
/// </summary>
internal static class CollectorCompanionProjector
{
    internal static IReadOnlyList<CombatCompanionObservation> Capture(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);

        var players = new HashSet<Player>(state.Players, ReferenceEqualityComparer.Instance);
        var roster = new HashSet<Creature>(state.Allies, ReferenceEqualityComparer.Instance);
        var escaped = new HashSet<Creature>(
            state.EscapedCreatures,
            ReferenceEqualityComparer.Instance);
        var current = new HashSet<Creature>(ReferenceEqualityComparer.Instance);

        foreach (var ally in roster)
        {
            if (ally.PetOwner is { } owner
                && players.Contains(owner)
                && ReferenceEquals(ally.CombatState, state))
            {
                current.Add(ally);
            }
        }

        foreach (var player in state.Players)
        {
            if (player.PlayerCombatState is not { } combatState)
            {
                continue;
            }

            foreach (var pet in combatState.Pets)
            {
                if (IsCurrentOffRosterPet(pet, player, state, roster, escaped))
                {
                    current.Add(pet);
                }
            }

            // The native Osty accessor is sourced from the same pet collection,
            // but check it explicitly so this class resource cannot be omitted
            // if the collection API changes independently.
            if (player.Osty is { } osty
                && IsCurrentOffRosterPet(osty, player, state, roster, escaped))
            {
                current.Add(osty);
            }
        }

        return current
            .Select(creature => CaptureCompanion(creature, creature.PetOwner!))
            .OrderBy(companion => companion.OwnerPlayerId)
            .ThenBy(companion => companion.ModelId, StringComparer.Ordinal)
            .ThenBy(companion => companion.CurrentHp)
            .ThenBy(companion => companion.Block)
            .ToArray();
    }

    private static bool IsCurrentOffRosterPet(
        Creature pet,
        Player owner,
        CombatState state,
        IReadOnlySet<Creature> roster,
        IReadOnlySet<Creature> escaped)
    {
        if (!ReferenceEquals(pet.PetOwner, owner)
            || !ReferenceEquals(pet.CombatState, state)
            || pet.Side != owner.Creature.Side)
        {
            return false;
        }

        return roster.Contains(pet)
            || pet.CombatId is not null
               && pet.IsAlive
               && pet.IsHittable
               && !escaped.Contains(pet)
               && HasVisibleNode(pet);
    }

    private static bool HasVisibleNode(Creature pet)
    {
        try
        {
            var node = pet.GetCreatureNode();
            return node is not null
                && GodotObject.IsInstanceValid(node)
                && node.IsInsideTree()
                && node.IsVisibleInTree();
        }
        catch
        {
            return false;
        }
    }

    private static CombatCompanionObservation CaptureCompanion(
        Creature creature,
        Player owner)
    {
        var modelId = creature.Monster?.Id.ToString()
            ?? throw new InvalidDataException("Active companion has no monster model ID.");
        return new CombatCompanionObservation(
            owner.NetId,
            modelId,
            creature.CurrentHp,
            creature.MaxHp,
            creature.Block,
            creature.Powers
                .Select(power => new ModelAmountSnapshot(
                    power.Id.ToString(),
                    checked((int)power.Amount)))
                .OrderBy(power => power.ModelId, StringComparer.Ordinal)
                .ToArray());
    }
}
