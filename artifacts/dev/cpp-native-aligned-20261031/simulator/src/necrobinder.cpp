#include "sts2/necrobinder.h"
#include "sts2/relics.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace sts2 {
namespace {
template<class F> void each_card(BattleContext &b,F f){
    auto pile=[&](Card *p,int n){for(int i=0;i<n;++i)f(p[i]);};
    pile(b.hand,b.handCount);pile(b.draw,b.drawCount);pile(b.discard,b.discardCount);
    pile(b.exhaust,b.exhaustCount);pile(b.playPile,b.playCount);pile(b.returnNextTurn,b.returnNextTurnCount);
    if(b.activePlay.active)f(b.activePlay.card);
}
bool temporary_power(PowerId id){
    switch(id){case PowerId::ENFEEBLING_TOUCH:case PowerId::DARK_SHACKLES:
    case PowerId::PIERCING_WAIL:case PowerId::TEMPORARY_STRENGTH:
    case PowerId::TEMPORARY_DEXTERITY:case PowerId::TEMPORARY_FOCUS:
    case PowerId::FLEX_POTION:case PowerId::SPEED_POTION:return true;default:return false;}
}
bool debuff_delta(PowerId id,int amount){
    if(id==PowerId::STRENGTH||id==PowerId::DEXTERITY||id==PowerId::FOCUS)return amount<0;
    switch(id){
    case PowerId::BIASED_COGNITION:
    case PowerId::BORROWED_TIME:
    case PowerId::CHAINS_OF_BINDING:
    case PowerId::CONFUSED:
    case PowerId::CONQUEROR:
    case PowerId::CONSTRICT:
    case PowerId::DAMPEN:
    case PowerId::DEBILITATE:
    case PowerId::DEMISE:
    case PowerId::DISINTEGRATION:
    case PowerId::DOOM:
    case PowerId::FLANKING:
    case PowerId::FRAIL:
    case PowerId::HANG:
    case PowerId::HEX:
    case PowerId::IMBALANCED:
    case PowerId::KNOCKDOWN:
    case PowerId::MAGIC_BOMB:
    case PowerId::MIND_ROT:
    case PowerId::NEUROSURGE:
    case PowerId::NO_BLOCK:
    case PowerId::NO_DRAW:
    case PowerId::NO_ENERGY_GAIN:
    case PowerId::OBLIVION:
    case PowerId::PLOW:
    case PowerId::POISON:
    case PowerId::RINGING:
    case PowerId::SHRIEK:
    case PowerId::SHRINK:
    case PowerId::SIC_EM:
    case PowerId::SLOTH:
    case PowerId::SLOW:
    case PowerId::SMOGGY:
    case PowerId::STRANGLE:
    case PowerId::SURROUNDED:
    case PowerId::TAG_TEAM:
    case PowerId::TAINTED:
    case PowerId::TANGLED:
    case PowerId::TENDER:
    case PowerId::THE_GAMBIT:
    case PowerId::VULNERABLE:
    case PowerId::WASTE_AWAY:
    case PowerId::WEAK:
    case PowerId::WRAITH_FORM:
        return true;
    default:return false;
    }
}
void hp_lost_osty(BattleContext &b,int amount){
    const int damage=amount*b.player_power(PowerId::NECRO_MASTERY);
    if(damage>0)for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive)b.damage_monster(i,damage,true,false,true);
}
}

