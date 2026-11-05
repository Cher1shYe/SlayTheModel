#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include <iostream>
#include <set>
using namespace sts2;
namespace {
int checks=0,failures=0;
void check(const char *name,bool ok){++checks;failures+=!ok;std::cout<<name<<(ok?" PASS\n":" FAIL\n");}
RunContext base(std::uint64_t seed=42) {
    RunContext r;r.init(147,0);r.screen=RunScreen::SHOP;r.deckCount=0;r.relicCount=0;r.hp=80;r.maxHp=80;
    for(CardId id:{CardId::BASH,CardId::DEFEND_IRONCLAD,CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,
                  CardId::STRIKE_IRONCLAD,CardId::ANGER,CardId::POMMEL_STRIKE,CardId::IRON_WAVE})
        r.deck[r.deckCount++]=r.make_run_card(id,false);
    r.runRng[RNG_NICHE]=Rng(seed);r.playerRng[PRNG_TRANSFORMATIONS]=Rng(seed);return r;
}
}
int main(){
    {
#include "../../native-round3-relic-fixtures/transformation_pool.inc"
        CardId actual[static_cast<int>(CardId::COUNT)];int count=0;
        for(int i=1;i<static_cast<int>(CardId::COUNT);++i) {
            const auto id=static_cast<CardId>(i);const auto &d=card_def(id);
            if(!card_native_available(id)||d.pool!=CardPool::IRONCLAD||(d.flags&CF_MULTIPLAYER_ONLY))continue;
            if(d.rarity==Rarity::COMMON||d.rarity==Rarity::UNCOMMON||d.rarity==Rarity::RARE)actual[count++]=id;
        }
        native_sort_card_ids(actual,count);
        const int expected=sizeof(nativeIroncladTransformPool)/sizeof(nativeIroncladTransformPool[0]);
        check("Complete native Ironclad transformation pool and order",count==expected&&std::equal(actual,actual+count,nativeIroncladTransformPool));
    }
    for(std::uint64_t seed:{0,42}) {
        auto r=base(seed);check("DistinguishedCape obtains",r.add_relic(RelicId::DISTINGUISHED_CAPE));
        check("DistinguishedCape preserves HP/maxHP",r.hp==80&&r.maxHp==80);
        check("DistinguishedCape adds two distinct native curses",r.deckCount==13&&
            r.deck[8].id==(seed==0?CardId::NORMALITY:CardId::CLUMSY)&&r.deck[9].id==(seed==0?CardId::REGRET:CardId::GUILTY));
        check("DistinguishedCape adds three Apparition",r.deck[10].id==CardId::APPARITION&&r.deck[11].id==CardId::APPARITION&&r.deck[12].id==CardId::APPARITION);
        check("DistinguishedCape exact RNG",r.runRng[RNG_NICHE].counter==2&&r.playerRng[PRNG_TRANSFORMATIONS].counter==0);
        r=base(seed);check("SereTalon obtains",r.add_relic(RelicId::SERE_TALON));
        check("SereTalon loses nine maximum HP",r.maxHp==71&&r.hp==71);
        check("SereTalon adds three Wish without curses",r.deckCount==11&&r.deck[8].id==CardId::WISH&&r.deck[9].id==CardId::WISH&&r.deck[10].id==CardId::WISH);
        check("SereTalon consumes no RNG",r.runRng[RNG_NICHE].counter==0&&r.playerRng[PRNG_TRANSFORMATIONS].counter==0);
        r=base(seed);const auto bashUid=r.deck[0].uid,defendUid=r.deck[3].uid,strikeUid=r.deck[4].uid;
        check("LeafyPoultice obtains",r.add_relic(RelicId::LEAFY_POULTICE));
        check("LeafyPoultice loses twelve maximum HP",r.maxHp==68&&r.hp==68);
        check("LeafyPoultice keeps Bash and second basic copies",r.deckCount==8&&r.deck[0].uid==bashUid&&r.deck[1].uid==defendUid&&r.deck[2].uid==strikeUid);
        check("LeafyPoultice exact native transformation identity/order",r.deck[6].id==(seed==0?CardId::SECOND_WIND:CardId::FIGHT_ME)&&r.deck[7].id==(seed==0?CardId::OFFERING:CardId::BLOOD_WALL));
        check("LeafyPoultice uses player Transformation RNG",r.runRng[RNG_NICHE].counter==0&&r.playerRng[PRNG_TRANSFORMATIONS].counter==2);
        std::set<int> uids;for(int i=0;i<r.deckCount;++i)uids.insert(r.deck[i].uid);
        check("LeafyPoultice uses fresh unique replacement entities",uids.size()==8&&r.deck[6].uid!=defendUid&&r.deck[7].uid!=strikeUid);
        r=base(seed);check("NeowsTorment obtains",r.add_relic(RelicId::NEOWS_TORMENT));
        check("NeowsTorment adds NeowsFury",r.deckCount==9&&r.deck[8].id==CardId::NEOWS_FURY);
        check("NeowsTorment consumes no RNG",r.runRng[RNG_NICHE].counter==0);
    }
    {
        auto r=base();r.hp=30;r.add_relic(RelicId::LUCKY_FYSH);r.add_relic(RelicId::BOOK_OF_FIVE_RINGS);
        r.add_relic(RelicId::MOLTEN_EGG);r.add_relic(RelicId::BING_BONG);r.cardsAdded=4;
        r.add_relic(RelicId::LEAFY_POULTICE);
        check("LeafyPoultice replacement hooks match native",r.hp==50&&r.maxHp==68&&r.gold==159&&r.cardsAdded==8&&r.deckCount==10);
        check("LeafyPoultice Egg and duplicate identities",r.deck[6].id==CardId::FIGHT_ME&&r.deck[6].upgraded&&r.deck[7].id==CardId::FIGHT_ME&&r.deck[7].upgraded&&r.deck[8].id==CardId::BLOOD_WALL&&r.deck[9].id==CardId::BLOOD_WALL);
        r=base();r.deckCount=1;r.add_relic(RelicId::LEAFY_POULTICE);
        check("LeafyPoultice leaves Bash alone without RNG",r.deckCount==1&&r.deck[0].id==CardId::BASH&&r.hp==68&&r.playerRng[PRNG_TRANSFORMATIONS].counter==0);
        r=base();r.hp=r.maxHp=8;r.add_relic(RelicId::LIZARD_TAIL);r.add_relic(RelicId::SERE_TALON);
        check("SereTalon maxHP loss activates LizardTail before clamping",r.hp==1&&r.maxHp==1&&r.relicAux[0]==1&&r.deckCount==11);
        r=base();r.hp=r.maxHp=10;r.add_relic(RelicId::TUNGSTEN_ROD);r.add_relic(RelicId::SERE_TALON);
        check("SereTalon Tungsten survival still clamps HP",r.hp==1&&r.maxHp==1&&r.deckCount==11);
    }
    for(int gold:{0,2,3,4,5,6}) {
        BattleContext b{};b.relicCount=1;b.relics[0]=static_cast<int>(RelicId::SEAL_OF_GOLD);b.gold=gold;b.turn=1;
        const int energy=relics_energy_for_turn(b,3);
        check("SealOfGold native three-gold boundary",energy==(gold>=3?4:3)&&b.gold==(gold>=3?gold-3:gold));
    }
    for(std::uint64_t seed:{0,42})for(bool empty:{false,true}) {
        // Original native draw order from the DLL fixture; simulator top is last.
        const CardId native[]={CardId::DEFEND_IRONCLAD,CardId::ANGER,CardId::IRON_WAVE,CardId::STRIKE_IRONCLAD,
            CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH,CardId::POMMEL_STRIKE};
        BattleContext b{};b.player.hp=b.player.maxHp=80;b.relicCount=1;b.relics[0]=static_cast<int>(RelicId::STONE_CRACKER);
        b.cardSelectionRng=Rng(seed);b.drawCount=8;b.encounter=Encounter::INVALID;
        for(int i=0;i<8;++i)b.draw[7-i]=make_card(native[i],empty,static_cast<std::uint16_t>(i+1));
        relics_combat_start(b);bool exact=true;
        for(int i=0;i<8;++i)exact&=b.draw[7-i].upgraded==(empty||i==6||i==(seed==0?3:4));
        check("StoneCracker exact native eligible identity outside boss",exact);
        check("StoneCracker stable shuffle RNG includes full eligible list",b.cardSelectionRng.counter==(empty?0:7));
    }
    {
        BattleContext b{};b.relicCount=1;b.relics[0]=static_cast<int>(RelicId::FAKE_STRIKE_DUMMY);
        check("FakeStrikeDummy adds one only to tagged strikes",relics_damage_additive(b,make_card(CardId::STRIKE_IRONCLAD,false,1))==1&&relics_damage_additive(b,make_card(CardId::BASH,false,2))==0);
        b.relics[b.relicCount++]=static_cast<int>(RelicId::STRIKE_DUMMY);
        check("FakeStrikeDummy stacks with real StrikeDummy",relics_damage_additive(b,make_card(CardId::STRIKE_IRONCLAD,false,1))==4);
    }
    std::cout<<"native relic round3: "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;
}
