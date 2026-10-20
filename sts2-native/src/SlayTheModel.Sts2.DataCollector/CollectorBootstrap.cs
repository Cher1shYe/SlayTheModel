using MegaCrit.Sts2.Core.Modding;

namespace SlayTheModel.Sts2.DataCollector;

[ModInitializer(nameof(Initialize))]
public static class CollectorBootstrap
{
    private static bool _initialized;

    public static void Initialize()
    {
        if (_initialized)
        {
            return;
        }

        _initialized = true;
        try
        {
            var configuration = CollectorConfiguration.Load();
            if (!configuration.Enabled)
            {
                Console.WriteLine("[SlayTheModel/Collector] disabled by configuration");
                return;
            }

            CollectorRuntime.Initialize(configuration);
        }
        catch (Exception exception)
        {
            // A read-only collector must never strand or mutate a live run when
            // its own storage/configuration is unavailable.
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] initialization failed; collection disabled: {exception}");
        }
    }
}
