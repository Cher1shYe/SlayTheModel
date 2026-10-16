using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Collector;

public enum CollectorSource
{
    Live,
    Headless,
}

public enum CollectorEventType
{
    EpisodeStarted,
    Decision,
    ActionSubmitted,
    ExecutionResult,
    Reward,
    SaveLoad,
    CoverageGap,
    Diagnostic,
    ManualCombatInput,
    ManualCombatInputOutcome,
    EpisodeFinished,
}

public enum CollectorDecisionDomain
{
    Combat,
    OutsideCombat,
}

public enum InformationRegime
{
    Unknown,
    NoSl,
    Sl,
}

public enum ActionActor
{
    Human,
    Policy,
    Script,
}

public enum CollectorExecutionStatus
{
    ObservedTransition,
    Applied,
    Cancelled,
    Rejected,
    Failed,
    TimedOut,
    Stale,
}

public enum EpisodeCompleteness
{
    Complete,
    Incomplete,
}

public enum SaveLoadKind
{
    /// <summary>Normal process continuation from the latest committed save.</summary>
    Resume,
    /// <summary>An explicit rewind/SL to an earlier point in the run.</summary>
    Rewind,
    /// <summary>A reload was observed, but its temporal relationship is unknown.</summary>
    Unknown,
}

public enum EpisodePhase
{
    New,
    Ready,
    AwaitingAction,
    AwaitingExecution,
    AwaitingReward,
    Finished,
}

public sealed record EpisodeStartInput(
    Guid EpisodeId,
    Guid EventId,
    CollectorSource Source,
    BuildIdentity Build,
    string CollectorRevision,
    string RewardVersion,
    bool NoSlExpected,
    IReadOnlyDictionary<string, string>? Metadata = null);

public sealed record DecisionInput(
    Guid EventId,
    CollectorDecisionDomain Domain,
    InformationRegime InformationRegime,
    long SourceDecisionIndex,
    string StateFingerprint,
    JsonElement Observation,
    JsonElement LegalActions,
    IReadOnlyList<string> ActionKeys,
    BuildIdentity? Build = null,
    JsonElement? Context = null)
{
    public static DecisionInput FromCombat(
        Guid eventId,
        CombatDecisionPoint decision,
        InformationRegime informationRegime = InformationRegime.Unknown)
    {
        ArgumentNullException.ThrowIfNull(decision);
        decision.ValidatePotionActionReferences();
        var actionKeys = decision.LegalActions
            .Select(ComputeCombatActionKey)
            .ToArray();
        return new DecisionInput(
            eventId,
            CollectorDecisionDomain.Combat,
            informationRegime,
            decision.DecisionIndex,
            decision.StateFingerprint,
            JsonSerializer.SerializeToElement(decision.Observation, CollectorJson.Options),
            JsonSerializer.SerializeToElement(decision.LegalActions, CollectorJson.Options),
            actionKeys);
    }

    public static DecisionInput FromOutside(
        Guid eventId,
        OutsideCombatDecisionPoint decision,
        InformationRegime informationRegime = InformationRegime.Unknown)
    {
        ArgumentNullException.ThrowIfNull(decision);
        decision.Validate();
        return new DecisionInput(
            eventId,
            CollectorDecisionDomain.OutsideCombat,
            informationRegime,
            decision.DecisionIndex,
            decision.StateFingerprint,
            JsonSerializer.SerializeToElement(decision.Observation, CollectorJson.Options),
            JsonSerializer.SerializeToElement(decision.LegalActions, CollectorJson.Options),
            decision.LegalActions.Select(action => action.ActionId).ToArray(),
            decision.Build);
    }

    internal static string ComputeCombatActionKey(CombatActionDescriptor action)
    {
        var json = JsonSerializer.Serialize(action, CollectorJson.Options);
        return "combat:" + Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
    }
}

