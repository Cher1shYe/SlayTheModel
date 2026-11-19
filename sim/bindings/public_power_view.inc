// Visible power instances. Amount is the tooltip's effect amount; displayAmount
// is the number on the icon. Some native powers deliberately display a countdown.
static py::list public_power_view(const BattleContext &bc, int monsterIndex = -1) {
    py::list out;
    const auto add=[&](PowerId id,int amount,int display,const char*variable=nullptr,int value=0){
        py::dict p;py::list vars;p["id"]=static_cast<int>(id);p["amount"]=amount;p["displayAmount"]=display;
        if(variable){py::dict v;v["name"]=variable;v["value"]=value;v["enchantedValue"]=value;vars.append(v);}
        p["dynamicVars"]=vars;out.append(p);
    };
    for(int i=0;i<static_cast<int>(PowerId::COUNT);++i) {
        const auto id=static_cast<PowerId>(i);
        int amount=monsterIndex<0?bc.player_power(id):bc.monster_power(monsterIndex,id);
        if(!amount || id==PowerId::AMBERGRIS)continue; // native explicitly invisible
        if(monsterIndex<0 && (id==PowerId::THE_BOMB || id==PowerId::THE_BOMB_DAMAGE || id==PowerId::AUTOMATION ||
            id==PowerId::PANACHE || id==PowerId::ROLLING_BOULDER || id==PowerId::TORIC_TOUGHNESS ||
            id==PowerId::CACOPHONY || id==PowerId::MONOLOGUE || id==PowerId::ORBIT))continue;
        int display=amount;
        const char *variable=nullptr;int value=0;
        if(monsterIndex>=0){const auto&m=bc.monsters[monsterIndex];
            if(id==PowerId::SLOW){display=m.slowCardsThisTurn*10;variable="SlowAmount";value=m.slowCardsThisTurn;}
            if(id==PowerId::HARDENED_SHELL)display=std::max(0,amount-m.shellHpLostThisTurn);
            if(id==PowerId::WITHERING_PRESENCE){display=m.aux[2];variable="CardsLeft";value=m.aux[2];}
        } else {
            if(id==PowerId::FERAL)display=std::max(0,amount-bc.defect.feralReturnsThisTurn);
            if(id==PowerId::PALE_BLUE_DOT)display=std::max(0,5-bc.regent.cardsFinishedThisTurn);
            if(id==PowerId::TAG_TEAM)display=1;
            if(id==PowerId::TENDER)display=bc.tenderCardsPlayedThisTurn;
            if(id==PowerId::SLOTH)display=bc.slothCardsPlayedThisTurn;
            if(id==PowerId::CRIMSON_MANTLE){variable="SelfDamage";value=bc.player.crimsonMantleSelfDamage;}
            if(id==PowerId::INFERNO){variable="SelfDamage";value=bc.player.infernoSelfDamage;}
        }
        add(id,amount,display,variable,value);
    }
    if(monsterIndex<0){
        for(int i=0;i<bc.bombCount;++i)add(PowerId::THE_BOMB,bc.bombTurns[i],bc.bombTurns[i],"Damage",bc.bombDamage[i]);
        for(int i=0;i<bc.automationCount;++i)add(PowerId::AUTOMATION,bc.automationAmount[i],bc.automationLeft[i]);
        for(int i=0;i<bc.panacheCount;++i)add(PowerId::PANACHE,bc.panacheDamage[i],bc.panacheLeft[i]);
        for(int i=0;i<bc.rollingCount;++i)add(PowerId::ROLLING_BOULDER,bc.rollingDamage[i],bc.rollingDamage[i]);
        for(int i=0;i<bc.toricCount;++i)add(PowerId::TORIC_TOUGHNESS,bc.toricTurns[i],bc.toricTurns[i],"Block",bc.toricBlock[i]);
        for(int i=0;i<bc.necro.cacophonyCount;++i)add(PowerId::CACOPHONY,bc.necro.cacophonyDamage[i],bc.necro.cacophonyRemaining[i]);
        for(int i=0;i<bc.regent.monologueCount;++i)add(PowerId::MONOLOGUE,bc.regent.monologueAmounts[i],bc.regent.monologueApplied[i]);
        for(int i=0;i<bc.regent.orbitCount;++i)add(PowerId::ORBIT,bc.regent.orbitAmounts[i],4-bc.regent.orbitEnergy[i]%4);
    }
    return out;
}
