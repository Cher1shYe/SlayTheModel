// Regent combat mechanics: Stars, Forge/Sovereign Blade and the Regent powers.
// Each hook mirrors the native v0.111.0 model named in its comment.  Stars and
// these powers are not Regent-only: other characters reach them through
// cross-character card generation (Prismatic Gem, Sea Glass, Splash, ...).
#include "sts2/regent.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"
#include <algorithm>
#include <stdexcept>

namespace sts2 {
namespace {
bool alive(const BattleContext &b,int i){return i>=0&&i<b.monsterCount&&b.monsters[i].alive;}

// PlayerCombatState.AllCards plus the in-flight play frames.  Dupes
// (HistoryCourse) are excluded, like ForgeCmd.GetSovereignBlades.
template<class F>void each_owned_card(BattleContext &b,bool includeExhausted,F fn){
    Card *piles[]={b.hand,b.draw,b.discard,b.exhaust,b.playPile,b.returnNextTurn};
    const int counts[]={b.handCount,b.drawCount,b.discardCount,b.exhaustCount,b.playCount,b.returnNextTurnCount};
    for(int p=0;p<6;++p){
        if(!includeExhausted&&piles[p]==b.exhaust)continue;
        for(int i=0;i<counts[p];++i)fn(piles[p][i]);
    }
    if(b.activePlay.active&&!b.activePlay.dupe)fn(b.activePlay.card);
    for(int i=0;i<b.suspendedPlayCount;++i)
        if(!b.suspendedPlays[i].play.dupe)fn(b.suspendedPlays[i].play.card);
}

void remove_power(BattleContext &b,PowerId id){const int n=b.player_power(id);if(n)b.add_player_power(id,-n);}

// TemporaryStrengthPower.AfterSideTurnEnd(owner side): remove, restore Strength.
void restore_temp_strength_down(BattleContext &b,int i,PowerId wrapper){
    const int n=b.monster_power(i,wrapper);
    if(!n)return;
    b.add_monster_power(i,wrapper,-n);
    b.add_monster_power(i,PowerId::STRENGTH,n);
}

void add_replays(Card &c,int amount){
    c.replay=static_cast<std::uint8_t>(std::clamp(static_cast<int>(c.replay)+amount,0,255));
}
}

// PlayerCmd.GainStars -> PlayerCombatState.GainStars -> Hook.AfterStarsGained.
void regent_gain_stars(BattleContext &b,int amount){
    if(b.outcome!=Outcome::UNDECIDED||amount<=0)return;
    b.regent.stars+=amount;
    // Radiate sums positive StarsModifiedEntry amounts this turn.
    b.regent.starsGainedThisTurn+=amount;
    // BlackHolePower.AfterStarsGained: unpowered damage to every hittable enemy.
    const int blackHole=b.player_power(PowerId::BLACK_HOLE);
    if(blackHole>0)for(int i=0;i<b.monsterCount&&b.outcome==Outcome::UNDECIDED;++i)
        if(alive(b,i))b.damage_monster(i,blackHole,true,false);
}

// CardModel.SpendStars -> PlayerCombatState.LoseStars -> Hook.AfterStarsSpent.
void regent_spend_stars(BattleContext &b,int amount){
    if(amount<=0)return;
    b.regent.stars=std::max(0,b.regent.stars-amount);
    // ChildOfTheStarsPower.AfterStarsSpent: Amount block per star, unpowered.
    const int child=b.player_power(PowerId::CHILD_OF_THE_STARS);
    if(child>0)b.gain_block(child*amount,false,false);
}

// CardModel.SpendEnergy -> Hook.AfterEnergySpent.  OrbitPower is instanced:
// each instance counts energy independently and pays out every 4 energy.
void regent_spend_energy(BattleContext &b,int amount){
    if(amount<=0)return;
    auto &r=b.regent;
    for(int i=0;i<r.orbitCount;++i){
        const int before=r.orbitEnergy[i];
        r.orbitEnergy[i]+=amount;
        const int triggers=r.orbitEnergy[i]/4-before/4;
        if(triggers>0)b.player.energy+=r.orbitAmounts[i]*triggers;
    }
}

// ForgeCmd.Forge: create a Sovereign Blade if no un-exhausted one exists, then
// add the damage to every blade, exhausted ones included.
void regent_forge(BattleContext &b,int amount){
    if(b.outcome!=Outcome::UNDECIDED)return;
    bool hasBlade=false;
    each_owned_card(b,false,[&](Card &c){hasBlade|=c.id==CardId::SOVEREIGN_BLADE;});
    if(!hasBlade){
        Card blade=make_card(CardId::SOVEREIGN_BLADE,false,b.require_card_uid());
        b.add_card_to_hand(blade);
        b.notify_card_generated(blade);
    }
    each_owned_card(b,true,[&](Card &c){if(c.id==CardId::SOVEREIGN_BLADE)c.bonusDamage+=amount;});
    // HammerTimePower.AfterForge only forges for other living players.
}

// CardFactory.GetDistinctForCombat over the colorless pool: TakeRandom is one
// full UnstableShuffle of the native-ordered pool on CombatCardGeneration.
void regent_generate_colorless(BattleContext &b,int count,bool upgraded){
    if(b.outcome!=Outcome::UNDECIDED||count<=0)return;
    CardId pool[static_cast<int>(CardId::COUNT)];int n=0;
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i){
        const auto id=static_cast<CardId>(i);const auto &d=card_def(id);
        if(d.pool!=CardPool::COLORLESS||!card_native_available(id))continue;
        if(d.rarity!=Rarity::COMMON&&d.rarity!=Rarity::UNCOMMON&&d.rarity!=Rarity::RARE)continue;
        if(d.flags&(CF_UNPLAYABLE|CF_MULTIPLAYER_ONLY|CF_CANNOT_GENERATE_IN_COMBAT))continue;
        pool[n++]=id;
    }
    native_sort_card_ids(pool,n);
    b.cardGenerationRng.shuffle(pool,n);
    for(int k=0;k<count&&k<n&&b.outcome==Outcome::UNDECIDED;++k){
        Card c=make_card(pool[k],upgraded,b.require_card_uid());
        b.add_card_to_hand(c);
        b.notify_card_generated(c);
    }
}

