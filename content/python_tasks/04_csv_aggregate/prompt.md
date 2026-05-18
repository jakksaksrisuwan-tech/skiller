# csv_aggregate

**Targets**
- 🎯 first working version: **20 minutes** (all visible tests pass)
- 🏁 complete version: **40 minutes** (visible + hidden tests pass)

## Task

Implement `csv_aggregate(text: str) -> dict[str, int]` that:

1. **Parses** CSV text. The first non-empty line is the header; following lines
   are data rows.
2. **Filters** invalid rows. A row is invalid if any of:
   - empty `category` column
   - non-integer `count` column (negative integers ARE valid)
   - wrong number of columns
3. **Aggregates** by summing the `count` column per `category`.
4. **Sorts** the output: count descending, then category ascending (alpha).
   Return a `dict` whose insertion order reflects the sort.

Required columns in the input header: `category` and `count`. Other columns
may be present and should be ignored. Use the `csv` stdlib module.

## Example

Input:
```
category,count,note
fruit,10,first
veg,3,
fruit,5,
,2,empty-cat       <-- invalid: empty category
veg,abc,bad-num    <-- invalid: count not int
fruit,2,
```

Output: `{"fruit": 17, "veg": 3}`

## Hints (for the 20-min cut)

- `csv.DictReader` handles the header line for you.
- A `defaultdict(int)` makes summing trivial.
- `sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))` gives count-desc + alpha-asc.

Edit `solution.py` in the editor pane. **ctrl+s** save · **ctrl+t** run visible
tests · **ctrl+g** submit (visible + hidden) · **esc** back. The screen tracks
both target times automatically.
