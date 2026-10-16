using System.Collections;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using Godot;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;

namespace SlayTheModel.Headless;

internal sealed record NativeSpecialAction(
    string Id, string LabelEn, string LabelZh, string Kind, object? Payload,
    Func<Task> ExecuteAsync);

internal sealed record NativeSpecialScreen(
    string Kind, object Observation, IReadOnlyList<NativeSpecialAction> Actions);

/// <summary>
/// Public-state projections and input adapters for the original v0.111.0 scenes.
/// Actions invoke the original input callback; they never complete a choice Task,
/// grant a reward, mutate a selected set, or reproduce an event's game rules.
/// Call only with the active native surface, on the Godot main thread.
/// </summary>
internal static class NativeSpecialScreens
{
    private sealed class PendingOperation { internal Task? Task; }
    private sealed class CardOrder { internal readonly Guid Token = Guid.NewGuid(); }
    private static readonly ConditionalWeakTable<Node, PendingOperation> PendingOperations = new();
    private static readonly ConditionalWeakTable<CardModel, CardOrder> CardOrders = new();

    internal static NativeSpecialScreen? Capture(
        Node surfaceRoot, Func<CardModel, object> describeCard)
    {
        var result = CaptureNative(surfaceRoot, describeCard);
        if (result is null) return null;
        var pending = PendingOperations.GetValue(surfaceRoot, _ => new PendingOperation());
        if (pending.Task is { IsCompleted: false }) return result with { Actions = [] };
        return result with
        {
            Actions = result.Actions.Select(action => action with
            {
                ExecuteAsync = () =>
                {
                    if (pending.Task is { IsCompleted: false })
                        throw new InvalidOperationException("This native screen is still resolving its previous input.");
                    var task = action.ExecuteAsync();
                    pending.Task = task;
                    return task;
                },
            }).ToArray(),
        };
    }

    private static NativeSpecialScreen? CaptureNative(
        Node surfaceRoot, Func<CardModel, object> describeCard)
    {
        if (!AliveVisible(surfaceRoot)) return null;
        if (surfaceRoot is NCrystalSphereScreen sphere) return CrystalSphere(sphere);
        if (surfaceRoot is NCardGridSelectionScreen grid) return CardGrid(grid, describeCard);
        if (surfaceRoot is NCardRewardSelectionScreen reward) return CardReward(reward, describeCard);
        if (surfaceRoot is NChooseACardSelectionScreen singleCard) return ChooseCard(singleCard, describeCard);
        if (surfaceRoot is NChooseABundleSelectionScreen bundles) return Bundles(bundles, describeCard);
        if (surfaceRoot.GetType().Name == "NChooseARelicSelection") return Relics(surfaceRoot);
        if (surfaceRoot.GetType().Name == "NTreasureRoom"
            && Read(surfaceRoot, "_isRelicCollectionOpen") is true)
            return Treasure(surfaceRoot);
        if (surfaceRoot is NMerchantInventory inventory) return Merchant(inventory, describeCard);
        if (surfaceRoot.GetType().Name is "NFakeMerchant" or "NMerchantRoom")
        {
            var shop = Descendants(surfaceRoot).OfType<NMerchantInventory>()
                .FirstOrDefault(candidate => AliveVisible(candidate) && candidate.IsOpen);
            if (shop is not null) return Merchant(shop, describeCard);
        }
        return null;
    }

