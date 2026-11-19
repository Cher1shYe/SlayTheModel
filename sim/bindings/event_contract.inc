// Native v0.111.0 EventOption.TextKey, audited against events.cpp state machines.
// Exports only the current public options; never export eventData wholesale.
static std::string native_model_slug(const char *key) {
    std::string out;
    for (std::size_t i=0;key[i];++i) {
        const unsigned char c=static_cast<unsigned char>(key[i]);
        if(i && c>='A' && c<='Z' && key[i-1]!='_') out+='_';
        out+= c>='a'&&c<='z' ? static_cast<char>(c-'a'+'A') : static_cast<char>(c);
    }
    return out;
}
// Explicit callback-to-description manifest. Every entry is a literal
// SetEventFinished (or its passed LocString) in the pinned native event source.
static std::string native_finished_event_page(const RunContext &rc, const std::string &event) {
    const int option = rc.eventLastOption, prior = rc.eventLastChoicePage;
    const auto page = [&](const std::string &suffix) { return event + ".pages." + suffix + ".description"; };
    struct Entry { const char *event; const char *pages[4]; };
    static const Entry exact[] = {
        {"AROMA_OF_CHAOS", {"LET_GO", "MAINTAIN_CONTROL"}},
        {"SUNKEN_STATUE", {"GRAB_SWORD", "DIVE_INTO_WATER"}},
        {"WELLSPRING", {"BOTTLE", "BATHE"}},
        {"UNREST_SITE", {"REST", "KILL"}},
        {"SAPPHIRE_SEED", {"EAT", "PLANT"}},
        {"THIS_OR_THAT", {"PLAIN", "ORNATE"}},
        {"ROOM_FULL_OF_CHEESE", {"GORGE", "SEARCH"}},
        {"POTION_COURIER", {"GRAB_POTIONS", "RANSACK"}},
        {"BRAIN_LEECH", {"SHARE_KNOWLEDGE", "RIP"}},
        {"STONE_OF_ALL_TIME", {"LIFT", "PUSH"}},
        {"HUNGRY_FOR_MUSHROOMS", {"BIG_MUSHROOM", "FRAGRANT_MUSHROOM"}},
        {"REFLECTIONS", {"TOUCH_A_MIRROR", "SHATTER"}},
        {"SPIRIT_GRAFTER", {"LET_IT_IN", "REJECTION"}},
        {"LOST_WISP", {"CLAIM", "SEARCH"}},
        {"AMALGAMATOR", {"COMBINE_STRIKES", "COMBINE_DEFENDS"}},
        {"BYRDONIS_NEST", {"EAT", "TAKE"}},
        {"BUGSLAYER", {"EXTERMINATION", "SQUASH"}},
        {"FIELD_OF_MAN_SIZED_HOLES", {"RESIST", "ENTER_YOUR_HOLE"}},
        {"GRAVE_OF_THE_FORGOTTEN", {"CONFRONT", "ACCEPT"}},
        {"INFESTED_AUTOMATON", {"STUDY", "TOUCH_CORE"}},
        {"JUNGLE_MAZE_ADVENTURE", {"SOLO_QUEST", "JOIN_FORCES"}},
        {"LUMINOUS_CHOIR", {"REACH_INTO_THE_FLESH", "OFFER_TRIBUTE"}},
        {"MORPHIC_GROVE", {"GROUP", "LONER"}},
        {"RANWID_THE_ELDER", {"POTION", "GOLD", "RELIC"}},
        {"SYMBIOTE", {"APPROACH", "KILL_WITH_FIRE"}},
        {"THE_LEGENDS_WERE_TRUE", {"NAB_THE_MAP", "SLOWLY_FIND_AN_EXIT"}},
        {"DROWNING_BEACON", {"BOTTLE", "CLIMB"}},
        {"SPIRALING_WHIRLPOOL", {"OBSERVE", "DRINK"}},
        {"SUNKEN_TREASURY", {"FIRST_CHEST", "SECOND_CHEST"}},
        {"DOORS_OF_LIGHT_AND_DARK", {"LIGHT", "DARK"}},
        {"TRASH_HEAP", {"DIVE_IN", "GRAB"}},
        {"WATERLOGGED_SCRIPTORIUM", {"BLOODY_INK", "TENTACLE_QUILL", "PRICKLY_SPONGE"}},
        {"WHISPERING_HOLLOW", {"GOLD", "HUG"}},
        {"WOOD_CARVINGS", {"SNAKE", "BIRD", "TORUS"}},
        {"ZEN_WEAVER", {"BREATHING_TECHNIQUES", "EMOTIONAL_AWARENESS", "ARACHNID_ACUPUNCTURE"}},
    };
    for (const auto &entry : exact) if (event == entry.event && option >= 0 && option < 4 && entry.pages[option])
        return page(entry.pages[option]);
    if (event == "NEOW") {
        // Pinned native AncientEventModel.RelicOption<T> drops customDonePage
        // when delegating, so Neow's POSITIVE/CURSED arguments never reach UI.
        return page("DONE");
    }
    if (event == "DARV" || event == "OROBAS" || event == "PAEL" || event == "TEZCATARA" ||
        event == "NONUPEIPE" || event == "TANX" || event == "VAKUU" || event == "COLORFUL_PHILOSOPHERS" ||
        event == "RELIC_TRADER" || event == "THE_FUTURE_OF_POTIONS" || event == "TINKER_TIME") return page("DONE");
    if (event == "CRYSTAL_SPHERE") return page("FINISH");
    if (event == "TRIAL") return "TRIAL.trialResult";
    if (event == "BATTLEWORN_DUMMY") return page(rc.battle.battlewornRanOutOfTime ? "DEFEAT" : "VICTORY");
    if (event == "SLIPPERY_BRIDGE") return page("OVERCOME");
    if (event == "DENSE_VEGETATION" && prior == 0 && option == 0) return page("TRUDGE_ON");
    if (event == "PUNCH_OFF" && prior == 0 && option == 0) return page("NAB");
    if (event == "THE_LANTERN_KEY" && prior == 0 && option == 0) return page("DONE.options.RETURN_THE_KEY");
    if (event == "ROUND_TEA_PARTY") return page(prior == 0 ? "ENJOY_TEA" : "CONTINUE_FIGHT");
    if (event == "ABYSSAL_BATHS") return page(prior == 0 ? "ABSTAIN" : "EXIT_BATHS");
    if (event == "TABLET_OF_TRUTH") return page(option == 0 ? "DECIPHER_" + std::to_string(rc.eventData[0]) : prior == 0 ? "SMASH" : "GIVE_UP");
    if (event == "COLOSSAL_FLOWER") return page(prior < 2 ? "EXTRACT_CURRENT_PRIZE" : option == 0 ? "EXTRACT_INSTEAD" : "POLLINOUS_CORE");
    if (event == "ENDLESS_CONVEYOR") return page(prior == 0 ? "OBSERVE_CHEF" : "LEAVE");
    if (event == "SELF_HELP_BOOK") {
        const char *suffixes[] = {"READ_THE_BACK", "READ_PASSAGE", "READ_ENTIRE_BOOK"};
        if (rc.eventLastChoiceCount == 1) return page("NO_OPTIONS");
        if (option >= 0 && option < 3) return page(suffixes[option]);
    }
    if (event == "TEA_MASTER") return page(option == 2 ? "TEA_OF_DISCOURTESY" : "DONE");
    if (event == "WAR_HISTORIAN_REPY") {
        if (prior == 0) return page(option == 0 ? "UNLOCK_CAGE" : "UNLOCK_CHEST");
        return page(rc.eventData[0] == 0 ? "EXTRA_UNLOCK_CAGE" : "EXTRA_UNLOCK_CHEST");
    }
    if (event == "DOLL_ROOM") {
        const auto relic = static_cast<RelicId>(rc.eventLastRelic);
        if (relic == RelicId::DAUGHTER_OF_THE_WIND) return page("DAUGHTER_OF_WIND");
        if (relic == RelicId::MR_STRUGGLES) return page("MR_STRUGGLES");
        if (relic == RelicId::BING_BONG) return page("FABLE");
    }
    if (event == "WELCOME_TO_WONGOS") {
        if (option == 3) return page("LEAVE");
        const int earned[] = {32,16,8};
        if (option >= 0 && option < 3) {
            const int points = rc.nativeProgress.wongoPoints;
            return page(points % 2000 + earned[option] >= 2000 ? "AFTER_BUY_RECEIVE_BADGE" :
                (points + earned[option]) / 2000 > 0 ? "AFTER_BUY_BADGE_COUNTER" : "AFTER_BUY");
        }
    }
    throw std::logic_error("No native finished event description for " + event);
}

