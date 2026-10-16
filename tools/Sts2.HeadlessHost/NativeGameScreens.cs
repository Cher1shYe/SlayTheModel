using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Potions;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;

namespace SlayTheModel.Headless;

public sealed partial class NativeGameBridge
{
    private void CaptureSurface(HeadlessState frame, List<Binding> bindings, Node surface)
    {
        frame.Screen = surface.GetType().Name;
        frame.Title = ScreenTitle(surface);
        if (NRun.Instance is null)
        {
            frame.Screen = "menu";
            frame.Title = "准备开始";
            frame.Description = "输入 new 创建一局原生游戏。";
            return;
        }
        if (surface is NMapScreen map) { CaptureMap(frame, bindings, map); return; }
        if (surface is NCombatRoom room) { CaptureCombat(frame, bindings, room); return; }
        var special = NativeSpecialScreens.Capture(surface, card => DescribeCard(card, "choice"));
        if (special is not null)
        {
            ApplySpecial(frame, bindings, surface, special);
            return;
        }
        frame.Description = NativeView.NodeText(surface);
        if (surface.GetType().Name == "NGameOverScreen")
        {
            bool victory = NativeView.Get(NativeView.Get(surface, "_history"), "Win") is true;
            frame.Status = "finished";
            frame.Screen = victory ? "victory" : "defeat";
            frame.Title = victory ? "胜利 · Victory" : "败北 · Defeat";
        }
        if (surface is NEventRoom eventRoom && NativeView.Get(eventRoom, "_event") is EventModel model)
        {
            frame.Title = NativeView.ModelName(model);
            frame.SurfaceModelId = model.Id.ToString();
        }
        CaptureButtons(frame, bindings, surface);
        if (surface is NPotionPopup popup)
            Add(frame, bindings, Identity(popup) + ":close", "关闭药水菜单", () =>
            { NativeView.Invoke(popup, "Remove"); return Task.CompletedTask; }, "cancel");
    }

    private static string ScreenTitle(Node screen) => screen.GetType().Name switch
    {
        "NMapScreen" => "地图", "NCombatRoom" => "战斗", "NEventRoom" => "事件",
        "NMerchantInventory" or "NMerchantRoom" => "商店", "NFakeMerchant" => "假商人",
        "NRestSiteRoom" => "休息点", "NRewardsScreen" => "奖励", "NTreasureRoom" => "宝箱",
        "NCrystalSphereScreen" => "水晶球 · 占卜", "NPotionPopup" => "药水操作",
        "NGameOverScreen" => "本局结束", _ => "选择 / 确认",
    };

    private void ApplySpecial(HeadlessState frame, List<Binding> bindings, Node surface, NativeSpecialScreen special)
    {
        frame.Screen = special.Kind;
        var data = JsonSerializer.SerializeToElement(special.Observation, HeadlessJson.Options);
        if (data.TryGetProperty("title", out var title)) frame.Title = title.GetString() ?? frame.Title;
        if (data.TryGetProperty("description", out var description)) frame.Description = NativeView.Text(description.GetString());
        if (data.TryGetProperty("board", out var board)) frame.Board = board.Clone();
        if (data.TryGetProperty("choices", out var choices)) frame.Choices = choices.Clone();
        if (data.TryGetProperty("minSelect", out var minimum) && minimum.ValueKind == JsonValueKind.Number
            && data.TryGetProperty("maxSelect", out var maximum) && maximum.ValueKind == JsonValueKind.Number)
            frame.Description += $"\n选择数量：{minimum}–{maximum} 张。";
        if (data.TryGetProperty("entities", out var entities))
            frame.Entities.AddRange(entities.Deserialize<HeadlessEntity[]>(HeadlessJson.Options) ?? []);
        foreach (var action in special.Actions)
        {
            var payload = action.Payload is null ? default : JsonSerializer.SerializeToElement(action.Payload, HeadlessJson.Options);
            string? PayloadText(string key) => payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty(key, out var value)
                && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
            int? PayloadInt(string key) => payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty(key, out var value)
                && value.TryGetInt32(out int result) ? result : null;
            Add(frame, bindings, Identity(surface) + ":" + action.Id, NativeView.Text(action.LabelZh), action.ExecuteAsync,
                action.Kind, PayloadText("entityId"), description: PayloadText("description"), enLabel: action.LabelEn,
                x: PayloadInt("x"), y: PayloadInt("y"));
        }
    }

