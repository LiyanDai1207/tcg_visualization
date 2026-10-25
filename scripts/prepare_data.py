"""
prepare_data.py
Turns the four raw API JSON files into the small CSVs used by the website.

Run:
    python3 scripts/prepare_data.py raw_data/

Input (raw_data/ folder, not uploaded to GitHub):
    mtg_sets.json   Scryfall  https://api.scryfall.com/sets
    pkm_sets.json   Pokemon TCG API  https://api.pokemontcg.io/v2/sets
    ygo_sets.json   YGOPRODeck  https://db.ygoprodeck.com/api/v7/cardsets.php
    ygo_cards.json  YGOPRODeck  https://db.ygoprodeck.com/api/v7/cardinfo.php
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(sys.argv[1] if len(sys.argv) > 1 else "raw_data")
OUT = Path("data")
OUT.mkdir(exist_ok=True)

CUTOFF = "2026-09-28"   # ignore sets dated after download
LAST_FULL_YEAR = 2025   # per-year charts stop at last full year


def write_csv(name, rows, fields):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


# ------------------------------------------------------------------
# 1. one row per set, all three games
# ------------------------------------------------------------------
# exclude products that are not card sets
MTG_EXCLUDE = {"token", "memorabilia", "promo", "alchemy", "minigame",
               "masterpiece", "vanguard", "treasure_chest"}
# multi-year reprint pools that create fake spikes
MTG_EXCLUDE_NAMES = {"The List", "Secret Lair Drop"}

sets = []

for s in json.load(open(RAW / "mtg_sets.json"))["data"]:
    d = s.get("released_at")
    if not d or d > CUTOFF or s["digital"] or s["set_type"] in MTG_EXCLUDE:
        continue
    if s.get("card_count", 0) == 0 or s["name"] in MTG_EXCLUDE_NAMES or s["name"].startswith("Salvat"):
        continue
    sets.append({"game": "Magic: The Gathering", "set_name": s["name"],
                 "date": d, "cards": s["card_count"]})

for s in json.load(open(RAW / "pkm_sets.json"))["data"]:
    d = s["releaseDate"].replace("/", "-")
    if d > CUTOFF or "promo" in s["name"].lower():
        continue
    sets.append({"game": "Pokémon", "set_name": s["name"],
                 "date": d, "cards": s["total"]})

ygo_set_date = {}   # set name → date, used below
for s in json.load(open(RAW / "ygo_sets.json")):
    d = s.get("tcg_date")
    if not d or d > CUTOFF or not s.get("num_of_cards"):
        continue
    if "promo" in s["set_name"].lower():
        continue                              # promos are not sets or printings
    ygo_set_date[s["set_name"]] = d
    sets.append({"game": "Yu-Gi-Oh!", "set_name": s["set_name"],
                 "date": d, "cards": s["num_of_cards"]})

sets.sort(key=lambda r: r["date"])
write_csv("sets_all.csv", sets, ["game", "set_name", "date", "cards"])


# ------------------------------------------------------------------
# 2. sets and cards per game per year
# ------------------------------------------------------------------
per_year = defaultdict(lambda: {"sets": 0, "cards": 0})
for s in sets:
    y = int(s["date"][:4])
    if y <= LAST_FULL_YEAR:
        per_year[(s["game"], y)]["sets"] += 1
        per_year[(s["game"], y)]["cards"] += s["cards"]

rows = [{"game": g, "year": y, **v} for (g, y), v in sorted(per_year.items(), key=lambda k: (k[0][1], k[0][0]))]
write_csv("sets_by_year.csv", rows, ["game", "year", "sets", "cards"])


# ------------------------------------------------------------------
# 3. card type by first-print year
# ------------------------------------------------------------------
TYPE_MAP = {
    "normal": "Normal Monster", "effect": "Effect Monster", "ritual": "Ritual",
    "fusion": "Fusion", "synchro": "Synchro", "xyz": "Xyz", "link": "Link",
    "spell": "Spell", "trap": "Trap",
}
cards = json.load(open(RAW / "ygo_cards.json"))["data"]

type_year = Counter()
for c in cards:
    ft = c["frameType"]
    if ft in ("skill", "token"):
        continue                                   # not regular cards
    t = "Pendulum" if "pendulum" in ft else TYPE_MAP[ft]
    dates = [ygo_set_date[cs["set_name"]] for cs in c.get("card_sets", [])
             if cs["set_name"] in ygo_set_date]
    if not dates:
        continue
    y = int(min(dates)[:4])                        # earliest set
    if 2002 <= y <= LAST_FULL_YEAR:            # TCG launched 2002
        type_year[(t, y)] += 1

rows = [{"card_type": t, "year": y, "new_cards": n} for (t, y), n in sorted(type_year.items(), key=lambda k: (k[0][1], k[0][0]))]
write_csv("ygo_types_by_year.csv", rows, ["card_type", "year", "new_cards"])


# ------------------------------------------------------------------
# 4. rarity tiers, early vs recent
# ------------------------------------------------------------------
INVALID = {"New", "2", "3", "Reprint", "New artwork", "European & Oceanian debut",
           "European debut", "Oceanian debut", "Cr", "force-SMW"}
CORE = {"Common": "Common", "Short Print": "Common", "Super Short Print": "Common",
        "Rare": "Rare", "Super Rare": "Super Rare", "Ultra Rare": "Ultra Rare",
        "Secret Rare": "Secret Rare"}
TIERS = ["Common", "Rare", "Super Rare", "Ultra Rare", "Secret Rare", "Special finishes"]
PERIODS = {"2002-2006": (2002, 2006), "2021-2025": (2021, 2025)}

tier_count = {p: Counter() for p in PERIODS}
names_per_year = defaultdict(set)
for c in cards:
    for cs in c.get("card_sets", []):
        r = cs["set_rarity"].replace("PLatinum", "Platinum")   # fix typo
        d = ygo_set_date.get(cs["set_name"])
        if r in INVALID or not d:
            continue
        y = int(d[:4])
        names_per_year[y].add(r)
        tier = CORE.get(r, "Special finishes")
        for p, (a, b) in PERIODS.items():
            if a <= y <= b:
                tier_count[p][tier] += 1

waffle = []
for p, cnt in tier_count.items():
    total = sum(cnt.values())
    raw = {t: cnt[t] / total * 100 for t in TIERS}
    cells = {t: int(raw[t]) for t in TIERS}
    # largest remainder so cells add to 100
    for t in sorted(TIERS, key=lambda t: raw[t] - cells[t], reverse=True)[: 100 - sum(cells.values())]:
        cells[t] += 1
    i = 0
    for t in TIERS:
        for _ in range(cells[t]):
            waffle.append({"period": p, "tier": t, "share": round(raw[t], 1),
                           "col": i % 10, "row": i // 10})
            i += 1
write_csv("ygo_rarity_waffle.csv", waffle, ["period", "tier", "share", "col", "row"])

rows = [{"year": y, "rarity_names": len(n)} for y, n in sorted(names_per_year.items()) if 2002 <= y <= LAST_FULL_YEAR]
write_csv("ygo_rarity_names_by_year.csv", rows, ["year", "rarity_names"])


# ------------------------------------------------------------------
# 5. first 5 years vs last 5 years
# ------------------------------------------------------------------
first_year = {}
for s in sets:
    first_year.setdefault(s["game"], int(s["date"][:4]))

dumbbell = []
for g, fy in first_year.items():
    early = [per_year[(g, y)]["cards"] for y in range(fy, fy + 5)]
    late = [per_year[(g, y)]["cards"] for y in range(LAST_FULL_YEAR - 4, LAST_FULL_YEAR + 1)]
    dumbbell.append({"game": g, "period": f"First 5 years ({fy}-{fy + 4})", "stage": "First 5 years",
                     "cards_per_year": round(sum(early) / 5)})
    dumbbell.append({"game": g, "period": f"{LAST_FULL_YEAR - 4}-{LAST_FULL_YEAR}", "stage": "Last 5 years",
                     "cards_per_year": round(sum(late) / 5)})
write_csv("then_vs_now.csv", dumbbell, ["game", "period", "stage", "cards_per_year"])


# ------------------------------------------------------------------
# 6. card-type share, early vs recent
# ------------------------------------------------------------------
tot = Counter()
for (t, y), n in type_year.items():
    tot[y] += n
heat = [{"card_type": t, "year": y, "new_cards": n, "share": round(n / tot[y] * 100, 1)}
        for (t, y), n in sorted(type_year.items(), key=lambda k: (k[0][1], k[0][0]))]
write_csv("ygo_types_by_year.csv", heat, ["card_type", "year", "new_cards", "share"])

slope = []
for label, (a, b) in {"2002-2006": (2002, 2006), "2021-2025": (2021, 2025)}.items():
    sub = Counter()
    for (t, y), n in type_year.items():
        if a <= y <= b:
            sub[t] += n
    total = sum(sub.values())
    for t, n in sub.items():
        slope.append({"card_type": t, "period": label, "share": round(n / total * 100, 1)})
write_csv("ygo_types_then_now.csv", slope, ["card_type", "period", "share"])


# ------------------------------------------------------------------
# 7. printings per rarity per year
# ------------------------------------------------------------------
rar_year = Counter()
for c in cards:
    for cs in c.get("card_sets", []):
        r = cs["set_rarity"].replace("PLatinum", "Platinum")
        d = ygo_set_date.get(cs["set_name"])
        if r in INVALID or not d:
            continue
        y = int(d[:4])
        if 2002 <= y <= LAST_FULL_YEAR:
            rar_year[(r, y)] += 1
by_name = Counter()
for (r, y), n in rar_year.items():
    by_name[r] += n
keep = [r for r, n in by_name.items() if n >= 200]          # common enough to draw
first = {r: min(y for (rr, y) in rar_year if rr == r) for r in keep}
order = sorted(keep, key=lambda r: (first[r], -by_name[r]))       # by first appearance
ridge = []
for i, r in enumerate(order):
    peak = max(rar_year.get((r, y), 0) for y in range(2002, LAST_FULL_YEAR + 1))
    for y in range(2002, LAST_FULL_YEAR + 1):
        n = rar_year.get((r, y), 0)
        # row: which ridge; norm: height relative to the rarity's own peak (0-1), so each ridge is scaled separately
        # row index and height relative to the ridge's own peak
        ridge.append({"rarity": r, "row": i, "year": y, "printings": n, "first_year": first[r],
                      "norm": round(n / peak, 3)})
write_csv("ygo_rarity_by_year.csv", ridge, ["rarity", "row", "year", "printings", "first_year", "norm"])


# ------------------------------------------------------------------
# 8. median listed price by tier
# ------------------------------------------------------------------
from statistics import median
prices = defaultdict(list)
for c in cards:
    for cs in c.get("card_sets", []):
        r = cs["set_rarity"].replace("PLatinum", "Platinum")
        d = ygo_set_date.get(cs["set_name"])
        p = float(cs.get("set_price") or 0)
        if r in INVALID or not d or p <= 0:                   # no listed price
            continue
        y = int(d[:4])
        for label, (a, b) in PERIODS.items():
            if a <= y <= b:
                prices[(CORE.get(r, "Special finishes"), label)].append(p)
price_rows = [{"tier": t, "period": p, "median_price": round(median(v), 2), "printings": len(v)}
              for (t, p), v in sorted(prices.items())]
write_csv("ygo_price_then_now.csv", price_rows, ["tier", "period", "median_price", "printings"])


# ------------------------------------------------------------------
# 9. precomputed beeswarm offsets
#    x axis: cards per set (log scale, same as the chart's scale)
# ------------------------------------------------------------------
import math
MIN_SET = 60                         # full-size set threshold (60+ cards)
W, R = 420, 1.8                      # must match the spec
LO, HI = 50, 1500                     # log-scale domain
LANES = {"Magic: The Gathering": 35, "Pokémon": 95, "Yu-Gi-Oh!": 195}   # lane centres in px


def era(y):
    return "1993-2004" if y <= 2004 else "2005-2014" if y <= 2014 else "2015-2025"


def px(v):
    return (math.log10(v) - math.log10(LO)) / (math.log10(HI) - math.log10(LO)) * W


swarm = []
for g in LANES:
    pts = sorted([s for s in sets if s["game"] == g and int(s["date"][:4]) <= LAST_FULL_YEAR
                  and s["cards"] >= MIN_SET],                 # full-size sets only
                 key=lambda s: s["cards"])
    placed = []
    ties = Counter()
    for s in pts:
        # many sets share a size (e.g. 57 sets of 100 cards), so they are spread over 5 columns instead of one tall stack
        # identical sizes are fanned into 5 narrow columns so they do not form one tall tower
        k_tie = ties[s["cards"]]
        ties[s["cards"]] += 1
        x = px(min(max(s["cards"], LO), HI)) + ((k_tie % 5) - 2) * 2 * R
        step, k = 2 * R, 0
        while True:
            dy = (k + 1) // 2 * step * (1 if k % 2 else -1) if k else 0
            if all((x - px2) ** 2 + (dy - dy2) ** 2 >= (2 * R) ** 2 for px2, dy2 in placed if abs(x - px2) < 2 * R):
                break
            k += 1
        placed.append((x, dy))
        swarm.append({"game": g, "set_name": s["set_name"], "date": s["date"], "cards": s["cards"],
                      "era": era(int(s["date"][:4])), "x": round(x, 1), "y": LANES[g] + round(dy, 1)})
write_csv("sets_beeswarm.csv", swarm, ["game", "set_name", "date", "cards", "era", "x", "y"])
