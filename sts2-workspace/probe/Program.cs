using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

var byName = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
void AddDir(string dir)
{
    if (!Directory.Exists(dir)) return;
    foreach (var f in Directory.GetFiles(dir, "*.dll"))
    {
        var n = Path.GetFileName(f);
        if (!byName.ContainsKey(n)) byName[n] = Path.GetFullPath(f);
    }
}
var gameDir = Environment.GetEnvironmentVariable("STS2_GAME_DIR")
              ?? @"D:/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64";
AddDir(gameDir);                                              // real engine deps first
AddDir("../sts2-cli/lib");                                    // patched sts2.dll + friends
AddDir("../sts2-cli/src/Sts2Headless/bin/Debug/net9.0");      // GodotStubs fallback
AddDir(RuntimeEnvironment.GetRuntimeDirectory());             // .NET runtime last
Console.WriteLine($"resolver roots: {byName.Count} unique assemblies");

using var mlc = new MetadataLoadContext(new PathAssemblyResolver(byName.Values));
var asm = mlc.LoadFromAssemblyPath(Path.GetFullPath("../sts2-cli/lib/sts2.dll"));
var all = asm.GetTypes();
Console.WriteLine($"sts2.dll types: {all.Length}\n");

string N(Type t) => t.IsGenericType ? t.Name.Split('`')[0] + "<" + string.Join(",", t.GetGenericArguments().Select(N)) + ">" : t.Name;
string Sig(MethodBase m) =>
    $"{(m.IsStatic ? "static " : "")}{(m is MethodInfo mi ? N(mi.ReturnType) : "ctor")} {m.Name}(" +
    string.Join(", ", m.GetParameters().Select(p => N(p.ParameterType))) + ")";
const BindingFlags P = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly;

// ---- 1. every type whose name mentions CombatState ----
Console.WriteLine("=== types matching *CombatState* ===");
foreach (var t in all.Where(t => t.Name.Contains("CombatState")).OrderBy(t => t.FullName))
    Console.WriteLine($"   {t.FullName}   [{(t.IsValueType ? "struct" : "class")}]");

// ---- 2. NetFullCombatState full surface ----
var nf = all.FirstOrDefault(t => t.Name == "NetFullCombatState");
Console.WriteLine($"\n=== NetFullCombatState fields + methods ===");
if (nf != null)
{
    foreach (var f in nf.GetFields(P)) Console.WriteLine($"   field {N(f.FieldType)} {f.Name}");
    foreach (var m in nf.GetMethods(P).OrderBy(m => m.Name)) Console.WriteLine($"   {Sig(m)}");
}

// ---- 3. clone / restore / apply anywhere in the engine ----
Console.WriteLine("\n=== ALL engine methods named *Clone*/*Snapshot*/*Restore*/*Apply* (top 60) ===");
var hits = all.SelectMany(t => t.GetMethods(P).Select(m => (t, m)))
              .Where(x => Regex.IsMatch(x.m.Name, "^(Mutable)?Clone$|Snapshot|Restore|Apply.*State|FromNet|ToNet"))
              .Select(x => $"{x.t.Name}.{Sig(x.m)}")
              .Distinct().OrderBy(s => s).Take(60);
foreach (var h in hits) Console.WriteLine($"   {h}");

// ---- 4. the real combat state holder ----
var cs = all.FirstOrDefault(t => t.Name == "CombatState");
Console.WriteLine($"\n=== {cs?.FullName} ===");
if (cs != null)
{
    Console.WriteLine("  properties:");
    foreach (var p in cs.GetProperties(BindingFlags.Public | BindingFlags.Instance).OrderBy(p => p.Name))
        Console.WriteLine($"     {N(p.PropertyType)} {p.Name} {(p.CanWrite ? "{get;set;}" : "{get;}")}");
    Console.WriteLine("  all declared methods:");
    foreach (var m in cs.GetMethods(P).OrderBy(m => m.Name)) Console.WriteLine($"     {Sig(m)}");
}

// ---- 4b. PlayerCombatState / Creature / CardPile ----
void DumpProps(string full)
{
    var t = all.FirstOrDefault(x => x.FullName == full || x.Name == full);
    if (t == null) { Console.WriteLine($"
=== {full}: MISSING ==="); return; }
    Console.WriteLine($"
=== {t.FullName} ===");
    foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance).OrderBy(p => p.Name))
        Console.WriteLine($"   prop {N(p.PropertyType)} {p.Name}");
    foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance).OrderBy(f => f.Name))
        Console.WriteLine($"   field {N(f.FieldType)} {f.Name}");
}
DumpProps("MegaCrit.Sts2.Core.Entities.Players.PlayerCombatState");
DumpProps("MegaCrit.Sts2.Core.Entities.Creatures.Creature");
DumpProps("MegaCrit.Sts2.Core.Entities.Cards.CardPile");
DumpProps("MegaCrit.Sts2.Core.Entities.Cards.CardModel");

// ---- 5. RunManager save/restore surface ----
var rm = all.FirstOrDefault(t => t.Name == "RunManager");
Console.WriteLine($"\n=== RunManager: save/load/divergence ===");
if (rm != null)
    foreach (var m in rm.GetMethods(P).Where(m => Regex.IsMatch(m.Name, "Save|Load|Diverg|Rejoin|Restore|ToSave|FromSave")))
        Console.WriteLine($"   {Sig(m)}");
