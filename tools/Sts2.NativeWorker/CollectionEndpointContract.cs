// A pending MCTS edge owns resolved choice branches, not a snapshot of the live
// partially executed action. Its scalar values are not a completed endpoint.
internal static class CollectionEndpointContract
{
    internal static string Validate(bool predictedPending, bool actualPending,
        bool predictedTerminal, bool actualTerminal, int predictedHp, int actualHp,
        bool predictedWon, bool actualWon)
    {
        if (predictedPending != actualPending)
            throw new InvalidDataException("Native/simulation pending-choice mismatch");
        if (actualPending)
        {
            if (predictedTerminal || actualTerminal)
                throw new InvalidDataException("A terminal endpoint cannot retain a pending choice");
            return "selector_boundary";
        }
        if (predictedTerminal != actualTerminal || predictedHp != actualHp
            || (actualTerminal && predictedWon != actualWon))
            throw new InvalidDataException($"Native/simulation endpoint mismatch: predicted terminal={predictedTerminal} hp={predictedHp} won={predictedWon}; actual terminal={actualTerminal} hp={actualHp} won={actualWon}");
        return "complete_continuation";
    }
}
