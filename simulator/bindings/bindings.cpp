#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>

#include "sts2/battle.h"
#include "sts2/map.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/relics.h"
#include "sts2/run.h"
#include "sts2/search.h"

namespace py = pybind11;
using namespace sts2;

static py::tuple action_tuple(const Action &a) {
    return py::make_tuple(static_cast<int>(a.type), static_cast<int>(a.hand),
                          static_cast<int>(a.target), static_cast<int>(a.uid));
}

static Action make_action(int type, int hand, int target, int uid) {
    Action a;
    a.type = static_cast<ActionType>(type);
    a.hand = static_cast<std::uint8_t>(hand);
    a.target = static_cast<std::uint8_t>(target);
    a.uid = static_cast<std::uint16_t>(uid);
    return a;
}

static py::list card_list(const Card *cards, int n) {
    py::list out;
    for (int i = 0; i < n; ++i) {
        out.append(py::make_tuple(static_cast<int>(cards[i].id), cards[i].upgraded,
                                  static_cast<int>(cards[i].uid), card_cost(cards[i])));
    }
    return out;
}

PYBIND11_MODULE(sts2_sim, m) {
    m.doc() = "Native STS2 simulator (sts_lightspeed-style)";

    py::enum_<Outcome>(m, "Outcome")
        .value("UNDECIDED", Outcome::UNDECIDED)
        .value("PLAYER_VICTORY", Outcome::PLAYER_VICTORY)
        .value("PLAYER_LOSS", Outcome::PLAYER_LOSS);
    py::enum_<ActionType>(m, "ActionType")
        .value("PLAY_CARD", ActionType::PLAY_CARD)
        .value("END_TURN", ActionType::END_TURN)
        .value("CHOOSE", ActionType::CHOOSE)
        .value("CONFIRM", ActionType::CONFIRM)
        .value("USE_POTION", ActionType::USE_POTION);
    {
        py::enum_<Encounter> pe(m, "Encounter");
        pe.value("INVALID", Encounter::INVALID);
        for (int i = 1; i < encounter_count(); ++i) {
            const char *key = encounter_def(i).key;
            if (key == nullptr) continue;
            pe.value(key, static_cast<Encounter>(i));
        }
    }
    py::enum_<MonsterId>(m, "MonsterId")
        .value("SHRINKER_BEETLE", MonsterId::SHRINKER_BEETLE)
        .value("FUZZY_WURM_CRAWLER", MonsterId::FUZZY_WURM_CRAWLER)
        .value("NIBBIT", MonsterId::NIBBIT)
        .value("LEAF_SLIME_S", MonsterId::LEAF_SLIME_S)
        .value("TWIG_SLIME_S", MonsterId::TWIG_SLIME_S)
        .value("LEAF_SLIME_M", MonsterId::LEAF_SLIME_M)
        .value("TWIG_SLIME_M", MonsterId::TWIG_SLIME_M);
    py::enum_<RoomType>(m, "RoomType")
        .value("MONSTER", RoomType::MONSTER)
        .value("ELITE", RoomType::ELITE)
        .value("EVENT", RoomType::EVENT)
        .value("REST", RoomType::REST)
        .value("SHOP", RoomType::SHOP)
        .value("TREASURE", RoomType::TREASURE)
        .value("BOSS", RoomType::BOSS);
    py::enum_<MapPointType>(m, "MapPointType")
        .value("UNASSIGNED", MapPointType::UNASSIGNED)
        .value("UNKNOWN", MapPointType::UNKNOWN)
        .value("SHOP", MapPointType::SHOP)
        .value("TREASURE", MapPointType::TREASURE)
        .value("REST", MapPointType::REST)
        .value("MONSTER", MapPointType::MONSTER)
        .value("ELITE", MapPointType::ELITE)
        .value("BOSS", MapPointType::BOSS)
        .value("ANCIENT", MapPointType::ANCIENT);
    py::enum_<RunScreen>(m, "RunScreen")
        .value("MAP", RunScreen::MAP)
        .value("COMBAT", RunScreen::COMBAT)
        .value("CARD_REWARD", RunScreen::CARD_REWARD)
        .value("REST", RunScreen::REST)
        .value("SHOP", RunScreen::SHOP)
        .value("EVENT", RunScreen::EVENT)
        .value("TREASURE", RunScreen::TREASURE)
        .value("RUN_OVER", RunScreen::RUN_OVER);
    py::enum_<RunActionType>(m, "RunActionType")
        .value("MOVE", RunActionType::MOVE)
        .value("TAKE_CARD", RunActionType::TAKE_CARD)
        .value("SKIP_CARD", RunActionType::SKIP_CARD)
        .value("REST_HEAL", RunActionType::REST_HEAL)
        .value("REST_UPGRADE", RunActionType::REST_UPGRADE)
        .value("REST_DIG", RunActionType::REST_DIG)
        .value("REST_LIFT", RunActionType::REST_LIFT)
        .value("BUY_CARD", RunActionType::BUY_CARD)
        .value("BUY_RELIC", RunActionType::BUY_RELIC)
        .value("BUY_POTION", RunActionType::BUY_POTION)
        .value("REMOVE_CARD", RunActionType::REMOVE_CARD)
        .value("LEAVE_SHOP", RunActionType::LEAVE_SHOP)
        .value("EVENT_CHOICE", RunActionType::EVENT_CHOICE)
        .value("COLLECT", RunActionType::COLLECT)
        .value("USE_POTION", RunActionType::USE_POTION);
    py::enum_<EventStatus>(m, "EventStatus")
        .value("IMPLEMENTED", EventStatus::IMPLEMENTED)
        .value("APPROXIMATE", EventStatus::APPROXIMATE)
        .value("UNSUPPORTED", EventStatus::UNSUPPORTED);

    {
        py::enum_<PotionId> pe(m, "PotionId");
        pe.value("INVALID", PotionId::INVALID);
        for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
            const PotionId id = static_cast<PotionId>(i);
            pe.value(potion_def(id).key, id);
        }
    }
    m.def("potion_name", [](int id) {
        return std::string(potion_name(static_cast<PotionId>(id)));
    });
    m.def("potion_def", [](int id) {
        const PotionDef &d = potion_def(static_cast<PotionId>(id));
        return py::make_tuple(d.key, d.name, static_cast<int>(d.rarity),
                              static_cast<int>(d.usage), static_cast<int>(d.target),
                              d.ironclad, d.combatGen);
    });
    {
        py::enum_<RelicId> re(m, "RelicId");
        re.value("INVALID", RelicId::INVALID);
        for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
            const RelicId id = static_cast<RelicId>(i);
            re.value(relic_def(id).key, id);
        }
    }
    m.def("relic_name", [](int id) {
        return std::string(relic_name(static_cast<RelicId>(id)));
    });
    m.def("relic_implemented", [](int id) {
        return relic_implemented(static_cast<RelicId>(id));
    });
    m.def("relic_info", [](int id) {
        const RelicDef &d = relic_def(static_cast<RelicId>(id));
        return py::make_tuple(d.key, d.name, static_cast<int>(d.rarity),
                              static_cast<int>(d.pool));
    });

    // Event manifest (name/status/act) for coverage tooling.
    m.def("generate_map", [](std::uint32_t seed, int act) {
        ActMap map;
        char name[32];
        std::snprintf(name, sizeof(name), "act_%d_map", act + 1);
        Rng rng(seed, name);
        generate_act_map(map, rng, act);
        py::list out;
        for (int i = 0; i < map.pointCount; ++i) {
            const MapNode &n = map.nodes[i];
            int row = -1;
            int col = -1;
            for (int r = 0; r <= map.mapLength && row < 0; ++r) {
                for (int c = 0; c < MAP_WIDTH; ++c) {
                    if (map.index[r][c] == i) {
                        row = r;
                        col = c;
                        break;
                    }
                }
            }
            py::list kids;
            for (int k = 0; k < n.childCount; ++k) kids.append(n.children[k]);
            py::list pars;
            for (int k = 0; k < n.parentCount; ++k) pars.append(n.parents[k]);
            out.append(py::make_tuple(i, static_cast<int>(n.type), col, row, kids, pars));
        }
        return py::make_tuple(map.rooms, map.mapLength, out);
    });
    m.def("event_count", []() { return event_count(); });
    m.def("event_pool", [](int act) {
        int ids[64];
        const int n = event_pool_for_act(act, ids, 64);
        py::list out;
        for (int i = 0; i < n; ++i) out.append(ids[i]);
        return out;
    });
    m.def("event_ancient", [](int act) { return event_ancient_for_act(act); });
    m.def("event_info", [](int id) {
        const EventInfo *info = sts2::event_info(id);
        if (info == nullptr) return py::make_tuple("", 2, -1);
        return py::make_tuple(std::string(info->name), static_cast<int>(info->status),
                              info->act);
    });

    m.attr("RUN_OBS_DIM") = RUN_OBS_DIM;
    m.attr("CARD_FEAT_DIM") = CARD_FEAT_DIM;
    m.attr("COMBAT_OBS_DIM") = COMBAT_OBS_DIM;
    m.attr("ACTION_FEAT_DIM") = ACTION_FEAT_DIM;
    m.attr("CARD_COUNT") = static_cast<int>(CardId::COUNT);
    m.attr("MAX_DECK") = MAX_DECK;
    m.attr("MAP_MAX_POINTS") = MAP_MAX_POINTS;

    m.def("card_name", [](int id) { return std::string(card_name(static_cast<CardId>(id))); });
    m.def("card_count", []() { return static_cast<int>(CardId::COUNT); });
    m.def("card_features", [](int id, bool upgraded, int price) {
        return card_features(make_card(static_cast<CardId>(id), upgraded, 0), price);
    }, py::arg("card_id"), py::arg("upgraded") = false, py::arg("price") = -1);

    py::class_<BattleContext>(m, "BattleContext")
        .def(py::init<>())
        .def("init", [](BattleContext &bc, int encounter, std::uint32_t seed,
                        const std::vector<int> &cardIds, const std::vector<bool> &upgraded,
                        int ascension, int hp, int maxHp,
                        const std::vector<int> &relics, const std::vector<int> &potions,
                        std::uint32_t potionSeed) {
            Card deck[MAX_PILE];
            const int n = std::min<int>(static_cast<int>(cardIds.size()), MAX_PILE);
            for (int i = 0; i < n; ++i) {
                const bool up = i < static_cast<int>(upgraded.size()) && upgraded[i];
                deck[i] = make_card(static_cast<CardId>(cardIds[i]), up,
                                    static_cast<std::uint16_t>(i + 1));
            }
            bc.init(static_cast<Encounter>(encounter), seed, deck, n, ascension, hp, maxHp,
                    relics.data(), static_cast<int>(relics.size()),
                    potions.data(), static_cast<int>(potions.size()), BASE_POTION_SLOTS, 0, 3, 0,
                    potionSeed);
        }, py::arg("encounter"), py::arg("seed"), py::arg("cards"), py::arg("upgraded"),
           py::arg("ascension") = 0, py::arg("hp") = -1, py::arg("max_hp") = -1,
           py::arg("relics") = std::vector<int>{}, py::arg("potions") = std::vector<int>{},
           py::arg("potion_seed") = 0)
        .def("clone", [](const BattleContext &bc) { return bc; },
             py::call_guard<py::gil_scoped_release>())
        .def("legal_actions", [](const BattleContext &bc) {
            py::list out;
            for (const Action &a : bc.legal_actions()) out.append(action_tuple(a));
            return out;
        })
        .def("step", [](BattleContext &bc, int type, int hand, int target, int uid) {
            return bc.step(make_action(type, hand, target, uid));
        }, py::call_guard<py::gil_scoped_release>())
        .def("greedy_action", [](const BattleContext &bc, double epsilon, std::uint32_t seed) {
            Rng rng(seed);
            Action a = greedy_action(bc, rng, epsilon);
            return action_tuple(a);
        }, py::arg("epsilon") = 0.0, py::arg("seed") = 0)
        .def("rollout", [](BattleContext &bc, double epsilon, std::uint32_t seed) {
            Rng rng(seed);
            return rollout(bc, rng, epsilon);
        }, py::arg("epsilon") = 0.05, py::arg("seed") = 0,
           py::call_guard<py::gil_scoped_release>())
        .def("search", [](const BattleContext &bc, int simulations, double c, double epsilon,
                          std::uint32_t seed) {
            SearchResult r = search(bc, simulations, c, epsilon, seed);
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.visits, r.values, r.simulations);
        }, py::arg("simulations") = 16, py::arg("c") = 1.5,
           py::arg("epsilon") = 0.05, py::arg("seed") = 0)
        .def("search_priors", [](const BattleContext &bc, int simulations,
                                 const std::vector<double> &priors, double c, double epsilon,
                                 std::uint32_t seed) {
            SearchResult r = search_priors(bc, simulations, priors, c, epsilon, seed);
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.visits, r.values, r.simulations);
        }, py::arg("simulations"), py::arg("priors"), py::arg("c") = 1.5,
           py::arg("epsilon") = 0.05, py::arg("seed") = 0)
        .def("action_features", [](const BattleContext &bc, int type, int hand, int target, int uid) {
            return combat_action_features(bc, make_action(type, hand, target, uid));
        })
        .def("observation", [](const BattleContext &bc) { return combat_observation(bc); })
        .def_property_readonly("outcome", [](const BattleContext &bc) { return bc.outcome; })
        .def_property_readonly("turn", [](const BattleContext &bc) { return bc.turn; })
        .def_property_readonly("player_hp", [](const BattleContext &bc) { return bc.player.hp; })
        .def_property_readonly("player_max_hp", [](const BattleContext &bc) { return bc.player.maxHp; })
        .def_property_readonly("player_block", [](const BattleContext &bc) { return bc.player.block; })
        .def_property_readonly("energy", [](const BattleContext &bc) { return bc.player.energy; })
        .def_property_readonly("strength", [](const BattleContext &bc) { return bc.player.strength; })
        .def_property_readonly("dexterity", [](const BattleContext &bc) { return bc.player.dexterity; })
        .def_property_readonly("hand", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.handCount; ++i) {
                out.append(py::make_tuple(static_cast<int>(bc.hand[i].id),
                                          static_cast<int>(bc.hand[i].uid),
                                          bc.hand[i].upgraded,
                                          card_cost(bc.hand[i])));
            }
            return out;
        })
        .def_property_readonly("draw_count", [](const BattleContext &bc) { return bc.drawCount; })
        .def_property_readonly("discard_count", [](const BattleContext &bc) { return bc.discardCount; })
        .def_property_readonly("exhaust_count", [](const BattleContext &bc) { return bc.exhaustCount; })
        .def_property_readonly("monsters", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.monsterCount; ++i) {
                const Monster &mm = bc.monsters[i];
                out.append(py::make_tuple(static_cast<int>(mm.id), mm.hp, mm.maxHp, mm.block,
                                          mm.intentDamage, mm.intentHits,
                                          static_cast<int>(mm.intentType), mm.alive,
                                          mm.vulnerable, mm.weak, mm.strength));
            }
            return out;
        })
        .def("monster_powers", [](const BattleContext &bc, int idx) {
            py::list out;
            if (idx < 0 || idx >= bc.monsterCount) return out;
            for (int p = 0; p < static_cast<int>(PowerId::COUNT); ++p) {
                if (bc.monsters[idx].power[p] != 0) out.append(py::make_tuple(p, bc.monsters[idx].power[p]));
            }
            return out;
        })
        .def("monster_state", [](const BattleContext &bc, int idx) {
            if (idx < 0 || idx >= bc.monsterCount) return py::make_tuple(-1, -1, false, false);
            const Monster &m = bc.monsters[idx];
            return py::make_tuple(static_cast<int>(m.move), static_cast<int>(m.lastMove),
                                  m.reviving, m.turn);
        })
        .def_property_readonly("pending_options", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.pending.count; ++i) out.append(bc.pending.cards[i].uid);
            return out;
        })
        .def_property_readonly("pending_info", [](const BattleContext &bc) {
            return py::make_tuple(static_cast<int>(bc.pending.op),
                                  static_cast<int>(bc.pending.pile),
                                  bc.pending.remaining, bc.pending.count);
        })
        .def_property_readonly("potions", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.potionCount; ++i) out.append(bc.potions[i]);
            return out;
        })
        .def("add_potion", [](BattleContext &bc, int id) {
            bc.add_potion(static_cast<PotionId>(id));
        })
        .def_property_readonly("relics", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.relicCount; ++i) out.append(bc.relics[i]);
            return out;
        });

    py::class_<RunContext>(m, "RunContext")
        .def(py::init<>())
        .def("init", [](RunContext &rc, std::uint32_t seed, int ascension) {
            rc.init(seed, ascension);
        }, py::arg("seed"), py::arg("ascension") = 0)
        .def("reset", [](RunContext &rc, std::uint32_t seed, int ascension) {
            rc.init(seed, ascension);
        }, py::arg("seed"), py::arg("ascension") = 0)
        .def("clone", [](const RunContext &rc) { return rc; },
             py::call_guard<py::gil_scoped_release>())
        .def("legal_actions", [](const RunContext &rc) {
            py::list out;
            for (const RunAction &a : rc.legal_actions()) {
                out.append(py::make_tuple(static_cast<int>(a.type), a.index));
            }
            return out;
        })
        .def("action_mask", [](const RunContext &rc) {
            py::list out;
            for (const RunAction &a : rc.legal_actions()) {
                out.append(py::make_tuple(static_cast<int>(a.type), a.index, 1));
            }
            return out;
        })
        .def("step", [](RunContext &rc, int type, int index) {
            RunAction a;
            a.type = static_cast<RunActionType>(type);
            a.index = index;
            return rc.step(a);
        }, py::call_guard<py::gil_scoped_release>())
        .def("step_combat", [](RunContext &rc, int type, int hand, int target, int uid) {
            return rc.step_combat(make_action(type, hand, target, uid));
        }, py::call_guard<py::gil_scoped_release>())
        .def("combat_action_features", [](const RunContext &rc, int type, int hand, int target, int uid) {
            return combat_action_features(rc.battle, make_action(type, hand, target, uid));
        })
        .def("observation", [](const RunContext &rc) { return run_observation(rc); })
        .def("observe_public", [](const RunContext &rc) {
            // Public information only: run summary + visible combat state.
            if (rc.screen == RunScreen::COMBAT) return run_observation(rc);
            return run_observation(rc);
        })
        .def("state_hash", [](const RunContext &rc) { return rc.state_hash(); },
             py::call_guard<py::gil_scoped_release>())
        .def("snapshot", [](const RunContext &rc) { return py::bytes(rc.serialize()); })
        .def("restore", [](RunContext &rc, const py::bytes &blob) {
            const std::string s = blob;
            return RunContext::restore(s, rc);
        })
        .def("terminal_reward", [](const RunContext &rc) { return rc.terminal_reward(); })
        .def_property_readonly("battle", [](RunContext &rc) -> BattleContext & { return rc.battle; },
                               py::return_value_policy::reference_internal)
        .def_property_readonly("hp", [](const RunContext &rc) { return rc.hp; })
        .def_property_readonly("max_hp", [](const RunContext &rc) { return rc.maxHp; })
        .def_property_readonly("gold", [](const RunContext &rc) { return rc.gold; })
        .def_property_readonly("floor", [](const RunContext &rc) { return rc.floor; })
        .def_property_readonly("act_floor", [](const RunContext &rc) { return rc.actFloor; })
        .def_property_readonly("act", [](const RunContext &rc) { return rc.act; })
        .def_property_readonly("screen", [](const RunContext &rc) { return rc.screen; })
        .def_property_readonly("won", [](const RunContext &rc) { return rc.won; })
        .def_property_readonly("is_terminal", [](const RunContext &rc) { return rc.is_over(); })
        .def_property_readonly("current_row", [](const RunContext &rc) { return rc.curRow; })
        .def_property_readonly("current_col", [](const RunContext &rc) { return rc.curCol; })
        .def_property_readonly("current_point_type", [](const RunContext &rc) {
            return static_cast<MapPointType>(rc.current_point_type());
        })
        .def("available_map_nodes", [](const RunContext &rc) { return rc.available_map_nodes(); })
        .def("map_nodes", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.map.pointCount; ++i) {
                const MapNode &n = rc.map.nodes[i];
                int row = -1;
                int col = -1;
                for (int r = 0; r <= rc.map.mapLength && row < 0; ++r) {
                    for (int c = 0; c < MAP_WIDTH; ++c) {
                        if (rc.map.index[r][c] == i) {
                            row = r;
                            col = c;
                            break;
                        }
                    }
                }
                py::list kids;
                for (int k = 0; k < n.childCount; ++k) kids.append(n.children[k]);
                py::list pars;
                for (int k = 0; k < n.parentCount; ++k) pars.append(n.parents[k]);
                out.append(py::make_tuple(i, static_cast<int>(n.type), col, row, kids, pars));
            }
            return out;
        })
        .def_property_readonly("map_rooms", [](const RunContext &rc) { return rc.map.rooms; })
        .def_property_readonly("map_length", [](const RunContext &rc) { return rc.map.mapLength; })
        .def_property_readonly("potions", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.potionCount; ++i) out.append(rc.potions[i]);
            return out;
        })
        .def_property_readonly("potion_slots", [](const RunContext &rc) { return rc.potionSlots; })
        .def_property_readonly("relics", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.relicCount; ++i) out.append(rc.relics[i]);
            return out;
        })
        .def("relic_aux", [](const RunContext &rc, int id) {
            for (int i = 0; i < rc.relicCount; ++i) {
                if (rc.relics[i] == id) return rc.relicAux[i];
            }
            return 0;
        })
        .def("add_relic", [](RunContext &rc, int id) {
            return rc.add_relic(static_cast<RelicId>(id));
        })
        .def("add_potion", [](RunContext &rc, int id) {
            rc.add_potion(static_cast<PotionId>(id));
        })
        .def_property_readonly("event_id", [](const RunContext &rc) { return static_cast<int>(rc.eventId); })
        .def_property_readonly("event_name", [](const RunContext &rc) {
            const EventInfo *info = sts2::event_info(rc.eventId);
            return std::string(info ? info->name : "");
        })
        .def_property_readonly("event_page", [](const RunContext &rc) { return rc.eventPage; })
        .def_property_readonly("event_choices", [](const RunContext &rc) {
            return static_cast<int>(rc.eventChoiceCount);
        })
        .def_property_readonly("event_relics", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.eventChoiceCount; ++i) out.append(rc.eventRelics[i]);
            return out;
        })
        .def_property_readonly("deck_count", [](const RunContext &rc) { return rc.deckCount; })
        .def_property_readonly("deck", [](const RunContext &rc) { return card_list(rc.deck, rc.deckCount); })
        .def_property_readonly("offered", [](const RunContext &rc) { return card_list(rc.offered, rc.offeredCount); })
        .def_property_readonly("reward_is_boss", [](const RunContext &rc) { return rc.rewardIsBoss; })
        .def_property_readonly("shop", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.shopCount; ++i) {
                out.append(py::make_tuple(static_cast<int>(rc.shopCards[i].id), rc.shopPrices[i],
                                          rc.shopSold[i]));
            }
            return out;
        })
        .def_property_readonly("shop_relics", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.shopRelicCount; ++i) {
                out.append(py::make_tuple(rc.shopRelics[i], rc.shopRelicPrices[i],
                                          rc.shopRelicSold[i]));
            }
            return out;
        })
        .def_property_readonly("shop_potions", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.shopPotionCount; ++i) {
                out.append(py::make_tuple(rc.shopPotions[i], rc.shopPotionPrices[i],
                                          rc.shopPotionSold[i]));
            }
            return out;
        })
        .def_property_readonly("removal_price", [](const RunContext &rc) { return rc.removalPrice; })
        .def_property_readonly("removal_used", [](const RunContext &rc) { return rc.removalUsed; })
        .def_property_readonly("combats_fought", [](const RunContext &rc) { return rc.combatsFought; })
        .def_property_readonly("elites_fought", [](const RunContext &rc) { return rc.elitesFought; })
        .def_property_readonly("bosses_fought", [](const RunContext &rc) { return rc.bossesFought; });
}
