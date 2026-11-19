// Numbers and hook timing transcribed from pinned native source, not DLL replay.
#include "sts2/run.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/combat_obs.h"
#include <cassert>
#include <memory>
using namespace sts2;

static std::unique_ptr<RunContext> start(Encounter encounter, int asc = 0) {
    auto r = std::make_unique<RunContext>();
    r->init(44515, asc); r->begin_combat(encounter);
    return r;
}

int main() {
    // Ascension thresholds are checked at every level, not only endpoints.
    for (int asc = 0; asc <= 10; ++asc) {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL, asc);
        auto &b = r->battle;
        b.player.hp = b.player.maxHp = 5000;
        auto &m = b.monsters[0];
        m.move = 1; // CURL_AND_GROW_MOVE
        monster_act(b, m);
        assert(m.strength == (asc >= 9 ? 7 : 5));
        assert(m.block == (asc >= 8 ? 18 : 14));

        spawn_monster(b, MonsterId::NIBBIT, 0);
        m.move = 1; // SLICE_MOVE
        monster_act(b, m);
        assert(m.block == (asc >= 8 ? 6 : 5));
        m.move = 2; // HISS_MOVE
        monster_act(b, m);
        assert(m.strength == (asc >= 9 ? 3 : 2));

        spawn_monster(b, MonsterId::THE_FORGOTTEN, 0);
        const int base = asc >= 9 ? 15 : 13;
        m.move = 1; // DREAD before any Dexterity gain
        roll_intent(b, m);
        assert(m.intentDamage == base);
        int hp = b.player.hp;
        monster_act(b, m);
        assert(hp - b.player.hp == base);
        for (int cast = 1; cast <= 2; ++cast) {
            m.move = 0; // MIASMA: block before this cast's Dexterity gain
            monster_act(b, m);
            assert(m.block == 8 + 2 * (cast - 1));
            assert(m.power[static_cast<int>(PowerId::DEXTERITY)] == 2 * cast);
            m.move = 1;
            roll_intent(b, m);
            assert(m.intentDamage == base + 2 * cast);
            hp = b.player.hp;
            monster_act(b, m);
            assert(hp - b.player.hp == base + 2 * cast);
        }
        // Powered monster block applies Dexterity before Frail, then floors.
        m.power[static_cast<int>(PowerId::FRAIL)] = 2;
        m.move = 0;
        monster_act(b, m);
        assert(m.block == 9); // (8 + current Dexterity 4) * 0.75

        spawn_monster(b, MonsterId::MYSTERIOUS_KNIGHT, 0);
        m.move = 2; // inherited FLAIL_MOVE
        roll_intent(b, m);
        assert(m.intentDamage == (asc >= 9 ? 10 : 9) && m.intentHits == 2);
        hp = b.player.hp;
        monster_act(b, m);
        assert(hp - b.player.hp == 2 * ((asc >= 9 ? 10 : 9) + 6));
        m.move = 3; // inherited RAM_MOVE
        roll_intent(b, m);
        assert(m.intentDamage == (asc >= 9 ? 17 : 15));
    }
    for (int asc : {0, 8, 9, 10}) {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL, asc);
        auto &b = r->battle; auto &m = b.monsters[0];
        const int curl = asc >= 8 ? 18 : 14;
        const int before = m.hp;
        Card card = make_card(CardId::TWIN_STRIKE, false, b.require_card_uid());
        b.activePlay.active = true; b.activePlay.card = card;
        b.activePlay.nextPlay = 1; b.activePlay.awaitingAfter = true;
        b.cardsPlayedThisCombat = b.cardsPlayedThisTurn = 1;
        b.playPile[0] = card; b.playCount = 1;
        // A real action clears temporary UID allocations before it can pause.
        b.clear_card_uid_reservations();
        b.attack_from_card(card, 0, 5, 2);
        assert(m.hp == before - 10 && m.block == 0);
        assert(m.power[static_cast<int>(PowerId::CURL_UP)] == curl);
        assert(static_cast<std::uint16_t>(m.aux[0]) == card.uid);
        auto copy = std::make_unique<RunContext>(*r);
        auto restored = std::make_unique<RunContext>();
        assert(RunContext::restore(r->serialize(), *restored));
        assert(restored->battle.monsters[0].aux[0] == m.aux[0]);
        // Renaming an execution UID cannot alter either legacy public layout.
        const auto flat = public_combat_observation(b);
        const auto entities = combat_entity_observation(b);
        const auto renamed = static_cast<std::uint16_t>(50001);
        b.activePlay.card.uid = b.playPile[0].uid = renamed;
        m.aux[0] = static_cast<std::int16_t>(renamed);
        assert(public_combat_observation(b) == flat);
        const auto renamedEntities = combat_entity_observation(b);
        assert(renamedEntities.kind == entities.kind && renamedEntities.id == entities.id &&
               renamedEntities.num == entities.num && renamedEntities.candNum == entities.candNum);
        b.after_card_played(b.activePlay.card);
        copy->battle.after_card_played(card);
        restored->battle.after_card_played(card);
        assert(m.block == curl && m.aux[0] == 0 && m.power[static_cast<int>(PowerId::CURL_UP)] == 0);
        assert(copy->battle.monsters[0].block == curl && restored->battle.monsters[0].block == curl);
    }
    {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL);
        auto &b = r->battle; auto &m = b.monsters[0];
        const int hp = m.hp;
        m.block = 20;
        Card card = make_card(CardId::STRIKE_IRONCLAD, false, 42000);
        b.attack_from_card(card, 0, 6, 1);
        assert(m.hp == hp && m.block == 14 && m.aux[0] != 0);
        Card nested = make_card(CardId::DEFEND_IRONCLAD, false, 42001);
        b.after_card_played(nested);
        assert(m.block == 14 && m.power[static_cast<int>(PowerId::CURL_UP)] == 14);
        b.after_card_played(card);
        assert(m.block == 28 && m.power[static_cast<int>(PowerId::CURL_UP)] == 0);
    }
    {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL);
        auto &b = r->battle; auto &m = b.monsters[0];
        b.damage_monster(0, 1); // poison/other damage with no card source
        assert(m.block == 0 && m.power[static_cast<int>(PowerId::CURL_UP)] == 14 && m.aux[0] == 0);
    }
    {
        auto r = start(Encounter::SETUP_KAISER_CRAB_BOSS);
        auto &b = r->battle;
        const int strength = b.monsters[0].strength, block = b.monsters[0].block;
        b.kill_monster(1);
        assert(b.monsters[0].strength == strength + 6 && b.monsters[0].block == block + 99);
    }
    {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL);
        auto &b = r->battle;
        spawn_monster(b, MonsterId::LIVING_SHIELD, 0);
        spawn_monster(b, MonsterId::TURRET_OPERATOR, 1);
        b.monsterCount = 2; b.monsters[1].block = 0;
        b.start_player_turn(true);
        assert(b.monsters[1].block == 0);
        b.start_player_turn(false);
        assert(b.monsters[1].block == 25);
    }
    {
        auto r = start(Encounter::SETUP_LOUSE_PROGENITOR_NORMAL);
        auto &b = r->battle;
        spawn_monster(b, MonsterId::GUARDBOT, 0);
        spawn_monster(b, MonsterId::FABRICATOR, 1);
        b.monsterCount = 2;
        b.monsters[1].block = 0;
        b.monsters[1].power[static_cast<int>(PowerId::DEXTERITY)] = 12;
        b.monsters[1].power[static_cast<int>(PowerId::FRAIL)] = 3;
        b.monsters[0].move = 0;
        monster_act(b, b.monsters[0]);
        assert(b.monsters[1].block == 15); // GuardMove uses ValueProp.Unpowered
    }
}