public sealed record PolicyTrace(
    ActionActor Actor,
    string? PolicyId = null,
    string? ModelRevision = null,
    IReadOnlyList<double>? Logits = null,
    IReadOnlyList<long>? MctsVisitCounts = null,
    string? TeacherInformation = null);

public sealed record ActionSubmissionInput(
    Guid EventId,
    Guid DecisionId,
    Guid AttemptId,
    int SelectedActionIndex,
    string SelectedActionKey,
    PolicyTrace Policy,
    JsonElement? SelectedAction = null);

public sealed record ExecutionInput(
    Guid EventId,
    Guid DecisionId,
    Guid AttemptId,
    int SelectedActionIndex,
    string SelectedActionKey,
    string ExpectedStateFingerprint,
    CollectorExecutionStatus Status,
    string? NextStateFingerprint = null,
    string? Detail = null);

public sealed record RewardInput(
    Guid EventId,
    Guid DecisionId,
    string RewardVersion,
    IReadOnlyDictionary<string, double> Components);

public sealed record SaveLoadInput(
    Guid EventId,
    SaveLoadKind Kind,
    string Reason,
    string? BeforeStateFingerprint = null,
    string? RestoredStateFingerprint = null,
    string? CheckpointSha256 = null);

/// <summary>
/// Records a known hole in semantic coverage. Unlike a diagnostic, this is a
/// training-integrity event: it invalidates any pending decision and prevents
/// the episode from being advertised as a complete value target.
/// </summary>
public sealed record CoverageGapInput(
    Guid EventId,
    string Reason,
    bool InvalidatePendingDecision = true,
    Guid? RelatedDecisionId = null,
    Guid? RelatedAttemptId = null,
    Guid? TargetDecisionId = null);

/// <summary>
/// Lossless side-channel data which is useful for auditing a native run but is
/// not yet part of a policy training label. Diagnostics share the episode hash
/// chain without advancing or resolving the current decision.
/// </summary>
public sealed record DiagnosticInput(
    Guid EventId,
    string Code,
    JsonElement Data);

/// <summary>
/// An exact manual combat input, whether or not it also has a structured
/// decision. Data carries click-time evidence; this side event alone never
/// implies a clean policy transition or a behavior-cloning label.
/// </summary>
public sealed record ManualCombatInputInput(
    Guid EventId,
    Guid IntentId,
    long NativeActionId,
    string ActionKind,
    JsonElement Data,
    Guid? RelatedDecisionId = null,
    Guid? RelatedAttemptId = null);

public sealed record ManualCombatInputOutcomeInput(
    Guid EventId,
    Guid IntentId,
    long NativeActionId,
    CollectorExecutionStatus Status,
    string? Detail = null,
    JsonElement? Data = null);

public sealed record EpisodeFinishInput(
    Guid EventId,
    string Outcome,
    string TerminationReason,
    EpisodeCompleteness Completeness,
    JsonElement? Summary = null);

public sealed record EpisodeStartedPayload(
    BuildIdentity Build,
    string CollectorRevision,
    string RewardVersion,
    bool NoSlExpected,
    IReadOnlyDictionary<string, string> Metadata);

public sealed record DecisionPayload(
    Guid DecisionId,
    CollectorDecisionDomain Domain,
    InformationRegime InformationRegime,
    long SourceDecisionIndex,
    string StateFingerprint,
    JsonElement Observation,
    JsonElement LegalActions,
    IReadOnlyList<string> ActionKeys,
    BuildIdentity? Build,
    JsonElement? Context,
    bool QueuedCombatInput = false,
    bool QueuedOutsideInput = false);

public sealed record ActionSubmittedPayload(
    Guid DecisionId,
    Guid AttemptId,
    int SelectedActionIndex,
    string SelectedActionKey,
    PolicyTrace Policy,
    [property: System.Text.Json.Serialization.JsonIgnore(
        Condition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull)]
    JsonElement? SelectedAction = null);

