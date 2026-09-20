namespace SlayTheModel.Sts2.Protocol;

public sealed record CombatStepRequest(
    Guid RequestId,
    string ExpectedStateFingerprint,
    CombatActionDescriptor Action)
{
    public void Validate()
    {
        if (RequestId == Guid.Empty)
        {
            throw new InvalidDataException("A combat step request requires a non-empty request ID.");
        }

        ProtocolJson.ValidateFingerprint(ExpectedStateFingerprint);

        Action.Validate();
    }
}

public sealed record CombatStepResult(
    Guid RequestId,
    CombatStepStatus Status,
    string BeforeStateFingerprint,
    CombatDecisionPoint? NextDecision = null,
    CombatTerminalResult? Terminal = null,
    string? Error = null)
{
    public void Validate()
    {
        if (RequestId == Guid.Empty)
        {
            throw new InvalidDataException("A combat step result requires a non-empty request ID.");
        }

        switch (Status)
        {
            case CombatStepStatus.Applied when (NextDecision is null) == (Terminal is null):
                throw new InvalidDataException(
                    "An applied step must contain exactly one next decision or terminal result.");
            case CombatStepStatus.Rejected when string.IsNullOrWhiteSpace(Error):
            case CombatStepStatus.Failed when string.IsNullOrWhiteSpace(Error):
                throw new InvalidDataException("A rejected or failed step requires an error message.");
        }

        NextDecision?.Validate();
        Terminal?.Validate();
    }
}

public enum CombatStepStatus
{
    Applied,
    Rejected,
    Failed,
}

public sealed record CombatTerminalResult(
    CombatOutcome Outcome,
    CombatSnapshot FinalState)
{
    public void Validate()
    {
        if (Outcome == CombatOutcome.InProgress)
        {
            throw new InvalidDataException("A terminal result cannot have the InProgress outcome.");
        }

        FinalState.Validate();
    }
}

public enum CombatOutcome
{
    InProgress,
    Victory,
    Defeat,
    Escaped,
    Aborted,
}

public static class CombatStepGuard
{
    public static void RequireExpectedState(
        CombatStepRequest request,
        CombatSnapshot currentState)
    {
        request.Validate();
        var actual = ProtocolJson.ComputeStateFingerprint(currentState);
        if (!string.Equals(
                request.ExpectedStateFingerprint,
                actual,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new StaleCombatStateException(request.ExpectedStateFingerprint, actual);
        }
    }
}

public sealed class StaleCombatStateException : InvalidOperationException
{
    public StaleCombatStateException(string expected, string actual)
        : base($"Combat state changed before the action was applied. Expected {expected}, found {actual}.")
    {
        Expected = expected;
        Actual = actual;
    }

    public string Expected { get; }

    public string Actual { get; }
}
