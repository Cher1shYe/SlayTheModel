#include "sts2/silent.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace sts2 {
namespace {
bool alive(const BattleContext &b,int i){return i>=0&&i<b.monsterCount&&b.monsters[i].alive;}
void poison_all(BattleContext &b,int n){if(n>0)for(int i=0;i<b.monsterCount;++i)if(alive(b,i))b.add_monster_power(i,PowerId::POISON,n);}
template<class F>void each_card(BattleContext &b,F fn){
    Card *piles[]={b.hand,b.draw,b.discard,b.exhaust,b.playPile,b.returnNextTurn};
    const int counts[]={b.handCount,b.drawCount,b.discardCount,b.exhaustCount,b.playCount,b.returnNextTurnCount};
    for(int p=0;p<6;++p)for(int i=0;i<counts[p];++i)fn(piles[p][i]);
    if(b.activePlay.active)fn(b.activePlay.card);
}
void restore_hand(BattleContext &b,const Card &c,int at){
    if(b.handCount>=MAX_HAND)throw std::overflow_error("Selected Silent hand card cannot be restored");
    at=std::clamp(at,0,b.handCount);
    for(int i=b.handCount;i>at;--i)b.hand[i]=b.hand[i-1];
    b.hand[at]=c;++b.handCount;
}
void remove_power(BattleContext &b,PowerId id){const int n=b.player_power(id);if(n)b.add_player_power(id,-n);}
}

void silent_create_shivs(BattleContext &b,int count,bool upgraded,bool inky){
    if(b.outcome!=Outcome::UNDECIDED)return;
    for(int i=0;i<count;++i){
        Card shiv=make_card(CardId::SHIV,upgraded,b.require_card_uid());
        silent_card_entered_combat(b,shiv,false);
        if(inky){shiv.enchantment=EnchantmentId::INKY;shiv.enchantmentAmount=1;}
        b.add_card_to_hand(shiv);
    }
}

void silent_before_card_played(BattleContext &b,const Card &){
    auto &s=b.activePlay.silent;s=SilentPlayState();
    s.afterimage=b.player_power(PowerId::AFTERIMAGE);
    s.serpentForm=b.player_power(PowerId::SERPENT_FORM);
    for(int i=0;i<b.monsterCount;++i)if(alive(b,i))s.strangle[i]=b.monster_power(i,PowerId::STRANGLE);
}

void silent_after_card_played(BattleContext &b,Card &card){
    // CardPlayFinished is recorded before AfterCardPlayed hooks.
    if(card_is_attack(card))++b.silent.attacksFinishedThisTurn;
    if(card.id==CardId::SHIV)++b.silent.shivsFinishedThisTurn;
    if(card_is_skill(card)){
        ++b.silent.skillsFinishedThisTurn;
        each_card(b,[](Card &c){if(c.id==CardId::PINPOINT)card_modify_cost(c,-1,false,2);});
        if(b.player_power(PowerId::MASTER_PLANNER)>0)card.slyThisCombat=true;
    }
    const auto saved=b.activePlay.silent;
    if(saved.afterimage>0)b.gain_block(saved.afterimage,false,false);
    if(saved.serpentForm>0&&b.outcome==Outcome::UNDECIDED){
        const int target=b.random_alive_monster();
        if(target>=0)b.damage_monster(target,saved.serpentForm,true,false);
    }
    for(int i=0;i<b.monsterCount&&b.outcome==Outcome::UNDECIDED;++i)
        if(saved.strangle[i]>0&&alive(b,i))b.damage_monster(i,saved.strangle[i],false,false,true);
}

void silent_card_entered_combat(BattleContext &b,Card &card,bool isClone){
    if(card.id==CardId::SHIV&&b.player_power(PowerId::PHANTOM_BLADES)>0)card.retainThisCombat=true;
    if(card.id==CardId::PINPOINT&&!isClone&&b.silent.skillsFinishedThisTurn>0)
        card_modify_cost(card,-b.silent.skillsFinishedThisTurn,false,2);
}

void silent_card_drawn(BattleContext &b,Card &card,bool fromHandDraw){
    ++b.silent.drawnThisCombat;
    if(b.activePlay.active){
        auto &s=b.activePlay.silent;
        if(s.stage==2){if(s.drawn++==0)s.firstDrawnType=static_cast<int>(card_def(card.id).type);}
        if(s.stage==3)card.retainThisTurn=true;
    }
    poison_all(b,b.player_power(PowerId::CORROSIVE_WAVE));
    if(!fromHandDraw&&!b.inMonsterTurn&&b.player_power(PowerId::SPEEDSTER)>0)
        b.attack_all(b.player_power(PowerId::SPEEDSTER),1,false);
}

