#include "sts2/battle.h"
#include "sts2/relics.h"
#include "sts2/silent.h"
#include "sts2/defect.h"
#include "sts2/necrobinder.h"

namespace sts2 {

void BattleContext::auto_play_cards(const Card *cards,int count,int fixedTarget,bool forceExhaust) {
    if(count<0 || count>MAX_PILE-autoPlayQueueCount)
        throw std::overflow_error("Automatic play queue capacity exhausted");
    for(int i=0;i<count;++i) {
        auto &task=autoPlayQueue[autoPlayQueueCount++];
        task.card=cards[i]; task.ownerDepth=activePlay.active?suspendedPlayCount:-1;
        task.target=fixedTarget; task.forceExhaust=forceExhaust; task.dupe=nextPlayIsDupe;
    }
    nextPlayIsDupe=false;
    if(!runningPlayLoop && !resolvingCard && pending.op==ChoiceOp::NONE)run_active_play();
}

bool BattleContext::start_queued_auto_play() {
    const int depth=activePlay.active?suspendedPlayCount:-1;
    int index=0;
    while(index<autoPlayQueueCount && autoPlayQueue[index].ownerDepth!=depth)++index;
    if(index==autoPlayQueueCount)return false;
    AutoPlayRequest task=autoPlayQueue[index];
    for(int i=index;i+1<autoPlayQueueCount;++i)autoPlayQueue[i]=autoPlayQueue[i+1];
    autoPlayQueue[--autoPlayQueueCount]=AutoPlayRequest{};
    // A previous auto-play can move or modify a later selected entity. Use its
    // current combat instance, then detach once; never manufacture a duplicate.
    Card *piles[]={hand,draw,discard,exhaust,playPile,returnNextTurn};
    const int counts[]={handCount,drawCount,discardCount,exhaustCount,playCount,returnNextTurnCount};
    for(int p=0;p<6;++p)for(int i=0;i<counts[p];++i)
        if(piles[p][i].uid==task.card.uid)task.card=piles[p][i];
    detach_card(task.card.uid);
    bool normality=false;
    for(int i=0;i<handCount;++i)normality|=hand[i].id==CardId::NORMALITY && cardsPlayedThisTurn>=3;
    if(!card_is_playable(task.card) || normality ||
       (relic_has(*this,RelicId::VELVET_CHOKER)&&cardsPlayedThisTurn>=6)) {
        if(task.forceExhaust)move_to_exhaust(task.card);else move_to_discard(task.card);
        return true;
    }
    if(activePlay.active) {
        if(suspendedPlayCount==MAX_PLAY_DEPTH)throw std::overflow_error("Nested card play depth exhausted");
        suspendedPlays[suspendedPlayCount++]={activePlay,xCost,pendingDrawRemainder,returnToHand};
    }
    pendingDrawRemainder=0;
    returnToHand=false;
    int target=task.target;
    const auto targetType=silent_card_target(*this,task.card);
    if(target<0 && (targetType==TargetType::ENEMY || targetType==TargetType::RANDOM_ENEMY))
        target=random_alive_monster();
    if(target<0)target=0;
    xCost=player.energy+(card_def(task.card.id).cost<0 && relic_has(*this,RelicId::CHEMICAL_X)?2:0);
    nextPlayIsDupe=task.dupe;
    begin_play(task.card,target,true,task.forceExhaust);
    return true;
}

void BattleContext::restore_suspended_play() {
    if(activePlay.active || suspendedPlayCount==0)return;
    const SuspendedPlay saved=suspendedPlays[--suspendedPlayCount];
    suspendedPlays[suspendedPlayCount]=SuspendedPlay{};
    activePlay=saved.play; xCost=saved.xCost; pendingDrawRemainder=saved.pendingDrawRemainder;
    returnToHand=saved.returnToHand;
}

void BattleContext::discard_cards(const Card *cards,int count,int drawAfter) {
    Card sly[MAX_HAND];int slyCount=0;
    // Explicit discard is distinct from the end-turn flush and result pile.
    for(int i=0;i<count;++i) {
        const Card card=cards[i];
        detach_card(card.uid);
        move_to_discard(card);
        silent_card_discarded(*this,card);
        if(card_has(card,CF_SLY)) {
            if(slyCount==MAX_HAND)throw std::overflow_error("Discard batch exceeds hand");
            sly[slyCount++]=card;
        }
    }
    if(drawAfter>0)draw_cards(drawAfter);
    if(slyCount)auto_play_cards(sly,slyCount);
}

void BattleContext::notify_card_generated(const Card &card) {
    defect_after_card_generated(*this,card);
    necrobinder_card_generated(*this,card);
}
}
