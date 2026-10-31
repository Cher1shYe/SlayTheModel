#include "sts2/relic_persistent.h"
#include <stdexcept>

namespace sts2 {
namespace {
void run_set_aux(RunContext &rc, RelicId id, int value) {
    for(int i=0;i<rc.relicCount;++i)
        if(rc.relics[i]==static_cast<int>(id)) {rc.relicAux[i]=value;return;}
}
void transform_combat_eggs(BattleContext &bc) {
    Card *piles[]={bc.hand,bc.draw,bc.discard,bc.exhaust,bc.playPile,bc.returnNextTurn};
    const int counts[]={bc.handCount,bc.drawCount,bc.discardCount,bc.exhaustCount,bc.playCount,bc.returnNextTurnCount};
    for(int p=0;p<6;++p)for(int i=0;i<counts[p];++i) {
        auto &card=piles[p][i];
        if(card.id!=CardId::BYRDONIS_EGG)continue;
        const auto oldUid=card.uid;
        // CardCmd.TransformTo creates a fresh mutable card, replacing the
        // combat card in the same pile slot, without copying old modifiers.
        card=make_card(CardId::BYRD_SWOOP,false,bc.require_card_uid());
        for(int j=0;j<bc.pending.count;++j)
            if(bc.pending.cards[j].uid==oldUid)bc.pending.cards[j]=card;
    }
}
}

bool relic_persistent_can_hatch(const RunContext &rc) {
    int eggs=0;
    for(int i=0;i<rc.deckCount;++i)eggs+=rc.deck[i].id==CardId::BYRDONIS_EGG;
    if(!eggs||run_has_relic(rc,RelicId::BYRDPIP)||rc.relicCount>=MAX_RELICS)return false;
    // Transform-to-deck still runs Bing Bong's normal acquisition hook.
    return !run_has_relic(rc,RelicId::BING_BONG)||rc.deckCount<=MAX_DECK-eggs;
}
bool relic_persistent_hatch(RunContext &rc) {
    return relic_persistent_can_hatch(rc)&&rc.add_relic(RelicId::BYRDPIP);
}
bool run_has_event_pet(const RunContext &rc) {
    if(run_has_relic(rc,RelicId::BYRDPIP)||run_has_relic(rc,RelicId::PAELS_LEGION))return true;
    for(int i=0;i<rc.deckCount;++i)if(rc.deck[i].id==CardId::BYRDONIS_EGG)return true;
    return false;
}
void relic_persistent_on_obtain(RunContext &rc, RelicId id) {
    if(id!=RelicId::BYRDPIP)return;
    const int hpBefore=rc.hp,goldBefore=rc.gold,maxHpBefore=rc.maxHp;
    int eggs=0;
    for(int i=0;i<rc.deckCount;++i)eggs+=rc.deck[i].id==CardId::BYRDONIS_EGG;
    if(run_has_relic(rc,RelicId::BING_BONG)&&rc.deckCount>MAX_DECK-eggs)
        throw std::overflow_error("Byrdpip transforms exceed deck capacity");
    // The relic's private stream depends on run seed and content ID, never on
    // rewards/niche/transform streams. Player slot is 0 in the single-player run.
    Rng skinRng(rc.seed,"BYRDPIP");
    const int skin=skinRng.next_int(0,3);
    run_set_aux(rc,id,skin);
    for(int i=0;i<rc.deckCount;) {
        if(rc.deck[i].id!=CardId::BYRDONIS_EGG){++i;continue;}
        for(int j=i;j+1<rc.deckCount;++j)rc.deck[j]=rc.deck[j+1];
        rc.deck[--rc.deckCount]=Card{};
        Card replacement=rc.make_run_card(CardId::BYRD_SWOOP,false);
        if(run_has_relic(rc,RelicId::MOLTEN_EGG)&&card_upgradable(replacement))card_apply_upgrade(replacement);
        if(!rc.add_card_to_deck(replacement))throw std::logic_error("Byrdpip transform rejected after capacity preflight");
    }
    if(rc.screen==RunScreen::COMBAT) {
        transform_combat_eggs(rc.battle);
        rc.battle.byrdpipPresent=true;
        if(!relic_has(rc.battle,id)) {
            if(rc.battle.relicCount>=MAX_RELICS)throw std::overflow_error("Byrdpip battle relic capacity exceeded");
            const int index=rc.battle.relicCount++;
            rc.battle.relics[index]=static_cast<int>(id);
            rc.battle.relicAux[index]=0;
            rc.battle.relicWax[index]=false;
            rc.battle.relicMelted[index]=false;
        }
        relic_aux_set(rc.battle,id,skin);
        rc.battle.player.maxHp+=rc.maxHp-maxHpBefore;
        rc.battle.heal_hp(rc.hp-hpBefore);
        rc.battle.gold+=rc.gold-goldBefore;
    }
}
void relic_persistent_rest_entered(RunContext &rc) {
    if(run_has_relic(rc,RelicId::FAKE_VENERABLE_TEA_SET))
        run_set_aux(rc,RelicId::FAKE_VENERABLE_TEA_SET,1);
}
void relic_persistent_before_combat(BattleContext &bc) {
    bc.byrdpipPresent=relic_has(bc,RelicId::BYRDPIP);
    bc.boneTeaPending=relic_has(bc,RelicId::BONE_TEA)&&relic_aux(bc,RelicId::BONE_TEA)>0;
}
void relic_persistent_after_energy_reset(BattleContext &bc) {
    if(!relic_has(bc,RelicId::FAKE_VENERABLE_TEA_SET)||relic_aux(bc,RelicId::FAKE_VENERABLE_TEA_SET)<=0)return;
    ++bc.player.energy;
    relic_aux_set(bc,RelicId::FAKE_VENERABLE_TEA_SET,0);
}
void relic_persistent_finish_turn_start(BattleContext &bc) {
    if(!bc.boneTeaPending||bc.turn!=1||bc.pending.op!=ChoiceOp::NONE||bc.activePlay.active||bc.outcome!=Outcome::UNDECIDED)return;
    bc.boneTeaPending=false;
    if(!relic_has(bc,RelicId::BONE_TEA)||relic_aux(bc,RelicId::BONE_TEA)<=0)return;
    for(int i=0;i<bc.handCount;++i)if(card_upgradable(bc.hand[i]))bc.upgrade_card(bc.hand[i]);
    relic_aux_set(bc,RelicId::BONE_TEA,relic_aux(bc,RelicId::BONE_TEA)-1);
}
}
