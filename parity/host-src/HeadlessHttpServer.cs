using System.Net;
using System.Text;
using System.Text.Json;

namespace SlayTheModel.Headless;

/// <summary>Loopback transport only. The bridge dispatches every Godot operation on its main thread.</summary>
public sealed class HeadlessHttpServer : IDisposable
{
    private readonly HttpListener _listener = new();
    private readonly NativeGameBridge _bridge;
    private readonly string _origin;
    private readonly CancellationTokenSource _stop = new();

    public HeadlessHttpServer(NativeGameBridge bridge, int port)
    {
        if (port is < 1024 or > 65535) throw new ArgumentOutOfRangeException(nameof(port));
        _bridge = bridge;
        _origin = $"http://127.0.0.1:{port}";
        _listener.Prefixes.Add(_origin + "/");
    }

    public string Url => _origin;

    public void Start()
    {
        _listener.Start();
        _ = AcceptAsync();
    }

    private async Task AcceptAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            try
            {
                var context = await _listener.GetContextAsync().WaitAsync(_stop.Token);
                _ = ServeAsync(context);
            }
            catch (Exception) when (_stop.IsCancellationRequested) { break; }
        }
    }

    private async Task ServeAsync(HttpListenerContext context)
    {
        try
        {
            var request = context.Request;
            context.Response.Headers["Cache-Control"] = "no-store";
            context.Response.Headers["X-Content-Type-Options"] = "nosniff";
            if (request.Url?.Authority != new Uri(_origin).Authority)
                throw new HeadlessRequestException(403, "Invalid local host.");
            string path = request.Url.AbsolutePath;
            if (request.HttpMethod == "GET" && path == "/api/state")
            {
                await WriteAsync(context, 200, _bridge.LatestJson);
            }
            else if (request.HttpMethod == "GET" && path == "/api/health")
            {
                await WriteAsync(context, 200, JsonSerializer.Serialize(new { ok = true, pid = Environment.ProcessId }, HeadlessJson.Options));
            }
            else if (request.HttpMethod == "POST" && path is "/api/new" or "/api/action")
            {
                if (request.Headers["Origin"] is { } origin && origin != _origin)
                    throw new HeadlessRequestException(403, "Cross-origin game commands are not accepted.");
                if (request.ContentType?.StartsWith("application/json", StringComparison.OrdinalIgnoreCase) != true)
                    throw new HeadlessRequestException(415, "Expected application/json.");
                if (request.ContentLength64 is < 0 or > 16384)
                    throw new HeadlessRequestException(413, "Request is too large.");
                using var reader = new StreamReader(request.InputStream, Encoding.UTF8);
                string body = await reader.ReadToEndAsync(_stop.Token);
                string result = path == "/api/new"
                    ? await _bridge.EnqueueNewRun(JsonSerializer.Deserialize<NewRunRequest>(body, HeadlessJson.Options)
                        ?? throw new HeadlessRequestException(400, "Missing new-run request."))
                    : await _bridge.EnqueueAction(JsonSerializer.Deserialize<HeadlessActionRequest>(body, HeadlessJson.Options)
                        ?? throw new HeadlessRequestException(400, "Missing action request."));
                await WriteAsync(context, 200, result);
            }
            else throw new HeadlessRequestException(404, "Unknown endpoint.");
        }
        catch (Exception error)
        {
            int status = error is HeadlessRequestException rejected ? rejected.StatusCode
                : error is JsonException ? 400 : 500;
            try { await WriteAsync(context, status, JsonSerializer.Serialize(new { error = error.Message }, HeadlessJson.Options)); }
            catch (Exception) { /* The client can disconnect while a native action is starting. */ }
        }
        finally { context.Response.Close(); }
    }

    private static async Task WriteAsync(HttpListenerContext context, int status, string json)
    {
        context.Response.StatusCode = status;
        context.Response.ContentType = "application/json; charset=utf-8";
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        context.Response.ContentLength64 = bytes.Length;
        await context.Response.OutputStream.WriteAsync(bytes);
    }

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Close();
        _stop.Dispose();
    }
}
