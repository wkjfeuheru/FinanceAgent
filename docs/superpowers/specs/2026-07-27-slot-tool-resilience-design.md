# Slot Tool Resilience Design

## Scope

Apply a minimal hardening pass to the existing on-demand native Tool Calling
workflow. Keep the graph topology, public API, tool schema, and profile merge
semantics unchanged.

## Decision validation

Treat model-produced tool calls as untrusted input. Ignore entries that are not
dictionaries, calls with the wrong tool name, non-dictionary arguments, intents
outside the current candidate set, queries that differ from the classified
sub-request, and duplicate intents. After validation, use the existing
deterministic fallback for required candidate intents that the model omitted.

## Per-intent execution isolation

Each validated call is one isolated operation. Invocation, result validation,
stock normalization, and state merge all occur inside that call's exception
boundary. A malformed result records an error for that intent and processing
continues with the remaining calls. Only successfully validated results update
the profile, resolved stocks, per-intent stocks, and explicit stock codes.

## Deterministic routing boundary

Asset allocation always remains a candidate. Market queries and recommendation
queries become candidates only when the sub-request contains a stock code, a
recognized A-share name, or a clear individual-stock reference. Broad market,
index, sector, industry, concept, commodity, currency, and generic thematic
requests skip slot extraction. The existing model decision remains the normal
path and deterministic completion remains the availability fallback.

## Tests

Add focused regression tests that first fail against the current implementation:

- malformed model tool-call entries do not abort decision handling;
- malformed tool results fail only their own intent while another call succeeds;
- broad non-stock market requests skip slot extraction;
- existing required/skipped examples remain unchanged.

After the focused tests pass, run the complete backend suite and frontend build.
The network-dependent real-model smoke test remains optional and will not run
without an already prepared model/API environment.
