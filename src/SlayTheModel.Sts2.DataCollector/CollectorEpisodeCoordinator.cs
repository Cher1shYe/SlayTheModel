using System.Reflection;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Platform;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed record RunStartEvidence(
    RunState State,
    bool LoadedFromSave,
    long? StartTime,
    int NativeReloadCount,
    string? NativeSaveFingerprint,
    bool NewRunObserved);

internal sealed record NativeSaveCheckpoint(
    Guid EpisodeId,
    long DurableEventSequence,
    string NativeSaveFingerprint);

internal sealed record CollectorActionDraft(
    DecisionInput Decision,
    DecisionReceipt Receipt,
    int SelectedActionIndex,
    string SelectedActionKey,
    Guid AttemptId,
    DateTimeOffset ObservedAtUtc,
    RunMetrics BeforeMetrics,
    string InputKind);

/// <summary>
/// Immutable observation captured before a native selector opens. The selected
/// ordinal is attached only after the game's task reports the human result.
/// </summary>
internal sealed record PreparedOutsideDecision(
    DecisionInput Decision,
    DecisionReceipt Receipt,
    DateTimeOffset ObservedAtUtc,
    RunMetrics BeforeMetrics,
    string InputKind);

internal sealed record PreparedCombatChoice(
    DecisionInput Decision,
    DecisionReceipt Receipt,
    DateTimeOffset ObservedAtUtc,
    RunMetrics BeforeMetrics,
    string InputKind);

internal sealed record StagedExecution(
    CollectorActionDraft Draft,
    CollectorExecutionStatus Status,
    string? Detail,
    Guid EpisodeId,
    int TimelineGeneration);

/// <summary>
/// Owns the one shared timeline for combat and outside-combat decisions. A
/// deterministic, non-feature run key maps a native save back to its partial
/// episode. Run provenance stays in episode_started metadata; the policy
/// observation never receives seed, identity, or save bytes.
/// </summary>
internal sealed class CollectorEpisodeCoordinator : IDisposable
{
    private const string RewardVersion = WholeRunV2RewardCalculator.Version;
    private readonly object _gate = new();
    private readonly CollectorConfiguration _configuration;
    private readonly CollectorStore _store;
    private readonly string _activeRunsDirectory;
    private EpisodeSession? _session;
    private StagedExecution? _stagedExecution;
    private readonly HashSet<Guid> _contaminatedTransitionAttempts = [];
    private string? _runKey;
    private string? _sidecarPath;
    private ActiveRunSidecar? _activeSidecar;
    private long _sourceDecisionIndex;
    private bool _observedFromRunStart;
    private bool _hasUnknownTimelineBoundary;
    private bool _disposed;

    internal CollectorEpisodeCoordinator(CollectorConfiguration configuration)
    {
        _configuration = configuration;
        _store = new CollectorStore(configuration.DatasetRoot);
        _activeRunsDirectory = Path.Combine(configuration.DatasetRoot, "active-runs");
        Directory.CreateDirectory(_activeRunsDirectory);
        DatasetManifestWriter.Ensure(configuration.DatasetRoot);
    }

    internal bool HasActiveEpisode
    {
        get
        {
            lock (_gate)
            {
                return _session is not null;
            }
        }
    }

