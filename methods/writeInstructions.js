// writeInstructions: the sentences the recipe page writes for steps given as plain data (stepSentences;
// mealplanner/instructions.py, as_data), so the two writers can be compared on any steps at all
// (tools/check_instructions.py). Reads nothing.
//
// Arguments: steps (a list in the shape instructions.as_data gives), and bearers (for each capability the
// steps name, the tools that can give it). Returns the sentences, in order.

const asked = $.methodParameters || {};
return stepSentences(asked.steps || [], asked.bearers || {});
