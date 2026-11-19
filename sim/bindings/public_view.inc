// Explicit public-state export used by the shared simulator/native policy encoder.
// Included after the binding helpers; never export a RunContext/Monster memory dump.
#include <cctype>
#include "sts2/card_candidates.h"
#include "public_power_view.inc"
#include "public_relic_view.inc"
static std::string public_native_slug(const char *name) {
    std::string result;
    for(int i=0;name[i];++i){const unsigned char c=name[i];if(i>0&&c>='A'&&c<='Z')result+='_' ;result+=static_cast<char>(std::toupper(c));}
    return result;
}
static py::dict public_card_view(const Card &c, const char *pile, int position,
                                 const BattleContext *battle = nullptr) {
    const auto &def = card_def(c.id);
    py::dict out;
    out["transportId"] = std::to_string(c.uid); // routing only; encoder removes it
    out["modelId"] = std::string("CARD.") + card_key(c.id);
    out["pile"] = pile;
    out["position"] = position >= 0 ? py::cast(position) : py::none();
    out["upgrade"] = c.upgraded ? 1 : 0;
    out["maxUpgrade"] = def.maxUpgradeLevel;
    out["type"] = static_cast<int>(card_type(c));
    out["rarity"] = static_cast<int>(def.rarity);
    out["target"] = static_cast<int>(card_target(c));
    out["costX"] = card_cost(c) < 0;
    out["cost"] = card_cost(c) < 0 ? -1 : battle ? battle->energy_cost_in_combat(c) : card_cost(c);
    out["baseCost"] = c.costThisTurn ? c.storedCost : c.costForTurn;
    out["localCost"] = card_cost(c);
    out["damage"] = card_base_damage(c);
    out["block"] = card_block(c);
    out["bonusDamage"] = c.bonusDamage;out["bonusBlock"] = c.bonusBlock;
    out["replay"] = c.replay + c.bonusReplay;
    out["enchantedReplay"] = c.replay + c.bonusReplay +
        ((c.enchantment == EnchantmentId::SPIRAL || (c.enchantment == EnchantmentId::GLAM && !c.enchantmentDisabled)) ? 1 : 0);
    out["exhaustOnNextPlay"] = battle && battle->activePlay.active && battle->activePlay.card.uid == c.uid && battle->activePlay.forceExhaust;
    out["progress"] = c.guiltyCombatsSeen;
    out["tinkerRider"] = c.tinkerRider;
    out["starCost"] = c.upgraded ? def.starCostUp : def.starCost;
    out["starCostX"] = c.upgraded ? def.starCostXUp : def.starCostX;
    out["dampened"] = c.dampened;
    py::list keywords,localKeywords;
    Card local=c;local.retainThisTurn=false;local.slyThisTurn=false;
    for (const auto &flag : std::vector<std::pair<int, const char *>>{
        {CF_EXHAUST,"Exhaust"},{CF_ETHEREAL,"Ethereal"},{CF_INNATE,"Innate"},
        {CF_UNPLAYABLE,"Unplayable"},{CF_RETAIN,"Retain"},{CF_SLY,"Sly"},{CF_ETERNAL,"Eternal"}})
        if (card_has(local, flag.first)) {keywords.append(flag.second);localKeywords.append(flag.second);}
    if(battle && c.hexed && battle->player_power(PowerId::HEX)>0 && !card_has(local,CF_ETHEREAL))keywords.append("Ethereal");
    out["keywords"] = keywords;
    out["localKeywords"] = localKeywords;
    out["retain"] = card_has(c, CF_RETAIN);
    out["retainThisTurn"] = c.retainThisTurn;
    out["slyThisTurn"] = c.slyThisTurn;
    py::list modifiers;
    for (int i = 0; i < c.costModifierCount; ++i) {
        const auto &mod = c.costModifiers[i];
        py::dict row;
        row["amount"] = mod.amount; row["absolute"] = mod.absolute;
        row["expiration"] = mod.expiration; row["reduceOnly"] = mod.reduceOnly;
        modifiers.append(row);
    }
    // Legacy scalar changes carry the same public duration semantics. freeCombat
    // is a bookkeeping flag: the actual modifier is already in costModifiers.
    if (c.combatCostCap >= 0) {
        py::dict row; row["amount"]=c.combatCostCap; row["absolute"]=true; row["expiration"]=0; row["reduceOnly"]=true;
        modifiers.insert(0, row);
    }
    if (c.costThisTurn) {
        py::dict row; row["amount"]=c.costForTurn; row["absolute"]=true; row["expiration"]=2; row["reduceOnly"]=false;
        modifiers.insert(0, row);
    }
    out["costModifiers"] = modifiers;
    py::dict enchantment;
    enchantment["id"] = static_cast<int>(c.enchantment);
    enchantment["amount"] = c.enchantmentAmount;
    enchantment["disabled"] = c.enchantmentDisabled;
    enchantment["extraDamage"] = c.momentumExtraDamage;
    out["enchantment"] = enchantment;
    py::list afflictions;
    for (const auto &aff : std::vector<std::pair<const char *, int>>{
        {"BOUND", c.bound ? 1 : 0}, {"GALVANIZED",c.galvanized},{"TAINTED",c.tainted},{"HEXED",c.hexed ? 1 : 0}})
        if (aff.second) { py::dict row; row["modelId"] = std::string("AFFLICTION.")+aff.first;
            row["amount"]=aff.second; afflictions.append(row); }
    out["afflictions"] = afflictions;
    return out;
}

