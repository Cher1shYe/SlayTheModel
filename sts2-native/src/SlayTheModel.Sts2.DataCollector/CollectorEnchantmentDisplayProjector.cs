using MegaCrit.Sts2.Core.Entities.Enchantments;
using MegaCrit.Sts2.Core.Models;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Reconstructs only the enchantment presentation available by inspecting a
/// known card. In v0.111.0 NCard.UpdateEnchantmentVisuals writes DisplayAmount
/// to its label only when ShowAmount is true, and fades a Disabled icon.
/// EnchantmentModel.HoverTip supplies Title and DynamicDescription to the
/// native card's hover tips. Raw Amount/Status are not policy features.
/// </summary>
internal static class CollectorEnchantmentDisplayProjector
{
    internal static CardEnchantmentDisplayObservation? Capture(CardModel card)
    {
        ArgumentNullException.ThrowIfNull(card);
        if (card.Enchantment is not { } enchantment)
        {
            return null;
        }

        try
        {
            var title = enchantment.Title.GetFormattedText();
            var description = enchantment.DynamicDescription.GetFormattedText();
            if (string.IsNullOrWhiteSpace(title) || description is null)
            {
                return null;
            }

            var appearance = enchantment.Status switch
            {
                EnchantmentStatus.Normal => "normal",
                EnchantmentStatus.Disabled => "dimmed",
                _ => null,
            };
            if (appearance is null)
            {
                return null;
            }

            return new CardEnchantmentDisplayObservation(
                title,
                description,
                enchantment.ShowAmount ? enchantment.DisplayAmount : null,
                appearance);
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            // A failed native/localized display read is missing data, never a
            // reason to expose the internal amount as a substitute.
            return null;
        }
    }
}