    private static NativeSpecialScreen CardGrid(
        NCardGridSelectionScreen screen, Func<CardModel, object> describeCard)
    {
        var actions = new List<NativeSpecialAction>();
        var grid = Read(screen, "_grid") as Node;
        // Native card holders are a virtualized sliding window. Read the grid's
        // full filtered list, including candidates below the current scroll area.
        // Independent tie-breaks prevent equal native sort keys retaining Draw order.
        var cards = Objects(Read(grid, "_cards")).OfType<CardModel>()
            .OrderBy(card => card.Id.ToString(), StringComparer.Ordinal)
            .ThenBy(card => card.CurrentUpgradeLevel)
            .ThenBy(card => CardOrders.GetValue(card, _ => new CardOrder()).Token).ToArray();
        var selected = Objects(Read(screen, "_selectedCards")).OfType<CardModel>().ToHashSet();
        if (Read(screen, "_selectedCard") is CardModel single) selected.Add(single);
        var choices = cards.Select((card, index) => new
        {
            index,
            selected = selected.Contains(card),
            card = describeCard(card),
        }).ToArray();

        // The original grid already applies the CardSelectCmd filter.
        // Preview cards are deliberately excluded: they may be transformed clones.
        for (var index = 0; index < cards.Length; index++)
        {
            var card = cards[index];
            if (!GridAcceptsInput(grid)) continue;
            var zhVerb = selected.Contains(card) ? "取消选择" : "选择";
            actions.Add(new($"card:{index}", $"Select {NativeView.English(card)}", $"{zhVerb} {CardTitle(card)}",
                "select_card", new { index }, () =>
                {
                    RequireVisible(screen);
                    if (!GridAcceptsInput(grid)
                        || !Objects(Read(grid, "_cards")).Any(candidate => ReferenceEquals(candidate, card)))
                        throw new InvalidOperationException("The native card candidate is no longer selectable.");
                    return InvokeTask(screen, "OnCardClicked", card);
                }));
        }
        AddButtons(screen, actions);
        var prefs = Read(screen, "_prefs");
        return new("card_selection", new
        {
            title = "卡牌选择",
            description = NativeView.Text(Read(prefs, "Prompt")),
            minSelect = Read(prefs, "MinSelect"),
            maxSelect = Read(prefs, "MaxSelect"),
            cancelable = Read(prefs, "Cancelable"),
            choices,
            entities = cards.Select(describeCard).ToArray(),
        }, actions);
    }

    private static NativeSpecialScreen ChooseCard(
        NChooseACardSelectionScreen screen, Func<CardModel, object> describeCard)
    {
        var actions = new List<NativeSpecialAction>();
        var row = Read(screen, "_cardRow") as Node;
        var holders = row is null ? [] : Descendants(row).OfType<NCardHolder>()
            .Where(holder => AliveVisible(holder) && holder.CardModel is not null).ToArray();
        var choices = holders.Select((holder, index) => new
        {
            index, card = describeCard(holder.CardModel!),
        }).ToArray();
        if (Read(screen, "_screenComplete") is not true
            && Read(screen, "_openedTicks") is ulong opened && Time.GetTicksMsec() - opened > 350)
        {
            for (var index = 0; index < holders.Length; index++)
            {
                var holder = holders[index];
                if (!CardClickable(holder) || holder.CardModel is not { } card) continue;
                actions.Add(new($"choose_card:{index}", $"Choose {NativeView.English(card)}",
                    $"选择 {CardTitle(card)}", "choose_card", new { index }, () =>
                    {
                        RequireVisible(screen);
                        if (!CardClickable(holder) || !ReferenceEquals(holder.CardModel, card)
                            || Read(screen, "_screenComplete") is true)
                            throw new InvalidOperationException("The native card choice has changed.");
                        return InvokeTask(screen, "SelectHolder", holder);
                    }));
            }
        }
        AddButtons(screen, actions);
        return new("choose_card", new
        {
            title = "选择一张卡牌", description = "从以下候选中选择一张卡牌。", choices,
            entities = choices.Select(choice => choice.card).ToArray(),
        }, actions);
    }

    private static NativeSpecialScreen CardReward(
        NCardRewardSelectionScreen screen, Func<CardModel, object> describeCard)
    {
        var actions = new List<NativeSpecialAction>();
        var row = Read(screen, "_cardRow") as Node;
        var holders = row is null ? [] : Descendants(row).OfType<NCardHolder>().ToArray();
        var choices = holders.Where(holder => AliveVisible(holder) && holder.CardModel is not null)
            .Select((holder, index) => new
        {
            index,
            card = describeCard(holder.CardModel!),
        }).ToArray();
        foreach (var holder in holders.Where(CardClickable))
        {
            if (holder.CardModel is not { } card) continue;
            actions.Add(new($"reward_card:{holder.GetInstanceId()}", $"Take {NativeView.English(card)}",
                $"拿取 {CardTitle(card)}", "choose_reward_card", null, () =>
                {
                    RequireVisible(screen);
                    if (!CardClickable(holder)) throw new InvalidOperationException("Reward card is disabled.");
                    return InvokeTask(screen, "SelectCard", holder);
                }));
        }
        // Each alternative's original Released callback supplies its own index.
        // This preserves reroll/skip/other relic alternatives and subsequent rewards.
        AddButtons(screen, actions);
        return new("card_reward", new
        {
            title = "卡牌奖励", description = "选择一张卡牌，或选择下方的奖励替代选项。", choices,
            entities = choices.Select(choice => choice.card).ToArray(),
        }, actions);
    }

