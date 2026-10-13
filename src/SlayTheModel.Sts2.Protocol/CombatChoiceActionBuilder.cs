namespace SlayTheModel.Sts2.Protocol;

/// <summary>
/// Builds policy-facing actions for a frozen, visible card selector. Single
/// choices retain one action per card; multi-card choices use one set template
/// and put the selected set in the eventual submitted action.
/// </summary>
public static class CombatChoiceActionBuilder
{
    // Only the legacy single-card path allocates one action per candidate.
    // Multi-card choices have one template regardless of set count.
    public const int MaximumSingleChoiceActions = 4096;

    public static IReadOnlyList<CombatActionDescriptor> Build(
        ulong actorPlayerId,
        CombatChoiceObservation choice)
    {
        ArgumentNullException.ThrowIfNull(choice);
        choice.Validate();

        var includeEmpty = choice.MinSelections == 0 || choice.CanCancel;
        if (choice.MaxSelections == 1)
        {
            if (choice.Cards.Count + (includeEmpty ? 1 : 0) > MaximumSingleChoiceActions)
            {
                throw new InvalidDataException(
                    "Combat card choice exceeds the legal action limit.");
            }

            // Keep the legacy single-card descriptor shape and action order.
            var singleActions = choice.Cards.Select(card =>
                new CombatActionDescriptor(
                    CombatActionKind.ResolveChoice,
                    actorPlayerId,
                    ChoiceId: choice.ChoiceId,
                    SelectedCombatCardIds: card.CombatCardIndex is { } cardId
                        ? [cardId]
                        : null,
                    OptionIndex: card.OptionIndex)).ToList();
            if (includeEmpty)
            {
                singleActions.Add(Empty(actorPlayerId, choice.ChoiceId));
            }

            return singleActions;
        }

        // A model ID is not an instance ID: two identical cards must remain
        // different candidates. Native IDs are required for the existing
        // aggregate-set descriptor; generated-card sets need another contract.
        if (choice.Cards.Any(card => card.CombatCardIndex is null))
        {
            throw new InvalidDataException(
                "Multi-card choices need a native ID for every offered card.");
        }

        var actions = new List<CombatActionDescriptor>
        {
            new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                actorPlayerId,
                ChoiceId: choice.ChoiceId,
                IsSelectionTemplate: true),
        };
        // A native cancel can complete with an empty Task result even when
        // the selection itself requires cards. Keep it distinct from the set
        // template so the model never learns an out-of-bounds empty set.
        if (choice.CanCancel && choice.MinSelections > 0)
        {
            actions.Add(Empty(actorPlayerId, choice.ChoiceId));
        }

        return actions;
    }

    private static CombatActionDescriptor Empty(ulong actorPlayerId, uint choiceId) =>
        new(CombatActionKind.ResolveChoice, actorPlayerId,
            ChoiceId: choiceId, SelectedCombatCardIds: []);
}
