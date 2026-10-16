using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Potions;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.ScreenContext;
using MegaCrit.Sts2.Core.Runs;
using Environment = System.Environment;

namespace SlayTheModel.Headless;

/// <summary>
/// Decision transport over the current native session. UI clients never own a
/// second simulation. All captures and commands run on the Godot main thread.
/// </summary>
public sealed partial class NativeGameBridge
{
    private sealed record Binding(string Identity, HeadlessAction Display, Func<string[]?, Task> Execute);
    private sealed class EntityIdentity(string value) { public string Value { get; } = value; }
    private readonly Node _host;
    private readonly Func<NewRunRequest, Task> _startNewRun;
    private readonly ConcurrentQueue<Action> _commands = new();
    private readonly ConditionalWeakTable<object, EntityIdentity> _entities = new();
    private readonly List<string> _log = [];
    private readonly List<Task> _pending = [];
    private List<Binding> _bindings = [];
    private HeadlessState _state = new();
    private string _latestJson;
    private string _signature = "";
    private long _revision;
    private long _nextCapture;
    private long _inputCooldown;
    private bool _starting;
    private string? _error;
    private string? _captureError;

    public NativeGameBridge(Node host, Func<NewRunRequest, Task> startNewRun)
    {
        _host = host;
        _startNewRun = startNewRun;
        _latestJson = JsonSerializer.Serialize(_state, HeadlessJson.Options);
    }

    public string LatestJson => Volatile.Read(ref _latestJson);

    public Task<string> EnqueueNewRun(NewRunRequest request) => Enqueue(() =>
    {
        if (_starting) throw new HeadlessRequestException(409, "新局正在启动，请稍候。");
        if (request.Ascension is < 0 or > 10) throw new HeadlessRequestException(400, "进阶须在 0–10 之间。");
        if (request.Language is not ("zhs" or "eng")) throw new HeadlessRequestException(400, "语言须为 zhs 或 eng。");
        if (request.Seed?.Length > 128) throw new HeadlessRequestException(400, "种子过长。");
        if (_pending.Any(task => !task.IsCompleted))
            throw new HeadlessRequestException(409, "当前原生操作尚未完成。请先完成选择，或重新启动终端会话。");
        _starting = true;
        _error = null;
        _log.Clear();
        Observe(StartAsync(request), "开始新局");
        Capture();
        return LatestJson;
    });

    private async Task StartAsync(NewRunRequest request)
    {
        try { await _startNewRun(request); }
        finally { _starting = false; _nextCapture = 0; }
    }

    public Task<string> EnqueueAction(HeadlessActionRequest request) => Enqueue(() =>
    {
        Capture();
        if (request.Revision != _revision)
            throw new HeadlessRequestException(409, "状态已变化，请根据最新菜单重新选择。");
        if (_starting || Environment.TickCount64 < _inputCooldown)
            throw new HeadlessRequestException(409, "原生操作正在启动，请稍候。");
        var binding = _bindings.SingleOrDefault(candidate => candidate.Display.Id == request.ActionId);
        if (binding is null || binding.Display.Disabled)
            throw new HeadlessRequestException(409, "该操作不在当前合法菜单中。");
        _error = null;
        _inputCooldown = Environment.TickCount64 + 120;
        Log(binding.Display.Label);
        Observe(binding.Execute(request.SelectedIds), binding.Display.Label);
        Capture();
        return LatestJson;
    });

    private Task<string> Enqueue(Func<string> command)
    {
        var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (_commands.Count >= 32)
        {
            completion.SetException(new HeadlessRequestException(429, "请求过多，请等待当前操作。"));
            return completion.Task;
        }
        _commands.Enqueue(() =>
        {
            try { completion.SetResult(command()); }
            catch (Exception error) { completion.SetException(error); }
        });
        return completion.Task;
    }

    public void Tick()
    {
        while (_commands.TryDequeue(out var command)) command();
        _pending.RemoveAll(task => task.IsCompleted);
        if (Environment.TickCount64 >= _nextCapture)
        {
            _nextCapture = Environment.TickCount64 + 150;
            Capture();
        }
    }

    private void Observe(Task task, string label)
    {
        _pending.Add(task);
        _ = ObserveAsync(task, label);
    }

