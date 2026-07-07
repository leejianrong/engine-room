# Engine Room — docs

A real-time matchmaking and spectating platform for AI chess bots. This tree holds all design and planning docs.

```
docs/
  design/     product & contract corpus — "what we decided"
  adr/        architecture decision records — "why we decided it"
  shaping/    implementation plan — "how & in what order we build it"
```

## design/ — product & contract corpus
| Doc | What it is |
|-----|------------|
| [REQS.md](design/REQS.md) | Original idea, problem, users, core outcomes, scope. |
| [CONTEXT.md](design/CONTEXT.md) | Living design context: glossary, domain model + invariants, decisions log, MVP definition. The hub that ties the ADRs together. |
| [PRD.md](design/PRD.md) | Product requirements: problem, solution, 76 user stories, implementation + testing decisions, out-of-scope. |
| [PROTOCOL.md](design/PROTOCOL.md) | The bot↔server WebSocket wire contract, v1.0 (public, versioned). |
| [QUESTIONS.md](design/QUESTIONS.md) | The full grilling backlog: resolved decisions + the few open build-time items. |

## adr/ — architecture decision records
[0001–0025](adr/) — one decision per file, with rationale and alternatives. `CONTEXT.md`'s decisions log links each row to its ADR.

## shaping/ — implementation plan
| Doc | What it is |
|-----|------------|
| [frame.md](shaping/frame.md) | The "why" of the build plan: source, problem, outcome. |
| [shaping.md](shaping/shaping.md) | Working doc: build requirements (R0–R7), slicing strategies (A/B/C), fit check, selected Shape A + A1 breadboard. |
| [slices.md](shaping/slices.md) | Slice map V1–V7; V1 fully specced, V2–V7 breadboarded just-in-time. |
| [V1-plan.md](shaping/V1-plan.md) | Individual implementation plan for slice V1 (the skeleton thread). |

## Reading order
New here? **REQS → CONTEXT → PRD → PROTOCOL**, dipping into **adr/** for any "why". To see the build plan: **shaping/frame → shaping → slices → V1-plan**.
