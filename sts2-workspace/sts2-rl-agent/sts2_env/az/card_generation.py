"""Public generation events, inferred from audited actions, never hidden piles."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CardGeneration:
    decision: int
    source_token: str
    result_token: str
    destination: str = "discard"
    mechanism: str = "anger-copy-v1"


def generated_tokens(events, decisions, content_version=None):
    from .content import MORPH_CONTENT, MULTI_CONTENT
    if type(events) is not tuple:
        raise ValueError("Generation ledger must be immutable")
    previous = 0
    tokens = []
    for event in events:
        valid_anger = (event.source_token in ("ANGER", "ANGER+") and event.result_token == event.source_token
                       and event.destination == "discard" and event.mechanism == "anger-copy-v1") if type(event) is CardGeneration else False
        valid_reave = (content_version in (MORPH_CONTENT, MULTI_CONTENT) and event.source_token in ("REAVE", "REAVE+")
                       and event.result_token == ("SOUL+" if event.source_token.endswith("+") else "SOUL")
                       and event.destination == "draw_bottom" and event.mechanism == "reave-soul-v1") if type(event) is CardGeneration else False
        if (type(event) is not CardGeneration or type(event.decision) is not int
                or not previous < event.decision <= decisions or not (valid_anger or valid_reave)):
            raise ValueError("Invalid public generation event")
        previous = event.decision
        tokens.append(event.result_token)
    return tuple(tokens)
