// Monster creation at combat start follows native v0.111.0 (ruleset v9, 2026-11-18):
// * EncounterModel.GenerateMonstersWithSlots uses the encounter's own
//   Rng(RunState.Rng.Seed + TotalFloor + hash(Id.Entry)); no game stream picks the roster;
// * Creature.SetUniqueMonsterHpValue: HP on the Niche stream, unique among the enemies;
// * starting moves fixed by the encounter (StarterMoveIdx, ScreamFirst, IsFront, ...).
// Expected rosters below are transcribed from the native Models/Encounters/*.cs files.
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/run.h"
#include <cstdio>
#include <set>
#include <string>
#include <vector>

using namespace sts2;

static int failures = 0;
static void check(bool ok, const std::string &label) {
    if (!ok) { ++failures; std::printf("FAIL %s\n", label.c_str()); }
}

static BattleContext start(Encounter enc, std::uint64_t encounterSeed, int asc = 0) {
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    BattleContext b;
    b.init(enc, 777, deck, 10, asc, 80, 80, nullptr, 0, nullptr, 0, BASE_POTION_SLOTS, 0, 3, 0, 0,
           nullptr, nullptr, nullptr, nullptr, encounterSeed);
    return b;
}

static std::vector<MonsterId> roster(const BattleContext &b) {
    std::vector<MonsterId> out;
    for (int i = 0; i < b.monsterCount; ++i) out.push_back(b.monsters[i].id);
    return out;
}

