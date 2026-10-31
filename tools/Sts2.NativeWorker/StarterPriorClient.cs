using System.Diagnostics;
using System.Text.Json;

internal sealed class StarterPriorClient : IDisposable
{
    private readonly Process process;
    public string ModelIdentity { get; }
    public long Calls { get; private set; }
    public double EncodeMs { get; private set; }
    public double InferMs { get; private set; }
    public double WallMs { get; private set; }
    public StarterPriorClient(string python, string script, string source, string checkpoint)
    {
        var start = new ProcessStartInfo(python) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true };
        start.Environment["PYTHONUTF8"] = "1";
        foreach (var arg in new[] { "-u", script, "--source", source, "--checkpoint", checkpoint }) start.ArgumentList.Add(arg);
        process = Process.Start(start) ?? throw new IOException("Prior process failed to start.");
        try
        {
            var ready = process.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(30)).GetAwaiter().GetResult()
                ?? throw new IOException("Prior exited during initialization.");
            using var message = JsonDocument.Parse(ready);
            if (!message.RootElement.GetProperty("ready").GetBoolean()) throw new InvalidDataException(ready);
            ModelIdentity = message.RootElement.GetProperty("sha256").GetString()!;
        }
        catch
        {
            // A failed handshake must not leave an orphan inference service.
            Dispose();
            throw;
        }
    }
    public Task<IReadOnlyList<double>> PredictAsync(object observation, CancellationToken cancellation)
        => Task.FromResult<IReadOnlyList<double>>(Request(observation, cancellation)
            .GetProperty("priors").EnumerateArray().Select(p => p.GetDouble()).ToArray());

    public Task<double> ValueAsync(object observation, CancellationToken cancellation, object? expected = null)
    {
        object request = expected == null ? (object)new { operation = "value", observation }
            : new { operation = "value", observation, expected };
        double value = Request(request, cancellation).GetProperty("value").GetDouble();
        if (!double.IsFinite(value) || value < -1 || value > 1)
            throw new InvalidDataException("Native value must be finite in [-1,1]");
        return Task.FromResult(value);
    }

    private JsonElement Request(object observation, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        var watch = Stopwatch.StartNew();
        process.StandardInput.WriteLine(JsonSerializer.Serialize(observation));
        process.StandardInput.Flush();
        // Drain the matching reply even if the search deadline expires, preserving framing.
        var line = process.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult()
            ?? throw new IOException("Prior exited.");
        using var response = JsonDocument.Parse(line);
        if (response.RootElement.TryGetProperty("error", out var error)) throw new InvalidDataException(error.GetString());
        Calls++;
        EncodeMs += response.RootElement.GetProperty("encodeMs").GetDouble();
        InferMs += response.RootElement.GetProperty("inferMs").GetDouble();
        WallMs += watch.Elapsed.TotalMilliseconds;
        return response.RootElement.Clone();
    }
    public void Dispose()
    {
        if (!process.HasExited)
        {
            process.StandardInput.Close();
            if (!process.WaitForExit(3000)) process.Kill(entireProcessTree: true);
        }
        process.Dispose();
    }
}
