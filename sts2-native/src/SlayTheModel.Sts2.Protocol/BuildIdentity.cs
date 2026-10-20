namespace SlayTheModel.Sts2.Protocol;

public sealed record BuildIdentity(
    string GameVersion,
    string AssemblySha256,
    string AssemblyModuleVersionId);
