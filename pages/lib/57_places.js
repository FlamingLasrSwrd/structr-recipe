// Where each food usually goes (mealplanner/places.py; docs/pantry.md, "Where each food goes"): a person's own
// place for it, else their household's, else everyone's, else the rule (storageFor). A level is a DomainType in
// the "Storage Place Reference" hierarchy, a remembered place a DefaultSpecification of kind "Storage Place" on it,
// keyed by the food, its targetType the storage condition.
//
//   Storage places -- everyone                 shared with every user (scripts/52a makes it)
//     Storage places -- household <name>       private to the household: its Group reads and writes it
//       Storage places -- person <name>        the person's: they read and write it, their household reads it
//
// A place is remembered when a person picks it (Buy, a shopping line changed before it is put away, a move
// within PLACE_FRESH_HOURS of buying it). A first choice for a food fills everyone's level and the
// household's where they have none (shared knowledge that overrides nothing, the owner's rule); the choice is
// the person's own only where the levels above them say otherwise. tools/check_bookings.py compares this with
// Python.

const PLACE_HIERARCHY = "Storage Place Reference", PLACE_KIND = "Storage Place", EVERYONE_PLACES = "Storage places -- everyone";
const PLACE_FRESH_HOURS = 24;
const PLACE_YOURS = "yours", PLACE_HOUSEHOLD = "your household's", PLACE_SHARED = "everyone's", PLACE_RULE = "the usual rule";
const cleanName = (name) => String(name).replace(/[,;]/g, "").trim();
const householdPlacesName = (name) => "Storage places -- household " + cleanName(name);
const personPlacesName = (name) => "Storage places -- person " + cleanName(name);

// places._one: the one node of this type and name, else null
function oneNamed(type, name) {
  const rows = $.find(type, {name: name}).filter((r) => r.type === type);
  return rows.length === 1 ? rows[0] : null;
}

const byId = (type, id) => { const found = $.find(type, {id: id}); return Array.isArray(found) ? found[0] : found; };

// places.place_food: the food itself, or for a product the food it is a product of. The products are read once
// a request (a shopping list asks for every line)
let placeProducts = null;
function placeFood(food) {
  const products = placeProducts || (placeProducts = productIds());
  for (const t of ancestorsOrSelf(food)) if (!products[t.id]) return t;
  return food;
}

// places.household_of: the person's one household, else null
function householdOfPerson(person) {
  const found = ((person && person.groups) || []).filter((g) => g.type === "Household");
  return found.length === 1 ? found[0] : null;
}

// places.levels: [[source, level]] of the levels that exist for this person, nearest first
function placeLevels(person) {
  const out = [];
  if (person) {
    const mine = oneNamed("DomainType", personPlacesName(person.name));
    if (mine) out.push([PLACE_YOURS, mine]);
    const household = householdOfPerson(person);
    const theirs = household ? oneNamed("DomainType", householdPlacesName(household.name)) : null;
    if (theirs) out.push([PLACE_HOUSEHOLD, theirs]);
  }
  const everyone = oneNamed("DomainType", EVERYONE_PLACES);
  if (everyone) out.push([PLACE_SHARED, everyone]);
  return out;
}

// places.entry: the place a level gives this food itself
function placeEntry(level, food) {
  for (const d of level.defaultSpecifications || []) {
    const keys = d.keyedBy || [];
    if (d.hasKind && d.hasKind.name === PLACE_KIND && keys.length === 1 && keys[0].id === food.id && d.targetType
        && STORAGE.indexOf(d.targetType.name) >= 0) return d;
  }
  return null;
}

// places._resolve: {storage, source, food (whose place it is, or null by the rule)}
function resolvePlace(food, found) {
  for (const t of ancestorsOrSelf(placeFood(food))) {
    for (const [source, level] of found) {
      const d = placeEntry(level, t);
      if (d) return {storage: d.targetType.name, source: source, food: t.name};
    }
  }
  return {storage: storageFor(food), source: PLACE_RULE, food: null};
}

// places.usual_place: where this food goes for this person (a Person, or null)
const usualPlace = (food, person) => resolvePlace(food, placeLevels(person));
// Usual.words: "the freezer (yours)"
const placeWords = (usual) => "the " + usual.storage.toLowerCase() + " (" + usual.source + ")";

