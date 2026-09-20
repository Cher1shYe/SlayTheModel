using System.Diagnostics;
using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

internal sealed class NativeWorkerClient : IDisposable
{
    private Process? _process;
    private string _directory = "";

    public async Task<NativeMctsResponse> SearchAsync(NativeMctsRequest request, CancellationToken cancellation)
    {
        EnsureStarted();
        var input = Path.Combine(_directory, "request.json");
        File.WriteAllText(input + ".tmp", JsonSerializer.Serialize(request));
        File.Move(input + ".tmp", input, true);
        var output = Path.Combine(_directory, $"{request.Id}.json");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(15));
        while (!File.Exists(output))
        {
            if (_process == null || _process.HasExited) throw new IOException("Native worker exited. See its logs.");
            await Task.Delay(20, timeout.Token);
        }
        cancellation.ThrowIfCancellationRequested();
        var response = JsonSerializer.Deserialize<NativeMctsResponse>(File.ReadAllText(output))
            ?? throw new InvalidDataException("Empty worker response.");
        if (response.Id != request.Id) throw new InvalidDataException("Stale worker response.");
        if (response.Error != null) throw new InvalidOperationException(response.Error);
        return response;
    }

    private void EnsureStarted()
    {
        if (_process is { HasExited: false }) return;
        var exe = Environment.GetEnvironmentVariable("SLAY_THE_MODEL_WORKER_EXE")
            ?? throw new InvalidOperationException("Launch mcts through scripts/windows.ps1 after building the native worker.");
        var project = Environment.GetEnvironmentVariable("SLAY_THE_MODEL_WORKER_PROJECT")
            ?? throw new InvalidOperationException("Missing worker project path.");
        _directory = Path.Combine(CombatCaptureService.GetOutputDirectory(), "search", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_directory);
        var start = new ProcessStartInfo(exe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(exe)!,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        start.ArgumentList.Add("--headless");
        start.ArgumentList.Add("--path");
        start.ArgumentList.Add(project);
        start.Environment["STS2_WORKER_MODE"] = "serve";
        start.Environment["STS2_WORKER_INBOX"] = _directory;
        start.Environment["STS2_WORKER_PARENT"] = Environment.ProcessId.ToString();
        start.Environment["STS2_GAME_PACK"] = Environment.GetEnvironmentVariable("STS2_GAME_PACK")
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
