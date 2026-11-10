#include "sts2/relic_card_rewards.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"

namespace sts2 {
namespace {
constexpr int MAX_RELIC_CARD_CANDIDATES = 15;

bool reward_rarity(Rarity rarity) {
    return rarity==Rarity::COMMON || rarity==Rarity::UNCOMMON || rarity==Rarity::RARE;
}

int append_pool(CardPool pool, CardId *out, int offset) {
    const int begin=offset;
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i) {
        const CardId id=static_cast<CardId>(i);const auto &d=card_def(id);
        if(card_native_available(id) && d.pool==pool && !(d.flags&CF_MULTIPLAYER_ONLY) && reward_rarity(d.rarity))
            out[offset++]=id;
    }
    native_sort_card_ids(out+begin,offset-begin);
    return offset;
}

// The shared order helper returns character pools in native UnlockState order.
int reward_pool(const RunContext &rc,RelicId source,CardPool seaPool,CardId *out) {
    int count=0;
    if(source==RelicId::LEAD_PAPERWEIGHT)return append_pool(CardPool::COLORLESS,out,0);
    if(source==RelicId::SEA_GLASS)return append_pool(seaPool,out,0);
    if(source==RelicId::DREAM_CATCHER && run_has_relic(rc,RelicId::PRISMATIC_GEM)) {
        CardPool pools[5];const int n=native_unlocked_character_pools(rc,pools,5);
        bool hasIronclad=false;
        for(int i=0;i<n;++i){count=append_pool(pools[i],out,count);hasIronclad|=pools[i]==CardPool::IRONCLAD;}
        if(!hasIronclad)count=append_pool(CardPool::IRONCLAD,out,count);
    } else count=append_pool(CardPool::IRONCLAD,out,0);
    if(source==RelicId::DREAM_CATCHER && run_has_relic(rc,RelicId::DINGY_RUG))
        count=append_pool(CardPool::COLORLESS,out,count);
    return count;
}

Rarity roll_rarity(RunContext &rc,bool encounter) {
    const float roll=rc.playerRng[PRNG_REWARDS].next_float();
    const float rare=(rc.ascension>=7?0.0149f:0.03f)+(encounter?rc.cardRarityOdds:0.0f);
    const Rarity rarity=roll<rare?Rarity::RARE:roll<rare+0.37f?Rarity::UNCOMMON:Rarity::COMMON;
    if(encounter)rc.cardRarityOdds=rarity==Rarity::RARE?-0.05f:
        std::min(0.4f,rc.cardRarityOdds+(rc.ascension>=7?0.005f:0.01f));
    return rarity;
}

void reward_hooks(RunContext &rc,Card *cards,int count,bool isCardReward) {
    // Each Sea Glass rarity group is an independent CreateForReward call.
    // Late hooks run in owned relic order; enchantments applied earlier prevent
    // later incompatible enchantments, exactly as native CanEnchant does.
    for(int slot=0;slot<rc.relicCount;++slot) {
        if(!run_relic_active_at(rc,slot))continue;
        const auto id=static_cast<RelicId>(rc.relics[slot]);
        if(id==RelicId::WING_CHARM) {
            int eligible[MAX_RELIC_CARD_CANDIDATES],n=0;
            for(int i=0;i<count;++i)if(card_can_enchant(cards[i],EnchantmentId::SWIFT))eligible[n++]=i;
            if(n)card_apply_enchantment(cards[eligible[rc.runRng[RNG_NICHE].next_int(0,n-1)]],EnchantmentId::SWIFT,1);
            continue;
        }
        const bool silver=id==RelicId::SILVER_CRUCIBLE && isCardReward && rc.silverCrucibleUses>0;
        const bool silken=id==RelicId::SILKEN_TRESS && isCardReward && rc.relicAux[slot]==0;
        for(int i=0;i<count;++i) {
            Card &c=cards[i];const auto type=card_def(c.id).type;
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
               bool uniform,Rarity fixedRarity,bool upgradeRoll,bool isCardReward) {
    for(int i=0;i<count;++i) {
        CardId options[static_cast<int>(CardId::COUNT)];int n=0;
        Rarity rarity=uniform?fixedRarity:roll_rarity(rc,isCardReward);
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
        out[i]=rc.make_run_card(options[rc.playerRng[PRNG_REWARDS].next_int(0,n-1)],false);
        if(upgradeRoll) {
            const float roll=rc.playerRng[PRNG_REWARDS].next_float();
            const float odds=card_def(out[i].id).rarity==Rarity::RARE?0.0f:rc.act*(rc.ascension>=7?0.125f:0.25f);
            if(card_upgradable(out[i])&&roll<=odds)card_apply_upgrade(out[i]);
        }
    }
    reward_hooks(rc,out,count,isCardReward);
    return count;
}
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
