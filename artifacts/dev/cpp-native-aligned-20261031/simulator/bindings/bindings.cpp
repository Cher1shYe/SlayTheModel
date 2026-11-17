#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <limits>
#include <cmath>
#include <stdexcept>
#include <string>
#include <tuple>

#include "sts2/battle.h"
#include "sts2/macro_obs.h"
#include "sts2/map.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/relics.h"
#include "sts2/run.h"
#include "sts2/search.h"
#include "sts2/combat_obs.h"
#include "sts2/net_search.h"

#include <pthread.h>
#include <vector>

namespace py = pybind11;
using namespace sts2;

static py::tuple action_tuple(const Action &a) {
    return py::make_tuple(static_cast<int>(a.type), static_cast<int>(a.hand),
                          static_cast<int>(a.target), static_cast<int>(a.uid));
}

static Action make_action(int type, int hand, int target, int uid) {
    if (type < static_cast<int>(ActionType::PLAY_CARD) ||
        type > static_cast<int>(ActionType::USE_POTION)) {
        throw std::invalid_argument("type is not a valid combat action type");
    }
    if (hand < 0 || hand > std::numeric_limits<std::uint8_t>::max()) {
        throw std::invalid_argument("hand is outside the uint8 range");
    }
    if (target < 0 || target > std::numeric_limits<std::uint8_t>::max()) {
        throw std::invalid_argument("target is outside the uint8 range");
    }
    if (uid < 0 || uid > std::numeric_limits<std::uint16_t>::max()) {
        throw std::invalid_argument("uid is outside the uint16 range");
    }
    Action a;
    a.type = static_cast<ActionType>(type);
    a.hand = static_cast<std::uint8_t>(hand);
    a.target = static_cast<std::uint8_t>(target);
    a.uid = static_cast<std::uint16_t>(uid);
    return a;
}


static py::dict combat_obs_dict(const CombatObservation &o) {
    auto ints = [](const std::vector<std::int32_t> &v, std::vector<py::ssize_t> shape) {
        py::array_t<std::int32_t> a(shape);
        std::copy(v.begin(), v.end(), a.mutable_data());
        return a;
    };
    auto floats = [](const std::vector<float> &v, std::vector<py::ssize_t> shape) {
        py::array_t<float> a(shape);
        std::copy(v.begin(), v.end(), a.mutable_data());
        return a;
    };
    const auto n = static_cast<py::ssize_t>(o.kind.size());
    const auto c = static_cast<py::ssize_t>(o.candType.size());
    py::dict d;
    d["kind"] = ints(o.kind, {n});
    d["id"] = ints(o.id, {n});
    d["num"] = floats(o.num, {n, COMBAT_ENTITY_NUM});
    d["cand_type"] = ints(o.candType, {c});
    d["cand_target"] = ints(o.candTarget, {c});
    d["cand_target2"] = ints(o.candTarget2, {c});
    d["cand_num"] = floats(o.candNum, {c, COMBAT_CAND_NUM});
    return d;
}

// Packs several combat observations into flat arrays plus per-sample lengths.
static py::dict pack_combat_obs(const std::vector<CombatObservation> &obs) {
    std::size_t n = 0, c = 0;
    for (const auto &o : obs) { n += o.kind.size(); c += o.candType.size(); }
    py::array_t<std::int32_t> kind(static_cast<py::ssize_t>(n)), id(static_cast<py::ssize_t>(n));
    py::array_t<float> num({static_cast<py::ssize_t>(n), static_cast<py::ssize_t>(COMBAT_ENTITY_NUM)});
    py::array_t<std::int32_t> ent_len(static_cast<py::ssize_t>(obs.size())), cand_len(static_cast<py::ssize_t>(obs.size()));
    py::array_t<std::int32_t> ctype(static_cast<py::ssize_t>(c)), ct1(static_cast<py::ssize_t>(c)), ct2(static_cast<py::ssize_t>(c));
    py::array_t<float> cnum({static_cast<py::ssize_t>(c), static_cast<py::ssize_t>(COMBAT_CAND_NUM)});
    auto *pk = kind.mutable_data(); auto *pi = id.mutable_data(); auto *pn = num.mutable_data();
    auto *pel = ent_len.mutable_data(); auto *pcl = cand_len.mutable_data();
    auto *pct = ctype.mutable_data(); auto *p1 = ct1.mutable_data(); auto *p2 = ct2.mutable_data(); auto *pcn = cnum.mutable_data();
    for (std::size_t k = 0; k < obs.size(); ++k) {
        const auto &o = obs[k];
        pk = std::copy(o.kind.begin(), o.kind.end(), pk);
        pi = std::copy(o.id.begin(), o.id.end(), pi);
        pn = std::copy(o.num.begin(), o.num.end(), pn);
        pct = std::copy(o.candType.begin(), o.candType.end(), pct);
        p1 = std::copy(o.candTarget.begin(), o.candTarget.end(), p1);
        p2 = std::copy(o.candTarget2.begin(), o.candTarget2.end(), p2);
        pcn = std::copy(o.candNum.begin(), o.candNum.end(), pcn);
        pel[k] = static_cast<std::int32_t>(o.kind.size());
        pcl[k] = static_cast<std::int32_t>(o.candType.size());
    }
    py::dict d;
    d["kind"] = kind; d["id"] = id; d["num"] = num; d["ent_len"] = ent_len;
    d["cand_type"] = ctype; d["cand_target"] = ct1; d["cand_target2"] = ct2; d["cand_num"] = cnum;
    d["cand_len"] = cand_len;
    return d;
}

