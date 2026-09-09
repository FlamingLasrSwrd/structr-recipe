# Review notes

You're looking at a solo, AI-assisted build of a BFO-grounded meal-planning data model, implemented on Structr 6.x/Neo4j. This document orients a reviewer coming in cold: what to read first, what's already been self-reported as a gap or a finding, and what would be most useful to check independently.

Nothing here is asking you to trust the claims below — the opposite. Where a claim is made ("this invariant is enforced," "this bug exists"), the code and commit history should let you verify or refute it directly.

## Where to start

1. **`docs/CLAUDE.md`** — read this first. It has a document-authority table (`data-model.md` and `structr-build-sketch.md` are authoritative; the two `design-review-document*.md` files are historical and explicitly should not be followed as current guidance — they record pre-fix state and would reintroduce solved problems if read as-is), a list of hard rules that came from real data-loss incidents, and the deliberately-out-of-scope list.
2. **`docs/data-model.md`** — the actual model. BFO-grounded (with IAO/CCO/RO/PROV-O/OWL-Time/SKOS/QUDT companions), four major revisions plus a fifth (§17, "Rev 4.3") added during this build when implementation contact surfaced real gaps. §11 has the 30 domain invariants; §14–17 are dated changelogs explaining *why* each revision happened, not just what changed.
3. **`docs/structr-build-sketch.md`** — how the model maps onto Structr specifically (the three-layer split: frozen structural traits / metamodel-as-data / instance data). §5 has an addendum documenting where the implementation deviates from what this doc originally planned (StructrScript → Python for several algorithms) and why.
4. **`docs/structr-cheatsheet.md`** — empirically-verified Structr mechanics, unrelated to this project's domain. Large; skim unless you're checking a specific implementation claim.
5. **The commit history** (`git log`) — every commit message explains the *why*, not just the diff. This was a deliberate practice throughout, not written after the fact for this review.

## Repo structure

