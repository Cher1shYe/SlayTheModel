#pragma once
#include "sts2/battle.h"
namespace sts2 {
bool regent_effect(BattleContext&,Card&,int);
bool regent_resume_effect(BattleContext&);
bool regent_resolve_choice(BattleContext&,std::uint16_t);
void regent_finish_choice(BattleContext&,ChoiceOp);
void regent_gain_stars(BattleContext&,int);
void regent_forge(BattleContext&,int);
void regent_generate_colorless(BattleContext&,int,bool upgraded=false);
void regent_reset_turn(BattleContext&);
void regent_after_energy_reset(BattleContext&);
void regent_before_hand_draw(BattleContext&);
void regent_after_player_turn_start(BattleContext&);
void regent_after_side_turn_start(BattleContext&);
void regent_player_turn_end(BattleContext&);
void regent_enemy_turn_end(BattleContext&);
void regent_before_card_played(BattleContext&);
void regent_after_card_played(BattleContext&);
void regent_power_changed(BattleContext&,PowerId,int);
void regent_card_drawn(BattleContext&,Card&);
void regent_card_generated(BattleContext&,const Card&);
void regent_card_entered_combat(BattleContext&,Card&,bool clone);
int regent_star_cost(const BattleContext&,const Card&);
void regent_spend_energy(BattleContext&,int);
void regent_spend_stars(BattleContext&,int);
bool regent_void_form_free(const BattleContext&,const Card&);
}
