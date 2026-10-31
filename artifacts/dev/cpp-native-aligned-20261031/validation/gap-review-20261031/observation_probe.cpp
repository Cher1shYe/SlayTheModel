#include "sts2/observe.h"
#include <iostream>
using namespace sts2;
int main() {
    Card deck[10];
    for (int i=0;i<10;++i) deck[i]=make_card(CardId::STRIKE_IRONCLAD,false,i+1);
    BattleContext a;
    a.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,123,deck,10,0,80,80);
    a.drawCount=1; a.discardCount=0; a.exhaustCount=0; a.knownTopCount=0;
    a.draw[0]=make_card(CardId::THRASH,false,99); a.draw[0].bonusDamage=4.5;
    auto b=a; b.draw[0].bonusDamage=12;
    const bool drawCollision=public_combat_observation(a)==public_combat_observation(b);
    a.discardCount=1; a.discard[0]=a.draw[0]; a.drawCount=0;
    b=a;b.discard[0].bonusDamage=12;
    const bool discardCollision=public_combat_observation(a)==public_combat_observation(b);
    a.handCount=1;a.hand[0]=a.discard[0];a.discardCount=0;
    b=a;b.hand[0].bonusDamage=12;
    const bool handDistinguished=public_combat_observation(a)!=public_combat_observation(b);
    std::cout<<"{\"draw_bonus_damage_collision\":"<<(drawCollision?"true":"false")
             <<",\"discard_bonus_damage_collision\":"<<(discardCollision?"true":"false")
             <<",\"hand_distinguishes_bonus_damage\":"<<(handDistinguished?"true":"false")<<"}\n";
}
