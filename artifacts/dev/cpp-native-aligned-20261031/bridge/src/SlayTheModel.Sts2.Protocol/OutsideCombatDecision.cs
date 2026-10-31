using System.Text.Json.Serialization;

namespace SlayTheModel.Sts2.Protocol;

/// <summary>
/// A game-assembly-independent snapshot presented to an outside-combat policy.
/// It contains persistent run information and the known map, but deliberately
/// excludes Godot nodes, localized UI text, native save payloads, and hidden RNG.
/// </summary>
public sealed record OutsideCombatObservation(
    int SchemaVersion,
    OutsideCombatSurfaceKind Surface,
    OutsideCombatChoiceContext ChoiceContext,
    int ActIndex,
    int ActFloor,
    int TotalFloor,
    int AscensionLevel,
    string RoomType,
    string? RoomModelId,
    OutsideMapCoordinate? CurrentMapCoordinate,
    IReadOnlyList<OutsideRunPlayerObservation> Players,
    IReadOnlyList<OutsideMapPointObservation> MapPoints)
{
    public const int CurrentSchemaVersion = 5;

    /// <summary>
    /// Only populated on the Crystal Sphere screen. Older outside observations
    /// remain v1/v2 with the same JSON and fingerprint.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CrystalSphereBoardObservation? CrystalSphere { get; init; }

    /// <summary>
    /// Ordered, visible options for one card-set choice. This list describes
    /// candidates once; it does not enumerate their possible subsets.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyList<OutsideSelectedCardReference>? CardSelectionOptions { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public OutsideArmGNativeContext? ArmGNativeContext { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public OutsideShopObservation? Shop { get; init; }

    public void Validate()
    {
        if (SchemaVersion is < 1 or > CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat observation schema {SchemaVersion}; "
                + $"expected 1..{CurrentSchemaVersion}.");
        }

        if (!Enum.IsDefined(Surface))
        {
            throw new InvalidDataException($"Unsupported outside-combat surface {Surface}.");
        }

        ArgumentNullException.ThrowIfNull(Players);
        ArgumentNullException.ThrowIfNull(MapPoints);
        ArgumentNullException.ThrowIfNull(ChoiceContext);
        if (Shop is not null)
        {
            if (Surface != OutsideCombatSurfaceKind.Merchant)
                throw new InvalidDataException("Shop inventory requires a merchant surface.");
            Shop.Validate();
        }
        if (CrystalSphere is not null)
        {
            if (SchemaVersion < 3 || Surface != OutsideCombatSurfaceKind.CrystalSphere)
            {
                throw new InvalidDataException(
                    "Crystal Sphere board requires a v3 Crystal Sphere observation.");
            }

            CrystalSphere.Validate();
        }
        else if (SchemaVersion >= 3 && Surface == OutsideCombatSurfaceKind.CrystalSphere)
        {
            throw new InvalidDataException(
                "Crystal Sphere v3 observation requires a visible board.");
        }
        if (ActIndex < 0 || ActFloor < 0 || TotalFloor < 0 || AscensionLevel < 0)
        {
            throw new InvalidDataException("Outside-combat run position cannot be negative.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(RoomType);
        ChoiceContext.Validate();
        if (CardSelectionOptions is { } options)
        {
            if (SchemaVersion < 5
                || Surface is not (OutsideCombatSurfaceKind.CardGridChoice
                    or OutsideCombatSurfaceKind.MerchantCardRemoval)
                || options.Count == 0
                || options.Where((option, index) => option.OptionIndex != index).Any()
                || options.Any(option => option is null)
                || options.Where(option => option.DeckIndex is not null)
                    .Select(option => option.DeckIndex)
                    .Distinct().Count()
                    != options.Count(option => option.DeckIndex is not null))
            {
                throw new InvalidDataException(
                    "Card-set candidates require a v5 grid observation in option order.");
            }

            foreach (var option in options)
            {
                option.Validate();
                if (option.DeckIndex is { } deckIndex
                    && (Players.Count != 1 || !Players[0].Deck.Any(card =>
                        card.DeckIndex == deckIndex
                        && string.Equals(card.ModelId, option.ModelId,
                            StringComparison.Ordinal))))
                {
                    throw new InvalidDataException(
                        "Card-set candidate does not match the observed deck.");
                }
            }
        }
        if (Players.Count == 0)
        {
            throw new InvalidDataException("Outside-combat observation requires at least one player.");
        }

        RequireUnique(Players.Select(player => player.PlayerId), "outside-combat player ID");
        foreach (var player in Players)
        {
            player.Validate();
            if (SchemaVersion >= 2 && player.Relics.Any(relic =>
                    relic.StackCount is not null || relic.IsUsedUp is not null
                    || relic.Status is not null || relic.DisplayAmount is not null))
            {
                throw new InvalidDataException(
                    "Outside-combat schema v2 cannot expose native relic fields.");
            }

            if (player.Deck.Any(card => card.EnchantmentDisplay is not null
                    && (SchemaVersion < 4 || card.EnchantmentId is null)))
            {
                throw new InvalidDataException(
                    "Outside-combat enchantment display requires a v4 enchanted card.");
            }
        }

        RequireUnique(MapPoints.Select(point => point.Coordinate), "outside-combat map coordinate");
        var coordinates = MapPoints.Select(point => point.Coordinate).ToHashSet();
        foreach (var point in MapPoints)
        {
            point.Validate();
            foreach (var child in point.Children)
            {
                if (!coordinates.Contains(child))
                {
                    throw new InvalidDataException(
                        $"Map point {point.Coordinate} references missing child {child}.");
                }
            }
        }

        if (CurrentMapCoordinate is { } current && !coordinates.Contains(current))
        {
            throw new InvalidDataException(
                $"Current map coordinate {current} is absent from the map observation.");
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

// Versioned native facts used by the isolated ArmG v11 bridge. Missing facts
// remain null/unsupported; they must not be inferred from a matching UI prompt.
public sealed record OutsideArmGNativeContext(
    int SchemaVersion,
    IReadOnlyList<string> ActIds,
    int GoldenPathAct,
    int UnknownMapPointsVisited,
    bool ApplyDiscoveryOrder,
    int NumberOfRuns,
    bool NeowUnlocked,
    bool OrobasUnlocked,
    bool DarvUnlocked,
    bool UnderdocksUnlocked,
    bool UnderdocksDiscovered,
    bool AeonglassSeen,
    IReadOnlyList<string> SeenEncounterIds,
    string BossEncounterId,
    string? SecondBossEncounterId,
    int PaelsToothStoredCount);

public sealed record OutsideShopItem(int SlotIndex, string? ModelId, int Cost, bool Sold,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? UpgradeLevel = null);
public sealed record OutsideShopObservation(
    IReadOnlyList<OutsideShopItem> Cards,
    IReadOnlyList<OutsideShopItem> Relics,
    IReadOnlyList<OutsideShopItem> Potions,
    int RemovalCost,
    bool RemovalAvailable)
{
    public void Validate()
    {
        if (RemovalCost < 0) throw new InvalidDataException("Invalid card removal price.");
        Check(Cards, 7); Check(Relics, 3); Check(Potions, 3);
    }

    private static void Check(IReadOnlyList<OutsideShopItem> items, int limit)
    {
        if (items is null || items.Count > limit
            || items.Where((item, i) => item is null || item.SlotIndex != i || item.Cost < 0
                || (!item.Sold && string.IsNullOrWhiteSpace(item.ModelId))).Any())
            throw new InvalidDataException("Invalid visible shop inventory.");
    }
}

/// <summary>
/// Player-visible Crystal Sphere minigame state. Item identity is only emitted
/// after the native reveal callback; covered items are never inspected for
/// feature values.
/// </summary>
public sealed record CrystalSphereBoardObservation(
    int Width,
    int Height,
    int DivinationsRemaining,
    string SelectedTool,
    bool IsFinished,
    IReadOnlyList<CrystalSphereCellObservation> Cells)
{
    public void Validate()
    {
        if (Width <= 0 || Height <= 0 || DivinationsRemaining < 0
            || Width > 32 || Height > 32 || Cells is null
            || Cells.Count != Width * Height
            || SelectedTool is not ("none" or "small" or "big"))
        {
            throw new InvalidDataException("Crystal Sphere board shape or tool is invalid.");
        }

        var coordinates = new HashSet<(int X, int Y)>();
        foreach (var cell in Cells)
        {
            cell.Validate();
            if (cell.X >= Width || cell.Y >= Height
                || !coordinates.Add((cell.X, cell.Y)))
            {
                throw new InvalidDataException(
                    "Crystal Sphere board has an out-of-bounds or duplicate cell.");
            }
        }
    }
}

public sealed record CrystalSphereCellObservation(
    int X,
    int Y,
    bool IsHidden,
    bool IsHighlighted,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? RevealedItemKind = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? RevealedVisualId = null)
{
    public void Validate()
    {
        if (X < 0 || Y < 0
            || (IsHidden && (RevealedItemKind is not null || RevealedVisualId is not null))
            || (RevealedItemKind is null && RevealedVisualId is not null))
        {
            throw new InvalidDataException(
                "Crystal Sphere cell exposes hidden content or invalid coordinates.");
        }

        if (RevealedItemKind is { Length: 0 }
            || RevealedVisualId is { Length: 0 })
        {
            throw new InvalidDataException("Crystal Sphere revealed visual value is empty.");
        }
    }
}

/// <summary>
/// Stable purpose and phase information that is not recoverable from a generic
/// screen class alone. In particular, it keeps upgrade/remove/transform card
/// selectors and multi-step minigames from collapsing to the same fingerprint.
/// </summary>
public sealed record OutsideCombatChoiceContext(
    string ContextId,
    string StateToken,
    OutsideCombatChoicePhase Phase,
    int? MinSelections,
    int? MaxSelections,
    int SelectedCount,
    bool Cancelable,
    bool RequiresConfirmation)
{
    // Frozen native deck identities; does not infer the selector's source relic.
    public IReadOnlyList<int>? SelectedDeckIndices { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ContextId);
        ProtocolJson.ValidateFingerprint(StateToken);
        if (!Enum.IsDefined(Phase) || SelectedCount < 0)
        {
            throw new InvalidDataException("Outside-combat choice phase or count is invalid.");
        }

        if (MinSelections.HasValue != MaxSelections.HasValue
            || MinSelections is < 0
            || (MinSelections is { } min
                && MaxSelections is { } boundedMax
                && boundedMax < min)
            || (MaxSelections is { } max && SelectedCount > max))
        {
            throw new InvalidDataException(
                "Outside-combat selection bounds are invalid or inconsistent.");
        }
    }
}

public enum OutsideCombatChoicePhase
{
    Default,
    Selection,
    Preview,
}

public enum OutsideCombatSurfaceKind
{
    Rewards,
    CardReward,
    CardChoice,
    CardBundleChoice,
    RelicChoice,
    CardGridChoice,
    MerchantCardRemoval,
    Event,
    RestSite,
    Merchant,
    Treasure,
    Map,
    CrystalSphere,
}

public readonly record struct OutsideMapCoordinate(int Row, int Column)
{
    public override string ToString() => $"({Row},{Column})";
}

public sealed record OutsideMapPointObservation(
    OutsideMapCoordinate Coordinate,
    string PointType,
    bool Visited,
    IReadOnlyList<OutsideMapCoordinate> Children)
{
    public void Validate()
    {
        ArgumentNullException.ThrowIfNull(Children);
        ArgumentException.ThrowIfNullOrWhiteSpace(PointType);
        if (Children.Distinct().Count() != Children.Count)
        {
            throw new InvalidDataException($"Map point {Coordinate} contains duplicate children.");
        }
    }
}

public sealed record OutsideRunPlayerObservation(
    ulong PlayerId,
    string CharacterId,
    int CurrentHp,
    int MaxHp,
    int Gold,
    int MaxPotionCount,
    IReadOnlyList<OutsideRunCardObservation> Deck,
    IReadOnlyList<OutsideRunRelicObservation> Relics,
    IReadOnlyList<PotionObservation> Potions)
{
    public void Validate()
    {
        ArgumentNullException.ThrowIfNull(Deck);
        ArgumentNullException.ThrowIfNull(Relics);
        ArgumentNullException.ThrowIfNull(Potions);
        ArgumentException.ThrowIfNullOrWhiteSpace(CharacterId);
        if (CurrentHp < 0 || MaxHp < 0 || CurrentHp > MaxHp || Gold < 0
            || MaxPotionCount < 0)
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has invalid persistent HP or gold.");
        }

        foreach (var card in Deck)
        {
            card.Validate();
        }

        var deckIndices = Deck.Select(card => card.DeckIndex).Order().ToArray();
        if (!deckIndices.SequenceEqual(Enumerable.Range(0, Deck.Count)))
        {
            throw new InvalidDataException(
                $"Player {PlayerId} deck indices must be unique and contiguous from zero.");
        }

        foreach (var relic in Relics)
        {
            relic.Validate();
        }

        var potionSlots = Potions.Select(potion => potion.SlotIndex).ToArray();
        // During a relic/effect transition the native slot collection can be
        // one frame ahead of MaxPotionCount. Preserve that valid observation
        // instead of disabling the whole policy; slot identity and uniqueness
        // are the stable contract needed by a learner.
        if (potionSlots.Any(slot => slot < 0)
            || potionSlots.Distinct().Count() != potionSlots.Length
            || Potions.Any(potion => string.IsNullOrWhiteSpace(potion.ModelId)))
        {
            throw new InvalidDataException(
                $"Player {PlayerId} has invalid or duplicate potion slots.");
        }
    }
}

public sealed record OutsideRunRelicObservation(
    string ModelId,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? StackCount = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] bool? IsUsedUp = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Status = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? DisplayAmount = null)
{
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public RelicDisplayObservation? Display { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        if (Status is not null)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(Status);
        }
        Display?.Validate();
    }
}

