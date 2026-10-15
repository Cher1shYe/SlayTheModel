using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.GameActions;

namespace SlayTheModel.Sts2.ModAdapter;

internal static class PolicyChoiceCapture
{
    internal static void BeforeAction(GameAction action) => Invoke("BeforeAction", [action]);

    internal static void Record(CardModel[] options, int minSelect, int maxSelect, CardModel[] selected)
        => Invoke("Record", [options, minSelect, maxSelect, selected]);

    private static void Invoke(string method, object[] args)
    {
        // The collector is optional and embeds its own protocol assembly.
        // Exchange only native game types; never require a second mod to play.
        var bridge = AppDomain.CurrentDomain.GetAssemblies()
            .FirstOrDefault(assembly => assembly.GetName().Name == "SlayTheModelDataCollector")?
            .GetType("SlayTheModel.Sts2.DataCollector.PolicyChoiceBridge")?
            .GetMethod(method);
        try { bridge?.Invoke(null, args); }
        catch (Exception exception)
        {
            Godot.GD.PushError($"[SlayTheModel] policy choice capture failed: {exception}");
        }
    }
}
