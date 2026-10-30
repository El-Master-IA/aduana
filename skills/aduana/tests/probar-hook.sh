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
t 2 'git -C ~/.claude/skills clone https://x/y' "git -C hacia skills y clone"
t 2 'curl -o ~/.claude/skills/x/SKILL.md https://x/y' "curl -o"
t 2 'curl --output ~/.claude/skills/x/SKILL.md https://x/y' "curl --output"
t 2 'wget -O ~/.claude/agents/x.md https://x/y' "wget -O"
t 2 'wget -P ~/.claude/skills https://x/y' "wget -P"
t 2 'iwr https://x/y -OutFile C:\Users\a\.claude\skills\x.md' "iwr -OutFile"
t 2 'Invoke-WebRequest https://x/y -OutFile ~/.claude/plugins/x.md' "Invoke-WebRequest -OutFile"
t 2 'echo hola > ~/.claude/skills/x/SKILL.md' "redireccion >"
t 2 'echo hola >> ~/.claude/skills/x/SKILL.md' "redireccion >>"
t 2 'cat a | tee ~/.claude/agents/x.md' "tee"
t 2 'ln -s /tmp/x ~/.claude/skills/x' "ln -s"
t 2 'New-Item -ItemType SymbolicLink -Path C:\Users\a\.claude\skills\x -Target D:\x' "New-Item SymbolicLink"
t 2 'cd ~/.claude/skills && curl -o x.md https://x/y' "cd hacia skills y curl -o relativo"
t 2 'curl -fsSLo ~/.claude/skills/x.md https://x/y' "curl con banderas combinadas"
t 2 'wget -qO ~/.claude/skills/x.md https://x/y' "wget -qO"
t 2 'curl -O --output-dir ~/.claude/skills https://x/y' "curl --output-dir"
t 2 'curl.exe -o ~/.claude/skills/x.md https://x/y' "curl.exe"
t 2 'git.exe -C ~/.claude/skills clone https://x/y' "git.exe -C"
t 2 'echo x >| ~/.claude/skills/x/SKILL.md' "redireccion >|"
t 2 'echo x &> ~/.claude/skills/x/SKILL.md' "redireccion &>"
t 2 "echo it's > ~/.claude/skills/x/SKILL.md" "redireccion con apostrofe suelto"
t 2 'cd ~/.claude/skills && echo x > SKILL.md' "cd hacia skills y redireccion relativa"
t 2 'ni -ItemType SymbolicLink -Path C:\Users\a\.claude\skills\x -Target D:\x' "ni SymbolicLink"

# Debe dejar pasar
t 0 'wget -O- https://x/y | head' "wget a stdout"
t 0 'New-Item -ItemType SymbolicLink -Path C:\tmp\y -Target C:\Users\a\.claude\skills\x' "enlace fuera apuntando a skills"
t 0 'curl -o ./x.md https://x/y' "curl a una carpeta local"
t 0 'cat ~/.claude/skills/x/SKILL.md > ./copia.md' "leer skills y redirigir afuera"
t 0 'echo hola > nota.txt' "redireccion local"
t 0 'echo "a > ~/.claude/skills/x" && ls 2>&1' "> dentro de comillas y 2>&1"
t 0 'ADUANA_OK=1 wget -O ~/.claude/skills/x.md https://x/y' "wget aprobado con ADUANA_OK=1"
t 0 'git -C ~/proyecto status' "git -C a otra carpeta"
t 0 'cp ~/.claude/skills/x/f .' "cp desde skills a la carpeta actual"
t 0 'ln -s ~/.claude/skills/x ./enlace' "ln desde skills hacia afuera"
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
