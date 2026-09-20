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
    int? OptionIndex = null)
{
    public void Validate()
    {
        switch (Kind)
        {
            case CombatActionKind.PlayCard when CombatCardIndex is null:
                throw new InvalidDataException("PlayCard requires a combat card index.");
            case CombatActionKind.UsePotion when PotionIndex is null:
                throw new InvalidDataException("UsePotion requires a potion index.");
            case CombatActionKind.ResolveChoice when ChoiceId is null:
                throw new InvalidDataException("ResolveChoice requires a choice ID.");
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
