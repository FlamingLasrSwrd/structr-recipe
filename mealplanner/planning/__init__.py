"""Plan-level meal selection: the optimizer proposed in docs/optimizer-design.md.

model.py     the problem as plain data
evaluate.py  what a complete assignment means: legality, hard constraints, score
search.py    finding the best assignment (exact search, beam search, oracle)
diagnose.py  what to report when no assignment satisfies the hard constraints
extract.py   graph -> problem
commit.py    solution -> MealPlanEntries
"""