// Hook.AfterCardGeneratedForCombat with the player as creator.
void regent_card_generated(BattleContext &b,const Card &){
    ++b.regent.generatedThisCombat;  // Supermassive counts CardGeneratedEntry.
    const int arsenal=b.player_power(PowerId::ARSENAL);
    if(arsenal>0)b.add_player_power(PowerId::STRENGTH,arsenal);
    const int pillar=b.player_power(PowerId::PILLAR_OF_CREATION);
    if(pillar>0)b.gain_block(pillar,false,false);
}

// SwordSagePower.AfterCardEnteredCombat: new (non-clone) blades gain replays.
void regent_card_entered_combat(BattleContext &b,Card &card,bool clone){
    if(clone||card.id!=CardId::SOVEREIGN_BLADE)return;
    const int sage=b.player_power(PowerId::SWORD_SAGE);
    if(sage>0)add_replays(card,sage);
}

void regent_power_changed(BattleContext &b,PowerId id,int accepted){
    if(!accepted)return;
    // SwordSagePower.AfterPowerAmountChanged / AfterRemoved adjust every blade.
    if(id==PowerId::SWORD_SAGE)
        each_owned_card(b,true,[&](Card &c){if(c.id==CardId::SOVEREIGN_BLADE)add_replays(c,accepted);});
    // VoidFormPower.BeforeApplied / BeforePowerAmountChanged hide this turn's
    // free plays: they only start on the next turn.
    if(id==PowerId::VOID_FORM)b.regent.voidFormManualPlays=999999999;
}

// Per-turn history counters, and VoidFormPower.BeforeSideTurnStart.
void regent_reset_turn(BattleContext &b){
    auto &r=b.regent;
    r.starsGainedThisTurn=0;r.cardsFinishedThisTurn=0;r.skillsFinishedThisTurn=0;
    std::fill(std::begin(r.hitsGivenThisTurn),std::end(r.hitsGivenThisTurn),0);
    r.voidFormManualPlays=0;
}

// Hook.AfterEnergyReset.
void regent_after_energy_reset(BattleContext &b){
    const int next=b.player_power(PowerId::STAR_NEXT_TURN);
    if(next>0){regent_gain_stars(b,next);remove_power(b,PowerId::STAR_NEXT_TURN);}
    const int genesis=b.player_power(PowerId::GENESIS);
    if(genesis>0)regent_gain_stars(b,genesis);
}

// Hook.BeforeHandDraw.  Foregone Conclusion opens a draw-pile selection; the
// caller must stop the turn flow while it is pending.
void regent_before_hand_draw(BattleContext &b){
    if(b.outcome!=Outcome::UNDECIDED)return;
    const int spectrum=b.player_power(PowerId::SPECTRUM_SHIFT);
    if(spectrum>0)regent_generate_colorless(b,spectrum);
    const int foregone=b.player_power(PowerId::FOREGONE_CONCLUSION);
    if(foregone>0&&b.outcome==Outcome::UNDECIDED){
        // CardPileCmd.ShuffleIfNecessary, then CardSelectCmd.FromCombatPile
        // (no RNG; auto-takes everything when the pile is not larger).
        if(b.drawCount==0)b.shuffle_discard_into_draw(false);
        remove_power(b,PowerId::FOREGONE_CONCLUSION);
        if(b.drawCount<=foregone){
            while(b.drawCount>0){Card c=b.draw[0];b.remove_draw_at(0);b.add_card_to_hand(c);}
        }else if(b.pending.op==ChoiceOp::NONE){
            Card source=make_card(CardId::FOREGONE_CONCLUSION,false,0xffff);
            b.start_draw_choice(source,false,-1,-1);
            if(b.pending.op!=ChoiceOp::NONE){
                b.pending.remaining=std::min(foregone,b.pending.count);
                b.pending.hasSource=false;
            }
        }
    }
}

