#pragma once
#include "sts2/battle.h"

namespace sts2 {

// Observation checklist A1: the value a card displays, as native
// CardModel.UpdateDynamicVarPreview(CardPreviewMode.Normal, target) computes it for
// the card's Damage/CalculatedDamage and Block/CalculatedBlock variables
// (DamageVar / BlockVar / CalculatedDamageVar / CalculatedBlockVar.UpdateCardPreview,
// Hook.ModifyDamage / Hook.ModifyBlock with cardPlay == null), truncated like
// DynamicVar's (int)PreviewValue. Read-only: never mutates the battle.
//
// target: monster index, or -1 for "no target" (how a card in hand is drawn).
// inHandOrPlay: runGlobalHooks (native runs global hooks only for Hand/Play cards).
// inPlay: the card sits in the Play pile (Pen Nib / Vambrace use this).
//
// Returns PREVIEW_UNSUPPORTED for calculated variables this port does not model
// (other characters' CalculatedDamage/Block cards); callers must mark it unknown.
constexpr int PREVIEW_UNSUPPORTED = -1000000;

// Rend.ShouldCountPower count (defined in cards_colorless.cpp, used by play and preview).
int rend_debuff_count(const Monster &m);

int card_preview_damage(const BattleContext &bc, const Card &card, int target, bool inHandOrPlay, bool inPlay);
int card_preview_block(const BattleContext &bc, const Card &card, int target, bool inHandOrPlay, bool inPlay);

}  // namespace sts2
