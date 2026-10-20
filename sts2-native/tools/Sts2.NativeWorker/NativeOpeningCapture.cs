using CombatSolver.Api;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;

// Worker-only hook: freeze the stable first-turn root before any draw/choice hooks.
[HarmonyPatch(typeof(CombatManager), "SetupPlayerTurn")]
internal static class NativeOpeningCapture
{
    internal static Action<Func<NativeMctsSimulationSession>>? Capture;

    private static void Prefix(CombatManager __instance, Player __1)
    {
        if (__1.PlayerCombatState?.TurnNumber == 1 && Capture is { } capture)
            capture(NativeMctsSimulationApi.FreezeTurnSetupRoot(__instance.DebugOnlyGetState()!));
    }
}
