// The pantry's bookings (mealplanner/pantry.py): its page's forms, and the bookPantry method.

const STORAGE = ["Fridge", "Freezer", "Pantry"];
const UNITS = ["g", "kg", "oz", "lb", "ml", "l", "cup", "tbsp", "tsp", "fl_oz", "each"];

// pantry._grams
function bookingGrams(food, amount, unit) {
  if (!(amount > 0) || !isFinite(amount)) throw new BookingError(food.name + ": an amount must be a number more than 0");
  const grams = toGrams(food, amount, unit);
  if (grams == null) throw new BookingError(food.name + ": " + amount + " " + unit + " does not convert to grams (no density or weight per item for it)");
  return grams;
}

// A household's booking acts on its own stock only: what is private to it. Stock every signed-in user
// sees belongs to no household (the data made before households kept theirs apart), so a household
// neither draws on it nor books on it (docs/methods.md).
const ownStock = (booking, portion) => !booking.household || portion.visibleToAuthenticatedUsers === false;

function portionFrom(request, booking) {
  const found = $.find("PortionOfSubstance", {id: String(request.portion || "")});
  const portion = Array.isArray(found) ? found[0] : found;
  if (!portion || portion.type !== "PortionOfSubstance") throw new BookingError("no such portion");
  if (!ownStock(booking, portion)) throw new BookingError(portion.name + ": not your household's stock");
  return portion;
}

function amountFrom(request) {
  const amount = Number(request.amount);
  if (request.amount == null || request.amount === "" || !isFinite(amount)) throw new BookingError("an amount is a number");
  return amount;
}

// pantry.last_perishability
function lastPerishability(food) {
  let best = null;
  for (const p of $.find("PortionOfSubstance")) {
    if (!p.instanceOf || p.instanceOf.id !== food.id || !p.hasPerishabilityType) continue;
    const key = p.createdDate ? new Date(p.createdDate).toISOString() : "";
    if (!best || key > best[0]) best = [key, p.hasPerishabilityType];
  }
  return best ? best[1] : null;
}

// pantry._opened_by_use: the first use of a sealed portion opens it (the owner's rule, 2026-11-23), so its
// Opened shelf life applies from then on; one that is used up needs no opening
function openedByUse(booking, portion) {
  const box = containerOf(booking, portion);
  if (box.hasOpenedStatus && box.hasOpenedStatus.name === "Opened") return;
  box.hasOpenedStatus = typeNamed("Opened");
  booking.notes.push(portion.name + ": opened by this use.");
}

// pantry._container
function containerOf(booking, portion) {
  if (portion.locatedIn) return portion.locatedIn;
  const box = ensureNode(booking, "ContainerObject", portion.name + " container", {
    hasStorageCondition: typeNamed("Fridge"), hasOpenedStatus: typeNamed("Sealed")});
  portion.locatedIn = box;
  return box;
}

// pantry._purchase: a Purchase Process and, for each [amount, unit], a sealed portion of the food in a container of
// its own kept in `storage`, with its mass bought: the first named "Purchase <token> -- <food>", as Buy names its
// one, the rest "... #2", "... #3". The portions.
function bookPurchase(booking, food, amounts, storage, keeps, token) {
  const process = bookProcess(booking, "Purchase", "Purchase " + token, NOW);
  return amounts.map(([amount, unit], i) => {
    const name = "Purchase " + token + " -- " + food.name + (i ? " #" + (i + 1) : "");
    const box = ensureNode(booking, "ContainerObject", name + " container", {
      hasStorageCondition: typeNamed(storage), hasOpenedStatus: typeNamed("Sealed")});
    const portion = ensureNode(booking, "PortionOfSubstance", name, {
      instanceOf: food, beginsToExistDuring: process, locatedIn: box, hasPerishabilityType: keeps});
    const quality = ensureNode(booking, "Quality", name + " mass Quality", {hasKind: typeNamed("Mass"), inheresIn: portion});
    ensureNode(booking, "Measurement", name + " mass bought", {value: amount, unit: unit, status: "observed",
                                                              hasTime: stamp(NOW), isAboutQuality: quality});
    return portion;
  });
}