// Hook.AfterPlayerTurnStart: TyrannyPower exhausts Amount chosen hand cards.
void regent_after_player_turn_start(BattleContext &b){
    const int n=b.player_power(PowerId::TYRANNY);
    if(n<=0||b.handCount==0||b.outcome!=Outcome::UNDECIDED)return;
    if(b.handCount<=n){
        Card cards[MAX_HAND];const int count=b.handCount;std::copy(b.hand,b.hand+count,cards);
        for(int i=0;i<count;++i){b.detach_card(cards[i].uid);b.move_to_exhaust(cards[i]);}
        return;
    }
    if(b.pending.op!=ChoiceOp::NONE)return;
    Card source=make_card(CardId::TYRANNY,false,0xffff);
    b.start_choice(ChoiceOp::EXHAUST,ChoicePile::HAND,n,false,source,false);
    if(b.pending.op!=ChoiceOp::NONE)b.pending.hasSource=false;
}

// Hook.AfterSideTurnStart(Player).
void regent_after_side_turn_start(BattleContext &b){
    const int furnace=b.player_power(PowerId::FURNACE);
    if(furnace>0)regent_forge(b,furnace);
    if(b.player_power(PowerId::REFLECT)>0)b.add_player_power(PowerId::REFLECT,-1);
}

// Hook.AfterSideTurnEnd(Player).
void regent_player_turn_end(BattleContext &b){
    auto &r=b.regent;
    // MonologuePower: every instance is removed and takes back its Strength.
    if(r.monologueCount){
        const int count=r.monologueCount;
        remove_power(b,PowerId::MONOLOGUE);
        for(int i=0;i<count;++i)if(r.monologueApplied[i])b.add_player_power(PowerId::STRENGTH,-r.monologueApplied[i]);
        r.monologueCount=0;
        std::fill(std::begin(r.monologueAmounts),std::end(r.monologueAmounts),0);
        std::fill(std::begin(r.monologueApplied),std::end(r.monologueApplied),0);
    }
    r.paleBlueActivated=false;
}

// Hook.AfterSideTurnEnd(Enemy).
void regent_enemy_turn_end(BattleContext &b){
    for(int i=0;i<b.monsterCount;++i){
        if(b.monster_power(i,PowerId::CONQUEROR)>0)b.add_monster_power(i,PowerId::CONQUEROR,-1);
        restore_temp_strength_down(b,i,PowerId::CRUSH_UNDER);
        restore_temp_strength_down(b,i,PowerId::DYING_STAR);
        restore_temp_strength_down(b,i,PowerId::MONARCHS_GAZE_STRENGTH_DOWN);
    }
}

// Hook.BeforeCardPlayed (each play iteration).
void regent_before_card_played(BattleContext &b){
    auto &r=b.regent;auto &p=b.activePlay.regent;
    // MonologuePower.BeforeCardPlayed records each instance's current value.
    p.monologueCount=r.monologueCount;
    std::copy(r.monologueAmounts,r.monologueAmounts+r.monologueCount,p.monologue);
    const int throne=b.player_power(PowerId::THE_SEALED_THRONE);
    if(throne>0)regent_gain_stars(b,throne);
}

