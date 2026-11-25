// The pantry's bookings (mealplanner/pantry.py): its page's forms, and the bookPantry method.

const STORAGE = ["Fridge", "Freezer", "Pantry"];
const WHERE_KEPT = "choose where it is kept: Fridge, Freezer or Pantry";
// A portion not the caller's to change: one of another household is not even said to exist (tools/check_households.py)
const NOT_IN_PANTRY = "that item isn't in your pantry. Reload the page to see what is";
const NOT_YOURS = " is not in your household's pantry, so it can't be changed here";
const UNITS = ["g", "kg", "oz", "lb", "ml", "l", "cup", "tbsp", "tsp", "fl_oz", "each"];

// What a booking's words call a portion: its food (or product), not the name the booking gave it
const foodOf = (portion) => (portion.instanceOf ? portion.instanceOf.name : portion.name);

// pantry._grams
function bookingGrams(food, amount, unit) {
  if (!(amount > 0) || !isFinite(amount)) throw new BookingError("enter an amount of " + food.name + " more than 0");
  const grams = toGrams(food, amount, unit);
  if (grams == null) throw new BookingError("the weight of " + amount + " " + unit + " of " + food.name + " isn't known. "
                                            + "Enter it by weight instead (g, kg, oz or lb)");
  return grams;
}

// The food Buy names, or a problem saying it is none
function foodNamed(name) {
  if (!name) throw new BookingError("say which food you bought");
  const found = $.find("DomainType", {name: name}).filter((t) => t.type === "DomainType");
  if (!found.length) throw new BookingError("there is no food called \"" + name + "\". Pick one from the list as you type");
  return typeNamed(name);
}

// A household's booking acts on its own stock only: what is private to it. Stock every signed-in user
// sees belongs to no household (the data made before households kept theirs apart), so a household
// neither draws on it nor books on it (docs/methods.md).
const ownStock = (booking, portion) => !booking.household || portion.visibleToAuthenticatedUsers === false;

function portionFrom(request, booking) {
  const found = $.find("PortionOfSubstance", {id: String(request.portion || "")});
  const portion = Array.isArray(found) ? found[0] : found;
  if (!portion || portion.type !== "PortionOfSubstance") throw new BookingError(NOT_IN_PANTRY);
  if (!ownStock(booking, portion)) throw new BookingError(foodOf(portion) + NOT_YOURS);
  return portion;
}

function amountFrom(request) {
  const amount = Number(request.amount);
  if (request.amount == null || request.amount === "" || !isFinite(amount)) throw new BookingError("enter the amount as a number");
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
  booking.notes.push(foodOf(portion) + " is marked opened now.");
}

// pantry._container
function containerOf(booking, portion) {
  if (portion.locatedIn) return portion.locatedIn;
  const box = ensureNode(booking, "ContainerObject", portion.name + " container", {
    hasStorageCondition: typeNamed("Fridge"), hasOpenedStatus: typeNamed("Sealed")});
  portion.locatedIn = box;
  return box;
}

const PANTRY_ACTIONS = {
  // pantry.buy
  buy: (booking, r, token) => {
    const storage = String(r.storage || "Fridge");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError(WHERE_KEPT);
    const food = foodNamed(String(r.food || "").trim());
    const amount = amountFrom(r), unit = String(r.unit || "g");
    bookingGrams(food, amount, unit);
    const keeps = r.keeps ? typeNamed(String(r.keeps)) : lastPerishability(food);
    const sealed = typeNamed("Sealed"), where = typeNamed(storage);
    const process = bookProcess(booking, "Purchase", "Purchase " + token, NOW);
    const name = "Purchase " + token + " -- " + food.name;
    const box = ensureNode(booking, "ContainerObject", name + " container", {
      hasStorageCondition: typeNamed(storage), hasOpenedStatus: typeNamed("Sealed")});
    const portion = ensureNode(booking, "PortionOfSubstance", name, {
      instanceOf: food, beginsToExistDuring: process, locatedIn: box, hasPerishabilityType: keeps});
    const quality = ensureNode(booking, "Quality", name + " mass Quality", {hasKind: typeNamed("Mass"), inheresIn: portion});
    ensureNode(booking, "Measurement", name + " mass bought", {value: amount, unit: unit, status: "observed",
                                                              hasTime: stamp(NOW), isAboutQuality: quality});
    const shelf = resolveDefault(food, "ShelfLife", [where.id, sealed.id]);
    if (!keeps && !(shelf && shelf.hasValue && shelf.hasValue.unit === "days" && shelf.hasValue.value != null)) {
      booking.notes.push("There is no use-by estimate for " + food.name + " in the " + storage.toLowerCase()
                         + ". To get one, choose how it keeps when you buy it.");
    }
  },
  // pantry.use: within USED_UP_G of what it holds, either way, is all of it (the page shows whole grams)
  use: (booking, r, token) => {
    const portion = portionFrom(r, booking), food = portion.instanceOf;
    const grams = bookingGrams(food, amountFrom(r), String(r.unit || "g"));
    const level = onHand(portion);
    if (!Array.isArray(level)) throw new BookingError("how much " + foodOf(portion) + " is left isn't known" + (level ? " (" + level + ")" : "")
                                                 + ", so nothing can be taken from it. Count it first");
    const have = level[0];
    if (!(have > 0)) throw new BookingError(foodOf(portion) + " is used up, so there is nothing to take");
    let take = grams;
    if (have - grams >= -USED_UP_G && have - grams < USED_UP_G) take = have;   // the amount shown, or one leaving a crumb: all of it
    else if (grams > have) throw new BookingError("only " + number(have, 0) + " g of " + foodOf(portion) + " is left, less than the " + number(grams, 0)
                                                  + " g entered. If there is more, use Count to say how much");
    bookDraw(booking, bookProcess(booking, "Use", "Use " + token, NOW), portion, take, NOW, portion.name);
    if (take < have) openedByUse(booking, portion);
  },
  // pantry.discard
  discard: (booking, r, token) => {
    const portion = portionFrom(r, booking);
    const level = onHand(portion);
    if (!Array.isArray(level) || !(level[0] > 0)) throw new BookingError(foodOf(portion) + " is used up already, so there is nothing to throw away");
    bookDraw(booking, bookProcess(booking, "Discarding", "Discard " + token, NOW), portion, level[0], NOW, portion.name);
  },
  // pantry.stock_take
  count: (booking, r, token) => {
    const portion = portionFrom(r, booking), amount = amountFrom(r), unit = String(r.unit || "g");
    if (amount < 0) throw new BookingError("a count can't be less than 0");
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
      booking.notes.push(foodOf(portion) + " is marked opened.");
    }
  },
  // pantry.move
  move: (booking, r, token) => {
    const storage = String(r.storage || "");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError(WHERE_KEPT);
    const portion = portionFrom(r, booking), box = containerOf(booking, portion);
    bookProcess(booking, "Move", "Move " + token, NOW, {hasParticipant: [portion]});
    box.hasStorageCondition = typeNamed(storage);
    booking.notes.push(foodOf(portion) + " is in the " + storage.toLowerCase() + " now.");
  },
};