// buy's note where no expiry can be told for a purchase
function noShelfLife(booking, food, keeps, storage, hint) {
  const shelf = resolveDefault(food, "ShelfLife", [typeNamed(storage).id, typeNamed("Sealed").id]);
  if (!keeps && !(shelf && shelf.hasValue && shelf.hasValue.unit === "days" && shelf.hasValue.value != null)) {
    booking.notes.push(food.name + ": no shelf life known for it in the " + storage.toLowerCase() + ", so no expiry" + hint);
  }
}

// pantry.FROZEN, pantry.MAX_PIECES
const FROZEN = /\bfrozen\b/i, MAX_PIECES = 99;

// pantry.default_storage: where a purchase from the shopping list is put away when the line does not say: in the
// freezer for a food sold frozen (its name, or a food's above it, says so), else where a portion in no container is
// taken to be kept (assumedStorage, J31)
function storageFor(food) {
  for (const t of ancestorsOrSelf(food)) if (FROZEN.test(t.name || "")) return "Freezer";
  return assumedStorage({instanceOf: food});
}

// pantry.buy_line: `pieces` the grams of each package, each a portion in a container of its own; kept in `storage`,
// else where storageFor says. The portions it wrote. "Bought something else" books its purchase through this too.
function bookBought(booking, food, pieces, token, storage) {
  if (storage != null && STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", ") + ", not '" + storage + "'");
  if (!pieces.length) throw new BookingError(food.name + ": nothing to put away");
  if (pieces.length > MAX_PIECES) throw new BookingError(food.name + ": " + pieces.length + " packages on one line is more than " + MAX_PIECES);
  if (pieces.some((g) => typeof g !== "number" || !isFinite(g) || !(g > 0))) {
    throw new BookingError(food.name + ": each package must weigh a number of grams more than 0");
  }
  const where = storage || storageFor(food);
  const keeps = lastPerishability(food);
  const portions = bookPurchase(booking, food, pieces.map((g) => [Math.round(g * 1e6) / 1e6, "g"]), where, keeps, token);
  booking.notes.push(food.name + ": " + (pieces.length > 1 ? pieces.length + " packages, " : "")
                     + number(pieces.reduce((s, g) => s + g, 0), 0) + " g, kept in the " + where.toLowerCase());
  noShelfLife(booking, food, keeps, where, "");
  return portions;
}

// pantry.line_purchase: what a shopping line's form asks to book: {food (the DomainType), pieces (grams each)}. The line's
// own packages (`pieces`, comma-separated grams), or `grams` bought instead, as one piece; or a product of the line's
// food chosen instead (`product`), so many packages (`count`, else enough to cover `buy` grams) of what one holds
function linePurchase(r) {
  const food = typeNamed(String(r.food || "").trim());
  const asked = (v) => v != null && String(v).trim() !== "";
  if (asked(r.product)) {
    const product = typeNamed(String(r.product).trim());
    if (!productIds()[product.id] || !ancestorsOrSelf(product).some((t) => t.id === food.id)) {
      throw new BookingError(product.name + ": not a product of " + food.name);
    }
    const size = resolveDefault(product, PACKAGE_KIND, []), held = size && size.hasValue;
    const each = held ? toGrams(product, held.value, held.unit) : null;
    if (!(each > 0)) throw new BookingError(product.name + ": no package size is known for it, so give the grams bought instead");
    let count;
    if (asked(r.count)) {
      count = Number(r.count);
      if (!(count >= 1) || Math.floor(count) !== count) throw new BookingError(product.name + ": the number of packages is a whole number, 1 or more");
    } else {
      const need = Number(r.buy);
      count = Math.max(1, Math.ceil((isFinite(need) ? need : 0) / each - 1e-9));
    }
    if (count > MAX_PIECES) throw new BookingError(product.name + ": " + count + " packages on one line is more than " + MAX_PIECES);
    return {food: product, pieces: Array(count).fill(each)};
  }
  if (asked(r.grams)) return {food: food, pieces: [Number(r.grams)]};
  return {food: food, pieces: String(r.pieces == null ? "" : r.pieces).split(",").filter((p) => p.trim() !== "").map(Number)};
}

