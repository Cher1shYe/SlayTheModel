// Source-derived numeric checks for every elite rules model at A0..A10.
// Not a live DLL combat replay. Native evidence: Models/Monsters/{name}.cs
// damage properties and actual DamageCmd/PowerCmd/CreatureCmd move bodies.
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include <cassert>
#include <memory>

using namespace sts2;

static std::unique_ptr<BattleContext> start(Encounter encounter, int asc) {
    auto b = std::make_unique<BattleContext>();
    Card deck[10];
    for (int i=0;i<10;++i) deck[i]=make_card(CardId::DEFEND_IRONCLAD,false,i+1);
    b->init(encounter,4242,deck,10,asc,5000,5000);
    return b;
}
static std::unique_ptr<BattleContext> isolate(MonsterId id,int asc) {
    auto b=start(Encounter::SETUP_TOADPOLES_WEAK,asc);
    b->monsterCount=1;
    spawn_monster(*b,id,0);
    b->monsters[1].alive=false;
    return b;
}
static void act(BattleContext &b,int move) {
    auto &m=b.monsters[0];
    m.move=move;m.pendingRoll=false;m.stunned=false;
    roll_intent(b,m);
    monster_act(b,m);
}
static int count(const BattleContext &b,CardId id) {
    int n=0;
    for(int i=0;i<b.handCount;++i)n+=b.hand[i].id==id;
    for(int i=0;i<b.drawCount;++i)n+=b.draw[i].id==id;
    for(int i=0;i<b.discardCount;++i)n+=b.discard[i].id==id;
    return n;
}

