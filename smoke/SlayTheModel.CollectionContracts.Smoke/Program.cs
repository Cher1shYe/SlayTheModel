using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;

void Require(bool value,string message) { if(!value) throw new Exception(message); }
void Reject(Action action) {
    try {action();} catch(InvalidDataException) {return;}
    throw new Exception("Malformed endpoint accepted");
}
Require(CollectionEndpointContract.Validate(true,true,false,false,80,57,false,false)=="selector_boundary","Pending edge scalar comparison");
Require(CollectionEndpointContract.Validate(false,false,false,false,57,57,false,false)=="complete_continuation","Resolved endpoint missing");
Require(CollectionEndpointContract.Validate(false,false,true,true,0,0,false,false)=="complete_continuation","Death rejected");
Reject(()=>CollectionEndpointContract.Validate(false,false,false,false,80,57,false,false));
Reject(()=>CollectionEndpointContract.Validate(true,false,false,false,80,80,false,false));
Reject(()=>CollectionEndpointContract.Validate(false,true,false,false,80,80,false,false));
Reject(()=>CollectionEndpointContract.Validate(true,true,true,true,0,0,false,false));
Reject(()=>CollectionEndpointContract.Validate(false,false,true,true,80,80,true,false));
Reject(()=>CollectionEndpointContract.Validate(false,false,true,false,80,80,true,false));

// Exercise the actual compiled Beam node and diagnostics, without a Godot combat.
// Uninitialized snapshots are used only as zero-valued scalar diagnostic fixtures.
string directory=Path.GetFullPath(args.Single());
AssemblyLoadContext.Default.Resolving+=(_,name)=>File.Exists(Path.Combine(directory,name.Name+".dll"))
    ? AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(directory,name.Name+".dll")) : null;
Assembly assembly=AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(directory,"CombatSolver.dll"));
Type nodeType=assembly.GetType("CombatSolver.SearchNode",true)!;
object node=RuntimeHelpers.GetUninitializedObject(nodeType);
object snapshot=RuntimeHelpers.GetUninitializedObject(assembly.GetType("CombatSolver.SimulationSnapshot",true)!);
nodeType.GetProperty("Snapshot")!.SetValue(node,snapshot);
nodeType.GetProperty("ActionCount")!.SetValue(node,9);
nodeType.GetProperty("ExternalRouteOwned")!.SetValue(node,true);
List<string> logs=[];
Action<string> capture=logs.Add;
object sink=Activator.CreateInstance(assembly.GetType("CombatSolver.SearchDiagnosticsSink",true)!,capture,capture,null)!;
MethodInfo publish=assembly.GetType("CombatSolver.SearchReplayEvidence",true)!.GetMethod("PublishCandidateFailure")!;
publish.Invoke(null,[sink,node,"original_transition_failure",null]);
using(var evidence=JsonDocument.Parse(logs.Single().Split("FAILED_CANDIDATE ")[1])) {
    Require(evidence.RootElement.GetProperty("prefix").ValueKind==JsonValueKind.Null,"External history fabricated");
    Require(evidence.RootElement.GetProperty("prefixOwnedByExternalSearch").GetBoolean(),"Missing route ownership");
    Require(evidence.RootElement.GetProperty("ActionCount").GetInt32()==9,"Absolute action count lost");
}
nodeType.GetProperty("ExternalRouteOwned")!.SetValue(node,false);
bool rejected=false;
try {publish.Invoke(null,[sink,node,"broken_beam_route",null]);}
catch(TargetInvocationException error) when(error.InnerException is InvalidOperationException) {rejected=true;}
Require(rejected,"Malformed Beam route no longer rejected");
nodeType.GetProperty("ActionCount")!.SetValue(node,0);
publish.Invoke(null,[sink,node,"valid_beam_root",null]);
Console.WriteLine("Collection contracts: pending/resolved endpoint boundaries, terminal and HP mismatch rejection, real external-route diagnostics and Beam chain invariant passed.");
