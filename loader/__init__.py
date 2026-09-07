"""amo-situation-bench graph loader.

Parses `data/amo-situations.md`, turns each card's entity_refs / edges /
sample_instance into Cypher, loads it into Memgraph in one transaction, and
validates that each card's trigger.pattern parses as real Cypher and fires
against its own sample_instance.

Every node is stamped with a `domain` property (always `"AMO"` here). One graph
instance can hold more than one domain; the property, enforced inline in every
trigger pattern, is what keeps a pattern from reaching across one.
"""