public sealed record OutsideRunCardObservation(
    int DeckIndex,
    string ModelId,
    int UpgradeLevel,
    string? EnchantmentId,
    string? AfflictionId)
{
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CardEnchantmentDisplayObservation? EnchantmentDisplay { get; init; }
    public int? EnchantmentAmount { get; init; }
    public bool? EnchantmentDisabled { get; init; }
    public int? GuiltyCombatsSeen { get; init; }
    public int? CurrentEnergyCost { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        if (DeckIndex < 0 || UpgradeLevel < 0)
        {
            throw new InvalidDataException(
                $"Card {ModelId} has a negative deck index or upgrade level.");
        }
        EnchantmentDisplay?.Validate();
    }
}

/// <summary>
/// Stable action data consumed and returned by policies. ActionId is meaningful
/// only together with the decision fingerprint; native UI objects stay in the
/// adapter's private execution binding.
/// </summary>
public sealed record OutsideCombatActionDescriptor(
    string ActionId,
    OutsideCombatActionKind Kind,
    int Ordinal,
    string? TargetId = null,
    OutsideMapCoordinate? MapCoordinate = null,
    int? Cost = null,
    int? TargetDeckIndex = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<OutsideSelectedCardReference>? SelectedCards = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<OutsideBundleCardReference>? BundleCards = null)
{
    /// <summary>The native belt slot of an outside-combat potion action.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? PotionSlotIndex { get; init; }

    /// <summary>Visible upgrade level for a single offered card, when available.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? TargetUpgradeLevel { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? TargetShopIndex { get; init; }

    /// <summary>
    /// One legal card-set action can stand for any set satisfying the observed
    /// candidate list and bounds. The actual set is recorded at submission.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    public bool IsSelectionTemplate { get; init; }

    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ActionId);
        if (!Enum.IsDefined(Kind))
        {
            throw new InvalidDataException($"Unsupported outside-combat action kind {Kind}.");
        }

        if (Ordinal < 0)
        {
            throw new InvalidDataException("Outside-combat action ordinal cannot be negative.");
        }

        if (Cost is < 0)
        {
            throw new InvalidDataException("Outside-combat action cost cannot be negative.");
        }

        if (TargetDeckIndex is < 0)
        {
            throw new InvalidDataException(
                "Outside-combat target deck index cannot be negative.");
        }

        if (TargetUpgradeLevel is < 0 || (TargetUpgradeLevel is not null
            && Kind is not (OutsideCombatActionKind.ChooseCard or OutsideCombatActionKind.RemoveCard
                or OutsideCombatActionKind.BuyCard or OutsideCombatActionKind.OpenCardRemoval)))
        {
            throw new InvalidDataException("Invalid target card upgrade level.");
        }

        if (PotionSlotIndex is < 0)
        {
            throw new InvalidDataException(
                "Outside-combat potion slot index cannot be negative.");
        }

        if (TargetShopIndex is < 0 || (TargetShopIndex is not null
            && Kind is not (OutsideCombatActionKind.BuyCard or OutsideCombatActionKind.BuyRelic
                or OutsideCombatActionKind.BuyPotion)))
            throw new InvalidDataException("Invalid shop item slot index.");

        if (Kind is OutsideCombatActionKind.UsePotion
            or OutsideCombatActionKind.DiscardPotion)
        {
            if (PotionSlotIndex is null || string.IsNullOrWhiteSpace(TargetId)
                || MapCoordinate is not null || Cost is not null
                || TargetDeckIndex is not null)
            {
                throw new InvalidDataException(
                    $"{Kind} requires a potion slot and model ID only.");
            }
        }
        else if (PotionSlotIndex is not null)
        {
            throw new InvalidDataException(
                "Only potion actions may carry a potion slot index.");
        }

        if (Kind == OutsideCombatActionKind.Travel && MapCoordinate is null)
        {
            throw new InvalidDataException("Travel action requires a map coordinate.");
        }

        if ((Kind is OutsideCombatActionKind.ChooseCard
                or OutsideCombatActionKind.RemoveCard
                or OutsideCombatActionKind.BuyCard
                or OutsideCombatActionKind.BuyRelic
                or OutsideCombatActionKind.BuyPotion)
            && string.IsNullOrWhiteSpace(TargetId))
        {
            throw new InvalidDataException($"{Kind} action requires a semantic target ID.");
        }

        if (Kind == OutsideCombatActionKind.RemoveCard && TargetDeckIndex is null)
        {
            throw new InvalidDataException(
                "RemoveCard action requires the target's observation deck index.");
        }

        if (Kind is OutsideCombatActionKind.ChooseCardSet
            or OutsideCombatActionKind.RemoveCardSet)
        {
            if ((IsSelectionTemplate && SelectedCards is not null)
                || (!IsSelectionTemplate && SelectedCards is null)
                || TargetDeckIndex is not null)
            {
                throw new InvalidDataException(
                    "A card-set template has no selected cards; a concrete action must have a set.");
            }

            foreach (var card in SelectedCards ?? [])
            {
                card.Validate();
            }

            var indexes = (SelectedCards ?? [])
                .Select(card => card.OptionIndex).ToArray();
            if (!indexes.SequenceEqual(indexes.Distinct().Order()))
            {
                throw new InvalidDataException(
                    "Card-set action option indexes must be unique and sorted.");
            }

            if (Kind == OutsideCombatActionKind.RemoveCardSet
                && SelectedCards is { } selected
                && (selected.Any(card => card.DeckIndex is null)
                    || selected.Select(card => card.DeckIndex).Distinct().Count()
                    != selected.Count))
            {
                throw new InvalidDataException(
                    "RemoveCardSet requires distinct observed deck indexes.");
            }
        }
        else if (SelectedCards is not null || IsSelectionTemplate)
        {
            throw new InvalidDataException(
                "Only card-set actions may contain selected cards.");
        }

        if (Kind == OutsideCombatActionKind.ChooseCardBundle)
        {
            if (BundleCards is not null)
            {
                if (BundleCards.Count == 0)
                {
                    throw new InvalidDataException("A card bundle cannot be empty.");
                }

                foreach (var card in BundleCards)
                {
                    card.Validate();
                }
            }
        }
        else if (BundleCards is not null)
        {
            throw new InvalidDataException(
                "Only ChooseCardBundle may contain bundle cards.");
        }
    }
}

