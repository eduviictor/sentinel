#!/bin/sh
set -u
input=$(cat)
case $input in
    *'"stop_hook_active":true'* | *'"stop_hook_active": true'*) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -n "$(git status --porcelain -- '*.py' pyproject.toml 2>/dev/null)" ] || exit 0

if ! output=$(make fast 2>&1); then
    printf 'make fast failed, fix before stopping:\n%s\n' "$(printf '%s\n' "$output" | tail -n 25)" >&2
    exit 2
fi