int main() {
    using M=MonsterId;
    struct Attack {M id;int move,low,high,hitsLow,hitsHigh;};
    // High damage/hits start at DeadlyEnemies=A9, not ToughEnemies=A8.
    const Attack attacks[]={
        {M::BYGONE_EFFIGY,3,13,15,1,1},
        {M::BYRDONIS,0,17,19,1,1},{M::BYRDONIS,1,3,4,3,3},
        {M::DECIMILLIPEDE_SEGMENT,0,5,6,2,2},{M::DECIMILLIPEDE_SEGMENT,1,8,9,1,1},{M::DECIMILLIPEDE_SEGMENT,2,6,7,1,1},
        {M::ENTOMANCER,0,3,3,7,8},{M::ENTOMANCER,1,18,20,1,1},
        {M::FLAIL_KNIGHT,2,9,10,2,2},{M::FLAIL_KNIGHT,3,15,17,1,1},
        {M::INFESTED_PRISM,0,15,17,1,1},{M::INFESTED_PRISM,1,11,13,1,1},
        {M::INFESTED_PRISM,2,5,6,3,3},{M::INFESTED_PRISM,3,8,10,1,1},
        {M::MAGI_KNIGHT,0,6,7,1,1},{M::MAGI_KNIGHT,2,10,11,1,1},{M::MAGI_KNIGHT,4,35,40,1,1},
        {M::MECHA_KNIGHT,0,25,30,1,1},{M::MECHA_KNIGHT,1,8,12,1,1},{M::MECHA_KNIGHT,3,35,40,1,1},
        {M::PHANTASMAL_GARDENER,1,5,5,1,1},{M::PHANTASMAL_GARDENER,2,7,7,1,1},{M::PHANTASMAL_GARDENER,3,1,1,3,3},
        {M::PHROG_PARASITE,1,4,5,4,4},
        {M::SKULKING_COLONY,0,9,11,1,1},{M::SKULKING_COLONY,1,14,16,1,1},
        {M::SKULKING_COLONY,2,7,8,2,2},{M::SKULKING_COLONY,3,14,16,1,1},
        {M::SOUL_NEXUS,1,29,31,1,1},{M::SOUL_NEXUS,2,6,7,4,4},{M::SOUL_NEXUS,3,18,19,1,1},
        {M::SPECTRAL_KNIGHT,2,15,17,1,1},{M::SPECTRAL_KNIGHT,3,3,4,3,3},
        {M::TERROR_EEL,0,16,18,1,1},{M::TERROR_EEL,1,3,4,3,3},
        {M::WRIGGLER,2,6,7,1,1},
    };
    for(int asc=0;asc<=10;++asc) {
        for(const auto &a:attacks) {
            auto b=isolate(a.id,asc);
            const int hp=b->player.hp;
            act(*b,a.move);
            assert(hp-b->player.hp==(asc>=9?a.high:a.low)*(asc>=9?a.hitsHigh:a.hitsLow));
        }
        {auto b=isolate(M::BYGONE_EFFIGY,asc);act(*b,1);assert(b->monster_power(0,PowerId::STRENGTH)==10);}
        {auto b=isolate(M::BYRDONIS,asc);act(*b,1);assert(b->monster_power(0,PowerId::STRENGTH)==1);}
        {auto b=isolate(M::DECIMILLIPEDE_SEGMENT,asc);act(*b,1);assert(b->player_power(PowerId::WEAK)==1);}
        {auto b=isolate(M::DECIMILLIPEDE_SEGMENT,asc);act(*b,2);assert(b->monster_power(0,PowerId::STRENGTH)==2);}
        {auto b=isolate(M::FLAIL_KNIGHT,asc);act(*b,1);assert(b->monster_power(0,PowerId::STRENGTH)==3);}
        {auto b=isolate(M::INFESTED_PRISM,asc);act(*b,1);assert(b->monsters[0].block==(asc>=9?13:11));}
        {auto b=isolate(M::INFESTED_PRISM,asc);act(*b,3);assert(b->monsters[0].block==(asc>=8?22:20));assert(b->monster_power(0,PowerId::VITAL_SPARK)==(asc>=9?6:4));}
        // VitalSparkPower.cs:79-96 also changes the amount displayed on every
        // already-afflicted card, not only damage applied after that card plays.
        {auto b=start(Encounter::SETUP_INFESTED_PRISMS_ELITE,asc);
         const int initial=asc>=9?3:2;
         assert(b->handCount>0 && b->hand[0].tainted==initial);
         act(*b,3);
         const Card *piles[]={b->hand,b->draw,b->discard,b->exhaust,b->playPile,b->returnNextTurn};
         const int sizes[]={b->handCount,b->drawCount,b->discardCount,b->exhaustCount,b->playCount,b->returnNextTurnCount};
         int checked=0;for(int p=0;p<6;++p)for(int i=0;i<sizes[p];++i)if(piles[p][i].tainted){++checked;assert(piles[p][i].tainted==initial*2);}
         assert(checked==10);}
        // Reachable mid-card death: Defend gains block, Juggernaut kills the
        // Prism, and VitalSpark.AfterRemoved must clean the active card before
        // finish_active_play moves its copy back to the discard pile.
        {auto b=start(Encounter::SETUP_INFESTED_PRISMS_ELITE,asc);
         assert(b->handCount>0 && b->hand[0].id==CardId::DEFEND_IRONCLAD && b->hand[0].tainted>0);
         const auto playedUid=b->hand[0].uid;
         b->player.power[static_cast<int>(PowerId::JUGGERNAUT)]=5;
         b->monsters[0].hp=1;b->monsters[0].block=0;
         assert(b->play_card(0,0));
         assert(!b->monsters[0].alive && b->outcome==Outcome::PLAYER_VICTORY);
         assert(!b->activePlay.active);
         const Card *piles[]={b->hand,b->draw,b->discard,b->exhaust,b->playPile,b->returnNextTurn};
         const int sizes[]={b->handCount,b->drawCount,b->discardCount,b->exhaustCount,b->playCount,b->returnNextTurnCount};
         int total=0,playedCopies=0;
         for(int p=0;p<6;++p)for(int i=0;i<sizes[p];++i){++total;playedCopies+=piles[p][i].uid==playedUid;assert(piles[p][i].tainted==0);}
         assert(total==10 && playedCopies==1);}
        for(int move:{0,3}) {auto b=isolate(M::MAGI_KNIGHT,asc);act(*b,move);assert(b->monsters[0].block==(asc>=8?9:5));}
        {auto b=isolate(M::MAGI_KNIGHT,asc);act(*b,1);assert(b->player_power(PowerId::DAMPEN)==1);}
        {auto b=isolate(M::MECHA_KNIGHT,asc);act(*b,1);assert(count(*b,CardId::BURN)==4);}
        {auto b=isolate(M::MECHA_KNIGHT,asc);act(*b,2);assert(b->monsters[0].block==15);assert(b->monster_power(0,PowerId::STRENGTH)==5);}
        {auto b=isolate(M::PHANTASMAL_GARDENER,asc);act(*b,4);assert(b->monster_power(0,PowerId::STRENGTH)==(asc>=9?3:2));}
        {auto b=isolate(M::PHROG_PARASITE,asc);act(*b,0);assert(count(*b,CardId::INFECTION)==3);}
        {auto b=isolate(M::SKULKING_COLONY,asc);act(*b,0);assert(b->monster_power(0,PowerId::STRENGTH)==(asc>=9?4:2));}
        {auto b=isolate(M::SOUL_NEXUS,asc);act(*b,3);assert(b->player_power(PowerId::WEAK)==2);assert(b->player_power(PowerId::VULNERABLE)==2);}
        {auto b=isolate(M::SPECTRAL_KNIGHT,asc);act(*b,0);assert(b->player_power(PowerId::HEX)==2);}
        {auto b=isolate(M::TERROR_EEL,asc);act(*b,1);assert(b->monster_power(0,PowerId::VIGOR)==6);act(*b,0);assert(b->monster_power(0,PowerId::VIGOR)==0);}
        {auto b=isolate(M::TERROR_EEL,asc);act(*b,3);assert(b->player_power(PowerId::VULNERABLE)==99);}
        {auto b=isolate(M::WRIGGLER,asc);act(*b,3);assert(count(*b,CardId::INFECTION)==1);assert(b->monster_power(0,PowerId::STRENGTH)==2);}

        // Entomancer.cs:60-66 returns immediately when Personal Hive is absent/3+.
        {auto b=isolate(M::ENTOMANCER,asc);for(int i=0;i<4;++i)act(*b,2);
         assert(b->monster_power(0,PowerId::PERSONAL_HIVE)==3);assert(b->monster_power(0,PowerId::STRENGTH)==6);}
        {auto b=isolate(M::ENTOMANCER,asc);power_ref(b->monsters[0],PowerId::PERSONAL_HIVE)=0;act(*b,2);
         assert(b->monster_power(0,PowerId::PERSONAL_HIVE)==0);assert(b->monster_power(0,PowerId::STRENGTH)==2);}

        // ReattachPower.cs:47 heals 25; all three concrete segments share it.
        {auto b=start(Encounter::SETUP_DECIMILLIPEDE_ELITE,asc);b->kill_monster(0);
         assert(b->monsters[0].reviving);monster_act(*b,b->monsters[0]);
         // Native DeadState first performs its empty move; the next player
         // turn rolls its Reattach follow-up before the following enemy turn.
         assert(b->monsters[0].reviving && b->monsters[0].hp==0);
         roll_pending_moves(*b);assert(b->monsters[0].move==4);
         monster_act(*b,b->monsters[0]);
         assert(!b->monsters[0].reviving && b->monsters[0].hp==25);}
        // InfestedPower.cs:26-32 creates four Wrigglers, each with one skipped turn.
        {auto b=start(Encounter::SETUP_PHROG_PARASITE_ELITE,asc);b->kill_monster(0);int n=0;
         for(int i=0;i<b->monsterCount;++i)if(b->monsters[i].id==M::WRIGGLER && b->monsters[i].alive){++n;assert(b->monsters[i].stunned);}
         assert(n==4);}
    }
}
