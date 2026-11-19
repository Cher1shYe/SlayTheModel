using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine;

namespace SlayTheModel.Headless;

// Audit-only raw getters/intent construction. No move is executed and no model
// fields, combat state, or ascension rules are patched to make values readable.
internal static class NativeMonsterNumbersExport
{
    private static object? Read(Func<object?> read)
    {
        try { return read(); }
        catch (Exception error)
        {
            while (error is TargetInvocationException && error.InnerException is { } inner) error = inner;
            return new { error = error.GetType().Name, message = error.Message };
        }
    }
    private static bool Numeric(Type type) => type == typeof(int) || type == typeof(decimal)
        || type == typeof(float) || type == typeof(double) || type == typeof(short) || type == typeof(byte);
    private static object Members(MonsterModel monster)
    {
        var result = new SortedDictionary<string, object?>();
        for (Type? type = monster.GetType(); type is not null && type != typeof(MonsterModel); type = type.BaseType)
        {
            const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
            foreach (var prop in type.GetProperties(flags).Where(prop => Numeric(prop.PropertyType) && prop.GetIndexParameters().Length == 0 && prop.GetMethod is not null))
                result[type.Name + "." + prop.Name] = Read(() => prop.GetValue(monster));
            foreach (var field in type.GetFields(flags).Where(field => Numeric(field.FieldType) && !field.Name.Contains("k__BackingField")))
                result[type.Name + "." + field.Name] = Read(() => field.GetValue(monster));
        }
        return result;
    }
    private static object? Moves(MonsterModel monster) => Read(() =>
    {
        var method = monster.GetType().GetMethod("GenerateMoveStateMachine", BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new MissingMethodException(monster.GetType().Name, "GenerateMoveStateMachine");
        var machine = (MonsterMoveStateMachine)method.Invoke(monster, null)!;
        return machine.States.Values.OfType<MoveState>().OrderBy(move => move.Id, StringComparer.Ordinal).Select(move => new
        {
            id = move.Id,
            intents = move.Intents.Select(intent => new
            {
                type = intent.GetType().Name,
                damage = intent is AttackIntent attack ? Read(() => attack.DamageCalc!()) : null,
                hits = intent is AttackIntent repeat ? Read(() => repeat.Repeats) : null,
                statusCount = intent is StatusIntent status ? (object)status.CardCount : null,
            }).ToArray(),
        }).ToArray();
    });
    private static object Capture(int ascension) => new
    {
        ascension,
        monsters = ModelDb.Monsters.OrderBy(monster => monster.Id.Entry, StringComparer.Ordinal).Select(original =>
        {
            var monster = original.ToMutable();
            var members = Members(monster);
            return new { id = original.Id.Entry, className = monster.GetType().Name, members, moves = Moves(monster) };
        }).ToArray(),
    };
    internal static async Task WriteAsync(string path, int ascension)
    {
        if (ascension < 0 || ascension > 10) throw new ArgumentOutOfRangeException(nameof(ascension));
        var before = Capture(0);
        await NativeBootstrap.StartNewRunAsync("IRONCLAD", ascension, "MONSTERNUMBERS0001", "eng");
        var result = new
        {
            schema = "sts2.monster-numbers/1", gameVersion = NativeBootstrap.GameVersion,
            gameCommit = NativeBootstrap.GameCommit, gameDllSha256 = NativeBootstrap.GameDllSha256,
            context = "Fresh mutable models, no Creature or encounter state; before run=A0, after=ordinary Ironclad run. Stateful getter failures are preserved. This is not move execution parity.",
            beforeRun = before, run = Capture(ascension),
        };
        File.WriteAllText(path, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }) + "\n");
        Godot.GD.Print("SLAY_HEADLESS_MONSTER_NUMBERS " + path);
    }
}