// pantry.RECORD_KEYS: what an undone purchase's record keeps of each node, so that it can be made again
const RECORD_KEYS = {
  TemporalRegion: ["hasBeginning"],
  Process: ["hasKind", "occupiesTemporalRegion", "wasAssociatedWith"],
  ContainerObject: ["hasStorageCondition", "hasOpenedStatus"],
  PortionOfSubstance: ["instanceOf", "beginsToExistDuring", "locatedIn", "hasPerishabilityType"],
  Quality: ["hasKind", "inheresIn"],
  Measurement: ["value", "unit", "status", "hasTime", "isAboutQuality"],
};
// pantry._recorded
function recorded(node) {
  const ref = (v) => Array.isArray(v) ? v.map(ref) : (v && typeof v === "object" ? {id: v.id, name: v.name} : v);
  const out = {type: node.type, id: node.id, name: node.name};
  for (const key of RECORD_KEYS[node.type]) {
    const v = node[key];
    out[key] = v == null || (Array.isArray(v) && !v.length) ? null : ref(v);
  }
  return out;
}

// pantry.purchase_nodes: what the purchase of this token wrote, in the order it is deleted, or a BookingError saying
// why it cannot be taken back
function purchaseNodes(booking, token) {
  if (!/^[0-9a-f]{4,16}$/.test(token)) throw new BookingError("no purchase Purchase " + token);
  const found = $.find("Process", {name: "Purchase " + token}).filter((n) => n.type === "Process" && ownStock(booking, n));
  if (found.length !== 1) throw new BookingError(found.length ? "two purchases named Purchase " + token
                                                              : "no purchase Purchase " + token + " (taken back already?)");
  const process = found[0];
  if (!process.hasKind || process.hasKind.name !== "Purchase") throw new BookingError("Purchase " + token + " is not a purchase");
  const nodes = [];
  const portions = (process.thingsBegunDuring || []).slice().sort((a, b) => (String(a.name) < String(b.name) ? -1 : String(a.name) > String(b.name) ? 1 : 0));
  for (const portion of portions) {
    if (portion.type !== "PortionOfSubstance") throw new BookingError("Purchase " + token + ": " + portion.name + " is no portion of food, so it is not undone here");
    if (!ownStock(booking, portion)) throw new BookingError(portion.name + ": not your household's stock");
    if ((portion.allocationsAbout || []).length) throw new BookingError(portion.name + ": some of it has been used, so it stays (use Count or Discard instead)");
    if ((portion.processesWithParticipant || []).length) throw new BookingError(portion.name + ": weighed, opened or moved since, so it stays (use Count or Discard instead)");
    const quality = massQuality(portion);
    const measurements = quality ? (quality.measurements || []) : [];
    if (measurements.some((m) => m.name !== portion.name + " mass bought")) throw new BookingError(portion.name + ": weighed since, so it stays (use Count or Discard instead)");
    nodes.push(...measurements);
    if (quality) nodes.push(quality);
    nodes.push(portion);
    const box = portion.locatedIn;
    if (box && box.name === portion.name + " container") nodes.push(box);
  }
  nodes.push(process);
  const region = process.occupiesTemporalRegion;
  if (region && region.name === "Purchase " + token + " time") nodes.push(region);
  return nodes;
}

// pantry.record_name
const recordName = (token, when) => "undone Purchase " + token + " " + when.toISOString().replace(/[-:]/g, "").slice(0, 15) + ".json";

// pantry.unbuy: the purchase of this token taken back while nothing rests on it. First a record of every node it wrote
// is kept, as text in a file private to the household (the owner's decision, 2026-11-23: docs/todo.md "Undo a
// booking"), then each node is deleted. `booking.created` lists what was deleted
function unbuyPurchase(booking, token) {
  const nodes = purchaseNodes(booking, token);
  const record = {undone: "Purchase " + token, at: stamp(NOW), by: BOOKED_BY, nodes: nodes.map(recorded)};
  const file = $.create("File", Object.assign({name: recordName(token, NOW), contentType: "application/json"}, PRIVATE));
  $.setContent(file, JSON.stringify(record, null, 1));
  if (booking.household) $.grant(booking.household, file, "read");
  booking.process = "Purchase " + token;
  booking.record = file.name;
  for (const node of nodes) {
    booking.created.push(node.name);
    $.delete(node);
  }
  booking.notes.push("Purchase " + token + ": taken back.");
}

