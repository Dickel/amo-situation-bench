"""Prompts for the two nodes where the model chooses content.

Deliberately short. Everything about sequencing lives in graph.py as topology,
so these carry no ordering instructions -- there is nothing here for a model to
disobey.
"""

SCREEN_PROMPT = """You are screening a description against a fixed catalogue of \
manufacturing situation types. Return only the ids whose trigger condition the \
description actually satisfies.

Catalogue:
{catalogue}

Description:
{question}

Rules:
- Return ids only, one per line. No prose.
- Return NONE if nothing in the catalogue fires. This is a common and correct \
answer -- the catalogue is small and deliberately bounded.
- A trigger has parts. If the description satisfies one part and not another, it \
does not fire. A capacity shortfall with a single customer does not satisfy \
SIT-AMO-004, which requires commitments to different customers. A shortage with \
one consuming order does not satisfy SIT-AMO-001, which requires two or more.
- If the description states an action the person wants to take ("expedite it", \
"rob the parts off the other order") rather than a condition, return NONE. An \
action is not a situation.

Ids:"""


VERDICT_PROMPT = """A person described a manufacturing problem that is not in the \
AMO situation bench. In two or three sentences, explain where the boundary falls: \
what kind of problem this is, and why it sits outside a bench of judgment-territory \
situations. Be useful, not apologetic. Do not invent a situation id and do not \
propose a set of strategies.

Description:
{question}

Explanation:"""
