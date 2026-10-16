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
            _bridge = new NativeGameBridge(this, async request =>
            {
                await NativeBootstrap.StartNewRunAsync(request.Character, request.Ascension, request.Seed, request.Language);
                await NativeSmokeScenario.EnterConfiguredAsync(message => GD.Print(message));
            });
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