const PANTRY_ACTIONS = {
  // pantry.buy
  buy: (booking, r, token) => {
    const storage = String(r.storage || "Fridge");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const food = typeNamed(String(r.food || "").trim());
    const amount = amountFrom(r), unit = String(r.unit || "g");
    bookingGrams(food, amount, unit);
    const keeps = r.keeps ? typeNamed(String(r.keeps)) : lastPerishability(food);
    bookPurchase(booking, food, [[amount, unit]], storage, keeps, token);
    noShelfLife(booking, food, keeps, storage, " (name a perishability class when buying)");
  },
  // pantry.buy_line: what a line of the shopping list bought, from "Put ticked items into the pantry" (pages/shopping.js)
  bought: (booking, r, token) => {
    const line = linePurchase(r);
    bookBought(booking, line.food, line.pieces, token, r.storage ? String(r.storage) : null);
  },
  // pantry.unbuy: a purchase taken back while nothing rests on it, by its token (`purchase`)
  unbuy: (booking, r) => unbuyPurchase(booking, String(r.purchase || "")),
  // pantry.use: within USED_UP_G of what it holds, either way, is all of it (the page shows whole grams)
  use: (booking, r, token) => {
    const portion = portionFrom(r, booking), food = portion.instanceOf;
    const grams = bookingGrams(food, amountFrom(r), String(r.unit || "g"));
    const level = onHand(portion);
    if (!Array.isArray(level)) throw new BookingError(portion.name + ": " + (level || "never weighed") + ", so there is nothing to take from it (count it first)");
    const have = level[0];
    if (!(have > 0)) throw new BookingError(portion.name + ": nothing on hand to take from it");
    let take = grams;
    if (have - grams >= -USED_UP_G && have - grams < USED_UP_G) take = have;   // the amount shown, or one leaving a crumb: all of it
    else if (grams > have) throw new BookingError(portion.name + ": " + number(grams, 0) + " g is more than the " + number(have, 0) + " g on hand");
    bookDraw(booking, bookProcess(booking, "Use", "Use " + token, NOW), portion, take, NOW, portion.name);
    if (take < have) openedByUse(booking, portion);
  },
  // pantry.discard
  discard: (booking, r, token) => {
    const portion = portionFrom(r, booking);
    const level = onHand(portion);
    if (!Array.isArray(level) || !(level[0] > 0)) throw new BookingError(portion.name + ": nothing on hand to discard");
    bookDraw(booking, bookProcess(booking, "Discarding", "Discard " + token, NOW), portion, level[0], NOW, portion.name);
  },
  // pantry.stock_take
  count: (booking, r, token) => {
    const portion = portionFrom(r, booking), amount = amountFrom(r), unit = String(r.unit || "g");
    if (amount < 0) throw new BookingError("a stock take is 0 or more");
    if (amount > 0) bookingGrams(portion.instanceOf, amount, unit);
    const quality = massQuality(portion) || ensureNode(booking, "Quality", portion.name + " mass Quality", {
      hasKind: typeNamed("Mass"), inheresIn: portion});
    bookProcess(booking, "Stock take", "Stock take " + token, NOW, {hasParticipant: [portion]});
    ensureNode(booking, "Measurement", portion.name + " stock take " + token, {value: amount, unit: unit, status: "observed",
                                                                                hasTime: stamp(NOW), isAboutQuality: quality});
  },
  // pantry.open_portion
  open: (booking, r, token) => {
    const portion = portionFrom(r, booking), box = containerOf(booking, portion);
    bookProcess(booking, "Opening", "Open " + token, NOW, {hasParticipant: [portion]});
    if (!box.hasOpenedStatus || box.hasOpenedStatus.name !== "Opened") {
      box.hasOpenedStatus = typeNamed("Opened");
      booking.notes.push(portion.name + ": opened.");
    }
  },
  // pantry.move
  move: (booking, r, token) => {
    const storage = String(r.storage || "");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const portion = portionFrom(r, booking), box = containerOf(booking, portion);
    bookProcess(booking, "Move", "Move " + token, NOW, {hasParticipant: [portion]});
    box.hasStorageCondition = typeNamed(storage);
    booking.notes.push(portion.name + ": kept in the " + storage.toLowerCase() + ".");
  },
};
