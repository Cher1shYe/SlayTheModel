using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Potions;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Hooks;
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
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rewards;

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
        var special = NativeSpecialScreens.Capture(surface, card => DescribeCard(card, "choice"), card => DescribePublicCard(card, "choice"));
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
            frame.Decision = new { eventId = model.Id.ToString(), pageKey = model.Description?.LocEntryKey,
                finished = model.IsFinished };
        }
        if (surface.GetType().Name == "NRewardsScreen")
        {
            var ordinal = new Dictionary<string, int>();
            var offers = new List<object>();
            foreach (var button in NativeView.Nodes(surface).OfType<NRewardButton>().Where(NativeView.Visible))
            {
                if (button.Reward is not { } reward) continue;
                string kind = reward.GetType().Name;
                ordinal.TryGetValue(kind, out int index);
                ordinal[kind] = index + 1;
                offers.Add(RewardMetadata(button, index));
            }
            frame.Decision = new { kind = "rewards", rewards = offers };
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
        if (!special.Ready) frame.Status = "busy";
        if (RunManager.Instance.DebugOnlyGetState()?.CurrentRoom is EventRoom eventRoom)
            frame.SurfaceModelId = eventRoom.LocalMutableEvent.Id.ToString();
        var data = JsonSerializer.SerializeToElement(special.Observation, HeadlessJson.Options);
        frame.Decision = data.Clone();
        if (data.TryGetProperty("title", out var title)) frame.Title = title.GetString() ?? frame.Title;
        if (data.TryGetProperty("description", out var description)) frame.Description = NativeView.Text(description.GetString());
        if (data.TryGetProperty("board", out var board)) frame.Board = board.Clone();
        if (data.TryGetProperty("choices", out var choices)) frame.Choices = choices.Clone();
        if (data.TryGetProperty("minSelect", out var minimum) && minimum.ValueKind == JsonValueKind.Number
            && data.TryGetProperty("maxSelect", out var maximum) && maximum.ValueKind == JsonValueKind.Number)
            frame.Description += $"\n选择数量：{minimum}–{maximum} 张。";
        if (data.TryGetProperty("entities", out var entities))
            foreach (var entity in entities.Deserialize<HeadlessEntity[]>(HeadlessJson.Options) ?? [])
                if (!frame.Entities.Any(existing => existing.Id == entity.Id)) frame.Entities.Add(entity);
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
            frame.Actions[^1].ChoiceIndex = PayloadInt("index");
            frame.Actions[^1].Metadata = payload.ValueKind == JsonValueKind.Object ? payload.Clone() : null;
        }
    }

    private void CaptureButtons(HeadlessState frame, List<Binding> bindings, Node surface)
    {
        var rewardOrdinals = new Dictionary<string, int>();
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
            if (control is NRewardButton rewardButton && !CanClaimReward(rewardButton)) continue;
            Add(frame, bindings, Identity(control), label, () =>
            {
                if (!NativeView.Enabled(control)) throw new InvalidOperationException("原生控件已不可用。");
                if (control is NRewardButton reward && !CanClaimReward(reward))
                    throw new InvalidOperationException("奖励当前无法领取。");
                return UiHelper.Click(control, 80);
            }, control is NEventOptionButton ? "event" : control is NRewardButton ? "reward" : "button",
                description: description);
            if (control is NEventOptionButton eventOption)
            {
                frame.Actions[^1].OptionModelId = eventOption.Option.Relic?.Id.ToString();
                frame.Actions[^1].OptionIsProceed = eventOption.Option.IsProceed;
                var evt = NativeView.Get(surface, "_event") as EventModel;
                frame.Actions[^1].Metadata = new { eventId = evt?.Id.ToString(),
                    pageKey = evt?.Description?.LocEntryKey, optionKey = EventOptionKey(evt, eventOption),
                    isProceed = eventOption.Option.IsProceed };
            }
            else if (control is NRestSiteButton restOption)
                frame.Actions[^1].Metadata = new { role = "rest", optionId = restOption.Option.OptionId };
            else if (control is NRewardButton reward)
            {
                var rewardValue = reward.Reward ?? throw new InvalidOperationException("Visible reward has no model.");
                string rewardType = rewardValue.GetType().Name;
                rewardOrdinals.TryGetValue(rewardType, out int ordinal);
                rewardOrdinals[rewardType] = ordinal + 1;
                frame.Actions[^1].Metadata = RewardMetadata(reward, ordinal);
            }
            else if (control is NProceedButton proceed)
                frame.Actions[^1].Metadata = new { role = "proceed", isSkip = proceed.IsSkip,
                    surface = surface.GetType().Name };
            else if (ReferenceEquals(NativeView.Get(surface, "_chestButton"), control))
                frame.Actions[^1].Metadata = new { role = "open_treasure" };
            else if (control.GetType().Name == "NMerchantButton")
                frame.Actions[^1].Metadata = new { role = "open_shop", transportOnly = true };
            else
                frame.Actions[^1].Metadata = new { role = "unclassified", control = control.GetType().Name };
        }
    }

    private object RewardMetadata(NRewardButton button, int ordinal)
    {
        var reward = button.Reward ?? throw new InvalidOperationException("Visible reward has no model.");
        var model = reward switch
        {
            PotionReward potion => potion.Potion as AbstractModel,
            RelicReward relic => relic.Relic,
            SpecialCardReward special => NativeView.Get(special, "_card") as CardModel,
            _ => null,
        };
        return new { role = "reward", rewardType = reward.GetType().Name, ordinal,
            amount = reward is GoldReward gold ? (int?)gold.Amount : null,
            recovered = reward is GoldReward && NativeView.Get(reward, "_wasGoldStolenBack") is true,
            modelId = model?.Id.ToString(), upgradeLevel = model is CardModel card ? (int?)card.CurrentUpgradeLevel : null,
            publicCard = model is CardModel visibleCard ? DescribePublicCard(visibleCard, "reward") : null,
            claimable = NativeView.Enabled(button) && CanClaimReward(button) };
    }

    private static string EventOptionKey(EventModel? model, NEventOptionButton button)
    {
        var option = button.Option;
        if (model?.Id.Entry == "DOLL_ROOM" && option.Title.LocTable == "relics")
        {
            // DollRoom.OptionFromChoice uses localized raw text as TextKey, but
            // its Title retains the exact relic localization/model key.
            string titleKey = option.Title.LocEntryKey;
            if (!titleKey.EndsWith(".title", StringComparison.Ordinal))
                throw new InvalidOperationException("Doll option has no stable relic title key.");
            return "DOLL_ROOM.choice.RELIC." + titleKey[..^6];
        }
        if (model?.Id.Entry == "THE_FUTURE_OF_POTIONS" && !option.IsProceed
            && option.TextKey == "THE_FUTURE_OF_POTIONS.pages.INITIAL.options.POTION")
        {
            // GenerateInitialOptions explicitly iterates the first three public
            // occupied potions. CardType is already displayed in each option;
            // read the populated dictionary, never invoke its RNG-using getter.
            var owner = model.Owner ?? throw new InvalidOperationException("Event has no local owner.");
            int index = Array.IndexOf(model.CurrentOptions.ToArray(), option);
            var potions = owner.Potions.Take(3).ToArray();
            if (index < 0 || index >= potions.Length
                || NativeView.Get(model, "_cardTypes") is not System.Collections.IDictionary types)
                throw new InvalidOperationException("Future of Potions public option model is unavailable.");
            var potion = potions[index];
            int slot = Array.IndexOf(owner.PotionSlots.ToArray(), potion);
            if (types[potion] is not CardType type)
                throw new InvalidOperationException("Future of Potions public card type is unavailable.");
            return option.TextKey + "@" + slot + ":" + potion.Id + ":" + type.ToString().ToUpperInvariant();
        }
        return option.TextKey;
    }

    private static bool CanClaimReward(NRewardButton button)
    {
        if (button.Reward is not PotionReward reward || reward.Potion is null) return true;
        var state = RunManager.Instance.DebugOnlyGetState();
        return state is not null && state.Players.Count == 1
            && (state.Players[0].HasOpenPotionSlots
                || !Hook.ShouldProcurePotion(state, state.Players[0].Creature.CombatState, reward.Potion, state.Players[0]));
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
            .Select((card, index) => new { index, selected = selected.Contains(card), card = DescribeCard(card, "choice"), publicCard = DescribePublicCard(card, "choice") }).ToArray();
        frame.Decision = new { kind = "hand_selection", mode = hand.CurrentMode.ToString(),
            minSelect = prefs.MinSelect, maxSelect = prefs.MaxSelect, requireManualConfirmation = true,
            cancelable = prefs.Cancelable, choices = frame.Choices };
        foreach (var holder in hand.ActiveHolders)
        {
            if (holder.CardNode?.Model is not { } card) continue;
            Add(frame, bindings, Identity(holder), "选择 " + NativeView.Text(card.Title), () =>
            {
                if (!hand.IsInCardSelection || !NativeView.Visible(holder)) throw new InvalidOperationException("选择器已变化。");
                holder.EmitSignal(NCardHolder.SignalName.Pressed, holder);
                return Task.CompletedTask;
            }, "selectCard", Identity(card));
            frame.Actions[^1].Metadata = new { card = DescribePublicCard(card, "choice") };
        }
        // UpgradeSelect replaces its preview when another card is selected;
        // selected cards are not owned by the SimpleSelect container.
        foreach (var card in selected.Where(_ => hand.CurrentMode == NPlayerHand.Mode.SimpleSelect))
        {
            Add(frame, bindings, Identity(card) + ":deselect", "取消选择 " + NativeView.Text(card.Title), () =>
            {
                if (!hand.IsInCardSelection) throw new InvalidOperationException("选择器已关闭。");
                if (NativeView.Get(hand, "_selectedHandCardContainer") is { } container)
                    NativeView.Invoke(container, "DeselectCard", card);
                return Task.CompletedTask;
            }, "deselectCard", Identity(card));
            frame.Actions[^1].Metadata = new { card = DescribePublicCard(card, "choice") };
        }
        if (hand.CurrentMode == NPlayerHand.Mode.UpgradeSelect
            && NativeView.Get(hand, "_upgradePreview") is Node preview
            && NativeView.Get(preview, "_before") is Node before)
            foreach (var holder in NativeView.Nodes(before).OfType<NCardHolder>())
                if (holder.CardNode?.Model is { } card && selected.Contains(card))
                {
                    Add(frame, bindings, Identity(holder) + ":deselect", "取消升级选择 " + NativeView.Text(card.Title), () =>
                    {
                        if (!hand.IsInCardSelection || !NativeView.Visible(holder))
                            throw new InvalidOperationException("升级预览已关闭。");
                        holder.EmitSignal(NCardHolder.SignalName.Pressed, holder);
                        return Task.CompletedTask;
                    }, "deselectCard", Identity(card));
                    frame.Actions[^1].Metadata = new { card = DescribePublicCard(card, "choice") };
                }
        if (NativeView.Get(hand, "_selectModeConfirmButton") is NClickableControl confirm && NativeView.Enabled(confirm))
            Add(frame, bindings, Identity(confirm), "确认选牌（" + selected.Length + " 张）", () => UiHelper.Click(confirm, 80), "confirm");
    }

    private void CapturePotionOpenActions(HeadlessState frame, List<Binding> bindings)
    {
        var run = NRun.Instance;
        if (run is null || frame.Status != "ready") return;
        bool selecting = NPlayerHand.Instance?.IsInCardSelection == true
            || NOverlayStack.Instance?.Peek() is ICardSelector;
        foreach (var holder in NativeView.Nodes(run.GlobalUi).OfType<NPotionHolder>().Where(NativeView.Enabled))
        {
            if (holder.Potion?.Model is not { } potion || potion.IsQueued
                || potion.Owner.RunState.IsGameOver || potion.Owner.Creature.IsDead
                || !potion.Owner.CanUseOrRemovePotions
                || NativeView.Get(holder, "_disabledUntilPotionRemoved") is true
                || NativeView.Get(holder, "_isUsable") is not true) continue;
            int slot = Array.IndexOf(potion.Owner.PotionSlots.ToArray(), potion);
            if (slot < 0) throw new InvalidOperationException("Potion holder has no owned slot.");
            void CheckCurrent()
            {
                if (!NativeView.Enabled(holder) || !ReferenceEquals(holder.Potion?.Model, potion)
                    || potion.Owner.RunState.IsGameOver || potion.IsQueued || potion.Owner.Creature.IsDead
                    || !potion.Owner.CanUseOrRemovePotions
                    || NativeView.Get(holder, "_disabledUntilPotionRemoved") is true)
                    throw new InvalidOperationException("药水槽当前不可操作。");
            }
            // These are precisely the native popup's command entry points. Opening
            // the popup and dragging its target are transport navigation; the model
            // still decides use versus discard, physical slot, and target explicitly.
            Add(frame, bindings, Identity(potion) + ":discard", "丢弃 " + NativeView.ModelName(potion), () =>
            {
                CheckCurrent();
                NativeView.Invoke(holder, "DisableUntilPotionRemoved");
                RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(
                    new DiscardPotionGameAction(potion.Owner, (uint)slot, CombatManager.Instance.IsInProgress));
                return Task.CompletedTask;
            }, "discard_potion", Identity(potion));
            frame.Actions[^1].Metadata = new { slot, modelId = potion.Id.ToString() };
            bool canUse = potion.Usage == PotionUsage.AnyTime
                || potion.Usage == PotionUsage.CombatOnly && CombatManager.Instance.IsInProgress
                    && potion.Owner.Creature.CombatState?.CurrentSide == potion.Owner.Creature.Side
                    && !selecting && !CombatManager.Instance.PlayerActionsDisabled;
            if (!canUse || !potion.PassesCustomUsabilityCheck) continue;
            IEnumerable<Creature?> candidates = potion.TargetType == TargetType.AnyEnemy || potion.CanThrowAtAlly()
                ? potion.Owner.Creature.CombatState?.Creatures.Cast<Creature?>() ?? []
                // EnqueueManualUse(null) normalizes an AnyPlayer potion to its
                // owner in single-player. Validate that normalized target too.
                : [potion.IsValidTarget(potion.Owner.Creature) ? potion.Owner.Creature : null];
            foreach (var target in candidates.Where(potion.IsValidTarget))
            {
                string? targetId = target is null || ReferenceEquals(target, potion.Owner.Creature) ? null : Identity(target);
                Add(frame, bindings, Identity(potion) + ":use:" + (targetId ?? "none"),
                    "使用 " + NativeView.ModelName(potion) + (target is null ? "" : " → " + NativeView.Text(target.Name)), () =>
                    {
                        CheckCurrent();
                        if (!potion.PassesCustomUsabilityCheck || !potion.IsValidTarget(target))
                            throw new InvalidOperationException("原生药水当前不可使用或目标已失效。");
                        NativeView.Invoke(holder, "DisableUntilPotionRemoved");
                        potion.EnqueueManualUse(target);
                        return Task.CompletedTask;
                    }, "use_potion", Identity(potion), targetId);
                frame.Actions[^1].Metadata = new { slot, modelId = potion.Id.ToString(),
                    usage = potion.Usage.ToString(), targetType = potion.TargetType.ToString() };
            }
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
