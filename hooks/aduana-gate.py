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


def sin_heredocs(texto: str) -> str:
    """Quita el cuerpo de los heredocs (<<EOF ... EOF) y de los here-strings de PowerShell."""
    texto = re.sub(r"@'.*?'@|@\".*?\"@", "", texto, flags=re.S)
    salida, cierre = [], None
    for linea in texto.splitlines():
        if cierre is not None:
            if linea.strip() == cierre:
                cierre = None
            continue
        salida.append(linea)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", linea)
        if m:
            cierre = m.group(1)
    return "\n".join(salida)


def segmentos(texto: str):
    for parte in re.split(r"\|\||&&|[;|\n]", texto):
        parte = parte.strip().lstrip("({ ").strip()
        # Quita asignaciones de variables al inicio (VAR=x cmd)
        parte = re.sub(r"^(?:\w+=\S*\s+)+", "", parte)
        if parte:
            yield parte


DESTINO = r"\.claude[/\\]+(skills|agents|plugins)\b"
REGLAS = [
    (rf"^git\s+clone\b.*{DESTINO}", "clonar un repo dentro de ~/.claude"),
    (rf"^(cp|mv|rsync|robocopy|xcopy|copy|move|Copy-Item|Move-Item|Expand-Archive|unzip|tar)\b.*{DESTINO}",
     "copiar o descomprimir algo dentro de ~/.claude"),
    (r"^npx\s+(-y\s+)?skills?\s+add\b", "instalar skills con npx"),
    (r"^claude\s+plugins?\s+(install|marketplace\s+add)\b", "instalar un plugin o marketplace"),
    (r"^(?:\w+\s+)?npm\s+(i|install|add)\b.*\s(-g|--global)\b", "instalar un paquete npm global"),
]

for seg in segmentos(sin_heredocs(cmd)):
    for regla, que in REGLAS:
        if re.search(regla, seg, re.I):
            sys.stderr.write(
                f"BLOQUEADO por la Aduana: intento de {que} sin revisión.\n"
                "Usa la skill `aduana`: trae el origen a ~/.claude/aduana/cuarentena, escanéalo con "
                "`aduana.py escanear <ruta|url>` e instálalo con `aduana.py promover`. Para npm/plugins "
                "aprobados, repite el comando con el prefijo ADUANA_OK=1 SOLO después de un PASS o de un "
                "WARN que la persona aprobó.\n")
            sys.exit(2)

sys.exit(0)
