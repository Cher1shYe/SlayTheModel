using System.Diagnostics;

namespace SlayTheModel.Sts2.ModAdapter;

internal static class NativeWorkerLaunch
{
    internal const string SentryGodotLibraryPath = "SENTRY_GODOT_LIB_PATH";

    internal static void IsolateFromGameProcess(ProcessStartInfo start)
    {
        // The running game sets this to its already-initialized Sentry GDExtension.
        // A child worker inherits the path but not the initialized native state, so
        // Sentry's managed module initializer calls into an invalid bridge and dies
        // with 0xC0000005 before Worker._Ready can run.
        start.Environment.Remove(SentryGodotLibraryPath);
    }
}
