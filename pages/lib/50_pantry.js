// The pantry's bookings (mealplanner/pantry.py): its page's forms, and the bookPantry method.

const STORAGE = ["Fridge", "Freezer", "Pantry"];
const UNITS = ["g", "kg", "oz", "lb", "ml", "l", "cup", "tbsp", "tsp", "fl_oz", "each"];

// pantry._grams
function bookingGrams(food, amount, unit) {
  if (!(amount > 0)) throw new BookingError(food.name + ": an amount must be more than 0");
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
  if (request.amount == null || request.amount === "" || isNaN(amount)) throw new BookingError("an amount is a number");
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
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const food = typeNamed(String(r.food || "").trim());
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
      booking.notes.push(food.name + ": no shelf life known for it in the " + storage.toLowerCase()
                         + ", so no expiry (name a perishability class when buying)");
    }
  },
  // pantry.use
  use: (booking, r, token) => {
    const portion = portionFrom(r, booking), food = portion.instanceOf;
    const grams = bookingGrams(food, amountFrom(r), String(r.unit || "g"));
    const level = onHand(portion);
    if (!Array.isArray(level)) throw new BookingError(portion.name + ": " + (level || "never weighed") + ", so there is nothing to take from it (count it first)");
    if (grams > level[0] + 1e-6) throw new BookingError(portion.name + ": " + number(grams, 0) + " g is more than the " + number(level[0], 0) + " g on hand");
    bookDraw(booking, bookProcess(booking, "Use", "Use " + token, NOW), portion, grams, NOW, portion.name);
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
    ensureNode(booking, "Measurement", portion.name + " stock take " + token, {value: amount, unit: unit, status: "observed",
                                                                                hasTime: stamp(NOW), isAboutQuality: quality});
    booking.process = portion.name + " counted";
  },
  // pantry.open_portion
  open: (booking, r) => {
    const portion = portionFrom(r, booking), box = containerOf(booking, portion);
    if (!box.hasOpenedStatus || box.hasOpenedStatus.name !== "Opened") {
      box.hasOpenedStatus = typeNamed("Opened");
      booking.notes.push(portion.name + ": opened.");
    }
  },
  // pantry.move
  move: (booking, r) => {
    const storage = String(r.storage || "");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const portion = portionFrom(r, booking), box = containerOf(booking, portion);
    box.hasStorageCondition = typeNamed(storage);
    booking.notes.push(portion.name + ": kept in the " + storage.toLowerCase() + ".");
  },
};
