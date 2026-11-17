#!/usr/bin/env python3
"""Turn data/days.json (raw parse) into a single self-contained index.html.

Usage: python3 -I build_site.py <days.json> <template.html> <out index.html>
"""
import datetime as dt
import json
import re
import sys

LABELS = {
    "CP Hotel": "CP hotel", "Field Hotel": "Field hotel", "Cast Hotel": "Cast hotel",
    "Local crew": "Lokální štáb", "Friends Hotel": "Friends hotel", "Drivers Hotel": "Hotel řidičů",
}
MONTH_SHORT = ["", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.", "11.", "12."]
WD_SHORT = ["po", "út", "st", "čt", "pá", "so", "ne"]
GPS_RE = re.compile(r"""(\d{1,3})°\s?(\d{1,2})'\s?([\d.]+)"\s?([NS])\s+(\d{1,3})°\s?(\d{1,2})'\s?([\d.]+)"\s?([EW])""")


def mins(t):
    a, b = t.split(":")
    return int(a) * 60 + int(b)


def fmt(m):
    return f"{m // 60}:{m % 60:02d}"


def dec(g):
    m = GPS_RE.search(g or "")
    if not m:
        return None
    lat = int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600
    lon = int(m[5]) + int(m[6]) / 60 + float(m[7]) / 3600
    return (lat * (1 if m[4] == "N" else -1), lon * (1 if m[8] == "E" else -1))


def near(a, b, tol=0.002):
    return a is not None and b is not None and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def kind_of(action):
    a = action.lower()
    if re.search(r"set ?up|contestants on set", a):
        return "setup"
    if re.search(r"^(hh[- ]race|start the race|bike race|alternative transport|on cam|off cam|transfer|hike|arrival to|kayak)", a):
        return "move"
    if "mission" in a:
        return "mission"
    if "amulet game" in a:
        return "game"
    if re.search(r"ranking|stop the race|ewl", a):
        return "rank"
    if re.search(r"check ?(in|out|point)|checkout|log ?(in|out)", a):
        return "check"
    if re.search(r"communal|morning with locals|camping", a):
        return "comm"
    return "other"


def norm_unit(u):
    who = u.get("who", "")
    notes = [n for n in list(u.get("notes", [])) + list(u.get("extra", []))
             if n.strip() and n.strip().lower() not in who.lower()]
    return {
        "name": u["name"],
        "who": u.get("who", ""),
        "bf": u.get("breakfast", ""),
        "load": u.get("loading", ""),
        "legs": u.get("legs", []),
        "notes": notes,
    }


def attach_units(segs, units):
    """Attach units to the first shooting block at a location (matched by GPS)."""
    prev_loc, prev_gps = None, None
    for s in segs:
        if "divider" in s:
            continue
        g = dec(s.get("gps"))
        loc_key = re.sub(r"\W+", "", (s.get("loc") or "").lower())
        if g is None and prev_loc and loc_key == prev_loc and loc_key:
            s["same"] = True
            continue
        if g is None:
            prev_loc = None
            continue
        if prev_gps is not None and near(g, prev_gps):
            s["same"] = True
            prev_gps, prev_loc = g, loc_key
            continue
        prev_gps, prev_loc = g, loc_key
        refs = []
        for ui, u in enumerate(units):
            for li, leg in enumerate(u["legs"]):
                if near(dec(leg.get("to_gps")), g):
                    refs.append([ui, li, "arr"])
                elif near(dec(leg.get("from_gps")), g):
                    refs.append([ui, li, "dep"])
        s["units"] = refs


def build_plan(d):
    segs = []
    for r in d["plan"]:
        if "divider" in r:
            segs.append({"divider": r["divider"]})
            continue
        t, dur = r.get("time", ""), r.get("dur", "")
        end = ""
        m = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$", t)
        if m:
            segs.append({"t": "", "d": "", "end": "", "win": f"{m.group(1)}–{m.group(2)}", "team": r["team"], "name": r["action"],
                         "loc": r["where"], "gps": r["gps"], "km": r["km"], "kind": kind_of(r["action"])})
            continue
        elif t and dur:
            end = fmt(mins(t) + mins(dur))
        segs.append({"t": t, "d": dur, "end": end, "team": r["team"], "name": r["action"], "loc": r["where"],
                     "gps": r["gps"], "km": r["km"], "kind": kind_of(r["action"])})
    # a merged time cell (e.g. 10:30 - 15:35) covers the neighbouring rows that have no time of their own
    for i, sg in enumerate(segs):
        if sg.get("win"):
            for rng in (range(i - 1, -1, -1), range(i + 1, len(segs))):
                for j in rng:
                    o = segs[j]
                    if "divider" in o or o.get("t") or o.get("win"):
                        break
                    o["win"] = sg["win"]
    return segs


def build_rr(d):
    """In-between day: merge duplicated meetings, add flights."""
    merged = {}
    for m in d["meetings"]:
        key = (m["start"], m["end"], m["what"].lower(), m["where"].lower())
        e = merged.setdefault(key, {"t": m["start"], "end": m["end"], "name": m["what"], "loc": m["where"],
                                    "teams": [], "who": [], "remarks": [], "kind": "meet", "gps": "", "km": "",
                                    "d": fmt(mins(m["end"]) - mins(m["start"]))})
        if m["team"] and m["team"] not in e["teams"]:
            e["teams"].append(m["team"])
        if m["who"] and m["who"] not in e["who"]:
            e["who"].append(m["who"])
        if m["remarks"] and m["remarks"] not in e["remarks"]:
            e["remarks"].append(m["remarks"])
    segs = []
    for e in merged.values():
        e["team"] = " · ".join(e["teams"])
        segs.append(e)
    for f in d["flights"]:
        info = f["info"]
        airport = next((i for i in info if re.search(r"airport|terminal", i, re.I)), "")
        rest = [i for i in info if i != airport]
        segs.append({"t": f["time"], "end": "", "d": "", "name": f"Let {f['flight']} {f['route']}", "loc": airport,
                     "team": "Lety", "kind": "flight", "gps": "", "km": "", "who": [], "remarks": rest})
    segs.sort(key=lambda s: (mins(s["t"]), s["name"]))
    return segs


def build():
    src, tpl, out = sys.argv[1:4]
    raw = json.load(open(src, encoding="utf-8"))
    by_day = {d["day"]: d for d in raw}
    days = []
    for n in range(raw[0]["day"], raw[-1]["day"] + 1):
        d = by_day.get(n)
        date = dt.date.fromisoformat(d["date"]) if d else dt.date(2026, 10, 30) + dt.timedelta(days=n - 5)
        short = f"{WD_SHORT[date.weekday()]} {date.day}. {date.month}."
        if d is None:
            days.append({"id": f"day{n}", "missing": True, "day": n, "date": date.isoformat(), "tab": f"Day {n}",
                         "sub": short + " · chybí"})
            continue
        h = d["header"]
        facts = [["Východ / západ slunce", f"{h['sunrise']} / {h['sunset']}"], ["Počasí", h["weather"]]]
        for lab, val in h["hotels"]:
            facts.append([LABELS.get(lab, lab), val])
        units = [norm_unit(u) for u in d["units"]]
        if d["rr"]:
            segs = build_rr(d)
            tab, did = "Mezi-den", f"d{date.day}-{date.month}"
        else:
            segs = build_plan(d)
            attach_units(segs, units)
            tab, did = f"ND{d['nd']}", f"nd{d['nd']}"
        warn = ""
        pd_ = d["printed_date"]
        exp_day = f"{date.day}"
        if d["printed_day"] != d["day"] or (pd_ and not re.search(rf"\b{exp_day}(st|nd|rd|th)\b", pd_)):
            warn = f"V callsheetu je uvedeno „Day {d['printed_day']} of 24, {pd_}“. Datum a číslo dne jsou dopočítané z pořadí."
        flights = d["flights"] if not d["rr"] else []
        days.append({
            "id": did, "day": d["day"], "nd": d.get("nd"), "rr": d["rr"], "date": date.isoformat(), "tab": tab,
            "sub": short, "long": f"{['pondělí','úterý','středa','čtvrtek','pátek','sobota','neděle'][date.weekday()]} {date.day}. {date.month}. {date.year}",
            "rrTitle": h.get("rr_title", ""), "facts": facts, "segs": segs, "units": units,
            "prep": d["prep"], "hotels": d["hotels"], "meals": d["meals"], "flights": flights,
            "notes": d["prod_notes"], "warn": warn,
        })
    html = open(tpl, encoding="utf-8").read()
    payload = json.dumps(days, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    open(out, "w", encoding="utf-8").write(html.replace("/*__DATA__*/[]", payload))
    print("built", out, len(days), "days,", len(payload) // 1024, "KB data")


if __name__ == "__main__":
    build()
