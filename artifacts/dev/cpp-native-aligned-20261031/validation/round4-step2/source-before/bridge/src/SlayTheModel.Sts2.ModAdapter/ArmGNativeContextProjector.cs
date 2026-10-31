using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Acts;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Timeline.Epochs;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

// Isolated bridge patch; no game actions or inferred selector source. A missing
// context makes the Python bridge unsupported while other policies still work.
internal static class ArmGNativeContextProjector
{
    internal static OutsideArmGNativeContext? TryCapture(RunState state)
    {
        try
        {
            if (state.Players.Count != 1 || state.Acts.Count != 3) return null;
            var player = state.Players[0];
            var unlocks = state.UnlockState;
            return new OutsideArmGNativeContext(
                1,
                state.Acts.Select(act => act.Id.ToString()).ToArray(),
                player.Relics.OfType<GoldenCompass>().SingleOrDefault()?.GoldenPathAct ?? -1,
                state.MapPointHistory.SelectMany(act => act).Count(point => point.MapPointType == MapPointType.Unknown),
                RunManager.Instance.ShouldApplyTutorialModifications(),
                unlocks.NumberOfRuns,
                unlocks.IsEpochRevealed<NeowEpoch>(),
                unlocks.IsEpochRevealed<OrobasEpoch>(),
                unlocks.IsEpochRevealed<DarvEpoch>(),
                unlocks.IsEpochRevealed<UnderdocksEpoch>(),
                SaveManager.Instance.Progress.DiscoveredActs.Contains(ModelDb.Act<Underdocks>().Id),
                unlocks.HasSeenEncounter(ModelDb.Encounter<AeonglassBoss>()),
                ModelDb.AllEncounters.Where(unlocks.HasSeenEncounter).Select(encounter => encounter.Id.ToString()).ToArray(),
                state.Act.BossEncounter.Id.ToString(),
                state.Act.SecondBossEncounter?.Id.ToString(),
                player.Relics.OfType<PaelsTooth>().Sum(relic => relic.SerializableCards.Count));
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[SlayTheModel ArmG] Native context unavailable: {exception.GetType().Name}: {exception.Message}");
            return null;
        }
    }
}
