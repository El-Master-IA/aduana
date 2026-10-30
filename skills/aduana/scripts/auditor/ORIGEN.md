# Origen

`skill_security_auditor.py` es una copia de
[skill-security-auditor](https://github.com/alirezarezvani/claude-skills/tree/main/engineering/skills/skill-security-auditor),
de Alireza Rezvani, con licencia MIT (ver `LICENSE`). Sin cambios.

Es la versión revisada el 24 de septiembre de 2026. Las posteriores permiten ignorar una línea con
`noqa: SEC-AUDITOR` o `auditor:ignore-line`, y una skill maliciosa podría usarlo para esconderse.

`aduana.py` verifica la huella SHA-256 de este archivo antes de cada escaneo. Si cambia, no lo usa.
