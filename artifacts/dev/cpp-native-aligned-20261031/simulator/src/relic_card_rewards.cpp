#include "sts2/relic_card_rewards.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"

namespace sts2 {
namespace {
constexpr int MAX_RELIC_CARD_CANDIDATES = 15;

bool reward_rarity(Rarity rarity) {
    return rarity==Rarity::COMMON || rarity==Rarity::UNCOMMON || rarity==Rarity::RARE;
}

int append_pool(CardPool pool, CardId *out, int offset, std::uint64_t epochs) {
    const int begin=offset;
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i) {
        const CardId id=static_cast<CardId>(i);const auto &d=card_def(id);
        if(card_native_available(id) && card_epoch_unlocked(epochs,id) && d.pool==pool && !(d.flags&CF_MULTIPLAYER_ONLY) && reward_rarity(d.rarity))
            out[offset++]=id;
    }
    native_sort_card_ids(out+begin,offset-begin);
    return offset;
}

// The shared order helper returns character pools in native UnlockState order.
int reward_pool(const RunContext &rc,RelicId source,CardPool seaPool,CardId *out) {
    int count=0;
    if(source==RelicId::LEAD_PAPERWEIGHT)return append_pool(CardPool::COLORLESS,out,0,rc.nativeProgress.revealedEpochs);
    if(source==RelicId::SEA_GLASS)return append_pool(seaPool,out,0,rc.nativeProgress.revealedEpochs);
    if(source==RelicId::DREAM_CATCHER)return native_card_reward_pool(rc,CardPool::IRONCLAD,out);
    return append_pool(CardPool::IRONCLAD,out,count,rc.nativeProgress.revealedEpochs);
}

Rarity roll_rarity(RunContext &rc,bool encounter) {
    const float roll=rc.playerRng[PRNG_REWARDS].next_float();
    const float rare=(rc.ascension>=7?0.0149f:0.03f)+(encounter?rc.cardRarityOdds:0.0f);
    const Rarity rarity=roll<rare?Rarity::RARE:roll<rare+0.37f?Rarity::UNCOMMON:Rarity::COMMON;
    if(encounter)rc.cardRarityOdds=rarity==Rarity::RARE?-0.05f:
        std::min(0.4f,rc.cardRarityOdds+(rc.ascension>=7?0.005f:0.01f));
    return rarity;
}

void reward_hooks(RunContext &rc,Card *cards,int count,bool isCardReward,bool lavaLamp=false) {
    // Each Sea Glass rarity group is an independent CreateForReward call.
    // Late hooks run in owned relic order; enchantments applied earlier prevent
    // later incompatible enchantments, exactly as native CanEnchant does.
    for(int slot=0;slot<rc.relicCount;++slot) {
        if(!run_relic_active_at(rc,slot))continue;
        const auto id=static_cast<RelicId>(rc.relics[slot]);
        // LavaLamp: combat rooms where no qualifying damage was taken.
        if(id==RelicId::LAVA_LAMP) {
            if(lavaLamp)for(int i=0;i<count;++i)if(card_upgradable(cards[i]))card_apply_upgrade(cards[i]);
            continue;
        }
        if(id==RelicId::WING_CHARM) {
            int eligible[MAX_RELIC_CARD_CANDIDATES],n=0;
            for(int i=0;i<count;++i)if(card_can_enchant(cards[i],EnchantmentId::SWIFT))eligible[n++]=i;
            if(n)card_apply_enchantment(cards[eligible[rc.runRng[RNG_NICHE].next_int(0,n-1)]],EnchantmentId::SWIFT,1);
            continue;
        }
        const bool silver=id==RelicId::SILVER_CRUCIBLE && isCardReward && rc.silverCrucibleUses>0;
        const bool silken=id==RelicId::SILKEN_TRESS && isCardReward && rc.relicAux[slot]==0;
        for(int i=0;i<count;++i) {
            Card &c=cards[i];const auto type=card_type(c);
            if(silver || (id==RelicId::MOLTEN_EGG&&type==CardType::ATTACK) ||
               (id==RelicId::TOXIC_EGG&&type==CardType::SKILL) || (id==RelicId::FROZEN_EGG&&type==CardType::POWER)) {
                if(card_upgradable(c))card_apply_upgrade(c);
            }
            if(id==RelicId::FRESNEL_LENS)card_apply_enchantment(c,EnchantmentId::NIMBLE,2);
            if(id==RelicId::GLITTER || silken)card_apply_enchantment(c,EnchantmentId::GLAM,1);
        }
        if(silver)--rc.silverCrucibleUses;
        if(silken)rc.relicAux[slot]=1;
    }
}

int draw_group(RunContext &rc,const CardId *pool,int poolCount,Card *out,int count,
               bool uniform,Rarity fixedRarity,bool upgradeRoll,bool isCardReward,int encounterOdds=-1,
               Rng *rngOverride=nullptr) {
    Rng &pick=rngOverride?*rngOverride:rc.playerRng[PRNG_REWARDS];  // CardCreationOptions.RngOverride
    // Encounter-sourced rewards use (and update) the pity offset; others roll base odds.
    const bool encounter=encounterOdds<0?isCardReward:encounterOdds!=0;
    for(int i=0;i<count;++i) {
        CardId options[static_cast<int>(CardId::COUNT)];int n=0;
        Rarity rarity=uniform?fixedRarity:roll_rarity(rc,encounter);
        // Native promotes a rarity through Common -> Uncommon -> Rare and
        // wraps if necessary; the pity update uses the rolled rarity.
        for(int attempt=0;attempt<3;++attempt) {
            n=0;
            for(int j=0;j<poolCount;++j) {
                const CardId id=pool[j];if(card_def(id).rarity!=rarity)continue;
                bool used=false;for(int k=0;k<i;++k)used|=out[k].id==id;
                if(!used)options[n++]=id;
            }
            if(n || uniform)break;
            rarity=rarity==Rarity::COMMON?Rarity::UNCOMMON:rarity==Rarity::UNCOMMON?Rarity::RARE:Rarity::COMMON;
        }
        if(!n)return -1;
        out[i]=rc.make_run_card(options[pick.next_int(0,n-1)],false);
        if(upgradeRoll) {
            const float roll=pick.next_float();
            const float odds=card_def(out[i].id).rarity==Rarity::RARE?0.0f:rc.act*(rc.ascension>=7?0.125f:0.25f);
            if(card_upgradable(out[i])&&roll<=odds)card_apply_upgrade(out[i]);
        }
    }
    reward_hooks(rc,out,count,isCardReward);
    return count;
}
}

