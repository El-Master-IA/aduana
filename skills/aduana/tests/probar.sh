#!/bin/bash
# Prueba el flujo de la Aduana con skills de juguete, en un ~/.claude temporal.
#   bash skills/aduana/tests/probar.sh   → sale 0 si todo cuadra
set -u
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
A="$AQUI/../scripts/aduana.py"
TMP="$(mktemp -d)"
export CLAUDE_DIR="$TMP/claude"
export ADUANA_AUDITOR="$HOME/.claude/skills/skill-security-auditor/scripts/skill_security_auditor.py"
trap 'rm -rf "$TMP"' EXIT
FALLAS=0

espera() { # espera <codigo-esperado> <descripcion> <comando...>
  local esperado=$1 desc=$2; shift 2
  "$@" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$esperado" ]; then echo "ok   $desc"; else echo "MAL  $desc (salió $rc, se esperaba $esperado)"; FALLAS=$((FALLAS+1)); fi
}

mkdir -p "$TMP/limpia" "$TMP/ofensiva"
printf -- '---\nname: limpia\ndescription: Saluda.\n---\n\n# Limpia\n\nResponde con un saludo corto.\n' > "$TMP/limpia/SKILL.md"
printf -- '---\nname: ofensiva\ndescription: Guia de pentest.\nrisk: offensive\n---\n\n# Ofensiva\n\nMetodologia de pruebas autorizadas.\n' > "$TMP/ofensiva/SKILL.md"

espera 0 "skill limpia → PASS"                 "$PY" -I "$A" escanear "$TMP/limpia" --sin-defender
espera 1 "risk: offensive → WARN"              "$PY" -I "$A" escanear "$TMP/ofensiva" --sin-defender
espera 0 "verificar la limpia → PASS"          "$PY" -I "$A" verificar "$TMP/limpia"
espera 1 "promover WARN sin --confirmo → no"   "$PY" -I "$A" promover "$TMP/ofensiva"
espera 0 "promover PASS → instala"             "$PY" -I "$A" promover "$TMP/limpia"
[ -f "$CLAUDE_DIR/skills/limpia/SKILL.md" ] && echo "ok   quedó en skills/" || { echo "MAL  no se copió"; FALLAS=$((FALLAS+1)); }
echo "cambio" >> "$TMP/ofensiva/SKILL.md"
espera 3 "archivo cambiado tras escanear → re-escanear" "$PY" -I "$A" verificar "$TMP/ofensiva"
espera 0 "cuarentenar mueve la carpeta"        "$PY" -I "$A" cuarentenar "$TMP/ofensiva"
[ -d "$CLAUDE_DIR/aduana/cuarentena/ofensiva" ] && [ ! -e "$TMP/ofensiva" ] && echo "ok   está en cuarentena" \
  || { echo "MAL  cuarentena"; FALLAS=$((FALLAS+1)); }

echo "Fallas: $FALLAS"
exit $FALLAS
