"""Native candidate pools: audit closure without narrowing generation."""
from .config import content_hash

DEFERRED={'SPLASH':'cross-character generation outside scope',
    'JACK_OF_ALL_TRADES':'native Colorless pool contains Splash',
    'ENTROPY':'transforming a Colorless/event/ancient card can produce Splash'}

def audit():
    from sts2_env.cards.factory import eligible_character_cards,eligible_registered_cards,eligible_transform_cards,create_card,card_metadata
    from sts2_env.core.card_pools import CardPoolId
    from sts2_env.core.enums import CardType,CardId
    from .content_expansion import CODEC
    character=eligible_character_cards('ironclad',generation_context='combat',is_multiplayer=False)
    attacks=[c for c in character if card_metadata(c).card_type==CardType.ATTACK]
    zero=[c for c in character if create_card(c).cost==0 and not create_card(c).has_energy_cost_x]
    colorless=eligible_registered_cards(card_pool=CardPoolId.COLORLESS,exclude_ids={CardId.JACK_OF_ALL_TRADES},generation_context='combat',is_multiplayer=False)
    transform=eligible_transform_cards(create_card(CardId.FINESSE),character_id='ironclad',generation_context='combat',is_multiplayer=False)
    pools={'DISCOVERY':character,'INFERNAL_BLADE':attacks,'CALAMITY_CARD':attacks,'JACKPOT':zero,
        'JACK_OF_ALL_TRADES':colorless,'ENTROPY':transform}
    rows={name:dict(candidates=sorted(c.name for c in pool),
        missing=sorted(c.name for c in pool if c.name not in CODEC.factories),
        admitted=name in CODEC.factories) for name,pool in pools.items()}
    for row in rows.values():row['pool_sha256']=content_hash(row['candidates'])
    return dict(version='native-generation-closure-v1',pools=rows,deferred=DEFERRED,
        native_pool_filtering=False,character_combat_count=len(character))