    private static NativeSpecialScreen Bundles(
        NChooseABundleSelectionScreen screen, Func<CardModel, object> describeCard)
    {
        var actions = new List<NativeSpecialAction>();
        var row = Read(screen, "_bundleRow") as Node;
        var bundles = row is null ? [] : Descendants(row).OfType<NCardBundle>().ToArray();
        var choices = bundles.Select((bundle, index) => new
        {
            index,
            selected = ReferenceEquals(Read(screen, "_selectedBundle"), bundle),
            cards = bundle.Bundle.Select(describeCard).ToArray(),
        }).ToArray();
        for (var index = 0; index < bundles.Length; index++)
        {
            var bundle = bundles[index];
            if (!Enabled(bundle.Hitbox)) continue;
            actions.Add(new($"bundle:{index}", $"Choose bundle {index + 1}",
                $"选择第 {index + 1} 组卡牌", "choose_bundle", new { index }, () =>
                {
                    RequireVisible(screen);
                    RequireEnabled(bundle.Hitbox);
                    return InvokeTask(screen, "OnBundleClicked", bundle);
                }));
        }
        AddButtons(screen, actions);
        return new("card_bundle", new
        {
            title = "卡牌包选择", description = "选择一组卡牌，再确认或返回。", choices,
            entities = choices.SelectMany(choice => choice.cards).ToArray(),
        }, actions);
    }

    private static NativeSpecialScreen Relics(Node screen)
    {
        var actions = new List<NativeSpecialAction>();
        var row = Read(screen, "_relicRow") as Node;
        var holders = row is null ? [] : Descendants(row)
            .Where(node => node.GetType().Name == "NRelicBasicHolder" && AliveVisible(node)).ToArray();
        var choices = new List<object>();
        var entities = new List<HeadlessEntity>();
        for (var index = 0; index < holders.Length; index++)
        {
            var holder = holders[index];
            var model = Read(holder, "_model") as RelicModel;
            if (model is null) continue;
            entities.Add(ModelEntity(model, $"relic-choice:{index}"));
            choices.Add(new { index, modelId = model.Id.ToString(), title = Formatted(Read(model, "Title")) });
            if (Read(screen, "_relicSelected") is true || Read(screen, "_screenComplete") is true) continue;
            if (holder is NClickableControl clickable && !Enabled(clickable)) continue;
            actions.Add(new($"relic:{index}", $"Choose {NativeView.English(model)}",
                $"选择 {NativeView.ModelName(model)}", "choose_relic",
                new { index, entityId = $"relic-choice:{index}" }, () =>
                {
                    RequireVisible(screen);
                    RequireVisible(holder);
                    if (Read(screen, "_relicSelected") is true || Read(screen, "_screenComplete") is true)
                        throw new InvalidOperationException("The native relic choice has already completed.");
                    return InvokeTask(screen, "SelectHolder", holder);
                }));
        }
        AddButtons(screen, actions);
        return new("relic_selection", new
        {
            title = "遗物选择", description = VisibleText(screen), choices, entities,
        }, actions);
    }

