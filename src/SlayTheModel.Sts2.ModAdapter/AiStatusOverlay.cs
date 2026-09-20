using Godot;

namespace SlayTheModel.Sts2.ModAdapter;

internal sealed record AiControlStatus(string Text, string Tooltip, string Accent, bool CanToggle);

/// <summary>Small viewport-anchored control; the surrounding overlay never consumes input.</summary>
internal static class AiStatusOverlay
{
    public static void Initialize()
    {
        Callable.From(() => Attach((SceneTree)Engine.GetMainLoop(), MctsCombatController.GetStatus,
            MctsCombatController.TogglePause)).CallDeferred();
    }

    internal static Button Attach(SceneTree tree, Func<AiControlStatus> getStatus, Action toggle)
    {
        var layer = new CanvasLayer { Name = "SlayTheModelStatus", Layer = 120 };
        var root = new Control { MouseFilter = Control.MouseFilterEnum.Ignore };
        layer.AddChild(root);
        tree.Root.AddChild(layer);
        root.SetAnchorsAndOffsetsPreset(Control.LayoutPreset.FullRect);
        var button = new Button
        {
            Name = "MctsStatusButton",
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        root.AddChild(button);
        button.SetAnchorsAndOffsetsPreset(Control.LayoutPreset.TopRight);
        button.OffsetLeft = -252;
        button.OffsetRight = -20;
        button.OffsetTop = 100;
        button.OffsetBottom = 142;
        button.AddThemeFontOverride("font", new SystemFont { FontNames = ["Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"] });
        button.AddThemeFontSizeOverride("font_size", 17);
        button.AddThemeStyleboxOverride("normal", Style("#15202beF"));
        button.AddThemeStyleboxOverride("disabled", Style("#15202beF"));
        button.AddThemeStyleboxOverride("hover", Style("#243648f5"));
        button.AddThemeStyleboxOverride("pressed", Style("#0e1722f5"));
        AiControlStatus? previous = null;
        void Refresh()
        {
            var status = getStatus();
            if (status == previous) return;
            previous = status;
            button.Text = status.Text;
            button.TooltipText = status.Tooltip;
            button.Disabled = !status.CanToggle;
            var color = new Color(status.Accent);
            foreach (var state in new[] { "font_color", "font_hover_color", "font_pressed_color", "font_disabled_color" })
                button.AddThemeColorOverride(state, color);
        }
        button.Pressed += () => { toggle(); Refresh(); };
        tree.ProcessFrame += Refresh;
        layer.TreeExiting += () => tree.ProcessFrame -= Refresh;
        Refresh();
        return button;
    }

    private static StyleBoxFlat Style(string background) => new()
    {
        BgColor = new Color(background),
        BorderColor = new Color("#53677d"),
        BorderWidthLeft = 1, BorderWidthRight = 1, BorderWidthTop = 1, BorderWidthBottom = 1,
        CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomLeft = 9, CornerRadiusBottomRight = 9,
        ContentMarginLeft = 12, ContentMarginRight = 12, ContentMarginTop = 8, ContentMarginBottom = 8,
    };
}
