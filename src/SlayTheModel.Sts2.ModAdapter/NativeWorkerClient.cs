using System.Diagnostics;
using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

internal sealed class NativeWorkerClient : IDisposable
{
    private Process? _process;
    private string _directory = "";
    private long _requestSequence;

    public async Task<NativeMctsResponse> SearchAsync(NativeMctsRequest request, CancellationToken cancellation)
    {
        EnsureStarted();
        var sequence = Interlocked.Increment(ref _requestSequence);
        var input = Path.Combine(_directory, $"{sequence:D20}-{request.Id:N}.request.json");
        File.WriteAllText(input + ".tmp", JsonSerializer.Serialize(request));
        File.Move(input + ".tmp", input);
        var output = Path.Combine(_directory, $"{request.Id}.json");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(15));
        NativeMctsResponse? response = null;
        while (response == null)
        {
            if (_process == null || _process.HasExited) throw new IOException("Native worker exited. See its logs.");
            if (File.Exists(output))
            {
                try { response = JsonSerializer.Deserialize<NativeMctsResponse>(File.ReadAllText(output)); }
                catch (IOException) { /* Retry transient Windows file sharing conflicts. */ }
            }
            if (response != null) break;
            await Task.Delay(20, timeout.Token);
        }
        cancellation.ThrowIfCancellationRequested();
        if (response.Id != request.Id) throw new InvalidDataException("Stale worker response.");
        if (response.Error != null) throw new InvalidOperationException(response.Error);
        return response;
    }

    private void EnsureStarted()
    {
        if (_process is { HasExited: false }) return;
        var exe = RuntimeConfiguration.Get("SLAY_THE_MODEL_WORKER_EXE")
            ?? throw new InvalidOperationException("MCTS worker path is not configured. Run windows.ps1 -Action Install or Launch.");
        var project = RuntimeConfiguration.Get("SLAY_THE_MODEL_WORKER_PROJECT")
            ?? throw new InvalidOperationException("MCTS worker project path is not configured. Run windows.ps1 -Action Install or Launch.");
        _directory = Path.Combine(CombatCaptureService.GetOutputDirectory(), "search", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_directory);
        var start = new ProcessStartInfo(exe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(exe)!,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        NativeWorkerLaunch.IsolateFromGameProcess(start);
        start.ArgumentList.Add("--headless");
        start.ArgumentList.Add("--path");
        start.ArgumentList.Add(project);
        start.Environment["STS2_WORKER_MODE"] = "serve";
        start.Environment["STS2_WORKER_INBOX"] = _directory;
        start.Environment["STS2_WORKER_PARENT"] = Environment.ProcessId.ToString();
        start.Environment["STS2_GAME_PACK"] = RuntimeConfiguration.Get("STS2_GAME_PACK")
            ?? Path.Combine(Path.GetDirectoryName(Environment.ProcessPath)!, "SlayTheSpire2.pck");
        _process = new Process { StartInfo = start };
        var directory = _directory;
        _process.OutputDataReceived += (_, args) => { if (args.Data != null) File.AppendAllText(Path.Combine(directory, "stdout.log"), args.Data + Environment.NewLine); };
        _process.ErrorDataReceived += (_, args) => { if (args.Data != null) File.AppendAllText(Path.Combine(directory, "stderr.log"), args.Data + Environment.NewLine); };
        _process.Start();
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
    }

    public void Dispose()
    {
        if (_process is { HasExited: false }) _process.Kill(entireProcessTree: true);
        _process?.Dispose();
        _process = null;
    }
}
