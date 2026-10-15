using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.GameActions;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>Optional in-process observation of choices returned by the MCTS selector.</summary>
public static class PolicyChoiceBridge
{
    public static void BeforeAction(GameAction action) => CollectorRuntime.PreparePolicyAction(action);

    public static void Record(CardModel[] options, int minSelect, int maxSelect, CardModel[] selected)
        => CollectorRuntime.RecordPolicyChoice(options, minSelect, maxSelect, selected);
}
