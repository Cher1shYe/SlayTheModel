using System.Text.Json;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Collector;

/// <summary>
/// A game-independent producer for one sequential headless run. It projects
/// typed policy decisions into the same EpisodeSession and JSONL journal used
/// by the live collector. The simulator remains responsible for truthful
/// observations, transitions, reward metrics, and terminal outcome.
/// </summary>
public sealed class HeadlessEpisodeRecorder : IDisposable
{
    private readonly EpisodeSession _session;
    private HeadlessStepHandle? _active;
    private bool _finished;
    private bool _disposed;

    public HeadlessEpisodeRecorder(CollectorStore store, EpisodeStartInput start)
    {
        ArgumentNullException.ThrowIfNull(store);
        ArgumentNullException.ThrowIfNull(start);
        if (start.Source != CollectorSource.Headless)
        {
            throw new ArgumentException(
                "A headless recorder requires CollectorSource.Headless.", nameof(start));
        }

        DatasetManifestWriter.Ensure(store.RootDirectory);
        _session = store.StartEpisode(start);
    }

    public Guid EpisodeId => _session.EpisodeId;

    public EpisodeSnapshot Snapshot => _session.Snapshot;

    public HeadlessStepHandle BeginCombat(
        CombatDecisionPoint decision,
        InformationRegime informationRegime,
        int selectedActionIndex,
        PolicyTrace policy,
        JsonElement? context = null,
        JsonElement? selectedAction = null)
    {
        ArgumentNullException.ThrowIfNull(decision);
        return Begin(
            DecisionInput.FromCombat(Guid.NewGuid(), decision, informationRegime) with
            {
                Context = context,
            },
            selectedActionIndex,
            policy,
            selectedAction);
    }

    public HeadlessStepHandle BeginOutside(
        OutsideCombatDecisionPoint decision,
        InformationRegime informationRegime,
        int selectedActionIndex,
        PolicyTrace policy,
        JsonElement? context = null,
        JsonElement? selectedAction = null)
    {
        ArgumentNullException.ThrowIfNull(decision);
        return Begin(
            DecisionInput.FromOutside(Guid.NewGuid(), decision, informationRegime) with
            {
                Context = context,
            },
            selectedActionIndex,
            policy,
            selectedAction);
    }

