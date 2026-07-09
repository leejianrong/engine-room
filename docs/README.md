# Engine Room — docs

A real-time matchmaking and spectating platform for AI chess bots. This tree holds all design and planning docs.

```
docs/
  design/     product & contract corpus — "what we decided"
  adr/        architecture decision records — "why we decided it"
  shaping/    implementation plan — "how & in what order we build it"
```

Dev process: [DEVELOPER-WORKFLOWS.md](DEVELOPER-WORKFLOWS.md) (the playbook) ·
[WORKFLOW-ADOPTION.md](WORKFLOW-ADOPTION.md) (what we've adopted / deferred).

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
| [slices.md](shaping/slices.md) | Slice map V1–V7 — **all built**; each slice was breadboarded just-in-time when picked up. |
| [V1-plan.md](shaping/V1-plan.md) … [V7-plan.md](shaping/V7-plan.md) | Per-slice implementation plans (goal, decisions, sub-steps, deviations-as-built). One per slice: [V1](shaping/V1-plan.md), [V2](shaping/V2-plan.md), [V3](shaping/V3-plan.md), [V4](shaping/V4-plan.md), [V5](shaping/V5-plan.md), [V6](shaping/V6-plan.md), [V7](shaping/V7-plan.md). |

## Reading order
New here? **REQS → CONTEXT → PRD → PROTOCOL**, dipping into **adr/** for any "why". To see the build plan: **shaping/frame → shaping → slices**, then the per-slice **V1-plan … V7-plan**.
