#!/usr/bin/env python3
"""aduana-gate.py — PreToolUse (Bash y PowerShell). Bloquea instalaciones de terceros
en ~/.claude que no pasaron por la skill `aduana`.

Exit 2 = BLOQUEAR (el mensaje de stderr le llega a Claude) | Exit 0 = PERMITIR
Se deja pasar si el comando usa `aduana.py` o lleva el prefijo ADUANA_OK=1, que Claude
solo pone después de un PASS o de un WARN aprobado por la persona.

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

if not cmd or "aduana.py" in cmd or re.search(r"\bADUANA_OK=1\b", cmd):
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


DESTINO = re.compile(r"\.claude[/\\]+(skills|agents|plugins)\b", re.I)
COPIAR = {"cp", "mv", "rsync", "robocopy", "xcopy", "copy", "move", "copy-item", "move-item",
          "expand-archive", "unzip", "tar", "ln"}
# Opción que nombra el destino, por comando (el resto usa el último argumento)
OPCION_DESTINO = {"copy-item": "-destination", "move-item": "-destination",
                  "expand-archive": "-destinationpath", "unzip": "-d", "tar": "-c", "cp": "-t", "mv": "-t",
                  "ln": "-t"}
# Descargas: opciones largas y de PowerShell (sin distinguir mayúsculas) que nombran la salida
DESCARGAS = {"curl": {"--output", "--output-dir", "-outfile"}, "wget": {"--output-document", "--directory-prefix", "-outfile"},
             "invoke-webrequest": {"-outfile"}, "iwr": {"-outfile"},
             "invoke-restmethod": {"-outfile"}, "irm": {"-outfile"}}
# Letras de opción corta que llevan la salida (distinguen mayúsculas): curl -o, wget -O / -P
CORTAS_SALIDA = {"curl": "o", "wget": "OP"}
GIT_GLOBAL_CON_VALOR = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
REGLAS = [
    (r"^npx\s+(-y\s+)?skills?\s+add\b", "instalar skills con npx"),
    (r"^claude\s+plugins?\s+(install|marketplace\s+add)\b", "instalar un plugin o marketplace"),
    (r"^(?:\w+\s+)?npm\s+(i|install|add)\b.*\s(-g|--global)\b", "instalar un paquete npm global"),
]


def partes(seg: str) -> list:
    return [t.strip("'\"") for t in seg.split()]


def git_partes(t: list):
    """Separa `git [opciones globales] <subcomando> <resto>` → (subcomando, carpeta de -C, resto)."""
    cdir, i = "", 1
    while i < len(t) and t[i].startswith("-"):
        if t[i] == "-C" and i + 1 < len(t):
            cdir = t[i + 1]
        elif t[i].startswith("-C") and len(t[i]) > 2:
            cdir = t[i][2:]
        i += 2 if t[i] in GIT_GLOBAL_CON_VALOR else 1
    return (t[i].lower() if i < len(t) else ""), cdir, t[i + 1:]


def redirecciones(seg: str, comillas: bool = True) -> list:
    """Destinos de `>` y `>>` fuera de comillas. Si las comillas quedan sin cerrar (un apóstrofe
    suelto, una comilla escapada) se repite el análisis sin respetarlas."""
    salida, comilla, i = [], "", 0
    while i < len(seg):
        c = seg[i]
        if c == "\\" and i + 1 < len(seg) and seg[i + 1] in "'\"":
            i += 1
        elif comilla:
            comilla = "" if c == comilla else comilla
        elif comillas and c in "'\"":
            comilla = c
        elif c == ">":
            m = re.match(r"([|&>]?)\s*(\S+)", seg[i + 1:])
            if m and not (m.group(1) == "&" and re.fullmatch(r"\d+|-", m.group(2))) and m.group(2)[0] != "&":
                salida.append(m.group(2).strip("'\""))
            i += 0 if not m else len(m.group(0))
        i += 1
    if comilla and comillas:
        return redirecciones(seg, False)
    return salida


def descargas(t: list) -> list:
    """Destinos que escribe un curl/wget/Invoke-WebRequest ('' = carpeta actual, '-' = stdout)."""
    prog = t[0].lower()
    opciones, salida = DESCARGAS[prog], []
    cortas = CORTAS_SALIDA.get(prog, "")
    for i, x in enumerate(t[1:], 1):
        base, _, valor = x.partition("=")
        siguiente = t[i + 1] if i + 1 < len(t) else None
        if x.lower() in opciones and siguiente is not None:
            salida.append(siguiente)
        elif valor and base.lower() in opciones:
            salida.append(valor)
        elif cortas and re.match(r"^-[A-Za-z]+$", x) and x[-1] in cortas and siguiente is not None:
            salida.append(siguiente)            # -o ruta, -fsSLo ruta, -qO ruta
        elif cortas and re.match(r"^-[%s](.+)$" % cortas, x):
            salida.append(x[2:])                # -oruta, -Pruta
        elif prog == "curl" and x in ("-O", "--remote-name"):
            salida.append("")
    if prog == "wget" and not salida:
        salida.append("")
    return [d for d in salida if d != "-"]


def destino(t: list):
    """Devuelve la ruta destino de un comando de copia o de git clone (None si no hay)."""
    prog = t[0].lower()
    if prog == "git":
        con_valor = {"--depth", "-b", "--branch", "-o", "--origin", "--reference", "-c", "--config",
                     "--filter", "--separate-git-dir", "-j", "--jobs", "-u", "--upload-pack"}
        pos, saltar = [], False
        for x in git_partes(t)[2]:
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


def dentro_de(d: str, dentro: bool) -> bool:
    """Ruta dentro de ~/.claude/skills|agents|plugins, o relativa después de un cd hacia allá."""
    return bool(DESTINO.search(d)) or (dentro and not re.match(r"^([a-z]:|[/\\~$])", d, re.I))


def motivo(seg: str, dentro: bool):
    for regla, que in REGLAS:
        if re.search(regla, seg, re.I):
            return que
    for d in redirecciones(seg):
        if dentro_de(d, dentro):
            return "escribir un archivo dentro de ~/.claude con una redirección"
    t = partes(seg)
    t[0] = re.sub(r"\.exe$", "", t[0].replace("\\", "/").rsplit("/", 1)[-1], flags=re.I)
    prog = t[0].lower()
    if prog == "git":
        sub, cdir, _ = git_partes(t)
        if sub == "clone":
            d = destino(t)
            if DESTINO.search(d) or dentro_de(d, dentro or bool(DESTINO.search(cdir))):
                return "clonar un repo dentro de ~/.claude"
        return None
    if prog in DESCARGAS and any(dentro_de(d, dentro) for d in descargas(t)):
        return "descargar un archivo dentro de ~/.claude"
    if prog == "tee" and any(dentro_de(x, dentro) for x in t[1:] if not x.startswith("-")):
        return "escribir un archivo dentro de ~/.claude con tee"
    if prog in ("new-item", "ni") and re.search(r"symboliclink|junction", seg, re.I) and \
            DESTINO.search(re.sub(r"-target\s+\S+", "", seg, flags=re.I)):
        return "crear un enlace dentro de ~/.claude"
    if prog in COPIAR:
        d = destino(t)
        if d is not None and dentro_de(d, dentro):
            return "copiar, enlazar o descomprimir algo dentro de ~/.claude"
    return None


def bloquear(que: str):
    sys.stderr.write(
        f"BLOQUEADO por la Aduana: intento de {que} sin revisión.\n"
        "Usa la skill `aduana`: trae el origen a ~/.claude/aduana/cuarentena, escanéalo con "
        "`aduana.py escanear <ruta|url>` e instálalo con `aduana.py promover`. Para npm/plugins "
        "aprobados, repite el comando con el prefijo ADUANA_OK=1 SOLO después de un PASS o de un "
        "WARN que la persona aprobó.\n")
    sys.exit(2)


texto = con_shells_anidadas(sin_heredocs(cmd))
# Las redirecciones se leen del texto entero: `>|` y `>&` se partirían al separar segmentos
if any(DESTINO.search(d) for d in redirecciones(texto)):
    bloquear("escribir un archivo dentro de ~/.claude con una redirección")

dentro = False
for seg in segmentos(texto):
    t = partes(seg)
    if t[0].lower() in ("cd", "pushd", "set-location", "sl"):
        dentro = len(t) > 1 and bool(DESTINO.search(t[-1]))
        continue
    interior = sin_envoltorio(seg)
    que = motivo(seg, dentro) or (interior and motivo(interior, dentro))
    if que:
        bloquear(que)

sys.exit(0)