// The Person signed in, for what the pages show; null for anyone else
const viewerPerson = () => ($.me && $.me.type === "Person" ? $.me : null);
// The Person a booking is for, loaded again in its transaction
const bookingPerson = () => (BOOKED_BY ? byId("Person", BOOKED_BY) || null : null);

// places.fresh: bought within PLACE_FRESH_HOURS before now, so a move corrects where it was put away
function placeFresh(portion) {
  const process = portion.beginsToExistDuring;
  if (!process || !process.hasKind || process.hasKind.name !== "Purchase") return false;
  const region = process.occupiesTemporalRegion;
  if (!region || !region.hasBeginning) return false;
  const since = NOW.getTime() - new Date(region.hasBeginning).getTime();
  return since >= 0 && since <= PLACE_FRESH_HOURS * 3600e3;
}

// places.remember: that the booking's person put this food in `storage`. As the superuser, since it may add to
// everyone's level, which no one writes as themselves; what is the household's or the person's is made private
// to them and granted, as their own bookings are. Every object is loaded again inside, since an object keeps
// the rights it was loaded with
function rememberPlace(booking, foodId, storage) {
  if (STORAGE.indexOf(storage) < 0 || !BOOKED_BY) return;
  const run = () => {
    const kind = oneNamed("DomainType", PLACE_KIND), everyone = oneNamed("DomainType", EVERYONE_PLACES);
    if (!kind || !everyone) {
      booking.notes.push("where it was kept isn't remembered yet: run scripts/52a_storage_places.py");
      return;
    }
    const person = byId("Person", BOOKED_BY);
    if (!person) return;
    const hierarchy = oneNamed("TypeHierarchy", PLACE_HIERARCHY);
    const food = placeFood(byId("DomainType", foodId)), bought = byId("DomainType", foodId);
    const place = typeNamed(storage), household = booking.household ? byId("Household", booking.household.id) : null;
    const source = "chosen by " + cleanName(person.name);
    // pantry._Writer.ensure for a place's nodes, each private to whose it is
    const ensure = (type, name, props, whose) => {
      const found = oneNamed(type, name);
      if (found) return found;
      booking.created.push(name);
      const node = $.create(type, Object.assign({name: name}, props, whose === "everyone" || !household ? SEEN : PRIVATE));
      if (household && whose === "household") $.grant(household, node, "read, write, delete");
      if (household && whose === "person") {
        $.grant(person, node, "read, write, delete");
        $.grant(household, node, "read");
      }
      return node;
    };
    const levelOf = (name, parent, whose) => ensure("DomainType", name, {hierarchy: hierarchy, isLookupBearing: true, parent: parent}, whose);
    const put = (level, whose) => ensure("DefaultSpecification", level.name + " -- " + food.name,
      {forType: level, hasKind: kind, keyedBy: [food], targetType: place, source: source}, whose);
    const above = () => resolvePlace(bought, placeLevels(person).filter(([source]) => source !== PLACE_YOURS));
    const mine = oneNamed("DomainType", personPlacesName(person.name));
    const own = mine ? placeEntry(mine, food) : null;
    if (above().storage === storage && !own) return;
    if (!placeEntry(everyone, food)) {
      put(everyone, "everyone");
      booking.notes.push(food.name + ": everyone's usual place now, the " + storage.toLowerCase());
    }
    let parent = everyone;
    if (household) {
      parent = levelOf(householdPlacesName(household.name), everyone, "household");
      if (!placeEntry(parent, food)) {
        put(parent, "household");
        booking.notes.push(food.name + ": your household's usual place now, the " + storage.toLowerCase());
      }
    }
    if (above().storage === storage) {
      if (own) {
        $.delete(own);
        booking.notes.push(food.name + ": your own place for it is forgotten, so it goes to the usual place again");
      }
      return;
    }
    if (own) {
      if (!own.targetType || own.targetType.id !== place.id) {
        own.targetType = place;
        own.source = source;
        booking.notes.push(food.name + ": your usual place now, the " + storage.toLowerCase());
      }
      return;
    }
    put(levelOf(personPlacesName(person.name), parent, "person"), "person");
    booking.notes.push(food.name + ": your usual place now, the " + storage.toLowerCase());
  };
  if (typeof $.doPrivileged === "function") $.doPrivileged(run); else run();
}
