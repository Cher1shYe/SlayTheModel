// v0.111.0 PotionFactory.GetPotionOptions: character pool followed by shared
// pool. Each character's three epoch potions come first in their native
// <Character>4Epoch order, then the shared pool in its declared order.
// Full unlocked pool; partial epoch filtering remains outside the progress
// contract. Ambergris (SPECIAL) is event-only and not in either normal pool.
static const PotionId NATIVE_SHARED_POTIONS[] = {
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

static const PotionId NATIVE_IRONCLAD_POTIONS[] = {
        PotionId::BLOOD_POTION, PotionId::SOLDIERS_STEW, PotionId::ASHWATER,
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

static const PotionId NATIVE_SILENT_POTIONS[] = {
        PotionId::POISON_POTION, PotionId::GHOST_IN_AJAR, PotionId::CUNNING_POTION,
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

static const PotionId NATIVE_DEFECT_POTIONS[] = {
        PotionId::FOCUS_POTION, PotionId::ESSENCE_OF_DARKNESS, PotionId::POTION_OF_CAPACITY,
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

static const PotionId NATIVE_REGENT_POTIONS[] = {
        PotionId::STAR_POTION, PotionId::COSMIC_CONCOCTION, PotionId::KINGS_COURAGE,
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

static const PotionId NATIVE_NECROBINDER_POTIONS[] = {
        PotionId::POTION_OF_DOOM, PotionId::POT_OF_GHOULS, PotionId::BONE_BREW,
        PotionId::ATTACK_POTION, PotionId::BEETLE_JUICE, PotionId::BLESSING_OF_THE_FORGE, PotionId::BLOCK_POTION,
        PotionId::BOTTLED_POTENTIAL, PotionId::CLARITY, PotionId::COLORLESS_POTION, PotionId::CURE_ALL,
        PotionId::DEXTERITY_POTION, PotionId::DISTILLED_CHAOS, PotionId::DROPLET_OF_PRECOGNITION, PotionId::DUPLICATOR,
        PotionId::ENERGY_POTION, PotionId::ENTROPIC_BREW, PotionId::EXPLOSIVE_AMPOULE, PotionId::FAIRY_IN_ABOTTLE,
        PotionId::FIRE_POTION, PotionId::FLEX_POTION, PotionId::FORTIFIER, PotionId::FRUIT_JUICE,
        PotionId::FYSH_OIL, PotionId::GAMBLERS_BREW, PotionId::GIGANTIFICATION_POTION, PotionId::HEART_OF_IRON,
        PotionId::LIQUID_BRONZE, PotionId::LIQUID_MEMORIES, PotionId::LUCKY_TONIC, PotionId::MAZALETHS_GIFT,
        PotionId::OROBIC_ACID, PotionId::POTION_OF_BINDING, PotionId::POWDERED_DEMISE, PotionId::POWER_POTION,
        PotionId::RADIANT_TINCTURE, PotionId::REGEN_POTION, PotionId::SHACKLING_POTION, PotionId::SHIP_IN_ABOTTLE,
        PotionId::SKILL_POTION, PotionId::SNECKO_OIL, PotionId::SPEED_POTION, PotionId::STABLE_SERUM,
        PotionId::STRENGTH_POTION, PotionId::SWIFT_POTION, PotionId::TOUCH_OF_INSANITY, PotionId::VULNERABLE_POTION,
        PotionId::WEAK_POTION,
    };

// Character pool lookup used by rewards/shops/events and combat generation.
static void native_potion_pool(CardPool character, const PotionId *&ids, int &count) {
    switch (character) {
        case CardPool::SILENT: ids = NATIVE_SILENT_POTIONS;
            count = static_cast<int>(sizeof(NATIVE_SILENT_POTIONS) / sizeof(PotionId)); break;
        case CardPool::DEFECT: ids = NATIVE_DEFECT_POTIONS;
            count = static_cast<int>(sizeof(NATIVE_DEFECT_POTIONS) / sizeof(PotionId)); break;
        case CardPool::REGENT: ids = NATIVE_REGENT_POTIONS;
            count = static_cast<int>(sizeof(NATIVE_REGENT_POTIONS) / sizeof(PotionId)); break;
        case CardPool::NECROBINDER: ids = NATIVE_NECROBINDER_POTIONS;
            count = static_cast<int>(sizeof(NATIVE_NECROBINDER_POTIONS) / sizeof(PotionId)); break;
        default: ids = NATIVE_IRONCLAD_POTIONS;
            count = static_cast<int>(sizeof(NATIVE_IRONCLAD_POTIONS) / sizeof(PotionId)); break;
    }
}
