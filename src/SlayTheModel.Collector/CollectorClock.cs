namespace SlayTheModel.Collector;

public interface ICollectorClock
{
    DateTimeOffset UtcNow { get; }
}

public sealed class SystemCollectorClock : ICollectorClock
{
    public static SystemCollectorClock Instance { get; } = new();

    private SystemCollectorClock()
    {
    }

    public DateTimeOffset UtcNow => DateTimeOffset.UtcNow;
}
