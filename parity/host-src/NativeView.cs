using System.Collections;
using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;
using Godot;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;

namespace SlayTheModel.Headless;

/// <summary>Explicit display projection. Never serializes native objects or their private object graphs.</summary>
internal static partial class NativeView
{
    private const BindingFlags Declared = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
    private static readonly Dictionary<string, Dictionary<string, string>> EnglishTables = [];

    internal static object? Get(object? value, string member)
    {
        if (value is null) return null;
        for (var type = value.GetType(); type is not null; type = type.BaseType)
        {
            var property = type.GetProperty(member, Declared);
            if (property is not null && property.GetIndexParameters().Length == 0) return property.GetValue(value);
            var field = type.GetField(member, Declared);
            if (field is not null) return field.GetValue(value);
        }
        return null;
    }

    internal static object? Invoke(object value, string name, params object?[] arguments)
    {
        for (var type = value.GetType(); type is not null; type = type.BaseType)
        {
            var methods = type.GetMethods(Declared).Where(method => method.Name == name
                && method.GetParameters().Length == arguments.Length
                && method.GetParameters().Select((p, i) => arguments[i] is null
                    ? !p.ParameterType.IsValueType || Nullable.GetUnderlyingType(p.ParameterType) is not null
                    : p.ParameterType.IsInstanceOfType(arguments[i])).All(matches => matches)).ToArray();
            if (methods.Length == 1)
            {
                try { return methods[0].Invoke(value, arguments); }
                catch (TargetInvocationException error) { throw error.InnerException ?? error; }
            }
            if (methods.Length > 1) throw new AmbiguousMatchException($"Ambiguous native entry: {type.Name}.{name}");
        }
        throw new MissingMethodException(value.GetType().FullName, name);
    }

    internal static IEnumerable<object> Items(object? values) => values is IEnumerable sequence
        ? sequence.Cast<object>() : [];

    internal static IEnumerable<Node> Nodes(Node root)
    {
        if (!GodotObject.IsInstanceValid(root) || root.IsQueuedForDeletion()) yield break;
        yield return root;
        foreach (Node child in root.GetChildren())
            foreach (var node in Nodes(child)) yield return node;
    }

    internal static bool Visible(Node node) => GodotObject.IsInstanceValid(node)
        && !node.IsQueuedForDeletion() && node.IsInsideTree()
        && (node is not CanvasItem item || item.IsVisibleInTree());

    internal static bool Enabled(NClickableControl control) => Visible(control) && control.IsEnabled;

    internal static string Text(object? value)
    {
        if (value is null) return "";
        string text = value switch
        {
            string plain => plain,
            LocString loc => loc.GetFormattedText(),
            _ => value.ToString() ?? "",
        };
        return Tags().Replace(Images().Replace(text, "◆"), "").Trim();
    }

    internal static string NodeText(Node node) => string.Join("\n", Nodes(node).Where(Visible)
        .Select(child => child switch { RichTextLabel rich => Text(rich.Text), Label label => Text(label.Text), _ => "" })
        .Where(text => text.Length > 0).Distinct());

    internal static string ModelName(AbstractModel model) => model is CardModel card ? Text(card.Title)
        : Text(Get(model, "Title") ?? Get(model, "TitleLocString") ?? Get(model, "Name") ?? model.Id.Entry);

    internal static string English(AbstractModel model)
    {
        string table = model.Id.Category.ToString().ToLowerInvariant() switch
        {
            "card" => "cards", "relic" => "relics", "potion" => "potions", "power" => "powers",
            "monster" => "monsters", "character" => "characters", "event" => "events", _ => "",
        };
        if (Get(model, "Title") is LocString loc) return English(loc, model.Id.Entry);
        if (model is CardModel c) return English(c.TitleLocString, model.Id.Entry)
            + (c.CurrentUpgradeLevel > 0 ? "+" + (c.CurrentUpgradeLevel > 1 ? c.CurrentUpgradeLevel : "") : "");
        return English(new LocString(table, model.Id.Entry + ".title"), model.Id.Entry);
    }

    internal static string English(LocString loc, string fallback)
    {
        if (!EnglishTables.TryGetValue(loc.LocTable, out var table))
        {
            string path = $"res://localization/eng/{loc.LocTable}.json";
            table = Godot.FileAccess.FileExists(path)
                ? JsonSerializer.Deserialize<Dictionary<string, string>>(Godot.FileAccess.GetFileAsString(path)) ?? [] : [];
            EnglishTables[loc.LocTable] = table;
        }
        return table.TryGetValue(loc.LocEntryKey, out string? text) ? Text(text) : fallback;
    }

    internal static HeadlessEntity Card(CardModel card, string id, string? pile = null) => new()
    {
        Id = id, Kind = "card", Name = Text(card.Title), EnName = English(card), ModelId = card.Id.ToString(),
        UpgradeLevel = card.CurrentUpgradeLevel, EnchantmentId = card.Enchantment?.Id.ToString(),
        Description = Text(card.GetDescriptionForPile(card.Pile?.Type ?? PileType.None)),
        Cost = card.EnergyCost.CostsX ? -1 : card.EnergyCost.GetWithModifiers(CostModifiers.All),
        StarCost = card.HasStarCostX ? -1 : card.GetStarCostWithModifiers() is var starCost && starCost >= 0 ? starCost : null,
        Pile = pile,
    };

    [GeneratedRegex(@"\[img[^\]]*\].*?\[/img\]", RegexOptions.Singleline)]
    private static partial Regex Images();
    [GeneratedRegex(@"\[/?[^\]]+\]")]
    private static partial Regex Tags();
}