    private static NativeSpecialScreen Merchant(
        NMerchantInventory inventory, Func<CardModel, object> describeCard)
    {
        var actions = new List<NativeSpecialAction>();
        var choices = new List<object>();
        var entities = new List<object>();
        if (!inventory.IsOpen) return new("merchant", new { title = "商店", choices, entities }, actions);
        var slots = inventory.GetAllSlots().Where(AliveVisible).ToArray();
        for (var index = 0; index < slots.Length; index++)
        {
            var slot = slots[index];
            var entry = slot.Entry;
            if (entry is null || !entry.IsStocked) continue;
            var card = entry is MerchantCardEntry cardEntry ? cardEntry.CreationResult?.Card : null;
            var model = Read(entry, "Model");
            var id = card?.Id.ToString() ?? Read(model, "Id")?.ToString()
                ?? (entry is MerchantCardRemovalEntry ? "CARD_REMOVAL" : entry.GetType().Name);
            var title = card is not null ? CardTitle(card)
                : model is AbstractModel abstractModel ? NativeView.ModelName(abstractModel)
                : entry is MerchantCardRemovalEntry ? "删牌服务" : id;
            object itemEntity;
            if (card is not null)
            {
                itemEntity = describeCard(card);
                if (itemEntity is HeadlessEntity display) display.Price = entry.Cost;
            }
            else if (model is AbstractModel product)
            {
                var display = ModelEntity(product, $"merchant:{index}");
                display.Price = entry.Cost;
                itemEntity = display;
            }
            else
                itemEntity = new HeadlessEntity
                {
                    Id = $"merchant:{index}", Kind = "service", Name = title,
                    EnName = "Card removal", Description = "从牌组中移除一张原生允许移除的牌。",
                    Price = entry.Cost,
                };
            entities.Add(itemEntity);
            choices.Add(new
            {
                index, kind = entry.GetType().Name, modelId = id, title,
                cost = entry.Cost, affordable = entry.EnoughGold,
                card = card is null ? null : itemEntity,
            });
            if (!entry.EnoughGold || !Enabled(slot.Hitbox) || Read(inventory, "_isInputBlocked") is true)
                continue;
            var enTitle = card is not null ? NativeView.English(card)
                : model is AbstractModel productModel ? NativeView.English(productModel) : "Card removal";
            actions.Add(new($"buy:{index}", $"Buy {enTitle} ({entry.Cost} gold)",
                $"购买 {title}（{entry.Cost} 金币）", "buy", new
                {
                    index, modelId = id, cost = entry.Cost,
                    entityId = (itemEntity as HeadlessEntity)?.Id,
                    description = (itemEntity as HeadlessEntity)?.Description,
                }, () =>
                {
                    RequireVisible(inventory);
                    RequireEnabled(slot.Hitbox);
                    if (!inventory.IsOpen || Read(inventory, "_isInputBlocked") is true
                        || !ReferenceEquals(slot.Entry, entry) || !entry.IsStocked || !entry.EnoughGold)
                        throw new InvalidOperationException("The original merchant offer is no longer purchasable.");
                    // The slot's callback retains both normal and FakeMerchant event hooks,
                    // the transaction's Task, restocking, and nested selection screens.
                    return InvokeTask(slot, "OnSelected");
                }));
        }
        AddButtons(inventory, actions);
        return new("merchant", new
        {
            title = "商店", description = VisibleText(inventory), choices, entities,
        }, actions);
    }

    private static NativeSpecialScreen Treasure(Node room)
    {
        var actions = new List<NativeSpecialAction>();
        var entities = new List<HeadlessEntity>();
        var collection = Read(room, "_relicCollection") as Node;
        var holders = collection is null ? [] : Descendants(collection).OfType<NButton>()
            .Where(button => button.GetType().Name == "NTreasureRoomRelicHolder" && AliveVisible(button)).ToArray();
        foreach (var holder in holders)
        {
            if (Read(Read(holder, "Relic"), "Model") is not RelicModel model) continue;
            string id = $"treasure:{Read(holder, "Index")}";
            var entity = ModelEntity(model, id);
            entities.Add(entity);
            if (!Enabled(holder) || Read(collection, "_openedTicks") is not ulong opened
                || Time.GetTicksMsec() - opened <= 200) continue;
            actions.Add(new(id, $"Take {NativeView.English(model)}", $"拿取 {NativeView.ModelName(model)}",
                "take_relic", new { entityId = id, description = entity.Description }, () =>
                {
                    RequireVisible(room);
                    RequireEnabled(holder);
                    if (Read(room, "_isRelicCollectionOpen") is not true
                        || !ReferenceEquals(Read(Read(holder, "Relic"), "Model"), model))
                        throw new InvalidOperationException("The native treasure reward has changed.");
                    holder.ForceClick();
                    return Task.CompletedTask;
                }));
        }
        AddButtons(room, actions, button => button.GetType().Name != "NTreasureRoomRelicHolder");
        return new("treasure", new { title = "宝箱遗物", description = VisibleText(room), entities }, actions);
    }

