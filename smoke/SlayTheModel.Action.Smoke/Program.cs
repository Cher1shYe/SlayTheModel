using SlayTheModel.Sts2.ModAdapter;

// A choice pauses the executor (idle), but not the card's completion task.
var card = new TaskCompletionSource();
var resumedQueue = new TaskCompletionSource();
var idleRequested = false;
var waiting = NativeActionCompletion.WaitAsync(card.Task, () =>
{
    idleRequested = true;
    return resumedQueue.Task;
});
if (waiting.IsCompleted || idleRequested)
    throw new Exception("A pending choice must not release the live controller.");
card.SetResult();
if (waiting.IsCompleted)
    throw new Exception("Wait for queue cleanup after the choice completes.");
resumedQueue.SetResult();
await waiting;
if (!idleRequested) throw new Exception("Queue cleanup was skipped.");

var cancelled = new TaskCompletionSource();
var afterCancellation = false;
var cancellation = NativeActionCompletion.WaitAsync(cancelled.Task, () =>
{
    afterCancellation = true;
    return Task.CompletedTask;
});
cancelled.SetCanceled();
try
{
    await cancellation;
    throw new Exception("Cancellation must propagate.");
}
catch (OperationCanceledException) { }
if (afterCancellation) throw new Exception("Cancelled actions must not wait for idle.");
await NativeActionCompletion.WaitAsync(Task.CompletedTask, () => Task.CompletedTask);
Console.WriteLine("action completion: paused choice, queue cleanup, cancellation, synchronous completion passed");
