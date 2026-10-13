using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SlayTheModel.Collector;

/// <summary>
/// Summary of a derived, human-readable compact episode view. The canonical
/// hash-chained episode remains the source of truth.
/// </summary>
public sealed record CompactEpisodeExportResult(
    string SourcePath,
    string CompactPath,
    int SourceEventCount,
    int DecisionCount,
    int FullObservationCount,
    long SourceBytes,
    long CompactBytes,
    string SourceSha256,
    string CompactSha256);

/// <summary>
/// Writes a compact event-sourced view of a canonical collector episode.
///
/// Decision observations and contexts use deterministic JSON-pointer deltas
/// between checkpoints. Legal actions and submitted set selections remain
/// explicit at their original click boundary. Every delta is expanded again
/// in memory and compared with the canonical payload before publication.
/// </summary>
public static class CompactEpisodeJournal
{
    public const int CurrentSchemaVersion = 1;
    public const int DefaultCheckpointInterval = 64;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = false,
    };

    public static CompactEpisodeExportResult Export(
        string sourcePath,
        string compactPath,
        int checkpointInterval = DefaultCheckpointInterval,
        bool overwrite = false)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sourcePath);
        ArgumentException.ThrowIfNullOrWhiteSpace(compactPath);
        if (checkpointInterval <= 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(checkpointInterval), "Checkpoint interval must be positive.");
        }

        sourcePath = Path.GetFullPath(sourcePath);
        compactPath = Path.GetFullPath(compactPath);
        if (string.Equals(sourcePath, compactPath, StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "Compact output must not overwrite the canonical episode.",
                nameof(compactPath));
        }

        var events = JsonlEpisodeJournal.ReadCompleted(sourcePath);
        if (events.Count == 0)
        {
            throw new InvalidDataException("Collector episode is empty.");
        }

        var episodeId = events[0].EpisodeId;
        var replay = EpisodeSession.Replay(episodeId, events);
        if (replay.Phase != EpisodePhase.Finished)
        {
            throw new InvalidDataException(
                "Compact views require a completed collector episode.");
        }

        var directory = Path.GetDirectoryName(compactPath)
            ?? throw new InvalidDataException("Compact output has no parent directory.");
        Directory.CreateDirectory(directory);
        if (!overwrite && File.Exists(compactPath))
        {
            throw new IOException($"Compact episode already exists: {compactPath}");
        }

        var temporary = Path.Combine(
            directory,
            $".{Path.GetFileName(compactPath)}.{Guid.NewGuid():N}.tmp");
        var sourceHash = FileSha256(sourcePath);
        var sourceBytes = new FileInfo(sourcePath).Length;
        var state = new ProjectionState(checkpointInterval);
        try
        {
            using (var stream = new FileStream(
                       temporary,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.Read,
                       bufferSize: 64 * 1024,
                       FileOptions.WriteThrough))
            using (var writer = new StreamWriter(
                       stream,
                       new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                       bufferSize: 64 * 1024,
                       leaveOpen: true))
            {
                foreach (var envelope in events)
                {
                    var record = Project(envelope, state, sourceHash, events.Count);
                    writer.Write(record.ToJsonString(JsonOptions));
                    writer.Write('\n');
                }

                writer.Flush();
                stream.Flush(flushToDisk: true);
            }

            File.Move(temporary, compactPath, overwrite);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }

        return new CompactEpisodeExportResult(
            sourcePath,
            compactPath,
            events.Count,
            state.DecisionCount,
            state.FullObservationCount,
            sourceBytes,
            new FileInfo(compactPath).Length,
            sourceHash,
            FileSha256(compactPath));
    }

    private static JsonObject Project(
        CollectorEventEnvelope envelope,
        ProjectionState state,
        string sourceHash,
        int sourceEventCount)
    {
        var record = new JsonObject
        {
            ["t"] = EventName(envelope.EventType),
            ["q"] = envelope.EventSequence,
        };
        if (envelope.GlobalStep is { } step)
        {
            record["s"] = step;
        }

        if (envelope.TimelineGeneration != 0)
        {
            record["g"] = envelope.TimelineGeneration;
        }

        switch (envelope.EventType)
        {
            case CollectorEventType.EpisodeStarted:
                ProjectStart(envelope, record, sourceHash);
                break;
            case CollectorEventType.Decision:
                ProjectDecision(envelope, record, state);
                break;
            case CollectorEventType.ActionSubmitted:
                ProjectAction(envelope, record, state);
                break;
            case CollectorEventType.ExecutionResult:
                ProjectExecution(envelope, record, state);
                break;
            case CollectorEventType.Reward:
                ProjectReward(envelope, record);
                break;
            case CollectorEventType.SaveLoad:
                record["data"] = PayloadNode(envelope);
                state.ResetDecisionBases();
                break;
            case CollectorEventType.CoverageGap:
            case CollectorEventType.Diagnostic:
                record["data"] = PayloadNode(envelope);
                break;
            case CollectorEventType.ManualCombatInput:
                ProjectManualInput(envelope, record, state);
                break;
            case CollectorEventType.ManualCombatInputOutcome:
                ProjectManualOutcome(envelope, record, state);
                break;
            case CollectorEventType.EpisodeFinished:
                record["data"] = PayloadNode(envelope);
                record["source_final_sha256"] = sourceHash;
                record["source_event_count"] = sourceEventCount;
                record["decision_count"] = state.DecisionCount;
                record["full_observation_count"] = state.FullObservationCount;
                record["delta_round_trip_verified"] = true;
                break;
            default:
                throw new InvalidDataException(
                    $"Unsupported collector event {envelope.EventType}.");
        }

        return record;
    }

    private static void ProjectStart(
        CollectorEventEnvelope envelope,
        JsonObject record,
        string sourceHash)
    {
        var payload = PayloadNode(envelope).AsObject();
        record["v"] = CurrentSchemaVersion;
        record["episode_id"] = envelope.EpisodeId.ToString("N");
        record["source"] = JsonValue.Create(
            envelope.Source.ToString().ToLowerInvariant());
        record["source_sha256"] = sourceHash;
        foreach (var property in payload)
        {
            record[property.Key] = property.Value?.DeepClone();
        }
    }

    private static void ProjectDecision(
        CollectorEventEnvelope envelope,
        JsonObject record,
        ProjectionState state)
    {
        var payload = envelope.Payload.Deserialize<DecisionPayload>(CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Decision event {envelope.EventSequence} has no payload.");
        var step = envelope.GlobalStep
            ?? throw new InvalidDataException("Decision event has no global step.");
        state.DecisionSteps[payload.DecisionId] = step;

        var prior = state.LastDecision;
        var useFull = prior is null
                      || prior.TimelineGeneration != envelope.TimelineGeneration
                      || state.DecisionCount % state.CheckpointInterval == 0;
        var observation = Node(payload.Observation);
        var observationDelta = EncodeDelta(
            observation,
            prior?.Observation,
            prior?.Step,
            useFull);
        VerifyDelta(observationDelta, prior?.Observation, observation, "observation");

        var context = payload.Context is { } rawContext
            && rawContext.ValueKind != JsonValueKind.Null
                ? Node(rawContext)
                : null;
        var contextDelta = EncodeNullableDelta(
            context,
            prior?.Context,
            prior?.Step,
            useFull);
        VerifyNullableDelta(contextDelta, prior?.Context, context, "context");

        record["domain"] = EnumName(payload.Domain);
        record["information_regime"] = EnumName(payload.InformationRegime);
        record["source_decision_index"] = payload.SourceDecisionIndex;
        record["state_fingerprint"] = payload.StateFingerprint;
        record["observation"] = observationDelta;
        record["observation_sha256"] = JsonSha256(observation);
        var legalActions = Node(payload.LegalActions);
        record["legal_actions"] = legalActions;
        record["context"] = contextDelta;
        if (context is not null)
        {
            record["context_sha256"] = JsonSha256(context);
        }

        if (payload.Build is not null)
        {
            record["build"] = JsonSerializer.SerializeToNode(
                payload.Build, CollectorJson.Options);
        }

        if (payload.QueuedCombatInput)
        {
            record["queued_combat_input"] = true;
        }

        if (payload.QueuedOutsideInput)
        {
            record["queued_outside_input"] = true;
        }

        state.LastDecision = new DecisionBase(
            step,
            envelope.TimelineGeneration,
            observation.DeepClone(),
            context?.DeepClone());
        state.Decisions[payload.DecisionId] = new DecisionReference(
            step,
            observation.DeepClone(),
            legalActions.DeepClone(),
            payload.StateFingerprint);
        state.DecisionCount++;
        if (useFull)
        {
            state.FullObservationCount++;
        }
    }

    private static void ProjectAction(
        CollectorEventEnvelope envelope,
        JsonObject record,
        ProjectionState state)
    {
        var payload = envelope.Payload.Deserialize<ActionSubmittedPayload>(CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Action event {envelope.EventSequence} has no payload.");
        var step = RequireDecisionStep(state, payload.DecisionId);
        var attempt = state.NextAttemptByDecision.TryGetValue(payload.DecisionId, out var prior)
            ? prior + 1
            : 1;
        state.NextAttemptByDecision[payload.DecisionId] = attempt;
        state.Attempts[payload.AttemptId] = new AttemptReference(
            step,
            attempt,
            payload.DecisionId,
            payload.SelectedActionIndex);
        record["s"] = step;
        record["attempt"] = attempt;
        record["selected_action_index"] = payload.SelectedActionIndex;
        record["policy"] = JsonSerializer.SerializeToNode(
            payload.Policy, CollectorJson.Options);
        if (payload.SelectedAction is { } selected)
        {
            record["selected_action"] = Node(selected);
        }
    }

    private static void ProjectExecution(
        CollectorEventEnvelope envelope,
        JsonObject record,
        ProjectionState state)
    {
        var payload = envelope.Payload.Deserialize<ExecutionResultPayload>(CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Execution event {envelope.EventSequence} has no payload.");
        if (!state.Attempts.TryGetValue(payload.AttemptId, out var attempt))
        {
            throw new InvalidDataException(
                $"Execution event {envelope.EventSequence} has no compact attempt.");
        }

        record["s"] = attempt.Step;
        record["attempt"] = attempt.Ordinal;
        record["status"] = EnumName(payload.Status);
        record["expected_state_fingerprint"] = payload.ExpectedStateFingerprint;
        if (payload.NextStateFingerprint is not null)
        {
            record["next_state_fingerprint"] = payload.NextStateFingerprint;
        }

        if (payload.Detail is not null)
        {
            record["detail"] = payload.Detail;
        }
    }

    private static void ProjectReward(
        CollectorEventEnvelope envelope,
        JsonObject record)
    {
        var payload = envelope.Payload.Deserialize<RewardPayload>(CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Reward event {envelope.EventSequence} has no payload.");
        record["components"] = JsonSerializer.SerializeToNode(
            payload.Components, CollectorJson.Options);
    }

    private static void ProjectManualInput(
        CollectorEventEnvelope envelope,
        JsonObject record,
        ProjectionState state)
    {
        var payload = envelope.Payload.Deserialize<ManualCombatInputPayload>(
                CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Manual input event {envelope.EventSequence} has no payload.");
        var inputOrdinal = ++state.ManualInputCount;
        state.Decisions.TryGetValue(
            payload.RelatedDecisionId ?? Guid.Empty,
            out var decision);
        state.Attempts.TryGetValue(
            payload.RelatedAttemptId ?? Guid.Empty,
            out var attempt);
        if (decision is null && attempt is not null)
        {
            state.Decisions.TryGetValue(attempt.DecisionId, out decision);
        }

        state.ManualInputs[payload.IntentId] = new ManualInputReference(
            inputOrdinal, decision, attempt);
        record["input"] = inputOrdinal;
        if (decision is not null)
        {
            record["s"] = decision.Step;
        }
        else if (payload.RelatedDecisionId is { } decisionId)
        {
            record["related_decision_id"] = decisionId.ToString("N");
        }

        if (attempt is not null)
        {
            record["attempt"] = attempt.Ordinal;
        }
        else if (payload.RelatedAttemptId is { } attemptId)
        {
            record["related_attempt_id"] = attemptId.ToString("N");
        }

        record["native_action_id"] = payload.NativeActionId;
        record["action_kind"] = payload.ActionKind;
        var data = Node(payload.Data);
        if (data is not JsonObject dataObject)
        {
            record["data"] = data;
            return;
        }

        RemoveNullProperties(dataObject);
        if (decision is not null)
        {
            var observationMatches = RemoveIfEqual(
                dataObject, "click_observation", decision.Observation);
            var legalMatches = RemoveIfEqual(
                dataObject, "click_legal_actions", decision.LegalActions);
            var fingerprintMatches = dataObject["click_observation_fingerprint"]
                                     ?.GetValue<string>() == decision.StateFingerprint;
            if (fingerprintMatches)
            {
                dataObject.Remove("click_observation_fingerprint");
            }

            if (observationMatches && legalMatches && fingerprintMatches)
            {
                record["decision_evidence"] = "exact";
            }
        }

        if (decision is not null
            && attempt is not null
            && decision.LegalActions is JsonArray legal
            && attempt.SelectedActionIndex >= 0
            && attempt.SelectedActionIndex < legal.Count
            && RemoveIfEqual(
                dataObject,
                "action",
                legal[attempt.SelectedActionIndex]))
        {
            record["action_evidence"] = "selected";
        }

        RewriteRelatedReference(
            dataObject, "overlaps_decision_id", "overlaps_step", state.Decisions);
        RewriteAttemptReference(
            dataObject, "overlaps_attempt_id", "overlaps_attempt", state.Attempts);
        RemoveNullProperties(dataObject);
        if (dataObject.Count > 0)
        {
            record["data"] = dataObject;
        }
    }

    private static void ProjectManualOutcome(
        CollectorEventEnvelope envelope,
        JsonObject record,
        ProjectionState state)
    {
        var payload = envelope.Payload.Deserialize<ManualCombatInputOutcomePayload>(
                CollectorJson.Options)
            ?? throw new InvalidDataException(
                $"Manual input outcome event {envelope.EventSequence} has no payload.");
        if (!state.ManualInputs.TryGetValue(payload.IntentId, out var input))
        {
            throw new InvalidDataException(
                $"Manual input outcome {envelope.EventSequence} has no compact input.");
        }

        record["input"] = input.Ordinal;
        if (input.Decision is not null)
        {
            record["s"] = input.Decision.Step;
        }

        if (input.Attempt is not null)
        {
            record["attempt"] = input.Attempt.Ordinal;
        }

        record["native_action_id"] = payload.NativeActionId;
        record["status"] = EnumName(payload.Status);
        if (payload.Detail is not null)
        {
            record["detail"] = payload.Detail;
        }

        if (payload.Data is not { } rawData
            || rawData.ValueKind == JsonValueKind.Null)
        {
            return;
        }

        var data = Node(rawData);
        if (data is not JsonObject dataObject)
        {
            record["data"] = data;
            return;
        }

        RemoveNullProperties(dataObject);
        if (input.Decision is not null)
        {
            RewriteObservationAsDelta(
                dataObject, "execution_start_observation", input.Decision);
            RewriteObservationAsDelta(
                dataObject, "execution_end_observation", input.Decision);
        }

        RemoveNullProperties(dataObject);
        if (dataObject.Count > 0)
        {
            record["data"] = dataObject;
        }
    }

    private static bool RemoveIfEqual(
        JsonObject data,
        string property,
        JsonNode? expected)
    {
        if (!data.TryGetPropertyValue(property, out var actual)
            || !JsonNode.DeepEquals(actual, expected))
        {
            return false;
        }

        data.Remove(property);
        return true;
    }

    private static void RewriteObservationAsDelta(
        JsonObject data,
        string property,
        DecisionReference decision)
    {
        if (!data.TryGetPropertyValue(property, out var observation)
            || observation is null)
        {
            return;
        }

        var delta = EncodeDelta(
            observation, decision.Observation, decision.Step, forceFull: false);
        VerifyDelta(delta, decision.Observation, observation, property);
        data[property] = delta;
        data[$"{property}_sha256"] = JsonSha256(observation);
    }

    private static void RewriteRelatedReference(
        JsonObject data,
        string sourceProperty,
        string targetProperty,
        IReadOnlyDictionary<Guid, DecisionReference> decisions)
    {
        var raw = data[sourceProperty]?.GetValue<string>();
        if (raw is null || !Guid.TryParse(raw, out var id)
            || !decisions.TryGetValue(id, out var decision))
        {
            return;
        }

        data.Remove(sourceProperty);
        data[targetProperty] = decision.Step;
    }

    private static void RewriteAttemptReference(
        JsonObject data,
        string sourceProperty,
        string targetProperty,
        IReadOnlyDictionary<Guid, AttemptReference> attempts)
    {
        var raw = data[sourceProperty]?.GetValue<string>();
        if (raw is null || !Guid.TryParse(raw, out var id)
            || !attempts.TryGetValue(id, out var attempt))
        {
            return;
        }

        data.Remove(sourceProperty);
        data[targetProperty] = new JsonObject
        {
            ["s"] = attempt.Step,
            ["attempt"] = attempt.Ordinal,
        };
    }

    private static void RemoveNullProperties(JsonObject value)
    {
        foreach (var key in value
                     .Where(property => property.Value is null)
                     .Select(property => property.Key)
                     .ToArray())
        {
            value.Remove(key);
        }
    }

    private static long RequireDecisionStep(ProjectionState state, Guid decisionId) =>
        state.DecisionSteps.TryGetValue(decisionId, out var step)
            ? step
            : throw new InvalidDataException(
                $"Compact event references unknown decision {decisionId}.");

    private static JsonObject EncodeDelta(
        JsonNode current,
        JsonNode? previous,
        long? previousStep,
        bool forceFull)
    {
        if (forceFull || previous is null || previousStep is null)
        {
            return new JsonObject
            {
                ["mode"] = "full",
                ["value"] = current.DeepClone(),
            };
        }

        var set = new JsonObject();
        var remove = new JsonArray();
        Diff(previous, current, string.Empty, set, remove);
        var result = new JsonObject
        {
            ["mode"] = "delta",
            ["base_step"] = previousStep.Value,
        };
        if (set.Count > 0)
        {
            result["set"] = set;
        }

        if (remove.Count > 0)
        {
            result["remove"] = remove;
        }

        return result;
    }

    private static JsonObject EncodeNullableDelta(
        JsonNode? current,
        JsonNode? previous,
        long? previousStep,
        bool forceFull)
    {
        if (current is null)
        {
            return new JsonObject { ["mode"] = "null" };
        }

        return EncodeDelta(current, previous, previousStep, forceFull || previous is null);
    }

    private static void VerifyDelta(
        JsonObject delta,
        JsonNode? previous,
        JsonNode expected,
        string label)
    {
        var actual = ApplyDelta(delta, previous);
        if (!JsonNode.DeepEquals(actual, expected))
        {
            throw new InvalidDataException(
                $"Compact {label} delta failed its round-trip check.");
        }
    }

    private static void VerifyNullableDelta(
        JsonObject delta,
        JsonNode? previous,
        JsonNode? expected,
        string label)
    {
        var actual = delta["mode"]?.GetValue<string>() == "null"
            ? null
            : ApplyDelta(delta, previous);
        if (!JsonNode.DeepEquals(actual, expected))
        {
            throw new InvalidDataException(
                $"Compact {label} delta failed its round-trip check.");
        }
    }

    private static JsonNode ApplyDelta(JsonObject delta, JsonNode? previous)
    {
        var mode = delta["mode"]?.GetValue<string>();
        if (mode == "full")
        {
            return delta["value"]?.DeepClone()
                ?? throw new InvalidDataException("Full compact delta has no value.");
        }

        if (mode != "delta" || previous is null)
        {
            throw new InvalidDataException("Compact delta has no valid base.");
        }

        var current = previous.DeepClone();
        if (delta["remove"] is JsonArray remove)
        {
            foreach (var path in remove
                         .Select(item => item?.GetValue<string>()
                             ?? throw new InvalidDataException("Null compact remove path."))
                         .OrderByDescending(item => item.Count(character => character == '/')))
            {
                RemoveAt(current, path);
            }
        }

        if (delta["set"] is JsonObject set)
        {
            foreach (var property in set)
            {
                current = SetAt(current, property.Key, property.Value?.DeepClone());
            }
        }

        return current;
    }

    private static void Diff(
        JsonNode previous,
        JsonNode current,
        string path,
        JsonObject set,
        JsonArray remove)
    {
        if (JsonNode.DeepEquals(previous, current))
        {
            return;
        }

        if (previous is JsonObject previousObject
            && current is JsonObject currentObject)
        {
            foreach (var key in previousObject.Select(item => item.Key)
                         .Except(currentObject.Select(item => item.Key), StringComparer.Ordinal)
                         .Order(StringComparer.Ordinal))
            {
                remove.Add(ChildPath(path, key));
            }

            foreach (var key in currentObject.Select(item => item.Key)
                         .Order(StringComparer.Ordinal))
            {
                var childPath = ChildPath(path, key);
                var currentChild = currentObject[key];
                if (!previousObject.TryGetPropertyValue(key, out var previousChild))
                {
                    set[childPath] = currentChild?.DeepClone();
                }
                else if (previousChild is null || currentChild is null)
                {
                    if (!JsonNode.DeepEquals(previousChild, currentChild))
                    {
                        set[childPath] = currentChild?.DeepClone();
                    }
                }
                else
                {
                    Diff(previousChild, currentChild, childPath, set, remove);
                }
            }

            return;
        }

        if (previous is JsonArray previousArray
            && current is JsonArray currentArray
            && previousArray.Count == currentArray.Count)
        {
            var candidateSet = new JsonObject();
            var candidateRemove = new JsonArray();
            for (var index = 0; index < currentArray.Count; index++)
            {
                var childPath = ChildPath(path, index.ToString());
                var previousChild = previousArray[index];
                var currentChild = currentArray[index];
                if (previousChild is null || currentChild is null)
                {
                    if (!JsonNode.DeepEquals(previousChild, currentChild))
                    {
                        candidateSet[childPath] = currentChild?.DeepClone();
                    }
                }
                else
                {
                    Diff(previousChild, currentChild, childPath,
                        candidateSet, candidateRemove);
                }
            }

            var candidate = new JsonObject
            {
                ["set"] = candidateSet.DeepClone(),
                ["remove"] = candidateRemove.DeepClone(),
            };
            var replacement = new JsonObject
            {
                [path] = current.DeepClone(),
            };
            if (candidate.ToJsonString(JsonOptions).Length
                < replacement.ToJsonString(JsonOptions).Length)
            {
                foreach (var property in candidateSet)
                {
                    set[property.Key] = property.Value?.DeepClone();
                }

                foreach (var item in candidateRemove)
                {
                    remove.Add(item?.DeepClone());
                }

                return;
            }
        }

        set[path] = current.DeepClone();
    }

    private static JsonNode SetAt(JsonNode root, string path, JsonNode? value)
    {
        if (path.Length == 0)
        {
            return value
                ?? throw new InvalidDataException("Compact observation root cannot be null.");
        }

        var (parent, leaf) = ParentAt(root, path);
        switch (parent)
        {
            case JsonObject parentObject:
                parentObject[leaf] = value;
                break;
            case JsonArray parentArray:
                parentArray[ParseArrayIndex(leaf, parentArray.Count)] = value;
                break;
            default:
                throw new InvalidDataException(
                    $"Compact JSON pointer parent is not a container: {path}");
        }

        return root;
    }

    private static void RemoveAt(JsonNode root, string path)
    {
        if (path.Length == 0)
        {
            throw new InvalidDataException("Compact delta cannot remove its root.");
        }

        var (parent, leaf) = ParentAt(root, path);
        var removed = parent switch
        {
            JsonObject parentObject => parentObject.Remove(leaf),
            JsonArray parentArray => RemoveArrayIndex(parentArray, leaf),
            _ => false,
        };
        if (!removed)
        {
            throw new InvalidDataException(
                $"Compact delta remove path does not exist: {path}");
        }
    }

    private static (JsonNode Parent, string Leaf) ParentAt(JsonNode root, string path)
    {
        var parts = path.Split('/', StringSplitOptions.None);
        if (parts.Length < 2 || parts[0].Length != 0)
        {
            throw new InvalidDataException($"Invalid compact JSON pointer: {path}");
        }

        JsonNode current = root;
        for (var index = 1; index < parts.Length - 1; index++)
        {
            var part = Unescape(parts[index]);
            current = current switch
            {
                JsonObject currentObject => currentObject[part],
                JsonArray currentArray => currentArray[
                    ParseArrayIndex(part, currentArray.Count)],
                _ => null,
            } ?? throw new InvalidDataException(
                $"Compact JSON pointer parent does not exist: {path}");
        }

        return (current, Unescape(parts[^1]));
    }

    private static int ParseArrayIndex(string value, int count)
    {
        if (!int.TryParse(value, out var index) || index < 0 || index >= count)
        {
            throw new InvalidDataException(
                $"Compact JSON pointer has invalid array index {value}.");
        }

        return index;
    }

    private static bool RemoveArrayIndex(JsonArray array, string value)
    {
        var index = ParseArrayIndex(value, array.Count);
        array.RemoveAt(index);
        return true;
    }

    private static string ChildPath(string parent, string key) =>
        parent + "/" + key.Replace("~", "~0", StringComparison.Ordinal)
            .Replace("/", "~1", StringComparison.Ordinal);

    private static string Unescape(string value) =>
        value.Replace("~1", "/", StringComparison.Ordinal)
            .Replace("~0", "~", StringComparison.Ordinal);

    private static JsonNode PayloadNode(CollectorEventEnvelope envelope) =>
        Node(envelope.Payload);

    private static JsonNode Node(JsonElement value) =>
        JsonNode.Parse(value.GetRawText())
        ?? throw new InvalidDataException("Collector JSON value is null.");

    private static string JsonSha256(JsonNode value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
                value.ToJsonString(JsonOptions))))
            .ToLowerInvariant();

    private static string FileSha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static string EnumName<T>(T value)
        where T : struct, Enum => JsonNamingPolicy.SnakeCaseLower.ConvertName(value.ToString());

    private static string EventName(CollectorEventType value) => value switch
    {
        CollectorEventType.EpisodeStarted => "episode",
        CollectorEventType.Decision => "decision",
        CollectorEventType.ActionSubmitted => "action",
        CollectorEventType.ExecutionResult => "result",
        CollectorEventType.Reward => "reward",
        CollectorEventType.SaveLoad => "save_load",
        CollectorEventType.CoverageGap => "gap",
        CollectorEventType.Diagnostic => "diagnostic",
        CollectorEventType.ManualCombatInput => "manual_input",
        CollectorEventType.ManualCombatInputOutcome => "manual_result",
        CollectorEventType.EpisodeFinished => "finish",
        _ => throw new InvalidDataException($"Unsupported collector event {value}."),
    };

    private sealed record DecisionBase(
        long Step,
        int TimelineGeneration,
        JsonNode Observation,
        JsonNode? Context);

    private sealed record DecisionReference(
        long Step,
        JsonNode Observation,
        JsonNode LegalActions,
        string StateFingerprint);

    private sealed record AttemptReference(
        long Step,
        int Ordinal,
        Guid DecisionId,
        int SelectedActionIndex);

    private sealed record ManualInputReference(
        int Ordinal,
        DecisionReference? Decision,
        AttemptReference? Attempt);

    private sealed class ProjectionState(int checkpointInterval)
    {
        public int CheckpointInterval { get; } = checkpointInterval;
        public int DecisionCount { get; set; }
        public int FullObservationCount { get; set; }
        public int ManualInputCount { get; set; }
        public DecisionBase? LastDecision { get; set; }
        public Dictionary<Guid, long> DecisionSteps { get; } = [];
        public Dictionary<Guid, int> NextAttemptByDecision { get; } = [];
        public Dictionary<Guid, DecisionReference> Decisions { get; } = [];
        public Dictionary<Guid, AttemptReference> Attempts { get; } = [];
        public Dictionary<Guid, ManualInputReference> ManualInputs { get; } = [];

        public void ResetDecisionBases() => LastDecision = null;
    }
}
