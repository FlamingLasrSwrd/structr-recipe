// The pantry page's food picker (docs/pantry.md, "Choosing the food"). Served as a file (tools/install_pages.py
// puts pages/files/ in Structr's folder /mealplanner/), run in the browser.
//
// A food is named exactly as the instance names it ("Chickpeas (canned)"), which no one can guess. Each
// food box on the page (Buy's, and "Add a product"'s) carries the names it takes as a datalist; this
// replaces the browser's own list, which phones show poorly, with one that searches as you type: each word
// typed may be the start of any word of the name, in any order, upper or lower case, singular or plural
// ("chick", "canned chickpea", "TOMATOES DICED"). A tap puts the name in the box. A name typed whole in other
// letter case is put right when the form is sent. Without this script the datalist is left as it was.
//
// The Open Food Facts look-up (mealplanner-lookup.js) asks it for the foods a product most likely is
// (guess) and shows them under "Add a product"'s box to tap: it never chooses one, since which food a
// product is a kind of is the user's judgment (J19).
//
// The same file runs in node for tests/test_pantry_foods.py, which reads words, search and guess.
(function () {
  "use strict";
  var SHOWN = 8;
  // words that say nothing of which food it is
  var STOP = {and: 1, with: 1, of: 1, the: 1, a: 1, in: 1, "for": 1, or: 1, to: 1, from: 1, en: 1, based: 1, foods: 1,
              food: 1, products: 1, product: 1};

  // one word as both sides are compared: "tomatoes" and "tomato", "berries" and "berry", "peas" and "pea"
  function stem(w) {
    if (w.length <= 3) return w;
    if (/ies$/.test(w)) return w.slice(0, -3) + "y";
    if (/(oes|ches|shes|xes)$/.test(w)) return w.slice(0, -2);
    if (/[^su]s$/.test(w)) return w.slice(0, -1);
    return w;
  }

  // a text's words: lower case, without accents, split at anything not a letter or digit, stemmed
  function words(text) {
    return String(text == null ? "" : text).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
      .split(/[^a-z0-9]+/).filter(function (w) { return w; }).map(stem);
  }

  // The names a typed text finds, best first: each typed word the start of a word of the name. A name that
  // begins as typed comes first, then a shorter name before a longer, then by alphabet.
  function search(names, typed, limit) {
    var want = words(typed);
    if (!want.length) return [];
    var start = want.join(" ");
    var found = [];
    names.forEach(function (name) {
      var have = words(name);
      var all = want.every(function (w) { return have.some(function (h) { return h.indexOf(w) === 0; }); });
      if (all) found.push({name: name, starts: have.join(" ").indexOf(start) === 0 ? 0 : 1, length: have.length});
    });
    found.sort(function (a, b) { return a.starts - b.starts || a.length - b.length || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0); });
    return found.slice(0, limit || SHOWN).map(function (f) { return f.name; });
  }

  // The names a product from Open Food Facts most likely is a kind of, best first: those whose every word
  // outside brackets is a word of its categories or its name. A name is likelier with more such words (it is
  // more particular), when its categories hold them all (they are surer than a name), and with each word in
  // its brackets ("canned" in "Chickpeas (canned)") they hold, less likely with each they do not. One far less
  // likely than the likeliest is left out: "Butter (salted)" beside "Peanut butter (creamy)", "Potatoes" beside
  // "Rolled oats" (filed under "Cereals and potatoes").
  // off: {name, categories} (the categories in English, any order).
  function guess(names, off, limit) {
    off = off || {};
    var inCategories = {}, inName = {};
    (off.categories || []).forEach(function (c) { words(c).forEach(function (w) { inCategories[w] = true; }); });
    words(off.name).forEach(function (w) { inName[w] = true; });
    var scored = [];
    names.forEach(function (name) {
      var outside = words(String(name).replace(/\([^)]*\)/g, " ")).filter(function (w) { return !STOP[w]; });
      var inside = words((String(name).match(/\(([^)]*)\)/g) || []).join(" ")).filter(function (w) { return !STOP[w]; });
      if (!outside.length) return;
      if (!outside.every(function (w) { return inCategories[w] || inName[w]; })) return;
      var score = outside.length * 10 + (outside.every(function (w) { return inCategories[w]; }) ? 5 : 0);
      inside.forEach(function (w) { score += inCategories[w] || inName[w] ? 3 : -1; });
      scored.push({name: name, score: score});
    });
    scored.sort(function (a, b) { return b.score - a.score || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0); });
    var best = scored.length ? scored[0].score : 0;
    return scored.filter(function (s) { return s.score > best - 10; }).slice(0, limit || 5).map(function (s) { return s.name; });
  }

  var api = {words: words, search: search, guess: guess};
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  function chooser(box, names, row, label) {
    row.textContent = "";
    if (!names.length) { row.hidden = true; return; }
    if (label) row.appendChild(document.createTextNode(label + " "));
    names.forEach(function (name) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = name;
      b.addEventListener("click", function () {
        box.value = name;
        box.dispatchEvent(new Event("change", {bubbles: true}));    // Buy picks its unit on change
        box.form.querySelectorAll("div.picks").forEach(function (d) { d.hidden = true; });
        box.focus();
      });
      row.appendChild(b);
    });
    row.hidden = false;
  }

  var boxes = [];
  document.querySelectorAll("details.buy input[name=food][list], details.product input[name=food][list]").forEach(function (box) {
    var list = document.getElementById(box.getAttribute("list"));
    if (!list) return;
    var names = Array.prototype.map.call(list.options, function (o) { return o.value; });
    var lower = {};
    names.forEach(function (n) { lower[n.toLowerCase()] = n; });
    box.removeAttribute("list");
    box.setAttribute("autocomplete", "off");
    var likely = document.createElement("div"), found = document.createElement("div");
    likely.className = "picks likely";
    found.className = "picks found";
    likely.hidden = found.hidden = true;
    box.form.appendChild(likely);
    box.form.appendChild(found);
    function show() {
      var typed = box.value.trim();
      if (!typed || names.indexOf(typed) >= 0) {
        found.hidden = true;
        return;
      }
      var hits = search(names, typed);
      chooser(box, hits, found);
      if (!hits.length) {
        found.textContent = "No food here is named like that: try a shorter or other word.";
        found.hidden = false;
      }
    }
    box.addEventListener("input", show);
    box.addEventListener("keydown", function (e) {      // Enter takes the first found, where the name is not whole yet
      if (e.key !== "Enter" || found.hidden) return;
      var first = found.querySelector("button");
      if (first) { e.preventDefault(); first.click(); }
    });
    box.form.addEventListener("submit", function () {   // a whole name in other letter case, put right
      var exact = lower[box.value.trim().toLowerCase()];
      if (exact) box.value = exact;
    });
    boxes.push({box: box, names: names, likely: likely});
  });

  // For the look-up: show `picked` (names this box takes) under the box as the foods it likely is
  function offer(box, picked) {
    boxes.forEach(function (b) {
      if (b.box !== box) return;
      chooser(box, picked.filter(function (n) { return b.names.indexOf(n) >= 0; }), b.likely, "Likely:");
    });
  }
  function namesOf(box) {
    var b = boxes.filter(function (x) { return x.box === box; })[0];
    return b ? b.names.slice() : [];
  }
  window.mealplannerFoods = {words: words, search: search, guess: guess, offer: offer, namesOf: namesOf};
})();