public sealed record OutsideSelectedCardReference(
    int OptionIndex,
    string ModelId,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? DeckIndex = null)
{
    public void Validate()
    {
        if (OptionIndex < 0 || DeckIndex is < 0)
        {
            throw new InvalidDataException("Selected card indexes must be non-negative.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
    }
}

public sealed record OutsideBundleCardReference(string ModelId, int UpgradeLevel)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        if (UpgradeLevel < 0)
        {
            throw new InvalidDataException("Bundle card upgrade level cannot be negative.");
        }
    }
}

public enum OutsideCombatActionKind
{
    ClaimReward,
    ChooseCard,
    ChooseRelic,
    ChooseCardBundle,
    ChooseRewardAlternative,
    ChooseEventOption,
    ChooseRestSiteOption,
    ChooseMinigameOption,
    Confirm,
    Skip,
    Proceed,
    Travel,
    OpenMerchant,
    OpenCardRemoval,
    RemoveCard,
    LeaveMerchant,
    OpenChest,
    TakeTreasureRelic,
    /// <summary>Abort the current choice and complete its native task without a selection.</summary>
    CancelSelection,
    /// <summary>Leave a confirmation preview and return to the still-pending selector.</summary>
    BackToSelection,
    /// <summary>Buy a card from a merchant inventory.</summary>
    BuyCard,
    /// <summary>Buy a relic from a merchant inventory.</summary>
    BuyRelic,
    /// <summary>Buy a potion from a merchant inventory.</summary>
    BuyPotion,
    /// <summary>Choose an unordered set of visible card options in one native selection.</summary>
    ChooseCardSet,
    /// <summary>Remove an unordered set of cards identified in the observed deck.</summary>
    RemoveCardSet,
    /// <summary>Use an available potion in a native belt slot outside combat.</summary>
    UsePotion,
    /// <summary>Discard a potion in a native belt slot outside combat.</summary>
    DiscardPotion,
}

