"""Public generation events, inferred from audited actions, never hidden piles.

``decision`` stays strictly increasing, as it always was.  One audited enemy
move adds several identical cards at the same public decision, so a
version-gated ``count`` field carries that multiplicity instead of inventing
extra decisions or silently bypassing conservation validation.
"""
from .content import BOSS_CONTENT
from dataclasses import dataclass

# C# EyeWithTeeth.DistractMove: AddToCombatAndPreview<Dazed>(targets, Discard, 3)
DISTRACT_DAZED_COUNT = 3


@dataclass(frozen=True)
class CardGeneration:
    decision: int
    source_token: str
    result_token: str
    destination: str = "discard"
    mechanism: str = "anger-copy-v1"
    count: int = 1


def generated_tokens(events, decisions, content_version=None):
    from .content import MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
    from .summon import admitted_generated
    if type(events) is not tuple:
        raise ValueError("Generation ledger must be immutable")
    previous = 0
    tokens = []
    for event in events:
        single = event.count == 1 if type(event) is CardGeneration else False
        valid_anger = (type(event) is CardGeneration and single and event.source_token in ("ANGER", "ANGER+")
                       and event.result_token == event.source_token
                       and event.destination == "discard" and event.mechanism == "anger-copy-v1")
        valid_reave = (type(event) is CardGeneration and single
                       and content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT)
                       and event.source_token in ("REAVE", "REAVE+")
                       and event.result_token == ("SOUL+" if event.source_token.endswith("+") else "SOUL")
                       and event.destination == "draw_bottom" and event.mechanism == "reave-soul-v1")
        valid_dazed = admitted_generated(event, SUMMON_CONTENT if content_version == BOSS_CONTENT else content_version)
        from .boss import admitted_generation
        valid_boss = admitted_generation(event, content_version)
        if (type(event) is not CardGeneration or type(event.count) is not int or type(event.decision) is not int
                or not previous < event.decision <= decisions or not (valid_anger or valid_reave or valid_dazed or valid_boss)):
            raise ValueError("Invalid public generation event")
        previous = event.decision
        tokens.extend([event.result_token] * event.count)
    return tuple(tokens)