static std::vector<NetSearch *> search_ptrs(const py::list &searches) {
    std::vector<NetSearch *> out;
    out.reserve(searches.size());
    for (const auto &h : searches) out.push_back(h.cast<NetSearch *>());
    return out;
}

struct ParallelJob {
    const std::function<void(std::size_t)> *fn;
    std::size_t n, t, threads;
    std::exception_ptr error;
};
static void *parallel_job(void *arg) {
    auto *job = static_cast<ParallelJob *>(arg);
    try { for (std::size_t i = job->t; i < job->n; i += job->threads) (*job->fn)(i); }
    catch (...) { job->error = std::current_exception(); }
    return nullptr;
}
// Worker threads get a 64 MiB stack: BattleContext copies are several hundred KiB.
static void parallel_for(std::size_t n, int threads, const std::function<void(std::size_t)> &fn) {
    threads = std::max(1, std::min<int>(threads, static_cast<int>(n)));
    if (threads <= 1) { for (std::size_t i = 0; i < n; ++i) fn(i); return; }
    std::vector<ParallelJob> jobs(static_cast<std::size_t>(threads));
    std::vector<pthread_t> ids(static_cast<std::size_t>(threads));
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 64u << 20);
    for (int t = 0; t < threads; ++t) {
        jobs[t] = {&fn, n, static_cast<std::size_t>(t), static_cast<std::size_t>(threads), nullptr};
        if (pthread_create(&ids[t], &attr, parallel_job, &jobs[t]) != 0) {
            pthread_attr_destroy(&attr);
            throw std::runtime_error("pthread_create failed");
        }
    }
    pthread_attr_destroy(&attr);
    for (int t = 0; t < threads; ++t) pthread_join(ids[t], nullptr);
    for (auto &j : jobs) if (j.error) std::rethrow_exception(j.error);
}

static py::list card_list(const Card *cards, int n) {
    py::list out;
    for (int i = 0; i < n; ++i) {
        out.append(py::make_tuple(static_cast<int>(cards[i].id), cards[i].upgraded,
                                  static_cast<int>(cards[i].uid), card_cost(cards[i])));
    }
    return out;
}

static py::list card_enchantments(const Card *cards, int n) {
    py::list out;
    for (int i = 0; i < n; ++i)
        out.append(py::make_tuple(static_cast<int>(cards[i].enchantment),
                                  cards[i].enchantmentAmount, cards[i].enchantmentDisabled));
    return out;
}

