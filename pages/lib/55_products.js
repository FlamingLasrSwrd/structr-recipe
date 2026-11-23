// Products and their barcodes (mealplanner/products.py; docs/pantry.md, "Products and barcodes"): a
// barcode read as its GTIN, the product it names, and a product added from the pantry page.

const GTIN_SCHEME = "GTIN", IDENTIFIER_SCHEME = "Identifier Scheme";
const PAGE_SOURCE = "the package, as entered on the pantry page";       // products.PAGE_SOURCE
const SHOP_PREFIXES = ["02", "04", "2"];
// The pantry page's camera and the barcode reader it loads where the browser has none (pages/files/, served
// from /mealplanner/ by tools/install_pages.py)
const CAMERA_FILE = "mealplanner-camera.js", READER_FILE = "zxing-library-0.23.0.min.js";
// and its look-up of an unknown barcode on Open Food Facts (docs/pantry.md, "Looking up an unknown barcode")
const LOOKUP_FILE = "mealplanner-lookup.js";

// products.off_source: where a package size taken from Open Food Facts on the pantry page is sourced
const offSource = (gtin) => "Open Food Facts, barcode " + gtin + ", as checked on the pantry page";

// products.check_digit: from the right, the other digits weigh 3, 1, 3, ...
function checkDigit(digits) {
  let total = 0;
  for (let i = 0; i < digits.length; i++) total += Number(digits[digits.length - 1 - i]) * (i % 2 === 0 ? 3 : 1);
  return (10 - total % 10) % 10;
}

// products._upc_a_of: a UPC-E spelled out to the UPC-A it shortens
function upcAOf(e) {
  const n = e[0], d = e.slice(1, 7), check = e[7];
  let body;
  if ("012".indexOf(d[5]) >= 0) body = d.slice(0, 2) + d[5] + "0000" + d.slice(2, 5);
  else if (d[5] === "3") body = d.slice(0, 3) + "00000" + d.slice(3, 5);
  else if (d[5] === "4") body = d.slice(0, 4) + "00000" + d[4];
  else body = d.slice(0, 5) + "0000" + d[5];
  return n + body + check;
}

// products.normalize: a barcode as its GTIN in 14 digits, or a BookingError saying what is wrong with it,
// in Python's words
function normalizeBarcode(barcode) {
  const shown = "'" + String(barcode == null ? "" : barcode) + "'";
  let text = String(barcode == null ? "" : barcode).replace(/[ -]/g, "");
  if (!/^[0-9]+$/.test(text)) throw new BookingError("barcode " + shown + " is not a number");
  if ([8, 12, 13, 14].indexOf(text.length) < 0) {
    throw new BookingError("barcode " + shown + " has " + text.length + " digits: a product's has 8, 12, 13 or 14");
  }
  if (text.length === 8 && "01".indexOf(text[0]) >= 0) text = upcAOf(text);
  const check = checkDigit(text.slice(0, -1));
  if (check !== Number(text[text.length - 1])) {
    throw new BookingError("barcode " + shown + " is misread or mistyped: its last digit should be " + check);
  }
  const gtin = ("00000000000000" + text).slice(-14);
  if (text.length === 8 ? text[0] === "2" : SHOP_PREFIXES.some((p) => gtin.slice(1).startsWith(p))) {
    throw new BookingError("barcode " + shown + " is a shop's own number for a pack (often with its weight or price in it), "
                           + "not a product's");
  }
  return gtin;
}

// products.product_ids: the Types a GTIN denotes, by id
function productIds() {
  const ids = {};
  for (const code of (($.find("Concept", {name: GTIN_SCHEME})[0] || {}).identifiersInScheme || [])) {
    if (code.denotesType) ids[code.denotesType.id] = true;
  }
  return ids;
}

// The GTIN Identifiers holding this value
const gtinRows = (gtin) => $.find("Identifier", {identifierValue: gtin})
  .filter((r) => r.type === "Identifier" && r.identifierScheme && r.identifierScheme.name === GTIN_SCHEME);

// products.find: what a barcode names: {gtin, product, food, amount, unit}, product null where no product
// has it; a BookingError for what is no product's barcode at all, or one two products share
function findProduct(barcode) {
  const gtin = normalizeBarcode(barcode);
  const rows = gtinRows(gtin).filter((r) => r.denotesType);
  if (!rows.length) return {gtin: gtin, product: null, food: null, amount: null, unit: null};
  if (rows.length > 1) {
    throw new BookingError("barcode " + gtin + " names " + rows.length + " products: "
                           + rows.map((r) => r.denotesType.name).sort().join(", "));
  }
  const product = rows[0].denotesType;
  const size = resolveDefault(product, PACKAGE_KIND, []);
  const held = size && size.hasValue;
  return {gtin: gtin, product: product.name, food: product.parent ? product.parent.name : null,
          amount: held ? held.value : null, unit: held ? held.unit : null};
}