int main() {
    using M = MonsterId;
    // 1. Fixed rosters corrected from native.
    check(roster(start(Encounter::SETUP_AXEBOTS_NORMAL, 1)) == std::vector<M>{M::AXEBOT}, "Axebots: one Axebot");
    check(roster(start(Encounter::SETUP_EXOSKELETONS_NORMAL, 1)) == std::vector<M>(4, M::EXOSKELETON), "Exoskeletons normal: 4");
    check(roster(start(Encounter::SETUP_EXOSKELETONS_WEAK, 1)) == std::vector<M>(3, M::EXOSKELETON), "Exoskeletons weak: 3");
    check(roster(start(Encounter::SETUP_GREMLIN_MERC_NORMAL, 1)) == std::vector<M>{M::GREMLIN_MERC}, "Gremlin merc alone at start");
    check(roster(start(Encounter::SETUP_SLUMBERING_BEETLE_NORMAL, 1)) ==
              (std::vector<M>{M::BOWLBUG_ROCK, M::BOWLBUG_SILK, M::SLUMBERING_BEETLE}), "Slumbering beetle roster");
    {
        const BattleContext b = start(Encounter::SETUP_TUNNELER_NORMAL, 1);
        check(roster(b) == (std::vector<M>{M::CHOMPER, M::TUNNELER}), "Tunneler normal roster");
        check(b.monsters[0].move == 1, "Tunneler's Chomper screams first");
    }

    // 2. Random rosters: shapes over many encounter seeds, and that the roster depends
    //    only on the encounter seed.
    std::set<std::vector<M>> slimesWeak, raiders, bowl;
    for (std::uint64_t s = 1; s <= 400; ++s) {
        const BattleContext a = start(Encounter::SETUP_SLIMES_WEAK, s);
        const auto r = roster(a);
        check(r.size() == 3 && r[0] != r[2] &&
                  (r[0] == M::LEAF_SLIME_S || r[0] == M::TWIG_SLIME_S) &&
                  (r[1] == M::LEAF_SLIME_M || r[1] == M::TWIG_SLIME_M),
              "SlimesWeak = small, medium, the other small");
        slimesWeak.insert(r);
        const auto rr = roster(start(Encounter::SETUP_RUBY_RAIDERS_NORMAL, s));
        check(rr.size() == 3 && rr[0] != rr[1] && rr[0] != rr[2] && rr[1] != rr[2], "Ruby raiders distinct");
        raiders.insert(rr);
        const auto bb = roster(start(Encounter::SETUP_BOWLBUGS_NORMAL, s));
        check(bb.size() == 3 && bb[0] == M::BOWLBUG_ROCK && bb[1] != bb[2] && bb[1] != M::BOWLBUG_ROCK, "Bowlbugs normal");
        bowl.insert(bb);
        const auto bw = roster(start(Encounter::SETUP_BOWLBUGS_WEAK, s));
        check(bw.size() == 2 && bw[0] == M::BOWLBUG_ROCK && (bw[1] == M::BOWLBUG_EGG || bw[1] == M::BOWLBUG_NECTAR), "Bowlbugs weak");
        const auto st = roster(start(Encounter::SETUP_SLITHERING_STRANGLER_NORMAL, s));
        check(!st.empty() && st.back() == M::SLITHERING_STRANGLER && st.size() <= 3, "Strangler last");
        const BattleContext c = start(Encounter::SETUP_CORPSE_SLUGS_NORMAL, s);
        check(c.monsters[0].move != c.monsters[1].move && c.monsters[1].move != c.monsters[2].move &&
                  c.monsters[0].move != c.monsters[2].move, "Corpse slugs start with different moves");
        const BattleContext d = start(Encounter::SETUP_DECIMILLIPEDE_ELITE, s);
        std::set<int> hp{d.monsters[0].maxHp, d.monsters[1].maxHp, d.monsters[2].maxHp};
        check(hp.size() == 3 && d.monsters[0].maxHp % 2 == 0 && d.monsters[1].maxHp % 2 == 0, "Decimillipede even, unique HP");
        const BattleContext p = start(Encounter::SETUP_PUNCH_OFF, s);
        check(p.monsters[0].move == 2 && p.monsters[1].move == 0 && p.monsters[0].hp >= 46 && p.monsters[0].hp <= 53,
              "Punch off: fast punch first, reduction 2..9");
    }
    check(slimesWeak.size() == 4, "SlimesWeak: all 4 combinations occur");
    check(raiders.size() == 60, "Ruby raiders: all 60 ordered picks occur");
    check(bowl.size() == 6, "Bowlbugs normal: all 6 ordered worker pairs occur");
    check(roster(start(Encounter::SETUP_SLIMES_NORMAL, 5)) == roster(start(Encounter::SETUP_SLIMES_NORMAL, 5)),
          "roster is a function of the encounter seed");

    // 3. Unique HP among enemies, and HP within the native range.
    for (std::uint64_t s = 1; s <= 200; ++s) {
        const BattleContext b = start(Encounter::SETUP_EXOSKELETONS_NORMAL, s, 8);
        std::set<int> hp;
        for (int i = 0; i < b.monsterCount; ++i) {
            hp.insert(b.monsters[i].maxHp);
            check(b.monsters[i].maxHp >= 26 && b.monsters[i].maxHp <= 30, "Exoskeleton A8 HP 26..30");
        }
        check(static_cast<int>(hp.size()) == b.monsterCount, "Exoskeleton HP unique");
    }
    check(start(Encounter::SETUP_AXEBOTS_NORMAL, 3).monsters[0].maxHp >= 70, "Axebot native HP 70..78");
    check(start(Encounter::SETUP_MYSTERIOUS_KNIGHT, 3, 0).monsters[0].maxHp == 101,
          "Mysterious Knight inherits native Flail Knight A0 HP 101");
    check(start(Encounter::SETUP_MYSTERIOUS_KNIGHT, 3, 10).monsters[0].maxHp == 108,
          "Mysterious Knight inherits native Flail Knight A10 HP 108");
    check(encounters_share_tags(Encounter::SETUP_SLITHERING_STRANGLER_NORMAL,
                                Encounter::SETUP_SNAPPING_JAXFRUIT_NORMAL), "native Jaxfruit encounter tag");
    check(encounters_share_tags(Encounter::SETUP_SLITHERING_STRANGLER_NORMAL,
                                Encounter::SETUP_SLIMES_NORMAL), "native Strangler Slimes encounter tag");
    check(encounters_share_tags(Encounter::SETUP_TUNNELER_NORMAL,
                                Encounter::SETUP_CHOMPERS_NORMAL), "retained Tunneler Chomper tag");

    // 4. The roster does not consume the MonsterAi stream (Gremlin Merc has one starting move).
    {
        Card deck[1] = {make_card(CardId::STRIKE_IRONCLAD, false, 1)};
        BattleContext b;
        b.init(Encounter::SETUP_GREMLIN_MERC_NORMAL, 99, deck, 1, 0);
        const Rng fresh(99 ^ 0x299F31D0u);
        check(b.monsterAiRng.counter == fresh.counter, "Gremlin merc setup leaves MonsterAi untouched");
    }

    // 5. The run passes Rng(Seed + TotalFloor + hash(Id.Entry)) as the encounter seed.
    for (std::uint32_t seed = 1; seed <= 20; ++seed) {
        RunContext rc;
        rc.init(seed, 0);
        int guard = 0;
        while (rc.screen != RunScreen::COMBAT && guard++ < 200) {
            const auto legal = rc.legal_actions();
            if (legal.empty()) break;
            rc.step(legal[0]);
        }
        if (rc.screen != RunScreen::COMBAT) continue;
        const Encounter enc = rc.battle.encounter;
        const std::uint64_t es = static_cast<std::uint64_t>(static_cast<std::int64_t>(rc.seed) + rc.floor) +
                                 Rng::deterministic_hash_code(encounter_native_entry(enc));
        check(roster(start(enc, es)) == roster(rc.battle), "run encounter seed formula");
    }
    check(std::string(encounter_native_entry(Encounter::SETUP_PUNCH_OFF)) == "PUNCH_OFF_EVENT_ENCOUNTER", "event entry alias");
    check(std::string(encounter_native_entry(Encounter::SETUP_SLIMES_WEAK)) == "SLIMES_WEAK", "entry = slug");

    std::printf("native monster creation: %d failures\n", failures);
    return failures == 0 ? 0 : 1;
}
