#!/bin/sh
# The plugin's two usage-count hooks: telemetry.sh command|state, with the hook's JSON on stdin.
# It starts Python only when the plugin is in use here: a plugin command was typed, or the folder holds files the plugin
# wrote under analysis/. A person who merely has the plugin installed never runs anything, and a Mac without developer
# tools never sees the "install command line tools" dialog that a bare python3 would raise.
# What is counted, and how to turn it off: see the Telemetry section of the README and scripts/telemetry.py.
mode="$1"
input=$(cat)
case "$mode" in
  command) printf '%s' "$input" | grep -Eq '"prompt"[[:space:]]*:[[:space:]]*"[[:space:]]*/(code-modernization:)?modernize' || exit 0 ;;
  state)
    found=
    for f in analysis/*/INTENT.md analysis/*/PREFLIGHT.md analysis/*/MODERNIZATION_BRIEF.md analysis/*/BUSINESS_RULES.md \
             analysis/*/DELTA_CATALOG.md analysis/*/VERIFICATION.json analysis/*/RULE_REVIEWS.json analysis/*/AI_NATIVE_SPEC.md; do
      [ -f "$f" ] && found=1 && break
    done
    [ -n "$found" ] || exit 0 ;;
  *) exit 0 ;;
esac
py=$(command -v python3) || exit 0
if [ "$py" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ]; then
  xcode-select -p >/dev/null 2>&1 || exit 0
fi
# never leave bytecode behind in the plugin's own folder
printf '%s' "$input" | PYTHONDONTWRITEBYTECODE=1 "$py" "$(dirname "$0")/telemetry.py" "$mode"
exit 0
