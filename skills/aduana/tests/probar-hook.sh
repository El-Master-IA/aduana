#!/bin/bash
# Prueba el hook aduana-gate con comandos que debe bloquear (2) y dejar pasar (0).
#   bash skills/aduana/tests/probar-hook.sh   → sale 0 si todo cuadra
set -u
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H="$AQUI/../../../hooks/aduana-gate.py"
PY=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)
FALLAS=0

t() { # t <codigo-esperado> <comando> <descripcion>
  printf '%s' "$2" | "$PY" -c 'import json,sys;print(json.dumps({"tool_input":{"command":sys.stdin.read()}}))' \
    | "$PY" -I "$H" 2>/dev/null
  local rc=$?
  if [ "$rc" = "$1" ]; then echo "ok   $3"; else echo "MAL  $3 (salió $rc, se esperaba $1)"; FALLAS=$((FALLAS+1)); fi
}

# Debe bloquear
t 2 'git clone https://x/y ~/.claude/skills/y' "clone hacia skills"
t 2 'git clone --depth 1 https://x/y C:\Users\a\.claude\agents\y' "clone con opciones (Windows)"
t 2 'cd ~/.claude/skills && git clone https://x/y' "cd hacia skills y clone"
t 2 'cd /tmp && cp -r foo ~/.claude/skills/' "cp encadenado"
t 2 'Copy-Item -Path a -Destination C:\Users\x\.claude\agents\b' "Copy-Item"
t 2 'unzip x.zip -d ~/.claude/plugins/x' "unzip"
t 2 'npx -y skills add x/y' "npx skills add"
t 2 'claude plugin install foo' "claude plugin install"
t 2 'FOO=1 npm i -g bar' "npm global"
t 2 'nohup cp -r x ~/.claude/skills/' "cp con envoltorio"
t 2 'env A=1 git clone https://x/y ~/.claude/skills/y' "env + clone"
t 2 'ls | xargs -I{} cp {} ~/.claude/skills/' "xargs cp"
t 2 'bash -c "cd /tmp; cp x ~/.claude/skills/x"' "bash -c"
t 2 "pwsh -NoProfile -Command 'Copy-Item a C:\\x\\.claude\\skills\\b'" "pwsh -Command"
t 2 $'bash <<\'EOF\'\ncp x ~/.claude/skills/x\nEOF' "heredoc a bash"
t 2 $'cat <<EOF | sh\nnpx skills add x\nEOF' "heredoc a sh"
t 2 'cp x ~/.claude/skills/x & echo hi' "en segundo plano"
t 2 'echo aduana.py; git clone https://x/y ~/.claude/skills/y' "aduana.py solo mencionado"
t 2 'python aduana.py escanear x && git clone https://x/y ~/.claude/skills/y' "aduana.py mezclado con clone"
t 2 'cat aduana.py | tee x; cp a ~/.claude/skills/a' "aduana.py como argumento de otro comando"
t 2 'cp -r python aduana.py ~/.claude/skills/' "aduana.py como origen de cp"
t 2 'python -W aduana.py evil.py && cp a ~/.claude/skills/a' "opcion -W con valor"

# Debe dejar pasar
t 0 'python3 -I aduana.py x' "python -I aduana.py"
t 0 'python3 -I ~/.claude/plugins/aduana/skills/aduana/scripts/aduana.py promover ~/.claude/aduana/cuarentena/x' "ejecutar aduana.py"
t 0 'py aduana.py escanear x' "py aduana.py"
t 0 'cp ~/.claude/skills/x/ref.png . && ls' "copiar desde skills hacia afuera"
t 0 'git clone https://x/y D:/tmp/y' "clone a otra carpeta"
t 0 'cd ~/.claude/skills && ls' "leer skills"
t 0 'git commit -m "bloquea npx skills add y claude plugin install"' "mensaje de commit"
t 0 $'git commit -F - <<\'EOF\'\nnpx skills add x\ncp a ~/.claude/skills/b\nEOF' "heredoc de texto"
t 0 $'cat > nota.md <<\'EOF\'\ngit clone u ~/.claude/skills/y\nEOF' "heredoc a un archivo"
t 0 'npm i react' "npm local"
t 0 'echo "usa npx skills add"' "echo"
t 0 'ADUANA_OK=1 npm i -g vercel' "aprobado con ADUANA_OK=1"

echo "Fallas: $FALLAS"
exit $FALLAS
