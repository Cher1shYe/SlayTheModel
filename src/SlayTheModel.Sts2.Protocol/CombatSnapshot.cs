namespace SlayTheModel.Sts2.Protocol;

public sealed record CombatSnapshot(
    int SchemaVersion,
    BuildIdentity Build,
    long DecisionIndex,
    int RoundNumber,
    CombatSide CurrentSide,
    IReadOnlyList<PlayerCombatSnapshot> Players,
    IReadOnlyList<CreatureSnapshot> Creatures,
    RunRngSnapshot RunRng,
    DeterminismCounters Counters,
    uint NativeChecksum)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported combat snapshot schema {SchemaVersion}; expected {CurrentSchemaVersion}.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(Build.GameVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(Build.AssemblySha256);
        ArgumentException.ThrowIfNullOrWhiteSpace(Build.AssemblyModuleVersionId);

        if (DecisionIndex < 0 || RoundNumber < 0)
        {
            throw new InvalidDataException("Decision index and round number must be non-negative.");
        }

        RequireUnique(Players.Select(player => player.PlayerId), "player ID");
        RequireUnique(Creatures.Select(creature => creature.CombatId), "creature combat ID");

        var playerIds = Players.Select(player => player.PlayerId).ToHashSet();
        foreach (var player in Players)
        {
            if (player.Energy < 0 || player.TurnNumber < 0)
            {
                throw new InvalidDataException($"Player {player.PlayerId} has invalid turn state.");
            }

            RequireUnique(
                player.Piles.SelectMany(pile => pile.Cards).Select(card => card.CombatCardIndex),
                $"combat card ID for player {player.PlayerId}");
        }

        foreach (var creature in Creatures)
        {
            if (creature.MaxHp < 0 || creature.CurrentHp < 0 || creature.Block < 0)
            {
                throw new InvalidDataException($"Creature {creature.CombatId} has invalid HP or block.");
            }

            if (creature.PlayerId is { } owner && !playerIds.Contains(owner))
            {
                throw new InvalidDataException(
                    $"Creature {creature.CombatId} references unknown player {owner}.");
            }
        }

        var streamNames = RunRng.Streams.Select(stream => stream.Name).ToArray();
        RequireUnique(streamNames, "RNG stream name");
        if (!streamNames.SequenceEqual(streamNames.Order(StringComparer.Ordinal)))
        {
            throw new InvalidDataException("RNG streams must be sorted by ordinal name.");
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

public enum CombatSide
{
    Player,
    Enemy,
    Unknown,
}

public sealed record PlayerCombatSnapshot(
    ulong PlayerId,
    string CharacterId,
    int Energy,
    int Stars,
    int Gold,
    int TurnNumber,
    string Phase,
    IReadOnlyList<CombatPileSnapshot> Piles,
    IReadOnlyList<RelicSnapshot> Relics,
    IReadOnlyList<string> Potions,
    IReadOnlyList<OrbSnapshot> Orbs,
    PlayerRngSnapshot PlayerRng);

public sealed record CombatPileSnapshot(
    string PileType,
    IReadOnlyList<CardSnapshot> Cards);

public sealed record CardSnapshot(
    uint CombatCardIndex,
    string ModelId,
    int? EnergyCost,
    string? AfflictionId,
    int AfflictionCount,
    IReadOnlyList<string> Keywords,
    string NativeCardJson);

public sealed record CreatureSnapshot(
    uint CombatId,
    ulong? PlayerId,
    string? MonsterId,
    int CurrentHp,
    int MaxHp,
    int Block,
    IReadOnlyList<ModelAmountSnapshot> Powers);

public sealed record ModelAmountSnapshot(
    string ModelId,
    int Amount);

public sealed record RelicSnapshot(
    string ModelId,
    string NativeRelicJson);

public sealed record OrbSnapshot(
    string ModelId,
    int Passive,
    int Evoke);

public sealed record DeterminismCounters(
    uint? LastExecutedActionId,
    uint? LastExecutedHookId,
    IReadOnlyList<uint> NextChoiceIds,
    IReadOnlyList<int> NextRewardIds);
