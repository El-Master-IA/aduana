#!/usr/bin/env python3
"""
aduana.py — Puerta de entrada para skills, agentes, plugins y repos de terceros.

No trae patrones propios: combina tres revisiones que ya existen y lleva el registro.
  1. skill-security-auditor (análisis estático de la skill, instalado en ~/.claude/skills)
  2. Windows Defender en modo solo-reporte (MpCmdRun -DisableRemediation), si está disponible
  3. Metadatos: `risk: offensive` en el frontmatter y la marca `alerta` de un fuentes.json opcional (--fuentes)

Uso:
    python aduana.py escanear <ruta|url-git> [--json] [--sin-defender] [--fuentes F]
    python aduana.py barrer <carpeta> [--salida informe.md] [--json-salida x.json] [--sin-defender]
    python aduana.py promover <ruta> [--destino skills|agents] [--confirmo]
    python aduana.py verificar <ruta>
    python aduana.py cuarentenar <ruta>

Salida de escanear/verificar: 0 = PASS, 1 = WARN, 2 = FAIL, 3 = error.
Nunca ejecuta el código que revisa.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
ADUANA_DIR = CLAUDE_DIR / "aduana"
CUARENTENA = ADUANA_DIR / "cuarentena"
REGISTRO = ADUANA_DIR / "registro.json"
EXIT = {"PASS": 0, "WARN": 1, "FAIL": 2}
ORDEN = {"PASS": 0, "WARN": 1, "FAIL": 2}
SALTAR = {".git", "node_modules", "__pycache__"}

AQUI = Path(__file__).resolve().parent
AUDITOR_CANDIDATOS = [
    os.environ.get("ADUANA_AUDITOR", ""),
    str(CLAUDE_DIR / "skills/skill-security-auditor/scripts/skill_security_auditor.py"),
    str(AQUI.parent.parent / "skill-security-auditor/scripts/skill_security_auditor.py"),
]
DEFENDER_CANDIDATOS = [r"C:\Program Files\Windows Defender\MpCmdRun.exe"]


def ahora():
    return dt.datetime.now().isoformat(timespec="seconds")


def peor(*veredictos):
    return max(veredictos, key=lambda v: ORDEN[v])


# --- Huella del árbol ---------------------------------------------------------

def huella(ruta: Path) -> str:
    h = hashlib.sha256()
    archivos = [ruta] if ruta.is_file() else sorted(
        p for p in ruta.rglob("*")
        if p.is_file() and not (set(p.relative_to(ruta).parts) & SALTAR))
    for p in archivos:
        rel = p.name if ruta.is_file() else p.relative_to(ruta).as_posix()
        h.update(rel.encode("utf-8", "replace") + b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<ilegible>")
        h.update(b"\0")
    return h.hexdigest()


def leer_registro() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_registro(reg: dict):
    ADUANA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRO)


# --- Revisiones ---------------------------------------------------------------

def revisar_auditor(ruta: Path) -> dict:
    auditor = next((c for c in AUDITOR_CANDIDATOS if c and Path(c).is_file()), None)
    if not auditor:
        return {"veredicto": "WARN", "error": "skill-security-auditor no está instalado", "hallazgos": []}
    def correr(objetivo) -> dict:
        r = subprocess.run([sys.executable, "-I", auditor, str(objetivo), "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        return json.loads(r.stdout)

    try:
        if ruta.is_file():
            # El auditor solo acepta carpetas: un agente suelto (.md) se revisa como si fuera SKILL.md.
            with tempfile.TemporaryDirectory(prefix="aduana-") as tmp:
                shutil.copy2(ruta, Path(tmp) / "SKILL.md")
                datos = correr(tmp)
            for f in datos.get("findings", []):
                f["file"] = str(ruta)
        else:
            datos = correr(ruta)
    except (subprocess.TimeoutExpired, ValueError) as e:
        return {"veredicto": "WARN", "error": f"el auditor no respondió bien: {e}", "hallazgos": []}
    v = datos.get("verdict", "WARN")
    hallazgos = [
        {"severidad": f.get("severity"), "categoria": f.get("category"),
         "archivo": f.get("file"), "linea": f.get("line"), "riesgo": f.get("risk")}
        for f in datos.get("findings", [])
    ]
    return {"veredicto": v if v in ORDEN else "WARN", "resumen": datos.get("summary", {}),
            "hallazgos": hallazgos}


def revisar_defender(ruta: Path) -> dict:
    exe = next((c for c in DEFENDER_CANDIDATOS if Path(c).is_file()), None)
    if not exe:
        return {"veredicto": "PASS", "omitido": "Defender no disponible en este sistema"}
    try:
        r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", str(ruta), "-DisableRemediation"],
                           capture_output=True, text=True, errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return {"veredicto": "WARN", "error": "Defender tardó más de 15 minutos"}
    salida = (r.stdout or "") + (r.stderr or "")
    amenazas = re.findall(r"Threat\s*:\s*(.+)", salida)
    if r.returncode == 2 or amenazas or "LIST OF DETECTED THREATS" in salida:
        return {"veredicto": "FAIL", "amenazas": amenazas or ["(ver salida de Defender)"]}
    return {"veredicto": "PASS"}


def leer_frontmatter(ruta: Path) -> str:
    skill = ruta / "SKILL.md" if ruta.is_dir() else ruta
    try:
        texto = skill.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"\ufeff?---\s*\n(.*?)\n---", texto, re.S)
    return m.group(1) if m else ""


def revisar_metadatos(ruta: Path, fuentes: Path | None) -> dict:
    notas = []
    fm = leer_frontmatter(ruta)
    if re.search(r"^risk:\s*['\"]?offensive", fm, re.M | re.I):
        notas.append("Declara risk: offensive (material de ataque o pentest)")
    if fuentes and fuentes.is_file():
        try:
            meta = json.loads(fuentes.read_text(encoding="utf-8"))
            nombre = ruta.stem if ruta.is_file() else ruta.name
            for tipo in ("skills", "agents"):
                info = meta.get(tipo, {}).get(nombre)
                if info and info.get("alerta"):
                    notas.append(f"Marcada con alerta en fuentes.json (repo {info.get('repo')})")
        except ValueError:
            pass
    return {"veredicto": "WARN" if notas else "PASS", "notas": notas}


def escanear(ruta: Path, defender=True, fuentes=None, registrar=True) -> dict:
    ruta = ruta.resolve()
    aud = revisar_auditor(ruta)
    dfn = revisar_defender(ruta) if defender else {"veredicto": "PASS", "omitido": "--sin-defender"}
    met = revisar_metadatos(ruta, fuentes)
    v = peor(aud["veredicto"], dfn["veredicto"], met["veredicto"])
    rep = {"ruta": str(ruta), "nombre": ruta.stem if ruta.is_file() else ruta.name,
           "veredicto": v, "huella": huella(ruta), "fecha": ahora(),
           "auditor": aud, "defender": dfn, "metadatos": met}
    if registrar:
        reg = leer_registro()
        reg[str(ruta)] = {k: rep[k] for k in ("nombre", "veredicto", "huella", "fecha")}
        guardar_registro(reg)
    return rep


# --- Comandos -----------------------------------------------------------------

def traer(origen: str) -> Path:
    """Si es una URL git, la clona en cuarentena (sin submódulos ni LFS). Si es ruta, la devuelve."""
    if re.match(r"^(https?://|git@)", origen):
        nombre = re.sub(r"\.git$", "", origen.rstrip("/").split("/")[-1])
        destino = CUARENTENA / nombre
        if destino.exists():
            raise SystemExit(f"Ya existe {destino}. Bórralo o revísalo antes de volver a clonar.")
        CUARENTENA.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")
        subprocess.run(["git", "clone", "--depth", "1", "--no-recurse-submodules", origen, str(destino)],
                       check=True, env=env)
        return destino
    p = Path(origen).expanduser()
    if not p.exists():
        raise SystemExit(f"No existe: {p}")
    return p


def resumen_texto(rep: dict) -> str:
    l = [f"[{rep['veredicto']}] {rep['nombre']}  ({rep['ruta']})"]
    a = rep["auditor"]
    if a.get("error"):
        l.append(f"  auditor: {a['error']}")
    graves = [h for h in a.get("hallazgos", []) if h["severidad"] in ("CRITICAL", "HIGH")]
    for h in graves[:8]:
        archivo = os.path.relpath(h["archivo"], rep["ruta"]) if h.get("archivo") else "?"
        l.append(f"  auditor {h['severidad']}: {h['categoria']} en {archivo}:{h['linea']} — {h['riesgo']}")
    if len(graves) > 8:
        l.append(f"  … y {len(graves) - 8} hallazgos graves más (ver --json)")
    d = rep["defender"]
    if d.get("amenazas"):
        l.append(f"  Defender: {', '.join(d['amenazas'])}")
    elif d.get("omitido") or d.get("error"):
        l.append(f"  Defender: {d.get('omitido') or d.get('error')}")
    for n in rep["metadatos"]["notas"]:
        l.append(f"  metadatos: {n}")
    return "\n".join(l)


def cmd_escanear(a):
    ruta = traer(a.origen)
    rep = escanear(ruta, defender=not a.sin_defender, fuentes=Path(a.fuentes) if a.fuentes else None)
    print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else resumen_texto(rep))
    return EXIT[rep["veredicto"]]


def cmd_barrer(a):
    base = Path(a.carpeta).expanduser().resolve()
    items = sorted(p for p in base.iterdir()
                   if (p.is_dir() and p.name not in SALTAR | {"aduana"}) or p.suffix == ".md")
    fuentes = Path(a.fuentes) if a.fuentes else None
    reps = []
    for i, p in enumerate(items, 1):
        reps.append(escanear(p, defender=False, fuentes=fuentes))
        if i % 100 == 0:
            print(f"  {i}/{len(items)}…", file=sys.stderr)
    dfn = revisar_defender(base) if not a.sin_defender else {"veredicto": "PASS", "omitido": "--sin-defender"}
    cuenta = {v: sum(r["veredicto"] == v for r in reps) for v in ORDEN}
    if a.json_salida:
        Path(a.json_salida).write_text(json.dumps({"carpeta": str(base), "fecha": ahora(), "defender": dfn,
                                                   "cuenta": cuenta, "items": reps}, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    if a.salida:
        out = [f"# Barrido de la Aduana — {base}", "", f"Fecha: {ahora()} · Total: {len(reps)} · "
               f"PASS {cuenta['PASS']} · WARN {cuenta['WARN']} · FAIL {cuenta['FAIL']}", "",
               f"Defender sobre la carpeta completa: {dfn.get('amenazas') or dfn.get('omitido') or dfn['veredicto']}", ""]
        for v in ("FAIL", "WARN"):
            out += [f"## {v}", ""]
            for r in (r for r in reps if r["veredicto"] == v):
                out += ["```", resumen_texto(r), "```", ""]
        Path(a.salida).write_text("\n".join(out), encoding="utf-8")
    print(f"Total {len(reps)} · PASS {cuenta['PASS']} · WARN {cuenta['WARN']} · FAIL {cuenta['FAIL']}"
          f" · Defender: {dfn.get('amenazas') or dfn.get('omitido') or dfn['veredicto']}")
    return 0


def cmd_verificar(a):
    ruta = Path(a.ruta).expanduser().resolve()
    entrada = leer_registro().get(str(ruta))
    if not entrada:
        print(f"Sin revisar: {ruta}. Corre primero: aduana.py escanear {ruta}")
        return 3
    if entrada["huella"] != huella(ruta):
        print(f"Cambió desde la revisión del {entrada['fecha']}. Vuelve a escanear.")
        return 3
    print(f"{entrada['veredicto']} (revisado {entrada['fecha']})")
    return EXIT[entrada["veredicto"]]


def cmd_promover(a):
    ruta = Path(a.ruta).expanduser().resolve()
    rc = cmd_verificar(a)
    if rc == 3:
        return 3
    if rc == EXIT["FAIL"]:
        print("FAIL: no se instala.")
        return 2
    if rc == EXIT["WARN"] and not a.confirmo:
        print("WARN: revisa los hallazgos con la persona y repite con --confirmo si lo aprueba.")
        return 1
    destino_dir = CLAUDE_DIR / a.destino
    destino = destino_dir / ruta.name
    if destino.exists():
        print(f"Ya existe {destino}. No se sobrescribe.")
        return 3
    destino_dir.mkdir(parents=True, exist_ok=True)
    (shutil.copytree(ruta, destino, ignore=shutil.ignore_patterns(".git"))
     if ruta.is_dir() else shutil.copy2(ruta, destino))
    reg = leer_registro()
    reg[str(destino.resolve())] = dict(reg[str(ruta)], huella=huella(destino), promovido_desde=str(ruta))
    guardar_registro(reg)
    print(f"Instalado en {destino}")
    return 0


def cmd_cuarentenar(a):
    ruta = Path(a.ruta).expanduser().resolve()
    CUARENTENA.mkdir(parents=True, exist_ok=True)
    destino = CUARENTENA / ruta.name
    n = 2
    while destino.exists():
        destino = CUARENTENA / f"{ruta.name}-{n}"
        n += 1
    shutil.move(str(ruta), str(destino))
    (destino.parent / f"{destino.name}.origen.txt").write_text(f"{ruta}\n{ahora()}\n", encoding="utf-8")
    print(f"Movido a cuarentena: {destino}")
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Aduana de skills, agentes y repos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("escanear"); s.add_argument("origen"); s.add_argument("--json", action="store_true")
    s.add_argument("--sin-defender", action="store_true"); s.add_argument("--fuentes")
    s.set_defaults(f=cmd_escanear)
    s = sub.add_parser("barrer"); s.add_argument("carpeta"); s.add_argument("--salida")
    s.add_argument("--json-salida"); s.add_argument("--sin-defender", action="store_true"); s.add_argument("--fuentes")
    s.set_defaults(f=cmd_barrer)
    s = sub.add_parser("verificar"); s.add_argument("ruta"); s.set_defaults(f=cmd_verificar)
    s = sub.add_parser("promover"); s.add_argument("ruta"); s.add_argument("--destino", default="skills",
                                                                           choices=["skills", "agents"])
    s.add_argument("--confirmo", action="store_true"); s.set_defaults(f=cmd_promover)
    s = sub.add_parser("cuarentenar"); s.add_argument("ruta"); s.set_defaults(f=cmd_cuarentenar)
    a = ap.parse_args()
    try:
        sys.exit(a.f(a))
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