- `mealplanner/` — Python modules: schema definitions (`*_schema.py`), the domain-invariant validators (`domain_invariants.py`), the compute-don't-store inventory engine (`inventory.py`), material accounting (`material_accounting.py`), seed vocabulary.
- `structr_client/` — a generic Structr REST client, no project-specific knowledge (deliberately kept separate — see `docs/CLAUDE.md`'s repo conventions).
- `scripts/` — numbered in build order (`01_...` through `18_...`); each is independently re-runnable (idempotent) and most end with their own inline verification. Roughly: `01`–`04` are the structural spike, `05` seeds vocabulary, `06` builds the first real recipe end to end, `07` on is domain invariants and the meal-planning layer, `08`–`09` are breadth tests, `10`–`14` build out meal planning/nutrition/stock scoring, `15` is a full data reset plus a realistic full-lifecycle stress test, `16`–`18` are targeted fixes from a holes-and-gaps analysis (see below).
- Everything is graph state in a local Structr/Neo4j instance (not committed) — the scripts are the reproducible source of truth for what's *in* that graph. There's no need to stand up Structr to review the model or the Python logic; you'd only need it to actually re-run and re-verify a script's claims live.

## Test-data hygiene — worth spot-checking

Convention throughout: any exploratory/illustrative/test instance data is name-prefixed `TEST -- `; real, curated vocabulary is not. This was applied consistently by intent, but it's exactly the kind of thing worth an independent grep — search for entity creation calls without the prefix and sanity-check that everything unprefixed is genuinely meant to be permanent vocabulary, not something that slipped through.

## Self-reported findings — a checklist, not a victory lap

These are things *I* found and, in most cases, fixed. Independent confirmation (or refutation) of any of these would be the most valuable thing a reviewer could do, since they're exactly the kind of claim that's easy to get subtly wrong when the same author who wrote the code also "verified" it.

### A. Data-modeling / BFO correctness

- **`data-model.md` §17 (Rev 4.3)** is the changelog for fixes made *during* this build, after the model was supposedly finalized (Rev 4.2). Each entry (H1–H5) is a claim that something in the original model was wrong or underspecified. Worth checking each on its merits:
  - H1: the yield/material-accounting formula (§5.1) was single-input shaped; the fix applies a yield factor per input before summing, for combination recipes. Is this the right fix, or should combination yield be modeled differently entirely?
  - H2: three relations (`for_type`, `for_meal_plan`, `targets_entry`) were used in the model's own prose but never formally named in §7. This is the *third* independent occurrence of that failure mode (after the original `E9` finding recorded in `docs/design-review-document-round2.md`). A systematic pass checking all 30 invariants against §7 was recommended but never done — genuinely open work, not just a suggestion.
  - H3: `has_recipe_yield`'s unit (servings vs. batches vs. something else) was never specified in the model; resolved by inference from the `AcquisitionList` formula. Is that inference sound?
  - H4/H5: `ContainerObject` gained `has_opened_status` and `has_storage_condition` to make §8's compound `ShelfLife` key actually usable. Reasonable, or should opened/sealed and storage condition be modeled some other way (e.g., as literal values rather than `DomainType` entries)?
- **The "Reading A" resolution** (a food's Perishability classification is an independent instance-level fact, not a second parent of the same `DomainType` node — see `data-model.md` §1 and the multi-hierarchy discussion) — this was a genuine ambiguity in the model that got resolved via judgment call, not derivation. Worth an ontologist's second opinion.
- **`ExclusionConstraint`** (a new concrete `PlanningConstraint` subtype, added for allergy/dietary-restriction handling — not in the original model at all) — was this the right structural choice versus, say, reusing `StockPolicy` with a convention, or modeling exclusions entirely differently?

### B. Structr implementation

- **`resolveDefault` doesn't honor its own documented signature.** `data-model.md` §8 says a `DefaultSpecification` resolves by its `(hasKind, keyedBy)` signature; the live StructrScript implementation only ever filters by `hasKind`. Documented in `docs/structr-build-sketch.md` §5's addendum. Two places work around it rather than fix it (`mealplanner/material_accounting.py`, `mealplanner/inventory.py`'s `shelf_life_days`) — worth checking whether the workarounds are actually sufficient for the cases that currently exist, and what would break if a `DomainType` ever carried two same-`hasKind` defaults with different `keyedBy` sets in a case the workarounds don't cover.
- **A literal comma in any Structr property value silently breaks exact-match REST queries** (`docs/structr-cheatsheet.md` §4) — confirmed empirically, and a guard was added to `structr_client/client.py`'s `upsert()` to reject commas outright. It caught real bugs during this build (several are visible in the commit history). Question worth checking: are there *other* characters with the same problem (the cheatsheet documents semicolon as a reserved OR-match separator, for instance) that aren't guarded against?
- **The StructrScript-vs-Python split** — `resolveDefault` and all `onCreate`/`onSave` invariant validators are StructrScript; `currentMagnitude()`, `physicalOnHand()`, `eligibleOnHand()`, `material_accounting.py`, and the selector itself are plain Python over REST. The stated reason (`mealplanner/inventory.py`'s module docstring) is that StructrScript hit a real ceiling on multi-hop/multi-entity control flow. Worth a skeptical read: is this actually a hard limitation, or could more of this reasonably live in Structr?

### C. Domain invariant coverage

`mealplanner/domain_invariants.py` is the single source of truth for which of the model's 30 invariants are enforced, which are structurally free, and which are deliberately deferred (with reasons). Roughly 12 of 30 are implemented; the rest are either genuinely blocked on unbuilt structural pieces (documented) or — in one case — confirmed *not* enforced at all despite the underlying computation existing:

- **Invariant 15** ("summed input quantities cannot exceed physical on-hand") has zero enforcement anywhere. Confirmed by direct probe (see `scripts/15e_edge_cases.py`): allocating 500g from a 200g on-hand portion was accepted outright. The compute-don't-store machinery to check this (`currentMagnitude()`) already exists; nothing calls it at write time.
- **Invariant 27a**'s consistency check (`ROLE_ONCREATE` in `domain_invariants.py`) only checks when both sides of the comparison are already resolvable, and silently passes otherwise — same reasoning used to defer invariant 16 entirely. Is "check when possible" actually safe here, or does it create a window where a bad state can be written and never caught?

### D. Selector / scoring design

`scripts/11c_simple_selector.py` is a weighted-sum scorer (not a real optimizer — see `docs/CLAUDE.md`'s explicit note that no optimizer has ever been designed for this project; this is deliberately the "simple path" discussed and agreed on before it was built). One finding from testing, not yet acted on:

- A real run showed a near-expiring ingredient (waste urgency scored 0.80/1.0) still losing to a faster recipe, because the time-budget term dominated the linear sum. Nothing in the current design escalates urgency non-linearly as expiry approaches — a soft constraint stays uniformly "soft" regardless of how close to a hard failure it is. Is a linear weighted sum the wrong shape for this, and if so, what should replace it?

## What would be most useful

Roughly in order of leverage:

1. **An ontologist's read of `data-model.md`**, especially the Rev 4.3 additions (§17) and the "Reading A" multi-hierarchy resolution — these were judgment calls made under implementation pressure, exactly where a second opinion is worth the most.
2. **A skeptical pass over `mealplanner/domain_invariants.py`** against `data-model.md` §11 — confirm the coverage claims, and specifically try to break invariant 27a's "check when possible" logic.
3. **A Structr-specific technical review** of `structr_client/client.py` and the `onCreate` validators in `mealplanner/domain_invariants.py` for correctness (the StructrScript is string-concatenated Python — easy to get subtly wrong in ways that only show up at write time).
4. **A general code-quality pass** — this was built by one AI-assisted developer across several sessions; consistency drift, dead code, and over-elaborate abstractions in places that didn't need them are all plausible and haven't had a dedicated look.
