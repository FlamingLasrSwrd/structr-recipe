# The pantry: booking stock in and out

The owner asked (2026-10-23) for pantry methods "for adding, subtracting, inventory, etc. similar to
Grocy", with Buy, Use / cook, Stock take, and Open / freeze / discard, on pages signed-in users can
write through. This records what was built, how each action maps onto the model, and what does not
fit yet.

## Grocy, for comparison

Grocy ([grocy.info](https://grocy.info), its REST API in `grocy.openapi.json`) keeps **stock entries**
(an amount, a due date, a purchase date, a price, a location, opened or not) and books every change
as a **transaction** in a journal that can be undone: *purchase*, *consume* (optionally *spoiled*,
from a chosen entry, by default opened first, then the soonest due, then the oldest), *open*,
*transfer* between locations, and *inventory*, which sets a new amount and books the difference as a
correction. Each product has default due days, and days after opening, freezing and thawing; a
minimum stock amount puts it on the shopping list; recipes consume their ingredients in one action.

## What each action writes here

None of it needs a new structural type or a stored figure. The actions write the shapes the model
already uses for what happens to food (data-model.md §4.1.1, §5, §5.5), so the inventory engine
(`mealplanner/inventory.py`), the shopping list, the planner's stock and the pages count it as they
count everything else.

| Action | Grocy | Written | Read back as |
|---|---|---|---|
| **Buy** (and a ticked shopping line: below, "Ticking the shopping list") | purchase | a `Process` of kind *Purchase* at a `TemporalRegion`; a `PortionOfSubstance` that `beginsToExistDuring` it, `locatedIn` a `ContainerObject` with its storage condition and *Sealed*; its Mass `Quality`, with an `observed` `Measurement` of the amount bought; its Perishability Class, if one is chosen or an earlier portion of the food had one | stock from that moment; expiry from the purchase (§5.5) |
| **Use** | consume | a `Process` of kind *Use* with an input `Allocation` about the portion, its amount an `observed` `Measurement` | current magnitude less the amount, from then on (§4.1.1) |
| **Count** | inventory | a new `observed` `Measurement` of the portion's mass | the new baseline: a recount is not a revision (§4.1.1) |
| **Open** | open | the container's opened status set to *Opened* (a container made for a portion in none, kept in the fridge and sealed, which is what one in none is taken to be) | the *Opened* shelf life |
| **Freeze** / **Move** | transfer | the container's storage condition set | that condition's shelf life |
| **Discard** | consume, spoiled | a `Process` of kind *Discarding* drawing everything left | on hand none; what was thrown away stays on record (§9's waste feedback) |
| **Mark cooked** (week page) | consume a recipe | a `Process` that `concretizes` the entry's Plan, drawing each ingredient the recipe buys (`nutrition_scope.raw_inputs`), scaled from its yield to the servings planned, from eligible stock of the food or a food below it, soonest to expire first; then the entry is `fulfilledBy` it | the shopping list and the reservations stop counting the meal |

The Process kinds are DomainTypes in a *Pantry Operation* hierarchy, made the first time one is used.
A cook has no kind: it `concretizes` its recipe, as data-model.md §10's braise does.

**A booking names who made it** (2026-11-04): each Process it writes (a purchase, a use, a discard, a
cook) is `wasAssociatedWith` the Person who booked it (PROV; data-model.md K1). On the pages and in the
methods that is whoever is signed in, `$.me`, when they are a `Person` (taken before a page's booking runs
as the superuser); `mealplanner/pantry.py` takes it as `by`, which `tools/pantry.py` fills from `--by NAME`
or else the Person it signs in as (the tools' own account is none, so a booking from the terminal then
names no one). Since 2026-11-23 a stock take, an opening and a move each write a Process too (kinds
*Stock take*, *Opening*, *Move*), with the portion as its participant, so every booking names who made it.
A booking sent again by someone else is still the first one's.

**The first use of a sealed portion opens it** (the owner's rule, 2026-11-23): a Use, or a cook's draw,
that leaves some of a portion in a sealed container sets it *Opened*, so the opened shelf life applies from
then on, and says so. One that takes all of it opens nothing.

**Every booking is named by a token** (a page form carries one made when the page was drawn; the tool
makes one per run, or takes `--token`), and every node it writes is found by name before it is
created, so a form sent twice, or a page reloaded, writes nothing new (CLAUDE.md hard rule 5). A use
of more than a portion holds is refused (invariant 15); so is an amount that does not convert to
grams.

Where it is built: `mealplanner/pantry.py` (the bookings; `tests/test_pantry.py`),
`tools/pantry.py` (the same from the terminal), and `pages/pantry.js`, `pages/week.js` and the
bookings section of `pages/common.js` (the same from the pages, which follow the Python function by
function, as the pages' reads do). A household's member books from the pages as themselves, and what
they write is private to their household (`docs/verification-and-sharing.md` §3.4a); the tools write as
the tools' account and then make what they wrote the household's (`mealplanner/ownership.py`). Every node
states its visibility (hard rule 4).

**An item is used up below 0.5 g** (`pantry.USED_UP_G`), what shows as 0 g, and leaves the page and the
tool's list. An amount is stored as it was given, so a Use typed as the rounded figure shown (996 g of
32 fl oz, which is 996.0005 g) leaves a crumb, which used to stay there for good with its expiry.

**A Use within half a gram of what a portion holds is all of it** (2026-11-04), either way: the page and
the tool show whole grams, so 996.6 g shows as "997 g", and a Use of 997 g, which invariant 15 used to
refuse as more than there is, now draws the 996.6 g; a Use of 996 g of 996.4 g draws the 996.4 g rather
than leave a crumb. Half a gram left (100 g of 100.5 g) is still left, as it still shows. More than half a
gram over is refused, and so is a Use of what is used up. The same rule is in `pantry.use` and the pages'
`PANTRY_ACTIONS.use` (`pages/lib/50_pantry.js`), and `tools/check_bookings.py` books one both ways.

A recipe that uses one food in two places draws it twice: the second Allocation from one portion is
named with " #2", the next " #3" (2026-11-22; before that only the first was written).

## Products and barcodes

The owner asked (2026-11-13) for barcode scanning to stock the pantry, as Grocy has, with scanning
optional: "A user should be able to set the specific brand/barcode if they want or default use a
generic version." Its first step was the data, what a barcode means here; the second, 2026-11-23, a
barcode box on the pantry page ("Scanning on the pantry page", below); the third, the same day, a
phone's camera feeding that box ("Scanning with a phone's camera"); the fourth, an unknown barcode
looked up on Open Food Facts ("Looking up an unknown barcode"). The steps still to come are in
`docs/todo.md`, "Barcode scanning for the pantry".

**A product is a packaged food**, written with what the schema has had since `scripts/29a`, so no
instance needs a migration (data-model.md §3, §6, §10: "a GTIN denotes a packaged-offering Type";
J38):

| What | Written as |
|---|---|
| the product ("Brand X chickpeas 400 g") | a `DomainType` in the Food Identity hierarchy, directly below the food it is a kind of |
| each of its barcodes | an `Identifier` in the scheme *GTIN* that `denotesType` it, its value the GTIN as 14 digits |
| what one package holds | a `DefaultSpecification` of kind *PurchaseQuantity* on it (§8) |

Sitting below its food, a product is that food to everything that already walks the hierarchy: a
portion of it counts as stock of the food (the pantry, the shopping list, a cook's draws, the planner),
and it takes the food's density, weight per item, shelf life and price, having none of its own. A
recipe goes on naming the food, never a product: nutrition reads a food's own figures and does not
look above it, so a product has none. A product is optional. The food itself is bought as before, and the pantry page's Buy offers both: it
used to offer every food nothing sits under (a food others sit under is a group, "Eggs" or "Poultry"),
and now offers every food nothing but products sits under, and each product
(`products.buyable`; `tools/check_pages.py` compares the page with it).

Choosing a food in Buy picks its unit (the owner's request, 2026-11-22; `products.buy_unit`): a
product's own, what one package holds; else that of the first size the food, or its nearest ancestor
food, is sold in at the default package level (`docs/packages.md`), so pounds for flour sold in a 5 lb
bag; else grams. A unit Buy does not offer, or one that does not convert to grams for the
food (fluid ounces of a food with no density), is passed over. The unit can still be changed by hand
before adding; typing part of a name changes nothing, and choosing another food picks again.

**What marks a Type as a product is that a GTIN denotes it**, so a product needs at least one barcode.
A brand with no barcode (a butcher's sausages) is bought as its food for now.

**A barcode is read as a GTIN** whatever length is printed (`products.normalize`): a UPC-A (12
digits), an EAN-13, a GTIN-14, an EAN-8, and the short UPC-E on small packages (8 digits starting 0
or 1), which is spelled out to its UPC-A. So the same package scans to the same product from any
scanner. A wrong check digit is refused as misread. So is a number a shop gives its own packs (a UPC-A
starting 2 or 4): it is no product's, and on meat, cheese or produce weighed in the shop it holds
that pack's weight or price.

Products are added on the pantry page as they are scanned (below), or come from a file. Which products a
household buys is its own data, so the owner's file is `private/products.toml`, which git ignores:

```toml
[[product]]
name = "Brand X chickpeas 400 g"      # how it is named in the pantry
food = "Chickpeas (canned)"           # the food it is a kind of
barcodes = ["0 36000 29145 2"]        # one or more; spaces and hyphens are ignored
amount = 400                          # what one package holds
unit = "g"
```

```bash
python3 tools/import_products.py private/products.toml --check   # read the file; write nothing
python3 tools/import_products.py private/products.toml           # load; idempotent
python3 tools/import_products.py --find "0 36000 29145 2"        # the product a barcode names
python3 tools/pantry.py scan 036000291452 2 --storage Pantry     # buy two packages of it
```

Loading refuses, before writing anything, a food the instance does not have, a group of foods, a
product below a product, a name that is already a food, a barcode that belongs to a product the file
does not name, and a package size that does not convert to grams (twelve of a food with no weight per
item). A barcode a product no longer lists is removed; a product the file no longer names is left,
since stock may be of it. `scan` books a Purchase of the product, so many packages of what one holds,
through `pantry.buy`.

Tried on a throwaway instance holding the whole vocabulary (2026-11-13): two products loaded, and
again with nothing written; two dozen eggs scanned were 1,200 g of Egg on hand, with Egg's shelf life;
`check_pages.py` found Buy offering the 297 foods and products `products.buyable` gives, and, with the
page's old rule put back on purpose, named the two foods it then dropped; `check_bookings.py` found the
pages' bookings unchanged.

### Scanning on the pantry page

Step 2 (2026-11-23). Buy has a barcode box. A USB or Bluetooth scanner types into it as a keyboard does
and ends with Enter, which sends it; a barcode can also be typed. Scanning stays optional: Buy by name
works as before.

- **A barcode a product has** fills Buy in with the product and what one package holds (12 each, 400 g),
  read as `products.find` reads it, whatever length is printed. Change the amount for more than one
  package, choose where it is kept, and **Add to pantry**: that is the ordinary purchase. A unit Buy does
  not offer is given in grams, or left for the hand where it does not convert.
- **A barcode no product has** opens **Add a product** with it: a name as on the package, the food it is
  a kind of (any food Buy offers that is no product itself, found as typed: "Choosing the food", below),
  and what one package holds. Adding writes what `products.add_product` writes, which is what the products file would write for
  that product, its package size sourced to the page ("the package, as entered on the pantry page"), and
  Buy is then filled in with it. The same name with a new barcode adds the barcode to that product, and
  writes nothing else: it must be of the same food and hold the same, since a package of another size is
  another product. Nothing is ever taken away from the page; the products file still does that.
- **A misread barcode**, or a shop's own number for a weighed pack, is named as the problem it is.

After a scan the barcode box keeps the cursor, so the next package can be scanned at once; on a plain
visit it does not, so a phone does not open its keyboard every time.

Adding a product writes shared vocabulary (a Type in the Food Identity hierarchy), so it is the page's
alone: the `bookPantry` method, which books for a household as the caller, does not offer it. Like every
page booking it runs once per form (its token) and after the bookings' lock.

Checked: `tests/test_pantry_scan.py` runs the page over a stand-in graph (and reads 400 random barcodes as
`products.normalize` does); `tests/test_products.py` tests `add_product`. On an instance,
`tools/check_bookings.py` adds a product through the page and through Python, a second barcode, the
same form again and two refusals, compares what each wrote field by field, and scans each barcode;
`tools/check_pages.py` scans every product's barcodes, as stored and as printed, against `products.find`.

### Scanning with a phone's camera

Step 3 (2026-11-23; the owner, 2026-11-13: "I definitely want to be able to scan using a phone camera").
Next to the barcode box, **Scan with camera** opens the phone's back camera on the page. Each frame is
read until a product's barcode (EAN-13, EAN-8, UPC-A or UPC-E) is found twice in a row with a right
check digit; the camera then stops, and the barcode goes into the box and is sent, as a scanner that
types would send it. Everything after is the box's: Buy filled in, or "Add a product". **Stop camera**
(the same button) or **Close** stops it, and so does leaving the page.

- **What reads the frames:** the browser's own `BarcodeDetector` where it reads these formats (Chrome on
  Android), else the ZXing reader (`@zxing/library` 0.23.0, Apache 2.0), which the page loads only then.
  Both are files on the instance, not a CDN (`pages/files/`, served at `/mealplanner/` to signed-in
  users only by `tools/install_pages.py`), so scanning works without the internet and tells no one what
  was scanned.
- **HTTPS:** a browser gives a page its camera only over HTTPS or on localhost, so on a phone the pantry
  must be opened at the HTTPS address (`docs/pages.md`, "HTTPS"). Opened over plain HTTP, or with the
  camera refused, the page says why and offers **Photo of the barcode** instead: the phone's camera app
  takes a picture, and the same reader reads it.
- The button appears only where the browser runs the camera script and the two files are installed;
  without them the page is as it was.

Checked: `tests/test_pantry_camera.py` runs the page in Chromium (through Playwright, where node has it)
with a barcode drawn from the EAN-13 tables standing in for the camera: ZXing reads it and the page
sends it through the box; a stand-in `BarcodeDetector` is used where it reads product barcodes, and
ZXing is then not loaded; a code with a wrong check digit is not sent; over `http://` a photo is read
instead. Breaking each of those on purpose failed its test. On a rebuilt instance the files were served
to a signed-in user byte for byte and to no one signed out, and Chromium's stand-in camera on the real
pantry page read the barcode and came back with "No product has barcode 4006381333931 yet". Not tried:
a real phone.

### Looking up an unknown barcode

Step 4 (2026-11-23). When a barcode scanned or typed is no product's, "Add a product" opens with it as
before, and the page asks Open Food Facts what it knows of that barcode
(`pages/files/mealplanner-lookup.js`). It fills in what is still empty:

- **the name**, as the products file names one: the first brand, the product's name (its English name
  where it has one), and the size, "Brand X Chickpeas 400 g", with no brand twice, no size twice, and
  no comma or semicolon (a name cannot hold them);
- **what one package holds**, read from the label's words as Open Food Facts records them ("400 g",
  "6 x 330 ml" is 1,980 ml, "75 cl" is 750 ml, "16 oz (1 lb) 454 g" is 16 oz, "12 eggs" is 12 each), else
  from its own figure in grams or millilitres, in a unit Buy offers;
- **never the food.** Which food a product is a kind of is a judgment (J19), so it is left to the user,
  with the categories Open Food Facts files the product under shown as a hint ("it files it under
  Chickpeas; Legumes"), a link to its page there, and the foods it most likely is offered to tap
  ("Choosing the food", below).

A name typed while the answer was on its way is kept. Where Open Food Facts does not know the barcode,
gives no size the page can use, or does not answer within 10 seconds, the page says so and the form is
filled in by hand, as before. Nothing is written until **Add product**, which writes what it always
has (`products.add_product`), with one difference: a package size kept as Open Food Facts gave it is
sourced there ("Open Food Facts, barcode 00012345678905, as checked on the pantry page"), not to the
package as entered on the page. Changing the amount, the unit or the barcode by hand makes it the page's again
(the form's `source` field; `add_product(..., from_off=True)` in Python).

**What is sent, and to whom.** The look-up runs in the browser, not on Structr, so the instance needs no
internet and never calls out; the phone does, once per unknown barcode, to
`world.openfoodfacts.org/api/v2/product/<barcode>.json` with the fields it reads. It sends the
barcode and nothing of the instance: no cookie, no referrer (the browser still sends its own address
and, as every cross-site request does, the instance's address as its origin). A barcode a product
already has, a plain visit, and a refused form send nothing. So scanning a known product still tells
no one; adding a new one tells Open Food Facts that someone looked its barcode up.

**Its data.** Open Food Facts is a crowd-sourced database under the Open Database License (ODbL). What a
look-up fills in is one product's name and size, written to this instance only (never to the
repository), checked by the user, and credited by its `source`; the share-alike terms bind a
substantial extract, such as the pinned file `docs/packages.md` declined.

Checked: `tests/test_pantry_lookup.py` reads label sizes and builds names in node, each expected value
worked out by hand; draws the page over a stand-in graph (the barcode marked for a look-up only where no
product has it and the file is installed; a size kept from Open Food Facts sourced there, any other
`source` the page's); and runs the page in Chromium with Open Food Facts answered by the test: what is
filled in and what is left (the food, a name typed while waiting), a size or barcode changed by hand, a product
with no size and with HTML in its name (shown as words), an unknown barcode, no answer, and that the one
request carries the barcode alone, with no cookie and no referrer, and that no request is made for a
known barcode or a plain visit. Breaking each of those on purpose failed its test. On a rebuilt
instance, `tools/check_bookings.py` adds a product sized from Open Food Facts through the page and
through `add_product(from_off=True)` and compares them field by field (with Python's side not sourced to
Open Food Facts on purpose, it named the `source` that differed); and Chromium on the real pantry page,
with Open Food Facts stood in for, filled the form in, sent the barcode alone, and **Add product** wrote
the product with its size sourced there. Not tried: the real Open Food Facts, whose site the cloud
session that built this could not reach, so whether it answers a browser's cross-site request (it is
documented to) is to be seen on the owner's phone.

### Choosing the food

The owner, 2026-11-23, adding a product: the food box asks for "the food it is", and "that's impossible
to guess". A food is named exactly as this instance names it ("Chickpeas (canned)", "Peanut butter
(creamy)"), and the page is sent with that name or it is refused. The box used to leave the choice to the
browser's own list of every name (a datalist), which a phone shows poorly, if at all, for some 300 foods.

Both food boxes, Buy's and "Add a product"'s, now search as you type (`pages/files/mealplanner-foods.js`):
each word typed may be the start of any word of a name, in any order, in any case, singular or plural, so
"chick" finds the chicken and the chickpeas and "canned chickpea" or "TOMATOES DICED" finds the one. Up
to eight are shown under the box, a name that begins as typed first, then shorter names; a tap puts the
name in the box (in Buy it then picks the unit, as choosing from the list did), and Enter takes the first.
A whole name typed in other letter case is put right when the form is sent; anything else is sent as typed
and refused as before. Without the script, the browser's list is left as it was.

Under "Add a product", a product Open Food Facts knows also shows **Likely:** and the foods it most likely
is, to tap. A food is offered when each word of its name outside brackets is a word of the product's
categories or its name (singular or plural); one is likelier with more such words, when the categories
hold them all, and with each word in its brackets they hold ("canned" in "Chickpeas (canned)"), and one far
less likely than the likeliest is left out ("Butter (salted)" beside "Peanut butter (creamy)"). It is a
list to tap, never a choice made: the box stays empty until the user taps or types, since a wrong food
would give the product that food's nutrition and shelf life.

Checked: `tests/test_pantry_foods.py` runs the search and the guess in node over names chosen for it, each
expected value worked out by hand from the rules above, and the page in Chromium: typing in Buy finds a
product and a tap fills it in and picks its unit; "Add a product" offers only foods a product may be, and
says when nothing matches; Enter takes the first; a name in other case is sent as the instance spells it;
a looked-up product's likely foods are offered and the box left empty until one is tapped, and none are
offered when Open Food Facts cannot be reached. Breaking each of those on purpose failed its test.

What is left, each in `docs/todo.md`: a product's own label nutrition (FDC's branded foods carry
the same GTINs); where a product is kept by default (a scan books to the fridge unless `--storage` says
otherwise, as Buy does); and a shop's own weighed packs.

## Ticking the shopping list

Built 2026-11-24 (`docs/todo.md`, "A grocery item checked off goes into the pantry"; plan 1 of
`docs/time-savings-plans.md`, which the owner approved to build on 2026-11-23). The time study found that
entering every purchase a second time on the pantry page was the app's biggest time cost.

**How it works.** The shopping page's tick boxes are still kept in the browser, so a list can be ticked in
the shop without a connection. One button, **Put ticked items into the pantry** (above and below the list),
then books every ticked line as a purchase. Each line is booked on its own, with a token of its own (the
form's and the line's number), so one line that cannot be booked does not stop the rest, and a form sent
twice books nothing twice. Booked lines leave the list, since the pantry now covers them, and their ticks
are cleared.

**What a line books** (`pantry.buy_line`, `PANTRY_ACTIONS.bought` in `pages/lib/50_pantry.js`):

- **Its whole packages, each a portion of its own**, in a container of its own (the line's `pieces`,
  `shopping.Line.pieces`): two cans of tomatoes are two portions, so that opening one (the owner's
  first-use rule) does not open the other. A line bought loose or by count (300 g of onion, 2 lemons) is
  one portion. The first portion is named as Buy names one, `Purchase <token> -- <food>`; the others
  `... #2`, `... #3`.
- **At the grams a recipe weighs them.** A bag of onions goes in as its edible part (a 1 lb bag as 408 g
  at a 10% trim), so stock bought from the list no longer counts the skins, as Buy by weight still does
  (`docs/packages.md`).
- **Kept where the food usually goes** (since 2026-11-25: the person's own place for it, their household's or
  everyone's, below, "Where each food goes"), and with none of those **where the food keeps**
  (`pantry.default_storage`, `storageFor`): in the freezer for a food sold
  frozen (its name, or the name of a food above it, says so: *Frozen green peas*); otherwise where the
  pantry already takes a portion in no container to be kept (J31): of the fridge and the pantry, where its
  food keeps longest unopened by FoodKeeper, the fridge on a tie or with neither. So potatoes, garlic,
  bread and flour go to the pantry, and milk, grapes and herbs to the fridge.
  The plan's first wording (frozen foods where FoodKeeper gives only a freezer time; the pantry where it
  gives any pantry time) was not used: the pinned FoodKeeper rows give whole milk and fresh tomatoes only a
  freezer time, and give grapes a pantry time of one day, so it would have frozen the milk and left the
  grapes out. **For the owner to confirm.**
- **Its perishability class** as Buy takes one: the latest portion's of the food.

**Changing a line first.** Each line has a **Change** with: a product of the line's food (one with a
package size), and how many packages of it (left empty, enough to cover what the line needs); or other
grams in all, as one portion; and where it is kept. A product bought is stock of its food (J38), so the
week's meals draw on it as they would on the food.

**Taking a purchase back** (`pantry.unbuy`, `PANTRY_ACTIONS.unbuy`). Each line booked shows **Undo**, and
the page lists what that browser has put away from the week's list for 14 days, each with **Undo**. An undo
is refused, with the reason, once anything rests on the purchase: some of it used (a Use, a cook, a
discard, a reservation's draw), weighed again, opened or moved. After that a Use, a Count or a Discard
corrects it. Otherwise, as the owner decided on 2026-11-23 (`docs/todo.md`, "Undo a booking"), **a record
of every node the purchase wrote is kept first**, as JSON in a Structr file named `undone Purchase
<token> <time>.json`, private to the household (readable by its members, by no other household), and then
the nodes are deleted. Each node is recorded with its type, id, name and the fields the purchase wrote
(`pantry.RECORD_KEYS`), so it can be made again. A household member may undo another member's purchase,
since a household's bookings are granted to its Group with delete; making that the household's own setting
is part of "Undo a booking". A purchase made on the pantry page's Buy can be undone the same way by its
token (`tools/pantry.py unbuy TOKEN`), though only the shopping page offers the button.

**Checked** (2026-11-24, on a cloud throwaway stack): `tests/test_pantry_bought.py` (16 tests: the pieces,
where each food is kept, a product's packages, what is refused, an undo and its record, an undo refused after
a use, a count or a move; breaking the frozen rule, the separate containers, the undo's check for a use, or
the pieces each failed them); the pieces in `tests/test_packages.py` and `tests/test_yields.py`;
`tools/check_bookings.py` books three ticked lines through the page and through Python (one as listed, one
with other grams and the freezer, one as a product in three packages), compares every node, sends the form
again, and undoes one each way, comparing what was deleted and the record (renaming the page's second
package failed it); `tools/check_pages.py` compares each line's pieces with Python's;
`tools/check_households.py` books a ticked line as a member of household A (private to A), refuses B's
member taking it back, lets A's other member, and keeps the record A's. Seen in a browser at phone width.

**Not yet:** scanning a barcode on the shopping page to match a line; a product's own default place (barcode
step 6: a product takes its food's remembered place, below); ticks shared between a household's phones (they are kept in each browser); and the bookings without
a page reload (plan 2).

## Where each food goes

Built 2026-11-25, at the owner's word (asked "Can individuals set a default storage location for foods?", then
"Yes" to a remembered place that inherits as remembered amounts are to: the person's own, then the
household's, then everyone's; `mealplanner/places.py`, `pages/lib/57_places.js`). It is the first remembered
value built; remembered amounts (`docs/todo.md`, "Scanning an item as it is used") can follow the same shape.

**Where a purchase goes.** A purchase that does not say where (Buy with "where it usually goes", a ticked
shopping line not changed, "Bought this instead" left as it is, `tools/pantry.py buy` without `--storage`) goes
to the food's **usual place** for the person who books it: the first of their own place for it, their
household's, everyone's; with none, the rule above (frozen by name, else the fridge or the pantry, whichever
FoodKeeper says keeps it longer). The food is the one bought, or for a product the food it is a product of
(a brand keeps where its food does); where none of the levels has a place for it, each food above it is
asked the same way, nearest first, as a price is found (`prices.food_price`): the person's own place for
potatoes does not override the household's for new potatoes. The Buy form names the usual place once the
food is known (from a scan), and a shopping line's **Change** names it for its food: "the freezer (yours)",
"(your household's)", "(everyone's)" or "(the usual rule)". `tools/pantry.py places [FOOD]` lists them.

**When a place is remembered.** When a person picks the place themselves: on Buy, on a shopping line's
**Change** before it is put away, on "Bought this instead", or by moving something within a day of buying it
(`places.FRESH_HOURS`, 24), which corrects where it was put away. A move later than that (freezing what is
about to go off) is not a habit and remembers nothing. A place the levels and the rule already give writes
nothing. Otherwise, following the owner's rule that new shared knowledge reaches everyone when it overrides
nothing (`docs/todo.md`, "New shared data reaches every user at once"):

1. where everyone's level has no place for the food, the choice becomes everyone's;
2. where the household's has none, it becomes the household's;
3. then, if the levels above the person now say what they picked, they keep no place of their own (one they
   had is forgotten, so they follow the household again); otherwise it is their own.

So the first person to put potatoes in the fridge sets everyone's and their household's place, and a
housemate who then keeps them in the pantry has that as their own place, without changing anyone else's. A
household's or everyone's place someone else gave is never changed by a booking; changing everyone's is a
suggestion to curate (`docs/verification-and-sharing.md` §3.6), not built.

**How it is stored** (data-model.md J43; no schema change). As prices and package sizes are: a level is a
`DomainType` in the hierarchy *Storage Place Reference*, and a remembered place is a `DefaultSpecification`
of kind *Storage Place* on a level, keyed by the food, whose `targetType` is *Fridge*, *Freezer* or *Pantry*,
its `source` "chosen by" the person.

| Level | Seen by |
|---|---|
| *Storage places -- everyone* (`scripts/52a` makes it) | every signed-in user; written as the superuser, as a new product is |
| *Storage places -- household \<name\>*, under everyone's | the household's members, who read and change it (its Group's grant) |
| *Storage places -- person \<name\>*, under their household's (under everyone's with no household) | the person, who reads and changes it; their household reads it |

A household's and a person's levels are made by the booking that first needs them, private as above; one
written by a tool (`tools/pantry.py --by`) is made so by `mealplanner/ownership.py` (`claimHousehold` finds a
person's level by its name).

**Checked** (2026-11-25, on a cloud throwaway stack): `tests/test_places.py` (11 tests, worked out by hand:
the rule alone, a first choice shared and a second the person's own, forgotten when it agrees, the nearest
food before the nearest level, a product remembered for its food, a move within a day and not after, nothing
remembered without a person or before `scripts/52a`; breaking the forgetting, the 24 hours, the filling of
everyone's or the household's level, or the order of the lookup each failed them); `tests/test_ownership.py`
(a person's level theirs, the household's its own, everyone's shared); `tools/check_bookings.py` remembers
through the page and through Python from the same starting places and compares every node (a source changed
on the page, or the forgetting taken out, failed it); `tools/check_households.py`: A1's first choice is
everyone's and A's, A's private to A; A2's own place A1 reads and cannot change and B cannot see; a purchase
that picks nothing goes to A1's household's place, A2's own and B1's everyone's; B's choice is B's alone (a
person's place granted to their household to write failed it).

**Not yet:** a page to see and forget one's places (the tool lists them); a product's own place, apart from
its food's; changing a household's or everyone's place except by removing it; the shopping list's "keeps
until" for what is left over still reads the rule, not the usual place; a Grocy import, which names no
person, remembers nothing.

## What does not fit yet

These are findings, recorded rather than worked around (CLAUDE.md, "When something doesn't fit").

1. **Thawing has nowhere to go.** Storage condition is a static tag (CLAUDE.md, out of scope), so a
   portion's shelf life is read as if it had always been kept where it is now. Freezing is
   therefore roughly right (a few days in the fridge first are counted as frozen), but moving a
   portion back to the fridge dates its fridge shelf life from the purchase, so food frozen for a
   month shows as expired the moment it thaws. Grocy restarts the clock on thawing. Here that would
   be a thawing Process from which a new portion begins to exist, as a portion divided off a larger
   one does (`inventory.origin_time`'s known limit); that is modeling thawing as a transformation,
   which §13 declined, so it is the owner's call.
2. **Opening does not restart the clock either.** The *Opened* shelf life also runs from the
   purchase: milk bought a week ago and opened today expires as if opened a week ago. That is
   conservative, and it is what `inventory.instance_expiration` already did.
3. **A printed best-before date cannot be recorded.** Invariant 2 lets a `Measurement` be about a
   Quality *or a Disposition* (the shelf-life Disposition every food object bears, §5), but the
   built schema's `isAboutQuality` reaches Qualities only. So expiry comes from a Perishability
   Class's defaults or not at all. Recording the date would need that relationship to reach
   `Disposition`, a schema change.
4. ~~**Most foods have no Perishability Class, so most expiries are unknown.**~~ Answered by
   FoodKeeper (2026-10-24, data-model.md J31): each food now carries USDA FoodKeeper's shelf lives,
   which come before a class's; a class serves a food FoodKeeper gives no time for. Nine foods
   FoodKeeper sends to the package's printed date still have none (point 3).
5. **A cook's leftovers are not stock.** Recipes store no output mass (J28), so a cook writes no
   leftover portion; leftovers stay where the planner keeps them, as leftover entries of the week.
6. **Not built yet:** undoing a booking (Grocy's journal), a journal on the page, prices paid
   (`PriceObservation` exists in the schema but nothing writes one: J27), minimum stock on the page
   (StockPolicy target levels are applied by `tools/shopping_list.py` only), and a product's best-before date
   scanned or read from its label (point 3).

An Allocation's amount is an `observed` Measurement about no Quality, as in data-model.md §10 and
`scripts/15e`: about the portion's mass Quality it would be read as a new weighing. Invariant 2
says every Measurement is about one Quality; the draws have never met it.
