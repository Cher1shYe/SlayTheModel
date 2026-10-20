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
        var statusFont = LoadStatusFont();
        if (statusFont is not null)
            button.AddThemeFontOverride("font", statusFont);
        GD.Print($"[SlayTheModel] status overlay attached font={(statusFont is null ? "game-default" : statusFont.GetType().Name)}");
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

    private static Font? LoadStatusFont()
    {
        if (OperatingSystem.IsMacOS())
        {
            // SystemFont resolves some macOS TTC families to an empty file in the
            // game's Godot build. Loading the actual file avoids zero font metrics,
            // which made the complete status button disappear.
            string[] paths =
            [
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/STHeiti Medium.ttc",
            ];
            foreach (var path in paths)
            {
                if (!File.Exists(path)) continue;
                try
                {
                    // Supplying bytes avoids a Godot 4.5 macOS path-resolution
                    // issue where LoadDynamicFont reports success but later asks
                    // FreeType to open an empty filename.
                    var font = new FontFile { Data = File.ReadAllBytes(path) };
                    GD.Print($"[SlayTheModel] loaded status font {path}");
                    return font;
                }
                catch (Exception exception)
                {
                    GD.PushWarning($"[SlayTheModel] could not load status font {path}: {exception.Message}");
                }
            }

            // Keeping the game theme font is preferable to installing a broken
            // override: the button remains visible even if Chinese glyphs are absent.
            return null;
        }

        return new SystemFont { FontNames = ["Microsoft YaHei", "Noto Sans CJK SC"] };
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
