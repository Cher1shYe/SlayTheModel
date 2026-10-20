using System.Text.Json.Serialization;

namespace SlayTheModel.Sts2.Protocol;

public sealed record CombatActionDescriptor(
    CombatActionKind Kind,
    ulong ActorPlayerId,
    uint? CombatCardIndex = null,
    uint? PotionIndex = null,
    uint? TargetCreatureId = null,
    uint? ChoiceId = null,
    IReadOnlyList<uint>? SelectedCombatCardIds = null,
    IReadOnlyList<string>? SelectedModelIds = null,
    int? OptionIndex = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    bool IsSelectionTemplate = false)
{
    public void Validate()
    {
        if (IsSelectionTemplate && (Kind != CombatActionKind.ResolveChoice
                                    || SelectedCombatCardIds is not null
                                    || SelectedModelIds is not null
                                    || OptionIndex is not null))
        {
            throw new InvalidDataException(
                "A combat selection template cannot contain a selected card.");
        }

        switch (Kind)
        {
            case CombatActionKind.PlayCard when CombatCardIndex is null:
                throw new InvalidDataException("PlayCard requires a combat card index.");
            case CombatActionKind.UsePotion when PotionIndex is null:
                throw new InvalidDataException("UsePotion requires a potion index.");
            case CombatActionKind.ResolveChoice when ChoiceId is null:
                throw new InvalidDataException("ResolveChoice requires a choice ID.");
            case CombatActionKind.ResolveChoice when OptionIndex is < 0:
                throw new InvalidDataException("ResolveChoice option index must be non-negative.");
            case CombatActionKind.EndTurn:
            case CombatActionKind.PlayCard:
            case CombatActionKind.UsePotion:
            case CombatActionKind.ResolveChoice:
                break;
            default:
                throw new InvalidDataException($"Unsupported combat action kind {Kind}.");
        }
    }
}

public enum CombatActionKind
{
    PlayCard,
    UsePotion,
    EndTurn,
    ResolveChoice,
}

