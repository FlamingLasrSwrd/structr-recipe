// stockOnHand: every portion the caller may see that has been weighed, with its grams on hand now and
// its days to expiry, as the pantry page lists them (inventory.current_magnitude, instance_expiration).
// No arguments. Runs as the caller, so Structr shows them only what they may read.

const out = [];
for (const portion of $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))) {
  const level = onHand(portion);
  if (level == null) continue;                                      // no weighing yet: not known to exist
  const [days, why] = daysUntilExpiry(portion);
  out.push({id: portion.id, name: portion.name, food: portion.instanceOf ? portion.instanceOf.name : null,
            grams: Array.isArray(level) ? level[0] : null, problem: Array.isArray(level) ? null : level,
            days: days, expiry: why});
}
return out;