// LastingCandy.TryModifyCardRewardOptions: on its triggering combat (odd
// CombatRewardsSeen) add one Power from the reward's pools that is not already
// offered (dupes allowed only if none remain), Source Other: base odds of the
// encounter type with rarity wrap, Rewards RNG pick, then the upgrade roll.
static bool lasting_candy_card(RunContext &rc, const Card *cards, int count, int oddsType, Card &out) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    const int total = native_card_reward_pool(rc, CardPool::IRONCLAD, pool);
    CardId powers[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int pass = 0; pass < 2 && n == 0; ++pass)
        for (int i = 0; i < total; ++i) {
            if (card_def(pool[i]).type != CardType::POWER) continue;
            bool offered = false;
            for (int k = 0; k < count; ++k) offered |= cards[k].id == pool[i];
            if (pass == 0 && offered) continue;
            powers[n++] = pool[i];
        }
    if (n == 0) return false;
    Rng &rng = rc.playerRng[PRNG_REWARDS];
    const bool a7 = rc.ascension >= 7;
    const float rare = oddsType == 2 ? 1.0f : oddsType == 1 ? (a7 ? 0.05f : 0.1f) : (a7 ? 0.0149f : 0.03f);
    const float uncommon = oddsType == 2 ? 0.0f : oddsType == 1 ? 0.4f : 0.37f;
    const float roll = rng.next_float();
    Rarity rarity = roll < rare ? Rarity::RARE : roll < uncommon + rare ? Rarity::UNCOMMON : Rarity::COMMON;
    CardId options[static_cast<int>(CardId::COUNT)];
    int m = 0;
    for (int attempt = 0; attempt < 3 && m == 0; ++attempt) {
        for (int i = 0; i < n; ++i) if (card_def(powers[i]).rarity == rarity) options[m++] = powers[i];
        if (!m) rarity = rarity == Rarity::COMMON ? Rarity::UNCOMMON : rarity == Rarity::UNCOMMON ? Rarity::RARE : Rarity::COMMON;
    }
    if (!m) return false;
    out = rc.make_run_card(options[rng.next_int(0, m - 1)], false);
    const float up = rng.next_float();
    const float odds = card_def(out.id).rarity == Rarity::RARE ? 0.0f : rc.act * (a7 ? 0.125f : 0.25f);
    if (card_upgradable(out) && up <= odds) card_apply_upgrade(out);
    return true;
}

