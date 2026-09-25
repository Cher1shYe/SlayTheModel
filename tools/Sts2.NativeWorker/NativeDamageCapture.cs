using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.ValueProps;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Entities.Cards;

// Worker-only observer of the canonical damage command's actual results.
// History omits terminal hits; LoseHpInternal also serves Kill/self-destruction.
// Neither is a substitute for the command's damage results.
internal static class NativeDamageCapture
{
    internal static ICombatState? ActiveCombat;
    internal static Action<DamageResult>? Sink;

    [HarmonyPatch(typeof(CreatureCmd), nameof(CreatureCmd.Damage),
        [typeof(PlayerChoiceContext), typeof(IEnumerable<Creature>), typeof(decimal),
         typeof(ValueProp), typeof(Creature), typeof(CardModel), typeof(CardPlay)])]
    private static class DamagePatch
    {
        private static void Postfix(ref Task<IEnumerable<DamageResult>> __result)
        {
            if (Sink != null) __result = CaptureAsync(__result, ActiveCombat);
        }

        private static async Task<IEnumerable<DamageResult>> CaptureAsync(
            Task<IEnumerable<DamageResult>> original, ICombatState? combat)
        {
            var results = (await original).ToArray();
            if (!ReferenceEquals(combat, ActiveCombat) || Sink == null)
                throw new InvalidDataException("Native damage completed outside its owning transition.");
            foreach (var result in results) Sink(result);
            return results;
        }
    }
}
