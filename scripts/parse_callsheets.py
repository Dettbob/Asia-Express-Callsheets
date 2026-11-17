#!/usr/bin/env python3
"""Parse Asia Express 2 (Prima CZ) callsheet PDFs into data/days.json.

Usage: python3 -I parse_callsheets.py <dir-with-pdfs> <out.json>
Reads every *DAY_<n>[_RR].pdf in the directory. Day 5 is ND4 (Fri 30 Oct 2026); days marked RR
are in-between ("rest") days that have no RACE PLANNING table.
"""
import datetime as dt
import glob
import json
import re
import subprocess
import sys

import pdfplumber

WHITE = [(1.0, 1.0, 1.0), (1, 1, 1)]
GPS_RE = re.compile(r"""\d{1,3}°\s?\d{1,2}'\s?\d{1,2}(?:\.\d+)?"\s?[NS]\s+\d{1,3}°\s?\d{1,2}'\s?\d{1,2}(?:\.\d+)?"\s?[EW]""")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
RANGE_RE = re.compile(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$")
FLIGHT_RE = re.compile(r"^[A-Z0-9]{2}\s?\d{2,4}$")
ROUTE_RE = re.compile(r"^[A-Z]{3}\s?-\s?[A-Z]{3}$")
FIRST_DAY = (5, dt.date(2026, 10, 30))  # Day 5 = Friday 30 Oct 2026
CZ_DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def poppler(pdf, page, x, y, w, h, layout=True):
    cmd = ["pdftotext", "-f", str(page), "-l", str(page), "-x", str(int(x)), "-y", str(int(y)),
           "-W", str(int(w)), "-H", str(int(h))]
    if layout:
        cmd.append("-layout")
    cmd += [pdf, "-"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def day_info(n):
    d = FIRST_DAY[1] + dt.timedelta(days=n - FIRST_DAY[0])
    return d


# ---------------------------------------------------------------- header
def parse_header(pdf, page_unused=None):
    with pdfplumber.open(pdf) as doc:
        p = doc.pages[0]
        ws = p.crop((55, 118, 262, 172)).extract_words(x_tolerance=2, y_tolerance=2)
        for w in ws:
            w["cy"] = (w["top"] + w["bottom"]) / 2
        out = {"sunrise": "", "sunset": "", "weather": "", "hotels": [], "rr_title": ""}
        full = p.crop((0, 95, 440, 200)).extract_text() or ""
        m = re.search(r"SUNRISE:\s*([\d:]+)", full); out["sunrise"] = m.group(1) if m else ""
        m = re.search(r"SUNSET:\s*([\d:]+)", full); out["sunset"] = m.group(1) if m else ""
        cp = next((w for w in ws if w["text"] == "CP"), None)
        xl = cp["x0"] if cp else 157
        labels = []
        for w in ws:
            if w["text"] in ("Hotel:", "crew:") and w["x0"] >= xl - 2:
                same = [v for v in ws if abs(v["cy"] - w["cy"]) < 4 and xl - 3 <= v["x0"] < w["x0"]]
                above = [v for v in ws if 0 < w["cy"] - v["cy"] < 16 and xl - 3 <= v["x0"] < xl + 24 and v["text"] not in ("Hotel:", "crew:")]
                lab = " ".join(v["text"] for v in sorted(same, key=lambda v: v["x0"])) or " ".join(v["text"] for v in above[-1:])
                labels.append({"name": clean(lab + " " + w["text"]).rstrip(":"), "cy": w["cy"], "vals": []})
        for w in ws:
            if w["x0"] >= xl + 24 and labels:
                tgt = min(labels, key=lambda L: abs(L["cy"] - w["cy"]))
                tgt["vals"].append(w)
        for L in labels:
            vs = sorted(L["vals"], key=lambda w: (round(w["cy"] / 5), w["x0"]))
            out["hotels"].append([L["name"], clean(" ".join(w["text"] for w in vs))])
        # weather: left column below the sunset line
        wx = [w for w in ws if w["cy"] > 150 and w["x0"] > 95 and w["x0"] < xl - 5]
        wx = sorted(wx, key=lambda w: (round(w["cy"] / 4), w["x0"]))
        out["weather"] = clean(" ".join(w["text"] for w in wx)).replace(" - ", "-").replace("° -", "°-")
        t = poppler(pdf, 1, 235, 140, 215, 45, layout=False)
        m = re.search(r"REST\s*&\s*([A-Z]{4,})", t)
        out["rr_title"] = ("REST & " + m.group(1)) if m else ""
    return out


def parse_prodnotes(pdf, p):
    # the orange/yellow "PRODUCTION NOTES" box
    cand = [r for r in p.rects if r.get("fill") and r["width"] > 100 and 25 < r["height"] < 90 and r["top"] < 190
            and tuple(round(x, 2) for x in (r.get("non_stroking_color") or ())) in [(1.0, 0.75, 0.0), (1.0, 0.75, 0.0, )]]
    if not cand:
        cand = [r for r in p.rects if r["top"] < 190 and r["x0"] > 400 and r["width"] > 100 and 25 < r["height"] < 90 and r.get("fill")]
    if not cand:
        return []
    r = max(cand, key=lambda r: r["height"])
    t = poppler(pdf, 1, r["x0"], r["top"], r["width"], r["height"], layout=False)
    lines = [clean(l) for l in t.splitlines() if clean(l)]
    lines = [l for l in lines if l.upper() != "PRODUCTION NOTES"]
    # re-join wrapped lines: new note starts with "*"
    notes = []
    for l in lines:
        if l.startswith("*") or not notes:
            notes.append(l.lstrip("* ").strip())
        else:
            notes[-1] += " " + l
    return [n for n in notes if n]


# ---------------------------------------------------------------- units
def is_title(p, r):
    t = (p.crop((r["x0"], r["top"], r["x1"], r["bottom"])).extract_text() or "").strip()
    if not t:
        return None
    first = t.split("\n")[0]
    if first != first.upper() or not re.search(r"[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2}", first):
        return None
    return t


def find_boxes(p):
    rs = [r for r in p.rects if 90 < r["width"] < 200 and 10 < r["height"] < 30 and r["top"] > 175
          and r.get("non_stroking_color") not in WHITE and r.get("fill")]
    seen, T = set(), []
    for r in sorted(rs, key=lambda r: (round(r["top"]), r["x0"])):
        k = (round(r["x0"]), round(r["top"]))
        if k in seen:
            continue
        seen.add(k)
        t = is_title(p, r)
        if t:
            T.append((r, t))
    tabs = p.find_tables()
    bottom = max(tb.bbox[3] for tb in tabs) if tabs else p.height - 40
    out = []
    for r, t in T:
        below = [r2["top"] for r2, _ in T if r2["top"] > r["top"] + 5 and not (r2["x1"] < r["x0"] + 5 or r2["x0"] > r["x1"] - 5)]
        out.append((r, t, min(below) if below else bottom))
    return out


def split_title(t):
    parts = [clean(x) for x in t.split("\n") if clean(x)]
    name = parts[0]
    who = " ".join(parts[1:])
    # some titles are written "NAME (note)" on line 2
    return name, who


def parse_unit_body(txt):
    lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
    u = {"breakfast": "", "loading": "", "legs": [], "notes": []}
    cur = None  # current leg
    mode = None
    in_notes = False
    extra = []
    for raw in lines:
        l = clean(raw)
        if not l:
            continue
        low = l.lower()
        m = re.match(r"^(from\s+\d{1,2}:\d{2}|o\.?s\.?|\d{1,2}:\d{2}|-)?\s*breakfast\b(.*)$", l, re.I)
        if m and not in_notes:
            u["breakfast"] = clean((m.group(1) or "") + " " + m.group(2)) or "-"
            continue
        m = re.match(r"^(\d{1,2}:\d{2}|o\.?s\.?|-)?\s*loading\b(.*)$", l, re.I)
        if m and not in_notes:
            u["loading"] = clean((m.group(1) or "") + " " + m.group(2))
            continue
        m = re.match(r"^(departure|arrival)\b\s*-?\s*(.*)$", l, re.I)
        if m and not in_notes:
            mode = m.group(1).lower()
            if mode == "departure":
                cur = {"dep": "", "from": "", "from_gps": "", "arr": "", "to": "", "to_gps": "", "label": clean(m.group(2))}
                u["legs"].append(cur)
            else:
                if cur is None or cur.get("arr") or cur.get("to"):
                    cur = {"dep": "", "from": "", "from_gps": "", "arr": "", "to": "", "to_gps": "", "label": clean(m.group(2))}
                    u["legs"].append(cur)
            continue
        if low.startswith("notes"):
            in_notes = True
            rest = clean(re.sub(r"^notes:?", "", l, flags=re.I))
            if rest:
                u["notes"].append(rest)
            continue
        if in_notes:
            u["notes"].append(l)
            continue
        if cur is None:
            extra.append(l)
            continue
        # time at the start of the line
        m = re.match(r"^(\d{1,2}:\d{2}|o\.?s\.?|-)\s*(.*)$", l, re.I)
        rest = l
        if m and (TIME_RE.match(m.group(1)) or m.group(1).lower().startswith("o") or m.group(1) == "-") and mode:
            t = m.group(1)
            if mode == "departure" and not cur["dep"]:
                cur["dep"] = t
            elif mode == "arrival" and not cur["arr"]:
                cur["arr"] = t
            rest = m.group(2)
            if not rest:
                continue
        gm = GPS_RE.search(rest)
        gps = gm.group(0) if gm else ""
        place = clean(rest.replace(gps, "")) if gps else clean(rest)
        if re.match(r"^from:?\b", place, re.I):
            cur["from"] = clean(re.sub(r"^from:?", "", place, flags=re.I)); cur["from_gps"] = gps or cur["from_gps"]
            last = "from"
        elif re.match(r"^to:?\b", place, re.I):
            cur["to"] = clean(re.sub(r"^to:?", "", place, flags=re.I)); cur["to_gps"] = gps or cur["to_gps"]
            last = "to"
        else:
            # continuation line of previous place, or a free note
            tgt = "to" if (mode == "arrival") else "from"
            sentence = ">" in place or re.match(r"^(note|stay|then|after|pick|wait|bring|driver)", place, re.I) or (cur[tgt + "_gps"] and len(place.split()) > 3)
            if cur[tgt] and not TIME_RE.match(place) and not sentence:
                cur[tgt] = clean(cur[tgt] + " " + place)
                if gps:
                    cur[tgt + "_gps"] = gps
            else:
                extra.append(place)
    u["extra"] = extra
    return u


def parse_units(pdf):
    out = []
    with pdfplumber.open(pdf) as doc:
        p = doc.pages[0]
        for r, t, y1 in find_boxes(p):
            name, who = split_title(t)
            body = poppler(pdf, 1, r["x0"] - 2, r["bottom"] - 1, r["x1"] - r["x0"] + 4, y1 - r["bottom"] - 1)
            u = parse_unit_body(body)
            u["name"] = name
            u["who"] = who
            out.append(u)
    return out


# ---------------------------------------------------------------- tables
SECTIONS = [
    ("plan", {"TEAM", "TIME", "ACTION", "LOCATION"}),
    ("prep", {"TEAM", "TIME", "ACTION", "WHERE", "WHO"}),
    ("hotels", {"TEAM", "CITY", "HOTEL NAME"}),
    ("meals", {"TEAM", "MEAL", "TYPE"}),
    ("meetings", {"TEAM", "WHO", "TIME", "WHAT"}),
]


def header_kind(cells):
    names = {c.upper() for c in cells if c}
    for kind, need in SECTIONS:
        if need <= names:
            return kind
    return None


LABEL_POOL = "RACEPLANNINGHOTELSMEALSPREPMEETINGS"
KM_RE = re.compile(r"^\d+(?:[.,]\d+)?\s?(?:km|m)$", re.I)


def is_label_cell(c):
    t = re.sub(r"[^A-Z]", "", c)
    return bool(t) and c == c.upper() and len(t) <= 14 and t[::-1] in LABEL_POOL and not TIME_RE.match(c)


def parse_tables(pdf):
    sections = {k: [] for k, _ in SECTIONS}
    flights = []
    with pdfplumber.open(pdf) as doc:
        cur, cols, cols_tid = None, {}, None
        last_team = ""
        tid = 0
        for pi, page in enumerate(doc.pages):
            for tbl in page.extract_tables():
                tid += 1
                for row in tbl:
                    cells = [clean(c) for c in row]
                    nonempty = [c for c in cells if c]
                    if not nonempty:
                        continue
                    kind = header_kind(cells)
                    if kind:
                        cur = kind
                        cols = {c.upper(): i for i, c in enumerate(cells) if c}
                        cols_tid = tid
                        last_team = ""
                        continue
                    if any(FLIGHT_RE.match(c) for c in nonempty) and any(ROUTE_RE.match(c) for c in nonempty):
                        flights.append(parse_flight(cells))
                        continue
                    if cur is None:
                        continue
                    if len(nonempty) == 1 and re.search(r"EPISODE|CYCLE|MIXED|FINAL", nonempty[0], re.I) and cur == "plan":
                        sections["plan"].append({"divider": nonempty[0]})
                        continue
                    if cur == "meetings":
                        rec = parse_meeting(cells, last_team)
                        if rec:
                            last_team = rec["team"]
                            sections["meetings"].append(rec)
                        continue
                    rec = row_by_cols(cells, cols) if tid == cols_tid and cur != "plan" else row_by_order(cur, cells)
                    if rec and cur == "plan" and re.match(r"^(EPISODE|CYCLE)\b", rec["team"], re.I) and not rec["time"] and not rec["action"]:
                        sections["plan"].append({"divider": rec["team"]})
                        continue
                    if rec:
                        sections[cur].append(rec)
    return sections, flights


BLANK = {"team": "", "time": "", "action": "", "where": "", "who": "", "remarks": "", "city": "", "hotel": "",
         "address": "", "gps": "", "meal": "", "type": "", "km": "", "dur": ""}


def row_by_order(kind, cells):
    texts = []
    gps = km = dur = time = ""
    for c in cells:
        if not c or is_label_cell(c):
            continue
        texts.append(c)
    rec = dict(BLANK)
    rest = []
    for c in texts:
        if GPS_RE.search(c) and not rec["gps"]:
            rec["gps"] = c
        else:
            rest.append(c)
    if kind == "plan":
        rest2 = []
        for c in rest:
            if KM_RE.match(c) and not rec["km"]:
                rec["km"] = c
            else:
                rest2.append(c)
        # duration = last h:mm cell, time = first h:mm or range cell
        times = [c for c in rest2 if TIME_RE.match(c) or RANGE_RE.match(c) or re.match(r"^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$", c)]
        if times:
            first_idx = rest2.index(times[0])
            # time cell sits right after the team cell; duration is the last time-like cell if there are two
            if len(times) >= 2:
                rec["time"], rec["dur"] = times[0], times[-1]
            else:
                # lone time-like cell: it is the duration if it comes after the action text, else the start time
                rec["time"] = times[0] if first_idx <= 1 else ""
                rec["dur"] = times[0] if first_idx > 1 else ""
            rest2 = [c for c in rest2 if c not in (rec["time"], rec["dur"]) or c == ""]
            # remove only the first occurrence of each
        texts2 = [c for c in rest2]
        rec["team"] = texts2[0] if texts2 else ""
        rec["action"] = texts2[1] if len(texts2) > 1 else ""
        rec["where"] = texts2[2] if len(texts2) > 2 else ""
    elif kind == "prep":
        rec["team"] = rest[0] if rest else ""
        rec["time"] = rest[1] if len(rest) > 1 else ""
        rec["action"] = rest[2] if len(rest) > 2 else ""
        rec["where"] = rest[3] if len(rest) > 3 else ""
        rec["who"] = rest[4] if len(rest) > 4 else ""
        rec["remarks"] = rest[5] if len(rest) > 5 else ""
    elif kind == "hotels":
        rec["team"] = rest[0] if rest else ""
        rec["city"] = rest[1] if len(rest) > 1 else ""
        rec["hotel"] = rest[2] if len(rest) > 2 else ""
        rec["address"] = rest[3] if len(rest) > 3 else ""
    elif kind == "meals":
        rec["team"] = rest[0] if rest else ""
        rec["meal"] = rest[1] if len(rest) > 1 else ""
        rec["type"] = rest[2] if len(rest) > 2 else ""
        rec["where"] = rest[3] if len(rest) > 3 else ""
        rec["remarks"] = rest[4] if len(rest) > 4 else ""
    return rec if any(rec.values()) else None


def row_by_cols(cells, cols):
    def g(*names):
        for n in names:
            i = cols.get(n)
            if i is not None and i < len(cells) and cells[i]:
                return cells[i]
        return ""
    rec = {"team": g("TEAM"), "time": g("TIME"), "action": g("ACTION"), "where": g("WHERE", "LOCATION"),
           "who": g("WHO"), "remarks": g("REMARKS"), "city": g("CITY"), "hotel": g("HOTEL NAME"),
           "address": g("ADDRESS"), "gps": g("GPS"), "meal": g("MEAL"), "type": g("TYPE"),
           "km": g("DISTANCE KM"), "dur": g("DURATION")}
    if not any(rec.values()):
        return None
    return rec


def parse_meeting(cells, last_team):
    idx = next((i for i, c in enumerate(cells) if RANGE_RE.match(c)), None)
    if idx is None:
        return None
    left = [c for c in cells[:idx] if c]
    right = [c for c in cells[idx + 1:] if c]
    m = RANGE_RE.match(cells[idx])
    who = left[-1] if left else ""
    team = left[-2] if len(left) >= 2 else last_team
    # a lone left cell can be either a team label or a who list; team labels are short and uppercase
    if len(left) == 1 and left[0].isupper() and len(left[0]) < 24:
        team, who = left[0], ""
    return {"team": team, "who": who, "start": m.group(1), "end": m.group(2),
            "what": right[0] if right else "", "where": right[1] if len(right) > 1 else "",
            "remarks": right[2] if len(right) > 2 else ""}


def keep_flight_info(c):
    """Keep airport and role/notes cells, drop passenger full names."""
    return bool(re.search(r"airport|terminal|>|\bLPA\b|driver|be at|pick", c, re.I))


def parse_flight(cells):
    ne = [c for c in cells if c]
    rec = {"time": "", "flight": "", "route": "", "info": []}
    for c in ne:
        if TIME_RE.match(c) and not rec["time"]:
            rec["time"] = c
        elif FLIGHT_RE.match(c) and not rec["flight"]:
            rec["flight"] = c
        elif ROUTE_RE.match(c) and not rec["route"]:
            rec["route"] = c
        elif re.sub(r"[^A-Z]", "", c)[::-1] in "DEPARTURESARRIVALS" and c == c.upper() and len(c) >= 4:
            continue
        else:
            rec["info"].append(c)
    rec["info"] = [c for c in rec["info"] if keep_flight_info(c)]
    return rec


def parse_day(path):
    n = int(re.search(r"DAY_(\d+)", path).group(1))
    rr = "_RR" in path
    d = day_info(n)
    with pdfplumber.open(path) as doc:
        p = doc.pages[0]
        printed = clean(p.crop((0, 60, p.width, 115)).extract_text())
        notes = parse_prodnotes(path, p)
    m = re.search(r"DAY\s+(\d+)\s+OF\s+24\s+(.*)$", printed)
    printed_day = int(m.group(1)) if m else n
    printed_date = clean(m.group(2)) if m else ""
    hdr = parse_header(path)
    sections, flights = parse_tables(path)
    units = parse_units(path)
    title_kind = ""
    return {
        "day": n, "rr": rr, "date": d.isoformat(), "weekday": CZ_DAYS[d.weekday()],
        "printed_day": printed_day, "printed_date": printed_date,
        "header": hdr, "prod_notes": notes, "flights": flights, "units": units,
        "plan": sections["plan"], "prep": sections["prep"], "hotels": sections["hotels"],
        "meals": sections["meals"], "meetings": sections["meetings"],
    }


PHONE_RE = re.compile(r"\+?\d[\d ]{7,}\d")
NAME_BEFORE_ARROW = re.compile(r"\b([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+)\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+(?=\s*>\s*\+?\d)")


def scrub(o):
    """Remove phone numbers (and surnames written right before them) from every string in the data."""
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    if isinstance(o, str) and PHONE_RE.search(o) and "°" not in o:
        o = NAME_BEFORE_ARROW.sub(r"\1", o)
        return PHONE_RE.sub("(telefon vynechán)", o)
    return o


def main():
    src, out = sys.argv[1], sys.argv[2]
    files = sorted(glob.glob(src.rstrip("/") + "/*DAY_*.pdf"), key=lambda f: int(re.search(r"DAY_(\d+)", f).group(1)))
    days = [parse_day(f) for f in files]
    # ND numbering: every non-RR day increments the counter; Day 5 is ND4.
    # Day 16 is not provided but is assumed to be a shooting day (ND13), so numbering stays continuous.
    nd = 3
    prev = None
    present = {d["day"] for d in days}
    for n in range(2, 25):
        pass
    rr_days = {d["day"] for d in days if d["rr"]}
    for d in days:
        if d["rr"]:
            d["label"] = None
        else:
            d["nd"] = d["day"] - 1 - len([x for x in rr_days if x < d["day"]])
    json.dump(scrub(days), open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", out, len(days), "days")


if __name__ == "__main__":
    main()
