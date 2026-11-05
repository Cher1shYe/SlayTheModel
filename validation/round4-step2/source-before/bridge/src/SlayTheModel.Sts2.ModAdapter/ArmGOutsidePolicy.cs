using System.Diagnostics;
using System.Text.Json;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>One resident Python scorer. Only public, frozen decisions cross this boundary.</summary>
internal sealed class ArmGOutsidePolicy : IOutsideCombatPolicy, IDisposable
{
    private readonly string _python;
    private readonly string _server;
    private readonly string _checkpoint;
    private readonly string _sts2Root;
    private readonly string _simulator;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private Process? _process;
    private bool _disposed;

    public string PolicyId => "armg";
    internal bool AutoMode { get; }
    internal bool AllowApproximate { get; }

    internal ArmGOutsidePolicy()
    {
        _python = Required("SLAY_THE_MODEL_ARMG_PYTHON");
        _server = Required("SLAY_THE_MODEL_ARMG_SERVER");
        _checkpoint = Required("SLAY_THE_MODEL_ARMG_CHECKPOINT");
        _sts2Root = Required("SLAY_THE_MODEL_ARMG_STS2_ROOT");
        _simulator = Required("SLAY_THE_MODEL_ARMG_SIMULATOR");
        var mode = (RuntimeConfiguration.Get("SLAY_THE_MODEL_ARMG_MODE") ?? "shadow").Trim().ToLowerInvariant();
        if (mode is not ("shadow" or "auto"))
            throw new InvalidDataException("SLAY_THE_MODEL_ARMG_MODE must be shadow or auto.");
        AutoMode = mode == "auto";
        AllowApproximate = RuntimeConfiguration.Get("SLAY_THE_MODEL_ARMG_ALLOW_APPROXIMATE") == "1";
    }

    private static string Required(string name)
    {
        var value = RuntimeConfiguration.Get(name);
        return !string.IsNullOrWhiteSpace(value) ? value :
            throw new InvalidDataException($"{name} must be configured for ArmG.");
    }

    // The controller starts this work on a background thread and polls it on
    // subsequent frames. No game objects are accessed by the worker.
    internal async Task<ArmGResponse> SelectAsync(OutsideCombatDecisionPoint decision)
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            EnsureStarted();
            var requestId = Guid.NewGuid().ToString("N");
            var request = ProtocolJson.Serialize(new { RequestId = requestId, Decision = decision });
            await _process!.StandardInput.WriteLineAsync(request).ConfigureAwait(false);
            await _process.StandardInput.FlushAsync().ConfigureAwait(false);
            var line = await _process.StandardOutput.ReadLineAsync()
                .WaitAsync(TimeSpan.FromSeconds(60)).ConfigureAwait(false);
            if (line is null) throw new EndOfStreamException("ArmG worker exited before replying.");
            var response = JsonSerializer.Deserialize<ArmGResponse>(line, ProtocolJson.Options)
                ?? throw new InvalidDataException("ArmG worker returned an empty response.");
            if (response.RequestId != requestId || response.StateFingerprint != decision.StateFingerprint)
                throw new InvalidDataException("ArmG worker returned a mismatched request or fingerprint.");
            if (response.Status is not ("ok" or "unsupported" or "error"))
                throw new InvalidDataException("ArmG worker returned an unknown status.");
            if (response.Status == "ok" && string.IsNullOrWhiteSpace(response.ActionId))
                throw new InvalidDataException("ArmG worker did not return an action ID.");
            if (response.Status == "ok" && response.Approximate is null)
                throw new InvalidDataException("ArmG worker did not declare whether its features are approximate.");
            if (response.Status == "ok" && (response.Scores is null
                || response.Scores.Count != decision.LegalActions.Count
                || response.Scores.Any(score => !float.IsFinite(score))))
                throw new InvalidDataException("ArmG worker returned invalid action scores.");
            return response;
        }
        catch
        {
            StopWorker();
            throw;
        }
        finally { _gate.Release(); }
    }

    private void EnsureStarted()
    {
        if (_process is { HasExited: false }) return;
        StopWorker();
        var start = new ProcessStartInfo(_python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = _sts2Root,
        };
        start.ArgumentList.Add("-u");
        start.ArgumentList.Add(_server);
        start.ArgumentList.Add("--checkpoint"); start.ArgumentList.Add(_checkpoint);
        start.ArgumentList.Add("--sts2-root"); start.ArgumentList.Add(_sts2Root);
        start.ArgumentList.Add("--simulator"); start.ArgumentList.Add(_simulator);
        NativeWorkerLaunch.IsolateFromGameProcess(start);
        _process = Process.Start(start) ?? throw new IOException("Failed to launch ArmG worker.");
        _process.ErrorDataReceived += (_, eventArgs) =>
        {
            if (!string.IsNullOrWhiteSpace(eventArgs.Data))
                Console.Error.WriteLine($"[SlayTheModel ArmG] {eventArgs.Data}");
        };
        _process.BeginErrorReadLine();
    }

    private void StopWorker()
    {
        var process = _process;
        _process = null;
        if (process is null) return;
        try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
        process.Dispose();
    }

    public OutsideCombatActionDescriptor SelectAction(OutsideCombatDecisionPoint decision) =>
        throw new NotSupportedException("ArmG requires asynchronous inference.");

    public void Dispose()
    {
        _disposed = true;
        StopWorker();
    }
}

internal sealed record ArmGResponse(
    string RequestId,
    string Status,
    string? ActionId,
    string StateFingerprint,
    string? Reason,
    bool? Approximate,
    IReadOnlyList<string>? MissingFeatures,
    IReadOnlyList<float>? Scores,
    IReadOnlyList<OutsideSelectedCardReference>? SelectedCards = null);

internal static class ArmGDecisionGuard
{
    // A null result means leave the current screen to the human player.
    internal static OutsideCombatActionDescriptor? Select(
        OutsideCombatDecisionPoint decision, ArmGResponse response,
        bool autoMode, bool allowApproximate)
    {
        if (response.StateFingerprint != decision.StateFingerprint)
            throw new InvalidDataException("ArmG response belongs to a stale decision.");
        if (response.Status == "unsupported") return null;
        if (response.Status != "ok")
            throw new InvalidDataException($"ArmG inference failed: {response.Reason}");
        if (response.Approximate is null)
            throw new InvalidDataException("ArmG worker did not declare approximation status.");
        var selected = decision.LegalActions.SingleOrDefault(action => action.ActionId == response.ActionId)
            ?? throw new InvalidDataException("ArmG returned an action not legal in the current state.");
        if (selected.IsSelectionTemplate)
        {
            if (response.SelectedCards is null)
                throw new InvalidDataException("ArmG returned an unresolved selection template.");
            var concrete = selected with { IsSelectionTemplate = false, SelectedCards = response.SelectedCards };
            OutsideCombatDecisionPoint.ValidateSubmittedSetAction(decision.Observation, selected, concrete);
            selected = concrete;
        }
        else if (response.SelectedCards is not null)
            throw new InvalidDataException("ArmG returned a subset for a non-template action.");
        return autoMode && (response.Approximate != true || allowApproximate) ? selected : null;
    }
}
