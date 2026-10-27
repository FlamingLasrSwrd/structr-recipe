// writeInstructions: the sentences the recipe page writes for steps given as plain data (stepSentences;
// mealplanner/instructions.py, as_data), so the two writers can be compared on any steps at all
// (tools/check_instructions.py). Reads nothing.
//
// Arguments: steps (a list in the shape instructions.as_data gives). Returns the sentences, in order.

return stepSentences((($.methodParameters || {}).steps) || []);
