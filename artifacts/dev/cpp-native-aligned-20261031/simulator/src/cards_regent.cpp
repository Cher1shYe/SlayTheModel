#include "sts2/regent.h"
#include "sts2/card_candidates.h"
namespace sts2 {
namespace {
void choose(BattleContext &b,Card &c,ChoiceOp op,ChoicePile pile,int n,bool optional=false) {
    b.start_choice(op,pile,n,c,false,optional);
    auto &p=b.pending;
    for(int i=0;i<p.count;) {
        const Card &candidate=p.cards[i];
        const auto pool=card_def(candidate.id).pool;
        bool allowed=op!=ChoiceOp::REGENT_AUTO_SKILL || (card_is_skill(candidate)&&card_is_playable(candidate));
        if(op==ChoiceOp::REGENT_CLONE)
            allowed=pool==CardPool::COLORLESS || pool==CardPool::EVENT || pool==CardPool::TOKEN;
        if(allowed)++i;else {for(int j=i+1;j<p.count;++j)p.cards[j-1]=p.cards[j];--p.count;}
    }
    p.remaining=std::min(p.remaining,p.count);
    if(!p.count) b.maybe_finish_pending();
}
void draw_then(BattleContext &b,Card &c,int stage) {
    b.activePlay.regent.stage=stage;
    b.draw_cards(card_var(c,VarId::CARDS));
    if(b.pending.op==ChoiceOp::NONE)regent_resume_effect(b);
}
int star_cards(const BattleContext &b) {
    int count=0;
    const Card *piles[]={b.hand,b.draw,b.discard,b.exhaust,b.playPile,b.returnNextTurn};
    const int sizes[]={b.handCount,b.drawCount,b.discardCount,b.exhaustCount,b.playCount,b.returnNextTurnCount};
    auto isStar=[](const Card &c){const auto &d=card_def(c.id);return d.starCost>=0 || d.starCostX;};
    for(int p=0;p<6;++p)for(int i=0;i<sizes[p];++i)count+=isStar(piles[p][i]);
    if(b.activePlay.active)count+=isStar(b.activePlay.card);
    for(int i=0;i<b.suspendedPlayCount;++i)count+=isStar(b.suspendedPlays[i].play.card);
    return count;
}
void temp_strength(BattleContext &b,int target,PowerId wrapper,int amount) {
    const int before=b.monster_power(target,wrapper);
    b.add_monster_power(target,wrapper,amount);
    const int accepted=b.monster_power(target,wrapper)-before;
    if(accepted)b.add_monster_power(target,PowerId::STRENGTH,-accepted);
}
}

bool regent_effect(BattleContext &b,Card &c,int target) {
    const auto v=[&](VarId id){return card_var(c,id);};
    const double damage=card_base_damage(c);
    switch(c.id) {
    case CardId::ALIGNMENT:b.player.energy+=v(VarId::ENERGY);break;
    case CardId::ARSENAL:b.add_player_power(PowerId::ARSENAL,v(VarId::ARSENAL_POWER));break;
    case CardId::ASTRAL_PULSE:b.attack_all_from_card(c,damage,2);break;
    case CardId::BEAT_INTO_SHAPE: {
        const int previous=target>=0&&target<b.monsterCount?b.regent.hitsGivenThisTurn[target]:0;
        b.attack_from_card(c,target,damage);
        regent_forge(b,v(VarId::CALCULATION_BASE)+v(VarId::CALCULATION_EXTRA)*previous);break;
    }
    case CardId::BEGONE:choose(b,c,ChoiceOp::REGENT_TRANSFORM,ChoicePile::HAND,1);break;
    case CardId::BIG_BANG:draw_then(b,c,1);break;
    case CardId::BLACK_HOLE:b.add_player_power(PowerId::BLACK_HOLE,v(VarId::BLACK_HOLE_POWER));break;
    case CardId::BOMBARDMENT:case CardId::DEVASTATE:case CardId::KINGLY_KICK:case CardId::KINGLY_PUNCH:
    case CardId::MAKE_IT_SO:case CardId::STRIKE_REGENT:case CardId::MINION_DIVE_BOMB:
        b.attack_from_card(c,target,damage);break;
    case CardId::BULWARK:b.gain_block(card_block(c),true);regent_forge(b,v(VarId::FORGE));break;
    case CardId::BUNDLE_OF_JOY:regent_generate_colorless(b,v(VarId::CARDS));break;
    case CardId::CELESTIAL_MIGHT:b.attack_from_card(c,target,damage,v(VarId::REPEAT));break;
    case CardId::CHARGE:choose(b,c,ChoiceOp::REGENT_TRANSFORM,ChoicePile::DRAW,v(VarId::CARDS));break;
    case CardId::CHILD_OF_THE_STARS:b.add_player_power(PowerId::CHILD_OF_THE_STARS,v(VarId::BLOCK_FOR_STARS));break;
    case CardId::CLOAK_OF_STARS:case CardId::DEFEND_REGENT:case CardId::I_AM_INVINCIBLE:
    case CardId::PARTICLE_WALL:case CardId::MINION_SACRIFICE:b.gain_block(card_block(c),true);break;
    case CardId::COLLISION_COURSE:case CardId::CRASH_LANDING: {
        if(c.id==CardId::CRASH_LANDING)b.attack_all_from_card(c,damage);else b.attack_from_card(c,target,damage);
        const int count=c.id==CardId::CRASH_LANDING?MAX_HAND-b.handCount:1;
        for(int i=0;i<count;++i){Card debris=make_card(CardId::DEBRIS,false,b.require_card_uid());b.add_card_to_hand(debris);b.notify_card_generated(debris);}break;
    }
    case CardId::COMET:case CardId::FALLING_STAR:case CardId::GAMMA_BLAST:case CardId::KNOW_THY_PLACE:
        if(c.id!=CardId::KNOW_THY_PLACE)b.attack_from_card(c,target,damage);
        b.apply_weak(target,v(VarId::WEAK_POWER));b.apply_vulnerable(target,v(VarId::VULNERABLE_POWER));break;
    case CardId::CONQUEROR:regent_forge(b,v(VarId::FORGE));b.add_monster_power(target,PowerId::CONQUEROR,1);break;
    case CardId::CONSTELLATION:draw_then(b,c,5);break;
    case CardId::CONVERGENCE:
        b.add_player_power(PowerId::RETAIN_HAND,1);b.add_player_power(PowerId::ENERGY_NEXT_TURN,v(VarId::ENERGY));
        b.add_player_power(PowerId::STAR_NEXT_TURN,v(VarId::STARS));break;
    case CardId::COSMIC_INDIFFERENCE:
        b.gain_block(card_block(c),true);choose(b,c,ChoiceOp::RETURN_DISCARD_TOP,ChoicePile::DISCARD,1);break;
    case CardId::CRESCENT_SPEAR:
        b.attack_from_card(c,target,v(VarId::CALCULATION_BASE)+v(VarId::EXTRA_DAMAGE)*star_cards(b)+c.bonusDamage);break;
    case CardId::CRUSH_UNDER:case CardId::DYING_STAR:
        b.attack_all_from_card(c,damage);
        for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive)
            temp_strength(b,i,c.id==CardId::CRUSH_UNDER?PowerId::CRUSH_UNDER:PowerId::DYING_STAR,v(VarId::STRENGTH_LOSS));break;
    case CardId::DECISIONS_DECISIONS:draw_then(b,c,4);break;
    case CardId::FOREGONE_CONCLUSION:b.add_player_power(PowerId::FOREGONE_CONCLUSION,v(VarId::CARDS));break;
    case CardId::FURNACE:b.add_player_power(PowerId::FURNACE,v(VarId::FORGE));break;
    case CardId::GATHER_LIGHT:b.gain_block(card_block(c),true);regent_gain_stars(b,v(VarId::STARS));break;
    case CardId::GENESIS:b.add_player_power(PowerId::GENESIS,v(VarId::STARS_PER_TURN));break;
    case CardId::GLIMMER:draw_then(b,c,3);break;
    case CardId::GLITTERSTREAM: {
        // BlockNextTurn captures today's powered block modifiers.
        int next=v(VarId::BLOCK_NEXT_TURN)+b.player.dexterity;
        if(b.player.frail>0)next=static_cast<int>(std::floor(next*0.75));
        b.gain_block(card_block(c),true);b.add_player_power(PowerId::BLOCK_NEXT_TURN,std::max(0,next));break;
    }
    case CardId::GLOW:regent_gain_stars(b,v(VarId::STARS));draw_then(b,c,2);break;
    case CardId::GUARDS:choose(b,c,ChoiceOp::REGENT_TRANSFORM,ChoicePile::HAND,MAX_HAND,true);break;
    case CardId::GUIDING_STAR:
        b.attack_from_card(c,target,damage);b.add_player_power(PowerId::DRAW_CARDS_NEXT_TURN,v(VarId::CARDS));break;
    case CardId::HAMMER_TIME:b.add_player_power(PowerId::HAMMER_TIME,1);break;
    case CardId::HEAVENLY_DRILL:b.attack_from_card(c,target,damage,b.xCost*(b.xCost>=v(VarId::ENERGY)?2:1));break;
    case CardId::HEGEMONY:b.attack_from_card(c,target,damage);b.add_player_power(PowerId::ENERGY_NEXT_TURN,v(VarId::ENERGY));break;
    case CardId::HEIRLOOM_HAMMER:b.attack_from_card(c,target,damage);choose(b,c,ChoiceOp::REGENT_CLONE,ChoicePile::HAND,1);break;
    case CardId::HIDDEN_CACHE:regent_gain_stars(b,v(VarId::STARS));b.add_player_power(PowerId::STAR_NEXT_TURN,v(VarId::STAR_NEXT_TURN_POWER));break;
    case CardId::KNOCKOUT_BLOW:if(b.attack_from_card(c,target,damage))regent_gain_stars(b,v(VarId::STARS));break;
    case CardId::LARGESSE:regent_generate_colorless(b,1,c.upgraded);break;
    case CardId::LUNAR_BLAST:b.attack_from_card(c,target,damage,b.regent.skillsFinishedThisTurn);break;
    case CardId::MANIFEST_AUTHORITY:b.gain_block(card_block(c),true);regent_generate_colorless(b,1,c.upgraded);break;
    case CardId::METEOR_SHOWER:
        b.attack_all_from_card(c,damage);for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive){b.apply_weak(i,v(VarId::WEAK_POWER));b.apply_vulnerable(i,v(VarId::VULNERABLE_POWER));}break;
    case CardId::MONARCHS_GAZE:b.add_player_power(PowerId::MONARCHS_GAZE,v(VarId::STRENGTH_LOSS));break;
    case CardId::MONOLOGUE: {
        auto &r=b.regent;if(r.monologueCount==MAX_PILE)throw std::overflow_error("Monologue instances exhausted");
        r.monologueAmounts[r.monologueCount++]=v(VarId::POWER);b.add_player_power(PowerId::MONOLOGUE,1);break;
    }
    case CardId::NEUTRON_AEGIS:b.add_player_power(PowerId::PLATING,v(VarId::PLATING_POWER));break;
    case CardId::ORBIT: {
        auto &r=b.regent;if(r.orbitCount==MAX_PILE)throw std::overflow_error("Orbit instances exhausted");
        r.orbitAmounts[r.orbitCount++]=v(VarId::ENERGY);b.add_player_power(PowerId::ORBIT,v(VarId::ENERGY));break;
    }
    case CardId::PALE_BLUE_DOT:b.add_player_power(PowerId::PALE_BLUE_DOT,v(VarId::CARDS));break;
    case CardId::PARRY:b.add_player_power(PowerId::PARRY,v(VarId::PARRY_POWER));break;
    case CardId::PATTER:b.gain_block(card_block(c),true);b.add_player_power(PowerId::VIGOR,v(VarId::VIGOR_POWER));break;
    case CardId::PHOTON_CUT:b.attack_from_card(c,target,damage);draw_then(b,c,3);break;
    case CardId::PILLAR_OF_CREATION:b.add_player_power(PowerId::PILLAR_OF_CREATION,v(VarId::BLOCK));break;
    case CardId::PLOT:break; // Multiplayer-only: no other players in this simulator.
    case CardId::PROPHESIZE:b.draw_cards(v(VarId::CARDS));break;
    case CardId::QUASAR: {
        Card offers[3];CardId pool[static_cast<int>(CardId::COUNT)];int n=0;
        for(int i=1;i<static_cast<int>(CardId::COUNT);++i){const auto id=static_cast<CardId>(i);const auto &d=card_def(id);
            if(d.pool==CardPool::COLORLESS && card_native_available(id) && !(d.flags&(CF_MULTIPLAYER_ONLY|CF_CANNOT_GENERATE_IN_COMBAT)))pool[n++]=id;}
        native_sort_card_ids(pool,n);
        for(int i=0;i<3;++i){int k=b.cardGenerationRng.next_int(0,n-1);offers[i]=make_card(pool[k],c.upgraded,b.require_card_uid());for(int j=k+1;j<n;++j)pool[j-1]=pool[j];--n;}
        b.start_offer(ChoiceOp::OFFER_TO_HAND,offers,3,c,false,false);b.pending.optional=true;break;
    }
    case CardId::RADIATE:b.attack_all_from_card(c,damage,b.regent.starsGainedThisTurn);break;
    case CardId::REFINE_BLADE:regent_forge(b,v(VarId::FORGE));b.add_player_power(PowerId::ENERGY_NEXT_TURN,v(VarId::ENERGY));break;
    case CardId::REFLECT:b.gain_block(card_block(c),true);b.add_player_power(PowerId::REFLECT,1);break;
    case CardId::RESONANCE:
        b.add_player_power(PowerId::STRENGTH,v(VarId::STRENGTH_POWER));for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive)b.add_monster_power(i,PowerId::STRENGTH,-1);break;
    case CardId::ROYAL_GAMBLE:case CardId::VENERATE:regent_gain_stars(b,v(VarId::STARS));break;
    case CardId::ROYALTIES:b.add_player_power(PowerId::ROYALTIES,v(VarId::GOLD));break;
    case CardId::SEEKING_EDGE:b.add_player_power(PowerId::SEEKING_EDGE,1);regent_forge(b,v(VarId::FORGE));break;
    case CardId::SEVEN_STARS:b.attack_all_from_card(c,damage,v(VarId::REPEAT));break;
    case CardId::SHINING_STRIKE:case CardId::SOLAR_STRIKE:b.attack_from_card(c,target,damage);regent_gain_stars(b,v(VarId::STARS));break;
    case CardId::SPECTRUM_SHIFT:b.add_player_power(PowerId::SPECTRUM_SHIFT,v(VarId::CARDS));break;
    case CardId::SPOILS_OF_BATTLE:regent_forge(b,v(VarId::FORGE));b.draw_cards(v(VarId::CARDS));break;
    case CardId::STARDUST:b.attack_random_from_card(c,damage,b.activePlay.starX);break;
    case CardId::SUMMON_FORTH: {
        Card *piles[]={b.draw,b.discard,b.exhaust,b.playPile};int *counts[]={&b.drawCount,&b.discardCount,&b.exhaustCount,&b.playCount};
        Card blades[MAX_PILE];int n=0;for(int p=0;p<4;++p)for(int i=0;i<*counts[p];++i)if(piles[p][i].id==CardId::SOVEREIGN_BLADE)blades[n++]=piles[p][i];
        for(int i=0;i<n;++i){b.detach_card(blades[i].uid);b.add_card_to_hand(blades[i]);}regent_forge(b,v(VarId::FORGE));break;
    }
    case CardId::SUPERMASSIVE:b.attack_from_card(c,target,v(VarId::CALCULATION_BASE)+v(VarId::EXTRA_DAMAGE)*b.regent.generatedThisCombat+c.bonusDamage);break;
    case CardId::SWORD_SAGE:b.add_player_power(PowerId::SWORD_SAGE,v(VarId::SWORD_SAGE_POWER));break;
    case CardId::TERRAFORMING:b.add_player_power(PowerId::VIGOR,v(VarId::VIGOR_POWER));break;
    case CardId::THE_SEALED_THRONE:b.add_player_power(PowerId::THE_SEALED_THRONE,1);break;
    case CardId::THE_SMITH:regent_forge(b,v(VarId::FORGE));break;
    case CardId::TUTOR:choose(b,c,ChoiceOp::DRAW_TO_HAND,ChoicePile::DRAW,1);break;
    case CardId::TYRANNY:b.add_player_power(PowerId::TYRANNY,1);break;
    case CardId::VOID_FORM:b.add_player_power(PowerId::VOID_FORM,v(VarId::VOID_FORM_POWER));b.regent.voidFormManualPlays=999999999;b.regent.endTurnRequested=true;break;
    case CardId::WROUGHT_IN_WAR:b.attack_from_card(c,target,damage);regent_forge(b,v(VarId::FORGE));break;
    case CardId::MINION_STRIKE:b.attack_from_card(c,target,damage);b.draw_cards(v(VarId::CARDS));break;
    case CardId::SOVEREIGN_BLADE:
        if(b.player_power(PowerId::SEEKING_EDGE)>0)b.attack_all_from_card(c,damage);else b.attack_from_card(c,target,damage);
        if(b.player_power(PowerId::PARRY)>0)b.gain_block(b.player_power(PowerId::PARRY),true);break;
    default:return false;
    }
    return true;
}

