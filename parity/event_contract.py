"""Explicit native EventOption.TextKey tables audited against event_choose.

The dictionary is intentionally per event and page. Unknown pages never inherit
an INITIAL mapping or fall back to generic option indices.
"""
INITIAL_OPTIONS = {
    "AROMA_OF_CHAOS": ("LET_GO", "MAINTAIN_CONTROL"),
    "DENSE_VEGETATION": ("TRUDGE_ON", "REST"),
    "SUNKEN_STATUE": ("GRAB_SWORD", "DIVE_INTO_WATER"),
    "WELLSPRING": ("BOTTLE", "BATHE"),
    "TABLET_OF_TRUTH": ("DECIPHER_1", "SMASH"),
    "UNREST_SITE": ("REST", "KILL"),
    "SAPPHIRE_SEED": ("EAT", "PLANT"),
    "THIS_OR_THAT": ("PLAIN", "ORNATE"),
    "ROOM_FULL_OF_CHEESE": ("GORGE", "SEARCH"),
    "POTION_COURIER": ("GRAB_POTIONS", "RANSACK"),
    "BRAIN_LEECH": ("SHARE_KNOWLEDGE", "RIP"),
    "STONE_OF_ALL_TIME": ("LIFT", "PUSH"),
    "WELCOME_TO_WONGOS": ("BARGAIN_BIN", "FEATURED_ITEM", "MYSTERY_BOX", "LEAVE"),
    "HUNGRY_FOR_MUSHROOMS": ("BIG_MUSHROOM", "FRAGRANT_MUSHROOM"),
    "REFLECTIONS": ("TOUCH_A_MIRROR", "SHATTER"),
    "SPIRIT_GRAFTER": ("LET_IT_IN", "REJECTION"),
    "LOST_WISP": ("CLAIM", "SEARCH"),
    "AMALGAMATOR": ("COMBINE_STRIKES", "COMBINE_DEFENDS"),
    "BYRDONIS_NEST": ("EAT", "TAKE"),
    "BUGSLAYER": ("EXTERMINATION", "SQUASH"),
    "CRYSTAL_SPHERE": ("UNCOVER_FUTURE", "PAYMENT_PLAN"),
    "DOLL_ROOM": ("RANDOM", "TAKE_SOME_TIME", "EXAMINE"),
    "FIELD_OF_MAN_SIZED_HOLES": ("RESIST", "ENTER_YOUR_HOLE"),
    "GRAVE_OF_THE_FORGOTTEN": ("CONFRONT", "ACCEPT"),
    "INFESTED_AUTOMATON": ("STUDY", "TOUCH_CORE"),
    "JUNGLE_MAZE_ADVENTURE": ("SOLO_QUEST", "JOIN_FORCES"),
    "LUMINOUS_CHOIR": ("REACH_INTO_THE_FLESH", "OFFER_TRIBUTE"),
    "MORPHIC_GROVE": ("GROUP", "LONER"),
    "RANWID_THE_ELDER": ("POTION", "GOLD", "RELIC"),
    "ROUND_TEA_PARTY": ("ENJOY_TEA", "PICK_FIGHT"),
    "SELF_HELP_BOOK": ("READ_THE_BACK", "READ_PASSAGE", "READ_ENTIRE_BOOK"),
    "SLIPPERY_BRIDGE": ("OVERCOME", "HOLD_ON_0"),
    "SYMBIOTE": ("APPROACH", "KILL_WITH_FIRE"),
    "TEA_MASTER": ("BONE_TEA", "EMBER_TEA", "TEA_OF_DISCOURTESY"),
    "THE_LANTERN_KEY": ("RETURN_THE_KEY", "KEEP_THE_KEY"),
    "THE_LEGENDS_WERE_TRUE": ("NAB_THE_MAP", "SLOWLY_FIND_AN_EXIT"),
    "TINKER_TIME": ("CHOOSE_CARD_TYPE",),
    "TRIAL": ("ACCEPT", "REJECT"),
    "WAR_HISTORIAN_REPY": ("UNLOCK_CAGE", "UNLOCK_CHEST"),
    "BATTLEWORN_DUMMY": ("SETTING_1", "SETTING_2", "SETTING_3"),
    "ABYSSAL_BATHS": ("IMMERSE", "ABSTAIN"),
    "DROWNING_BEACON": ("BOTTLE", "CLIMB"),
    "PUNCH_OFF": ("NAB", "I_CAN_TAKE_THEM"),
    "SPIRALING_WHIRLPOOL": ("OBSERVE", "DRINK"),
    "SUNKEN_TREASURY": ("FIRST_CHEST", "SECOND_CHEST"),
    "DOORS_OF_LIGHT_AND_DARK": ("LIGHT", "DARK"),
    "TRASH_HEAP": ("DIVE_IN", "GRAB"),
    "WATERLOGGED_SCRIPTORIUM": ("BLOODY_INK", "TENTACLE_QUILL", "PRICKLY_SPONGE"),
    "WHISPERING_HOLLOW": ("GOLD", "HUG"),
    "WOOD_CARVINGS": ("SNAKE", "BIRD", "TORUS"),
    "ZEN_WEAVER": ("BREATHING_TECHNIQUES", "EMOTIONAL_AWARENESS", "ARACHNID_ACUPUNCTURE"),
}
# Page numbers are the simulator's existing explicit state machine; the strings
# are copied from the corresponding native callback's SetEventState options.
PAGES = {
    ("DENSE_VEGETATION", 1): ("REST.FIGHT",),
    ("THE_LANTERN_KEY", 1): ("KEEP_THE_KEY.FIGHT",),
    ("PUNCH_OFF", 1): ("I_CAN_TAKE_THEM.FIGHT",),
    ("ROUND_TEA_PARTY", 1): ("PICK_FIGHT.CONTINUE_FIGHT",),
    ("ABYSSAL_BATHS", 1): ("ALL.LINGER", "ALL.EXIT_BATHS"),
    ("TRIAL", 1): ("REJECT.ACCEPT", "REJECT.DOUBLE_DOWN"),
}


def simulator_event_option(rc, index, sim=None):
    from .semantic import UnsupportedSemanticState
    event, page = rc.event_name, int(rc.event_page)
    if sim is not None and hasattr(sim, "event_option_keys"):
        keys = list(sim.event_option_keys(rc))
        if 0 <= index < len(keys) and keys[index]:
            return keys[index]
    if page == 0 and event in INITIAL_OPTIONS:
        keys = INITIAL_OPTIONS[event]
        if event == "SELF_HELP_BOOK" and int(rc.event_choices) == 1:
            keys = ("NO_OPTIONS",)
        if 0 <= index < len(keys):
            return f"{event}.pages.INITIAL.options.{keys[index]}"
    if (event, page) in PAGES and 0 <= index < len(PAGES[event, page]):
        native_page, option = PAGES[event, page][index].split(".")
        return f"{event}.pages.{native_page}.options.{option}"
    raise UnsupportedSemanticState(f"event {event} page {page} option {index} has no audited native option key")
