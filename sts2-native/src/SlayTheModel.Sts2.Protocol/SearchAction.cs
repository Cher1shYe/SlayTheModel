namespace SlayTheModel.Sts2.Protocol;

public sealed record SearchAction(string Key, CombatActionDescriptor? Combat = null, int[]? Selection = null);
