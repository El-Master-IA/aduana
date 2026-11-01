#!/usr/bin/env python3
"""aduana-gate.py — PreToolUse (Bash y PowerShell). Bloquea instalaciones de terceros
en ~/.claude que no pasaron por la skill `aduana`.

Exit 2 = BLOQUEAR (el mensaje de stderr le llega a Claude) | Exit 0 = PERMITIR
Se deja pasar el segmento que *ejecuta* `aduana.py` (`python aduana.py ...`) y todo el
comando si lleva el prefijo ADUANA_OK=1, que Claude solo pone después de un PASS o de un
WARN aprobado por la persona. Mencionar `aduana.py` en otro lugar no cuenta.

Cada regla mira solo el inicio de cada comando (separado por ; && || | o salto de línea),
y antes se quitan los cuerpos de heredoc: así un mensaje de commit o un README que
*mencionan* un comando no lo disparan.
"""
import json
import re
import sys

try:
    datos = json.load(sys.stdin)
    cmd = (datos.get("tool_input") or {}).get("command") or ""
except (ValueError, AttributeError):
    sys.exit(0)

if not cmd or re.search(r"\bADUANA_OK=1\b", cmd):
    sys.exit(0)


SHELL = r"\b(bash|sh|zsh|dash|ksh|pwsh|powershell)(\.exe)?\b"


def sin_heredocs(texto: str) -> str:
    """Quita el cuerpo de los heredocs y here-strings que son texto (un mensaje, un archivo).
    Si el heredoc alimenta a una shell (`bash <<EOF`, `cat <<EOF | sh`, `@'...'@ | iex`),
    su cuerpo se deja: ahí sí son comandos."""
    if not re.search(r"\b(iex|Invoke-Expression)\b", texto, re.I):
        texto = re.sub(r"@'.*?'@|@\".*?\"@", "", texto, flags=re.S)
    salida, cierre, guardar = [], None, False
    for linea in texto.splitlines():
        if cierre is not None:
            if linea.strip() == cierre:
                cierre = None
            elif guardar:
                salida.append(linea)
            continue
        salida.append(linea)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", linea)
        if m:
            cierre, guardar = m.group(1), bool(re.search(SHELL, linea, re.I))
    return "\n".join(salida)


def con_shells_anidadas(texto: str) -> str:
    """Agrega como líneas aparte lo que va dentro de `bash -c "..."` o `pwsh -Command '...'`."""
    extra = [m.group(4) for m in re.finditer(
        SHELL + r"[^'\"\n]*?\s-(?:c|Command)\s+(['\"])(.*?)\3", texto, re.I | re.S)]
    return "\n".join([texto, *extra])


def segmentos(texto: str):
    for parte in re.split(r"\|\||&&|[;|&\n]", texto):
        parte = parte.strip().lstrip("({ ").strip()
        # Quita asignaciones de variables al inicio (VAR=x cmd)
        parte = re.sub(r"^(?:\w+=\S*\s+)+", "", parte)
        if parte:
            yield parte


def sin_envoltorio(seg: str) -> str:
    """Si el comando va detrás de un envoltorio (privilegios, env, nohup, xargs…), lo saca:
    salta la primera palabra, sus opciones y asignaciones VAR=x."""
    t = seg.split()
    i = 1
    while i < len(t) and (t[i].startswith("-") or re.match(r"^\w+=", t[i])):
        i += 1
    return " ".join(t[i:])


ENVOLTORIOS = {"sudo", "env", "nohup", "command", "exec", "time", "nice"}


def ejecuta_aduana(seg: str) -> bool:
    """True si el segmento ejecuta aduana.py: `python [opciones] ruta/aduana.py ...` o la ruta directa.
    Solo se admiten envoltorios conocidos y opciones de python sin valor; un segmento con
    sustituciones (`$(...)`, comillas invertidas, `<(...)`) nunca se salta."""
    if re.search(r"\$\(|`|[<>]\(", seg):
        return False
    t = partes(seg)
    if t[0].lower() in ENVOLTORIOS:
        t = partes(sin_envoltorio(seg)) or t
    prog = re.sub(r"\.exe$", "", t[0].replace("\\", "/").rsplit("/", 1)[-1].lower())
    if prog == "aduana.py":
        return True
    if not re.match(r"^(python[\d.]*|py)$", prog):
        return False
    for x in t[1:]:
        if x in ("-I", "-E", "-s", "-S", "-B", "-u", "-O", "-OO", "-q"):
            continue
        return not x.startswith("-") and x.replace("\\", "/").rsplit("/", 1)[-1] == "aduana.py"
    return False