public sealed record CombatDecisionPoint(
    int SchemaVersion,
    long DecisionIndex,
    string StateFingerprint,
    CombatObservation Observation,
    IReadOnlyList<CombatActionDescriptor> LegalActions)
{
    public const int CurrentSchemaVersion = 1;

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported combat decision schema {SchemaVersion}; expected {CurrentSchemaVersion}.");
        }

        if (DecisionIndex < 0)
        {
            throw new InvalidDataException("Decision index must be non-negative.");
        }

        ProtocolJson.ValidateFingerprint(StateFingerprint);
        Observation.Validate();
        if (LegalActions.Count == 0)
        {
            throw new InvalidDataException("A non-terminal decision point must expose a legal action.");
        }

        foreach (var action in LegalActions)
        {
            action.Validate();
        }

        var playerIds = Observation.Players.Select(player => player.PlayerId).ToHashSet();
        var creatureIds = Observation.Creatures.Select(creature => creature.CombatId).ToHashSet();
        var cardIds = Observation.Players
            .SelectMany(player => player.Piles)
            .SelectMany(pile => pile.Cards)
            .Select(card => card.CombatCardIndex)
            .ToHashSet();

        foreach (var action in LegalActions)
        {
            if (!playerIds.Contains(action.ActorPlayerId))
            {
                throw new InvalidDataException(
                    $"Action references unknown player {action.ActorPlayerId}.");
            }

            if (action.TargetCreatureId is { } target && !creatureIds.Contains(target))
            {
                throw new InvalidDataException($"Action references unknown creature {target}.");
            }

            if (action.CombatCardIndex is { } card && !cardIds.Contains(card))
            {
                throw new InvalidDataException($"Action references unknown combat card {card}.");
            }

            if (action.Kind == CombatActionKind.ResolveChoice)
            {
                var choice = Observation.ActiveChoice
                    ?? throw new InvalidDataException("ResolveChoice requires an active choice observation.");
                if (action.IsSelectionTemplate)
                {
                    if (choice.MaxSelections <= 1
                        || LegalActions.Count != (choice.CanCancel && choice.MinSelections > 0 ? 2 : 1)
                        || action.ChoiceId != choice.ChoiceId
                        || action.CombatCardIndex is not null
                        || action.PotionIndex is not null
                        || action.TargetCreatureId is not null)
                    {
                        throw new InvalidDataException(
                            "Combat selection template does not match the visible choice.");
                    }

                    continue;
                }

                var selected = action.SelectedCombatCardIds;
                var offered = choice.Cards
                    .Where(option => option.CombatCardIndex.HasValue)
                    .Select(option => option.CombatCardIndex!.Value)
                    .ToHashSet();
                var hasIndexedOptions = choice.Cards[0].OptionIndex.HasValue;
                var selectedCount = hasIndexedOptions && action.OptionIndex.HasValue
                    ? 1
                    : selected?.Count ?? -1;
                var option = hasIndexedOptions && action.OptionIndex is { } optionIndex
                    ? choice.Cards.SingleOrDefault(card => card.OptionIndex == optionIndex)
                    : null;
                if (action.ChoiceId != choice.ChoiceId
                    || selectedCount < 0
                    || selected is not null && selected.Count != selected.Distinct().Count()
                    || selected is not null && selected.Any(id => !offered.Contains(id))
                    || hasIndexedOptions && action.OptionIndex.HasValue && option is null
                    || hasIndexedOptions && action.OptionIndex.HasValue && selected is { Count: 0 }
                    || hasIndexedOptions && action.OptionIndex.HasValue && selected is { Count: > 0 }
                       && (selected.Count != 1 || option?.CombatCardIndex != selected[0])
                    || selectedCount != 0 && selectedCount < choice.MinSelections
                    || selectedCount > choice.MaxSelections
                    || selectedCount == 0 && !choice.CanCancel && choice.MinSelections > 0)
                {
                    throw new InvalidDataException("ResolveChoice does not match the visible choice.");
                }
            }
            else if (Observation.ActiveChoice is not null)
            {
                throw new InvalidDataException("A card choice decision can only resolve that choice.");
            }
        }

        if (LegalActions.Any(action => action.IsSelectionTemplate))
        {
            var choice = Observation.ActiveChoice!;
            if (LegalActions.Count(action => action.IsSelectionTemplate) != 1
                || choice.CanCancel && choice.MinSelections > 0
                   && (LegalActions[1].IsSelectionTemplate
                       || LegalActions[1].Kind != CombatActionKind.ResolveChoice
                       || LegalActions[1].SelectedCombatCardIds is not { Count: 0 }
                       || LegalActions[1].ChoiceId != choice.ChoiceId))
            {
                throw new InvalidDataException(
                    "Combat card-set choice requires one template and its optional cancel action.");
            }
        }
    }

    /// <summary>
    /// Checks the completed unordered card set against the one legal template
    /// and the click-time choice. The journal records the concrete action in
    /// action_submitted instead of enumerating every possible set in decision.
    /// </summary>
    public static void ValidateSubmittedSetAction(
        CombatObservation observation,
        CombatActionDescriptor template,
        CombatActionDescriptor concrete)
    {
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(template);
        ArgumentNullException.ThrowIfNull(concrete);
        var choice = observation.ActiveChoice
            ?? throw new InvalidDataException("Combat set submission has no active choice.");
        if (!template.IsSelectionTemplate || concrete.IsSelectionTemplate
            || template.Kind != CombatActionKind.ResolveChoice
            || concrete.Kind != template.Kind
            || concrete.ActorPlayerId != template.ActorPlayerId
            || concrete.ChoiceId != template.ChoiceId
            || concrete.ChoiceId != choice.ChoiceId
            || template.CombatCardIndex is not null || concrete.CombatCardIndex is not null
            || template.PotionIndex is not null || concrete.PotionIndex is not null
            || template.TargetCreatureId is not null || concrete.TargetCreatureId is not null
            || template.OptionIndex is not null || concrete.OptionIndex is not null
            || template.SelectedCombatCardIds is not null
            || template.SelectedModelIds is not null || concrete.SelectedModelIds is not null
            || choice.MaxSelections <= 1
            || concrete.SelectedCombatCardIds is not { } selected)
        {
            throw new InvalidDataException("Concrete combat set does not match its template.");
        }

        concrete.Validate();
        var offered = choice.Cards
            .Select(card => card.CombatCardIndex)
            .Where(id => id.HasValue)
            .Select(id => id!.Value)
            .ToHashSet();
        if (!selected.SequenceEqual(selected.Distinct().Order())
            || selected.Any(id => !offered.Contains(id))
            || selected.Count > choice.MaxSelections
            || selected.Count < choice.MinSelections)
        {
            throw new InvalidDataException(
                "Concrete combat set violates visible candidates or selection bounds.");
        }
    }

    /// <summary>
    /// Enforces the slot contract for newly captured decisions. Historical
    /// episodes can contain compacted potion observations and must remain
    /// replayable so an auditor can identify their bad training fields.
    /// </summary>
    public void ValidatePotionActionReferences()
    {
        Validate();
        foreach (var action in LegalActions)
        {
            if (action.Kind != CombatActionKind.UsePotion)
            {
                continue;
            }

            var potionIndex = action.PotionIndex!.Value;
            if (!Observation.Players
                    .Single(player => player.PlayerId == action.ActorPlayerId)
                    .Potions.Any(potion => (uint)potion.SlotIndex == potionIndex))
            {
                throw new InvalidDataException(
                    $"UsePotion references a potion slot absent from player {action.ActorPlayerId}'s observation: {potionIndex}.");
            }
        }
    }
}

/// <summary>
/// Internal search boundary: the simulator receives the complete state, while a
/// combat policy receives only Decision and a run policy receives only RunObservation.
/// </summary>
public sealed record CombatSearchPoint(
    CombatSnapshot SimulatorState,
    RunObservation RunObservation,
    CombatDecisionPoint Decision)
{
    public void Validate()
    {
        SimulatorState.Validate();
        RunObservation.Validate();
        Decision.Validate();

        if (Decision.DecisionIndex != SimulatorState.DecisionIndex)
        {
            throw new InvalidDataException(
                "Simulator state and combat decision have different decision indices.");
        }

        var expectedFingerprint = ProtocolJson.ComputeStateFingerprint(SimulatorState);
        if (!string.Equals(
                Decision.StateFingerprint,
                expectedFingerprint,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Combat decision fingerprint does not match its simulator state.");
        }
    }
}
