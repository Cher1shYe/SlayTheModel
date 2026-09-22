using System.Threading.Tasks;
using HarmonyLib;
using MegaCrit.Sts2.Core.Models.Monsters;

/// <summary>
/// Headless-only compatibility patches for effects that are purely visual.
/// The worker still runs the normal death pipeline and Hook.BeforeDeath; only
/// the monster-specific presentation task is replaced with a completed task.
/// </summary>
internal static class NativeReplayCompatibilityPatches
{
    private static readonly Harmony Harmony = new("slaythemodel.native-worker.replay");
    private static bool _installed;

    public static void Install()
    {
        if (_installed) return;
        Harmony.PatchAll(typeof(NativeReplayCompatibilityPatches).Assembly);
        _installed = true;
    }

    [HarmonyPatch(typeof(Crusher), nameof(Crusher.BeforeDeath))]
    private static class CrusherBeforeDeathPatch
    {
        private static bool Prefix(ref Task __result)
        {
            __result = Task.CompletedTask;
            return false;
        }
    }

    [HarmonyPatch(typeof(Rocket), nameof(Rocket.BeforeDeath))]
    private static class RocketBeforeDeathPatch
    {
        private static bool Prefix(ref Task __result)
        {
            __result = Task.CompletedTask;
            return false;
        }
    }

    [HarmonyPatch(typeof(SoulNexus), nameof(SoulNexus.AfterDeath))]
    private static class SoulNexusAfterDeathPatch
    {
        // SoulNexus.AfterDeath only drives the room VFX in the game build. The
        // removal/cleanup callback remains part of the normal death pipeline.
        private static bool Prefix() => false;
    }
}