int apply_card_reward_hooks(RunContext &rc, Card *cards, int count, int capacity, int encounterOdds,
                            bool lavaLampEligible) {
    const bool fromCombat = encounterOdds >= 0;
    if (fromCombat && count > 0 && count < capacity) {
        for (int slot = 0; slot < rc.relicCount; ++slot) {
            if (!run_relic_active_at(rc, slot) || rc.relics[slot] != static_cast<int>(RelicId::LASTING_CANDY)) continue;
            const int seen = rc.relicAux[slot];
            Card extra;
            if (seen > 0 && seen % 2 == 1 && lasting_candy_card(rc, cards, count, encounterOdds, extra))
                cards[count++] = extra;
        }
    }
    reward_hooks(rc, cards, count, true, fromCombat && lavaLampEligible);
    return count;
}

int native_card_reward_pool(const RunContext &rc, CardPool base, CardId *out) {
    CardPool pools[8];
    int n = 0;
    pools[n++] = base;
    auto has = [&](CardPool p) { for (int i = 0; i < n; ++i) if (pools[i] == p) return true; return false; };
    for (int slot = 0; slot < rc.relicCount; ++slot) {
        if (!run_relic_active_at(rc, slot)) continue;
        const auto id = static_cast<RelicId>(rc.relics[slot]);
        if (id == RelicId::PRISMATIC_GEM) {
            bool allColorless = true;
            for (int i = 0; i < n; ++i) allColorless &= pools[i] == CardPool::COLORLESS;
            if (allColorless) continue;
            CardPool merged[8];
            int m = native_unlocked_character_pools(rc, merged, 5);
            for (int i = 0; i < n; ++i) {
                bool seen = false;
                for (int j = 0; j < m; ++j) seen |= merged[j] == pools[i];
                if (!seen) merged[m++] = pools[i];
            }
            std::copy(merged, merged + m, pools);
            n = m;
        } else if (id == RelicId::DINGY_RUG && !has(CardPool::COLORLESS)) {
            pools[n++] = CardPool::COLORLESS;
        }
    }
    int count = 0;
    for (int i = 0; i < n; ++i) count = append_pool(pools[i], out, count,rc.nativeProgress.revealedEpochs);
    return count;
}

bool card_reward_pool_widened(const RunContext &rc) {
    return run_has_relic(rc, RelicId::PRISMATIC_GEM) || run_has_relic(rc, RelicId::DINGY_RUG);
}

int make_default_odds_event_cards(RunContext &rc, CardPool pool, EventCardFilter filter,
                                  Card *out, int count) {
    CardId ids[static_cast<int>(CardId::COUNT)];
    const int total = append_pool(pool, ids, 0,rc.nativeProgress.revealedEpochs);
    int kept = 0;
    for (int i = 0; i < total; ++i) {
        const CardDef &d = card_def(ids[i]);
        if (filter == EventCardFilter::POWER && d.type != CardType::POWER) continue;
        // EnergyCost.Canonical == 0 && !CostsX (X costs are encoded as -1).
        if (filter == EventCardFilter::CANONICAL_ZERO_COST && d.cost != 0) continue;
        ids[kept++] = ids[i];
    }
    if (!kept) return -1;
    return draw_group(rc, ids, kept, out, count, false, Rarity::COMMON, false, false);
}

int make_uniform_rarity_card_reward(RunContext &rc, CardPool pool, Rarity rarity,
                                    Card *out, int count, int typeFilter) {
    CardId ids[static_cast<int>(CardId::COUNT)];
    int total = append_pool(pool, ids, 0,rc.nativeProgress.revealedEpochs);
    if (typeFilter >= 0) {
        int kept = 0;
        for (int i = 0; i < total; ++i)
            if (static_cast<int>(card_def(ids[i]).type) == typeFilter) ids[kept++] = ids[i];
        total = kept;
    }
    return draw_group(rc, ids, total, out, count, true, rarity, true, true);
}

