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
import subprocess  # <-- added

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

    # Show recent incidents (top 10)
    print(Style.BRIGHT + "Últimas incidencias (detallado, top 10):" + Style.RESET_ALL)
    for r in sorted_incs[:10]:
        pri = r["prioritat"] or "Desconegut"
        color = color_for_priority(pri)
        ts = r["ts_parsed"].strftime("%Y-%m-%d %H:%M:%S") if r["ts_parsed"] else (r["date"] + " " + r["time"] if r["date"] else r["timestamp_raw"] or "N/A")
        print(color + f"\n[{pri.upper():6}] {ts}" + Style.RESET_ALL)
        print(f"  Informant: {Fore.CYAN}{shorten(r['informant'], 80)}{Style.RESET_ALL}  Email: {r['email'] or 'N/A'}")
        print(f"  Ubicació: {Fore.WHITE}{shorten(r['ubicacio'], 60)}{Style.RESET_ALL}  Tipus: {shorten(r['tipus_equip'],30)}")
        print(f"  Model / Codi: {shorten(r['model'],30)} / {shorten(r['codi'],30)}")
        print("  Descripció:")
        print("   " + textwrap.fill(shorten(r['desc'], 400), width=76, initial_indent="   ", subsequent_indent="   "))
    print()

    # Extras: mostrar un pequeño checklist de acciones sugeridas
    high_count = sum(c for p, c in by_priority.items() if "alta" in p.lower() or "high" in p.lower())
    print(Style.BRIGHT + "Sugerencias rápidas:" + Style.RESET_ALL)
    print(f"  - Incidencias alta: {Fore.RED}{high_count}{Style.RESET_ALL} -> priorizar revisión hardware/seguridad.")
    print(f"  - Top ubicaciones a revisar: {', '.join([loc for loc, _ in by_location.most_common(3)])}")
    print()

    # Prepare JSON payload if requested
    json_written = None
    if json_path:
        def serialize_record(r):
            return {
                "timestamp_raw": r.get("timestamp_raw"),
                "ts_iso": (r["ts_parsed"].isoformat() if r["ts_parsed"] else None),
                "date": r.get("date"),
                "time": r.get("time"),
                "informant": r.get("informant"),
                "email": r.get("email"),
                "ubicacio": r.get("ubicacio"),
                "tipus_equip": r.get("tipus_equip"),
                "model": r.get("model"),
                "codi": r.get("codi"),
                "desc": r.get("desc"),
                "prioritat": r.get("prioritat"),
                "funciona": r.get("funciona"),
            }

        payload = {
            "meta": {
                "source_file": str(Path(file_path).resolve()),
                "total": total,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "by_priority": dict(by_priority),
                "by_type": dict(by_type),
                "by_location": dict(by_location),
                "funciona": dict(funciona_counter),
            },
            "recent": [serialize_record(r) for r in sorted_incs[:10]],
            "incidencias": [serialize_record(r) for r in incidencias],
        }

        try:
            p = Path(json_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            print(Fore.GREEN + f"JSON exportado a: {p}" + Style.RESET_ALL)
            json_written = str(p.resolve())
        except Exception as e:
            print(Fore.RED + "Error escribiendo JSON: " + str(e) + Style.RESET_ALL)

    return json_written

# new helper to add/commit/push the generated JSON
def git_push(json_path, remote="origin", branch="main", commit_msg=None):
    if commit_msg is None:
        commit_msg = f"Add/update incidencias JSON: {Path(json_path).name}"
    json_p = Path(json_path).resolve()
    if not json_p.exists():
        print(Fore.RED + f"File not found for git push: {json_p}" + Style.RESET_ALL)
        return False
    repo_cwd = json_p.parent
    # try to find git top-level directory
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo_cwd, capture_output=True, text=True, check=True)
        repo_root = Path(proc.stdout.strip())
    except Exception as e:
        print(Fore.RED + "Git repo not found (run inside a git repo) or git not installed: " + str(e) + Style.RESET_ALL)
        return False

    # make path relative to repo root if possible
    try:
        rel_path = str(json_p.relative_to(repo_root))
    except Exception:
        rel_path = str(json_p)  # fallback to absolute

    try:
        subprocess.run(["git", "add", rel_path], cwd=repo_root, check=True)
    except subprocess.CalledProcessError as e:
        print(Fore.RED + "git add failed: " + str(e) + Style.RESET_ALL)
        return False

    # commit (may return non-zero if nothing to commit)
    commit_proc = subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_root, capture_output=True, text=True)
    if commit_proc.returncode != 0:
        # no commit created (possibly no changes)
        stdout = commit_proc.stdout + commit_proc.stderr
        if "nothing to commit" in stdout.lower() or "no changes added to commit" in stdout.lower():
            print(Fore.YELLOW + "No changes to commit." + Style.RESET_ALL)
        else:
            print(Fore.RED + "git commit failed: " + stdout + Style.RESET_ALL)
            return False

    # push
    try:
        subprocess.run(["git", "push", remote, branch], cwd=repo_root, check=True)
        print(Fore.GREEN + f"Pushed {rel_path} to {remote}/{branch}" + Style.RESET_ALL)
        return True
    except subprocess.CalledProcessError as e:
        print(Fore.RED + "git push failed: " + str(e) + Style.RESET_ALL)
        return False

def main():
    parser = argparse.ArgumentParser(description="Procesa un XML de incidencias y muestra estadísticas coloreadas.")
    parser.add_argument("--file", "-f", default="/home/cristian.ojeda.7e7/PycharmProjects/incidencias/Incidencies.xml",
                        help="Ruta al fichero XML de incidencias")
    parser.add_argument("--json", "-j", dest="json_out", default=None,
                        help="(opcional) Ruta de salida para exportar JSON con los datos procesados (por defecto se crea junto al XML)")
    # new git options
    parser.add_argument("--push", action="store_true", help="Si se usa, hace git add/commit/push del JSON generado (debe estar dentro de un repo git).")
    parser.add_argument("--git-remote", dest="git_remote", default="origin", help="Remote git (default: origin)")
    parser.add_argument("--git-branch", dest="git_branch", default="main", help="Branch a pushear (default: main)")
    parser.add_argument("--commit-msg", dest="commit_msg", default=None, help="Mensaje de commit para el JSON")

    args = parser.parse_args()

    # Si no se indica --json, crear JSON junto al fichero XML (misma base, extensión .json)
    json_out = args.json_out
    if not json_out:
        try:
            xml_path = Path(args.file)
            json_out = str(xml_path.with_suffix('.json'))
        except Exception:
            json_out = None

    json_written = process(args.file, json_path=json_out)

    if args.push:
        if not json_written:
            print(Fore.RED + "No JSON file was written; skipping git push." + Style.RESET_ALL)
            sys.exit(1)

if __name__ == "__main__":
    main()