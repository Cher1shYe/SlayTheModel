using System.Text.Json.Serialization;

namespace SlayTheModel.Sts2.Protocol;

/// <summary>
/// The policy-facing view of a combat. It excludes hidden RNG state, native
/// serialization payloads, and determinism metadata. Gold is included because
/// some combat effects depend on the player's current gold.
/// </summary>
public sealed record CombatObservation(
    int SchemaVersion,
    int RoundNumber,
    CombatSide CurrentSide,
    IReadOnlyList<CombatPlayerObservation> Players,
    IReadOnlyList<CreatureSnapshot> Creatures)
{
    public const int CurrentSchemaVersion = 5;

    /// <summary>
    /// Intent icons that the live UI currently exposes for enemy creatures.
    /// An empty or unverified intent is not a prediction of the next move.
    /// </summary>
    public IReadOnlyList<CombatEnemyIntentObservation> EnemyIntents { get; init; } = [];

    /// <summary>
    /// Owned combat companions such as Osty. These may not occur in the
    /// native creature array used by the simulator snapshot.
    /// </summary>
    public IReadOnlyList<CombatCompanionObservation> Companions { get; init; } = [];

    /// <summary>
    /// A visible card selector opened while a combat action is resolving.
    /// Null for ordinary play-card, potion, and end-turn decisions.
    /// </summary>
    public CombatChoiceObservation? ActiveChoice { get; init; }

    /// <summary>
    /// Manual combat commands already submitted by the player, in click order.
    /// This is visible input history, not a native queue snapshot or a legal set.
    /// </summary>
    public IReadOnlyList<CombatActionDescriptor> PendingManualActions { get; init; } = [];

    public void Validate()
    {
        if (SchemaVersion is < 1 or > CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported combat observation schema {SchemaVersion}; expected 1..{CurrentSchemaVersion}.");
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
            foreach (var card in player.Piles.SelectMany(pile => pile.Cards))
            {
                if (string.IsNullOrWhiteSpace(card.ModelId)
                    || card.UpgradeLevel is < 0
                    || card.Display?.DynamicValues.Any(value =>
                        string.IsNullOrWhiteSpace(value.Key)) == true
                    || SchemaVersion >= 4 && card.EnchantmentAmount is not null
                    || card.EnchantmentDisplay is not null
                        && (SchemaVersion < 4 || card.EnchantmentId is null))
                {
                    throw new InvalidDataException("Combat card has invalid visible data.");
                }

                card.EnchantmentDisplay?.Validate();
            }
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

        RequireUnique(EnemyIntents.Select(intent => intent.CreatureCombatId), "enemy intent creature ID");
        var creatureIds = Creatures.Select(creature => creature.CombatId).ToHashSet();
        foreach (var intent in EnemyIntents)
        {
            if (!creatureIds.Contains(intent.CreatureCombatId)
                || Creatures.Any(creature => creature.CombatId == intent.CreatureCombatId
                                             && creature.PlayerId is not null)
                || intent.Visibility is not ("visible" or "not_visible" or "unverified")
                || intent.Visibility != "visible" && intent.Intents.Count != 0
                || intent.Intents.Any(item => string.IsNullOrWhiteSpace(item.Kind)
                                              || item.TotalDamage is < 0
                                              || item.Hits is < 0))
            {
                throw new InvalidDataException("Combat enemy intent is invalid or references an unknown creature.");
            }
        }

        foreach (var companion in Companions)
        {
            if (!playerIds.Contains(companion.OwnerPlayerId)
                || string.IsNullOrWhiteSpace(companion.ModelId)
                || companion.CurrentHp < 0
                || companion.MaxHp < 0
                || companion.Block < 0)
            {
                throw new InvalidDataException("Combat companion has invalid owner, identity, HP, or block.");
            }
        }

        ActiveChoice?.Validate();
        foreach (var action in PendingManualActions)
        {
            action.Validate();
            if (action.Kind == CombatActionKind.ResolveChoice
                || !playerIds.Contains(action.ActorPlayerId))
            {
                throw new InvalidDataException("Pending manual action is not a combat command by a visible player.");
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

public sealed record CombatChoiceObservation(
    uint ChoiceId,
    string Source,
    int MinSelections,
    int MaxSelections,
    bool CanCancel,
    IReadOnlyList<CombatChoiceCardObservation> Cards)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(Source);
        if (MinSelections < 0 || MaxSelections < MinSelections || Cards.Count == 0
            || MaxSelections > Cards.Count)
        {
            throw new InvalidDataException("Combat choice cardinality or candidate set is invalid.");
        }

        var nativeIds = Cards
            .Where(card => card.CombatCardIndex.HasValue)
            .Select(card => card.CombatCardIndex!.Value)
            .ToArray();
        var optionIndexes = Cards
            .Where(card => card.OptionIndex.HasValue)
            .Select(card => card.OptionIndex!.Value)
            .ToArray();
        if (nativeIds.Distinct().Count() != nativeIds.Length
            || optionIndexes.Length != 0
               && (optionIndexes.Length != Cards.Count
                   || !optionIndexes.SequenceEqual(Enumerable.Range(0, Cards.Count)))
            || Cards.Any(card => string.IsNullOrWhiteSpace(card.ModelId)
                                 || card.UpgradeLevel < 0
                                 || card.CombatCardIndex is null && card.OptionIndex is null
                                 || card.Display?.DynamicValues.Any(value =>
                                     string.IsNullOrWhiteSpace(value.Key)) == true))
        {
            throw new InvalidDataException("Combat choice cards need unique native IDs or ordered selector options.");
        }
    }
}

public sealed record CombatChoiceCardObservation(
    uint? CombatCardIndex,
    string ModelId,
    int UpgradeLevel,
    int? OptionIndex = null)
{
    /// <summary>
    /// Card presentation observed on the choice interface at the manual
    /// input boundary. A null value means no visible card node was verified.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CombatCardDisplayObservation? Display { get; init; }
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
    public int? Gold { get; init; }

    public int? OrbCapacity { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(CharacterId);
        ArgumentException.ThrowIfNullOrWhiteSpace(Phase);
        if (Energy < 0 || TurnNumber < 0 || Gold is < 0 || OrbCapacity is < 0)
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

        foreach (var relic in Relics)
        {
            relic.Validate();
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
    IReadOnlyList<string> Keywords)
{
    public int? UpgradeLevel { get; init; }

    public string? EnchantmentId { get; init; }

    /// <summary>
    /// Legacy v2/v3 native amount. New v4 observations must leave it null and
    /// use EnchantmentDisplay.VisibleAmount only when the card UI shows it.
    /// </summary>
    public int? EnchantmentAmount { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CardEnchantmentDisplayObservation? EnchantmentDisplay { get; init; }

    /// <summary>
    /// In v5 live collector observations, internal Hand cards carry native
    /// current costs here regardless of hand animation; Description is null.
    /// Earlier collector versions used UI-visible card presentation. Base
    /// projections and cards outside Hand may leave this null.
    /// </summary>
    public CombatCardDisplayObservation? Display { get; init; }
}

public sealed record CombatCardDisplayObservation(
    string? Description,
    int? EnergyCost,
    int? StarCost,
    bool? CostsX,
    IReadOnlyList<CombatCardDynamicValueObservation> DynamicValues);

public sealed record CombatCardDynamicValueObservation(string Key, decimal Value);

/// <summary>
/// Inspectable enchantment presentation: the native card hover title and
/// description, plus only the counter and icon state that NCard would show.
/// </summary>
public sealed record CardEnchantmentDisplayObservation(
    string Title,
    string Description,
    int? VisibleAmount,
    string IconAppearance)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(Title);
        ArgumentNullException.ThrowIfNull(Description);
        if (IconAppearance is not ("normal" or "dimmed"))
        {
            throw new InvalidDataException("Enchantment icon appearance is invalid.");
        }
    }
}

public sealed record CombatEnemyIntentObservation(
    uint CreatureCombatId,
    string Visibility,
    IReadOnlyList<CombatIntentObservation> Intents);

public sealed record CombatIntentObservation(
    string Kind,
    string? DisplayText,
    int? TotalDamage,
    int? Hits);

public sealed record CombatCompanionObservation(
    ulong OwnerPlayerId,
    string ModelId,
    int CurrentHp,
    int MaxHp,
    int Block,
    IReadOnlyList<ModelAmountSnapshot> Powers);

public sealed record RelicObservation(string ModelId)
{
    /// <summary>
    /// The state available from this relic's icon and hover text at the
    /// decision boundary. Null means that no display projection was obtained.
    /// A null VisibleCounter within Display means that the icon showed no
    /// counter; zero is a visible zero.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public RelicDisplayObservation? Display { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        Display?.Validate();
    }
}

public sealed record RelicDisplayObservation(
    string IconStatus,
    bool IsMelted,
    bool IsWax,
    int? VisibleCounter,
    string? HoverDescription)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(IconStatus);
    }
}

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

        foreach (var relic in Relics)
        {
            relic.Validate();
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
                ProjectPotions(player),
                player.Orbs.ToArray())
            {
                Gold = player.Gold,
            })
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
                    ProjectPotions(player));
            })
            .ToArray();

        var observation = new RunObservation(RunObservation.CurrentSchemaVersion, players);
        observation.Validate();
        return observation;
    }

    private static PotionObservation[] ProjectPotions(PlayerCombatSnapshot player) =>
        player.Potions
            .Select((modelId, index) => new PotionObservation(
                player.PotionSlotIndexes?[index] ?? index,
                modelId))
            .ToArray();
}
