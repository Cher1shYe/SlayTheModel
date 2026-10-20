namespace SlayTheModel.Sts2.Protocol;

public sealed record RngSnapshot(
    int Counter,
    ulong State0,
    ulong State1,
    ulong State2,
    ulong State3);

public sealed record NamedRngSnapshot(
    string Name,
    RngSnapshot State);

public sealed record RunRngSnapshot(
    string Seed,
    IReadOnlyList<NamedRngSnapshot> Streams);

public sealed record PlayerRngSnapshot(
    ulong Seed,
    IReadOnlyList<NamedRngSnapshot> Streams);