static void bind_event_contract(py::module_ &m) {
    m.def("event_page_key", [](const RunContext &rc) -> py::object {
        if (rc.screen != RunScreen::EVENT) return py::none();
        const auto *info = event_info(rc.eventId); if (!info) return py::none();
        const std::string event = info->name;
        const auto page = [&](const std::string &suffix) -> py::object {
            return py::cast(event + ".pages." + suffix + ".description");
        };
        if (rc.eventPage == 0) return page("INITIAL");
        if (rc.eventPage == 127) return py::cast(native_finished_event_page(rc, event));
        if (rc.eventPage == 1) {
            if (event == "DENSE_VEGETATION") return page("REST");
            if (event == "THE_LANTERN_KEY") return page("KEEP_THE_KEY");
            if (event == "PUNCH_OFF") return page("I_CAN_TAKE_THEM");
            if (event == "ROUND_TEA_PARTY") return page("PICK_FIGHT");
            if (event == "TINKER_TIME") return page("CHOOSE_CARD_TYPE");
            if (event == "TRIAL") return page("REJECT");
            if (event == "ENDLESS_CONVEYOR") return page("GRAB_SOMETHING_OFF_THE_BELT");
            if (event == "DOLL_ROOM") return page(rc.eventChoiceCount == 2 ? "TAKE_SOME_TIME" : "EXAMINE");
            if (event == "WAR_HISTORIAN_REPY") return page(rc.eventData[0] == 1 ? "UNLOCK_CAGE" : "UNLOCK_CHEST");
            if (event == "TABLET_OF_TRUTH") return page("DECIPHER_" + std::to_string(rc.eventData[0]));
            if (event == "SLIPPERY_BRIDGE") return page("HOLD_ON_" +
                (rc.eventData[0] - 1 >= 7 ? std::string("LOOP") : std::to_string(rc.eventData[0] - 1)));
            if (event == "ABYSSAL_BATHS") {
                const int linger = rc.eventData[0] - 4;
                if (linger <= 0) return page("IMMERSE");
                if (rc.hp <= rc.eventData[0] - 2) return page("DEATH_WARNING");
                return page("LINGER" + std::to_string(std::min(9, linger)));
            }
        }
        if (event == "COLOSSAL_FLOWER" && rc.eventPage >= 1 && rc.eventPage <= 2)
            return page("REACH_DEEPER_" + std::to_string(rc.eventData[0]));
        if (event == "TINKER_TIME" && rc.eventPage == 2) return page("CHOOSE_RIDER");
        if (event == "TRIAL" && rc.eventPage == 2) return py::cast("TRIAL.trialFormat");
        // Unknown nonterminal pages never inherit INITIAL.
        return py::none();
    });
    m.def("event_option_keys", [](const RunContext &rc) {
        std::vector<std::string> keys;
        if(rc.screen!=RunScreen::EVENT || rc.eventCardSelection || rc.cardGrid.kind) return keys;
        const auto *info=event_info(rc.eventId); if(!info) return keys;
        const std::string event=info->name;
        keys.resize(rc.eventChoiceCount);
        const auto key=[&](const std::string &page,const std::string &option) {
            return event+".pages."+page+".options."+option;
        };
        const auto assign=[&](int index,const std::string &value) {
            if(index>=0 && index<static_cast<int>(keys.size())) keys[index]=value;
        };
        if(rc.eventPage==127) return keys; // explicit Proceed is handled separately
        if(event=="NEOW" || event=="DARV" || event=="OROBAS" || event=="PAEL" ||
           event=="TEZCATARA" || event=="NONUPEIPE" || event=="TANX" || event=="VAKUU") {
            for(int i=0;i<rc.eventChoiceCount;++i)
                if(rc.eventRelics[i]>0) assign(i,key("INITIAL",relic_def(static_cast<RelicId>(rc.eventRelics[i])).key));
        } else if(event=="TABLET_OF_TRUTH" && rc.eventPage==1) {
            assign(0,key("DECIPHER_"+std::to_string(rc.eventData[0]),"DECIPHER"));
            assign(1,key("DECIPHER","GIVE_UP"));
        } else if(event=="SLIPPERY_BRIDGE" && rc.eventPage==1) {
            const auto suffix=[](int n){return n>=7?std::string("LOOP"):std::to_string(n);};
            assign(0,key("INITIAL","OVERCOME"));
            assign(1,key("HOLD_ON_"+suffix(rc.eventData[0]-1),"HOLD_ON_"+suffix(rc.eventData[0])));
        } else if(event=="COLOSSAL_FLOWER" && rc.eventPage<=2) {
            const int digs=rc.eventData[0];
            if(digs==2) {assign(0,key("REACH_DEEPER_2","EXTRACT_INSTEAD"));assign(1,key("REACH_DEEPER_2","POLLINOUS_CORE"));}
            else if(digs>=0 && digs<2) {
                const auto page=digs==0?std::string("INITIAL"):"REACH_DEEPER_"+std::to_string(digs);
                assign(0,key(page,"EXTRACT_CURRENT_PRIZE_"+std::to_string(digs+1)));
                assign(1,key(page,"REACH_DEEPER_"+std::to_string(digs+1)));
            }
        } else if(event=="TRIAL" && rc.eventPage==2 && rc.eventData[0]>=0 && rc.eventData[0]<3) {
            const char *cases[]={"MERCHANT","NOBLE","NONDESCRIPT"};
            assign(0,key(cases[rc.eventData[0]],"GUILTY"));assign(1,key(cases[rc.eventData[0]],"INNOCENT"));
        } else if(event=="TINKER_TIME" && rc.eventPage==1) {
            const char *types[]={"","ATTACK","SKILL","POWER"};
            for(int i=0;i<2;++i) if(rc.eventData[i]>=1&&rc.eventData[i]<=3) assign(i,key("CHOOSE_CARD_TYPE",types[rc.eventData[i]]));
        } else if(event=="TINKER_TIME" && rc.eventPage==2) {
            const char *riders[]={"","SAPPING","VIOLENCE","CHOKING","ENERGIZED","WISDOM","CHAOS","EXPERTISE","CURIOUS","IMPROVEMENT"};
            for(int i=0;i<2;++i) if(rc.eventData[i+2]>=1&&rc.eventData[i+2]<=9) assign(i,key("CHOOSE_RIDER",riders[rc.eventData[i+2]]));
        } else if(event=="ENDLESS_CONVEYOR" && rc.eventPage<=1) {
            const char *dishes[]={"CAVIAR","SPICY_SNAPPY","JELLY_LIVER","FRIED_EEL","SUSPICIOUS_CONDIMENT","CLAM_ROLL","GOLDEN_FYSH","SEAPUNK_SALAD"};
            if(rc.eventData[1]>=0&&rc.eventData[1]<8) assign(0,key("ALL",dishes[rc.eventData[1]]));
            assign(1,key(rc.eventPage==0?"INITIAL":"GRAB_SOMETHING_OFF_THE_BELT",rc.eventPage==0?"OBSERVE_CHEF":"LEAVE"));
        } else if(event=="COLORFUL_PHILOSOPHERS" && rc.eventPage==0) {
            for(int i=0;i<rc.eventChoiceCount;++i) {
                const auto pool=static_cast<CardPool>(rc.eventData[i]); const char *name=nullptr;
                switch(pool) {case CardPool::IRONCLAD:name="IRONCLAD";break;case CardPool::SILENT:name="SILENT";break;
                    case CardPool::REGENT:name="REGENT";break;case CardPool::NECROBINDER:name="NECROBINDER";break;
                    case CardPool::DEFECT:name="DEFECT";break;default:break;}
                if(name) assign(i,key("INITIAL",name));
            }
        } else if(event=="RELIC_TRADER" && rc.eventPage==0) {
            if(rc.eventData[3]==0) assign(0,"PROCEED");
            else {const char *choices[]={"TOP","MIDDLE","BOTTOM"};for(int i=0;i<3;++i)assign(i,key("INITIAL",choices[i]));}
        } else if(event=="DOLL_ROOM" && rc.eventPage==1) {
            for(int i=0;i<rc.eventChoiceCount;++i) if(rc.eventRelics[i]>0)
                assign(i,"DOLL_ROOM.choice.RELIC."+std::string(relic_def(static_cast<RelicId>(rc.eventRelics[i])).key));
        } else if(event=="THE_FUTURE_OF_POTIONS" && rc.eventPage==0) {
            int option=0; const char *types[]={"ATTACK","SKILL","POWER"};
            for(int slot=0;slot<rc.potionSlots&&option<rc.eventChoiceCount;++slot) if(rc.potions[slot]) {
                int type=rc.eventData[option];
                if(type>=0&&type<=2)assign(option,key("INITIAL","POTION")+"@"+std::to_string(slot)+":POTION."+
                    native_model_slug(potion_def(static_cast<PotionId>(rc.potions[slot])).key)+":"+types[type]);
                ++option;
            }
        } else if(event=="WAR_HISTORIAN_REPY" && rc.eventPage==1) {
            assign(0,key("INITIAL",rc.eventData[0]==0?"UNLOCK_CAGE":"UNLOCK_CHEST"));
        } else if(event=="FAKE_MERCHANT" && rc.eventPage==0) {
            for(int i=0;i<6;++i) if(rc.eventRelics[i]>0) assign(i,"BUY_RELIC:"+
                std::string(relic_def(static_cast<RelicId>(rc.eventRelics[i])).key)+":"+std::to_string(rc.eventData[i]));
            assign(6,"LEAVE_SHOP");
        }
        return keys;
    });
}