// products.add_product: a barcode added from the pantry page to the product of a name, made below a food
// and holding what one package holds where it is new. It never takes a barcode away and changes nothing
// of a product that exists. Every problem is named before anything is written, as products.py does.
// Shared vocabulary the household's own bookings do not write, so it is the page's alone (not bookPantry's).
const PRODUCT_ACTIONS = {
  product: (booking, r) => {
    if (booking.household) throw new BookingError("a product is added on the pantry page");
    const name = String(r.name || "").trim(), foodName = String(r.food || "").trim();
    const unit = String(r.unit || "").trim().toLowerCase();
    const amount = r.amount == null || r.amount === "" ? NaN : Number(r.amount);
    if (!name) throw new BookingError("a product has no name");
    // products.parse_products
    const problems = [];
    if (/[,;]/.test(name)) problems.push(name + ": a name cannot hold a comma or a semicolon");
    if (!foodName) problems.push(name + ": it names no food");
    else if (foodName === name) problems.push(name + ": a product is named apart from its food");
    if (!(amount > 0) || !isFinite(amount)) problems.push(name + ": what a package holds (amount) must be more than 0");
    if (!Object.prototype.hasOwnProperty.call(UNIT_TABLE, unit)) {
      problems.push(name + ": unit '" + unit + "' is not one of " + Object.keys(UNIT_TABLE).sort().join(", "));
    }
    let gtin = null;
    try { gtin = normalizeBarcode(r.barcode); } catch (e) { problems.push(name + ": " + e.message); }
    if (problems.length) throw new BookingError(problems.join("; "));
    // products.import_products, and add_product for a product that exists
    const products = productIds();
    const typed = (n) => $.find("DomainType", {name: n}).filter((t) => t.type === "DomainType");
    const food = typed(foodName).filter((t) => t.hierarchy && t.hierarchy.name === "Food Identity")[0] || null;
    const mine = typed(name)[0] || null;
    const isMine = mine && products[mine.id];
    const held = (other) => gtinRows(gtin).filter((row) => row.denotesType && (!other || row.denotesType.id !== other.id))
      .forEach((row) => problems.push(name + ": barcode " + gtin + " already belongs to '" + row.denotesType.name + "'"));
    if (isMine) {                           // products.add_product, for a product that exists
      const parent = mine.parent ? mine.parent.name : null;
      if (parent !== foodName) problems.push(name + ": it is a product of '" + parent + "' already, not of '" + foodName + "'");
      const size = resolveDefault(mine, PACKAGE_KIND, []), holds = size && size.hasValue;
      if (!holds) problems.push(name + ": no package size is known for it");
      else if (holds.value !== amount || holds.unit !== unit) {
        problems.push(name + ": one package of it holds " + holds.value + " " + holds.unit + " already; a package of another "
                      + "size is another product, so name it apart");
      }
      held(mine);
    } else if (!food) {                     // products.import_products, for a new one
      problems.push(name + ": '" + foodName + "' is not a food of this instance");
    } else if (products[food.id]) {
      problems.push(name + ": '" + foodName + "' is a product itself; name the food it is a kind of");
    } else {
      const others = (food.children || []).filter((c) => !products[c.id]).map((c) => c.name).sort();
      if (others.length) {
        problems.push(name + ": '" + foodName + "' is a group of foods (" + others.slice(0, 3).join(", ")
                      + (others.length > 3 ? ", ..." : "") + "), not a food that is bought");
      }
      if (mine) problems.push(name + ": that name is already a food here, not a product");
      held(null);
      if (toGrams(food, amount, unit) == null) {
        problems.push(name + ": " + amount + " " + unit + " of " + foodName + " does not convert to grams "
                      + "(the food has no density or weight per item)");
      }
    }
    if (!isMine && $.find("DomainType", {name: PACKAGE_KIND}).length !== 1) {
      problems.push("this instance has no '" + PACKAGE_KIND + "' kind of default (scripts/05_seed_vocabulary.py makes it)");
    }
    if (problems.length) throw new BookingError(problems.join("; "));

    const scheme = ensureNode(booking, "ConceptScheme", IDENTIFIER_SCHEME, {});
    const gtins = ensureNode(booking, "Concept", GTIN_SCHEME, {inScheme: scheme});
    const product = isMine ? mine : ensureNode(booking, "DomainType", name, {hierarchy: food.hierarchy, isLookupBearing: true,
                                                                              parent: food});
    const code = ensureNode(booking, "Identifier", GTIN_SCHEME + " " + gtin, {identifierValue: gtin, identifierScheme: gtins,
                                                                              denotesType: product});
    if (!code.denotesType) {                // one left by a product since deleted: this product's now
      code.identifierValue = gtin;
      code.identifierScheme = gtins;
      code.denotesType = product;
      booking.created.push(code.name);
    }
    if (!isMine) {
      const size = ensureNode(booking, "QuantitySpecification", name + " package size value", {value: amount, unit: unit,
                                                                                             status: "default"});
      ensureNode(booking, "DefaultSpecification", name + " package size", {forType: product, hasKind: typeNamed(PACKAGE_KIND),
                                                                           hasValue: size, provenance: "sourced",
                                                                           source: r.source === "off" ? offSource(gtin) : PAGE_SOURCE});  // add_product's from_off
    }
    booking.notes.push(booking.created.length ? name + " (" + foodName + ", " + amount + " " + unit + " a package) has barcode " + gtin + "."
                                              : name + " had barcode " + gtin + " already, so nothing new was written.");
  },
};