    private async Task ObserveAsync(Task task, string label)
    {
        try
        {
            await task;
            if (task is Task<bool> result && !result.Result) Log(label + "：原生游戏未执行或已取消。");
        }
        catch (Exception error)
        {
            _error = label + "：" + error.Message;
            GD.PrintErr("HEADLESS_ACTION_FAILED " + error);
            Log(_error);
        }
        finally { _nextCapture = 0; }
    }

    private void Capture()
    {
        try
        {
            var frame = new HeadlessState { Status = "ready", Title = "杀戮尖塔 2", Log = [.. _log], Error = _error };
            var bindings = new List<Binding>();
            if (_starting)
            {
                frame.Status = "starting";
                frame.Description = "正在创建原生整局…";
            }
            else
            {
                CapturePlayer(frame);
                Node? surface = ActiveScreenContext.Instance.GetCurrentScreen() as Node;
                bool hasModal = NModalContainer.Instance?.OpenModal is not null;
                var popup = hasModal ? null : NativeView.Nodes(_host.GetTree().Root).OfType<NPotionPopup>()
                    .LastOrDefault(node => NativeView.Visible(node) && !node.IsMarkedForRemoval);
                if (popup is not null) surface = popup;
                var targetManager = NRun.Instance?.GlobalUi.TargetManager;
                if (!hasModal && targetManager is { IsInSelection: true } targeting)
                    CaptureTargets(frame, bindings, targeting);
                else if (surface is not null && NativeView.Visible(surface))
                    CaptureSurface(frame, bindings, surface);
                else
                {
                    frame.Screen = "transition";
                    frame.Title = NRun.Instance is null ? "准备开始" : "原生游戏正在切换场景";
                    frame.Description = NRun.Instance is null ? "输入 new 开始一局。" : "等待下一个原生决策点…";
                }
                if (NRun.Instance is not null && popup is null && NModalContainer.Instance?.OpenModal is null
                    && targetManager?.IsInSelection != true && NPlayerHand.Instance?.IsInCardSelection != true)
                    CapturePotionOpenActions(frame, bindings);
                if (frame.Actions.Count == 0 && NRun.Instance is not null && frame.Status == "ready") frame.Status = "busy";
            }
            if (NativeSmokeScenario.ConfiguredName is { } scenario)
                frame.Description = $"【接口测试场景：{scenario}；非自然整局轨迹】\n" + frame.Description;
            if (Environment.TickCount64 < _inputCooldown)
            {
                frame.Status = "busy";
                foreach (var action in frame.Actions) action.Disabled = true;
            }
            string signature = JsonSerializer.Serialize(frame, HeadlessJson.Options)
                + string.Join("|", bindings.Select(binding => binding.Identity));
            if (signature != _signature)
            {
                _signature = signature;
                _revision++;
            }
            frame.Revision = _revision;
            _captureError = null;
            _state = frame;
            _bindings = bindings;
            Volatile.Write(ref _latestJson, JsonSerializer.Serialize(frame, HeadlessJson.Options));
        }
        catch (Exception error)
        {
            string message = "状态读取失败：" + error.Message;
            if (_captureError != message) GD.PrintErr("HEADLESS_CAPTURE_FAILED " + error);
            _captureError = message;
            _bindings.Clear();
            _state = new HeadlessState { Revision = ++_revision, Status = "error", Error = message, Log = [.. _log] };
            Volatile.Write(ref _latestJson, JsonSerializer.Serialize(_state, HeadlessJson.Options));
        }
    }

    private void Add(HeadlessState frame, List<Binding> bindings, string key, string label,
        Func<Task> execute, string kind = "button", string? entityId = null, string? targetId = null,
        string? description = null, string? enLabel = null, int? x = null, int? y = null, bool disabled = false)
    {
        var display = new HeadlessAction { Id = "a" + bindings.Count, Label = label, Kind = kind,
            EntityId = entityId, TargetId = targetId, Description = description, EnLabel = enLabel,
            X = x, Y = y, Disabled = disabled };
        frame.Actions.Add(display);
        bindings.Add(new Binding(key, display, _ => execute()));
    }

    // Opaque, process-local labels must not encode the order in which a hidden
    // pile was traversed. This uses OS randomness, never the game's RNG.
    private string Identity(object value) => _entities.GetValue(value, _ => new EntityIdentity("e" + Guid.NewGuid().ToString("N"))).Value;
    private HeadlessEntity DescribeCard(CardModel card, string? pile = null) => NativeView.Card(card, Identity(card), pile);

    private void Log(string message)
    {
        _log.Add(message);
        if (_log.Count > 20) _log.RemoveAt(0);
    }
}
