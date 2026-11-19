// RelicModel.ShowCounter / DisplayAmount / Status, pinned native 41cef1ea.
// Animation-only IsActivating pulses are excluded: observations are taken at
// settled decision boundaries. Internal triggering card UIDs are never exposed.
static py::list public_relic_view(const RunContext &rc,bool inCombat) {
    const BattleContext &b=rc.battle;
    int finishedCards=b.cardsPlayedThisTurn,finishedAttacks=b.attacksPlayedThisTurn,finishedSkills=b.skillsPlayedThisTurn;
    bool manualInFlight=false;
    auto unfinished=[&](const ActivePlay &play) {
        manualInFlight |= play.active && !play.autoPlay;
        if(!play.active || !play.awaitingAfter)return;
        --finishedCards;finishedAttacks-=card_is_attack(play.card);finishedSkills-=card_is_skill(play.card);
    };
    unfinished(b.activePlay);
    for(int i=0;i<b.suspendedPlayCount;++i)unfinished(b.suspendedPlays[i].play);
    py::list result;
    const int count=inCombat?b.relicCount:rc.relicCount;
    for(int slot=0;slot<count;++slot) {
        const auto id=static_cast<RelicId>(inCombat?b.relics[slot]:rc.relics[slot]);
        const std::string key=relic_def(id).key;
        const int aux=inCombat?b.relicAux[slot]:rc.relicAux[slot];
        const bool melted=inCombat?b.relicMelted[slot]:rc.relicMelted[slot];
        const bool live=inCombat&&!melted;
        const int relicFinishedCards=melted?0:finishedCards;
        const int relicFinishedAttacks=melted?0:finishedAttacks;
        const int relicFinishedSkills=melted?0:finishedSkills;
        int runAux=0;
        for(int i=0;i<rc.relicCount;++i)if(rc.relics[i]==static_cast<int>(id)){runAux=rc.relicAux[i];break;}
        bool show=false,active=false,disabled=false;
        int counter=0;
        if(key=="PEN_NIB") {show=true;counter=aux==100?0:aux%10;active=counter==9;}
        else if(key=="HAPPY_FLOWER") {show=true;counter=aux%3;active=live&&counter==2;}
        else if(key=="FAKE_HAPPY_FLOWER") {show=true;counter=aux%5;active=live&&counter==4;}
        else if(key=="PENDULUM") {show=true;counter=aux%3;active=live&&counter==2;}
        else if(key=="POLLINOUS_CORE") {show=true;counter=aux;active=live&&counter==3;}
        else if(key=="IRON_CLUB") {show=true;counter=aux%4;active=counter==3;}
        else if(key=="NUNCHAKU") {show=true;counter=aux%10;active=counter==9;}
        else if(key=="JOSS_PAPER") {show=true;counter=aux;active=counter==4;}
        else if(key=="TUNING_FORK") {show=true;counter=aux;active=counter==9;}
        else if(key=="LASTING_CANDY") {show=true;counter=aux%2;}
        else if(key=="BOOK_OF_FIVE_RINGS") {show=true;counter=rc.cardsAdded%5;}
        else if(key=="GIRYA") {show=true;counter=runAux;}
        else if(key=="FISHING_ROD") {show=true;counter=aux%3;}
        else if(key=="PAELS_WING") {show=true;counter=rc.paelsWingSkips%2;}
        else if(key=="SWORD_OF_STONE") {show=true;counter=rc.swordOfStoneWins;}
        else if(key=="PUMPKIN_CANDLE") {show=true;counter=aux;disabled=counter<=0;}
        else if(key=="EMBER_TEA") {show=true;counter=std::max(0,rc.emberTeaCombats);disabled=counter==0;}
        else if(key=="BONE_TEA") disabled=aux<=0;
        else if(key=="TEA_OF_DISCOURTESY") disabled=rc.nextCombatDazed<=0;
        else if(key=="SILVER_CRUCIBLE") {counter=rc.silverCrucibleUses;show=counter>0;disabled=!show&&rc.treasureSkipped;}
        else if(key=="TOY_BOX") {disabled=rc.toyBoxCombats>=15;show=!disabled;counter=rc.toyBoxCombats%3;}
        else if(key=="WONGOS_MYSTERY_TICKET") {counter=std::max(0,5-rc.wongoCombats);show=counter>0;disabled=!show;}
        else if(key=="WINGED_BOOTS") {counter=std::max(0,3-aux);show=counter>0;disabled=!show;}
        else if(key=="PAELS_TOOTH") {counter=rc.paelsToothCount;show=counter>0;disabled=!show;}
        else if(key=="LIZARD_TAIL" || key=="SILKEN_TRESS") disabled=aux!=0;
        else if(key=="LAVA_ROCK") disabled=rc.lavaRockTriggered;
        else if(key=="MAW_BANK") disabled=rc.mawBankPurchased;
        else if(key=="BRILLIANT_SCARF") {counter=melted?0:b.manualCardsPlayedThisTurn;show=inCombat&&counter<5;active=live&&counter==4;}
        else if(key=="KUNAI" || key=="SHURIKEN" || key=="ORNAMENTAL_FAN" || key=="KUSARIGAMA") {
            show=inCombat;counter=relicFinishedAttacks%3;active=live&&counter==2;
        }
        else if(key=="LETTER_OPENER") {show=inCombat;counter=relicFinishedSkills%3;active=live&&counter==2;}
        else if(key=="POCKETWATCH") {show=inCombat;counter=relicFinishedCards;active=live&&counter<=3;}
        else if(key=="VELVET_CHOKER") {show=inCombat;counter=relicFinishedCards;}
        else if(key=="STONE_CALENDAR") {show=inCombat&&b.turn<7;counter=b.turn;active=live&&b.turn==7&&!b.inMonsterTurn;}
        else if(key=="PAELS_FLESH") {active=live&&b.turn>=3;show=live&&!active;counter=b.turn;}
        else if(key=="PAELS_LEGION") {show=inCombat&&aux>0;counter=aux;active=live&&aux<=0;}
        else if(key=="UNSETTLING_LAMP") active=live&&aux>=0;
        else if(key=="VAMBRACE" || key=="THROWING_AXE" || key=="BURNING_STICKS") active=live&&aux==0;
        else if(key=="PAELS_EYE") active=live&&aux==0&&b.manualCardsPlayedThisTurn==0&&!manualInFlight;
        else if(key=="ART_OF_WAR") active=live&&finishedAttacks==0;
        else if(key=="RIPPLE_BASIN") active=live&&!b.inMonsterTurn&&finishedAttacks==0;
        else if(key=="BELT_BUCKLE") active=live&&b.potionCount==0;
        else if(key=="MEAT_ON_THE_BONE" || key=="RED_SKULL") active=live&&b.player.hp<=b.player.maxHp/2;
        else if(key=="RAINBOW_RING") active=live&&aux>=8;
        else if(key=="VENERABLE_TEA_SET") active=rc.teaSetPending;
        else if(key=="FAKE_VENERABLE_TEA_SET") active=aux>0;
        else if(key=="REGAL_PILLOW") {
            const int node=rc.map.at(rc.curRow,rc.curCol);
            active=!melted && (rc.screen==RunScreen::REST || (node>=0&&rc.map.nodes[node].type==static_cast<int>(MapPointType::REST)));
        }
        else if(key=="PANTOGRAPH") {
            const int node=rc.map.at(rc.curRow,rc.curCol);
            if(!melted&&node>=0)for(int i=0;i<rc.map.nodes[node].childCount;++i)
                active|=rc.map.nodes[rc.map.nodes[node].children[i]].type==static_cast<int>(MapPointType::BOSS);
        }
        else if(key=="METRONOME") {show=inCombat&&aux<7;counter=std::min(aux,7);active=live&&aux==6;}
        else if(key=="GALACTIC_DUST" || key=="EMOTION_CHIP")
            throw std::logic_error("unsupported non-Ironclad relic public state: "+key);
        py::dict relic;
        relic["modelId"]=std::string("RELIC.")+key;relic["position"]=slot;
        relic["wax"]=inCombat?b.relicWax[slot]:rc.relicWax[slot];
        relic["melted"]=inCombat?b.relicMelted[slot]:rc.relicMelted[slot];
        relic["counterVisible"]=show;relic["counter"]=show?counter:0;
        relic["status"]=(melted||disabled)?"Disabled":active?"Active":"Normal";
        result.append(relic);
    }
    return result;
}
