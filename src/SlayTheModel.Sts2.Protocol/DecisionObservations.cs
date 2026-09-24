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
    IReadOnlyList<CombatCreatureObservation> Creatures,
    CombatChoiceObservation? Choice = null)
{
    public const int CurrentSchemaVersion = 3;

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
            if (creature.PlayerId is null && creature.CurrentHp > 0
                && string.IsNullOrWhiteSpace(creature.CurrentIntent))
                throw new InvalidDataException($"Living enemy {creature.CombatId} has no visible current intent.");
            if (creature.PlayerId is not null && creature.CurrentIntent != null)
                throw new InvalidDataException($"Player creature {creature.CombatId} cannot have a monster intent.");
        }
        if (Choice is { } choice)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(choice.TriggerCardId);
            ArgumentException.ThrowIfNullOrWhiteSpace(choice.Effect);
            ArgumentException.ThrowIfNullOrWhiteSpace(choice.SourcePile);
            if (choice.MinCount < 0 || choice.MaxCount < choice.MinCount
                || choice.MaxCount > choice.Candidates.Count)
                throw new InvalidDataException("Choice cardinality is inconsistent with its candidates.");
            RequireUnique(choice.Candidates.Select(candidate => candidate.CombatCardIndex), "choice candidate ID");
            foreach (var previous in choice.CompletedSelections)
            {
                ArgumentException.ThrowIfNullOrWhiteSpace(previous.Effect);
                RequireUnique(previous.CombatCardIndices, "completed selection card ID");
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
        string[] publicPileTypes = ["Hand", "Draw", "Discard", "Exhaust", "Play"];
        foreach (var pile in Piles)
        {
            if (!publicPileTypes.Contains(pile.PileType, StringComparer.Ordinal))
                throw new InvalidDataException($"Unknown policy pile type {pile.PileType}.");
            if (pile.PileType == "Draw" && pile.Cards.Count != 0)
                throw new InvalidDataException("Hidden draw pile cards are not policy observations.");
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

public sealed record CombatCreatureObservation(
    uint CombatId, ulong? PlayerId, string? MonsterId,
    int CurrentHp, int MaxHp, int Block,
    IReadOnlyList<ModelAmountSnapshot> Powers,
    string? CurrentIntent);

public sealed record CombatChoiceCandidateObservation(uint CombatCardIndex, string ModelId, int UpgradeLevel);
public sealed record CombatCompletedChoiceObservation(string Effect, IReadOnlyList<uint> CombatCardIndices);
public sealed record CombatChoiceObservation(
    string TriggerCardId, string Effect, string SourcePile, int MinCount, int MaxCount,
    bool Ordered, IReadOnlyList<CombatChoiceCandidateObservation> Candidates,
    IReadOnlyList<CombatCompletedChoiceObservation> CompletedSelections);

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
    public static CombatObservation ToCombat(CombatSnapshot state, Func<uint, int?> visibleEnergyCost,
        Func<uint, string?> visibleCurrentIntent)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(visibleEnergyCost);
        ArgumentNullException.ThrowIfNull(visibleCurrentIntent);
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
                        // Draw order is hidden information. Keep the public pile
                        // boundary but never project its card contents.
                        pile.PileType.Equals("Draw", StringComparison.OrdinalIgnoreCase)
                            ? Array.Empty<CombatCardObservation>()
                            : pile.Cards
                            .Select(card => new CombatCardObservation(
                                card.CombatCardIndex,
                                card.ModelId,
                                visibleEnergyCost(card.CombatCardIndex),
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
            state.Creatures.Select(creature => new CombatCreatureObservation(
                creature.CombatId, creature.PlayerId, creature.MonsterId,
                creature.CurrentHp, creature.MaxHp, creature.Block,
                creature.Powers.ToArray(),
                creature.PlayerId is null && creature.CurrentHp > 0
                    ? visibleCurrentIntent(creature.CombatId) : null)).ToArray());
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
