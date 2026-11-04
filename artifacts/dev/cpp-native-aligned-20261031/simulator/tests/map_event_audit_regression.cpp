#include <cstring>
#include <iostream>
#include "sts2/map.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/relics.h"
#include "sts2/run.h"

using namespace sts2;

// Native PotionFactory.GetPotionOptions pool order (Ironclad then shared).
#include "sts2/native_potion_pool.inc"

static int failures = 0;
static void check(const char *name, bool condition) {
    if (!condition) { std::cerr << name << " failed\n"; ++failures; }
}

static int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) {
        const EventInfo *info = event_info(i);
        if (info && std::strcmp(info->name, name) == 0) return i;
    }
    return -1;
}

static int count_points(const ActMap &map, MapPointType type) {
    int n = 0;
    for (int i = 0; i < map.pointCount; ++i)
        n += map.nodes[i].type == static_cast<int>(type);
    return n;
}

int main() {
    {
        RunContext rc;
        rc.init(12, 0);
        check("Pael's Growth can be obtained", rc.add_relic(RelicId::PAELS_GROWTH));
        check("Pael's Growth offers deck selection", rc.cardGrid.kind == 4);
        RunContext restored;
        check("Clone selection snapshot restores", RunContext::restore(rc.serialize(), restored));
        check("Clone selection can choose first card", rc.step({RunActionType::SELECT_GRID_CARD, 0}));
        check("Clone enchant amount is four", rc.deck[0].enchantment == EnchantmentId::CLONE && rc.deck[0].enchantmentAmount == 4);
        check("Clone selection closes", rc.cardGrid.kind == 0);
        const int originalCount = rc.deckCount;
        const std::uint16_t originalUid = rc.deck[0].uid;
        rc.screen = RunScreen::REST;
        check("Clone rest succeeds", rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone rest copies one card", rc.deckCount == originalCount + 1);
        check("Clone copy retains enchantment and distinct UID", rc.deck[originalCount].enchantment == EnchantmentId::CLONE && rc.deck[originalCount].uid != originalUid);
        rc.screen = RunScreen::REST;
        check("Clone rest repeats with original and clone", rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone copies grow from a fixed original snapshot", rc.deckCount == originalCount + 3);
    }
    {
        RunContext rc;
        rc.init(13, 0);
        rc.add_relic(RelicId::PAELS_GROWTH);
        rc.step({RunActionType::SELECT_GRID_CARD, 0});
        rc.add_relic(RelicId::BING_BONG);
        rc.add_relic(RelicId::LUCKY_FYSH);
        rc.screen = RunScreen::REST;
        const int count = rc.deckCount, gold = rc.gold;
        check("Clone rest with Bing Bong succeeds", rc.step({RunActionType::REST_CLONE, 0}));
        check("Bing Bong duplicates Clone addition", rc.deckCount == count + 2);
        check("Clone additions have unique UIDs", rc.deck[count].uid != rc.deck[count + 1].uid && rc.deck[count].uid != rc.deck[0].uid);
        check("Lucky Fysh triggers for both copies", rc.gold == gold + 30);
        while (rc.deckCount < MAX_DECK - 1)
            rc.deck[rc.deckCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 500 + rc.deckCount);
        rc.screen = RunScreen::REST;
        const int before = rc.deckCount, beforeGold = rc.gold;
        check("Clone capacity rejects entire action", !rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone capacity failure is atomic", rc.deckCount == before && rc.gold == beforeGold && rc.screen == RunScreen::REST);
    }
    for (unsigned seed = 0; seed < 20; ++seed) {
        ActMap a9, a10;
        Rng rng9(seed), rng10(seed);
        generate_act_map(a9, rng9, 2, 9);
        generate_act_map(a10, rng10, 2, 10);
        check("A9 final act has no second boss", a9.secondBossIdx == -1);
        check("A10 final act adds one boss node", a10.secondBossIdx >= 0 &&
              a10.pointCount == a9.pointCount + 1);
        check("A10 boss node consumes no map RNG", rng9.counter == rng10.counter);
        if (a10.secondBossIdx >= 0 && a10.bossIdx >= 0) {
            const MapNode &first = a10.nodes[a10.bossIdx];
            const MapNode &second = a10.nodes[a10.secondBossIdx];
            check("A10 second boss coordinate", a10.at(a10.mapLength + 1, MAP_WIDTH / 2) == a10.secondBossIdx);
            check("A10 first boss has one second boss child", first.childCount == 1 &&
                  first.children[0] == a10.secondBossIdx);
            check("A10 second boss has first boss parent", second.parentCount == 1 &&
                  second.parents[0] == a10.bossIdx && second.childCount == 0);
            check("A10 both nodes are bosses", first.type == static_cast<int>(MapPointType::BOSS) &&
                  second.type == static_cast<int>(MapPointType::BOSS));
        }
        for (int act : {0, 1}) {
            ActMap earlier;
            Rng rng(seed);
            generate_act_map(earlier, rng, act, 10);
            check("A10 earlier acts have one boss", earlier.secondBossIdx == -1);
        }
    }
    for (int act = 0; act < 3; ++act) {
        int elite0 = 0, elite1 = 0, rest5 = 0, rest6 = 0;
        for (unsigned seed = 0; seed < 100; ++seed) {
            ActMap maps[4];
            Rng rngs[] = {Rng(seed), Rng(seed), Rng(seed), Rng(seed)};
            const int asc[] = {0, 1, 5, 6};
            for (int i = 0; i < 4; ++i) generate_act_map(maps[i], rngs[i], act, asc[i]);
            elite0 += count_points(maps[0], MapPointType::ELITE);
            elite1 += count_points(maps[1], MapPointType::ELITE);
            rest5 += count_points(maps[2], MapPointType::REST);
            rest6 += count_points(maps[3], MapPointType::REST);
        }
        check("A1 increases elite count", elite1 > elite0);
        check("A6 decreases rest count", rest6 < rest5);
    }
    {
        RunContext rc;
        rc.init(2020, 0);
        event_begin(rc, event_id("DENSE_VEGETATION"), false);
        Rng shared(rc.seed, "DENSE_VEGETATION");
        check("Dense gold rolls on event entry", rc.eventData[0] == shared.next_int(61, 99));
        check("shared event RNG excludes player id", rc.eventRng.next_int(0, 100000) == shared.next_int(0, 100000));
        event_begin(rc, event_id("TABLET_OF_TRUTH"), false);
        Rng persistent(rc.seed, "TABLET_OF_TRUTH"); // single-player slot zero
        for (int i = 0; i < 3; ++i) {
            int candidates[MAX_DECK];
            int n = 0;
            for (int j = 0; j < rc.deckCount; ++j)
                if (card_upgradable(rc.deck[j])) candidates[n++] = j;
            const int selected = candidates[persistent.next_int(0, n - 1)];
            event_choose(rc, 0);
            check("multi-page event advances persistent RNG", rc.eventRng.counter == persistent.counter);
            check("multi-page event uses next RNG draw", rc.deck[selected].upgraded);
        }
    }
    {
        // TabletOfTruth.GetDecipherCost: 3, 6, 12, 24, then MaxHp - 1; the
        // fifth decipher upgrades every upgradable card and finishes.
        RunContext rc;
        rc.init(2025, 0);
        rc.hp = rc.maxHp = 100;
        event_begin(rc, event_id("TABLET_OF_TRUTH"), false);
        const int costs[5] = {3, 6, 12, 24, -1};
        int expectedMaxHp = 100;
        for (int i = 0; i < 5; ++i) {
            if (costs[i] < 0) {
                check("Tablet fifth cost is MaxHp - 1", rc.eventPage == 1);
                expectedMaxHp -= expectedMaxHp - 1;
            } else {
                expectedMaxHp -= costs[i];
            }
            check("Tablet decipher cost sequence", event_choose(rc, 0));
            check("Tablet MaxHp after decipher", rc.maxHp == expectedMaxHp);
        }
        check("Tablet finishes after five deciphers", rc.eventId < 0);
        int upgradable = 0;
        for (int i = 0; i < rc.deckCount; ++i) upgradable += card_upgradable(rc.deck[i]) ? 1 : 0;
        check("Tablet fifth decipher upgrades all", upgradable == 0);
    }
    {
        // Decipher whose cost is not below MaxHp drops MaxHp to 1 and kills.
        RunContext rc;
        rc.init(2026, 0);
        rc.hp = rc.maxHp = 30;
        event_begin(rc, event_id("TABLET_OF_TRUTH"), false);
        event_choose(rc, 0);  // 3
        event_choose(rc, 0);  // 6
        event_choose(rc, 0);  // 12 -> MaxHp 9
        check("Tablet third decipher leaves MaxHp 9", rc.maxHp == 9);
        event_choose(rc, 0);  // 24 >= 9
        check("Tablet lethal decipher kills", rc.hp == 0);
    }
    {
        // Wellspring.Bottle: PlayerRng.Rewards.NextItem over the concatenated
        // Ironclad + shared potion pools, offered as a PotionReward.
        RunContext rc;
        rc.init(2029, 0);
        event_begin(rc, event_id("WELLSPRING"), false);
        Rng rewards = rc.playerRng[PRNG_REWARDS];
        const int poolN = static_cast<int>(sizeof(NATIVE_IRONCLAD_POTIONS) /
                                           sizeof(NATIVE_IRONCLAD_POTIONS[0]));
        const int expected =
            static_cast<int>(NATIVE_IRONCLAD_POTIONS[rewards.next_int(0, poolN - 1)]);
        check("Wellspring bottle", event_choose(rc, 0));
        check("Wellspring bottle draws native pool order",
              rc.pendingPotionCount == 1 && rc.pendingPotions[0] == expected);
        check("Wellspring bottle consumes one Rewards draw",
              rc.playerRng[PRNG_REWARDS].counter == rewards.counter);
    }
    {
        // Wellspring.Bathe: remove one card, then add Guilty.
        RunContext rc;
        rc.init(2030, 0);
        const int before = rc.deckCount;
        event_begin(rc, event_id("WELLSPRING"), false);
        check("Wellspring bathe offers removal",
              event_choose(rc, 1) && rc.eventCardSelection == 6);
        check("Wellspring bathe removes a card", event_select_card(rc, 0));
        int guilty = 0;
        for (int i = 0; i < rc.deckCount; ++i) guilty += rc.deck[i].id == CardId::GUILTY ? 1 : 0;
        check("Wellspring bathe adds one Guilty", guilty == 1);
        check("Wellspring bathe keeps deck size", rc.deckCount == before);
    }
    {
        // LostWisp.CalculateVars: Gold = 60 + base.Rng.NextInt(-15, 16).
        RunContext rc;
        rc.init(2027, 0);
        rc.gold = 100;
        event_begin(rc, event_id("LOST_WISP"), false);
        Rng event(rc.seed, "LOST_WISP");
        check("LostWisp gold uses event RNG", rc.eventData[0] == 60 + event.next_int(-15, 15));
        const int gold = rc.gold;
        check("LostWisp search", event_choose(rc, 1));
        check("LostWisp search grants rolled gold", rc.gold == gold + rc.eventData[0]);
    }
    {
        RunContext rc;
        rc.init(2028, 0);
        int decay = 0;
        for (int i = 0; i < rc.deckCount; ++i) decay += rc.deck[i].id == CardId::DECAY ? 1 : 0;
        event_begin(rc, event_id("LOST_WISP"), false);
        check("LostWisp claim", event_choose(rc, 0));
        int decayAfter = 0;
        for (int i = 0; i < rc.deckCount; ++i) decayAfter += rc.deck[i].id == CardId::DECAY ? 1 : 0;
        check("LostWisp claim adds Decay", decayAfter == decay + 1);
        check("LostWisp claim obtains relic", run_has_relic(rc, RelicId::LOST_WISP));
    }
    {
        RunContext rc;
        rc.init(3, 2);
        rc.hp = 19; rc.maxHp = 100;
        event_begin(rc, event_id("OROBAS"), true);
        check("A2 Ancient heals 80 percent of missing HP", rc.hp == 83);
        event_begin(rc, event_id("NEOW"), true);
        check("A2 Neow heals 80 percent from zero", rc.hp == 80);
    }
    {
        RunContext rc;
        rc.init(4, 0);
        rc.deckCount = MAX_DECK;
        event_begin(rc, event_id("BRAIN_LEECH"), false);
        const int hp = rc.hp;
        check("full deck rejects event choice", !event_choose(rc, 1));
        check("rejected event choice keeps HP and deck", rc.hp == hp && rc.deckCount == MAX_DECK);
    }
    {
        RunContext rc;
        rc.init(5, 0);
        rc.add_relic(RelicId::BING_BONG);
        rc.deckCount = MAX_DECK;
        event_begin(rc, event_id("WELLSPRING"), false);
        check("Bing Bong accounts for both new cards", !event_choose(rc, 1));
        check("rejected replacement does not remove a card", rc.deckCount == MAX_DECK);
    }
    {
        RunContext rc;
        rc.init(6, 0);
        rc.gold = 500;
        rc.relicCount = MAX_RELICS;
        event_begin(rc, event_id("WELCOME_TO_WONGOS"), false);
        check("full relic inventory rejects purchase", !event_choose(rc, 0));
        check("rejected relic purchase keeps gold", rc.gold == 500);
    }
    for (unsigned seed = 0; seed < 500; ++seed) {
        RunContext rc;
        rc.seed = seed;
        rc.deckCount = 1;
        rc.deck[0] = rc.make_run_card(CardId::STRIKE_IRONCLAD, false);
        event_begin(rc, event_id("AROMA_OF_CHAOS"), false);
        check("Aroma transformation succeeds", event_choose(rc, 0));
        const CardDef &replacement = card_def(rc.deck[0].id);
        check("Aroma uses the original character pool", replacement.pool == CardPool::IRONCLAD);
        check("Aroma transformation is not basic or event", replacement.rarity == Rarity::COMMON ||
              replacement.rarity == Rarity::UNCOMMON || replacement.rarity == Rarity::RARE);
        check("Aroma excludes the original card", rc.deck[0].id != CardId::STRIKE_IRONCLAD);
    }
    // ---------------------------------------------------------------- batch 11
    {
        // StoneOfAllTime (:127111): NextItem over Player.Potions (non-null
        // slots in physical order). Lift discards it, gains 10 MaxHp, then
        // draws Rng.NextInt(100).
        RunContext rc;
        rc.init(2031, 0);
        rc.potionSlots = 3;
        rc.potions[0] = 0;
        rc.potions[1] = static_cast<int>(PotionId::FOUL_POTION);
        rc.potions[2] = static_cast<int>(PotionId::FIRE_POTION);
        rc.potionCount = 2;
        const int maxHp = rc.maxHp;
        event_begin(rc, event_id("STONE_OF_ALL_TIME"), false);
        Rng expected(rc.seed, "STONE_OF_ALL_TIME");
        check("Stone selects among non-null potions",
              rc.eventData[0] == expected.next_int(0, 1));
        const int removedSlot = rc.eventData[0] == 0 ? 1 : 2;
        check("Stone lift", event_choose(rc, 0));
        check("Stone lift gains 10 MaxHp", rc.maxHp == maxHp + 10);
        check("Stone lift discards the selected potion",
              rc.potionCount == 1 && rc.potions[removedSlot] == 0);
        check("Stone lift consumes one event draw",
              rc.eventRng.counter == expected.counter + 1);
    }
    {
        // Push: 6 HP loss, one Vigorous enchant (amount 8), then
        // Rng.NextInt(100) after the selection resolves.
        RunContext rc;
        rc.init(2032, 0);
        rc.hp = 50;
        rc.maxHp = 80;
        event_begin(rc, event_id("STONE_OF_ALL_TIME"), false);
        check("Stone push", event_choose(rc, 1) && rc.eventCardSelection == 3);
        check("Stone push loses 6 HP", rc.hp == 44);
        int pick = -1;
        for (int i = 0; i < rc.deckCount; ++i)
            if (event_card_selectable(rc, i)) { pick = i; break; }
        check("Stone push has a Vigorous target", pick >= 0);
        check("Stone push enchants", event_select_card(rc, pick));
        check("Stone push uses Vigorous 8",
              rc.deck[pick].enchantment == EnchantmentId::VIGOROUS &&
              rc.deck[pick].enchantmentAmount == 8);
        check("Stone push draws one event RNG value", rc.eventRng.counter == 1);
    }
    {
        // UnrestSite (:129075): Rest heals exactly the missing HP and adds
        // PoorSleep; Kill loses 8 MaxHp and pulls a front relic.
        RunContext rc;
        rc.init(2033, 0);
        rc.hp = 50;
        rc.maxHp = 100;
        const int deck = rc.deckCount;
        event_begin(rc, event_id("UNREST_SITE"), false);
        check("UnrestSite rest", event_choose(rc, 0));
        check("UnrestSite rest heals to full", rc.hp == 100);
        check("UnrestSite rest adds PoorSleep",
              rc.deckCount == deck + 1 && rc.deck[deck].id == CardId::POOR_SLEEP);
    }
    {
        RunContext rc;
        rc.init(2034, 0);
        rc.hp = rc.maxHp = 100;
        Rng rewards = rc.playerRng[PRNG_REWARDS];
        event_begin(rc, event_id("UNREST_SITE"), false);
        const int relics = rc.relicCount;
        check("UnrestSite kill", event_choose(rc, 1));
        check("UnrestSite kill loses 8 MaxHp", rc.maxHp == 92);
        check("UnrestSite kill obtains a relic", rc.relicCount == relics + 1);
        check("UnrestSite relic pull uses one Rewards draw",
              rc.playerRng[PRNG_REWARDS].counter == rewards.counter + 1);
    }
    {
        // Reflections.TouchAMirror (:126435): two downgrades then four
        // upgrades, each a single NextItem draw over the evolving list.
        RunContext rc;
        rc.init(2035, 0);
        for (int i = 0; i < 3; ++i) card_apply_upgrade(rc.deck[i]);
        event_begin(rc, event_id("REFLECTIONS"), false);
        check("Reflections touch", event_choose(rc, 0));
        check("Reflections touch draws six event values", rc.eventRng.counter == 6);
        int upgraded = 0;
        for (int i = 0; i < rc.deckCount; ++i) upgraded += rc.deck[i].upgraded ? 1 : 0;
        check("Reflections touch net +2 upgrades", upgraded == 5);
    }
    {
        // Reflections.Shatter (:126466): every deck card is cloned through
        // CardPileCmd.Add, so Egg relics upgrade clones and Bing Bong
        // duplicates each cloned card and the BadLuck curse.
        RunContext rc;
        rc.init(2036, 0);
        rc.deckCount = 3;
        rc.deck[0] = rc.make_run_card(CardId::STRIKE_IRONCLAD, false);
        rc.deck[1] = rc.make_run_card(CardId::DEFEND_IRONCLAD, false);
        rc.deck[2] = rc.make_run_card(CardId::DEFEND_IRONCLAD, false);
        check("Reflections fixture relic", rc.add_relic(RelicId::MOLTEN_EGG) &&
              rc.add_relic(RelicId::BING_BONG));
        event_begin(rc, event_id("REFLECTIONS"), false);
        check("Reflections shatter", event_choose(rc, 1));
        check("Reflections clones use deck-add hooks", rc.deckCount == 11);
        int strikes = 0, upgradedStrikes = 0;
        for (int i = 0; i < rc.deckCount; ++i) {
            if (rc.deck[i].id != CardId::STRIKE_IRONCLAD) continue;
            ++strikes;
            upgradedStrikes += rc.deck[i].upgraded ? 1 : 0;
        }
        // The original remains unupgraded; both clones pass through the egg.
        check("Molten Egg upgrades cloned attacks", strikes == 3 && upgradedStrikes == 2);
    }
    {
        // AromaOfChaos (:123533) transforms with CardCmd.TransformToRandom:
        // Quest cards fall back to the Colorless pool (the port used to
        // no-op them because no card shares CardPool.Quest).
        RunContext rc;
        rc.init(2037, 0);
        rc.deckCount = 1;
        rc.deck[0] = rc.make_run_card(CardId::BYRDONIS_EGG, false);
        event_begin(rc, event_id("AROMA_OF_CHAOS"), false);
        check("Aroma quest transform", event_choose(rc, 0));
        check("Aroma quest transform replaces the card",
              rc.deckCount == 1 && rc.deck[0].id != CardId::BYRDONIS_EGG);
        check("Aroma quest transform uses the Colorless pool",
              card_def(rc.deck[0].id).pool == CardPool::COLORLESS);
    }
    {
        // Tezcatara.GenerateInitialOptions (:127838): pool 1 is
        // VeryHotCocoa/YummyCookie plus NutritiousSoup only with a Basic
        // Strike-tagged deck card; pools 2/3 draw in their declared order.
        RunContext rc;
        rc.init(2038, 0);
        event_begin(rc, event_id("TEZCATARA"), false);
        Rng e(rc.seed, "TEZCATARA");
        const int p1[3] = {static_cast<int>(RelicId::VERY_HOT_COCOA),
                           static_cast<int>(RelicId::YUMMY_COOKIE),
                           static_cast<int>(RelicId::NUTRITIOUS_SOUP)};
        const int p2[3] = {static_cast<int>(RelicId::BIIIG_HUG),
                           static_cast<int>(RelicId::STORYBOOK),
                           static_cast<int>(RelicId::TOASTY_MITTENS)};
        const int p3[4] = {static_cast<int>(RelicId::GOLDEN_COMPASS),
                           static_cast<int>(RelicId::PUMPKIN_CANDLE),
                           static_cast<int>(RelicId::TOY_BOX),
                           static_cast<int>(RelicId::SEAL_OF_GOLD)};
        check("Tezcatara first pool", rc.eventRelics[0] == p1[e.next_int(0, 2)]);
        check("Tezcatara second pool", rc.eventRelics[1] == p2[e.next_int(0, 2)]);
        check("Tezcatara third pool", rc.eventRelics[2] == p3[e.next_int(0, 3)]);
    }
    {
        RunContext rc;
        rc.init(2039, 0);
        rc.deckCount = 1;
        rc.deck[0] = rc.make_run_card(CardId::DEFEND_IRONCLAD, false);
        event_begin(rc, event_id("TEZCATARA"), false);
        Rng e(rc.seed, "TEZCATARA");
        const int p1[2] = {static_cast<int>(RelicId::VERY_HOT_COCOA),
                           static_cast<int>(RelicId::YUMMY_COOKIE)};
        check("Tezcatara omits soup without a Basic Strike",
              rc.eventRelics[0] == p1[e.next_int(0, 1)]);
    }
    {
        // Nonupeipe (:125747): 9 relics plus BeautifulBracelet when at least
        // four deck cards accept Swift, then UnstableShuffle and take 3.
        RunContext rc;
        rc.init(2040, 0);
        event_begin(rc, event_id("NONUPEIPE"), false);
        Rng e(rc.seed, "NONUPEIPE");
        int list[10] = {static_cast<int>(RelicId::BLESSED_ANTLER),
                        static_cast<int>(RelicId::BRILLIANT_SCARF),
                        static_cast<int>(RelicId::DELICATE_FROND),
                        static_cast<int>(RelicId::DIAMOND_DIADEM),
                        static_cast<int>(RelicId::FUR_COAT),
                        static_cast<int>(RelicId::GLITTER),
                        static_cast<int>(RelicId::JEWELRY_BOX),
                        static_cast<int>(RelicId::LOOMING_FRUIT),
                        static_cast<int>(RelicId::SIGNET_RING)};
        int n = 9;
        int swift = 0;
        for (int i = 0; i < rc.deckCount; ++i)
            swift += card_can_enchant(rc.deck[i], EnchantmentId::SWIFT) ? 1 : 0;
        if (swift >= 4) list[n++] = static_cast<int>(RelicId::BEAUTIFUL_BRACELET);
        for (int i = n - 1; i > 0; --i) {
            const int j = e.next_int(0, i);
            const int t = list[i]; list[i] = list[j]; list[j] = t;
        }
        check("Nonupeipe first option", rc.eventRelics[0] == list[0]);
        check("Nonupeipe second option", rc.eventRelics[1] == list[1]);
        check("Nonupeipe third option", rc.eventRelics[2] == list[2]);
    }
    {
        // Vakuu (:129112): shuffle Pool1(3), Pool2(3), Pool3(4) and take the
        // first entry of each.
        RunContext rc;
        rc.init(2041, 0);
        event_begin(rc, event_id("VAKUU"), false);
        Rng e(rc.seed, "VAKUU");
        int a[3] = {static_cast<int>(RelicId::BLOOD_SOAKED_ROSE),
                    static_cast<int>(RelicId::WHISPERING_EARRING),
                    static_cast<int>(RelicId::FIDDLE)};
        int b[3] = {static_cast<int>(RelicId::PRESERVED_FOG),
                    static_cast<int>(RelicId::SERE_TALON),
                    static_cast<int>(RelicId::DISTINGUISHED_CAPE)};
        int c[4] = {static_cast<int>(RelicId::CHOICES_PARADOX),
                    static_cast<int>(RelicId::MUSIC_BOX),
                    static_cast<int>(RelicId::LORDS_PARASOL),
                    static_cast<int>(RelicId::JEWELED_MASK)};
        for (auto *pool : {&a, &b}) {
            for (int i = 2; i > 0; --i) {
                const int j = e.next_int(0, i);
                const int t = (*pool)[i]; (*pool)[i] = (*pool)[j]; (*pool)[j] = t;
            }
        }
        for (int i = 3; i > 0; --i) {
            const int j = e.next_int(0, i);
            const int t = c[i]; c[i] = c[j]; c[j] = t;
        }
        check("Vakuu pool 1", rc.eventRelics[0] == a[0]);
        check("Vakuu pool 2", rc.eventRelics[1] == b[0]);
        check("Vakuu pool 3", rc.eventRelics[2] == c[0]);
    }
    {
        // Darv (:124163): one NextItem per valid set (7 at act 0), then
        // UnstableShuffle and NextBool; true takes two relics plus DustyTome.
        RunContext rc;
        rc.init(2042, 0);
        event_begin(rc, event_id("DARV"), false);
        Rng e(rc.seed, "DARV");
        int list[7] = {static_cast<int>(RelicId::ASTROLABE),
                       static_cast<int>(RelicId::BLACK_STAR),
                       static_cast<int>(RelicId::CALLING_BELL),
                       static_cast<int>(RelicId::EMPTY_CAGE),
                       static_cast<int>(RelicId::PANDORAS_BOX),
                       static_cast<int>(RelicId::RUNIC_PYRAMID),
                       static_cast<int>(RelicId::SNECKO_EYE)};
        for (int i = 0; i < 7; ++i) e.next_int(0, 0);  // singleton sets draw
        for (int i = 6; i > 0; --i) {
            const int j = e.next_int(0, i);
            const int t = list[i]; list[i] = list[j]; list[j] = t;
        }
        if (e.next_bool()) {
            check("Darv DustyTome option", rc.eventRelics[2] == static_cast<int>(RelicId::DUSTY_TOME));
            check("Darv first two options", rc.eventRelics[0] == list[0] && rc.eventRelics[1] == list[1]);
        } else {
            check("Darv three options", rc.eventRelics[0] == list[0] &&
                  rc.eventRelics[1] == list[1] && rc.eventRelics[2] == list[2]);
        }
    }
    {
        // Reward-grid generation follows CardFactory.CreateForReward: one
        // rarity draw, one NextItem, then one RollForUpgrade float per card.
        RunContext rc;
        rc.init(2043, 0);
        Rng rewards = rc.playerRng[PRNG_REWARDS];
        event_begin(rc, event_id("ROOM_FULL_OF_CHEESE"), false);
        check("Cheese grid", event_choose(rc, 0) && rc.cardGrid.kind == 2);
        check("Cheese grid draws upgrade rolls",
              rc.playerRng[PRNG_REWARDS].counter == rewards.counter + 16);
    }
    {
        // Pael (:126105): Pool1; then Pool2 starts with Wing, adds Claw when
        // >=3 Goopy-enchantable cards and Tooth when >=5 removable cards,
        // duplicates itself (AddRange(list)), then appends Growth; Pool3 is
        // Eye/Blood plus Legion when the player has no event pet.
        RunContext rc;
        rc.init(2044, 0);
        rc.deckCount = 6;
        for (int i = 0; i < 4; ++i) rc.deck[i] = rc.make_run_card(CardId::DEFEND_IRONCLAD, false);
        for (int i = 4; i < 6; ++i) rc.deck[i] = rc.make_run_card(CardId::STRIKE_IRONCLAD, false);
        event_begin(rc, event_id("PAEL"), false);
        Rng e(rc.seed, "PAEL");
        const int p1[3] = {static_cast<int>(RelicId::PAELS_FLESH),
                           static_cast<int>(RelicId::PAELS_HORN),
                           static_cast<int>(RelicId::PAELS_TEARS)};
        const int p2[7] = {static_cast<int>(RelicId::PAELS_WING),
                           static_cast<int>(RelicId::PAELS_CLAW),
                           static_cast<int>(RelicId::PAELS_TOOTH),
                           static_cast<int>(RelicId::PAELS_WING),
                           static_cast<int>(RelicId::PAELS_CLAW),
                           static_cast<int>(RelicId::PAELS_TOOTH),
                           static_cast<int>(RelicId::PAELS_GROWTH)};
        const int p3[3] = {static_cast<int>(RelicId::PAELS_EYE),
                           static_cast<int>(RelicId::PAELS_BLOOD),
                           static_cast<int>(RelicId::PAELS_LEGION)};
        check("Pael pool 1", rc.eventRelics[0] == p1[e.next_int(0, 2)]);
        check("Pael duplicated pool 2", rc.eventRelics[1] == p2[e.next_int(0, 6)]);
        check("Pael pool 3", rc.eventRelics[2] == p3[e.next_int(0, 2)]);
    }
    return failures == 0 ? 0 : 1;
}