static py::dict public_model_state(const RunContext &rc) {
    const bool inCombat = rc.screen == RunScreen::COMBAT;
    const auto &bc = rc.battle;
    py::dict out, player, run, combat;
    out["version"] = 1;
    player["hp"] = inCombat ? bc.player.hp : rc.hp;
    player["maxHp"] = inCombat ? bc.player.maxHp : rc.maxHp;
    player["block"] = inCombat ? bc.player.block : 0;
    player["gold"] = inCombat ? bc.gold : rc.gold;
    player["energy"] = inCombat ? bc.player.energy : 0;
    player["maxEnergy"] = inCombat ? bc.player.energyPerTurn : 0;
    player["stars"] = inCombat ? bc.regent.stars : 0;
    player["potionSlots"] = inCombat ? bc.potionSlots : rc.potionSlots;
    py::list powers=inCombat?public_power_view(bc):py::list();
    player["powers"]=powers;
    out["player"]=player;
    run["act"]=rc.act;run["floor"]=rc.floor;run["actFloor"]=rc.actFloor;run["ascension"]=rc.ascension;
    run["combatsFought"]=rc.combatsFought;run["elitesFought"]=rc.elitesFought;run["bossesFought"]=rc.bossesFought;
    run["cardShopRemovalsUsed"]=rc.cardShopRemovalsUsed;run["unknownMapPointsVisited"]=rc.unknownMapPointsVisited;
    const char *acts[]={"ACT.OVERGROWTH","ACT.HIVE","ACT.GLORY","ACT.UNDERDOCKS"};
    run["currentAct"]=acts[static_cast<int>(rc.actTypes[rc.act])];
    run["boss"]=std::string("ENCOUNTER.")+encounter_native_entry(static_cast<Encounter>(rc.bossEncounter));
    run["secondBoss"]=rc.secondBossEncounter>=0 ? py::cast(std::string("ENCOUNTER.")+encounter_native_entry(static_cast<Encounter>(rc.secondBossEncounter))) : py::none();
    out["run"]=run;
    if (inCombat) {
        combat["turn"]=bc.turn;combat["round"]=bc.combatRound;
        combat["cardsPlayedTurn"]=bc.cardsPlayedThisTurn;combat["attacksPlayedTurn"]=bc.attacksPlayedThisTurn;
        combat["skillsPlayedTurn"]=bc.skillsPlayedThisTurn;combat["cardsPlayedCombat"]=bc.cardsPlayedThisCombat;
        combat["cardsFinishedCombat"]=bc.cardsFinishedThisCombat;combat["cardsExhaustedTurn"]=bc.exhaustedThisTurn;
        combat["manualCardsPlayedTurn"]=bc.manualCardsPlayedThisTurn;
        combat["unblockedHitsCombat"]=bc.unblockedHitsThisCombat;combat["hpLostTurn"]=bc.hpLostThisTurn;
        out["combat"]=combat;
    } else out["combat"]=py::none();
    py::list cards;
    const auto addCards=[&](const Card *pile,int count,const char *name,bool ordered,const BattleContext *b) {
        std::vector<const Card *> visible;
        for(int i=0;i<count;++i)visible.push_back(&pile[i]);
        if(!ordered)std::sort(visible.begin(),visible.end(),[](const Card*a,const Card*b){return card_canonical_less(*a,*b);});
        for(int i=0;i<count;++i)cards.append(public_card_view(*visible[i],name,ordered?i:-1,b));
    };
    addCards(rc.deck,rc.deckCount,"deck",false,nullptr);
    if(inCombat) {
        addCards(bc.hand,bc.handCount,"hand",true,&bc);
        addCards(bc.draw,bc.drawCount,"draw",false,&bc);
        addCards(bc.discard,bc.discardCount,"discard",false,&bc);
        addCards(bc.exhaust,bc.exhaustCount,"exhaust",false,&bc);
        addCards(bc.playPile,bc.playCount,"play",false,&bc);
        if(bc.activePlay.active)cards.append(public_card_view(bc.activePlay.card,"play",-1,&bc));
        for(int i=0;i<bc.suspendedPlayCount;++i)if(bc.suspendedPlays[i].play.active)
            cards.append(public_card_view(bc.suspendedPlays[i].play.card,"play",-1,&bc));
        // Known top positions are intentional public memory, not an inspection of hidden order.
        py::list knownTop;
        for(int i=0;i<std::min(bc.knownTopCount,bc.drawCount);++i)
            knownTop.append(public_card_view(bc.draw[bc.drawCount-1-i],"knownTop",i,&bc));
        out["knownTop"]=knownTop;
    } else out["knownTop"]=py::list();
    out["cards"]=cards;
    py::list choices;
    if(inCombat && bc.pending.count) {
        for(int i=0;i<bc.pending.count;++i){auto c=public_card_view(bc.pending.cards[i],"choice",i,&bc);
            bool selected=false;for(int j=0;j<bc.pending.selectedCount;++j)selected|=bc.pending.selectedUids[j]==bc.pending.cards[i].uid;
            c["selected"]=selected;choices.append(c);}
    } else if(rc.cardGrid.kind) {
        // The event contract supplies candidate positions. Deck candidates keep
        // their public card identity, not an internal acquisition-order feature.
        const int kind=rc.cardGrid.kind;
        const bool own=kind==1||kind==2||kind==5||kind==13||kind==14||kind==16;
        const int n=own?rc.cardGrid.count:rc.deckCount;
        for(int i=0;i<n;++i){
            if(!own && !(kind==22?event_card_selectable(rc,i):card_eligible_for_deck_choice(rc.deck[i],kind,rc.cardGrid.filter)))continue;
            auto c=public_card_view(own?rc.cardGrid.cards[i]:rc.deck[i],"choice",i);
            c["selected"]=rc.cardGrid.selected[i];choices.append(c);}
    } else if(rc.screen==RunScreen::CARD_REWARD) {
        for(int i=0;i<rc.offeredCount;++i)choices.append(public_card_view(rc.offered[i],"offer",i));
    } else if(rc.screen==RunScreen::SHOP) {
        for(int i=0;i<rc.shopCount;++i){if(rc.shopSold[i])continue;auto c=public_card_view(rc.shopCards[i],"offer",i);
            c["price"]=rc.shopPrices[i];c["sold"]=rc.shopSold[i];choices.append(c);}
    }
    out["choices"]=choices;
    py::list offers;
    const auto legal=rc.legal_actions();
    const auto can=[&](RunActionType type,int index){for(const auto&a:legal)if(a.type==type&&a.index==index)return true;return false;};
    const auto offer=[&](const char*kind,py::object id,py::object amount,bool recovered,int price,bool available){py::dict d;
        d["kind"]=kind;d["modelId"]=id;d["amount"]=amount;d["recovered"]=recovered;d["price"]=price;d["available"]=available;offers.append(d);};
    const auto relicId=[](int id){return py::cast(std::string("RELIC.")+relic_def(static_cast<RelicId>(id)).key);};
    const auto potionId=[](int id){return py::cast(std::string("POTION.")+public_native_slug(potion_def(static_cast<PotionId>(id)).key));};
    if(rc.screen==RunScreen::REWARDS){
        if(rc.pendingGoldReward>0)offer("GoldReward",py::none(),py::cast(rc.pendingGoldReward),false,-1,can(RunActionType::TAKE_GOLD_REWARD,0));
        if(rc.pendingRecoveredGold>0)offer("GoldReward",py::none(),py::cast(rc.pendingRecoveredGold),true,-1,can(RunActionType::TAKE_GOLD_REWARD,1));
        for(int i=0;i<MAX_EXTRA_GOLD_REWARDS;++i)if(rc.extraGoldRewards[i]>0)offer("GoldReward",py::none(),py::cast(rc.extraGoldRewards[i]),false,-1,can(RunActionType::TAKE_GOLD_REWARD,2+i));
        for(int i=0;i<rc.pendingPotionCount;++i)if(rc.pendingPotions[i])offer("PotionReward",potionId(rc.pendingPotions[i]),py::none(),false,-1,can(RunActionType::TAKE_POTION_REWARD,i));
        for(int i=0;i<rc.pendingRelicCount;++i)if(!rc.pendingRelicClaimed[i])offer("RelicReward",relicId(rc.pendingRelics[i]),py::none(),false,-1,can(RunActionType::TAKE_RELIC_REWARD,i));
        for(int i=0;i<MAX_CARD_REWARDS;++i)if(rc.rewardCardPending[i])offer("CardReward",py::none(),py::none(),false,-1,can(RunActionType::OPEN_CARD_REWARD,i));
        for(int i=0;i<rc.pendingCardRemovals;++i)offer("CardRemovalReward",py::none(),py::none(),false,-1,can(RunActionType::OPEN_CARD_REMOVAL_REWARD,i));
        const auto special=[&](const Card &card,int index,RunActionType type){auto c=public_card_view(card,"offer",-1);choices.append(c);
            offer("SpecialCardReward",py::cast(std::string("CARD.")+card_key(card.id)),py::none(),false,-1,can(type,index));};
        for(int i=0;i<MAX_SPECIAL_CARD_REWARDS;++i)if(rc.specialRewardPending[i])special(rc.specialRewardCards[i],i,RunActionType::TAKE_SPECIAL_CARD_REWARD);
        for(int i=0;i<rc.stolenSyncCount;++i)if(rc.stolenRewardPending[i])special(rc.stolenOriginals[i],i,RunActionType::TAKE_STOLEN_CARD_REWARD);
    }else if(rc.screen==RunScreen::SHOP){
        for(int i=0;i<rc.shopRelicCount;++i)if(!rc.shopRelicSold[i])offer("MerchantRelicEntry",relicId(rc.shopRelics[i]),py::none(),false,rc.shopRelicPrices[i],can(RunActionType::BUY_RELIC,i));
        for(int i=0;i<rc.shopPotionCount;++i)if(!rc.shopPotionSold[i])offer("MerchantPotionEntry",potionId(rc.shopPotions[i]),py::none(),false,rc.shopPotionPrices[i],can(RunActionType::BUY_POTION,i));
        if(!rc.removalUsed)offer("MerchantCardRemovalEntry",py::none(),py::none(),false,rc.removalPrice,can(RunActionType::REMOVE_CARD,0));
    }
    out["offers"]=offers;
    py::object decision=py::none();
    if(inCombat && bc.pending.op!=ChoiceOp::NONE){py::dict d;
        d["minSelect"]=bc.pending.optional?0:std::min(bc.pending.remaining,bc.pending.count);
        d["maxSelect"]=std::min(bc.pending.remaining,bc.pending.count);
        d["requireManualConfirmation"]=bc.pending.pile==ChoicePile::HAND;
        d["preview"]=false;d["cancelable"]=false;d["selectedCount"]=bc.pending.selectedCount;decision=d;
    }else if(rc.cardGrid.kind){py::dict d;d["minSelect"]=rc.cardGrid.minSelect;d["maxSelect"]=rc.cardGrid.maxSelect;
        d["requireManualConfirmation"]=true;d["preview"]=rc.cardGrid.preview;d["cancelable"]=rc.cardGrid.service!=0;
        d["selectedCount"]=rc.cardGrid.selectedCount;decision=d;}
    out["decision"]=decision;
    out["board"]=py::none();
    if(rc.crystalSphere.active){const auto &g=rc.crystalSphere;py::dict board;py::list cells;
        board["width"]=CRYSTAL_SPHERE_SIZE;board["height"]=CRYSTAL_SPHERE_SIZE;
        board["remaining"]=g.divinations;board["finished"]=g.divinations<=0;
        const char *types[]={"CrystalSphereRelic","CrystalSpherePotion","CrystalSpherePotion",
            "CrystalSphereCardReward","CrystalSphereCardReward","CrystalSphereCardReward","CrystalSphereCurse",
            "CrystalSphereGold","CrystalSphereGold"};
        for(int cell=0;cell<CRYSTAL_SPHERE_CELLS;++cell){py::dict c;
            const bool hidden=(g.hidden[cell/64]>>(cell%64))&1;
            const int item=hidden?-1:g.cellItem[cell]-1;bool complete=false;
            if(item>=0)for(int i=0;i<g.revealedCount;++i)complete|=g.revealed[i]==item;
            c["x"]=cell/CRYSTAL_SPHERE_SIZE;c["y"]=cell%CRYSTAL_SPHERE_SIZE;c["hidden"]=hidden;
            c["fragment"]=item>=0;c["revealedItem"]=complete?py::cast(types[g.itemType[item]]):py::none();c["revealedReward"]=py::none();
            if(complete){const int t=g.itemType[item];py::dict reward;reward["kind"]=types[t];
                reward["rarity"]=(t==1||t==3)?py::cast("Common"):(t==2||t==5)?py::cast("Rare"):t==4?py::cast("Uncommon"):py::none();
                reward["amount"]=t==7?py::cast(10):t==8?py::cast(30):py::none();c["revealedReward"]=reward;}
            cells.append(c);}
        board["cells"]=cells;out["board"]=board;}
    py::list map;
    const auto coordinate=[&](int index){py::dict point;for(int row=0;row<MAP_MAX_ROWS;++row)for(int col=0;col<MAP_WIDTH;++col)
        if(rc.map.index[row][col]==index){point["row"]=row;point["col"]=col;return point;}throw std::logic_error("map node lacks coordinate");};
    for(int i=0;i<rc.map.pointCount;++i){auto point=coordinate(i);const auto&node=rc.map.nodes[i];
        point["type"]=static_cast<int>(node.type);point["visited"]=i<64?((rc.visitedLo>>i)&1)!=0:((rc.visitedHi>>(i-64))&1)!=0;
        point["current"]=rc.map.at(rc.curRow,rc.curCol)==i;py::list children,quests;
        for(int j=0;j<node.childCount;++j)children.append(coordinate(node.children[j]));
        if(py::cast<int>(point["row"])==rc.spoilsQuestRow && py::cast<int>(point["col"])==rc.spoilsQuestCol)quests.append("CARD.SPOILS_MAP");
        point["children"]=children;point["quests"]=quests;map.append(point);}
    out["map"]=map;
    py::list enemies;
    const auto slots=native_encounter_slots(bc.encounter);
    const auto order=public_monster_turn_order(bc);
    if(inCombat)for(int k=0;k<static_cast<int>(order.size());++k) {
        const int i=order[k]; const auto&m=bc.monsters[i];py::dict e;py::list ep;
        e["modelId"]=std::string("MONSTER.")+native_monster_entry(bc,m);e["order"]=k;
        e["transportId"]=std::to_string(i);e["slotName"]=m.orderKey>=0 && m.orderKey<static_cast<int>(slots.size()) ? py::cast(slots[m.orderKey]) : py::none();
        e["hp"]=m.hp;e["maxHp"]=m.maxHp;e["block"]=m.block;
        e["intentType"]=m.intentType;e["intentDamage"]=m.intentDamage;e["intentHits"]=m.intentHits;
        py::list intents;
        for(const auto &intent:visible_monster_intents(bc,i)){py::dict row;row["type"]=intent.type;row["damage"]=intent.damage;row["hits"]=intent.hits;intents.append(row);}
        e["intents"]=intents;e["intentsVisible"]=true;
        e["reviving"]=m.reviving;e["slowCardsThisTurn"]=m.slowCardsThisTurn;
        e["alive"]=m.alive && m.hp>0;e["hittable"]=m.alive && !m.reviving && m.hp>0;
        e["powers"]=public_power_view(bc,i);enemies.append(e);
    }
    out["enemies"]=enemies;
    out["relics"]=public_relic_view(rc,inCombat);
    py::list potions;
    const int pcount=inCombat?bc.potionSlots:rc.potionSlots;
    for(int i=0;i<pcount;++i){const int id=inCombat?bc.potions[i]:rc.potions[i];py::dict p;p["slot"]=i;
        p["modelId"]=id?py::cast(std::string("POTION.")+public_native_slug(potion_def(static_cast<PotionId>(id)).key)):py::none();
        bool queued=false,disabled=false;if(inCombat)for(int q=0;q<bc.queuedPotionActionCount;++q)if(bc.queuedPotionActions[q].hand==i){
            disabled=true;queued=bc.queuedPotionActions[q].type==ActionType::USE_POTION;}
        p["queued"]=queued;p["disabledUntilRemoved"]=disabled;potions.append(p);}
    out["potions"]=potions;
    return out;
}

static void bind_public_view(py::module_ &m) {
    m.def("public_model_state", &public_model_state,
          "Public policy facts; IDs are routing metadata. Hidden piles are unordered multisets.");
    m.def("pending_extra_gold_rewards", [](const RunContext &rc) {
        return std::vector<int>(std::begin(rc.extraGoldRewards), std::end(rc.extraGoldRewards));
    });
}
