using SlayTheModel.Sts2.ModAdapter;

var path = Path.Combine(Path.GetDirectoryName(typeof(ArmGSwitch).Assembly.Location)!,
    "SlayTheModelAdapter.armg-toggle.json");
if (File.Exists(path)) throw new Exception("Refusing to overwrite an existing switch state.");
try
{
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_ENABLED", "1");
    ArmGSwitch.Configure(false);
    if (ArmGSwitch.Available || ArmGSwitch.Enabled || ArmGSwitch.GetStatus().CanToggle)
        throw new Exception("Unavailable switch must be disabled.");
    ArmGSwitch.Configure(true);
    if (!ArmGSwitch.Available || !ArmGSwitch.Enabled || !ArmGSwitch.GetStatus().CanToggle)
        throw new Exception("Configured network switch should default to enabled.");
    var generation = ArmGSwitch.Generation;
    ArmGSwitch.Toggle();
    if (ArmGSwitch.Enabled || ArmGSwitch.Generation <= generation || !File.Exists(path))
        throw new Exception("Turning off must advance the generation and save state.");
    ArmGSwitch.Configure(false);
    ArmGSwitch.Configure(true);
    if (ArmGSwitch.Enabled) throw new Exception("Disabled switch state was not restored.");
    generation = ArmGSwitch.Generation;
    ArmGSwitch.Toggle();
    if (!ArmGSwitch.Enabled || ArmGSwitch.Generation <= generation)
        throw new Exception("Turning on must advance the generation.");
    ArmGSwitch.Configure(false);
    ArmGSwitch.Configure(true);
    if (!ArmGSwitch.Enabled) throw new Exception("Enabled switch state was not restored.");
    Console.WriteLine("ArmG independent switch: availability, toggling, request generation and persistence passed.");
}
finally { if (File.Exists(path)) File.Delete(path); }

namespace SlayTheModel.Sts2.ModAdapter
{
    internal sealed record AiControlStatus(string Text, string Tooltip, string Accent, bool CanToggle);
}