bool regent_resume_effect(BattleContext &b) {
    auto &r=b.activePlay.regent;
    if(r.stage==0)return true;
    if(b.pending.op!=ChoiceOp::NONE || b.pendingDrawRemainder>0)return false;
    Card &c=b.activePlay.card;const int stage=r.stage;r.stage=0;
    if(stage==1){regent_gain_stars(b,card_var(c,VarId::STARS));b.player.energy+=card_var(c,VarId::ENERGY);regent_forge(b,card_var(c,VarId::FORGE));}
    if(stage==2)b.add_player_power(PowerId::DRAW_CARDS_NEXT_TURN,card_var(c,VarId::CARDS));
    if(stage==3)choose(b,c,ChoiceOp::PUT_HAND_TOP,ChoicePile::HAND,card_var(c,VarId::PUT_BACK));
    if(stage==4)choose(b,c,ChoiceOp::REGENT_AUTO_SKILL,ChoicePile::HAND,1);
    if(stage==5){b.player.energy+=card_var(c,VarId::ENERGY);b.gain_block(card_block(c),true);}
    return b.pending.op==ChoiceOp::NONE;
}

bool regent_resolve_choice(BattleContext &b,std::uint16_t uid) {
    const auto op=b.pending.op;
    if(op!=ChoiceOp::REGENT_TRANSFORM && op!=ChoiceOp::REGENT_CLONE && op!=ChoiceOp::REGENT_AUTO_SKILL)return false;
    auto &r=b.activePlay.regent;
    for(int i=0;i<b.pending.count;++i)if(b.pending.cards[i].uid==uid){
        if(r.selectedCount==MAX_HAND)throw std::overflow_error("Regent selection capacity exhausted");
        r.selected[r.selectedCount++]=uid;
        for(int j=i+1;j<b.pending.count;++j)b.pending.cards[j-1]=b.pending.cards[j];
        --b.pending.count;--b.pending.remaining;b.maybe_finish_pending();return true;
    }
    return false;
}