PYBIND11_MODULE(sts2_sim, m) {
    m.doc() = "Native STS2 simulator (sts_lightspeed-style)";
    // Identity of this port, not a claim of complete native-game parity.
    m.attr("ENGINE_RULESET_ID") = "native-41cef1ea-port-v8";
    m.attr("TARGET_GAME_DLL_SHA256") = "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4";
    m.attr("NATIVE_PARITY_COMPLETE") = false;

    py::enum_<Outcome>(m, "Outcome")
        .value("UNDECIDED", Outcome::UNDECIDED)
        .value("PLAYER_VICTORY", Outcome::PLAYER_VICTORY)
        .value("PLAYER_LOSS", Outcome::PLAYER_LOSS)
        .value("TRUNCATED", Outcome::TRUNCATED);
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
        .value("RUN_OVER", RunScreen::RUN_OVER)
        .value("REWARDS", RunScreen::REWARDS);
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
        .value("USE_POTION", RunActionType::USE_POTION)
        .value("TAKE_GOLD_REWARD", RunActionType::TAKE_GOLD_REWARD)
        .value("TAKE_POTION_REWARD", RunActionType::TAKE_POTION_REWARD)
        .value("TAKE_RELIC_REWARD", RunActionType::TAKE_RELIC_REWARD)
        .value("OPEN_CARD_REWARD", RunActionType::OPEN_CARD_REWARD)
        .value("LEAVE_REWARDS", RunActionType::LEAVE_REWARDS)
        .value("DISCARD_POTION", RunActionType::DISCARD_POTION)
        .value("SACRIFICE_CARD_REWARD", RunActionType::SACRIFICE_CARD_REWARD)
        .value("EVENT_SELECT_CARD", RunActionType::EVENT_SELECT_CARD)
        .value("TAKE_STOLEN_CARD_REWARD", RunActionType::TAKE_STOLEN_CARD_REWARD)
        .value("SKIP_STOLEN_CARD_REWARD", RunActionType::SKIP_STOLEN_CARD_REWARD)
        .value("SELECT_GRID_CARD", RunActionType::SELECT_GRID_CARD)
        .value("CONFIRM_GRID_CARDS", RunActionType::CONFIRM_GRID_CARDS)
        .value("CANCEL_GRID_PREVIEW", RunActionType::CANCEL_GRID_PREVIEW)
        .value("REST_CLONE", RunActionType::REST_CLONE)
        .value("REST_HATCH", RunActionType::REST_HATCH)
        .value("CRYSTAL_SPHERE_SMALL", RunActionType::CRYSTAL_SPHERE_SMALL)
        .value("CRYSTAL_SPHERE_BIG", RunActionType::CRYSTAL_SPHERE_BIG);
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
    m.def("native_epoch_names", [] {
        std::vector<std::string> names;
        for (int i = 0; i < native_epoch_count(); ++i) names.emplace_back(native_epoch_name(i));
        return names;
    }, "UnlockState epoch names; index = bit in NativeProgressContext.revealed_epochs");
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

    // Standalone map generation takes the already-derived low-level RNG seed.
    m.def("generate_map", [](std::uint64_t seed, int act, int ascension) {
        ActMap map;
        char name[32];
        std::snprintf(name, sizeof(name), "act_%d_map", act + 1);
        Rng rng(seed, name);
        generate_act_map(map, rng, act, ascension);
        py::list out;
        for (int i = 0; i < map.pointCount; ++i) {
            const MapNode &n = map.nodes[i];
            int row = -1;
            int col = -1;
            for (int r = 0; r < MAP_MAX_ROWS && row < 0; ++r) {
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
    }, py::arg("seed"), py::arg("act"), py::arg("ascension") = 0,
       "Generate a map from a raw uint64 RNG seed (same numeric contract as RunContext.init).");
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
    m.attr("PUBLIC_OBS_DIM") = PUBLIC_OBS_DIM;
    m.attr("PUBLIC_RUN_DIM") = PUBLIC_RUN_DIM;
    m.attr("PUB_RUN_BOSS_OFFSET") = PUB_RUN_BOSS_OFFSET;
    m.attr("PUB_RUN_EXTENSION") = PUB_RUN_EXTENSION;
    m.attr("PUBLIC_COMBAT_OBS_DIM") = PUBLIC_COMBAT_OBS_DIM;
    m.attr("PUBLIC_OBS_VERSION") = PUBLIC_OBS_VERSION;
    m.attr("MACRO_OBS_VERSION") = MACRO_OBS_VERSION;
    m.attr("COMBAT_OBS_VERSION") = COMBAT_OBS_VERSION;
    m.attr("COMBAT_ENTITY_NUM") = COMBAT_ENTITY_NUM;
    m.attr("COMBAT_CAND_NUM") = COMBAT_CAND_NUM;
    m.attr("COMBAT_ENTITY_KINDS") = static_cast<int>(CombatEntity::COUNT);
    m.def("combat_id_vocab", []() {
        py::list out;
        for (int k = 0; k < static_cast<int>(CombatEntity::COUNT); ++k)
            out.append(combat_id_vocab(static_cast<CombatEntity>(k)));
        return out;
    }, "id vocabulary size of each CombatEntity kind");
    m.attr("MACRO_ENTITY_NUM") = MACRO_ENTITY_NUM;
    m.attr("MACRO_CAND_NUM") = MACRO_CAND_NUM;
    m.attr("MACRO_PHASES") = MACRO_PHASES;
    m.attr("RUN_ACTION_TYPES") = static_cast<int>(RUN_ACTION_LAST) + 1;
    m.def("macro_vocab", [] {
        std::vector<int> sizes;
        for (int k = 0; k < static_cast<int>(MacroEntity::COUNT); ++k)
            sizes.push_back(macro_id_vocab(static_cast<MacroEntity>(k)));
        return sizes;
    }, "id vocabulary size per macro entity kind (index = kind)");
    m.attr("ACTION_SCHEMA_VERSION") = ACTION_SCHEMA_VERSION;
    m.attr("CARD_COUNT") = static_cast<int>(CardId::COUNT);
    m.attr("MAX_DECK") = MAX_DECK;
    m.attr("MAP_MAX_POINTS") = MAP_MAX_POINTS;

    m.def("monster_info", [](int id) {
        const MonsterDef &d = monster_def(static_cast<MonsterId>(id));
        return py::make_tuple(std::string(d.key ? d.key : ""),
                              d.hpLo[0], d.hpHi[0], d.hpLo[1], d.hpHi[1],
                              d.stateOff, d.stateCount, d.reviveState, d.multiClawState);
    });
    m.def("encounter_info", [](int id) {
        const EncounterDef &d = encounter_def(id);
        py::list pats;
        for (int i = 0; i < d.patternCount; ++i) {
            const EncounterPattern &p = encounter_pattern(d.patternOff + i);
            py::list ids;
            for (int k = 0; k < p.count; ++k) ids.append(static_cast<int>(p.ids[k]));
            pats.append(py::make_tuple(ids, p.weight));
        }
        return py::make_tuple(std::string(d.key ? d.key : ""), d.act, pats);
    });
    m.def("card_name", [](int id) { return std::string(card_name(static_cast<CardId>(id))); });
    m.def("card_count", []() { return static_cast<int>(CardId::COUNT); });
    m.def("card_native_available", [](int id) { return card_native_available(static_cast<CardId>(id)); });
    m.def("card_features", [](int id, bool upgraded, int price) {
        return card_features(make_card(static_cast<CardId>(id), upgraded, 0), price);
    }, py::arg("card_id"), py::arg("upgraded") = false, py::arg("price") = -1);

    py::class_<NetSearch>(m, "NetSearch", "resumable PUCT search with batched external priors/values")
        .def(py::init([](const BattleContext &root, int simulations, std::uint32_t seed, double c_puct,
                         double fpu_reduction, double dirichlet_alpha, double dirichlet_frac,
                         double potion_weight, double win_base, bool resample, bool normalize_q,
                         bool eval_terminal_wins) {
            NetSearchConfig cfg;
            cfg.cPuct = c_puct; cfg.fpuReduction = fpu_reduction; cfg.dirichletAlpha = dirichlet_alpha;
            cfg.dirichletFrac = dirichlet_frac; cfg.potionWeight = potion_weight; cfg.winBase = win_base;
            cfg.resampleHidden = resample; cfg.normalizeQ = normalize_q; cfg.evalTerminalWins = eval_terminal_wins;
            return new NetSearch(root, simulations, seed, cfg);
        }), py::arg("root"), py::arg("simulations"), py::arg("seed") = 0, py::arg("c_puct") = 1.5,
           py::arg("fpu_reduction") = 0.2, py::arg("dirichlet_alpha") = 0.3, py::arg("dirichlet_frac") = 0.0,
           py::arg("potion_weight") = 4.0, py::arg("win_base") = 0.4, py::arg("resample") = true,
           py::arg("normalize_q") = false, py::arg("eval_terminal_wins") = false)
        .def("advance", &NetSearch::advance, py::call_guard<py::gil_scoped_release>())
        .def_property_readonly("waiting", &NetSearch::waiting)
        .def("pending_observation", [](const NetSearch &s) { return combat_obs_dict(combat_entity_observation(s.pending_state())); })
        .def("provide", &NetSearch::provide, py::arg("priors"), py::arg("value"))
        .def_property_readonly("simulations_done", &NetSearch::simulations_done)
        .def("root_actions", [](const NetSearch &s) {
            py::list out;
            for (const Action &a : s.root_actions()) out.append(action_tuple(a));
            return out;
        })
        .def("root_visits", &NetSearch::root_visits)
        .def("root_q", &NetSearch::root_q)
        .def("root_priors", &NetSearch::root_priors)
        .def_property_readonly("root_value", &NetSearch::root_value)
        .def("best_action", [](const NetSearch &s) { return action_tuple(s.best_action()); });
    m.def("net_search_advance", [](const py::list &searches, int threads) {
        auto ptrs = search_ptrs(searches);
        std::vector<char> waiting(ptrs.size(), 0);
        std::vector<CombatObservation> obs(ptrs.size());
        {
            py::gil_scoped_release release;
            parallel_for(ptrs.size(), threads, [&](std::size_t i) {
                if (ptrs[i]->advance()) {
                    waiting[i] = 1;
                    obs[i] = combat_entity_observation(ptrs[i]->pending_state());
                }
            });
        }
        std::vector<CombatObservation> packed;
        py::list idx;
        for (std::size_t i = 0; i < ptrs.size(); ++i)
            if (waiting[i]) { idx.append(static_cast<int>(i)); packed.push_back(std::move(obs[i])); }
        py::dict d = pack_combat_obs(packed);
        d["index"] = idx;
        return d;
    }, py::arg("searches"), py::arg("threads") = 1,
       "advance every search to its next pending leaf; returns packed observations of the waiting ones");
    m.def("net_search_provide", [](const py::list &searches, const std::vector<int> &index,
                                   const std::vector<double> &priors, const std::vector<int> &cand_len,
                                   const std::vector<double> &values) {
        auto ptrs = search_ptrs(searches);
        if (index.size() != cand_len.size() || index.size() != values.size())
            throw std::invalid_argument("index, cand_len and values must have the same length");
        std::size_t off = 0;
        for (std::size_t k = 0; k < index.size(); ++k) {
            const auto n = static_cast<std::size_t>(cand_len[k]);
            if (off + n > priors.size()) throw std::invalid_argument("priors shorter than cand_len total");
            std::vector<double> p(priors.begin() + static_cast<std::ptrdiff_t>(off),
                                  priors.begin() + static_cast<std::ptrdiff_t>(off + n));
            ptrs.at(static_cast<std::size_t>(index[k]))->provide(p, values[k]);
            off += n;
        }
    }, py::arg("searches"), py::arg("index"), py::arg("priors"), py::arg("cand_len"), py::arg("values"));

    py::class_<BattleContext>(m, "BattleContext")
        .def(py::init<>())
        .def("init", [](BattleContext &bc, int encounter, std::uint64_t seed,
                        const std::vector<int> &cardIds, const std::vector<bool> &upgraded,
                        int ascension, int hp, int maxHp,
                        const std::vector<int> &relics, const std::vector<int> &potions,
                        std::uint64_t potionSeed) {
            Card deck[MAX_PILE];
            const int n = std::min<int>(static_cast<int>(cardIds.size()), MAX_PILE);
            for (int i = 0; i < n; ++i) {
                if (!card_native_available(static_cast<CardId>(cardIds[i])))
                    throw std::invalid_argument("card is absent from the target native version");
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
                          std::uint32_t seed, bool resample) {
            SearchResult r;
            {
                py::gil_scoped_release release;
                r = search(bc, simulations, c, epsilon, seed, resample);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.visits, r.values, r.simulations);
        }, py::arg("simulations") = 16, py::arg("c") = 1.5,
           py::arg("epsilon") = 0.05, py::arg("seed") = 0,
           py::arg("resample") = false)
        .def("mcts", [](const BattleContext &bc, int simulations, double c,
                         std::uint32_t seed, bool resample, bool greedy_rollout, double epsilon,
                         double potion_weight) {
            if (simulations < 0 || !std::isfinite(c) || c < 0 ||
                !std::isfinite(epsilon) || epsilon < 0 || epsilon > 1)
                throw std::invalid_argument("invalid MCTS budget, exploration or epsilon");
            MctsResult r;
            {
                py::gil_scoped_release release;
                r = mcts(bc, simulations, c, seed, resample, greedy_rollout, epsilon, potion_weight);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.simulations, r.victory);
        }, py::arg("simulations") = 2000, py::arg("c") = 4.242640687,
           py::arg("seed") = 0, py::arg("resample") = false,
           py::arg("greedy_rollout") = false, py::arg("epsilon") = 0.05,
           py::arg("potion_weight") = 4.0)
        .def("mcts_root", [](const BattleContext &bc, int simulations, double c,
                              std::uint32_t seed, bool resample, double epsilon, double potion_weight) {
            if (simulations < 0 || !std::isfinite(c) || c < 0 ||
                !std::isfinite(epsilon) || epsilon < 0 || epsilon > 1)
                throw std::invalid_argument("invalid MCTS budget, exploration or epsilon");
            MctsResult r;
            {
                py::gil_scoped_release release;
                r = mcts(bc, simulations, c, seed, resample, false, epsilon, potion_weight);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.simulations, r.rootVisits);
        }, py::arg("simulations"), py::arg("c") = 4.242640687, py::arg("seed") = 0,
           py::arg("resample") = true, py::arg("epsilon") = 0.05, py::arg("potion_weight") = 4.0,
           "same search as mcts(); also returns the root visit count of each legal action "
           "(legal_actions() order): (actions, simulations, root_visits)")
        .def("entity_observation", [](const BattleContext &bc) {
            CombatObservation o;
            {
                py::gil_scoped_release release;
                o = combat_entity_observation(bc);
            }
            return combat_obs_dict(o);
        }, "entity-structured public combat observation (candidates = legal_actions() order)")
        .def("mcts_priors", [](const BattleContext &bc, int simulations,
                                const std::vector<std::tuple<int, int, int, int>> &actions_in,
                                const std::vector<double> &priors, double c,
                                std::uint32_t seed, bool resample, bool greedy_rollout, double epsilon,
                                double potion_weight) {
            std::vector<Action> expected;
            expected.reserve(actions_in.size());
            for (const auto &a : actions_in)
                expected.push_back(make_action(std::get<0>(a), std::get<1>(a),
                                               std::get<2>(a), std::get<3>(a)));
            MctsResult r;
            {
                py::gil_scoped_release release;
                r = mcts_priors(bc, simulations, expected, priors, c, seed,
                                resample, greedy_rollout, epsilon, potion_weight);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.simulations, r.victory);
        }, py::arg("simulations"), py::arg("actions"), py::arg("priors"),
           py::arg("c") = 3.0, py::arg("seed") = 0, py::arg("resample") = false,
           py::arg("greedy_rollout") = false, py::arg("epsilon") = 0.05,
           py::arg("potion_weight") = 4.0)
        .def("mcts_depth_priors", [](const BattleContext &bc, int simulations,
                                      py::function prior_fn, int max_depth, double c,
                                      std::uint32_t seed, bool greedy_rollout, double epsilon,
                                      bool resample_hidden, py::object value_fn) {
            MctsPriorFn callback = [&prior_fn](const BattleContext &state, const std::vector<Action> &) {
                py::gil_scoped_acquire acquire;
                // The wrapper is valid only for the duration of this callback.
                return prior_fn(py::cast(&state, py::return_value_policy::reference)).cast<std::vector<double>>();
            };
            if (!value_fn.is_none() && !PyCallable_Check(value_fn.ptr()))
                throw std::invalid_argument("value_fn must be callable or None");
            const bool has_value_fn = !value_fn.is_none();
            MctsValueFn value_callback = [&value_fn](const BattleContext &state) {
                py::gil_scoped_acquire acquire;
                return value_fn(py::cast(&state, py::return_value_policy::reference)).cast<double>();
            };
            MctsResult r;
            {
                py::gil_scoped_release release;
                r = mcts_depth_priors(bc, simulations, callback, max_depth, c, seed,
                                      greedy_rollout, epsilon, resample_hidden,
                                      has_value_fn ? &value_callback : nullptr);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.simulations, r.victory);
        }, py::arg("simulations"), py::arg("prior_fn"), py::arg("max_depth"),
           py::arg("c") = 3.0, py::arg("seed") = 0,
           py::arg("greedy_rollout") = false, py::arg("epsilon") = 0.05,
           py::arg("resample_hidden") = false, py::arg("value_fn") = py::none())
        .def("search_priors", [](const BattleContext &bc, int simulations,
                                 const std::vector<double> &priors, double c, double epsilon,
                                 std::uint32_t seed, bool resample) {
            SearchResult r;
            {
                py::gil_scoped_release release;
                r = search_priors(bc, simulations, priors, c, epsilon, seed, resample);
            }
            py::list actions;
            for (const Action &a : r.actions) actions.append(action_tuple(a));
            return py::make_tuple(actions, r.visits, r.values, r.simulations);
        }, py::arg("simulations"), py::arg("priors"), py::arg("c") = 1.5,
           py::arg("epsilon") = 0.05, py::arg("seed") = 0,
           py::arg("resample") = false)
        .def("resample_hidden", [](BattleContext &bc, std::uint32_t seed) {
            bc.resample_hidden(seed);
        }, py::arg("seed"))
        .def("action_features", [](const BattleContext &bc, int type, int hand, int target, int uid) {
            return combat_action_features(bc, make_action(type, hand, target, uid));
        })
        .def("observation", [](const BattleContext &bc) { return combat_observation(bc); })
        .def("observation_public", [](const BattleContext &bc) {
            return public_combat_observation(bc);
        })
        .def("observation_public_array", [](const BattleContext &bc) {
            const auto values = public_combat_observation(bc);
            py::array_t<float> result(values.size());
            std::copy(values.begin(), values.end(), result.mutable_data());
            return result;
        })
        .def("legal_action_features_array", [](const BattleContext &bc) {
            const auto actions = bc.legal_actions();
            py::array_t<float> result({static_cast<py::ssize_t>(actions.size()),
                                       static_cast<py::ssize_t>(ACTION_FEAT_DIM)});
            float *out = result.mutable_data();
            for (const auto &action : actions) {
                const auto values = combat_action_features(bc, action);
                if (values.size() != ACTION_FEAT_DIM)
                    throw std::logic_error("invalid combat action feature length");
                out = std::copy(values.begin(), values.end(), out);
            }
            return result;
        })
        .def_property_readonly("outcome", [](const BattleContext &bc) { return bc.outcome; })
        .def_property_readonly("turn", [](const BattleContext &bc) { return bc.turn; })
        .def_property_readonly("player_hp", [](const BattleContext &bc) { return bc.player.hp; })
        .def_property_readonly("player_max_hp", [](const BattleContext &bc) { return bc.player.maxHp; })
        .def_property_readonly("potion_count", [](const BattleContext &bc) { return bc.potionCount; })
        .def("combat_value", [](const BattleContext &bc, double win_base, double potion_weight) {
            return combat_terminal_value(bc, win_base, potion_weight);
        }, py::arg("win_base") = 0.4, py::arg("potion_weight") = 4.0,
           "value of a finished battle as used by NetSearch (0 if not won)")
        .def_property_readonly("player_block", [](const BattleContext &bc) { return bc.player.block; })
        .def_property_readonly("player_weak", [](const BattleContext &bc) { return bc.player.weak; })
        .def_property_readonly("player_frail", [](const BattleContext &bc) { return bc.player.frail; })
        .def_property_readonly("crimson_mantle_self_damage", [](const BattleContext &bc) { return bc.player.crimsonMantleSelfDamage; })
        .def_property_readonly("inferno_self_damage", [](const BattleContext &bc) { return bc.player.infernoSelfDamage; })
        .def_property_readonly("inferno_before_crimson_mantle", [](const BattleContext &bc) { return bc.player.infernoBeforeCrimsonMantle; })
        .def_readwrite("gold", &BattleContext::gold)
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
        .def_property_readonly("hand_enchantments", [](const BattleContext &bc) {
            return card_enchantments(bc.hand, bc.handCount);
        })
        .def_property_readonly("draw", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.drawCount; ++i) out.append(static_cast<int>(bc.draw[i].id));
            return out;
        })
        .def_property_readonly("discard", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.discardCount; ++i) out.append(static_cast<int>(bc.discard[i].id));
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
        // Occupied potions in slot order; potion_belt keeps physical holes (0),
        // which is what USE_POTION action indices refer to.
        .def_property_readonly("potions", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.potionSlots; ++i) if (bc.potions[i]) out.append(bc.potions[i]);
            return out;
        })
        .def_property_readonly("potion_belt", [](const BattleContext &bc) {
            py::list out;
            for (int i = 0; i < bc.potionSlots; ++i) out.append(bc.potions[i]);
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

    py::enum_<ActType>(m, "ActType")
        .value("OVERGROWTH", ActType::OVERGROWTH)
        .value("HIVE", ActType::HIVE)
        .value("GLORY", ActType::GLORY)
        .value("UNDERDOCKS", ActType::UNDERDOCKS);
    py::class_<NativeProgressContext>(m, "NativeProgressContext",
        "Limited native progress inputs; does not implement all card/relic/event epoch unlocks.")
        .def(py::init<>())
        .def_readwrite("apply_discovery_order", &NativeProgressContext::applyDiscoveryOrder)
        .def_readwrite("number_of_runs", &NativeProgressContext::numberOfRuns)
        .def_readwrite("neow_unlocked", &NativeProgressContext::neowUnlocked)
        .def_readwrite("orobas_unlocked", &NativeProgressContext::orobasUnlocked)
        .def_readwrite("darv_unlocked", &NativeProgressContext::darvUnlocked)
        .def_readwrite("underdocks_unlocked", &NativeProgressContext::underdocksUnlocked)
        .def_readwrite("underdocks_discovered", &NativeProgressContext::underdocksDiscovered)
        .def_readwrite("aeonglass_seen", &NativeProgressContext::aeonglassSeen)
        .def_readwrite("wongo_points", &NativeProgressContext::wongoPoints)
        .def_readwrite("revealed_epochs", &NativeProgressContext::revealedEpochs)
        .def_readwrite("event1_epoch_revealed", &NativeProgressContext::event1EpochRevealed)
        .def_readwrite("event2_epoch_revealed", &NativeProgressContext::event2EpochRevealed)
        .def_readwrite("event3_epoch_revealed", &NativeProgressContext::event3EpochRevealed)
        .def_property("seen_encounters", [](const NativeProgressContext &context) {
            std::vector<int> seen;
            for (int i = 1; i < static_cast<int>(Encounter::COUNT); ++i)
                if (context.has_seen(static_cast<Encounter>(i))) seen.push_back(i);
            return seen;
        }, [](NativeProgressContext &context, const std::vector<int> &seen) {
            for (int id : seen)
                if (id <= 0 || id >= static_cast<int>(Encounter::COUNT))
                    throw std::invalid_argument("Invalid seen encounter ID");
            for (auto &word : context.seenEncounters) word = 0;
            for (int id : seen) context.seenEncounters[id / 64] |= std::uint64_t{1} << (id % 64);
        });
    py::class_<RunContext>(m, "RunContext")
        .def(py::init<>())
        .def("init", [](RunContext &rc, std::uint64_t seed, int ascension) {
            rc.init(seed, ascension);
        }, py::arg("seed"), py::arg("ascension") = 0)
        .def("init_seed", &RunContext::init_seed, py::arg("seed"), py::arg("ascension") = 0,
             "Canonicalize/hash an ASCII game seed string; numeric init uses a raw uint64 RNG seed.")
        .def("init_with_context", &RunContext::init_with_context,
             py::arg("seed"), py::arg("ascension"), py::arg("first_act"), py::arg("progress"),
             "Raw uint64 seed; first_act=-1 selects natively, 0 fixes Overgrowth, 3 fixes Underdocks.")
        .def("init_seed_with_context", &RunContext::init_seed_with_context,
             py::arg("seed"), py::arg("ascension"), py::arg("first_act"), py::arg("progress"))
        .def("reset", [](RunContext &rc, std::uint64_t seed, int ascension) {
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
            if (type < static_cast<int>(RunActionType::MOVE) ||
                type > static_cast<int>(RUN_ACTION_LAST)) {
                throw std::invalid_argument("type is not a valid run action type");
            }
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
        .def("observe_public", [](const RunContext &rc) { return public_observation(rc); })
        .def("macro_observation", [](const RunContext &rc) {
            MacroObservation o;
            {
                py::gil_scoped_release release;
                o = macro_observation(rc);
            }
            auto ints = [](const std::vector<std::int32_t> &v, std::vector<py::ssize_t> shape) {
                py::array_t<std::int32_t> a(shape);
                std::copy(v.begin(), v.end(), a.mutable_data());
                return a;
            };
            auto floats = [](const std::vector<float> &v, std::vector<py::ssize_t> shape) {
                py::array_t<float> a(shape);
                std::copy(v.begin(), v.end(), a.mutable_data());
                return a;
            };
            const auto n = static_cast<py::ssize_t>(o.kind.size());
            const auto c = static_cast<py::ssize_t>(o.candType.size());
            py::dict d;
            d["kind"] = ints(o.kind, {n});
            d["id"] = ints(o.id, {n});
            d["num"] = floats(o.num, {n, MACRO_ENTITY_NUM});
            d["edges"] = ints(o.edges, {static_cast<py::ssize_t>(o.edges.size() / 2), 2});
            d["cand_type"] = ints(o.candType, {c});
            d["cand_index"] = ints(o.candIndex, {c});
            d["cand_target"] = ints(o.candTarget, {c});
            d["cand_target2"] = ints(o.candTarget2, {c});
            d["cand_num"] = floats(o.candNum, {c, MACRO_CAND_NUM});
            d["phase"] = o.phase;
            return d;
        }, "entity-structured public observation for the out-of-combat policy")
        .def("play_combat_mcts", [](RunContext &rc, int normal, int boss, double c, std::uint32_t seed,
                                    int decision_start, double epsilon, double potion_weight, int max_steps) {
            CombatDriveResult r;
            {
                py::gil_scoped_release release;
                r = play_combat_mcts(rc, normal, boss, c, seed, decision_start, epsilon, potion_weight, max_steps);
            }
            return py::make_tuple(r.decisions, r.forced, r.simulations, r.ok);
        }, py::arg("normal_simulations"), py::arg("boss_simulations"), py::arg("c") = 4.242640687,
           py::arg("seed") = 0, py::arg("decision_start") = 0, py::arg("epsilon") = 0.05,
           py::arg("potion_weight") = 4.0, py::arg("max_steps") = 20000,
           "play the current combat to its end with fixed hidden-state MCTS; returns "
           "(decisions, forced_steps, simulations, ok)")
        .def("observe_public_combat", [](const RunContext &rc) {
            return public_combat_observation(rc.battle);
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
        .def_property_readonly("combat_is_boss", [](const RunContext &rc) { return rc.combatIsBoss; })
        .def_property_readonly("combat_is_elite", [](const RunContext &rc) { return rc.combatIsElite; })
        .def_property_readonly("hp", [](const RunContext &rc) { return rc.hp; })
        .def_property_readonly("max_hp", [](const RunContext &rc) { return rc.maxHp; })
        .def_property_readonly("gold", [](const RunContext &rc) { return rc.gold; })
        .def_property_readonly("seed", [](const RunContext &rc) { return rc.seed; },
                               "Raw uint64 RNG seed, returned as a Python integer without float conversion.")
        .def_property_readonly("floor", [](const RunContext &rc) { return rc.floor; })
        .def_property_readonly("act_floor", [](const RunContext &rc) { return rc.actFloor; })
        .def_property_readonly("act", [](const RunContext &rc) { return rc.act; })
        .def_property_readonly("act_types", [](const RunContext &rc) {
            return std::vector<ActType>(std::begin(rc.actTypes), std::end(rc.actTypes));
        })
        .def_property_readonly("native_progress", [](const RunContext &rc) { return rc.nativeProgress; })
        .def_property_readonly("golden_path_act", [](const RunContext &rc) { return rc.goldenPathAct; })
        .def_property_readonly("spoils_quest", [](const RunContext &rc) {
            return rc.spoils_quest_active() ? py::make_tuple(int(rc.spoilsQuestRow), int(rc.spoilsQuestCol))
                                            : py::make_tuple();
        })
        .def_property_readonly("unknown_map_points_visited", [](const RunContext &rc) { return rc.unknownMapPointsVisited; })
        .def_property_readonly("screen", [](const RunContext &rc) { return rc.screen; })
        .def_property_readonly("won", [](const RunContext &rc) { return rc.won; })
        .def_property_readonly("truncated", [](const RunContext &rc) { return rc.truncated; })
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
                for (int r = 0; r < MAP_MAX_ROWS && row < 0; ++r) {
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
        .def_property_readonly("boss_encounter", [](const RunContext &rc) { return rc.bossEncounter; })
        .def_property_readonly("second_boss_encounter", [](const RunContext &rc) { return rc.secondBossEncounter; })
        .def_property_readonly("potions", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.potionSlots; ++i) if (rc.potions[i]) out.append(rc.potions[i]);
            return out;
        })
        .def_property_readonly("potion_belt", [](const RunContext &rc) {
            py::list out;
            for (int i = 0; i < rc.potionSlots; ++i) out.append(rc.potions[i]);
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
        .def_property_readonly("ancient_id", [](const RunContext &rc) { return static_cast<int>(rc.ancientId); })
        .def("start_act", [](RunContext &rc, int actIndex) {
            if (actIndex < 0 || actIndex >= MAX_ACTS) return false;
            rc.start_act(actIndex);
            return true;
        })
        .def("begin_event", [](RunContext &rc, int eventId) {
            const sts2::EventInfo *info = sts2::event_info(eventId);
            if (info == nullptr) return false;
            sts2::event_begin(rc, eventId, info->act == 3);
            return true;
        })
        .def_property_readonly("event_name", [](const RunContext &rc) {
            const EventInfo *info = sts2::event_info(rc.eventId);
            return std::string(info ? info->name : "");
        })
        .def_property_readonly("event_page", [](const RunContext &rc) { return rc.eventPage; })
        .def_property_readonly("event_card_selection", [](const RunContext &rc) { return rc.eventCardSelection; })
        .def_property_readonly("card_grid_kind", [](const RunContext &rc) { return rc.cardGrid.kind; })
        .def_property_readonly("card_grid_preview", [](const RunContext &rc) { return rc.cardGrid.preview; })
        .def_property_readonly("card_grid_cards", [](const RunContext &rc) {
            return (rc.cardGrid.kind == 1 || rc.cardGrid.kind == 2 || rc.cardGrid.kind == 5)
                ? card_list(rc.cardGrid.cards, rc.cardGrid.count) : py::list();
        })
        .def_property_readonly("card_grid_selected", [](const RunContext &rc) {
            py::list out;
            if (rc.cardGrid.kind) for (int i = 0; i < rc.cardGrid.count; ++i) out.append(rc.cardGrid.selected[i]);
            return out;
        })
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
        .def_property_readonly("deck_enchantments", [](const RunContext &rc) {
            return card_enchantments(rc.deck, rc.deckCount);
        })
        .def_property_readonly("offered", [](const RunContext &rc) {
            return card_list(rc.offered, rc.screen == RunScreen::CARD_REWARD ? rc.offeredCount : 0);
        })
        .def_property_readonly("reward_is_boss", [](const RunContext &rc) { return rc.rewardIsBoss; })
        .def_property_readonly("reward_gold", [](const RunContext &rc) {
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            return visible ? rc.pendingGoldReward : 0;
        })
        .def_property_readonly("reward_recovered_gold", [](const RunContext &rc) {
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            return visible ? rc.pendingRecoveredGold : 0;
        })
        .def_property_readonly("reward_potion", [](const RunContext &rc) {
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            return visible ? rc.pendingPotionReward : 0;
        })
        .def_property_readonly("reward_potions", [](const RunContext &rc) {
            py::list out;
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            if (visible) for (int i = 0; i < rc.pendingPotionCount; ++i) out.append(rc.pendingPotions[i]);
            return out;
        })
        .def_property_readonly("reward_card_slots", [](const RunContext &rc) {
            py::list out;
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            if (visible) for (int i = 0; i < MAX_CARD_REWARDS; ++i) out.append(rc.rewardCardPending[i]);
            return out;
        })
        .def_property_readonly("reward_stolen_cards", [](const RunContext &rc) {
            py::list out;
            if (rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards)) {
                for (int i = 0; i < rc.stolenSyncCount; ++i) {
                    if (!rc.stolenRewardPending[i]) continue;
                    const Card &c = rc.stolenOriginals[i];
                    out.append(py::make_tuple(i, static_cast<int>(c.id), c.upgraded,
                                              static_cast<int>(c.uid), static_cast<int>(c.enchantment),
                                              c.enchantmentAmount));
                }
            }
            return out;
        })
        .def_property_readonly("reward_card_pending", [](const RunContext &rc) {
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            return visible && rc.pendingCardReward;
        })
        .def_property_readonly("reward_returns_to_event", [](const RunContext &rc) {
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            return visible && rc.pendingReturnToEvent;
        })
        .def_property_readonly("reward_relics", [](const RunContext &rc) {
            py::list out;
            const bool visible = rc.screen == RunScreen::REWARDS ||
                (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
            if (visible) {
                for (int i = 0; i < rc.pendingRelicCount; ++i)
                    out.append(py::make_tuple(rc.pendingRelics[i], rc.pendingRelicClaimed[i]));
            }
            return out;
        })
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