    private void CaptureButtons(HeadlessState frame, List<Binding> bindings, Node surface)
    {
        foreach (var control in NativeView.Nodes(surface).OfType<NClickableControl>().Where(NativeView.Enabled))
        {
            if (control is NPotionHolder or NAncientDialogueLine || control.GetParent() is NCardHolder) continue;
            string label = ButtonLabel(control);
            if (string.IsNullOrWhiteSpace(label)) label = control.Name.ToString();
            string? description = control switch
            {
                NEventOptionButton eventButton => NativeView.Text(eventButton.Option.Description),
                NRestSiteButton rest => NativeView.Text(rest.Option.Description),
                _ => null,
            };
            // The native option carries additional locks beyond an enabled button.
            if (control is NEventOptionButton option && (option.Option.IsLocked
                || (option.Option.WasChosen && NativeView.Get(option.Option, "DisableOnChosen") is true))) continue;
            if (control is NRestSiteButton restButton && !restButton.Option.IsEnabled) continue;
            Add(frame, bindings, Identity(control), label, () =>
            {
                if (!NativeView.Enabled(control)) throw new InvalidOperationException("原生控件已不可用。");
                return UiHelper.Click(control, 80);
            }, control is NEventOptionButton ? "event" : control is NRewardButton ? "reward" : "button",
                description: description);
        }
    }

    private static string ButtonLabel(NClickableControl button) => button switch
    {
        NEventOptionButton option => NativeView.Text(option.Option.Title),
        NRestSiteButton rest => NativeView.Text(rest.Option.Title),
        NRewardButton reward => NativeView.Text(reward.Reward?.Description),
        NProceedButton proceed => proceed.IsSkip ? "跳过" : "继续",
        _ => NativeView.NodeText(button),
    };

    private void CaptureMap(HeadlessState frame, List<Binding> bindings, NMapScreen map)
    {
        var run = RunManager.Instance.DebugOnlyGetState();
        if (run is null) return;
        var points = NativeView.Nodes(map).OfType<NMapPoint>().Where(NativeView.Visible)
            .OrderBy(point => point.Point.coord.row).ThenBy(point => point.Point.coord.col).ToArray();
        string Key(NMapPoint point) => $"map:{point.Point.coord.col},{point.Point.coord.row}";
        frame.Screen = "map";
        frame.Description = $"第 {run.CurrentActIndex + 1} 幕 · 第 {run.ActFloor} 层";
        frame.Map = new
        {
            nodes = points.Select(point => new
            {
                id = Key(point), x = point.Point.coord.col, y = point.Point.coord.row,
                kind = point.Point.PointType.ToString(), label = MapLabel(point.Point.PointType.ToString()),
                available = map.IsTravelEnabled && !map.IsTraveling && NativeView.Get(point, "IsTravelable") is true,
                visited = run.VisitedMapCoords.Contains(point.Point.coord),
            }).ToArray(),
            edges = points.SelectMany(point => point.Point.Children.Select(child => new
                { from = Key(point), to = $"map:{child.coord.col},{child.coord.row}" })).ToArray(),
        };
        if (map.IsTraveling)
        {
            frame.Status = "busy";
            return;
        }
        foreach (var point in points.Where(point => map.IsTravelEnabled && !map.IsTraveling && NativeView.Get(point, "IsTravelable") is true))
            Add(frame, bindings, Identity(point), $"前往 {MapLabel(point.Point.PointType.ToString())}（{point.Point.coord.col},{point.Point.coord.row}）", () =>
            {
                if (!map.IsTravelEnabled || map.IsTraveling || NativeView.Get(point, "IsTravelable") is not true)
                    throw new InvalidOperationException("该地图节点当前不可前往。");
                map.OnMapPointSelectedLocally(point);
                return Task.CompletedTask;
            }, "map", targetId: Key(point), x: point.Point.coord.col, y: point.Point.coord.row);
        foreach (var button in NativeView.Nodes(map).OfType<NClickableControl>().Where(NativeView.Enabled)
                     .Where(node => node.GetType().Name == "NBackButton"))
            Add(frame, bindings, Identity(button), "返回当前房间", () => UiHelper.Click(button, 80), "back");
    }

