# python
from dataclasses import dataclass
from datetime import datetime
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET
import argparse
import sys

# ANSI colors (simple)
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%S",
]


@dataclass
class Incident:
    id: str
    date: datetime | None
    type: str
    severity: str
    location: str
    description: str
    raw: dict


def try_parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    # try parse year-only or fallback numeric year
    try:
        if len(s) == 4 and s.isdigit():
            return datetime(int(s), 1, 1)
    except Exception:
        pass
    return None


def normalize_text(s: str) -> str:
    if s is None:
        return ""
    return " ".join(s.strip().split())


def parse_xml(path: str) -> list[Incident]:
    try:
        tree = ET.parse(path)
    except Exception as e:
        print(f"{RED}Error parsing XML:{RESET} {e}", file=sys.stderr)
        return []

    root = tree.getroot()
    records = []

    # Guess record nodes: children of root; skip attributes-only root
    for elem in root:
        # build map of child tag -> text (flatten)
        data = {}
        for child in elem:
            tag = child.tag.lower()
            # strip namespace if present
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            data[tag] = normalize_text(child.text)
        # fallback: if elem has text itself and no children, treat as value
        if not data and (elem.text and elem.text.strip()):
            data[elem.tag.lower()] = normalize_text(elem.text)

        # heuristics for common field names
        id_ = data.get("id") or data.get("identificador") or data.get("incidenciaid") or data.get("codigo") or ""
        date_s = data.get("date") or data.get("data") or data.get("fecha") or data.get("dia") or ""
        date = try_parse_date(date_s)
        type_ = data.get("type") or data.get("tipus") or data.get("categoria") or data.get("categoria_incidencia") or data.get("clasificacion") or ""
        severity = data.get("severity") or data.get("gravedad") or data.get("nivel") or data.get("prioritat") or ""
        location = data.get("location") or data.get("municipi") or data.get("place") or data.get("localitat") or ""
        description = data.get("description") or data.get("descripcio") or data.get("detall") or ""

        inc = Incident(
            id=id_,
            date=date,
            type=type_,
            severity=severity,
            location=location,
            description=description,
            raw=data,
        )
        records.append(inc)
    return records


def filter_incidents(records: list[Incident]) -> tuple[list[Incident], int]:
    filtered = []
    removed = 0
    now_year = datetime.now().year
    for r in records:
        # remove if no id and no date and no type
        if (not r.id) and (r.date is None) and (not r.type):
            removed += 1
            continue
        # remove if date year obviously wrong (far future or too old)
        if r.date:
            y = r.date.year
            if y > now_year + 2 or y < 1900:
                removed += 1
                continue
        filtered.append(r)
    return filtered, removed


def compute_stats(records: list[Incident]) -> dict:
    stats = {}
    stats["total"] = len(records)
    by_year = Counter()
    by_type = Counter()
    by_severity = Counter()
    by_location = Counter()

    for r in records:
        if r.date:
            by_year[r.date.year] += 1
        else:
            by_year["unknown"] += 1
        by_type[r.type or "unknown"] += 1
        by_severity[r.severity or "unknown"] += 1
        by_location[r.location or "unknown"] += 1

    stats["by_year"] = by_year
    stats["by_type"] = by_type
    stats["by_severity"] = by_severity
    stats["by_location"] = by_location
    return stats


def pretty_print(records: list[Incident], stats: dict, removed_count: int, no_color: bool = False, show_examples: int = 5):
    C = {"B": BOLD, "G": GREEN, "Y": YELLOW, "R": RED, "C": CYAN, "Z": RESET}
    if no_color:
        for k in C:
            C[k] = ""
    print(f"{C['B']}{C['C']}Incidents summary{C['Z']}")
    print(f" Total parsed: {len(records) + removed_count}")
    print(f" Valid: {C['G']}{stats['total']}{C['Z']}  Removed (filtered): {C['Y']}{removed_count}{C['Z']}\n")

    def print_counter(title, counter: Counter, top=10):
        print(f"{C['B']}{title}{C['Z']}")
        for i, (k, v) in enumerate(counter.most_common(top), 1):
            print(f" {i:2d}. {k:20.20s}  {C['G']}{v}{C['Z']}")
        print()

    print_counter("Incidents by year", stats["by_year"])
    print_counter("Incidents by type", stats["by_type"])
    print_counter("Incidents by severity", stats["by_severity"])
    print_counter("Top locations", stats["by_location"])

    if show_examples:
        print(f"{C['B']}Example records (first {show_examples}):{C['Z']}")
        for r in records[:show_examples]:
            d = r.date.strftime("%Y-%m-%d") if r.date else "unknown"
            print(f" - {C['Y']}{d}{C['Z']} | {C['C']}{r.type or 'no-type'}{C['Z']} | {r.location or 'no-location'} | {r.id or '-'}")
            if r.description:
                desc = r.description
                if len(desc) > 140:
                    desc = desc[:137] + "..."
                print(f"    {desc}")
        print()


def main():
    p = argparse.ArgumentParser(description="Process incidents XML and show statistics")
    p.add_argument("xml", nargs="?", default="incidencies.xml", help="XML file path")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    p.add_argument("--examples", type=int, default=5, help="Show example records")
    args = p.parse_args()

    records = parse_xml(args.xml)
    if not records:
        print(f"{RED}No records found in file {args.xml}{RESET}", file=sys.stderr)
        return

    filtered, removed = filter_incidents(records)
    stats = compute_stats(filtered)
    pretty_print(filtered, stats, removed, no_color=args.no_color, show_examples=args.examples)


if __name__ == "__main__":
    main()
 #