int make_crystal_sphere_card_reward(RunContext &rc, Rarity rarity, Rng &rng, Card *out) {
    // CardReward(character pool, Uniform, rarity filter).WithRngOverride(rng), 3 cards.
    CardId pool[static_cast<int>(CardId::COUNT)];
    const int total = reward_pool(rc, RelicId::DREAM_CATCHER, CardPool::IRONCLAD, pool);
    return draw_group(rc, pool, total, out, 3, true, rarity, true, true, 0, &rng);
}

int make_default_odds_card_reward(RunContext &rc, Card *out, int count) {
    // Same pool hooks as other IsCardReward rewards (Prismatic Gem, Dingy Rug).
    CardId pool[static_cast<int>(CardId::COUNT)];
    const int total = reward_pool(rc, RelicId::DREAM_CATCHER, CardPool::IRONCLAD, pool);
    return draw_group(rc, pool, total, out, count, false, Rarity::COMMON, false, true, 0);
}

int make_relic_card_reward_candidates(RunContext &rc,RelicId source,Card *out,int capacity,CardPool seaPool) {
    const int count=source==RelicId::LEAD_PAPERWEIGHT?2:source==RelicId::ARCANE_SCROLL?1:
        source==RelicId::DREAM_CATCHER?3:source==RelicId::SEA_GLASS?15:0;
    if(!count||!out||capacity<count)return -1;
    CardId pool[static_cast<int>(CardId::COUNT)];const int total=reward_pool(rc,source,seaPool,pool);
    if(total<count)return -1;
    if(source==RelicId::SEA_GLASS||source==RelicId::ARCANE_SCROLL) {
        for(Rarity rarity:{Rarity::COMMON,Rarity::UNCOMMON,Rarity::RARE}) {
            if(source==RelicId::ARCANE_SCROLL&&rarity!=Rarity::RARE)continue;
            int n=0;for(int i=0;i<total;++i)n+=card_def(pool[i]).rarity==rarity;
            if(n<(source==RelicId::SEA_GLASS?5:1))return -1;
        }
    }
    Card generated[MAX_RELIC_CARD_CANDIDATES];
    if(source==RelicId::SEA_GLASS) {
        int offset=0;
        for(Rarity rarity:{Rarity::COMMON,Rarity::UNCOMMON,Rarity::RARE}) {
            if(draw_group(rc,pool,total,generated+offset,5,true,rarity,false,false)!=5)
                throw std::logic_error("Sea Glass candidate pool changed during generation");
            offset+=5;
        }
    } else {
        if(draw_group(rc,pool,total,generated,count,source==RelicId::ARCANE_SCROLL,Rarity::RARE,
                      source!=RelicId::ARCANE_SCROLL,source==RelicId::DREAM_CATCHER)!=count)
            throw std::logic_error("Native card reward pool exhausted");
    }
    std::copy(generated,generated+count,out);
    return count;
}

CardId prepare_dusty_tome_card(RunContext &rc) {
    CardId candidates[static_cast<int>(CardId::COUNT)];int count=0;
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i) {
        const CardId id=static_cast<CardId>(i);const auto &d=card_def(id);
        // Ironclad is the player character in this run implementation. Break
        // is its ArchaicTooth transcendence card and must not be a Tome offer.
        if(card_native_available(id)&&d.pool==CardPool::IRONCLAD&&d.rarity==Rarity::ANCIENT&&
           id!=CardId::BREAK&&!(d.flags&CF_MULTIPLAYER_ONLY))candidates[count++]=id;
    }
    if(!count)return CardId::INVALID;
    native_sort_card_ids(candidates,count);
    return candidates[rc.playerRng[PRNG_REWARDS].next_int(0,count-1)];
}

bool obtain_dusty_tome_card(RunContext &rc,CardId prepared) {
    const auto &d=card_def(prepared);
    if(!card_native_available(prepared)||d.pool!=CardPool::IRONCLAD||d.rarity!=Rarity::ANCIENT||prepared==CardId::BREAK)return false;
    const int copies=run_has_relic(rc,RelicId::BING_BONG)?2:1;
    if(rc.deckCount>MAX_DECK-copies)return false;
    Card card=rc.make_run_card(prepared,false);
    if(card_upgradable(card))card_apply_upgrade(card);
    return rc.add_card_to_deck(card);
}
}
