using System.Text.Json;
using System.Text.Json.Serialization;

namespace SlayTheModel.Headless;

public sealed record NewRunRequest(
    string Character = "IRONCLAD", int Ascension = 0, string? Seed = null, string Language = "zhs");

public sealed record HeadlessActionRequest(long Revision, string ActionId, string[]? SelectedIds = null);

public sealed class HeadlessState
{
    public long Revision { get; set; }
    public string Status { get; set; } = "starting";
    public string Screen { get; set; } = "startup";
    public string? SurfaceModelId { get; set; }
    public string Title { get; set; } = "Slay the Spire 2";
    public string Description { get; set; } = "正在启动原生游戏环境…";
    public object? Player { get; set; }
    public List<HeadlessEntity> Entities { get; set; } = [];
    public List<HeadlessAction> Actions { get; set; } = [];
    public object? Map { get; set; }
    public object? Board { get; set; }
    public object? Choices { get; set; }
    public List<string> Log { get; set; } = [];
    public string? Error { get; set; }
}

public sealed class HeadlessEntity
{
    public string Id { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Name { get; set; } = "";
    public string? EnName { get; set; }
    public string? ModelId { get; set; }
    public string? Description { get; set; }
    public string? Pile { get; set; }
    public int? Hp { get; set; }
    public int? MaxHp { get; set; }
    public int? Block { get; set; }
    public int? Cost { get; set; }
    public int? StarCost { get; set; }
    public int? Price { get; set; }
    public int? Count { get; set; }
    public int? UpgradeLevel { get; set; }
    public string? EnchantmentId { get; set; }
    public string? Intent { get; set; }
    public object[] Statuses { get; set; } = [];
}

public sealed class HeadlessAction
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public string? EnLabel { get; set; }
    public string Kind { get; set; } = "button";
    public string? EntityId { get; set; }
    public string? TargetId { get; set; }
    public int? X { get; set; }
    public int? Y { get; set; }
    public bool Disabled { get; set; }
    public string? Description { get; set; }
}

public sealed class HeadlessRequestException(int statusCode, string message) : Exception(message)
{
    public int StatusCode { get; } = statusCode;
}

public static class HeadlessJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };
}