public sealed record OutsideCombatDecisionPoint(
    int SchemaVersion,
    BuildIdentity Build,
    long DecisionIndex,
    string StateFingerprint,
    OutsideCombatObservation Observation,
    IReadOnlyList<OutsideCombatActionDescriptor> LegalActions)
{
    public const int CurrentSchemaVersion = 1;

    /// <summary>
    /// Check the concrete result of a set-action template against the frozen
    /// visible candidates, without materializing every candidate subset.
    /// </summary>
    public static void ValidateSubmittedSetAction(
        OutsideCombatObservation observation,
        OutsideCombatActionDescriptor template,
        OutsideCombatActionDescriptor selected)
    {
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(template);
        ArgumentNullException.ThrowIfNull(selected);
        if (!template.IsSelectionTemplate
            || template.Kind is not (OutsideCombatActionKind.ChooseCardSet
                or OutsideCombatActionKind.RemoveCardSet)
            || selected.IsSelectionTemplate
            || selected.ActionId != template.ActionId
            || selected.Kind != template.Kind
            || selected.Ordinal != template.Ordinal
            || selected.TargetId != template.TargetId
            || selected.MapCoordinate != template.MapCoordinate
            || selected.Cost != template.Cost
            || selected.TargetDeckIndex != template.TargetDeckIndex
            || selected.PotionSlotIndex != template.PotionSlotIndex
            || selected.BundleCards is not null
            || observation.CardSelectionOptions is not { } candidates
            || observation.ChoiceContext.MinSelections is not { } min
            || observation.ChoiceContext.MaxSelections is not { } max
            || selected.SelectedCards is not { } chosen
            || chosen.Count < min || chosen.Count > max)
        {
            throw new InvalidDataException(
                "Submitted card set is not an instance of the legal template.");
        }

        selected.Validate();
        foreach (var card in chosen)
        {
            if (card.OptionIndex >= candidates.Count
                || card != candidates[card.OptionIndex])
            {
                throw new InvalidDataException(
                    "Submitted card set does not match a frozen candidate.");
            }
        }
    }

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat decision schema {SchemaVersion}; "
                + $"expected {CurrentSchemaVersion}.");
        }

        ArgumentNullException.ThrowIfNull(Build);
        ArgumentNullException.ThrowIfNull(Observation);
        ArgumentNullException.ThrowIfNull(LegalActions);
        if (DecisionIndex < 0)
        {
            throw new InvalidDataException("Outside-combat decision index must be non-negative.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(Build.GameVersion);
        ProtocolJson.ValidateFingerprint(Build.AssemblySha256);
        if (!Guid.TryParse(Build.AssemblyModuleVersionId, out _))
        {
            throw new InvalidDataException(
                "Outside-combat build identity has an invalid module version ID.");
        }

        ProtocolJson.ValidateFingerprint(StateFingerprint);
        Observation.Validate();
        if (LegalActions.Count == 0)
        {
            throw new InvalidDataException(
                "A non-terminal outside-combat decision must expose a legal action.");
        }

        foreach (var action in LegalActions)
        {
            action.Validate();
            if (!IsAllowedOnSurface(Observation.Surface, action.Kind))
            {
                throw new InvalidDataException(
                    $"Action {action.Kind} is not valid on outside-combat surface "
                    + $"{Observation.Surface}.");
            }

            if (action.Kind == OutsideCombatActionKind.RemoveCard)
            {
                if (Observation.Players.Count != 1)
                {
                    throw new InvalidDataException(
                        "Outside-combat RemoveCard v1 requires exactly one player.");
                }

                var target = Observation.Players[0].Deck.SingleOrDefault(card =>
                    card.DeckIndex == action.TargetDeckIndex);
                if (target is null
                    || !string.Equals(
                        target.ModelId,
                        action.TargetId,
                        StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        $"RemoveCard target {action.TargetId} at deck index "
                        + $"{action.TargetDeckIndex} is absent from the observation.");
                }
            }

            if (action.Kind is OutsideCombatActionKind.UsePotion
                or OutsideCombatActionKind.DiscardPotion)
            {
                if (Observation.Players.Count != 1
                    || !Observation.Players[0].Potions.Any(potion =>
                        potion.SlotIndex == action.PotionSlotIndex
                        && string.Equals(potion.ModelId, action.TargetId,
                            StringComparison.Ordinal)))
                {
                    throw new InvalidDataException(
                        $"{action.Kind} potion slot/model is absent from the observation.");
                }
            }

            if (action.Kind == OutsideCombatActionKind.Travel
                && !Observation.MapPoints.Any(point =>
                    point.Coordinate == action.MapCoordinate))
            {
                throw new InvalidDataException(
                    $"Travel target {action.MapCoordinate} is absent from the map observation.");
            }

            if (action.Kind == OutsideCombatActionKind.ChooseCard
                && action.TargetDeckIndex is { } deckIndex)
            {
                if (Observation.Players.Count != 1)
                {
                    throw new InvalidDataException(
                        "Deck-backed ChooseCard v1 requires exactly one player.");
                }

                var target = Observation.Players[0].Deck.SingleOrDefault(card =>
                    card.DeckIndex == deckIndex);
                if (target is null
                    || !string.Equals(target.ModelId, action.TargetId, StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        $"ChooseCard target {action.TargetId} at deck index {deckIndex} "
                        + "is absent from the observation.");
                }
            }

            if (action.Kind is OutsideCombatActionKind.ChooseCardSet
                or OutsideCombatActionKind.RemoveCardSet)
            {
                if (Observation.ChoiceContext.MinSelections is not { } min
                    || Observation.ChoiceContext.MaxSelections is not { } max
                    || (action.IsSelectionTemplate
                        ? Observation.CardSelectionOptions is not { } options
                          || min > options.Count || max < min || max > options.Count
                        : action.SelectedCards is not { } selected
                          || selected.Count < min || selected.Count > max))
                {
                    throw new InvalidDataException(
                        "Card-set action violates the observed selection bounds.");
                }

                foreach (var card in (action.SelectedCards ?? [])
                             .Where(card => card.DeckIndex is not null))
                {
                    if (Observation.Players.Count != 1
                        || !Observation.Players[0].Deck.Any(observed =>
                            observed.DeckIndex == card.DeckIndex
                            && string.Equals(observed.ModelId, card.ModelId,
                                StringComparison.Ordinal)))
                    {
                        throw new InvalidDataException(
                            $"Card-set deck target {card.ModelId} at index "
                            + $"{card.DeckIndex} is absent from the observation.");
                    }
                }
            }

            if (Observation.CrystalSphere is { } sphere)
            {
                if (action.Kind == OutsideCombatActionKind.Proceed)
                {
                    if (!sphere.IsFinished || action.TargetId != "proceed")
                    {
                        throw new InvalidDataException(
                            "Crystal Sphere Proceed requires a finished visible board.");
                    }
                }
                else if (action.Kind == OutsideCombatActionKind.ChooseMinigameOption)
                {
                    if (sphere.IsFinished || !IsObservedCrystalSphereOption(
                            sphere, action.TargetId))
                    {
                        throw new InvalidDataException(
                            "Crystal Sphere action is absent from the visible board.");
                    }
                }
            }
        }

        if (LegalActions.Select(action => action.ActionId).Distinct(StringComparer.Ordinal).Count()
            != LegalActions.Count)
        {
            throw new InvalidDataException("Outside-combat action IDs must be unique.");
        }

        if (LegalActions.Where((action, index) => action.Ordinal != index).Any())
        {
            throw new InvalidDataException(
                "Outside-combat actions must be stored in ordinal order from zero.");
        }

        var computedFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
            Build,
            Observation,
            LegalActions);
        if (!string.Equals(
                StateFingerprint,
                computedFingerprint,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                $"Outside-combat state fingerprint does not match its payload. "
                + $"Expected {computedFingerprint}, found {StateFingerprint}.");
        }
    }

    private static bool IsObservedCrystalSphereOption(
        CrystalSphereBoardObservation sphere,
        string? target)
    {
        if (target is "tool:small" or "tool:big")
        {
            return true;
        }

        if (sphere.DivinationsRemaining <= 0
            || target is null
            || !target.StartsWith("cell:", StringComparison.Ordinal))
        {
            return false;
        }

        var coordinates = target["cell:".Length..].Split(',');
        return coordinates.Length == 2
               && int.TryParse(coordinates[0], out var x)
               && int.TryParse(coordinates[1], out var y)
               && sphere.Cells.Any(cell => cell.X == x && cell.Y == y && cell.IsHidden);
    }

    private static bool IsAllowedOnSurface(
        OutsideCombatSurfaceKind surface,
        OutsideCombatActionKind action) => surface switch
    {
        OutsideCombatSurfaceKind.Rewards => action is
            OutsideCombatActionKind.ClaimReward
            or OutsideCombatActionKind.Proceed
            or OutsideCombatActionKind.UsePotion
            or OutsideCombatActionKind.DiscardPotion,
        OutsideCombatSurfaceKind.CardReward => action is
            OutsideCombatActionKind.ChooseCard
            or OutsideCombatActionKind.ChooseRewardAlternative
            or OutsideCombatActionKind.Skip,
        OutsideCombatSurfaceKind.CardChoice => action is
            OutsideCombatActionKind.ChooseCard or OutsideCombatActionKind.Skip,
        OutsideCombatSurfaceKind.CardBundleChoice => action is
            OutsideCombatActionKind.ChooseCardBundle or OutsideCombatActionKind.Confirm,
        OutsideCombatSurfaceKind.RelicChoice => action is
            OutsideCombatActionKind.ChooseRelic or OutsideCombatActionKind.Skip,
        OutsideCombatSurfaceKind.CardGridChoice => action is
            OutsideCombatActionKind.ChooseCard
            or OutsideCombatActionKind.ChooseCardSet
            or OutsideCombatActionKind.RemoveCard
            or OutsideCombatActionKind.RemoveCardSet
            or OutsideCombatActionKind.Confirm
            or OutsideCombatActionKind.CancelSelection
            or OutsideCombatActionKind.BackToSelection,
        OutsideCombatSurfaceKind.MerchantCardRemoval => action is
            OutsideCombatActionKind.RemoveCard
            or OutsideCombatActionKind.RemoveCardSet
            or OutsideCombatActionKind.Confirm
            or OutsideCombatActionKind.CancelSelection
            or OutsideCombatActionKind.BackToSelection,
        OutsideCombatSurfaceKind.Event => action is
            OutsideCombatActionKind.ChooseEventOption
            or OutsideCombatActionKind.ChooseMinigameOption,
        OutsideCombatSurfaceKind.RestSite => action is
            OutsideCombatActionKind.ChooseRestSiteOption or OutsideCombatActionKind.Proceed,
        OutsideCombatSurfaceKind.Merchant => action is
            OutsideCombatActionKind.OpenMerchant
            or OutsideCombatActionKind.OpenCardRemoval
            or OutsideCombatActionKind.BuyCard
            or OutsideCombatActionKind.BuyRelic
            or OutsideCombatActionKind.BuyPotion
            or OutsideCombatActionKind.LeaveMerchant
            or OutsideCombatActionKind.Proceed
            or OutsideCombatActionKind.UsePotion
            or OutsideCombatActionKind.DiscardPotion,
        OutsideCombatSurfaceKind.Treasure => action is
            OutsideCombatActionKind.OpenChest
            or OutsideCombatActionKind.TakeTreasureRelic
            or OutsideCombatActionKind.Proceed,
        OutsideCombatSurfaceKind.Map => action == OutsideCombatActionKind.Travel,
        OutsideCombatSurfaceKind.CrystalSphere => action is
            OutsideCombatActionKind.ChooseMinigameOption or OutsideCombatActionKind.Proceed,
        _ => false,
    };
}

