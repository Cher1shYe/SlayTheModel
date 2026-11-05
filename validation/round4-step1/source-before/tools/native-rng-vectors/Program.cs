using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

if (args.Length != 1) throw new ArgumentException("Pass the absolute path to the native sts2.dll oracle.");
string dll = Path.GetFullPath(args[0]);
string dir = Path.GetDirectoryName(dll);
AssemblyLoadContext.Default.Resolving += (_, n) => {
    string path = Path.Combine(dir, n.Name + ".dll");
    return File.Exists(path) ? Assembly.LoadFrom(path) : null;
};
Assembly asm = Assembly.LoadFrom(dll);
Type rngType = asm.GetType("MegaCrit.Sts2.Core.Random.Rng", true);
Type hashType = asm.GetType("MegaCrit.Sts2.Core.Helpers.StringHelper", true);
Type seedType = asm.GetType("MegaCrit.Sts2.Core.Helpers.SeedHelper", true);
MethodInfo hashMethod = hashType.GetMethod("GetDeterministicHashCode", new[]{typeof(string)});
MethodInfo canonicalMethod = seedType.GetMethod("CanonicalizeSeed", new[]{typeof(string)});
object Call(object rng, string method, params object[] values) =>
    rngType.GetMethod(method, values.Select(x => x.GetType()).ToArray()).Invoke(rng, values);
object State(object rng) {
    object state = rngType.GetMethod("ToSerializable").Invoke(rng, null);
    Type t = state.GetType();
    return new { counter = (int)t.GetField("counter").GetValue(state),
        words = Enumerable.Range(0,4).Select(i => (ulong)t.GetField("state"+i).GetValue(state)).ToArray() };
}
var hashes = new List<object>();
foreach (string text in new[]{"", "22", "shuffle", "act_1_map", "rewards", "A\0B", "牌堆🎴", "é"}
    .Concat(new[]{1,7,8,15,16,31,32,33,63,64,65,1025}.Select(n => new string('x',n))))
    hashes.Add(new { text, hash = (ulong)hashMethod.Invoke(null, new object[]{text}) });
var canonical = new List<object>();
foreach (string text in new[]{"22", " stm-whole-run-speed-1 ", "oIiO", "\t lower-oo11 \r\n", ""}) {
    string result = (string)canonicalMethod.Invoke(null,new object[]{text});
    canonical.Add(new { text, canonical = result, hash = (ulong)hashMethod.Invoke(null,new object[]{result}) });
}
var vectors = new List<object>();
foreach (ulong seed in new ulong[]{0,1,22,123,4294967296,4294967318,9223372036854775808,18446744073709551615}) {
    object rng = Activator.CreateInstance(rngType,new object[]{seed});
    object initial = State(rng);
    var steps = new List<object>();
    void Add(string op, object[] parameters, object value) => steps.Add(new { op, parameters, value, state=State(rng) });
    for(int i=0;i<32;i++) Add("int",new object[]{100},Call(rng,"NextInt",100));
    Add("range",new object[]{int.MinValue,int.MaxValue},Call(rng,"NextInt",int.MinValue,int.MaxValue));
    Add("range",new object[]{-19,23},Call(rng,"NextInt",-19,23));
    for(int i=0;i<3;i++) Add("bool",Array.Empty<object>(),Call(rng,"NextBool"));
    foreach (float[] bounds in new[]{new[]{0f,1f},new[]{-0.25f,12.75f},new[]{4.25f,4.25f}})
        Add("float_bits",bounds.Cast<object>().ToArray(),BitConverter.SingleToUInt32Bits((float)Call(rng,"NextFloat",bounds[0],bounds[1])));
    Add("double_bits",Array.Empty<object>(),BitConverter.DoubleToUInt64Bits((double)Call(rng,"NextDouble")));
    Add("double_range_bits",new object[]{-5.5,10.25},BitConverter.DoubleToUInt64Bits((double)Call(rng,"NextDouble",-5.5,10.25)));
    Add("gaussian",new object[]{7,1,6,7},Call(rng,"NextGaussianInt",7,1,6,7));
    Add("gaussian",new object[]{100,10,0,200},Call(rng,"NextGaussianInt",100,10,0,200));
    Add("ulong",Array.Empty<object>(),Call(rng,"NextUnsignedLong"));
    for(int i=0;i<8;i++) Add("int",new object[]{100},Call(rng,"NextInt",100));
    vectors.Add(new { seed, initial, steps });
}
var oldRegression = new List<object>();
foreach(string op in new[]{"long_int", "gaussian"}) {
    object rng = Activator.CreateInstance(rngType,new object[]{0UL});
    object value;
    if(op=="long_int") { for(int i=0;i<155215;i++) Call(rng,"NextInt",100); value=Call(rng,"NextInt",100); }
    else value=Call(rng,"NextGaussianInt",100,10,0,200);
    oldRegression.Add(new { op,value,state=State(rng),next100=Call(rng,"NextInt",100) });
}
Console.WriteLine(JsonSerializer.Serialize(new {
    oracle_dll_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(dll))).ToLowerInvariant(),
    reference_release = "v0.111.0/41cef1ea", hashes, canonical, vectors, oldRegression
},new JsonSerializerOptions{WriteIndented=true}));
