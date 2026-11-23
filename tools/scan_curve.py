"""Model for docs/time-study.md ("The barcode curve"): run `python3 tools/scan_curve.py`.

Model: how many of a week's barcoded purchases are products the instance does not know yet.

A household's barcoded purchases are drawn from a pool of products with Zipf popularity (a few
bought nearly every week, a long tail bought rarely). Each week some products are replaced by a
new one at the same popularity (a new size, a brand swap, a shop change, a seasonal item): a
package of another size is another product here (docs/pantry.md), so this churn never ends.
Assumptions, not measurements: pool size, Zipf exponent, churn rate, lines per week.
"""
import random, statistics

def run(lines_per_week, pool=400, s=1.0, churn=0.01, weeks=52, sims=400, seed=1):
    rng = random.Random(seed)
    weights = [1 / (r + 1) ** s for r in range(pool)]
    new_by_week = [[] for _ in range(weeks)]
    for _ in range(sims):
        ids = list(range(pool)); next_id = pool; known = set()
        for w in range(weeks):
            for r in range(pool):                     # churn: a product replaced at the same rank
                if rng.random() < churn:
                    ids[r] = next_id; next_id += 1
            chosen = set()
            while len(chosen) < lines_per_week:       # distinct lines in the week's shop
                chosen.add(rng.choices(range(pool), weights)[0])
            new = sum(1 for r in chosen if ids[r] not in known)
            known.update(ids[r] for r in chosen)
            new_by_week[w].append(new)
    return [statistics.mean(x) for x in new_by_week]

if __name__ == "__main__":
    T_KNOWN, T_NEW = 15, 70     # seconds of app time per line, beyond putting the item away (report's estimates)
    for name, lines in [("A single", 12), ("B couple", 22), ("C family", 40)]:
        curve = run(lines)
        print(name, lines, "barcoded lines a week")
        for w in [1, 2, 3, 4, 6, 8, 12, 16, 26, 52]:
            n = curve[w - 1]
            mins = ((lines - n) * T_KNOWN + n * T_NEW) / 60
            print(f"  week {w:2d}: new {n:5.1f} ({100*n/lines:4.0f}%)  scan time {mins:5.1f} min")
        cum = sum(curve)
        print(f"  products added in a year: {cum:.0f}")
