using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>Minimal deterministic choices for the live integration policy.</summary>
internal sealed class FirstLegalCardSelector : ICardSelector
{
    public Task<IEnumerable<CardModel>> GetSelectedCards(
        IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        if (minSelect < 0 || maxSelect < minSelect)
        {
            throw new ArgumentOutOfRangeException(nameof(minSelect), "Invalid card selection bounds.");
        }

        // The command has already filtered eligibility. Match the game's behavior
        // when fewer candidates remain than required; optional choices select none.
        var selected = options.Take(minSelect).ToArray();
        Console.WriteLine(
            $"[SlayTheModel] live choice min={minSelect} max={maxSelect} "
            + $"selected=[{string.Join(",", selected.Select(card => card.Id.Entry))}]");
        return Task.FromResult<IEnumerable<CardModel>>(selected);
    }

    public CardRewardSelection GetSelectedCardReward(
        IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives) =>
        throw new NotSupportedException("The combat policy does not select run rewards.");
}
