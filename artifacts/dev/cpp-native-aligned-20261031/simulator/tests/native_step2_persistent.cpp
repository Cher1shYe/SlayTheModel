#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include "sts2/relic_persistent.h"
using namespace sts2;using json=nlohmann::json;
namespace {
int checks=0,failures=0;
void check(const std::string &s,double got,double want){++checks;if(std::abs(got-want)>1e-9){++failures;std::cout<<s<<" got="<<got<<" native="<<want<<" FAIL\n";}}
CardId id(const std::string &s){for(int i=1;i<int(CardId::COUNT);++i)if(s==card_key(static_cast<CardId>(i)))return static_cast<CardId>(i);throw std::runtime_error("Missing fixture CardId "+s);}
BattleContext base(){BattleContext b;Card c=make_card(CardId::DEFEND_IRONCLAD,false,1);b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,7,&c,1,0,80,80);b.handCount=b.drawCount=b.discardCount=b.exhaustCount=b.knownTopCount=0;b.relicCount=0;b.monsterCount=2;for(int i=0;i<2;++i){b.monsters[i]=Monster{};b.monsters[i].id=MonsterId::CALCIFIED_CULTIST;b.monsters[i].hp=b.monsters[i].maxHp=10000;}return b;}
void cards(const std::string &label,const Card *pile,int count,const json &want,bool ordered=true){
 check(label+" count",count,want.size());if(count!=int(want.size()))return;
 std::vector<std::pair<std::string,bool>> got,expected;
 for(int i=0;i<count;++i){got.push_back({card_key(pile[i].id),pile[i].upgraded});expected.push_back({want[i]["id"],want[i]["upgraded"]});}
 if(!ordered){std::sort(got.begin(),got.end());std::sort(expected.begin(),expected.end());}
 for(int i=0;i<count;++i){check(label+" identity",got[i].first==expected[i].first,true);check(label+" upgraded",got[i].second,expected[i].second);}
}
}
int main(){
 const auto root=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path();json fixtures;std::ifstream(root/"native-round4-step2-persistent-fixtures/results.json")>>fixtures;
 check("native completed",fixtures["status"]=="completed",true);check("target DLL",fixtures["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4",true);
 for(const auto &f:fixtures["results"]){const std::string t=f["test"];
  if(t=="bone_tea"){
   auto b=base();b.turn=1;b.relics[b.relicCount++]=int(RelicId::BONE_TEA);b.relicAux[0]=f["startsUsed"]?0:1;b.boneTeaPending=b.relicAux[0]>0;
   for(const auto &c:f["before"])b.hand[b.handCount++]=make_card(id(c["id"]),c["upgraded"],b.require_card_uid());
   relic_persistent_finish_turn_start(b);cards("BoneTea first",b.hand,b.handCount,f["first"]);
   b.hand[b.handCount++]=make_card(CardId::BASH,false,b.require_card_uid());relic_persistent_finish_turn_start(b);cards("BoneTea second",b.hand,b.handCount,f["second"]);check("BoneTea consumed",b.relicAux[0],f["left"]);
  }else if(t=="bone_initial"){
   Card deck[5];int n=0;for(const auto &c:f["deck"])deck[n++]=make_card(id(c["id"]),false,n+1);
   BattleContext b;int relic=int(RelicId::BONE_TEA);b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,7,deck,n,0,80,80,&relic,1);
   cards("BoneTea actual init hand",b.hand,b.handCount,f["hand"],false);cards("BoneTea deck unchanged",deck,n,f["deck"],false);check("BoneTea actual init consumed",b.relicAux[0],f["left"]);
  }else if(t=="fake_tea"){
   RunContext r;r.relics[r.relicCount++]=int(RelicId::FAKE_VENERABLE_TEA_SET);for(int i=0;i<int(f["rests"]);++i)relic_persistent_rest_entered(r);
   check("FakeTea armed",r.relicAux[0]>0,bool(f["armed"]));auto b=base();b.relicCount=1;b.relics[0]=r.relics[0];b.relicAux[0]=r.relicAux[0];b.player.energy=3;relic_persistent_after_energy_reset(b);check("FakeTea first energy",b.player.energy,f["first"]);check("FakeTea consumed",b.relicAux[0]==0,bool(f["consumed"]));b.player.energy=3;relic_persistent_after_energy_reset(b);check("FakeTea second energy",b.player.energy,f["second"]);
  }else if(t=="byrd_transform"){
   RunContext r;r.seed=f["seed"];r.hp=r.maxHp=80;r.gold=99;r.screen=RunScreen::COMBAT;
   r.deck[r.deckCount++]=r.make_run_card(CardId::BASH,false);r.deck[r.deckCount++]=r.make_run_card(CardId::BYRDONIS_EGG,false);r.deck[r.deckCount++]=r.make_run_card(CardId::DEFEND_IRONCLAD,false);r.deck[r.deckCount++]=r.make_run_card(CardId::BYRDONIS_EGG,false);
   r.battle=base();auto &b=r.battle;b.draw[b.drawCount++]=make_card(CardId::BYRDONIS_EGG,false,b.require_card_uid());b.discard[b.discardCount++]=make_card(CardId::BYRDONIS_EGG,false,b.require_card_uid());b.exhaust[b.exhaustCount++]=make_card(CardId::BYRDONIS_EGG,false,b.require_card_uid());
   const std::string hooks=f["hooks"];
   if(hooks=="molten")r.add_relic(RelicId::MOLTEN_EGG);if(hooks=="bing")r.add_relic(RelicId::BING_BONG);
   if(hooks=="fresnel_lucky_book"){r.add_relic(RelicId::FRESNEL_LENS);r.add_relic(RelicId::LUCKY_FYSH);r.add_relic(RelicId::BOOK_OF_FIVE_RINGS);r.cardsAdded=3;r.hp=b.player.hp=30;}
   const int niche=r.runRng[RNG_NICHE].counter,trans=r.playerRng[PRNG_TRANSFORMATIONS].counter,gold=r.gold;
   const std::uint16_t oldEggUids[]={r.deck[1].uid,r.deck[3].uid,b.draw[0].uid,b.discard[0].uid,b.exhaust[0].uid};
   check("Byrd acquired",r.add_relic(RelicId::BYRDPIP),true);
   for(int i=2;i<r.deckCount;++i)check("Byrd fresh deck entity",r.deck[i].uid!=oldEggUids[0]&&r.deck[i].uid!=oldEggUids[1],true);
   check("Byrd fresh draw entity",b.draw[0].uid!=oldEggUids[2],true);check("Byrd fresh discard entity",b.discard[0].uid!=oldEggUids[3],true);check("Byrd fresh exhaust entity",b.exhaust[0].uid!=oldEggUids[4],true);
   cards("Byrd deck",r.deck,r.deckCount,f["deck"]);cards("Byrd draw",b.draw,b.drawCount,f["draw"]);cards("Byrd discard",b.discard,b.discardCount,f["discard"]);cards("Byrd exhaust",b.exhaust,b.exhaustCount,f["exhaust"]);
   for(int i=0;i<r.relicCount;++i)if(r.relics[i]==int(RelicId::BYRDPIP))check("Byrd skin",r.relicAux[i],std::stoi(std::string(f["skin"]).substr(7))-1);
   check("Byrd pet",b.byrdpipPresent,int(f["petCount"]));check("Byrd event pet",run_has_event_pet(r),bool(f["hasEventPet"]));check("Byrd hp hook",r.hp,f["hp"]);check("Byrd combat hp hook",b.player.hp,f["hp"]);check("Byrd gold hook",r.gold-gold,f["goldDelta"]);check("Byrd book hook",r.cardsAdded,f["bookCount"]);check("Byrd niche unchanged",r.runRng[RNG_NICHE].counter-niche,f["nicheDelta"]);check("Byrd transform rng unchanged",r.playerRng[PRNG_TRANSFORMATIONS].counter-trans,f["transformDelta"]);
   for(int i=0;i<r.deckCount;++i)check("Byrd Fresnel hook",r.deck[i].enchantment==EnchantmentId::NIMBLE,!f["enchants"][i].is_null());
  }else if(t=="byrd_attack"){
   auto b=base();b.byrdpipPresent=f["pet"];b.player.strength=3;b.hand[b.handCount++]=make_card(CardId::BYRD_SWOOP,f["upgraded"],b.require_card_uid());Action a;a.type=ActionType::PLAY_CARD;a.hand=0;a.target=0;check("Byrd Swoop playable",b.step(a),true);for(int i=0;i<2;++i)check("Byrd Swoop damage",10000-b.monsters[i].hp,f["damage"][i]);
  }else check("known fixture",false,true);
 }
 // The upgrade pauses with the actual player choice, rather than consuming the
 // one-combat relic while the opening hand is still being constructed.
 auto b=base();b.relics[b.relicCount++]=int(RelicId::BONE_TEA);b.relicAux[0]=1;b.boneTeaPending=true;b.turn=1;b.hand[b.handCount++]=make_card(CardId::BASH,false,b.require_card_uid());b.pending.op=ChoiceOp::DRAW_TO_HAND;b.pending.pile=ChoicePile::DRAW;b.pending.remaining=1;
 b.draw[b.drawCount++]=make_card(CardId::DEFEND_IRONCLAD,false,b.require_card_uid());b.pending.cards[0]=b.draw[0];b.pending.count=1;
 relic_persistent_finish_turn_start(b);check("BoneTea paused",b.relicAux[0],1);check("BoneTea original hand unmodified before choice",b.hand[0].upgraded,false);b.resolve_choice(b.pending.cards[0].uid);check("BoneTea resumes after choice",b.relicAux[0],0);check("BoneTea chosen card upgraded",b.hand[1].upgraded,true);
 std::cout<<"Native step2 persistent: "<<fixtures["results"].size()<<" fixtures, "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;
}