void regent_finish_choice(BattleContext &b,ChoiceOp op) {
    if(op!=ChoiceOp::REGENT_TRANSFORM && op!=ChoiceOp::REGENT_CLONE && op!=ChoiceOp::REGENT_AUTO_SKILL)return;
    Card &source=b.activePlay.card;auto &r=b.activePlay.regent;
    for(int i=0;i<r.selectedCount;++i){
        Card *selected=b.find_in_hand(r.selected[i]);if(!selected)selected=b.find_in_draw(r.selected[i]);
        if(!selected)continue;
        if(op==ChoiceOp::REGENT_TRANSFORM){
            const CardId id=source.id==CardId::CHARGE?CardId::MINION_DIVE_BOMB:source.id==CardId::GUARDS?CardId::MINION_SACRIFICE:CardId::MINION_STRIKE;
            *selected=make_card(id,source.upgraded,b.require_card_uid());b.notify_card_generated(*selected);
        }else if(op==ChoiceOp::REGENT_CLONE){
            Card original=*selected;
            for(int n=0;n<card_var(source,VarId::REPEAT);++n){Card copy=original;copy.uid=b.require_card_uid();b.add_card_to_hand(copy);b.notify_card_generated(copy);}
        }else{
            Card copies[MAX_HAND];const int count=card_var(source,VarId::REPEAT);
            if(count>MAX_HAND)throw std::overflow_error("Regent autoplay repeat capacity exhausted");
            for(int n=0;n<count;++n)copies[n]=*selected;b.auto_play_cards(copies,count);
        }
    }
    r.selectedCount=0;
}
}