    /// <summary>
    /// Record the outcome of the action selected at Begin. A successful action
    /// still requires RecordReward before another decision or a complete finish.
    /// </summary>
    public void RecordExecution(
        HeadlessStepHandle step,
        CollectorExecutionStatus status,
        string? nextStateFingerprint = null,
        string? detail = null)
    {
        RequireActive(step, awaitingReward: false);
        if (status == CollectorExecutionStatus.Rejected)
        {
            throw new ArgumentException(
                "Rejected actions require a retry on the same decision, which this sequential recorder does not support.",
                nameof(status));
        }

        _session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            step.DecisionId,
            step.AttemptId,
            step.SelectedActionIndex,
            step.SelectedActionKey,
            step.StateFingerprint,
            status,
            nextStateFingerprint,
            detail));

        if (status is CollectorExecutionStatus.Applied
            or CollectorExecutionStatus.ObservedTransition)
        {
            step.AwaitingReward = true;
        }
        else
        {
            _active = null;
        }
    }

    public void RecordReward(
        HeadlessStepHandle step,
        IReadOnlyDictionary<string, double> components)
    {
        RequireActive(step, awaitingReward: true);
        ArgumentNullException.ThrowIfNull(components);
        if (string.Equals(
                _session.RewardVersion,
                WholeRunV2RewardCalculator.Version,
                StringComparison.Ordinal))
        {
            WholeRunV2RewardCalculator.ValidateComponents(components);
        }

        _session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            step.DecisionId,
            _session.RewardVersion,
            components));
        _active = null;
    }

    public void RecordWholeRunV2Reward(
        HeadlessStepHandle step,
        WholeRunV2Metrics before,
        WholeRunV2Metrics after)
    {
        RequireActive(step, awaitingReward: true);
        if (!string.Equals(
                _session.RewardVersion,
                WholeRunV2RewardCalculator.Version,
                StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                "The episode reward version is not whole-run-v2.");
        }

        RecordReward(step, WholeRunV2RewardCalculator.Compute(before, after));
    }

    public void Finish(EpisodeFinishInput finish)
    {
        ArgumentNullException.ThrowIfNull(finish);
        ThrowIfUnavailable();
        if (finish.Completeness == EpisodeCompleteness.Complete && _active is not null)
        {
            throw new InvalidOperationException(
                "A complete headless episode cannot contain an action without execution or reward.");
        }

        _session.Finish(finish);
        _finished = true;
        _active = null;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _session.Dispose();
        _disposed = true;
    }

    private HeadlessStepHandle Begin(
        DecisionInput input,
        int selectedActionIndex,
        PolicyTrace policy,
        JsonElement? selectedAction)
    {
        ThrowIfUnavailable();
        if (_active is not null)
        {
            throw new InvalidOperationException(
                "The previous headless action needs an execution result and, on success, a reward.");
        }

        if (selectedActionIndex < 0 || selectedActionIndex >= input.ActionKeys.Count)
        {
            throw new ArgumentOutOfRangeException(nameof(selectedActionIndex));
        }

        ValidatePolicy(policy, input.ActionKeys.Count);
        EpisodeStateMachine.ValidateSubmittedSelection(
            input.Domain,
            input.Observation,
            input.LegalActions,
            selectedActionIndex,
            selectedAction);
        var receipt = _session.RecordDecision(input);
        var step = new HeadlessStepHandle(
            receipt.DecisionId,
            Guid.NewGuid(),
            receipt.GlobalStep,
            selectedActionIndex,
            receipt.ActionKeys[selectedActionIndex],
            input.StateFingerprint);
        _session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            step.DecisionId,
            step.AttemptId,
            selectedActionIndex,
            step.SelectedActionKey,
            policy,
            selectedAction));
        _active = step;
        return step;
    }

    private static void ValidatePolicy(PolicyTrace policy, int actionCount)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!Enum.IsDefined(policy.Actor)
            || string.IsNullOrWhiteSpace(policy.PolicyId)
            || policy.ModelRevision is not null
            && string.IsNullOrWhiteSpace(policy.ModelRevision)
            || policy.Logits is { } logits
            && (logits.Count != actionCount
                || logits.Any(value => !double.IsFinite(value)))
            || policy.MctsVisitCounts is { } visits
            && (visits.Count != actionCount
                || visits.Any(value => value < 0)
                || visits.All(value => value == 0)))
        {
            throw new ArgumentException(
                "Headless policy identity, logits, or visits are invalid.", nameof(policy));
        }
    }

    private void RequireActive(HeadlessStepHandle step, bool awaitingReward)
    {
        ArgumentNullException.ThrowIfNull(step);
        ThrowIfUnavailable();
        if (!ReferenceEquals(_active, step) || step.AwaitingReward != awaitingReward)
        {
            throw new InvalidOperationException(
                "The headless step is not in the requested recording phase.");
        }
    }

    private void ThrowIfUnavailable()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_finished)
        {
            throw new InvalidOperationException("The headless episode has finished.");
        }
    }
}

/// <summary>Identity and action key fixed at the headless decision boundary.</summary>
public sealed class HeadlessStepHandle
{
    internal HeadlessStepHandle(
        Guid decisionId,
        Guid attemptId,
        long globalStep,
        int selectedActionIndex,
        string selectedActionKey,
        string stateFingerprint)
    {
        DecisionId = decisionId;
        AttemptId = attemptId;
        GlobalStep = globalStep;
        SelectedActionIndex = selectedActionIndex;
        SelectedActionKey = selectedActionKey;
        StateFingerprint = stateFingerprint;
    }

    public Guid DecisionId { get; }
    public Guid AttemptId { get; }
    public long GlobalStep { get; }
    public int SelectedActionIndex { get; }
    public string SelectedActionKey { get; }
    public string StateFingerprint { get; }
    internal bool AwaitingReward { get; set; }
}