    internal EpisodeSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return (_session
                    ?? throw new InvalidOperationException("No collector episode is active.")).Snapshot;
            }
        }
    }

    internal CollectorActionDraft? StagedActionAwaitingBoundary
    {
        get
        {
            lock (_gate)
            {
                return _stagedExecution is { } staged
                       && _session is not null
                       && staged.EpisodeId == _session.EpisodeId
                       && staged.TimelineGeneration == _session.Snapshot.TimelineGeneration
                    ? staged.Draft
                    : null;
            }
        }
    }

    internal long NextSourceDecisionIndex()
    {
        lock (_gate)
        {
            return _sourceDecisionIndex++;
        }
    }

    internal void BeginRun(RunStartEvidence evidence)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        if (evidence.LoadedFromSave && evidence.NewRunObserved)
        {
            throw new ArgumentException(
                "A loaded save cannot also be an observed native new run.",
                nameof(evidence));
        }
        lock (_gate)
        {
            ThrowIfDisposed();
            _stagedExecution = null;
            _contaminatedTransitionAttempts.Clear();
            var state = evidence.State;
            if (state.Players.Count != 1)
            {
                if (_session is not null)
                {
                    FinalizeInterruptedSession(
                        "singleplayer_episode_replaced_by_multiplayer_run",
                        new { player_count = state.Players.Count });
                }
                Console.WriteLine(
                    "[SlayTheModel/Collector] multiplayer run ignored; v1 records single-player only");
                return;
            }

            var incomingRunKey = ComputeRunKey(state, evidence.StartTime);
            if (_session is not null
                && evidence.LoadedFromSave
                && string.Equals(_runKey, incomingRunKey, StringComparison.Ordinal))
            {
                var snapshot = _session.Snapshot;
                var checkpointMatches = evidence.NativeSaveFingerprint is not null
                                        && _activeSidecar is
                                        {
                                            ResumeCheckpointValid: true,
                                        } checkpointSidecar
                                        && checkpointSidecar.DurableEventSequence
                                        == snapshot.NextEventSequence
                                        && string.Equals(
                                            checkpointSidecar.ResumeSaveFingerprint,
                                            evidence.NativeSaveFingerprint,
                                            StringComparison.OrdinalIgnoreCase);
                var saveLoadKind = SaveLoadKindForObservedCheckpoint(checkpointMatches);
                _hasUnknownTimelineBoundary |= saveLoadKind == SaveLoadKind.Unknown;
                _session.MarkSaveLoad(new SaveLoadInput(
                    Guid.NewGuid(),
                    saveLoadKind,
                    SaveLoadReason(saveLoadKind, "in_process"),
                    RestoredStateFingerprint: evidence.NativeSaveFingerprint
                                              ?? FingerprintRunContext(state)));
                _sourceDecisionIndex = _session.Snapshot.NextGlobalStep;
                if (_activeSidecar is not null)
                {
                    PersistSidecar(_activeSidecar with
                    {
                        NativeReloadCount = evidence.NativeReloadCount,
                        ResumeCount = _activeSidecar.ResumeCount + 1,
                        HasUnknownTimelineBoundary = _hasUnknownTimelineBoundary,
                        ResumeCheckpointValid = false,
                        ResumeSaveFingerprint = null,
                        DurableEventSequence = _session.Snapshot.NextEventSequence,
                        UpdatedAtUtc = DateTimeOffset.UtcNow,
                    });
                }

                Console.WriteLine(
                    $"[SlayTheModel/Collector] continued in-process episode="
                    + $"{_session.EpisodeId:N} reloads={evidence.NativeReloadCount}");
                return;
            }

            if (_session is not null)
            {
                FinalizeInterruptedSession(
                    "native_run_replaced_without_resume_checkpoint",
                    new { evidence.LoadedFromSave });
            }

            _runKey = incomingRunKey;
            _sidecarPath = Path.Combine(_activeRunsDirectory, _runKey + ".json");
            _sourceDecisionIndex = 0;
            _observedFromRunStart = false;
            _hasUnknownTimelineBoundary = false;
            ActiveRunSidecar? sidecar = ReadSidecar(_sidecarPath);
            if (sidecar is not null
                && (sidecar.SchemaVersion != ActiveRunSidecar.CurrentSchemaVersion
                    || !string.Equals(sidecar.RunKey, _runKey, StringComparison.Ordinal)
                    || sidecar.EpisodeId == Guid.Empty))
            {
                Console.Error.WriteLine(
                    "[SlayTheModel/Collector] incompatible active-run sidecar ignored");
                if (sidecar.EpisodeId != Guid.Empty
                    && File.Exists(_store.GetOpenEpisodePath(sidecar.EpisodeId)))
                {
                    if (TryResumePartial(sidecar.EpisodeId, "incompatible_sidecar"))
                    {
                        if (_session!.CanAppend)
                        {
                            FinalizeInterruptedSession(
                                "incompatible_active_run_sidecar",
                                new { sidecar.SchemaVersion });
                        }
                        else
                        {
                            _session.Dispose();
                            _session = null;
                        }
                    }
                }

                File.Delete(_sidecarPath);
                sidecar = null;
            }

            if (!evidence.LoadedFromSave
                && sidecar is not null
                && File.Exists(_store.GetOpenEpisodePath(sidecar.EpisodeId)))
            {
                if (TryResumePartial(sidecar.EpisodeId, "stale_new_run"))
                {
                    if (_session!.CanAppend)
                    {
                        FinalizeInterruptedSession(
                            "stale_partial_replaced_by_new_run",
                            new { incoming_run_key = incomingRunKey });
                    }
                    else
                    {
                        _session.Dispose();
                        _session = null;
                    }
                }

                sidecar = null;
            }

            if (evidence.LoadedFromSave
                && sidecar is not null
                && File.Exists(_store.GetOpenEpisodePath(sidecar.EpisodeId)))
            {
                if (!TryResumePartial(sidecar.EpisodeId, "loaded_run_resume"))
                {
                    sidecar = null;
                }
                else if (!_session!.CanAppend)
                {
                    // The finish record was durable but publication was
                    // interrupted. ResumeEpisode has now published it; this
                    // loaded native save must begin a distinct partial episode.
                    _session.Dispose();
                    _session = null;
                    File.Delete(_sidecarPath);
                    sidecar = null;
                }
            }

            if (_session is not null && sidecar is not null)
            {
                var snapshot = _session.Snapshot;
                var restoredFingerprint = evidence.NativeSaveFingerprint;
                var checkpointMatches = sidecar.ResumeCheckpointValid
                                        && restoredFingerprint is not null
                                        && sidecar.DurableEventSequence
                                        == snapshot.NextEventSequence
                                        && string.Equals(
                                            sidecar.ResumeSaveFingerprint,
                                            restoredFingerprint,
                                            StringComparison.OrdinalIgnoreCase);
                if (!checkpointMatches)
                {
                    FinalizeInterruptedSession(
                        "resume_checkpoint_mismatch",
                        new
                        {
                            sidecar.ResumeCheckpointValid,
                            sidecar.DurableEventSequence,
                            durable_event_sequence = snapshot.NextEventSequence,
                            state_fingerprint_matches = string.Equals(
                                sidecar.ResumeSaveFingerprint,
                                restoredFingerprint,
                                StringComparison.OrdinalIgnoreCase),
                        });
                    sidecar = null;
                }
            }

            if (_session is not null && sidecar is not null)
            {
                _observedFromRunStart = sidecar.ObservedFromRunStart;
                // SourceDecisionIndex is a diagnostic ordering key. Continue
                // it from the durable decision count instead of restarting at
                // zero after a process resume.
                _sourceDecisionIndex = _session.Snapshot.NextGlobalStep;
                var saveLoadKind = SaveLoadKindForObservedCheckpoint(
                    checkpointMatches: true);
                _hasUnknownTimelineBoundary = sidecar.HasUnknownTimelineBoundary
                                              || saveLoadKind == SaveLoadKind.Unknown;
                _session.MarkSaveLoad(new SaveLoadInput(
                    Guid.NewGuid(),
                    saveLoadKind,
                    SaveLoadReason(saveLoadKind, "process_resume"),
                    RestoredStateFingerprint: evidence.NativeSaveFingerprint
                                              ?? FingerprintRunContext(state)));
                var resumedSidecar = sidecar with
                {
                    NativeReloadCount = evidence.NativeReloadCount,
                    ResumeCount = sidecar.ResumeCount + 1,
                    HasUnknownTimelineBoundary = _hasUnknownTimelineBoundary,
                    ResumeCheckpointValid = false,
                    ResumeSaveFingerprint = null,
                    DurableEventSequence = _session.Snapshot.NextEventSequence,
                    UpdatedAtUtc = DateTimeOffset.UtcNow,
                };
                PersistSidecar(resumedSidecar);
                Console.WriteLine(
                    $"[SlayTheModel/Collector] resumed episode={sidecar.EpisodeId:N} "
                    + $"reloads={evidence.NativeReloadCount}");
                return;
            }

            var episodeId = Guid.NewGuid();
            _observedFromRunStart = evidence.NewRunObserved;
            var initialLoadKind = !evidence.NewRunObserved
                ? evidence.LoadedFromSave
                  && _configuration.InformationMode == CollectorInformationMode.Sl
                    ? SaveLoadKind.Rewind
                    : SaveLoadKind.Unknown
                : (SaveLoadKind?)null;
            _hasUnknownTimelineBoundary = initialLoadKind == SaveLoadKind.Unknown;
            var metadata = new SortedDictionary<string, string>(StringComparer.Ordinal)
            {
                ["actor"] = _configuration.Actor,
                ["ascension"] = state.AscensionLevel.ToString(),
                ["character_id"] = state.Players[0].Character.Id.ToString(),
                ["episode_start_current_hp"] = state.Players[0].Creature.CurrentHp
                    .ToString(CultureInfo.InvariantCulture),
                ["episode_start_max_hp"] = state.Players[0].Creature.MaxHp
                    .ToString(CultureInfo.InvariantCulture),
                ["game_mode"] = state.GameMode.ToString(),
                ["information_mode"] = InformationModeName(_configuration.InformationMode),
                ["native_reload_count_at_start"] = evidence.NativeReloadCount.ToString(),
                ["observed_from_run_start"] = _observedFromRunStart.ToString(),
                ["run_key"] = _runKey,
            };
            if (_observedFromRunStart)
            {
                // A new episode opened from an old save has a segment-start
                // HP anchor, not a trustworthy native run-start HP anchor.
                metadata["run_start_current_hp"] = metadata["episode_start_current_hp"];
                metadata["run_start_max_hp"] = metadata["episode_start_max_hp"];
            }
            var runSeed = state.Rng.StringSeed;
            if (!string.IsNullOrWhiteSpace(runSeed))
            {
                metadata["run_seed"] = runSeed;
                metadata["run_seed_status"] = "available";
            }
            else
            {
                metadata["run_seed_status"] = "unavailable";
            }
            if (evidence.StartTime is { } unixSeconds)
            {
                metadata["run_started_unix_seconds"] =
                    unixSeconds.ToString(CultureInfo.InvariantCulture);
                try
                {
                    metadata["run_started_at_utc"] = DateTimeOffset
                        .FromUnixTimeSeconds(unixSeconds)
                        .ToUniversalTime()
                        .ToString("O", CultureInfo.InvariantCulture);
                    metadata["run_start_time_status"] = "available";
                }
                catch (ArgumentOutOfRangeException)
                {
                    // Keep the exact native value for audit, while the event
                    // envelope still provides a valid collection timestamp.
                    metadata["run_start_time_status"] = "invalid_native_value";
                }
            }
            else
            {
                metadata["run_start_time_status"] = "unavailable";
            }
            AddSteamIdentity(metadata);
            _session = _store.StartEpisode(new EpisodeStartInput(
                episodeId,
                Guid.NewGuid(),
                CollectorSource.Live,
                CombatCaptureService.CurrentBuild,
                CollectorRevision(),
                RewardVersion,
                _configuration.InformationMode == CollectorInformationMode.NoSl,
                metadata));

            var newSidecar = new ActiveRunSidecar(
                ActiveRunSidecar.CurrentSchemaVersion,
                _runKey,
                episodeId,
                evidence.StartTime,
                evidence.NativeReloadCount,
                evidence.LoadedFromSave ? 1 : 0,
                _observedFromRunStart,
                HasUnknownTimelineBoundary: _hasUnknownTimelineBoundary,
                ResumeCheckpointValid: false,
                ResumeSaveFingerprint: null,
                DurableEventSequence: _session.Snapshot.NextEventSequence,
                DateTimeOffset.UtcNow);
            PersistSidecar(newSidecar);
            if (initialLoadKind is not null)
            {
                // A saved run without its old sidecar and a run whose native
                // start hook was missed both lack whole-run continuity proof.
                _session.MarkSaveLoad(new SaveLoadInput(
                    Guid.NewGuid(),
                    initialLoadKind.Value,
                    evidence.LoadedFromSave
                        ? "saved_run_loaded_without_prior_collector_segment"
                        : "run_start_provenance_unverified",
                    RestoredStateFingerprint: evidence.NativeSaveFingerprint
                                              ?? FingerprintRunContext(state)));
            }

            Console.WriteLine(
                $"[SlayTheModel/Collector] started episode={episodeId:N} "
                + $"path={_store.GetOpenEpisodePath(episodeId)}");
        }
    }

    internal CollectorActionDraft DraftCombat(
        CapturedCombatDecision captured,
        int selectedActionIndex,
        string inputKind)
    {
        var input = DecisionInput.FromCombat(
            Guid.NewGuid(),
            captured.Decision,
            InformationRegimeForConfiguration());
        input = input with
        {
            Context = BuildContext(
                captured.RunContext,
                captured.ObservedGuardMetadata()),
        };
        lock (_gate)
        {
            var session = _session
                ?? throw new InvalidOperationException("No collector episode is active.");
            var observedAt = DateTimeOffset.UtcNow;
            var metrics = CaptureCurrentMetrics();
            ResolveStagedExecutionCore(metrics);
            var receipt = session.RecordDecision(input);
            return BeginSubmittedActionCore(
                       input,
                       receipt,
                       selectedActionIndex,
                       observedAt,
                       metrics,
                       inputKind)
                   ?? throw new InvalidOperationException(
                       "Combat action did not match its recorded legal set.");
        }
    }

    internal CollectorActionDraft DraftQueuedCombat(
        CapturedCombatDecision captured,
        int selectedActionIndex,
        string inputKind)
    {
        var input = DecisionInput.FromCombat(
            Guid.NewGuid(),
            captured.Decision,
            InformationRegimeForConfiguration()) with
        {
            Context = BuildContext(
                captured.RunContext,
                captured.ObservedGuardMetadata()),
        };
        lock (_gate)
        {
            var session = _session
                ?? throw new InvalidOperationException("No collector episode is active.");
            var observedAt = DateTimeOffset.UtcNow;
            var metrics = CaptureCurrentMetrics();
            // The preceding action may have completed after this click was
            // frozen. Settle it before opening the next policy step, without
            // using the later action's execution prestate as its click state.
            ResolveStagedExecutionCore(metrics);
            var receipt = session.RecordQueuedCombatDecision(input);
            return BeginSubmittedActionCore(
                       input,
                       receipt,
                       selectedActionIndex,
                       observedAt,
                       metrics,
                       inputKind)
                   ?? throw new InvalidOperationException(
                       "Queued combat input did not match its click-time legal set.");
        }
    }

    internal CollectorActionDraft AtCombatExecutionStart(CollectorActionDraft draft)
    {
        lock (_gate)
        {
            return draft with { BeforeMetrics = CaptureCurrentMetrics() };
        }
    }

    internal CollectorActionDraft? DraftOutside(
        OutsideCombatDecisionPoint decision,
        int selectedActionIndex,
        string inputKind)
        => ResolveOutside(
            PrepareOutside(decision, inputKind),
            selectedActionIndex);

    internal PreparedCombatChoice PrepareCombatChoice(
        CapturedCombatDecision captured,
        string inputKind)
    {
        var input = DecisionInput.FromCombat(
            Guid.NewGuid(),
            captured.Decision,
            InformationRegimeForConfiguration());
        input = input with
        {
            Context = BuildContext(
                captured.RunContext,
                captured.ObservedGuardMetadata()),
        };
        lock (_gate)
        {
            var session = _session
                ?? throw new InvalidOperationException("No collector episode is active.");
            var observedAt = DateTimeOffset.UtcNow;
            var metrics = CaptureCurrentMetrics();
            ResolveStagedExecutionCore(metrics);
            // A queued manual click may already have opened a combat decision
            // while its earlier card is waiting for this native selector.
            // The selector is a separate player decision on the same timeline.
            var receipt = session.Snapshot.PendingDecisionCount == 0
                ? session.RecordDecision(input)
                : session.RecordQueuedCombatDecision(input);
            return new PreparedCombatChoice(
                input,
                receipt,
                observedAt,
                metrics,
                inputKind);
        }
    }

    internal CollectorActionDraft? ResolveCombatChoice(
        PreparedCombatChoice prepared,
        int selectedActionIndex,
        JsonElement? selectedAction = null)
    {
        ArgumentNullException.ThrowIfNull(prepared);
        lock (_gate)
        {
            return BeginSubmittedActionCore(
                prepared.Decision,
                prepared.Receipt,
                selectedActionIndex,
                prepared.ObservedAtUtc,
                prepared.BeforeMetrics,
                prepared.InputKind,
                selectedAction);
        }
    }

    internal PreparedOutsideDecision PrepareOutside(
        OutsideCombatDecisionPoint decision,
        string inputKind,
        JsonElement? metadata = null)
    {
        var input = DecisionInput.FromOutside(
            Guid.NewGuid(),
            decision,
            InformationRegimeForConfiguration());
        var state = RequireRunState();
        input = input with
        {
            Context = BuildContext(
                CollectorRunContextProjector.Capture(state),
                metadata),
        };
        lock (_gate)
        {
            var session = _session
                ?? throw new InvalidOperationException("No collector episode is active.");
            var metrics = CollectorRunContextProjector.CaptureMetrics(state);
            ResolveStagedExecutionCore(metrics);
            return new PreparedOutsideDecision(
                input,
                session.RecordDecision(input),
                DateTimeOffset.UtcNow,
                metrics,
                inputKind);
        }
    }

    internal CollectorActionDraft? ResolveOutside(
        PreparedOutsideDecision prepared,
        int selectedActionIndex,
        JsonElement? selectedAction = null)
    {
        ArgumentNullException.ThrowIfNull(prepared);
        lock (_gate)
        {
            return BeginSubmittedActionCore(
                prepared.Decision,
                prepared.Receipt,
                selectedActionIndex,
                prepared.ObservedAtUtc,
                prepared.BeforeMetrics,
                prepared.InputKind,
                selectedAction);
        }
    }

    internal void Commit(
        CollectorActionDraft draft,
        CollectorExecutionStatus status = CollectorExecutionStatus.Applied,
        string? detail = null)
    {
        ArgumentNullException.ThrowIfNull(draft);
        lock (_gate)
        {
            if (_session is null)
            {
                return;
            }

            var snapshot = _session.Snapshot;
            if (snapshot.PendingDecisions?.Any(pending =>
                    pending.DecisionId == draft.Receipt.DecisionId
                    && pending.Phase == EpisodePhase.AwaitingExecution) != true)
            {
                RecordDiagnosticCore(
                    "stale_native_completion",
                    new
                    {
                        draft.InputKind,
                        expected_decision_id = draft.Receipt.DecisionId,
                        current_decision_id = snapshot.PendingDecisionId,
                        pending_decision_ids = snapshot.PendingDecisions?
                            .Select(pending => pending.DecisionId).ToArray(),
                        draft.ObservedAtUtc,
                    });
                return;
            }

            if (status is CollectorExecutionStatus.Applied
                or CollectorExecutionStatus.ObservedTransition)
            {
                if (_stagedExecution is not null)
                {
                    throw new InvalidOperationException(
                        "A previous successful action is still awaiting a stable boundary.");
                }

                _stagedExecution = new StagedExecution(
                    draft,
                    status,
                    detail,
                    _session.EpisodeId,
                    snapshot.TimelineGeneration);
                return;
            }

            _session.RecordExecution(new ExecutionInput(
                Guid.NewGuid(),
                draft.Receipt.DecisionId,
                draft.AttemptId,
                draft.SelectedActionIndex,
                draft.SelectedActionKey,
                draft.Decision.StateFingerprint,
                status,
                NextStateFingerprint: TryFingerprintCurrentState(draft.Decision),
                Detail: detail));
            _contaminatedTransitionAttempts.Remove(draft.AttemptId);
        }
    }

    internal void MarkTransitionContaminated(CollectorActionDraft draft)
    {
        lock (_gate)
        {
            if (_session is not null)
            {
                _contaminatedTransitionAttempts.Add(draft.AttemptId);
            }
        }
    }

    internal bool RecordManualCombatInput(ManualCombatInputInput input)
    {
        lock (_gate)
        {
            if (_session is null)
            {
                return false;
            }

            _session.RecordManualCombatInput(input);
            return true;
        }
    }

    internal void RecordManualCombatInputOutcome(ManualCombatInputOutcomeInput input)
    {
        lock (_gate)
        {
            _session?.RecordManualCombatInputOutcome(input);
        }
    }

    internal void ResolveAtCurrentBoundary()
    {
        lock (_gate)
        {
            // FinishRun waits for accepted native operations to settle. Read
            // the final run state at this boundary; history has no HP field.
            // When the native run state is gone, leave the anchor unavailable.
            var terminalMetrics = CaptureCurrentMetrics();
            ResolveStagedExecutionCore(terminalMetrics);
        }
    }

    internal bool FailStagedExecution(
        CollectorActionDraft draft,
        string detail)
    {
        lock (_gate)
        {
            var staged = _stagedExecution;
            if (_session is null
                || staged is null
                || staged.EpisodeId != _session.EpisodeId
                || staged.Draft.AttemptId != draft.AttemptId
                || staged.Draft.Receipt.DecisionId != draft.Receipt.DecisionId
                || staged.TimelineGeneration != _session.Snapshot.TimelineGeneration
                || _session.Snapshot.PendingDecisions?.Any(pending =>
                    pending.DecisionId == draft.Receipt.DecisionId
                    && pending.Phase == EpisodePhase.AwaitingExecution) != true)
            {
                return false;
            }

            _stagedExecution = null;
            _session.RecordExecution(new ExecutionInput(
                Guid.NewGuid(),
                draft.Receipt.DecisionId,
                draft.AttemptId,
                draft.SelectedActionIndex,
                draft.SelectedActionKey,
                draft.Decision.StateFingerprint,
                CollectorExecutionStatus.Failed,
                NextStateFingerprint: TryFingerprintCurrentState(draft.Decision),
                Detail: detail));
            _contaminatedTransitionAttempts.Remove(draft.AttemptId);
            return true;
        }
    }

    internal void RecordCoverageGap(
        string reason,
        object data,
        bool invalidatePendingDecision = true,
        Guid? relatedDecisionId = null,
        Guid? relatedAttemptId = null,
        Guid? targetDecisionId = null)
    {
        lock (_gate)
        {
            if (_session is null)
            {
                return;
            }

            RecordDiagnosticCore("coverage_gap_detail", new { reason, data });
            _session.RecordCoverageGap(new CoverageGapInput(
                Guid.NewGuid(),
                reason,
                invalidatePendingDecision,
                relatedDecisionId,
                relatedAttemptId,
                targetDecisionId));
            if (invalidatePendingDecision
                && (targetDecisionId is null
                    || _stagedExecution?.Draft.Receipt.DecisionId == targetDecisionId))
            {
                _stagedExecution = null;
            }
        }
    }

    internal void RecordDiagnostic(string code, object data)
    {
        lock (_gate)
        {
            if (_session is not null)
            {
                RecordDiagnosticCore(code, data);
            }
        }
    }

    internal NativeSaveCheckpoint? PrepareNativeSaveCheckpoint(
        SerializableRun nativeSave,
        bool nativeActionRunning)
    {
        var fingerprint = TryFingerprintNativeSave(nativeSave);
        if (fingerprint is null)
        {
            return null;
        }

        lock (_gate)
        {
            if (_session is null)
            {
                return null;
            }

            if (_stagedExecution is { } staged && !nativeActionRunning)
            {
                var live = CaptureCurrentMetrics();
                var saved = TryCaptureSavedMetrics(nativeSave);
                var floorAdvanced = staged.Draft.InputKind != "map_travel"
                                    || live.TotalFloor > staged.Draft.BeforeMetrics.TotalFloor;
                if (saved is not null
                    && HasRewardMetrics(live)
                    && HasRewardMetrics(saved)
                    && EqualRewardMetrics(live, saved)
                    && floorAdvanced)
                {
                    ResolveStagedExecutionCore(live);
                }
            }

            // A save taken while an action awaits its stable successor is not
            // a resumable collector cursor. In particular, the game's map
            // save runs before TotalFloor advances.
            if (nativeActionRunning
                || _session.Snapshot.Phase != EpisodePhase.Ready)
            {
                RecordDiagnosticCore(
                    "native_save_checkpoint_skipped_for_pending_step",
                    new
                    {
                        phase = _session.Snapshot.Phase.ToString(),
                        native_action_running = nativeActionRunning,
                    });
                return null;
            }

            return new NativeSaveCheckpoint(
                _session.EpisodeId,
                _session.Snapshot.NextEventSequence,
                fingerprint);
        }
    }

    internal void CommitNativeSaveCheckpoint(NativeSaveCheckpoint checkpoint)
    {
        ArgumentNullException.ThrowIfNull(checkpoint);
        lock (_gate)
        {
            if (_session is null
                || _activeSidecar is null
                || _session.EpisodeId != checkpoint.EpisodeId)
            {
                return;
            }

            PersistSidecar(_activeSidecar with
            {
                ResumeCheckpointValid = true,
                ResumeSaveFingerprint = checkpoint.NativeSaveFingerprint,
                DurableEventSequence = checkpoint.DurableEventSequence,
                UpdatedAtUtc = DateTimeOffset.UtcNow,
            });
        }
    }

    internal void Finish(RunHistory history)
    {
        ArgumentNullException.ThrowIfNull(history);
        lock (_gate)
        {
            if (_session is null)
            {
                return;
            }

            // FinishRun waits for accepted native operations to settle. Read
            // the final run state at this boundary; history has no HP field.
            // When the native run state is gone, leave the anchor unavailable.
            var terminalMetrics = CaptureCurrentMetrics();
            ResolveStagedExecutionCore(terminalMetrics);

            var snapshot = _session.Snapshot;
            // Only a trajectory observed continuously from the native run
            // start may become a whole-run value target. Auto-mode reloads
            // remain conservative because they cannot prove whether a load
            // was a clean continuation or save-scumming.
            var complete = snapshot.Phase == EpisodePhase.Ready
                           && _observedFromRunStart
                           && !_hasUnknownTimelineBoundary
                           && snapshot.UnknownSaveLoadCount == 0
                           && snapshot.InvalidatedPendingCount == 0
                           && snapshot.UncertainExecutionCount == 0
                           && snapshot.CoverageGapCount == 0
                           && snapshot.UnresolvedManualCombatInputCount == 0
                           && snapshot.UnstructuredUnsafeManualCombatInputCount == 0
                           && !history.WasAbandoned;
            var summary = JsonSerializer.SerializeToElement(
                new
                {
                    history.StartTime,
                    history.RunTime,
                    history.Ascension,
                    game_mode = history.GameMode.ToString(),
                    act_ids = history.Acts.Select(act => act.ToString()).ToArray(),
                    floors_recorded = history.MapPointHistory.Sum(act => act.Count),
                    terminal_current_hp = terminalMetrics.CurrentHp,
                    terminal_max_hp = terminalMetrics.MaxHp,
                    terminal_hp_status = terminalMetrics.CurrentHp is not null
                                         && terminalMetrics.MaxHp is not null
                        ? "available"
                        : "unavailable",
                    players = history.Players.Select(player => new
                    {
                        player_id = player.Id,
                        character_id = player.Character.ToString(),
                        deck_size = player.Deck.Count(),
                        relic_count = player.Relics.Count(),
                        potion_count = player.Potions.Count(),
                    }).ToArray(),
                },
                CollectorJson.Options);
            var outcome = history.WasAbandoned
                ? "abandoned"
                : history.Win ? "win" : "defeat";
            _session.Finish(new EpisodeFinishInput(
                Guid.NewGuid(),
                outcome,
                history.WasAbandoned ? "native_abandon" : "native_run_history",
                complete ? EpisodeCompleteness.Complete : EpisodeCompleteness.Incomplete,
                summary));
            if (_session.CompactViewError is { } compactError)
            {
                Console.WriteLine(
                    "[SlayTheModel/Collector] compact view failed: "
                    + compactError.Message);
            }
            Console.WriteLine(
                $"[SlayTheModel/Collector] finished episode={_session.EpisodeId:N} "
                + $"outcome={outcome} complete={complete}");
            _session.Dispose();
            _session = null;
            _stagedExecution = null;
            DeleteSidecar();
        }
    }

    internal void EndProcessSegment(string reason)
    {
        lock (_gate)
        {
            if (_session is null)
            {
                return;
            }

            var beforeDiagnostic = _session.Snapshot.NextEventSequence;
            RecordDiagnosticCore(
                "segment_ended",
                new { reason, at_utc = DateTimeOffset.UtcNow });
            if (_activeSidecar is
                {
                    ResumeCheckpointValid: true,
                } sidecar
                && sidecar.DurableEventSequence == beforeDiagnostic)
            {
                // Diagnostics do not mutate the native run. Advance the WAL
                // cursor across this final audit record while retaining the
                // exact fingerprint captured from the successfully saved DTO.
                PersistSidecar(sidecar with
                {
                    DurableEventSequence = _session.Snapshot.NextEventSequence,
                    UpdatedAtUtc = DateTimeOffset.UtcNow,
                });
            }
            _session.Dispose();
            _session = null;
            _stagedExecution = null;
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            CloseCurrentSession();
            _disposed = true;
        }
    }

    private CollectorActionDraft? BeginSubmittedActionCore(
        DecisionInput decision,
        DecisionReceipt receipt,
        int selectedActionIndex,
        DateTimeOffset observedAtUtc,
        RunMetrics beforeMetrics,
        string inputKind,
        JsonElement? selectedAction = null)
    {
        var session = _session
            ?? throw new InvalidOperationException("No collector episode is active.");
        if (selectedActionIndex < 0
            || selectedActionIndex >= receipt.ActionKeys.Count)
        {
            RecordDiagnosticCore(
                "unmatched_native_action",
                new
                {
                    inputKind,
                    selectedActionIndex,
                    action_count = receipt.ActionKeys.Count,
                    observedAtUtc,
                });
            session.RecordCoverageGap(new CoverageGapInput(
                Guid.NewGuid(),
                $"unmatched_native_action:{inputKind}"));
            return null;
        }

        var actionKey = receipt.ActionKeys[selectedActionIndex];
        var attemptId = Guid.NewGuid();
        session.SubmitAction(new ActionSubmissionInput(
            Guid.NewGuid(),
            receipt.DecisionId,
            attemptId,
            selectedActionIndex,
            actionKey,
            new PolicyTrace(
                ActionActorForConfiguration(),
                string.Equals(
                    _configuration.Actor,
                    "automation_or_unknown",
                    StringComparison.Ordinal)
                    ? "observed-automation"
                    : "human-demonstration",
                ModelRevision: null),
            selectedAction));
        return new CollectorActionDraft(
            decision,
            receipt,
            selectedActionIndex,
            actionKey,
            attemptId,
            observedAtUtc,
            beforeMetrics,
            inputKind);
    }

    private void RecordDiagnosticCore(string code, object data)
    {
        _session!.RecordDiagnostic(
            code,
            JsonSerializer.SerializeToElement(data, CollectorJson.Options));
    }

    private void FinalizeInterruptedSession(string reason, object details)
    {
        if (_session is null)
        {
            return;
        }

        RecordDiagnosticCore("interrupted_episode", new { reason, details });
        _session.RecordCoverageGap(new CoverageGapInput(Guid.NewGuid(), reason));
        _session.Finish(new EpisodeFinishInput(
            Guid.NewGuid(),
            "interrupted",
            reason,
            EpisodeCompleteness.Incomplete,
            JsonSerializer.SerializeToElement(details, CollectorJson.Options)));
        if (_session.CompactViewError is { } compactError)
        {
            Console.WriteLine(
                "[SlayTheModel/Collector] compact view failed: "
                + compactError.Message);
        }
        Console.WriteLine(
            $"[SlayTheModel/Collector] published interrupted episode="
            + $"{_session.EpisodeId:N} reason={reason}");
        _session.Dispose();
        _session = null;
        _stagedExecution = null;
        _activeSidecar = null;
        if (_sidecarPath is not null && File.Exists(_sidecarPath))
        {
            File.Delete(_sidecarPath);
        }
    }

    private RunMetrics CaptureCurrentMetrics()
    {
        var state = RunManager.Instance.DebugOnlyGetState();
        return state is null
            ? new RunMetrics(null, null, null, null, null, null, null, null, null)
            : CollectorRunContextProjector.CaptureMetrics(state);
    }

    private void ResolveStagedExecutionCore(RunMetrics after)
    {
        var staged = _stagedExecution;
        if (staged is null || _session is null)
        {
            return;
        }

        var snapshot = _session.Snapshot;
        if (staged.EpisodeId != _session.EpisodeId
            || staged.TimelineGeneration != snapshot.TimelineGeneration
            || snapshot.PendingDecisions?.Any(pending =>
                pending.DecisionId == staged.Draft.Receipt.DecisionId
                && pending.Phase == EpisodePhase.AwaitingExecution) != true)
        {
            _stagedExecution = null;
            _contaminatedTransitionAttempts.Remove(staged.Draft.AttemptId);
            RecordDiagnosticCore(
                "staged_execution_discarded",
                new { staged.Draft.InputKind, snapshot.Phase });
            return;
        }

        if (!HasRewardMetrics(staged.Draft.BeforeMetrics)
            || !HasRewardMetrics(after))
        {
            _stagedExecution = null;
            _contaminatedTransitionAttempts.Remove(staged.Draft.AttemptId);
            RecordDiagnosticCore(
                "reward_metrics_unavailable",
                new { staged.Draft.InputKind });
            // Native success is still a valid behavior-cloning label. Write
            // its execution result, then invalidate only the unavailable
            // reward and whole-run value target.
            _session.RecordExecution(new ExecutionInput(
                Guid.NewGuid(),
                staged.Draft.Receipt.DecisionId,
                staged.Draft.AttemptId,
                staged.Draft.SelectedActionIndex,
                staged.Draft.SelectedActionKey,
                staged.Draft.Decision.StateFingerprint,
                staged.Status,
                NextStateFingerprint: null,
                Detail: staged.Detail));
            _session.RecordCoverageGap(new CoverageGapInput(
                Guid.NewGuid(),
                "reward_metrics_unavailable"));
            return;
        }

        _stagedExecution = null;
        var draft = staged.Draft;
        var contaminated = _contaminatedTransitionAttempts.Remove(draft.AttemptId);
        _session.RecordExecution(new ExecutionInput(
            Guid.NewGuid(),
            draft.Receipt.DecisionId,
            draft.AttemptId,
            draft.SelectedActionIndex,
            draft.SelectedActionKey,
            draft.Decision.StateFingerprint,
            staged.Status,
            NextStateFingerprint: contaminated
                ? null
                : TryFingerprintCurrentState(draft.Decision),
            Detail: contaminated
                ? string.IsNullOrWhiteSpace(staged.Detail)
                    ? "transition_contaminated_by_queued_manual_input"
                    : staged.Detail + "; transition_contaminated_by_queued_manual_input"
                : staged.Detail));
        _session.RecordReward(new RewardInput(
            Guid.NewGuid(),
            draft.Receipt.DecisionId,
            RewardVersion,
            RewardComponents(draft.BeforeMetrics, after)));
        // An outside potion can be used or discarded while another native
        // screen action is awaiting its next stable boundary. Even if an
        // entry-point hook was missed, the resulting potion loss must not be
        // advertised as a complete whole-run trajectory. This is an audit
        // guard, never a reconstructed potion action label.
        if (draft.Decision.Domain == CollectorDecisionDomain.OutsideCombat
            && draft.InputKind is not ("outside_potion_use" or "outside_potion_discard")
            && draft.BeforeMetrics.PotionCount > after.PotionCount)
        {
            RecordDiagnosticCore(
                "outside_potion_loss_during_other_action",
                new
                {
                    draft.InputKind,
                    draft.SelectedActionKey,
                    before_potion_count = draft.BeforeMetrics.PotionCount,
                    after_potion_count = after.PotionCount,
                });
            _session.RecordCoverageGap(new CoverageGapInput(
                Guid.NewGuid(),
                "outside_potion_loss_during_other_action",
                InvalidatePendingDecision: false,
                RelatedDecisionId: draft.Receipt.DecisionId,
                RelatedAttemptId: draft.AttemptId));
        }
    }

    private static bool HasRewardMetrics(RunMetrics metrics) =>
        WholeRunV2RewardCalculator.HasMetrics(ToRewardMetrics(metrics));

    private static RunMetrics? TryCaptureSavedMetrics(SerializableRun save)
    {
        if (save.Players.Count != 1)
        {
            return null;
        }

        var player = save.Players[0];
        return new RunMetrics(
            player.CurrentHp,
            player.MaxHp,
            player.Gold,
            save.CurrentActIndex,
            ActFloor: null,
            save.FloorReached,
            player.Deck.Count,
            player.Relics.Count,
            player.Potions.Count);
    }

    private static bool EqualRewardMetrics(RunMetrics left, RunMetrics right) =>
        left.CurrentHp == right.CurrentHp
        && left.Gold == right.Gold
        && left.ActIndex == right.ActIndex
        && left.TotalFloor == right.TotalFloor
        && left.DeckSize == right.DeckSize
        && left.RelicCount == right.RelicCount
        && left.PotionCount == right.PotionCount;

    private static IReadOnlyDictionary<string, double> RewardComponents(
        RunMetrics before,
        RunMetrics after) => WholeRunV2RewardCalculator.Compute(
        ToRewardMetrics(before), ToRewardMetrics(after));

    private static WholeRunV2Metrics ToRewardMetrics(RunMetrics metrics) => new(
        metrics.CurrentHp,
        metrics.Gold,
        metrics.ActIndex,
        metrics.TotalFloor,
        metrics.DeckSize,
        metrics.RelicCount,
        metrics.PotionCount);

    private static JsonElement BuildContext(
        JsonElement runContext,
        JsonElement? metadata) => JsonSerializer.SerializeToElement(
        new
        {
            run_context = runContext,
            audit = metadata,
        },
        CollectorJson.Options);

    private RunState RequireRunState() =>
        RunManager.Instance.DebugOnlyGetState()
        ?? throw new InvalidOperationException("Native run state is unavailable.");

    private string? TryFingerprintCurrentState(DecisionInput decision)
    {
        try
        {
            if (decision.Domain == CollectorDecisionDomain.Combat
                && CombatManager.Instance.IsInProgress
                && CombatManager.Instance.DebugOnlyGetState() is { } combat)
            {
                return CollectorCombatProjector.Capture(
                    combat,
                    decision.SourceDecisionIndex).ObservationFingerprint;
            }

            // An outside decision fingerprint includes the exact surface and
            // legal-action set. Run context alone is a different hash domain,
            // so leave this null until the next semantic surface is projected.
            return null;
        }
        catch
        {
            return null;
        }
    }

    private static string FingerprintRunContext(RunState state)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(
            CollectorRunContextProjector.Capture(state),
            CollectorJson.Options);
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    internal static string? TryFingerprintNativeSave(SerializableRun save)
    {
        try
        {
            ArgumentNullException.ThrowIfNull(save);
            var writer = new PacketWriter();
            writer.Write(save);

            // Work on a packet clone: the DTO passed to SaveRun belongs to the
            // game and must never be mutated by an observer. SaveTime/RunTime
            // and NumReloads are bookkeeping fields that can change while an
            // otherwise identical checkpoint is written or loaded. Removing
            // them makes the comparison about the saved game state/RNG, not
            // wall-clock timing or how many times it has been opened.
            var reader = new PacketReader();
            reader.Reset(writer.Buffer.AsSpan(0, writer.BytePosition).ToArray());
            var canonical = reader.Read<SerializableRun>();
            canonical.SaveTime = 0;
            canonical.RunTime = 0;
            canonical.NumReloads = 0;

            writer = new PacketWriter();
            writer.Write(canonical);
            return Convert.ToHexString(
                    SHA256.HashData(writer.Buffer.AsSpan(0, writer.BytePosition)))
                .ToLowerInvariant();
        }
        catch
        {
            return null;
        }
    }

    private static string ComputeRunKey(RunState state, long? startTime)
    {
        var profile = SaveManager.Instance.IsProfileInitialized
            ? SaveManager.Instance.CurrentProfileId.ToString()
            : "uninitialized";
        var character = state.Players.Count == 1
            ? state.Players[0].Character.Id.ToString()
            : "unknown";
        var material = string.Join(
            "|",
            profile,
            startTime?.ToString() ?? "unknown",
            state.Rng.StringSeed,
            character);
        return Convert.ToHexString(
                SHA256.HashData(Encoding.UTF8.GetBytes(material)))
            .ToLowerInvariant();
    }

    private static void AddSteamIdentity(IDictionary<string, string> metadata)
    {
        try
        {
            if (PlatformUtil.PrimaryPlatform != PlatformType.Steam)
            {
                metadata["steam_identity_status"] = "not_steam";
                return;
            }

            var steamId = PlatformUtil.GetLocalPlayerId(PlatformType.Steam);
            if (steamId == 0)
            {
                metadata["steam_identity_status"] = "unavailable";
                return;
            }

            var idText = steamId.ToString(CultureInfo.InvariantCulture);
            metadata["steam_id64"] = idText;
            var name = PlatformUtil.GetPlayerNameRaw(PlatformType.Steam, steamId);
            if (string.IsNullOrWhiteSpace(name)
                || string.Equals(name, idText, StringComparison.Ordinal))
            {
                metadata["steam_identity_status"] = "name_unavailable";
                return;
            }

            metadata["steam_persona_name"] = name;
            metadata["steam_identity_status"] = "available";
        }
        catch
        {
            // Steam can be unavailable even when the game itself works.
            // Identity failure must never disable a read-only collector.
            metadata["steam_identity_status"] = "unavailable";
        }
    }

    private InformationRegime InformationRegimeForConfiguration() =>
        _configuration.InformationMode switch
        {
            CollectorInformationMode.NoSl when !_hasUnknownTimelineBoundary =>
                InformationRegime.NoSl,
            CollectorInformationMode.NoSl => InformationRegime.Unknown,
            CollectorInformationMode.Sl => InformationRegime.Sl,
            _ => InformationRegime.Unknown,
        };

    private ActionActor ActionActorForConfiguration() =>
        string.Equals(
            _configuration.Actor,
            "automation_or_unknown",
            StringComparison.Ordinal)
            ? ActionActor.Policy
            : ActionActor.Human;

    private SaveLoadKind SaveLoadKindForObservedCheckpoint(bool checkpointMatches) =>
        _configuration.InformationMode switch
        {
            CollectorInformationMode.Sl => SaveLoadKind.Rewind,
            CollectorInformationMode.NoSl when checkpointMatches => SaveLoadKind.Resume,
            _ => SaveLoadKind.Unknown,
        };

    private static string SaveLoadReason(SaveLoadKind kind, string boundary) => kind switch
    {
        SaveLoadKind.Rewind => $"saved_run_loaded_explicit_sl:{boundary}",
        SaveLoadKind.Resume => $"saved_run_loaded_explicit_no_sl:{boundary}",
        _ => $"saved_run_loaded_auto_unknown:{boundary}",
    };

    private static string InformationModeName(CollectorInformationMode mode) => mode switch
    {
        CollectorInformationMode.Auto => "unknown",
        CollectorInformationMode.NoSl => "no_sl",
        CollectorInformationMode.Sl => "sl",
        _ => throw new ArgumentOutOfRangeException(nameof(mode)),
    };

    private static string CollectorRevision()
    {
        var assembly = typeof(CollectorEpisodeCoordinator).Assembly;
        return $"{assembly.GetName().Version?.ToString(3) ?? "0.0.0"}+"
               + assembly.ManifestModule.ModuleVersionId.ToString("N");
    }

    private static ActiveRunSidecar? ReadSidecar(string path)
    {
        try
        {
            return File.Exists(path)
                ? JsonSerializer.Deserialize<ActiveRunSidecar>(File.ReadAllText(path))
                : null;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] active-run sidecar ignored: {exception.Message}");
            return null;
        }
    }

    private static void WriteSidecar(string path, ActiveRunSidecar sidecar)
    {
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(sidecar));
        File.Move(temporary, path, overwrite: true);
    }

    private bool TryResumePartial(Guid episodeId, string context)
    {
        try
        {
            _session = _store.ResumeEpisode(episodeId);
            if (_session.CanAppend
                && !string.Equals(
                    _session.RewardVersion,
                    RewardVersion,
                    StringComparison.Ordinal))
            {
                FinalizeInterruptedSession(
                    "collector_reward_version_changed",
                    new
                    {
                        prior_reward_version = _session.RewardVersion,
                        current_reward_version = RewardVersion,
                    });
                return false;
            }
            return true;
        }
        catch (Exception exception)
        {
            _session = null;
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] corrupt partial quarantined "
                + $"episode={episodeId:N} context={context}: {exception.Message}");
            var source = _store.GetOpenEpisodePath(episodeId);
            try
            {
                if (File.Exists(source))
                {
                    var quarantine = Path.Combine(
                        _configuration.DatasetRoot,
                        "episodes",
                        "_quarantine");
                    Directory.CreateDirectory(quarantine);
                    var destination = Path.Combine(
                        quarantine,
                        $"{episodeId:N}-{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}"
                        + ".jsonl.partial");
                    File.Move(source, destination, overwrite: false);
                }
            }
            catch (Exception quarantineError)
            {
                // Removing the stale sidecar below still prevents one corrupt
                // file from permanently disabling collection on every launch.
                Console.Error.WriteLine(
                    "[SlayTheModel/Collector] corrupt partial quarantine move failed: "
                    + quarantineError.Message);
            }

            if (_sidecarPath is not null && File.Exists(_sidecarPath))
            {
                File.Delete(_sidecarPath);
            }
            _activeSidecar = null;
            return false;
        }
    }

    private void PersistSidecar(ActiveRunSidecar sidecar)
    {
        if (_sidecarPath is null)
        {
            throw new InvalidOperationException("Active-run sidecar path is unavailable.");
        }

        WriteSidecar(_sidecarPath, sidecar);
        _activeSidecar = sidecar;
    }

    private void DeleteSidecar()
    {
        if (_sidecarPath is not null && File.Exists(_sidecarPath))
        {
            File.Delete(_sidecarPath);
        }

        _runKey = null;
        _sidecarPath = null;
        _activeSidecar = null;
    }

    private void CloseCurrentSession()
    {
        _session?.Dispose();
        _session = null;
        _stagedExecution = null;
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(CollectorEpisodeCoordinator));
        }
    }

    private sealed record ActiveRunSidecar(
        int SchemaVersion,
        string RunKey,
        Guid EpisodeId,
        long? StartTime,
        int NativeReloadCount,
        int ResumeCount,
        bool ObservedFromRunStart,
        bool HasUnknownTimelineBoundary,
        bool ResumeCheckpointValid,
        string? ResumeSaveFingerprint,
        long DurableEventSequence,
        DateTimeOffset UpdatedAtUtc)
    {
        internal const int CurrentSchemaVersion = 3;
    }
}

internal static class CapturedCombatDecisionExtensions
{
    internal static JsonElement ObservedGuardMetadata(this CapturedCombatDecision captured) =>
        JsonSerializer.SerializeToElement(
            new
            {
                execution_guard_fingerprint = captured.ExecutionGuardFingerprint,
                observation_fingerprint = captured.ObservationFingerprint,
            },
            CollectorJson.Options);
}