/// <summary>
/// Policy-to-adapter command. ExpectedStateFingerprint prevents a delayed model
/// response from being executed on a different screen or run state.
/// </summary>
public sealed record OutsideCombatStepRequest(
    Guid RequestId,
    string ExpectedStateFingerprint,
    string ActionId)
{
    public void Validate()
    {
        if (RequestId == Guid.Empty)
        {
            throw new InvalidDataException(
                "An outside-combat step request requires a non-empty request ID.");
        }

        ProtocolJson.ValidateFingerprint(ExpectedStateFingerprint);
        ArgumentException.ThrowIfNullOrWhiteSpace(ActionId);
    }
}

public static class OutsideCombatStepGuard
{
    public static OutsideCombatActionDescriptor RequireCurrentAction(
        OutsideCombatStepRequest request,
        OutsideCombatDecisionPoint currentDecision)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(currentDecision);
        request.Validate();
        currentDecision.Validate();
        if (!string.Equals(
                request.ExpectedStateFingerprint,
                currentDecision.StateFingerprint,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new StaleOutsideCombatStateException(
                request.ExpectedStateFingerprint,
                currentDecision.StateFingerprint);
        }

        return currentDecision.LegalActions.SingleOrDefault(action => string.Equals(
                action.ActionId,
                request.ActionId,
                StringComparison.Ordinal))
            ?? throw new InvalidDataException(
                $"Outside-combat action '{request.ActionId}' is not legal in the current decision.");
    }
}

