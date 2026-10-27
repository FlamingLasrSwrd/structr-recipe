# Recipes and copyright: what an import may keep

**Status: guide, 2026-10-26.** Written at the owner's request ("Do a search on the copyrights of
recipes. Determine what can be copied from recipes and what can't. Define some rules for imports that
respect copyright."). It is research by Claude from the sources listed at the end, **not legal
advice**. Before a hosted service shares recipes between people, have someone qualified review it.

## What the law protects

### In the United States

- **The Copyright Office's own position** (Circular 33, *Works Not Protected by Copyright*): a recipe
  is a statement of the ingredients and the procedure for making a dish. A mere list of ingredients,
  or a simple set of directions, cannot be copyrighted. Writing that creatively explains or depicts
  how or why to do something may be, and so may photographs and illustrations. A registration never
  covers the ingredient list, the underlying process, or the dish itself. The circular's own example
  refuses a salad dressing recipe whose few numbered directions held too little creative authorship.
- **Ideas, procedures, processes and methods** are excluded by statute, however they are described
  (17 U.S.C. § 102(b), quoted in the circular). A cooking method is a process.
- **Names, titles and short phrases** are not copyrightable (Circular 33), though a brand's name may
  be a trademark.
- **A cookbook or a site's collection** may be protected as a compilation: its selection and
  arrangement, not the individual recipes. *Publications International v. Meredith* (7th Cir. 1996),
  the leading case, held a cookbook's compilation copyright did not reach its recipes, whose
  ingredient lists are statements of fact, and left open whether a recipe with more literary
  expression could be protected. *Lambing v. Godiva Chocolatier* (6th Cir. 1998) treated recipes as
  unprotected outright.
- **The expressive extras around a recipe can be protected.** In *Barbour v. Head* (S.D. Tex. 2001),
  recipes copied word for word went to trial because they carried suggestions for presentation,
  advice on drinks, and similar text: whether they were expressive enough was a question of fact.

### Elsewhere, for a service with users abroad

- **The EU's database right** (Directive 96/9/EC, Art. 7) protects a database that took substantial
  investment, even when its contents are facts: taking a substantial part of it, or taking small parts
  repeatedly and systematically, can infringe. The UK has a similar right; how it applies to databases
  made after Brexit is debated.
- **A site's terms of use are a contract.** In *Ryanair v PR Aviation* (CJEU, 2015), a site whose
  data had neither copyright nor database protection could still forbid automated extraction in its
  terms. US courts also enforce terms of use as contracts.
- **Recipe text** can be protected in the UK and EU when it is original, as in the US; ingredient
  lists and plain methods generally are not.

## What an import keeps, and what it does not

| Kept: facts and function | Not kept: expression |
|---|---|
| the recipe's name (a title) | the instructions as written |
| ingredients, amounts and units | the headnote, description, story or history |
| servings, minutes, hours made ahead, difficulty | tips, serving suggestions, pairings, variations |
| meal types | photographs, videos, illustrations |
| the order of operations as the model records it: each step's method, what goes in, what comes out, with what equipment (a label of a few words names the step); since 2026-10-26 also its working and waiting minutes, the steps before it, a tool's heat and the doneness of what it makes, in a few words or a temperature (J35); and what may stand in for an ingredient, and how much (J36) | reviews and comments (a rating's numbers are facts) |
| the source's address, in `source` | a site's or a book's collection as a collection |
| nutrition worked out here, or figures the source publishes | |

This is what the model already does: a recipe file has no field for instructions or descriptions,
an unknown field is refused (`recipe_import.TOP_KEYS`), and since 2026-10-26 a step's name is at most
80 characters (`recipe_import.STEP_NAME_MAX`), so it stays a label. A step's doneness is at most 60
(`recipe_import.UNTIL_MAX`): "golden", "until the rice is tender", not the source's sentence.

## Rules for importing

1. **Keep only the left column above.** The importer enforces the format; a person or a tool filling
   it in keeps to it.
2. **Name the source.** Every recipe from someone else carries its address in `source`. It is the
   credit, and the way back to the full text, which the model does not hold.
3. **One recipe at a time, the ones you will cook.** Do not mirror a site's or a book's whole
   catalogue: its selection and arrangement may be protected (a compilation in the US, a database in
   the EU and UK).
4. **No automated bulk extraction.** Read a page's structured facts, or transcribe by hand. Respect
   robots.txt and a site's terms. A page behind a bot check is the owner's to transcribe; it is never
   worked around (as with the White Chicken Chili, 2026-09-27).
5. **From structured data, take the facts only.** Where a page publishes schema.org `Recipe` data,
   `name`, `recipeIngredient`, `recipeYield`, `totalTime` and the like are facts. `recipeInstructions`
   text, `description`, `image` and `review` are not kept.
6. **Comments in a recipe file record the transcription's choices** (a can's size, a size in grams, an
   ingredient taken as optional). They quote at most a few words: a title, an ingredient's label.
7. **Instructions of our own are written fresh**: short and functional, from the steps' facts, never a
   line-by-line paraphrase of the source's text. Since 2026-10-26 the recipe page writes them, each step
   one sentence from its facts by fixed rules (`mealplanner/instructions.py`), and nothing of them is
   stored: they follow the facts.
8. **Recipes exported from another application** (Grocy, Mealie, Paprika and the like) may carry text
   and photos copied from elsewhere. The importer keeps the left column and the source's address, and
   drops the rest.

**Audit, 2026-10-26:** the owner's 53 recipe files keep to these rules. They hold no instruction text;
the longest string is a source address (101 characters), step labels are at most 67 characters, and
the quoted passages in comments (69) are titles and ingredient labels of at most 12 words.

## A personal instance and a hosted service

- **A personal instance** keeping the facts of recipes its owner cooks, with their sources, is well
  inside the rules above.
- **A hosted service sharing recipes between people** needs more:
  - a recipe published to others carries the facts and the link, never the source's text or photos;
  - whoever adds text or photos of their own affirms they made them, or have a licence to share them;
  - a way to take down what a rights holder objects to. In the US, the safe harbour for hosts of
    user-posted material (17 U.S.C. § 512) requires a designated agent and a notice-and-takedown
    process;
  - no bulk imports from commercial sites, and attention to the database right and terms of use for
    users in the EU and UK;
  - brand names used only to say where a recipe came from, never to suggest the brand endorses the
    service.
- **The reference data is not a concern.** USDA FoodData Central, FoodKeeper and the retention
  factors, and BLS and ERS prices, are public domain or CC0, and credited in their files
  (`docs/self-hosting.md`).

## Sources

- U.S. Copyright Office, *Circular 33: Works Not Protected by Copyright*:
  https://www.copyright.gov/circs/circ33.pdf
- *Publications International, Ltd. v. Meredith Corp.*, 88 F.3d 473 (7th Cir. 1996):
  https://law.resource.org/pub/us/case/reporter/F3/088/88.F3d.473.95-3530.95-3485.html
- Commentary on *Lambing v. Godiva* and *Barbour v. Head*: https://copyright.nova.edu/copyright-in-recipes/
  and https://ip.fasken.com/?p=922
- Directive 96/9/EC, Art. 7 (the database right): https://www.legislation.gov.uk/eudr/1996/9/article/7/data.html
- *Ryanair v PR Aviation* (C-30/14, 2015):
  https://marketinglaw.osborneclarke.com/media-and-ip/could-ryanair-control-use-of-its-flight-data-by-pr-aviation-without-database-right/
- The UK database right after Brexit: https://www.womblebonddickinson.com/uk/insights/articles-and-briefings/brexit-and-database-rights
