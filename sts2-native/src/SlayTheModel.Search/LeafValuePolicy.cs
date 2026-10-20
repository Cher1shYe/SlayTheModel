namespace SlayTheModel.Search;

public sealed record LeafValuePolicy
{
    public string Mode { get; }
    public double Mix { get; }
    public LeafValuePolicy(string mode, double mix = .5)
    {
        if (mode is not ("heuristic" or "learned" or "mixed") || !double.IsFinite(mix) || mix<0 || mix>1)
            throw new ArgumentException("Expected heuristic/learned/mixed and finite mix in [0,1]");
        Mode=mode; Mix=mix;
    }
    public double Combine(double heuristic, double learned)
    {
        if (!double.IsFinite(heuristic) || heuristic < -1 || heuristic > 1
            || !double.IsFinite(learned) || learned < -1 || learned > 1)
            throw new InvalidDataException("Leaf values must be finite in [-1,1]");
        return Mode switch { "heuristic" => heuristic, "learned" => learned, _ => (1-Mix)*heuristic+Mix*learned };
    }
}
