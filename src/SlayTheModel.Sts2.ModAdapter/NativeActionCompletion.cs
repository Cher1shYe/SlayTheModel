namespace SlayTheModel.Sts2.ModAdapter;

internal static class NativeActionCompletion
{
    public static async Task WaitAsync(Task completion, Func<Task> waitForIdle)
    {
        await completion;
        await waitForIdle();
    }
}