bool necrobinder_is_osty_attack(CardId id){
    switch(id){case CardId::BONE_SHARDS:case CardId::FETCH:case CardId::FLATTEN:
    case CardId::HIGH_FIVE:case CardId::POKE:case CardId::PROTECTOR:case CardId::RATTLE:
    case CardId::RIGHT_HAND_HAND:case CardId::SIC_EM:case CardId::SNAP:case CardId::SQUEEZE:
    case CardId::UNLEASH:case CardId::SWEEPING_GAZE:return true;default:return false;}
}
void necrobinder_summon(BattleContext &b,int amount){
    if(amount<=0)return;
    if(b.necro.ostyHp>0){b.necro.ostyMaxHp+=amount;b.necro.ostyHp+=amount;}
    else{b.necro.ostyPresent=true;b.necro.ostyMaxHp=amount;b.necro.ostyHp=amount;
        b.necro.ostyStrength=0;b.necro.ostyWeak=0;b.necro.ostyVulnerable=0;}
}
void necrobinder_kill_osty(BattleContext &b){
    if(b.necro.ostyHp<=0)return;
    const int hp=b.necro.ostyHp;b.necro.ostyHp=0;
    hp_lost_osty(b,hp);b.necro.ostyStrength=0;b.necro.ostyWeak=0;b.necro.ostyVulnerable=0;
    necrobinder_after_death(b,false);
}
int necrobinder_damage_osty(BattleContext &b,int amount,bool unblockable){
    if(b.necro.ostyHp<=0)return 0;
    if(!unblockable){const int blocked=std::min(b.player.block,amount);b.player.block-=blocked;amount-=blocked;}
    const int loss=std::min(std::max(0,amount),b.necro.ostyHp);
    b.necro.ostyHp-=loss;hp_lost_osty(b,loss);
    if(b.necro.ostyHp==0){b.necro.ostyStrength=0;b.necro.ostyWeak=0;b.necro.ostyVulnerable=0;necrobinder_after_death(b,false);}
    return loss;
}
int necrobinder_redirect_damage(BattleContext &b,int unblocked,bool powered){
    if(!powered||b.necro.ostyHp<=0)return unblocked;
    const int before=b.necro.ostyHp;necrobinder_damage_osty(b,unblocked,true);
    return std::max(0,unblocked-before);
}
void necrobinder_attack_osty(BattleContext &b,Card &c,int target,double base,int hits,bool all,bool random){
    if(b.necro.ostyHp<=0)return;
    bool first[4]{},unblocked[4]{};
    const bool previous=b.necro.dealingOstyDamage;b.necro.dealingOstyDamage=true;
    for(int h=0;h<hits&&b.outcome==Outcome::UNDECIDED&&b.necro.ostyHp>0;++h){
        const int chosen=random?b.random_alive_monster():target;
        for(int i=0;i<b.monsterCount;++i){
            if(!all&&i!=chosen)continue;
            if(!b.monsters[i].alive||b.necro.ostyHp<=0)continue;
            const Monster &m=b.monsters[i];
            double damage=base+b.necro.ostyStrength+b.player_power(PowerId::CALCIFY);
            if(c.enchantment==EnchantmentId::VIGOROUS&&!c.enchantmentDisabled)damage+=c.enchantmentAmount;
            if(b.necro.ostyWeak>0)damage*=0.75;
            if(m.vulnerable>0){double vuln=relic_has(b,RelicId::PAPER_PHROG)?1.75:1.5;
                vuln+=b.player_power(PowerId::CRUELTY)/100.0;
                if(b.monster_power(i,PowerId::DEBILITATE)>0)vuln=1.0+(vuln-1.0)*2;
                damage*=vuln;}
            if(b.monster_power(i,PowerId::SOAR)>0)damage*=0.5;
            if(b.monster_power(i,PowerId::FLUTTER)>0)damage*=0.5;
            if(b.monster_power(i,PowerId::SLOW)>0)damage*=1.0+0.1*m.slowCardsThisTurn;
            damage*=necrobinder_damage_multiplier(b,&c,i,true);
            damage*=relics_damage_multiplier(b,c);
            const auto result=b.damage_monster(i,std::max(0,static_cast<int>(std::floor(damage))),true,true);
            if(!first[i])unblocked[i]=result.unblocked>0;first[i]=true;
        }
    }
    b.necro.dealingOstyDamage=previous;
    ++b.necro.ostyAttacksThisTurn;
    each_card(b,[&](Card &card){if(card.id==CardId::FLATTEN)card_modify_cost(card,0,true,2);});
    if(relic_has(b,RelicId::BONE_FLUTE))b.gain_block(2,false,false);
    for(int i=0;i<b.monsterCount;++i)if(first[i])b.trigger_skittish(i,unblocked[i]);
}
void necrobinder_create_souls(BattleContext &b,int count,ChoicePile destination,bool upgraded){
    if(count<=0)return;
    if(count>160)throw std::overflow_error("Soul generation batch exceeds card capacity");
    Card cards[160];for(int i=0;i<count;++i)cards[i]=make_card(CardId::SOUL,upgraded,b.require_card_uid());
    for(int i=0;i<count;++i){
        if(destination==ChoicePile::HAND)b.add_card_to_hand(cards[i]);
        else if(destination==ChoicePile::DISCARD)b.add_card_to_discard(cards[i]);
        else b.add_card_to_draw_random(cards[i]);
        b.notify_card_generated(cards[i]);
    }
}
void necrobinder_card_generated(BattleContext &b,const Card &c){
    if(c.id!=CardId::SOUL||b.necro.generatingSoulbound)return;
    const int n=b.player_power(PowerId::SOULBOUND);if(n<=0)return;
    b.necro.generatingSoulbound=true;necrobinder_create_souls(b,n);b.necro.generatingSoulbound=false;
}
void necrobinder_before_combat(BattleContext &b){
    if(relic_has(b,RelicId::BOUND_PHYLACTERY))necrobinder_summon(b,1);
    if(relic_has(b,RelicId::PHYLACTERY_UNBOUND))necrobinder_summon(b,5);
}
void necrobinder_player_turn_start(BattleContext &b){
    b.necro.ostyAttacksThisTurn=0;b.necro.extraDrawsThisTurn=0;b.necro.doomAppliedThisTurn=false;
    b.necro.finishedUidCount=0;b.necro.summonAtTurnStart=b.player_power(PowerId::SUMMON_NEXT_TURN);
}
void necrobinder_after_energy_reset(BattleContext &b){
    if(b.turn>1&&relic_has(b,RelicId::BOUND_PHYLACTERY))necrobinder_summon(b,1);
}
void necrobinder_after_side_turn_start(BattleContext &b){
    if(relic_has(b,RelicId::PHYLACTERY_UNBOUND))necrobinder_summon(b,2);
    const int countdown=b.player_power(PowerId::COUNTDOWN);
    if(countdown>0){const int i=b.random_alive_monster();if(i>=0)b.add_monster_power(i,PowerId::DOOM,countdown);}
    const int doom=b.player_power(PowerId::NEUROSURGE);if(doom>0)b.add_player_power(PowerId::DOOM,doom);
}
void necrobinder_before_hand_draw(BattleContext &b){
    if(b.turn==1&&relic_has(b,RelicId::FUNERARY_MASK))necrobinder_create_souls(b,3);
    for(int i=0,n=b.player_power(PowerId::SENTRY_MODE);i<n;++i){Card c=make_card(CardId::SWEEPING_GAZE,false,b.require_card_uid());b.add_card_to_hand(c);b.notify_card_generated(c);}
    for(int i=0,n=b.player_power(PowerId::CALL_OF_THE_VOID);i<n;++i){
        CardId candidates[static_cast<int>(CardId::COUNT)];int count=0;
        for(int j=1;j<static_cast<int>(CardId::COUNT);++j){const auto id=static_cast<CardId>(j);const auto &d=card_def(id);
            if(d.pool!=b.characterPool)continue;
            if(d.rarity==Rarity::BASIC||d.rarity==Rarity::ANCIENT||(d.flags&(CF_MULTIPLAYER_ONLY|CF_CANNOT_GENERATE_IN_COMBAT))||!card_native_available(id))continue;
            candidates[count++]=id;}
        std::sort(candidates,candidates+count,[](CardId a,CardId d){return card_def(a).nativePoolOrder<card_def(d).nativePoolOrder;});
        b.cardGenerationRng.shuffle(candidates,count);
        if(count){Card c=make_card(candidates[0],false,b.require_card_uid());c.etherealThisCombat=true;b.add_card_to_hand(c);b.notify_card_generated(c);}
    }
}
void necrobinder_after_player_turn_start(BattleContext &b){
    if(b.necro.summonAtTurnStart<=0)return;
    const int n=b.player_power(PowerId::SUMMON_NEXT_TURN);b.necro.summonAtTurnStart=0;
    necrobinder_summon(b,n);b.add_player_power(PowerId::SUMMON_NEXT_TURN,-n);
}
void necrobinder_doom_kill(BattleContext &b,bool playerSide){
    if(playerSide){if(b.player.hp>0&&b.player_power(PowerId::DOOM)>=b.player.hp)b.kill_player();return;}
    int targets[4],n=0;
    for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive&&b.monster_power(i,PowerId::DOOM)>=b.monsters[i].hp)targets[n++]=i;
    for(int j=0;j<n;++j)b.kill_monster(targets[j]);
    if(relic_has(b,RelicId::BOOK_REPAIR_KNIFE)){int fatal=0;for(int j=0;j<n;++j)if(b.can_trigger_fatal(targets[j]))++fatal;b.heal_hp(fatal*3);}
}
void necrobinder_player_turn_end(BattleContext &b){
    b.add_player_power(PowerId::BORROWED_TIME,-b.player_power(PowerId::BORROWED_TIME));
    for(int i=0;i<b.monsterCount;++i)b.add_monster_power(i,PowerId::OBLIVION,-b.monster_power(i,PowerId::OBLIVION));
    necrobinder_doom_kill(b,true);
    if(b.necro.ostyWeak>0)--b.necro.ostyWeak;if(b.necro.ostyVulnerable>0)--b.necro.ostyVulnerable;
}
void necrobinder_enemy_turn_end(BattleContext &b){
    necrobinder_doom_kill(b);
    for(int i=0;i<b.monsterCount;++i){if(b.monster_power(i,PowerId::DEBILITATE)>0)b.add_monster_power(i,PowerId::DEBILITATE,-1);
        b.add_monster_power(i,PowerId::SIC_EM,-b.monster_power(i,PowerId::SIC_EM));}
    b.add_player_power(PowerId::UNDERWORLD,-b.player_power(PowerId::UNDERWORLD));
}
void necrobinder_before_card_played(BattleContext &b,const Card &c){
    b.activePlay.necro={};
    for(int i=0;i<b.monsterCount;++i)b.activePlay.necro.oblivion[i]=b.monster_power(i,PowerId::OBLIVION);
    const int danse=b.player_power(PowerId::DANSE_MACABRE);
    if(danse>0&&necrobinder_resolved_cost(b,c,card_cost(c))>=2)b.gain_block(danse,false,false);
    if(card_has(c,CF_ETHEREAL)){
        const int spirit=b.player_power(PowerId::SPIRIT_OF_ASH);if(spirit>0)b.gain_block(spirit,false,false);
        if(b.player_power(PowerId::VEILPIERCER)>0)b.add_player_power(PowerId::VEILPIERCER,-1);
    }
}
void necrobinder_after_card_played(BattleContext &b,Card &c){
    for(int i=0;i<b.monsterCount;++i)if(b.activePlay.necro.oblivion[i]>0)b.add_monster_power(i,PowerId::DOOM,b.activePlay.necro.oblivion[i]);
    if(c.id==CardId::SOUL){
        necrobinder_summon(b,b.player_power(PowerId::DEVOUR_LIFE));
        const int haunt=b.player_power(PowerId::HAUNT);if(haunt>0){const int i=b.random_alive_monster();if(i>=0)b.damage_monster(i,haunt,false,false,true);}
    }
    if(card_has(c,CF_ETHEREAL)){
        ++b.necro.etherealPlayedThisCombat;
        each_card(b,[&](Card &card){if(card.id==CardId::BANSHEES_CRY)card_modify_cost(card,-2,false,0);});
    }
    bool found=false;for(int i=0;i<b.necro.finishedUidCount;++i)if(b.necro.finishedUidsThisTurn[i]==c.uid)found=true;
    if(!found){if(b.necro.finishedUidCount==160)throw std::overflow_error("Finished card identity capacity");b.necro.finishedUidsThisTurn[b.necro.finishedUidCount++]=c.uid;}
    if(b.activePlay.energySpent>=2){
        for(int i=0;i<b.discardCount;){if(b.discard[i].id!=CardId::RIGHT_HAND_HAND){++i;continue;}
            Card card=b.discard[i];for(int j=i+1;j<b.discardCount;++j)b.discard[j-1]=b.discard[j];--b.discardCount;b.add_card_to_hand(card);
            if(b.handCount==MAX_HAND)break;}
    }
}
void necrobinder_card_entered_combat(BattleContext &b,Card &c,bool isClone){
    if(isClone)return;
    if(c.id==CardId::BANSHEES_CRY)card_modify_cost(c,-2*b.necro.etherealPlayedThisCombat,false,0);
    if(c.id==CardId::FLATTEN&&b.necro.ostyAttacksThisTurn>0)card_modify_cost(c,0,true,2);
}
void necrobinder_card_drawn(BattleContext &b,const Card &c,bool fromHandDraw){
    if(!fromHandDraw)++b.necro.extraDrawsThisTurn;
    for(int i=0;i<b.necro.cacophonyCount;++i)if(--b.necro.cacophonyRemaining[i]<=0){
        b.necro.cacophonyRemaining[i]=33;const int target=b.random_alive_monster();
        if(target>=0)b.damage_monster(target,b.necro.cacophonyDamage[i],true,false);}
    if(card_has(c,CF_ETHEREAL)&&b.player_power(PowerId::PAGESTORM)>0)b.draw_cards(b.player_power(PowerId::PAGESTORM));
}
void necrobinder_after_death(BattleContext &b,bool removalPrevented){
    if(removalPrevented)return;++b.necro.deathsThisCombat;
    each_card(b,[&](Card &c){if(c.id==CardId::MELANCHOLY)card_modify_cost(c,-1,false,0);});
}
void necrobinder_after_power_changed(BattleContext &b,int target,PowerId power,int delta,bool playerApplied){
    if(!playerApplied||!delta)return;
    if(power==PowerId::DOOM){b.necro.doomAppliedThisTurn=true;const int n=b.player_power(PowerId::SHROUD);if(n>0)b.gain_block(n,false,false);}
    if(target>=0&&!temporary_power(power)&&debuff_delta(power,delta)){
        const int n=b.player_power(PowerId::SLEIGHT_OF_FLESH);if(n>0)b.damage_monster(target,n,true,false);}
}
void necrobinder_after_damage_given(BattleContext &b,int target,const DamageDealt &result,bool powered){
    if(b.activePlay.active&&powered)b.activePlay.necro.damageTotal+=result.total;
    if(powered&&result.total>0&&b.player_power(PowerId::REAPER_FORM)>0)b.add_monster_power(target,PowerId::DOOM,result.total*b.player_power(PowerId::REAPER_FORM));
    if(b.necro.dealingOstyDamage)necrobinder_summon(b,b.monster_power(target,PowerId::SIC_EM));
}
int necrobinder_resolved_cost(const BattleContext &b,const Card &c,int cost){
    if(cost<0)return cost;
    cost+=b.player_power(PowerId::BORROWED_TIME);
    if(card_has(c,CF_ETHEREAL)&&b.player_power(PowerId::VEILPIERCER)>0)cost=0;
    return std::max(0,cost);
}
double necrobinder_damage_multiplier(const BattleContext &b,const Card *card,int target,bool powered){
    if(!powered||!card)return 1.0;
    double multiplier=1.0;
    if(b.player_power(PowerId::LETHALITY)>0&&b.attacksPlayedThisTurn<=1&&(!b.activePlay.active||b.activePlay.nextPlay<=1))multiplier*=1.0+b.player_power(PowerId::LETHALITY)/100.0;
    if(card->id==CardId::HANG)multiplier*=std::max(1,b.monster_power(target,PowerId::HANG));
    if(!b.necro.dealingOstyDamage&&target>=0&&target<b.monsterCount&&b.monsters[target].vulnerable>0&&b.monster_power(target,PowerId::DEBILITATE)>0){
        const double vuln=(relic_has(b,RelicId::PAPER_PHROG)?1.75:1.5)+b.player_power(PowerId::CRUELTY)/100.0;
        multiplier*=(1.0+2.0*(vuln-1.0))/vuln;
    }
    return multiplier;
}
double necrobinder_monster_damage_multiplier(const BattleContext &b,int target){
    if(target<0||target>=b.monsterCount)return 1.0;double multiplier=1.0;
    if(b.monsters[target].weak>0&&b.monster_power(target,PowerId::DEBILITATE)>0)multiplier*=2.0/3.0;
    if(relic_has(b,RelicId::UNDYING_SIGIL)&&b.monsters[target].hp<=b.monster_power(target,PowerId::DOOM))multiplier*=0.5;
    return multiplier;
}
int necrobinder_extra_energy(const BattleContext &b){return b.player_power(PowerId::DEMESNE)+b.player_power(PowerId::FRIENDSHIP);}
int necrobinder_extra_draw(const BattleContext &b){return b.player_power(PowerId::DEMESNE);}
bool necrobinder_card_playable(const BattleContext &b,const Card &c){return c.id!=CardId::HIGH_FIVE||b.necro.ostyHp>0;}
bool necrobinder_resolve_choice(BattleContext &b,const Card &chosen){
    Card *card=nullptr;switch(b.pending.op){
    case ChoiceOp::NECRO_SCULPT_ETHEREAL:card=b.find_in_hand(chosen.uid);if(card)card->etherealThisCombat=true;return true;
    case ChoiceOp::NECRO_SNAP_RETAIN:card=b.find_in_hand(chosen.uid);if(card)card->retainThisCombat=true;return true;
    case ChoiceOp::NECRO_TRANSFIGURE:card=b.find_in_hand(chosen.uid);if(card){
        if(card_def(card->id).cost>=0)card_modify_cost(*card,1,false,0);
        if(card->bonusReplay==255)throw std::overflow_error("Transfigure replay capacity");++card->bonusReplay;}return true;
    case ChoiceOp::NECRO_SEANCE:
        card=b.find_in_draw(chosen.uid);if(card)*card=make_card(CardId::SOUL,false,b.require_card_uid());return true;
    default:return false;
    }
}
}
