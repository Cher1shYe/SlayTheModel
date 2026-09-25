using System.Reflection;
using CombatSolver.Engine.Common;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Relics;

namespace CombatSolver;

internal sealed partial class SimulatedCombatState
{
    private static readonly HashSet<string> PostCombatRewardHookNames =
    [
        nameof(AbstractModel.AfterCombatVictoryEarly),
        nameof(AbstractModel.AfterCombatVictory),
        nameof(AbstractModel.AfterCombatEnd),
    ];

    internal void EnsureSupportedPostCombatRewardEffects()
    {
        foreach (AbstractModel listener in GetEffectiveHookListeners())
        {
            Type type = listener.GetType();
            foreach (MethodInfo method in type.GetMethods(BindingFlags.Instance
                         | BindingFlags.Public | BindingFlags.NonPublic))
            {
                if (!PostCombatRewardHookNames.Contains(method.Name)
                    || method.DeclaringType == typeof(AbstractModel)
                    || method.DeclaringType == typeof(RelicModel)
                    || method.DeclaringType == typeof(CardModel)
                    || method.DeclaringType == typeof(PowerModel))
                    continue;
                if (type == typeof(BurningBlood) || type == typeof(BlackBlood)
                    || type == typeof(MeatOnTheBone))
                    continue;
                throw new PredictionUnsupportedException(
                    $"Post-combat reward projection does not support {type.FullName}.{method.Name}.");
            }
        }
    }
}