public sealed class StaleOutsideCombatStateException : InvalidOperationException
{
    public StaleOutsideCombatStateException(string expected, string actual)
        : base(
            $"Outside-combat state changed before the action was applied. "
            + $"Expected {expected}, found {actual}.")
    {
        Expected = expected;
        Actual = actual;
    }

    public string Expected { get; }

    public string Actual { get; }
}

/// <summary>
/// One policy decision as stored for imitation learning or later trajectory
/// assembly. EpisodeId groups decisions without exposing a game seed to policy.
/// </summary>
public sealed record OutsideCombatDecisionSample(
    int SchemaVersion,
    Guid EpisodeId,
    string PolicyId,
    OutsideCombatDecisionPoint Decision,
    OutsideCombatStepRequest Step)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat sample schema {SchemaVersion}; "
                + $"expected {CurrentSchemaVersion}.");
        }

        if (EpisodeId == Guid.Empty)
        {
            throw new InvalidDataException("Outside-combat sample requires an episode ID.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(PolicyId);
        Decision.Validate();
        Step.Validate();
        if (!string.Equals(
                Decision.StateFingerprint,
                Step.ExpectedStateFingerprint,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Outside-combat step fingerprint does not match its decision.");
        }

        if (!Decision.LegalActions.Any(action =>
                string.Equals(action.ActionId, Step.ActionId, StringComparison.Ordinal)))
        {
            throw new InvalidDataException(
                $"Outside-combat step references unknown action '{Step.ActionId}'.");
        }
    }
}

/// <summary>
/// Result of handing a selected action to the native adapter. It is kept
/// separate from the observation-action sample so a failed UI transaction is
/// never silently mislabeled as successful training data.
/// </summary>
public sealed record OutsideCombatExecutionResult(
    int SchemaVersion,
    Guid EpisodeId,
    long DecisionIndex,
    string PolicyId,
    Guid RequestId,
    string ExpectedStateFingerprint,
    string ActionId,
    OutsideCombatExecutionStatus Status,
    string? Detail = null)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat result schema {SchemaVersion}; "
                + $"expected {CurrentSchemaVersion}.");
        }

        if (EpisodeId == Guid.Empty || RequestId == Guid.Empty || DecisionIndex < 0)
        {
            throw new InvalidDataException(
                "Outside-combat result has an invalid episode, request, or decision index.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(PolicyId);
        ArgumentException.ThrowIfNullOrWhiteSpace(ActionId);
        ProtocolJson.ValidateFingerprint(ExpectedStateFingerprint);
        if (!Enum.IsDefined(Status))
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat execution status {Status}.");
        }

        if ((Status is OutsideCombatExecutionStatus.Failed
                or OutsideCombatExecutionStatus.TimedOut)
            && string.IsNullOrWhiteSpace(Detail))
        {
            throw new InvalidDataException(
                $"Outside-combat {Status} result requires diagnostic detail.");
        }
    }
}