public sealed record ExecutionResultPayload(
    Guid DecisionId,
    Guid AttemptId,
    int SelectedActionIndex,
    string SelectedActionKey,
    string ExpectedStateFingerprint,
    CollectorExecutionStatus Status,
    string? NextStateFingerprint,
    string? Detail);

public sealed record RewardPayload(
    Guid DecisionId,
    string RewardVersion,
    IReadOnlyDictionary<string, double> Components);

public sealed record SaveLoadPayload(
    SaveLoadKind Kind,
    string Reason,
    int FromTimelineGeneration,
    int ToTimelineGeneration,
    string? BeforeStateFingerprint,
    string? RestoredStateFingerprint,
    string? CheckpointSha256,
    Guid? InvalidatedDecisionId,
    long? InvalidatedGlobalStep,
    EpisodePhase InvalidatedPhase,
    bool CreatesDataGap,
    IReadOnlyList<PendingDecisionReference>? InvalidatedDecisions = null);

public sealed record CoverageGapPayload(
    string Reason,
    Guid? InvalidatedDecisionId,
    long? InvalidatedGlobalStep,
    EpisodePhase InvalidatedPhase,
    bool InvalidatesPendingDecision,
    Guid? RelatedDecisionId = null,
    Guid? RelatedAttemptId = null,
    IReadOnlyList<PendingDecisionReference>? InvalidatedDecisions = null,
    Guid? TargetDecisionId = null);

/// <summary>Identity and stage of an in-flight decision at an invalidation boundary.</summary>
public sealed record PendingDecisionReference(
    Guid DecisionId,
    long GlobalStep,
    EpisodePhase Phase);

public sealed record DiagnosticPayload(
    string Code,
    JsonElement Data);

public sealed record ManualCombatInputPayload(
    Guid IntentId,
    long NativeActionId,
    string ActionKind,
    JsonElement Data,
    Guid? RelatedDecisionId,
    Guid? RelatedAttemptId);

public sealed record ManualCombatInputOutcomePayload(
    Guid IntentId,
    long NativeActionId,
    CollectorExecutionStatus Status,
    string? Detail,
    JsonElement? Data);

public sealed record EpisodeFinishedPayload(
    string Outcome,
    string TerminationReason,
    EpisodeCompleteness Completeness,
    bool ContainsSaveLoad,
    int SaveLoadCount,
    int UnknownSaveLoadCount,
    int RewindCount,
    int InvalidatedPendingCount,
    int UncertainExecutionCount,
    int CoverageGapCount,
    bool ValueTargetValid,
    Guid? IncompleteDecisionId,
    EpisodePhase PreviousPhase,
    JsonElement? Summary,
    int ManualCombatInputCount = 0,
    int UnresolvedManualCombatInputCount = 0,
    int UnstructuredManualCombatInputCount = 0,
    int UnstructuredUnsafeManualCombatInputCount = 0,
    IReadOnlyList<PendingDecisionReference>? IncompleteDecisions = null);

public sealed record DecisionReceipt(
    Guid DecisionId,
    long GlobalStep,
    IReadOnlyList<string> ActionKeys);

public sealed record EpisodeSnapshot(
    Guid EpisodeId,
    EpisodePhase Phase,
    long NextEventSequence,
    long NextGlobalStep,
    int TimelineGeneration,
    bool ContainsSaveLoad,
    int SaveLoadCount,
    int UnknownSaveLoadCount,
    int RewindCount,
    int InvalidatedPendingCount,
    int UncertainExecutionCount,
    int CoverageGapCount,
    Guid? PendingDecisionId,
    long? PendingGlobalStep,
    bool CanAppend,
    bool IsPublished,
    int ManualCombatInputCount = 0,
    int UnresolvedManualCombatInputCount = 0,
    int UnstructuredManualCombatInputCount = 0,
    int UnstructuredUnsafeManualCombatInputCount = 0,
    IReadOnlyList<PendingDecisionReference>? PendingDecisions = null)
{
    public int PendingDecisionCount => PendingDecisions?.Count ?? (PendingDecisionId is null ? 0 : 1);
}