// Hook.AfterCardPlayed (each play iteration; CardPlayFinished is recorded first).
void regent_after_card_played(BattleContext &b){
    auto &r=b.regent;auto &play=b.activePlay;
    const bool last=play.nextPlay>=play.playCount;
    if(!play.dupe){
        ++r.cardsFinishedThisTurn;
        if(card_is_skill(play.card))++r.skillsFinishedThisTurn;
    }
    // MonologuePower.AfterCardPlayed.
    for(int i=0;i<play.regent.monologueCount&&i<r.monologueCount;++i){
        const int value=play.regent.monologue[i];
        if(value){b.add_player_power(PowerId::STRENGTH,value);r.monologueApplied[i]+=value;}
    }
    play.regent.monologueCount=0;
    if(b.outcome!=Outcome::UNDECIDED)return;
    // BlackHolePower.AfterCardPlayed: once per series that spent stars.
    const int blackHole=b.player_power(PowerId::BLACK_HOLE);
    if(blackHole>0&&last&&play.starsSpent>0)
        for(int i=0;i<b.monsterCount&&b.outcome==Outcome::UNDECIDED;++i)
            if(alive(b,i))b.damage_monster(i,blackHole,true,false);
    // PaleBlueDotPower counts every finished play this turn (not only attacks).
    const int paleBlue=b.player_power(PowerId::PALE_BLUE_DOT);
    if(paleBlue>0&&!r.paleBlueActivated&&r.cardsFinishedThisTurn>=5){
        r.paleBlueActivated=true;
        b.add_player_power(PowerId::DRAW_CARDS_NEXT_TURN,paleBlue);
    }
    // VoidFormPower.AfterCardPlayed counts manual, last-in-series plays.
    if(b.player_power(PowerId::VOID_FORM)>0&&!play.autoPlay&&last&&r.voidFormManualPlays<999999999)
        ++r.voidFormManualPlays;
}

// No Regent power listens to AfterCardDrawn in the target version.
void regent_card_drawn(BattleContext &,Card &){}

// Hook.AfterDamageGiven / DamageReceivedEntry for player-dealt damage.
void regent_after_damage_given(BattleContext &b,int target,bool poweredAttack){
    if(!poweredAttack||target<0||target>=b.monsterCount)return;
    // Beat Into Shape counts powered attack hits on its target this turn.
    if(target<4)++b.regent.hitsGivenThisTurn[target];
    // MonarchsGazePower: MonarchsGazeStrengthDown (temporary Strength loss).
    const int gaze=b.player_power(PowerId::MONARCHS_GAZE);
    if(gaze>0&&alive(b,target)){
        const int before=b.monster_power(target,PowerId::MONARCHS_GAZE_STRENGTH_DOWN);
        b.add_monster_power(target,PowerId::MONARCHS_GAZE_STRENGTH_DOWN,gaze);
        const int accepted=b.monster_power(target,PowerId::MONARCHS_GAZE_STRENGTH_DOWN)-before;
        if(accepted)b.add_monster_power(target,PowerId::STRENGTH,-accepted);
    }
}

// ReflectPower.AfterDamageReceived: blocked powered attack damage is dealt
// back to the attacker as unpowered damage.
void regent_after_player_attacked(BattleContext &b,int dealer,int blocked){
    if(blocked<=0||b.player_power(PowerId::REFLECT)<=0||!alive(b,dealer)||b.outcome!=Outcome::UNDECIDED)return;
    b.damage_monster(dealer,blocked,true,false);
}

// ConquerorPower.ModifyDamageMultiplicative: Sovereign Blade powered attacks
// deal double damage to the Conqueror owner.
double regent_damage_multiplier(const BattleContext &b,const Card &card,int target){
    if(card.id!=CardId::SOVEREIGN_BLADE||target<0||target>=b.monsterCount)return 1.0;
    return b.monster_power(target,PowerId::CONQUEROR)>0?2.0:1.0;
}

// TyrannyPower.ModifyHandDraw.
int regent_extra_hand_draw(const BattleContext &b){return std::max(0,b.player_power(PowerId::TYRANNY));}

// VoidFormPower: free energy and star cost for the first Amount manual plays
// of each turn, for cards in hand or the play pile.
bool regent_void_form_free(const BattleContext &b,const Card &){
    const int amount=b.player_power(PowerId::VOID_FORM);
    return amount>0&&b.regent.voidFormManualPlays<amount;
}

// CardModel.GetStarCostWithModifiers for a card in a combat pile.  Returns -1
// when the card has no star cost.
int regent_star_cost(const BattleContext &b,const Card &card){
    const auto &d=card_def(card.id);
    const bool x=card.upgraded?d.starCostXUp:d.starCostX;
    if(x)return b.regent.stars;
    const int cost=card.upgraded?d.starCostUp:d.starCost;
    if(cost<0)return -1;
    if(regent_void_form_free(b,card))return 0;
    // BrilliantScarf.TryModifyStarCost shares its energy rule.
    if(relic_has(b,RelicId::BRILLIANT_SCARF)&&b.cardsPlayedThisTurn==4)return 0;
    return cost;
}

// PlayerCmd.EndTurn from Void Form: the turn ends once the action queue has
// drained.  Returns true when the turn was ended.
bool regent_take_end_turn_request(BattleContext &b){
    if(!b.regent.endTurnRequested)return false;
    if(b.pending.op!=ChoiceOp::NONE||b.activePlay.active||b.suspendedPlayCount||b.autoPlayQueueCount)return false;
    b.regent.endTurnRequested=false;
    if(b.outcome!=Outcome::UNDECIDED)return false;
    b.end_player_turn();
    return true;
}
}