public enum OutsideCombatExecutionStatus
{
    /// <summary>The native input was followed by a different observable state.</summary>
    ObservedTransition,
    /// <summary>The native transaction explicitly reported success.</summary>
    Applied,
    /// <summary>The native transaction completed without applying the selection.</summary>
    Cancelled,
    Failed,
    TimedOut,
}

/// <summary>
/// Minimal policy boundary shared by live play, headless evaluation, and future
/// learned policies. Implementations never receive native game objects.
/// </summary>
public interface IOutsideCombatPolicy
{
    string PolicyId { get; }

    OutsideCombatActionDescriptor SelectAction(OutsideCombatDecisionPoint decision);
}

public sealed class FirstLegalOutsideCombatPolicy : IOutsideCombatPolicy
{
    public const string Id = "first-legal";

    public string PolicyId => Id;

    public OutsideCombatActionDescriptor SelectAction(OutsideCombatDecisionPoint decision)
    {
        ArgumentNullException.ThrowIfNull(decision);
        decision.Validate();
        var cardRemoval = decision.LegalActions
            .Where(action => action.Kind == OutsideCombatActionKind.RemoveCard)
            .OrderBy(action => RemovalPriority(action.TargetId!))
            .ThenBy(action => action.TargetId, StringComparer.Ordinal)
            .ThenBy(action => action.Ordinal)
            .FirstOrDefault();
        return cardRemoval
            ?? decision.LegalActions.MinBy(action => action.Ordinal)
            ?? throw new InvalidDataException("Outside-combat decision has no legal action.");
    }

    private static int RemovalPriority(string modelId)
    {
        var entry = modelId
            .Split([':', '/', '.'], StringSplitOptions.RemoveEmptyEntries)
            .LastOrDefault() ?? modelId;
        return entry.Equals("STRIKE", StringComparison.Ordinal)
            || entry.StartsWith("STRIKE_", StringComparison.Ordinal) ? 0
            : entry.Equals("DEFEND", StringComparison.Ordinal)
                || entry.StartsWith("DEFEND_", StringComparison.Ordinal) ? 1
                : 2;
    }
}
