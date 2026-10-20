using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal static class TriggeredPowerSupport
{
    public static void CompensateHistorySince(
        CombatPredictionSimulator simulator,
        SimulatedCombatState combat,
        int historyEntryStart)
    {
        CombatPredictionHistory history = simulator.History;
        int nextEntry = historyEntryStart;
        while (true)
        {
            int batchEnd = history.Entries.Count;
            CombatPredictionHistory.HistoryEntryRange batch = history.EntriesBetween(nextEntry, batchEnd);
            foreach (CombatPredictionHistoryEntry entry in batch)
                combat.RecordRelicDamageEntry(entry);
            // Damage-triggered effects execute at their native hook boundary.
            nextEntry = batchEnd;
            PowerLifecycleSupport.ResolvePowerAmountChanges(simulator, combat);
            if (simulator.HasPendingChoice)
                return;
            if (nextEntry >= history.Entries.Count)
                return;
        }
    }


}
