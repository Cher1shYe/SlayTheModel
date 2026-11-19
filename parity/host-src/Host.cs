using Godot;

namespace SlayTheModel.Headless;

public partial class Host : Node
{
    private NativeGameBridge? _bridge;
    private HeadlessHttpServer? _server;

    public override async void _Ready()
    {
        try
        {
            await NativeBootstrap.InitializeAsync(this);
            if (System.Environment.GetEnvironmentVariable("STS2_MONSTER_NUMBERS_OUTPUT") is { Length: > 0 } numbersPath)
            {
                int ascension = int.Parse(System.Environment.GetEnvironmentVariable("STS2_MONSTER_NUMBERS_ASCENSION") ?? "10");
                await NativeMonsterNumbersExport.WriteAsync(numbersPath, ascension);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_REGISTRY_OUTPUT") is { Length: > 0 } registryPath)
            {
                await NativeRegistryExport.WriteAsync(registryPath);
                GetTree().Quit();
                return;
            }
            _bridge = new NativeGameBridge(this, request =>
                NativeBootstrap.StartNewRunAsync(request.Character, request.Ascension, request.Seed, request.Language));
            int port = int.Parse(System.Environment.GetEnvironmentVariable("STS2_HEADLESS_PORT") ?? "18777");
            _server = new HeadlessHttpServer(_bridge, port);
            _server.Start();
            GD.Print("SLAY_HEADLESS_READY " + _server.Url);
        }
        catch (Exception exception)
        {
            GD.PrintErr("SLAY_HEADLESS_FAILED " + exception);
            GetTree().Quit(1);
        }
    }

    public override void _Process(double delta) => _bridge?.Tick();
    public override void _ExitTree() => _server?.Dispose();
}