    private static NativeSpecialScreen CrystalSphere(NCrystalSphereScreen screen)
    {
        var actions = new List<NativeSpecialAction>();
        var entity = Read(screen, "_entity") as CrystalSphereMinigame
            ?? throw new InvalidOperationException("Crystal Sphere native model is unavailable.");
        var revealed = Objects(Read(entity, "_revealed")).OfType<CrystalSphereItem>().ToHashSet();
        var nodes = Descendants(screen).OfType<NCrystalSphereCell>()
            .Where(AliveVisible).OrderBy(node => node.Entity.Y).ThenBy(node => node.Entity.X).ToArray();
        var cells = nodes.Select(node =>
        {
            var cell = node.Entity;
            // Never inspect Item while hidden. Fully revealed types describe only
            // already earned/public rewards, never the board's pre-generated layout.
            var item = cell.IsHidden ? null : cell.Item;
            return new
            {
                x = cell.X, y = cell.Y, hidden = cell.IsHidden, revealed = !cell.IsHidden,
                fragment = item is not null,
                revealedItem = item is not null && revealed.Contains(item) ? item.GetType().Name : null,
                label = cell.IsHidden ? "?" : item is null ? "·" : revealed.Contains(item)
                    ? CrystalItemLabel(item) : "碎片",
            };
        }).ToArray();
        if (!entity.IsFinished && entity.DivinationCount > 0)
        {
            foreach (var node in nodes.Where(node => node.Entity.IsHidden && Enabled(node)))
            {
                var cell = node.Entity;
                actions.Add(new($"cell:{cell.X}:{cell.Y}", $"Reveal ({cell.X + 1}, {cell.Y + 1})",
                    $"占卜第 {cell.Y + 1} 行、第 {cell.X + 1} 列", "reveal_cell", new { x = cell.X, y = cell.Y }, () =>
                    {
                        RequireVisible(screen);
                        RequireEnabled(node);
                        if (entity.IsFinished || entity.DivinationCount <= 0 || !cell.IsHidden)
                            throw new InvalidOperationException("The native divination cell is no longer available.");
                        return InvokeTask(screen, "OnCellClicked", node);
                    }));
            }
        }
        AddButtons(screen, actions);
        return new("crystal_sphere", new
        {
            title = "水晶球占卜", description = VisibleText(screen),
            board = new
            {
                width = entity.GridSize.X, height = entity.GridSize.Y,
                remaining = entity.DivinationCount, tool = entity.CrystalSphereTool.ToString(),
                finished = entity.IsFinished, cells,
            },
        }, actions);
    }

    private static void AddButtons(Node root, List<NativeSpecialAction> actions,
        Func<NButton, bool>? include = null)
    {
        foreach (var button in Descendants(root).OfType<NButton>().Where(Enabled))
        {
            if (include is not null && !include(button)) continue;
            // Card/merchant/bundle input has dedicated semantic bindings above.
            // Their hitboxes can be several wrapper nodes below the owner.
            if (HasSemanticOwner(button, root)) continue;
            var text = VisibleText(button);
            var name = button.GetType().Name;
            // Peeking and viewing upgrades are display controls, never choices.
            if (name.Contains("Peek", StringComparison.Ordinal)) continue;
            var (enLabel, zhLabel) = ButtonLabels(root, button);
            var label = string.IsNullOrWhiteSpace(text) ? zhLabel : text;
            actions.Add(new($"button:{button.GetInstanceId()}", enLabel, label,
                "native_button", new { control = name }, () =>
                {
                    RequireVisible(root);
                    RequireEnabled(button);
                    button.ForceClick();
                    return Task.CompletedTask;
                }));
        }
    }

    private static bool HasSemanticOwner(Node button, Node root)
    {
        for (var ancestor = button.GetParent(); ancestor is not null && !ReferenceEquals(ancestor, root);
             ancestor = ancestor.GetParent())
            if (ancestor is NCardHolder or NCardBundle or NMerchantSlot
                || ancestor.GetType().Name is "NRelicBasicHolder" or "NTreasureRoomRelicHolder")
                return true;
        return false;
    }

    private static (string En, string Zh) ButtonLabels(Node root, NButton button)
    {
        if (ReferenceEquals(Read(root, "_smallDivinationButton"), button))
            return ("Small divination", "小型占卜");
        if (ReferenceEquals(Read(root, "_bigDivinationButton"), button))
            return ("Big divination", "大型占卜");
        if (button is NCardRewardAlternativeButton
            && Read(root, "_rewardAlternativesContainer") is Node container)
        {
            var buttons = Descendants(container).OfType<NCardRewardAlternativeButton>().Where(AliveVisible).ToArray();
            int index = Array.FindIndex(buttons, item => ReferenceEquals(item, button));
            var options = Objects(Read(root, "_extraOptions")).ToArray();
            if (index >= 0 && index < options.Length && Read(options[index], "Title") is LocString title)
                return (NativeView.English(title, ""), NativeView.Text(title));
        }
        return button.GetType().Name switch
        {
            "NConfirmButton" => ("Confirm", "确认"),
            "NBackButton" => ("Back", "返回"),
            "NProceedButton" => ("Continue", "继续"),
            "NChoiceSelectionSkipButton" => ("Skip", "跳过"),
            _ => ("", "选择"),
        };
    }

