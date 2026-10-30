"""Envuelve el texto de stdin como lo recibe un hook PreToolUse: {"tool_input": {"command": ...}}."""
import json
import sys

print(json.dumps({"tool_input": {"command": sys.stdin.read()}}))