DESTINO = re.compile(r"\.claude[/\\]+(skills|agents|plugins)\b", re.I)
COPIAR = {"cp", "mv", "rsync", "robocopy", "xcopy", "copy", "move", "copy-item", "move-item",
          "expand-archive", "unzip", "tar"}
# Opción que nombra el destino, por comando (el resto usa el último argumento)
OPCION_DESTINO = {"copy-item": "-destination", "move-item": "-destination",
                  "expand-archive": "-destinationpath", "unzip": "-d", "tar": "-c", "cp": "-t", "mv": "-t"}
REGLAS = [
    (r"^npx\s+(-y\s+)?skills?\s+add\b", "instalar skills con npx"),
    (r"^claude\s+plugins?\s+(install|marketplace\s+add)\b", "instalar un plugin o marketplace"),
    (r"^(?:\w+\s+)?npm\s+(i|install|add)\b.*\s(-g|--global)\b", "instalar un paquete npm global"),
]


def partes(seg: str) -> list:
    return [t.strip("'\"") for t in seg.split()]


def destino(t: list):
    """Devuelve la ruta destino de un comando de copia o de git clone (None si no hay)."""
    prog = t[0].lower()
    if prog == "git":
        con_valor = {"--depth", "-b", "--branch", "-o", "--origin", "--reference", "-c", "--config",
                     "--filter", "--separate-git-dir", "-j", "--jobs", "-u", "--upload-pack"}
        pos, saltar = [], False
        for x in t[2:]:
            if saltar:
                saltar = False
            elif x.startswith("-"):
                saltar = x in con_valor
            else:
                pos.append(x)
        return pos[1] if len(pos) > 1 else ""   # "" = clona en la carpeta actual
    opcion = OPCION_DESTINO.get(prog)
    for i, x in enumerate(t[1:-1], 1):
        if opcion and x.lower() == opcion:
            return t[i + 1]
        if x.lower().startswith(("--target-directory=", "--directory=")):
            return x.split("=", 1)[1]
    if prog == "robocopy":
        return t[2] if len(t) > 2 else None
    if prog in ("unzip", "tar", "expand-archive"):
        return ""                                # sin opción: descomprime en la carpeta actual
    pos = [x for x in t[1:] if not x.startswith("-")]
    return pos[-1] if len(pos) > 1 else None


def motivo(seg: str, dentro: bool):
    for regla, que in REGLAS:
        if re.search(regla, seg, re.I):
            return que
    t = partes(seg)
    es_clone = len(t) > 1 and t[0].lower() == "git" and t[1].lower() == "clone"
    if es_clone or t[0].lower() in COPIAR:
        d = destino(t)
        # Destino dentro de ~/.claude, o relativo después de un cd hacia allá
        if d is not None and (DESTINO.search(d) or (dentro and not re.match(r"^([a-z]:|[/\\~$])", d, re.I))):
            return "clonar un repo dentro de ~/.claude" if es_clone else "copiar o descomprimir algo dentro de ~/.claude"
    return None


dentro = False
for seg in segmentos(con_shells_anidadas(sin_heredocs(cmd))):
    t = partes(seg)
    if t[0].lower() in ("cd", "pushd", "set-location", "sl"):
        dentro = len(t) > 1 and bool(DESTINO.search(t[-1]))
        continue
    if ejecuta_aduana(seg):
        continue
    interior = sin_envoltorio(seg)
    que = motivo(seg, dentro) or (interior and motivo(interior, dentro))
    if que:
            sys.stderr.write(
                f"BLOQUEADO por la Aduana: intento de {que} sin revisión.\n"
                "Usa la skill `aduana`: trae el origen a ~/.claude/aduana/cuarentena, escanéalo con "
                "`aduana.py escanear <ruta|url>` e instálalo con `aduana.py promover`. Para npm/plugins "
                "aprobados, repite el comando con el prefijo ADUANA_OK=1 SOLO después de un PASS o de un "
                "WARN que la persona aprobó.\n")
            sys.exit(2)

sys.exit(0)