    private static bool CardClickable(NCardHolder holder) => AliveVisible(holder)
        && holder.CardModel is not null && Read(holder, "_isClickable") is true
        && Enabled(holder.Hitbox);

    private static bool GridAcceptsInput(Node? grid) => grid is Control control && AliveVisible(grid)
        && control.FocusBehaviorRecursive != Control.FocusBehaviorRecursiveEnum.Disabled;

    private static HeadlessEntity ModelEntity(AbstractModel model, string id) => new()
    {
        Id = id, Kind = model is RelicModel ? "relic" : "potion", Name = NativeView.ModelName(model),
        EnName = NativeView.English(model), ModelId = model.Id.ToString(),
        Description = NativeView.Text(Read(model, "DynamicDescription") ?? Read(model, "Description")),
    };

    private static string CrystalItemLabel(CrystalSphereItem item) => item.GetType().Name switch
    {
        "CrystalSphereGold" => "金币", "CrystalSphereCurse" => "诅咒",
        "CrystalSphereCardReward" => "卡牌", "CrystalSpherePotion" => "药水",
        "CrystalSphereRelic" => "遗物", _ => "物品",
    };

    private static string CardTitle(CardModel card) => NativeView.ModelName(card);

    private static bool AliveVisible(Node node) => GodotObject.IsInstanceValid(node)
        && !node.IsQueuedForDeletion() && node.IsInsideTree()
        && (node is not CanvasItem item || item.IsVisibleInTree());

    private static bool Enabled(NClickableControl? node) => node is not null && AliveVisible(node) && node.IsEnabled;

    private static void RequireVisible(Node node)
    {
        if (!AliveVisible(node)) throw new InvalidOperationException("The native screen has changed.");
    }

    private static void RequireEnabled(NClickableControl node)
    {
        if (!Enabled(node)) throw new InvalidOperationException("The native control is disabled.");
    }

    private static IEnumerable<Node> Descendants(Node root)
    {
        foreach (var child in root.GetChildren())
        {
            yield return child;
            foreach (var descendant in Descendants(child)) yield return descendant;
        }
    }

    private static string VisibleText(Node node) => string.Join("\n", Descendants(node).Prepend(node)
        .Where(AliveVisible).Select(value => value switch
        {
            RichTextLabel rich => rich.GetParsedText(),
            Label label => label.Text,
            _ => null,
        }).Where(value => !string.IsNullOrWhiteSpace(value)).Distinct());

    private static IEnumerable<object> Objects(object? value) => value is IEnumerable collection
        ? collection.Cast<object>() : [];

    private static object? Read(object? instance, string name)
    {
        if (instance is null) return null;
        for (var type = instance.GetType(); type is not null; type = type.BaseType)
        {
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
            var property = type.GetProperty(name, flags);
            if (property is not null) return property.GetValue(instance);
            var field = type.GetField(name, flags);
            if (field is not null) return field.GetValue(instance);
        }
        return null;
    }

    private static string? Formatted(object? loc)
    {
        if (loc is null) return null;
        var formatter = loc.GetType().GetMethod("GetFormattedText", Type.EmptyTypes);
        return formatter?.Invoke(loc, null) as string;
    }

    private static Task InvokeTask(object target, string methodName, params object[] arguments)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        MethodInfo? method = null;
        for (var type = target.GetType(); type is not null && method is null; type = type.BaseType)
            method = type.GetMethods(flags).FirstOrDefault(candidate => candidate.Name == methodName
                && candidate.GetParameters().Length == arguments.Length
                && candidate.GetParameters().Zip(arguments).All(pair => pair.First.ParameterType.IsInstanceOfType(pair.Second)));
        if (method is null) throw new MissingMethodException(target.GetType().FullName, methodName);
        try { return method.Invoke(target, arguments) as Task ?? Task.CompletedTask; }
        catch (TargetInvocationException exception) when (exception.InnerException is not null)
        {
            ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
            throw;
        }
    }
}
