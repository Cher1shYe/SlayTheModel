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
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported outside-combat observation schema {SchemaVersion}; "
                + $"expected {CurrentSchemaVersion}.");
        }

        if (!Enum.IsDefined(Surface))
        {
            throw new InvalidDataException($"Unsupported outside-combat surface {Surface}.");
        }

        ArgumentNullException.ThrowIfNull(Players);
        ArgumentNullException.ThrowIfNull(MapPoints);
        ArgumentNullException.ThrowIfNull(ChoiceContext);
        if (ActIndex < 0 || ActFloor < 0 || TotalFloor < 0 || AscensionLevel < 0)
        {
            throw new InvalidDataException("Outside-combat run position cannot be negative.");
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(RoomType);
        ChoiceContext.Validate();
        if (Players.Count == 0)
        {
            throw new InvalidDataException("Outside-combat observation requires at least one player.");
        }

        RequireUnique(Players.Select(player => player.PlayerId), "outside-combat player ID");
        foreach (var player in Players)
        {
            player.Validate();
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
    int StackCount,
    bool IsUsedUp,
    string Status,
    int DisplayAmount)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        ArgumentException.ThrowIfNullOrWhiteSpace(Status);
        // Keep StackCount and DisplayAmount lossless. Native relics may use
        // sentinel values, including negative values, for their own UI state.
    }
}

public sealed record OutsideRunCardObservation(
    int DeckIndex,
    string ModelId,
    int UpgradeLevel,
    string? EnchantmentId,
    string? AfflictionId)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ModelId);
        if (DeckIndex < 0 || UpgradeLevel < 0)
        {
            throw new InvalidDataException(
                $"Card {ModelId} has a negative deck index or upgrade level.");
        }
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
    int? TargetDeckIndex = null)
{
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

        if (Kind == OutsideCombatActionKind.Travel && MapCoordinate is null)
        {
            throw new InvalidDataException("Travel action requires a map coordinate.");
        }

        if ((Kind is OutsideCombatActionKind.ChooseCard or OutsideCombatActionKind.RemoveCard)
            && string.IsNullOrWhiteSpace(TargetId))
        {
            throw new InvalidDataException($"{Kind} action requires a target card model ID.");
        }

        if (Kind == OutsideCombatActionKind.RemoveCard && TargetDeckIndex is null)
        {
            throw new InvalidDataException(
                "RemoveCard action requires the target's observation deck index.");
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

    private static bool IsAllowedOnSurface(
        OutsideCombatSurfaceKind surface,
        OutsideCombatActionKind action) => surface switch
    {
        OutsideCombatSurfaceKind.Rewards => action is
            OutsideCombatActionKind.ClaimReward or OutsideCombatActionKind.Proceed,
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
            or OutsideCombatActionKind.Confirm
            or OutsideCombatActionKind.CancelSelection
            or OutsideCombatActionKind.BackToSelection,
        OutsideCombatSurfaceKind.MerchantCardRemoval => action is
            OutsideCombatActionKind.RemoveCard
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
            or OutsideCombatActionKind.LeaveMerchant
            or OutsideCombatActionKind.Proceed,
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