    private static string MapLabel(string kind) => kind switch
    {
        "Monster" => "普通战斗", "Elite" => "精英", "Boss" => "首领", "Shop" or "Merchant" => "商店",
        "RestSite" => "休息点", "Treasure" => "宝箱", "Unknown" => "未知事件", "Ancient" => "古代事件",
        _ => kind,
    };

    private void CaptureCombat(HeadlessState frame, List<Binding> bindings, NCombatRoom room)
    {
        frame.Screen = "combat";
        frame.SurfaceModelId = (RunManager.Instance.DebugOnlyGetState()?.CurrentRoom as CombatRoom)?.Encounter.Id.ToString();
        var state = CombatManager.Instance.DebugOnlyGetState();
        var player = RunManager.Instance.DebugOnlyGetState()?.Players.FirstOrDefault();
        var hand = NPlayerHand.Instance;
        if (state is null || player?.PlayerCombatState is not { } pc || hand is null) return;
        frame.Description = $"回合 {state.RoundNumber} · {pc.Phase}";
        if (hand.IsInCardSelection) { CaptureHandSelection(frame, bindings, hand); return; }
        if (pc.Phase != PlayerTurnPhase.Play || RunManager.Instance.ActionExecutor?.IsRunning == true
            || !RunManager.Instance.ActionQueueSet.IsEmpty)
        {
            frame.Status = "busy";
            return;
        }
        if (CombatManager.Instance.IsInProgress && NativeView.Invoke(hand, "CanPlayCards") is true)
        {
            foreach (var card in pc.Hand.Cards.Where(card => card.CanPlay()))
            {
                IEnumerable<Creature?> targets = state.Creatures.Cast<Creature?>().Prepend(null).Where(card.CanPlayTargeting);
                foreach (var target in targets)
                {
                    string label = "打出 " + NativeView.Text(card.Title) + (target is null ? "" : " → " + NativeView.Text(target.Name));
                    Add(frame, bindings, Identity(card) + ":play:" + (target is null ? "none" : Identity(target)), label, () =>
                    {
                        if (!card.TryManualPlay(target)) throw new InvalidOperationException("原生游戏拒绝了该次出牌。");
                        return Task.CompletedTask;
                    }, "play", Identity(card), target is null ? null : Identity(target), enLabel: NativeView.English(card));
                }
            }
        }
        foreach (var button in NativeView.Nodes(room).OfType<NEndTurnButton>().Where(NativeView.Enabled))
            Add(frame, bindings, Identity(button), "结束回合", () => UiHelper.Click(button, 80), "endTurn");
    }

