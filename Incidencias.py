#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script sencillo para procesar /home/.../Incidencies.xml y mostrar información
significativa por consola con colores.
"""
import argparse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from operator import itemgetter
import textwrap
import sys
import json
from pathlib import Path
import re

try:
    from colorama import init as colorama_init, Fore, Style
except Exception:
    # If colorama is not installed, provide minimal fallback
    class _Fake:
        RESET_ALL = ''
        RED = ''
        YELLOW = ''
        GREEN = ''
        CYAN = ''
        MAGENTA = ''
        BLUE = ''
        WHITE = ''
        BRIGHT = ''
    Fore = _Fake()
    Style = _Fake()
    def colorama_init(): pass

colorama_init(autoreset=True)

# Tags used in the XML (exact names from el fichero)
TAG_TIMESTAMP = "Marca_de_temps"
TAG_PRIORITY = "Prioritat_de_la_incidència"
TAG_TYPE = "Tipus_de_equip__PC__impressora__projector__televisor__switch_"
TAG_LOCATION = "Ubicació"
TAG_INFORMANT = "Nom_i_cognoms_d_informant"
TAG_EMAIL = "Adreça_electrònica"
TAG_DESC = "Descripció_de_la_incidència"
TAG_FUNCIONA = "_El_equipament_funciona_actualment_"
TAG_DATE = "Data_de_incidència"
TAG_TIME = "Hora_de_incidència"

def get_text(elem, tag):
    t = elem.find(tag)
    if t is None or t.text is None:
        return ""
    return t.text.strip()

def try_parse_timestamp(ts_text, date_text, time_text):
    # Try multiple formats, return datetime or None
    candidates = []
    if ts_text:
        candidates.append(ts_text)
    if date_text:
        # combine date and time if available
        combined = date_text + (' ' + time_text if time_text else '')
        candidates.append(combined)
    for s in candidates:
        s = s.strip()
        if not s:
            continue
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None

# --- NEW helpers for validation ---
def looks_like_email(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    # simple email heuristic
    return bool(re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", s))

def vowel_ratio(s: str) -> float:
    if not s:
        return 0.0
    letters = re.findall(r"[A-Za-z]", s)
    if not letters:
        return 0.0
    vowels = sum(1 for ch in letters if ch.lower() in "aeiouáéíóúàèìòù")
    return vowels / len(letters)

def is_gibberish(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    # Consider gibberish: long token with very few vowels, or many non-letter characters
    if len(s) >= 6:
        vr = vowel_ratio(s)
        non_alnum = sum(1 for ch in s if not ch.isalnum())
        # heuristics tuned to catch things like "sdgbJnnP" or random tokens/full of symbols
        if vr < 0.15 or non_alnum / max(1, len(s)) > 0.4:
            return True
    # also short tokens consisting only of repeated consonants
    if re.fullmatch(r"[bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ]{4,}", s):
        return True
    return False

# --- NEW: enhanced validation helper ---
def validate_record(r):
    """
    Reglas de validación más estrictas:
      - informant (nombre) presente y no parecer email ni gibberish
      - ubicació presente y no parecer email ni gibberish
      - descripción presente y no gibberish
      - timestamp parseado disponible
      - detectar valores repetidos (p. ej. poner el email en muchos campos)
    Devuelve (is_valid: bool, reasons: list[str])
    """
    reasons = []
    # basic presence checks
    if not (r.get("informant") and r["informant"].strip()):
        reasons.append("sin informant")
    if not (r.get("ubicacio") and r["ubicacio"].strip()):
        reasons.append("sin ubicació")
    if not (r.get("desc") and r["desc"].strip()):
        reasons.append("sin descripció")
    if not r.get("ts_parsed"):
        reasons.append("timestamp no parseado")

    # content heuristics
    email_val = (r.get("email") or "").strip()
    fields_to_check = {
        "informant": (r.get("informant") or "").strip(),
        "ubicacio": (r.get("ubicacio") or "").strip(),
        "desc": (r.get("desc") or "").strip(),
    }

    # If informant/ubicacio/desc contain what looks like an email -> suspicious
    for fname, val in fields_to_check.items():
        if val and looks_like_email(val):
            reasons.append(f"{fname} parece un email")
    # detect gibberish tokens
    for fname, val in fields_to_check.items():
        if val and is_gibberish(val):
            reasons.append(f"{fname} gibberish")
    # detect if the same non-empty value appears in many fields (spammy input)
    all_vals = [v for v in [email_val, fields_to_check["informant"], fields_to_check["ubicacio"], fields_to_check["desc"], r.get("tipus_equip") or ""] if v]
    counts = Counter(all_vals)
    for val, cnt in counts.items():
        if cnt >= 3:
            # if repeated 3+ veces, mark as suspicious (e.g., email used everywhere)
            sample = val if len(val) <= 40 else val[:37] + "..."
            reasons.append(f"valor repetido en campos ({sample}) x{cnt}")
            break

    # specific: if email exists and many fields equal that email -> bad
    if email_val:
        same_as_email = sum(1 for v in all_vals if v == email_val)
        if same_as_email >= 3:
            reasons.append("email repetido en varios campos")

    # unique rule: if description is extremely short and looks like noise
    desc = (r.get("desc") or "").strip()
    if desc and len(desc) < 10 and is_gibberish(desc):
        reasons.append("descripción demasiado corta y no significativa")

    return (len(reasons) == 0, reasons)

def color_for_priority(p):
    p_low = p.lower()
    if "alta" in p_low or "high" in p_low:
        return Fore.RED + Style.BRIGHT
    if "media" in p_low or "med" in p_low:
        return Fore.YELLOW + Style.BRIGHT
    if "baixa" in p_low or "low" in p_low:
        return Fore.GREEN + Style.BRIGHT
    return Fore.CYAN

def shorten(s, width=140):
    return textwrap.shorten(s or "", width=width, placeholder="…")

def process(file_path, json_path=None):
    try:
        tree = ET.parse(file_path)
    except Exception as e:
        print(Fore.RED + "Error leyendo XML:" + str(e))
        sys.exit(1)
    root = tree.getroot()
    incidencias = []
    for inc in root.findall("Incidencia"):
        record = {
            "timestamp_raw": get_text(inc, TAG_TIMESTAMP),
            "date": get_text(inc, TAG_DATE),
            "time": get_text(inc, TAG_TIME),
            "email": get_text(inc, TAG_EMAIL),
            "informant": get_text(inc, TAG_INFORMANT),
            "ubicacio": get_text(inc, TAG_LOCATION),
            "tipus_equip": get_text(inc, TAG_TYPE),
            "model": get_text(inc, "Model_de_equip"),
            "codi": get_text(inc, "Codi_d_ordinador__SACE_"),
            "desc": get_text(inc, TAG_DESC),
            "prioritat": get_text(inc, TAG_PRIORITY),
            "funciona": get_text(inc, TAG_FUNCIONA),
        }
        record["ts_parsed"] = try_parse_timestamp(record["timestamp_raw"], record["date"], record["time"])
        # --- NEW: validate and store results ---
        is_valid, reasons = validate_record(record)
        record["is_valid"] = is_valid
        record["invalid_reasons"] = reasons
        incidencias.append(record)

    total = len(incidencias)
    by_priority = Counter((r["prioritat"] or "Desconegut").strip() for r in incidencias)
    by_type = Counter((r["tipus_equip"] or "Desconegut").strip() for r in incidencias)
    by_location = Counter((r["ubicacio"] or "Desconegut").strip() for r in incidencias)
    funciona_counter = Counter((r["funciona"] or "Desconegut").strip() for r in incidencias)

    # Sort by parsed timestamp (fallback to unspecified)
    sorted_incs = sorted(incidencias, key=lambda r: r["ts_parsed"] or datetime.min, reverse=True)

    # Output summary
    print(Style.BRIGHT + Fore.MAGENTA + "\nResumen de Incidencias".center(80, " "))
    print(Style.RESET_ALL)
    print(f"Archivo: {file_path}")
    print(f"Total incidencias: {Fore.CYAN}{total}{Style.RESET_ALL}")
    print()

    # Priorities
    print(Style.BRIGHT + "Incidencias por prioridad:" + Style.RESET_ALL)
    for p, c in by_priority.most_common():
        color = color_for_priority(p)
        print(f"  {color}{p:12}{Style.RESET_ALL}  {c}")
    print()

    # Equipo
    print(Style.BRIGHT + "Incidencias por tipo de equipo (top 10):" + Style.RESET_ALL)
    for tipo, c in by_type.most_common(10):
        print(f"  {Fore.BLUE}{tipo[:30]:30}{Style.RESET_ALL}  {c}")
    print()

    # Ubicaciones top
    print(Style.BRIGHT + "Ubicaciones más frecuentes (top 10):" + Style.RESET_ALL)
    for loc, c in by_location.most_common(10):
        print(f"  {Fore.WHITE}{loc[:40]:40}{Style.RESET_ALL}  {c}")
    print()

    # Funcionamiento
    print(Style.BRIGHT + "Estado de funcionamiento:" + Style.RESET_ALL)
    for k, v in funciona_counter.items():
        k_display = k or "Desconegut"
        col = Fore.GREEN if "Si" in k or "si" in k else (Fore.RED if "No" in k or "no" in k else Fore.CYAN)
        print(f"  {col}{k_display:12}{Style.RESET_ALL}  {v}")
    print()

    # --- NEW: validation summary (correctos / erroneos) ---
    valid_count = sum(1 for r in incidencias if r.get("is_valid"))
    invalid_count = total - valid_count
    print(Style.BRIGHT + "Validación de datos:" + Style.RESET_ALL)
    print(f"  {Fore.GREEN}Correctos: {valid_count}{Style.RESET_ALL}  {Fore.RED}Erróneos: {invalid_count}{Style.RESET_ALL}")
    # show top reasons for invalid records (aggregate)
    invalid_reasons = Counter(reason for r in incidencias for reason in r.get("invalid_reasons", []))
    if invalid_reasons:
        print("  Motivos más comunes de error:")
        for reason, cnt in invalid_reasons.most_common(5):
            print(f"    - {reason}: {cnt}")
    print()

    # Show recent incidents (top 10)
    print(Style.BRIGHT + "Últimas incidencias (detallado, top 10):" + Style.RESET_ALL)
    for r in sorted_incs[:10]:
        pri = r["prioritat"] or "Desconegut"
        color = color_for_priority(pri)
        ts = r["ts_parsed"].strftime("%Y-%m-%d %H:%M:%S") if r["ts_parsed"] else (r["date"] + " " + r["time"] if r["date"] else r["timestamp_raw"] or "N/A")
        valid_mark = Fore.GREEN + "✔" + Style.RESET_ALL if r.get("is_valid") else Fore.RED + "✖" + Style.RESET_ALL
        print(color + f"\n[{pri.upper():6}] {ts} {valid_mark}" + Style.RESET_ALL)
        print(f"  Informant: {Fore.CYAN}{shorten(r['informant'], 80)}{Style.RESET_ALL}  Email: {r['email'] or 'N/A'}")
        print(f"  Ubicació: {Fore.WHITE}{shorten(r['ubicacio'], 60)}{Style.RESET_ALL}  Tipus: {shorten(r['tipus_equip'],30)}")
        print(f"  Model / Codi: {shorten(r['model'],30)} / {shorten(r['codi'],30)}")
        print("  Descripció:")
        print("   " + textwrap.fill(shorten(r['desc'], 400), width=76, initial_indent="   ", subsequent_indent="   "))
        if not r.get("is_valid"):
            print(f"  {Fore.RED}  Razones: {', '.join(r.get('invalid_reasons', []))}{Style.RESET_ALL}")
    print()

    # Extras: mostrar un pequeño checklist de acciones sugeridas
    high_count = sum(c for p, c in by_priority.items() if "alta" in p.lower() or "high" in p.lower())
    print(Style.BRIGHT + "Sugerencias rápidas:" + Style.RESET_ALL)
    print(f"  - Incidencias alta: {Fore.RED}{high_count}{Style.RESET_ALL} -> priorizar revisión hardware/seguridad.")
    print(f"  - Top ubicaciones a revisar: {', '.join([loc for loc, _ in by_location.most_common(3)])}")
    print()

    # --- JSON export ---
    if json_path is not None:
        try:
            out = {
                "meta": {
                    "source_file": str(file_path),
                    "total": total,
                    "generated_at": datetime.now().isoformat()
                },
                "summary": {
                    "by_priority": dict(by_priority),
                    "by_type": dict(by_type),
                    "by_location": dict(by_location),
                    "funciona": dict(funciona_counter),
                    # --- NEW: validation counts ---
                    "validation": {
                        "valid": valid_count,
                        "invalid": invalid_count,
                        "invalid_reasons": dict(invalid_reasons.most_common())
                    }
                },
                "incidencias": []
            }
            for idx, r in enumerate(incidencias):
                out["incidencias"].append({
                    "id": idx,
                    "timestamp_raw": r["timestamp_raw"],
                    "timestamp_iso": r["ts_parsed"].isoformat() if r["ts_parsed"] else None,
                    "date": r["date"],
                    "time": r["time"],
                    "email": r["email"],
                    "informant": r["informant"],
                    "ubicacio": r["ubicacio"],
                    "tipus_equip": r["tipus_equip"],
                    "model": r["model"],
                    "codi": r["codi"],
                    "desc": r["desc"],
                    "prioritat": r["prioritat"],
                    "funciona": r["funciona"],
                    "is_valid": r.get("is_valid", False),
                    "invalid_reasons": r.get("invalid_reasons", [])
                })
            # Ensure parent directory exists
            p = Path(json_path)
            if not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=2)
            print(Fore.GREEN + f"JSON escrito en: {str(p)}" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"Error escribiendo JSON: {e}" + Style.RESET_ALL)

def main():
    # Resolve script directory so the program can be executed from any cwd
    script_dir = Path(__file__).resolve().parent
    default_xml = script_dir / "Incidencies.xml"

    parser = argparse.ArgumentParser(description="Procesa un XML de incidencias y muestra estadísticas coloreadas.")
    parser.add_argument("--file", "-f", default=str(default_xml),
                        help="Ruta al fichero XML de incidencias (si no existe, se buscará en el directorio del script)")
    parser.add_argument("--json", "-j", dest="json_out", default=None,
                        help="(opcional) Ruta de salida para exportar JSON con los datos procesados (por defecto se crea junto al XML)")
    args = parser.parse_args()

    # Resolve the XML path: prefer the provided path, but if it doesn't exist try script dir
    xml_path = Path(args.file)
    if not xml_path.exists():
        alt = script_dir / args.file
        if alt.exists():
            xml_path = alt
        else:
            # If default (script_dir/Incidencies.xml) doesn't exist, keep xml_path as-is so process() will error clearly
            pass

    # Inform which XML file will be used
    try:
        print(Fore.CYAN + f"Usando archivo XML: {str(xml_path)}" + Style.RESET_ALL)
    except Exception:
        pass

    # Determine JSON output next to the chosen XML if not provided
    json_out = args.json_out
    if not json_out and xml_path:
        try:
            json_out = str(Path(xml_path).with_suffix('.json'))
        except Exception:
            json_out = None

    process(str(xml_path), json_path=json_out)

if __name__ == "__main__":
    main()