void silent_card_discarded(BattleContext &b,const Card &){++b.silent.discardedThisTurn;}

void silent_before_hand_draw(BattleContext &b){
    silent_create_shivs(b,b.player_power(PowerId::INFINITE_BLADES));
    const int count=b.silent.nightmareCount;
    for(int i=0;i<count;++i){
        for(int n=0;n<b.silent.nightmareAmounts[i];++n){
            Card clone=b.silent.nightmareCards[i];clone.uid=b.require_card_uid();
            silent_card_entered_combat(b,clone,true);b.add_card_to_hand(clone);
        }
    }
    if(count){b.silent.nightmareCount=0;remove_power(b,PowerId::NIGHTMARE);}
}

void silent_after_player_turn_start(BattleContext &b){
    const int n=b.player_power(PowerId::TOOLS_OF_THE_TRADE);
    if(n<=0||b.handCount==0)return;
    if(n>=b.handCount){Card cards[MAX_HAND];const int count=b.handCount;std::copy(b.hand,b.hand+count,cards);b.discard_cards(cards,count,0);return;}
    Card source=make_card(CardId::TOOLS_OF_THE_TRADE,false,0xffff);
    b.silent.turnStartSelectedCount=0;
    b.start_choice(ChoiceOp::SILENT_DISCARD,ChoicePile::HAND,std::min(n,b.handCount),false,source,false);
    if(b.pending.op!=ChoiceOp::NONE)b.pending.hasSource=false;
}

void silent_reset_turn_counters(BattleContext &b){
    b.silent.discardedThisTurn=0;b.silent.attacksFinishedThisTurn=0;
    b.silent.skillsFinishedThisTurn=0;b.silent.shivsFinishedThisTurn=0;
}
void silent_player_turn_start(BattleContext &b){
    // AfterSideTurnStart follows SetupPlayerTurn's draw/AfterPlayerTurnStart.
    // Blur's previous amount has already protected the block clear.
    if(b.player_power(PowerId::BLUR)>0)b.add_player_power(PowerId::BLUR,-1);
    poison_all(b,b.player_power(PowerId::NOXIOUS_FUMES));
    if(b.player_power(PowerId::WRAITH_FORM)>0)b.add_player_power(PowerId::DEXTERITY,-b.player_power(PowerId::WRAITH_FORM));
    if(b.player_power(PowerId::SHADOW_STEP)>0){b.add_player_power(PowerId::DOUBLE_DAMAGE,b.player_power(PowerId::SHADOW_STEP));remove_power(b,PowerId::SHADOW_STEP);}
    silent_trigger_poison(b,-1);
}

void silent_player_turn_end(BattleContext &b){
    for(PowerId id:{PowerId::ANTICIPATE,PowerId::FADE}){
        const int n=b.player_power(id);if(n){remove_power(b,id);b.add_player_power(PowerId::DEXTERITY,-n);}
    }
    remove_power(b,PowerId::BURST);remove_power(b,PowerId::CORROSIVE_WAVE);remove_power(b,PowerId::SHADOWMELD);
    each_card(b,[](Card &c){c.retainThisTurn=false;c.slyThisTurn=false;});
}

void silent_enemy_turn_start(BattleContext &b){for(int i=0;i<b.monsterCount&&b.outcome==Outcome::UNDECIDED;++i)if(alive(b,i))silent_trigger_poison(b,i);}
void silent_enemy_turn_end(BattleContext &b){
    remove_power(b,PowerId::CONCOCT);
    for(int i=0;i<b.monsterCount;++i){
        const int n=b.monster_power(i,PowerId::PIERCING_WAIL);
        if(n){b.add_monster_power(i,PowerId::STRENGTH,n);b.add_monster_power(i,PowerId::PIERCING_WAIL,-n);}
        b.monsters[i].power[static_cast<int>(PowerId::STRANGLE)]=0;
        b.monsters[i].power[static_cast<int>(PowerId::FLANKING)]=0;
    }
}

