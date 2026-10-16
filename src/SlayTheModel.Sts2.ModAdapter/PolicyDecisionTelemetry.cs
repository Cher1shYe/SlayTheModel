using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Optional read-only observers. The adapter has no collector dependency;
/// observer failures never change the action or selection returned to STS2.
/// </summary>
public static class PolicyDecisionTelemetry
{
    public static event Action<GameAction, string>? ActionSubmitting;
    public static event Action<object, CardModel[], int, int>? CardChoiceRequested;
    public static event Action<object, object>? CardChoiceManualFallback;
    public static event Action<object, CardModel[]?, Exception?>? CardChoiceCompleted;

    public static void NotifyActionSubmitting(GameAction action, string policyJson) =>
        Notify(ActionSubmitting, observer => observer(action, policyJson));

    internal static void NotifyCardChoiceRequested(
        object request, CardModel[] cards, int minSelect, int maxSelect) =>
        Notify(CardChoiceRequested, observer => observer(request, cards.ToArray(), minSelect, maxSelect));

    internal static void NotifyCardChoiceManualFallback(object request, object selector) =>
        Notify(CardChoiceManualFallback, observer => observer(request, selector));

    internal static void NotifyCardChoiceCompleted(
        object request, CardModel[]? cards, Exception? exception = null) =>
        Notify(CardChoiceCompleted, observer => observer(request, cards?.ToArray(), exception));

    private static void Notify<T>(T? observers, Action<T> invoke) where T : Delegate
    {
        if (observers is null) return;
        foreach (var observer in observers.GetInvocationList().Cast<T>())
        {
            try { invoke(observer); }
            catch (Exception exception) when (exception is not OutOfMemoryException)
            {
                Console.Error.WriteLine($"[SlayTheModel] decision observer failed: {exception}");
            }
        }
    }
}
