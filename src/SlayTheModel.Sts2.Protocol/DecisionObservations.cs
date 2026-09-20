namespace SlayTheModel.Sts2.Protocol;

/// <summary>
/// The policy-facing view of a combat. It deliberately excludes run economy,
/// hidden RNG state, native serialization payloads, and determinism metadata.
/// </summary>
public sealed record CombatObservation(
    int SchemaVersion,
    int RoundNumber,
    CombatSide CurrentSide,
    IReadOnlyList<CombatPlayerObservation> Players,
    IReadOnlyList<CreatureSnapshot> Creatures)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported combat observation schema {SchemaVersion}; expected {CurrentSchemaVersion}.");
        }

        if (RoundNumber < 0)
        {
            throw new InvalidDataException("Combat observation round number must be non-negative.");
        }

        RequireUnique(Players.Select(player => player.PlayerId), "combat observation player ID");
        RequireUnique(Creatures.Select(creature => creature.CombatId), "combat observation creature ID");

        var playerIds = Players.Select(player => player.PlayerId).ToHashSet();
        foreach (var player in Players)
        {
            player.Validate();
        }

        foreach (var creature in Creatures)
        {
            if (creature.MaxHp < 0 || creature.CurrentHp < 0 || creature.Block < 0)
            {
                throw new InvalidDataException(
                    $"Creature {creature.CombatId} has invalid HP or block.");
            }

            if (creature.PlayerId is { } owner && !playerIds.Contains(owner))
            {
                throw new InvalidDataException(
                    $"Creature {creature.CombatId} references unknown player {owner}.");
            }
        }
    }

    private static void RequireUnique<T>(IEnumerable<T> values, string label)
        where T : notnull
    {
        var seen = new HashSet<T>();
        foreach (var value in values)
        {
            if (!seen.Add(value))
            {
                throw new InvalidDataException($"Duplicate {label}: {value}.");
            }
        }
    }
}

public sealed record CombatPlayerObservation(
    ulong PlayerId,
    string CharacterId,
    int Energy,
    int Stars,
    int TurnNumber,
    string Phase,
    IReadOnlyList<CombatPileObservation> Piles,
    IReadOnlyList<RelicObservation> Relics,
    IReadOnlyList<PotionObservation> Potions,
    IReadOnlyList<OrbSnapshot> Orbs)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(CharacterId);
        ArgumentException.ThrowIfNullOrWhiteSpace(Phase);
        if (Energy < 0 || TurnNumber < 0)
        {
            throw new InvalidDataException($"Player {PlayerId} has invalid turn state.");
        }

        var cardIds = Piles
            .SelectMany(pile => pile.Cards)
            .Select(card => card.CombatCardIndex)
            .ToArray();
        if (cardIds.Distinct().Count() != cardIds.Length)
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has duplicate combat card IDs in its observation.");
        }

        var potionSlots = Potions.Select(potion => potion.SlotIndex).ToArray();
        if (potionSlots.Any(slot => slot < 0)
            || potionSlots.Distinct().Count() != potionSlots.Length)
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has invalid or duplicate potion slots.");
        }
    }
}

public sealed record CombatPileObservation(
    string PileType,
    IReadOnlyList<CombatCardObservation> Cards);

public sealed record CombatCardObservation(
    uint CombatCardIndex,
    string ModelId,
    int? EnergyCost,
    string? AfflictionId,
    int AfflictionCount,
    IReadOnlyList<string> Keywords);

public sealed record RelicObservation(string ModelId);

public sealed record PotionObservation(int SlotIndex, string ModelId);

/// <summary>
/// The policy-facing persistent context carried by the current combat snapshot.
/// Map, floor, shop, rewards, and the canonical run deck will be added with the
/// run-state bridge; they are intentionally not inferred from transient combat piles.
/// </summary>
public sealed record RunObservation(
    int SchemaVersion,
    IReadOnlyList<RunPlayerObservation> Players)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported run observation schema {SchemaVersion}; expected {CurrentSchemaVersion}.");
        }

        var playerIds = Players.Select(player => player.PlayerId).ToArray();
        if (playerIds.Distinct().Count() != playerIds.Length)
        {
            throw new InvalidDataException("Run observation contains duplicate player IDs.");
        }

        foreach (var player in Players)
        {
            player.Validate();
        }
    }
}

public sealed record RunPlayerObservation(
    ulong PlayerId,
    string CharacterId,
    int CurrentHp,
    int MaxHp,
    int Gold,
    IReadOnlyList<RelicObservation> Relics,
    IReadOnlyList<PotionObservation> Potions)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(CharacterId);
        if (CurrentHp < 0 || MaxHp < 0 || Gold < 0)
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has invalid persistent HP or gold.");
        }

        var potionSlots = Potions.Select(potion => potion.SlotIndex).ToArray();
        if (potionSlots.Any(slot => slot < 0)
            || potionSlots.Distinct().Count() != potionSlots.Length)
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has invalid or duplicate run potion slots.");
        }
    }
}

/// <summary>
/// Creates the two policy views from the complete simulator state. Keeping this
/// projection in the game-independent protocol makes every policy receive the
/// same information regardless of whether it is driven live or headlessly.
/// </summary>
public static class DecisionObservationProjector
{
    public static CombatObservation ToCombat(CombatSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(state);
        state.Validate();

        var players = state.Players
            .Select(player => new CombatPlayerObservation(
                player.PlayerId,
                player.CharacterId,
                player.Energy,
                player.Stars,
                player.TurnNumber,
                player.Phase,
                player.Piles
                    .Select(pile => new CombatPileObservation(
                        pile.PileType,
                        pile.Cards
                            .Select(card => new CombatCardObservation(
                                card.CombatCardIndex,
                                card.ModelId,
                                card.EnergyCost,
                                card.AfflictionId,
                                card.AfflictionCount,
                                card.Keywords.ToArray()))
                            .ToArray()))
                    .ToArray(),
                player.Relics
                    .Select(relic => new RelicObservation(relic.ModelId))
                    .ToArray(),
                player.Potions
                    .Select((modelId, slotIndex) => new PotionObservation(slotIndex, modelId))
                    .ToArray(),
                player.Orbs.ToArray()))
            .ToArray();

        var observation = new CombatObservation(
            CombatObservation.CurrentSchemaVersion,
            state.RoundNumber,
            state.CurrentSide,
            players,
            state.Creatures.ToArray());
        observation.Validate();
        return observation;
    }

    public static RunObservation ToRun(CombatSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(state);
        state.Validate();

        var creaturesByPlayer = state.Creatures
            .Where(creature => creature.PlayerId is not null)
            .ToDictionary(creature => creature.PlayerId!.Value);
        var players = state.Players
            .Select(player =>
            {
                if (!creaturesByPlayer.TryGetValue(player.PlayerId, out var creature))
                {
                    throw new InvalidDataException(
                        $"Run observation has no creature for player {player.PlayerId}.");
                }

                return new RunPlayerObservation(
                    player.PlayerId,
                    player.CharacterId,
                    creature.CurrentHp,
                    creature.MaxHp,
                    player.Gold,
                    player.Relics
                        .Select(relic => new RelicObservation(relic.ModelId))
                        .ToArray(),
                    player.Potions
                        .Select((modelId, slotIndex) => new PotionObservation(slotIndex, modelId))
                        .ToArray());
            })
            .ToArray();

        var observation = new RunObservation(RunObservation.CurrentSchemaVersion, players);
        observation.Validate();
        return observation;
    }
}