void silent_trigger_poison(BattleContext &b,int target){
    if(target>=0&&!alive(b,target))return;
    int amount=target<0?b.player_power(PowerId::POISON):b.monster_power(target,PowerId::POISON);
    int extra=target<0?0:b.player_power(PowerId::ACCELERANT);
    if(target<0)for(int i=0;i<b.monsterCount;++i)if(alive(b,i))extra+=b.monster_power(i,PowerId::ACCELERANT);
    const int times=std::min(amount,1+extra);
    for(int n=0;n<times;++n){
        if(target<0){
            b.damage_player(b.player_power(PowerId::POISON),true,false);
            if(b.player.hp>0)b.add_player_power(PowerId::POISON,-1);
        }else{
            if(!alive(b,target))break;
            b.damage_monster(target,b.monster_power(target,PowerId::POISON),false,false,true);
            if(alive(b,target))b.add_monster_power(target,PowerId::POISON,-1);
        }
    }
}

void silent_after_attack_damage(BattleContext &b,int target,int unblocked){
    if(unblocked<=0||!alive(b,target))return;
    for(PowerId id:{PowerId::ENVENOM,PowerId::CONCOCT})
        if(b.player_power(id)>0)b.add_monster_power(target,PowerId::POISON,b.player_power(id));
}

double silent_damage_additive(const BattleContext &b,const Card *card,bool powered){
    if(!powered||card==nullptr||card->id!=CardId::SHIV)return 0;
    return b.player_power(PowerId::ACCURACY)+(b.silent.shivsFinishedThisTurn==0?b.player_power(PowerId::PHANTOM_BLADES):0);
}
double silent_damage_multiplier(const BattleContext &b,int target,bool powered){
    return powered&&alive(b,target)&&b.monsters[target].weak>0?1.0+b.player_power(PowerId::TRACKING)/100.0:1.0;
}
double silent_block_multiplier(const BattleContext &b){return std::pow(2.0,b.player_power(PowerId::SHADOWMELD));}
bool silent_card_playable(const BattleContext &b,const Card &c){return c.id!=CardId::GRAND_FINALE||b.drawCount==0;}
TargetType silent_card_target(const BattleContext &b,const Card &c){return c.id==CardId::SHIV&&b.player_power(PowerId::FAN_OF_KNIVES)>0?TargetType::ALL_ENEMIES:card_def(c.id).target;}
int silent_extra_play_count(BattleContext &b,const Card &c){
    if(card_is_skill(c)&&b.player_power(PowerId::BURST)>0){b.add_player_power(PowerId::BURST,-1);return 1;}return 0;
}

bool silent_resolve_choice(BattleContext &b,const Card &chosen,int handIndex){
    switch(b.pending.op){
    case ChoiceOp::SILENT_DISCARD:
        if(b.activePlay.active){auto &s=b.activePlay.silent;if(s.selectedCount>=MAX_HAND)throw std::overflow_error("Silent discard batch overflow");s.selected[s.selectedCount++]=chosen;}
        else{auto &s=b.silent;if(s.turnStartSelectedCount>=MAX_HAND)throw std::overflow_error("Tools of the Trade discard batch overflow");s.turnStartSelected[s.turnStartSelectedCount++]=chosen;}
        return true;
    case ChoiceOp::SILENT_SLY:{Card marked=chosen;marked.slyThisTurn=true;restore_hand(b,marked,handIndex);return true;}
    case ChoiceOp::SILENT_NIGHTMARE:{
        silent_store_nightmare(b,chosen);restore_hand(b,chosen,handIndex);return true;
    }
    default:return false;
    }
}

bool silent_finish_choice(BattleContext &b,ChoiceOp op){
    if(op==ChoiceOp::SILENT_SLY||op==ChoiceOp::SILENT_NIGHTMARE)return true;
    if(op!=ChoiceOp::SILENT_DISCARD)return false;
    Card selected[MAX_HAND];int n;
    if(b.activePlay.active){auto &s=b.activePlay.silent;n=s.selectedCount;std::copy(s.selected,s.selected+n,selected);s.selectedCount=0;}
    else{auto &s=b.silent;n=s.turnStartSelectedCount;std::copy(s.turnStartSelected,s.turnStartSelected+n,selected);s.turnStartSelectedCount=0;}
    b.discard_cards(selected,n,0);return true;
}

void silent_store_nightmare(BattleContext &b,const Card &chosen){
    if(b.silent.nightmareCount>=MAX_PILE)throw std::overflow_error("Nightmare instance capacity exceeded");
    Card clone=chosen;clone.galvanized=0;
    const int i=b.silent.nightmareCount++;b.silent.nightmareCards[i]=clone;b.silent.nightmareAmounts[i]=3;
    b.add_player_power(PowerId::NIGHTMARE,3);
}
}