    private void CaptureHandSelection(HeadlessState frame, List<Binding> bindings, NPlayerHand hand)
    {
        frame.Screen = "handSelection";
        var prefs = (CardSelectorPrefs)(NativeView.Get(hand, "_prefs") ?? throw new InvalidOperationException("选牌约束缺失。"));
        frame.Title = NativeView.Text(prefs.Prompt);
        frame.Description = $"选择 {prefs.MinSelect}–{prefs.MaxSelect} 张，再确认。";
        var selected = NativeView.Items(NativeView.Get(hand, "_selectedCards")).Cast<CardModel>().ToArray();
        frame.Choices = hand.ActiveHolders.Select(holder => holder.CardNode?.Model).OfType<CardModel>().Concat(selected).Distinct()
            .Select((card, index) => new { index, selected = selected.Contains(card), card = DescribeCard(card, "choice") }).ToArray();
        foreach (var holder in hand.ActiveHolders)
        {
            if (holder.CardNode?.Model is not { } card) continue;
            Add(frame, bindings, Identity(holder), "选择 " + NativeView.Text(card.Title), () =>
            {
                if (!hand.IsInCardSelection || !NativeView.Visible(holder)) throw new InvalidOperationException("选择器已变化。");
                holder.EmitSignal(NCardHolder.SignalName.Pressed, holder);
                return Task.CompletedTask;
            }, "selectCard", Identity(card));
        }
        // UpgradeSelect replaces its preview when another card is selected;
        // selected cards are not owned by the SimpleSelect container.
        foreach (var card in selected.Where(_ => hand.CurrentMode == NPlayerHand.Mode.SimpleSelect))
            Add(frame, bindings, Identity(card) + ":deselect", "取消选择 " + NativeView.Text(card.Title), () =>
            {
                if (!hand.IsInCardSelection) throw new InvalidOperationException("选择器已关闭。");
                if (NativeView.Get(hand, "_selectedHandCardContainer") is { } container)
                    NativeView.Invoke(container, "DeselectCard", card);
                return Task.CompletedTask;
            }, "deselectCard", Identity(card));
        if (NativeView.Get(hand, "_selectModeConfirmButton") is NClickableControl confirm && NativeView.Enabled(confirm))
            Add(frame, bindings, Identity(confirm), "确认选牌（" + selected.Length + " 张）", () => UiHelper.Click(confirm, 80), "confirm");
    }

    private void CapturePotionOpenActions(HeadlessState frame, List<Binding> bindings)
    {
        var run = NRun.Instance;
        if (run is null) return;
        foreach (var holder in NativeView.Nodes(run.GlobalUi).OfType<NPotionHolder>().Where(NativeView.Enabled))
        {
            if (holder.Potion?.Model is not { } potion || potion.IsQueued
                || potion.Owner.RunState.IsGameOver || NativeView.Get(holder, "_disabledUntilPotionRemoved") is true
                || NativeView.Get(holder, "_isUsable") is not true) continue;
            Add(frame, bindings, Identity(holder) + ":potion", "药水操作：" + NativeView.ModelName(potion),
                () =>
                {
                    if (!NativeView.Enabled(holder) || !ReferenceEquals(holder.Potion?.Model, potion)
                        || potion.Owner.RunState.IsGameOver || potion.IsQueued
                        || NativeView.Get(holder, "_disabledUntilPotionRemoved") is true)
                        throw new InvalidOperationException("药水槽当前不可操作。");
                    return UiHelper.Click(holder, 80);
                }, "potion", Identity(potion));
        }
    }

    private void CaptureTargets(HeadlessState frame, List<Binding> bindings, NTargetManager manager)
    {
        frame.Screen = "target";
        frame.Title = "选择目标";
        frame.Description = "选择此次原生操作的目标，或取消。";
        foreach (var node in NativeView.Nodes(_host.GetTree().Root).Where(NativeView.Visible)
                     .Where(node => node is NCreature || node.GetType().Name is "NMerchantButton" or "NMultiplayerPlayerState"))
        {
            if (!manager.AllowedToTargetNode(node)) continue;
            string label = node is NCreature creature ? NativeView.Text(creature.Entity.Name)
                : node.GetType().Name == "NMerchantButton" ? "商人" : "玩家";
            Add(frame, bindings, Identity(node) + ":target", "选择目标：" + label, () =>
            {
                if (!manager.IsInSelection || !manager.AllowedToTargetNode(node))
                    throw new InvalidOperationException("目标当前不可用。");
                manager.OnNodeHovered(node);
                NativeView.Invoke(manager, "FinishTargeting", false);
                return Task.CompletedTask;
            }, "target", targetId: node is NCreature c ? Identity(c.Entity) : Identity(node));
        }
        Add(frame, bindings, "cancel-target", "取消目标选择", () => { manager.CancelTargeting(); return Task.CompletedTask; }, "cancel");
    }
}
