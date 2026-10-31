#include "sts2/necrobinder.h"
#include "sts2/relics.h"
#include <algorithm>
#include <stdexcept>

namespace sts2 {
namespace {
int v(const Card &c, VarId id) { return card_var(c,id); }
void doom_all(BattleContext &b,int amount) {
    for (int i=0;i<b.monsterCount;++i) if(b.monsters[i].alive) b.add_monster_power(i,PowerId::DOOM,amount);
}
void choose(BattleContext &b,Card &c,ChoiceOp op,ChoicePile pile,int count=1) {
    b.start_choice(op,pile,count,false,c,b.card_will_exhaust(c));
    if(op==ChoiceOp::NECRO_SCULPT_ETHEREAL || op==ChoiceOp::NECRO_SNAP_RETAIN) {
        int n=0;
        for(int i=0;i<b.pending.count;++i) {
            const Card &candidate=b.pending.cards[i];
            if(op==ChoiceOp::NECRO_SCULPT_ETHEREAL && card_has(candidate,CF_ETHEREAL)) continue;
            if(op==ChoiceOp::NECRO_SNAP_RETAIN && card_has(candidate,CF_RETAIN)) continue;
            b.pending.cards[n++]=candidate;
        }
        b.pending.count=n;
        if(!n) b.pending=PendingChoice{};
    }
}
bool was_finished(const BattleContext &b,std::uint16_t uid) {
    for(int i=0;i<b.necro.finishedUidCount;++i) if(b.necro.finishedUidsThisTurn[i]==uid)return true;
    return false;
}
void misery(BattleContext &b,Card &card,int target);
}

bool necrobinder_effect(BattleContext &b,Card &c,int target) {
    const double damage=card_base_damage(c);
    switch(c.id) {
    case CardId::AFTERLIFE: case CardId::BODYGUARD: case CardId::LEGION_OF_BONE:
    case CardId::REANIMATE:
        necrobinder_summon(b,v(c,VarId::SUMMON)); return true;
    case CardId::BANSHEES_CRY: case CardId::SOW:
        b.attack_from_card(c,target,damage,1,true); return true;
    case CardId::BURY: case CardId::DEFILE: case CardId::REAP: case CardId::STRIKE_NECROBINDER:
        b.attack_from_card(c,target,damage); return true;
    case CardId::BLIGHT_STRIKE: {
        const int before=b.activePlay.necro.damageTotal;
        b.attack_from_card(c,target,damage);
        b.add_monster_power(target,PowerId::DOOM,b.activePlay.necro.damageTotal-before); return true;
    }
    case CardId::BONE_SHARDS:
        if(b.necro.ostyHp>0) {
            necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE),1,true);
            b.gain_block(card_block(c),true);
            necrobinder_kill_osty(b);
        } return true;
    case CardId::BORROWED_TIME:
        b.player.energy+=v(c,VarId::ENERGY);
        b.add_player_power(PowerId::BORROWED_TIME,v(c,VarId::EXTRA_COST)); return true;
    case CardId::CACOPHONY: {
        if(b.necro.cacophonyCount==160)throw std::overflow_error("Cacophony instance capacity");
        const int i=b.necro.cacophonyCount++;
        b.necro.cacophonyDamage[i]=v(c,VarId::DAMAGE);
        b.necro.cacophonyRemaining[i]=v(c,VarId::CARDS);
        b.add_player_power(PowerId::CACOPHONY,v(c,VarId::DAMAGE)); return true;
    }
    case CardId::CALCIFY: b.add_player_power(PowerId::CALCIFY,v(c,VarId::CALCIFY_POWER)); return true;
    case CardId::CALL_OF_THE_VOID: b.add_player_power(PowerId::CALL_OF_THE_VOID,v(c,VarId::CARDS)); return true;
    case CardId::CAPTURE_SPIRIT:
        b.damage_monster(target,v(c,VarId::DAMAGE),true,false,true);
        necrobinder_create_souls(b,v(c,VarId::CARDS)); return true;
    case CardId::CLEANSE:
        necrobinder_summon(b,v(c,VarId::SUMMON)); choose(b,c,ChoiceOp::EXHAUST,ChoicePile::DRAW); return true;
    case CardId::COUNTDOWN: b.add_player_power(PowerId::COUNTDOWN,v(c,VarId::COUNTDOWN_POWER)); return true;
    case CardId::DANSE_MACABRE: b.add_player_power(PowerId::DANSE_MACABRE,v(c,VarId::DANSE_MACABRE_POWER)); return true;
    case CardId::DEATH_MARCH:
        b.attack_from_card(c,target,v(c,VarId::CALCULATION_BASE)+v(c,VarId::EXTRA_DAMAGE)*b.necro.extraDrawsThisTurn+c.bonusDamage); return true;
    case CardId::DEATHBRINGER:
        doom_all(b,v(c,VarId::DOOM_POWER));
        for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive)b.apply_weak(i,v(c,VarId::WEAK_POWER)); return true;
    case CardId::DEATHS_DOOR:
        for(int i=0,n=1+(b.necro.doomAppliedThisTurn?v(c,VarId::REPEAT):0);i<n;++i)b.gain_block(card_block(c),true); return true;
    case CardId::DEBILITATE:
        b.attack_from_card(c,target,damage); b.add_monster_power(target,PowerId::DEBILITATE,v(c,VarId::DEBILITATE_POWER)); return true;
    case CardId::DEFEND_NECROBINDER: b.gain_block(card_block(c),true);return true;
    case CardId::DEFY:
        b.gain_block(card_block(c),true);b.apply_weak(target,v(c,VarId::WEAK_POWER));return true;
    case CardId::DELAY:
        b.gain_block(card_block(c),true);b.nextTurnEnergy+=v(c,VarId::ENERGY);return true;
    case CardId::DEMESNE: b.add_player_power(PowerId::DEMESNE,1);return true;
    case CardId::DEVOUR_LIFE:b.add_player_power(PowerId::DEVOUR_LIFE,v(c,VarId::DEVOUR_LIFE_POWER));return true;
    case CardId::DIRGE:
        for(int i=0;i<b.xCost;++i)necrobinder_summon(b,v(c,VarId::SUMMON));
        necrobinder_create_souls(b,b.xCost,ChoicePile::DRAW,c.upgraded);return true;
    case CardId::DRAIN_POWER: {
        b.attack_from_card(c,target,damage);
        int indices[MAX_PILE],n=0;
        for(int i=0;i<b.discardCount;++i)if(card_upgradable(b.discard[i]))indices[n++]=i;
        b.cardSelectionRng.shuffle(indices,n);
        for(int i=0;i<std::min(n,v(c,VarId::CARDS));++i)b.upgrade_card(b.discard[indices[i]]);
        return true;
    }
    case CardId::DREDGE:
        choose(b,c,ChoiceOp::DISCARD_TO_HAND,ChoicePile::DISCARD,std::min(v(c,VarId::CARDS),MAX_HAND-b.handCount)); return true;
    case CardId::EIDOLON: {
        Card cards[MAX_PILE];int n=0;
        for(int i=0;i<b.exhaustCount;++i)if(card_has(b.exhaust[i],CF_ETHEREAL)&&!card_has(b.exhaust[i],CF_UNPLAYABLE))cards[n++]=b.exhaust[i];
        b.auto_play_cards(cards,n); return true;
    }
    case CardId::END_OF_DAYS:
        doom_all(b,v(c,VarId::DOOM_POWER));necrobinder_doom_kill(b);return true;
    case CardId::ENFEEBLING_TOUCH:
        b.apply_strength_loss(target,v(c,VarId::STRENGTH_LOSS));return true;
    case CardId::ERADICATE:b.attack_from_card(c,target,damage,b.xCost);return true;
    case CardId::FEAR:
        b.attack_from_card(c,target,damage);b.apply_vulnerable(target,v(c,VarId::VULNERABLE_POWER));return true;
    case CardId::FETCH:
        if(b.necro.ostyHp>0){necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE));if(!was_finished(b,c.uid))b.draw_cards(v(c,VarId::CARDS));}return true;
    case CardId::FLATTEN:case CardId::POKE:case CardId::RIGHT_HAND_HAND:
        necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE));return true;
    case CardId::FORBIDDEN_GRIMOIRE:b.add_player_power(PowerId::FORBIDDEN_GRIMOIRE,1);return true;
    case CardId::FRIENDSHIP:
        b.add_player_power(PowerId::STRENGTH,-v(c,VarId::STRENGTH_POWER));b.add_player_power(PowerId::FRIENDSHIP,v(c,VarId::ENERGY));return true;
    case CardId::GLIMPSE_BEYOND:necrobinder_create_souls(b,v(c,VarId::CARDS));return true;
    case CardId::GRAVE_WARDEN:
        b.gain_block(card_block(c),true);necrobinder_create_souls(b,v(c,VarId::CARDS));return true;
    case CardId::GRAVEBLAST:
        b.attack_from_card(c,target,damage);choose(b,c,ChoiceOp::DISCARD_TO_HAND,ChoicePile::DISCARD);return true;
    case CardId::HANG: {
        b.attack_from_card(c,target,damage);
        b.add_monster_power(target,PowerId::HANG,std::max(2,b.monster_power(target,PowerId::HANG)));return true;
    }
    case CardId::HAUNT:b.add_player_power(PowerId::HAUNT,v(c,VarId::HP_LOSS));return true;
    case CardId::HIGH_FIVE:
        if(b.necro.ostyHp>0){necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE),1,true);
        for(int i=0;i<b.monsterCount;++i)if(b.monsters[i].alive)b.apply_vulnerable(i,v(c,VarId::VULNERABLE_POWER));}return true;
    case CardId::INVOKE:
        b.add_player_power(PowerId::SUMMON_NEXT_TURN,v(c,VarId::SUMMON));b.nextTurnEnergy+=v(c,VarId::ENERGY);return true;
    case CardId::LETHALITY:b.add_player_power(PowerId::LETHALITY,v(c,VarId::LETHALITY_POWER));return true;
    case CardId::MELANCHOLY:b.gain_block(card_block(c),true);return true;
    case CardId::MISERY:misery(b,c,target);return true;
    case CardId::NECRO_MASTERY:
        necrobinder_summon(b,v(c,VarId::SUMMON));b.add_player_power(PowerId::NECRO_MASTERY,1);return true;
    case CardId::NEGATIVE_PULSE:
        b.gain_block(card_block(c),true);doom_all(b,v(c,VarId::DOOM_POWER));return true;
    case CardId::NEUROSURGE:
        b.player.energy+=v(c,VarId::ENERGY);b.activePlay.necro.stage=1;
        b.draw_cards(v(c,VarId::CARDS));
        if(b.pending.op==ChoiceOp::NONE)necrobinder_resume_effect(b);return true;
    case CardId::NO_ESCAPE:
        b.add_monster_power(target,PowerId::DOOM,v(c,VarId::CALCULATION_BASE)+v(c,VarId::CALCULATION_EXTRA)*(b.monster_power(target,PowerId::DOOM)/std::max(1,v(c,VarId::DOOM_THRESHOLD))));return true;
    case CardId::OBLIVION:b.add_monster_power(target,PowerId::OBLIVION,v(c,VarId::DOOM_POWER));return true;
    case CardId::PAGESTORM:b.add_player_power(PowerId::PAGESTORM,v(c,VarId::CARDS));return true;
    case CardId::PARSE:case CardId::SOUL:b.draw_cards(v(c,VarId::CARDS));return true;
    case CardId::PROTECTOR:
        necrobinder_attack_osty(b,c,target,v(c,VarId::CALCULATION_BASE)+b.necro.ostyMaxHp+c.bonusDamage);return true;
    case CardId::PULL_AGGRO:
        necrobinder_summon(b,v(c,VarId::SUMMON));b.gain_block(card_block(c),true);return true;
    case CardId::PULL_FROM_BELOW:
        b.attack_from_card(c,target,damage,b.necro.etherealPlayedThisCombat);return true;
    case CardId::PUTREFY:
        b.apply_weak(target,v(c,VarId::POWER));b.apply_vulnerable(target,v(c,VarId::POWER));return true;
    case CardId::RATTLE:
        necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE),1+b.necro.ostyAttacksThisTurn);return true;
    case CardId::REAPER_FORM:b.add_player_power(PowerId::REAPER_FORM,1);return true;
    case CardId::REAVE:
        b.attack_from_card(c,target,damage);necrobinder_create_souls(b,v(c,VarId::CARDS),ChoicePile::DRAW,c.upgraded);return true;
    case CardId::SACRIFICE: {
        if(b.necro.ostyHp>0){const int block=b.necro.ostyMaxHp*3;necrobinder_kill_osty(b);b.gain_block(block,true);}return true;
    }
    case CardId::SCOURGE:
        b.add_monster_power(target,PowerId::DOOM,v(c,VarId::DOOM_POWER));b.draw_cards(v(c,VarId::CARDS));return true;
    case CardId::SCULPTING_STRIKE:
        b.attack_from_card(c,target,damage);choose(b,c,ChoiceOp::NECRO_SCULPT_ETHEREAL,ChoicePile::HAND);return true;
    case CardId::SEANCE:choose(b,c,ChoiceOp::NECRO_SEANCE,ChoicePile::DRAW);return true;
    case CardId::SENTRY_MODE:b.add_player_power(PowerId::SENTRY_MODE,v(c,VarId::SENTRY_MODE_POWER));return true;
    case CardId::SEVERANCE:
        b.attack_from_card(c,target,damage);necrobinder_create_souls(b,1);necrobinder_create_souls(b,1,ChoicePile::DISCARD);necrobinder_create_souls(b,1,ChoicePile::HAND);return true;
    case CardId::SHARED_FATE:
        b.add_player_power(PowerId::STRENGTH,-v(c,VarId::PLAYER_STRENGTH_LOSS));b.add_monster_power(target,PowerId::STRENGTH,-v(c,VarId::ENEMY_STRENGTH_LOSS));return true;
    case CardId::SHROUD:b.add_player_power(PowerId::SHROUD,v(c,VarId::BLOCK));return true;
    case CardId::SIC_EM:
        necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE));b.add_monster_power(target,PowerId::SIC_EM,v(c,VarId::SIC_EM_POWER));return true;
    case CardId::SLEIGHT_OF_FLESH:b.add_player_power(PowerId::SLEIGHT_OF_FLESH,v(c,VarId::SLEIGHT_OF_FLESH_POWER));return true;
    case CardId::SNAP:
        necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE));choose(b,c,ChoiceOp::NECRO_SNAP_RETAIN,ChoicePile::HAND);return true;
    case CardId::SOUL_STORM:{
        int n=0;for(int i=0;i<b.exhaustCount;++i)if(b.exhaust[i].id==CardId::SOUL)++n;
        b.attack_from_card(c,target,v(c,VarId::CALCULATION_BASE)+v(c,VarId::EXTRA_DAMAGE)*n+c.bonusDamage);return true;
    }
    case CardId::SOULBOUND:b.add_player_power(PowerId::SOULBOUND,1);return true;
    case CardId::SPIRIT_OF_ASH:b.add_player_power(PowerId::SPIRIT_OF_ASH,v(c,VarId::BLOCK_ON_EXHAUST));return true;
    case CardId::SPUR:
        necrobinder_summon(b,v(c,VarId::SUMMON));b.necro.ostyHp=std::min(b.necro.ostyMaxHp,b.necro.ostyHp+v(c,VarId::HEAL));return true;
    case CardId::SQUEEZE:{
        int n=0;auto count=[&](const Card*p,int size){for(int i=0;i<size;++i)if(p[i].uid!=c.uid&&necrobinder_is_osty_attack(p[i].id))++n;};
        count(b.hand,b.handCount);count(b.draw,b.drawCount);count(b.discard,b.discardCount);count(b.exhaust,b.exhaustCount);count(b.playPile,b.playCount);
        necrobinder_attack_osty(b,c,target,v(c,VarId::CALCULATION_BASE)+v(c,VarId::EXTRA_DAMAGE)*n+c.bonusDamage);return true;
    }
    case CardId::THE_SCYTHE:{
        b.attack_from_card(c,target,damage);const int growth=v(c,VarId::INCREASE);c.bonusDamage+=growth;
        bool original=false;for(int i=0;i<b.originalDeckCount;++i)if(b.originalDeckUids[i]==c.uid)original=true;
        if(original){int i=0;while(i<b.necro.scytheCount&&b.necro.scytheUids[i]!=c.uid)++i;
            if(i==b.necro.scytheCount){if(i==160)throw std::overflow_error("Scythe identity capacity");b.necro.scytheUids[i]=c.uid;++b.necro.scytheCount;}
            b.necro.scytheGrowth[i]+=growth;}
        return true;
    }
    case CardId::TIMES_UP:b.attack_from_card(c,target,b.monster_power(target,PowerId::DOOM)+c.bonusDamage);return true;
    case CardId::TRANSFIGURE:choose(b,c,ChoiceOp::NECRO_TRANSFIGURE,ChoicePile::HAND);return true;
    case CardId::UNDEATH:{
        b.gain_block(card_block(c),true);Card copy=c;copy.uid=b.require_card_uid();b.add_card_to_discard(copy);return true;
    }
    case CardId::UNDERWORLD:b.add_player_power(PowerId::UNDERWORLD,1);return true;
    case CardId::UNLEASH:necrobinder_attack_osty(b,c,target,v(c,VarId::CALCULATION_BASE)+b.necro.ostyHp+c.bonusDamage);return true;
    case CardId::VEILPIERCER:
        b.attack_from_card(c,target,damage);b.add_player_power(PowerId::VEILPIERCER,1);return true;
    case CardId::WISP:b.player.energy+=v(c,VarId::ENERGY);return true;
    case CardId::SWEEPING_GAZE:necrobinder_attack_osty(b,c,target,v(c,VarId::OSTY_DAMAGE),1,false,true);return true;
    default:return false;
    }
}
bool necrobinder_resume_effect(BattleContext &b) {
    if(b.activePlay.card.id==CardId::NEUROSURGE&&b.activePlay.necro.stage==1){
        if(b.pending.op!=ChoiceOp::NONE)return false;
        b.activePlay.necro.stage=0;b.add_player_power(PowerId::NEUROSURGE,v(b.activePlay.card,VarId::NEUROSURGE_POWER));
    }return true;
}
namespace {
bool is_debuff(PowerId id,int amount) {
    if(id==PowerId::STRENGTH)return amount<0;
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
        return amount>0;
    default:return false;
    }
}
void misery(BattleContext &b,Card &card,int target) {
    if(target<0||target>=b.monsterCount)return;
    const Monster source=b.monsters[target];
    b.attack_from_card(card,target,card_base_damage(card));
    for(int i=0;i<b.monsterCount;++i)if(i!=target&&b.monsters[i].alive){
        // Temporary strength wrappers apply the strength loss themselves. Keep
        // only the permanent remainder for the independent StrengthPower.
        if(source.weak>0)b.apply_weak(i,source.weak);
        if(source.vulnerable>0)b.apply_vulnerable(i,source.vulnerable);
        const int permanent=source.strength+source.tempStrengthLoss;
        if(permanent<0)b.add_monster_power(i,PowerId::STRENGTH,permanent);
        if(source.tempStrengthLoss>0)b.apply_strength_loss(i,source.tempStrengthLoss);
        for(int p=0;p<static_cast<int>(PowerId::COUNT);++p){
            const auto id=static_cast<PowerId>(p);
            if(id==PowerId::WEAK||id==PowerId::VULNERABLE||id==PowerId::STRENGTH)continue;
            if(is_debuff(id,source.power[p]))b.add_monster_power(i,id,source.power[p]);
        }
        // Native clones preserve debuffs' own accumulated state.
        if(source.power[static_cast<int>(PowerId::SLOW)]>0)b.monsters[i].slowCardsThisTurn=source.slowCardsThisTurn;
    }
}
}
}
