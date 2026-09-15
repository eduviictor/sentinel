#!/bin/sh
set -eu
export LC_ALL=C

cd "$(dirname "$0")/.."

if [ $# -ne 1 ]; then
    echo "usage: scripts/init.sh <name>   e.g. scripts/init.sh net-monitor" >&2
    exit 2
fi

name=$1
package=$(printf '%s' "$name" | tr '-' '_')

case $name in
    "" | *[!a-z0-9-]* | [!a-z]* | *- | *--*)
        echo "invalid name '$name': lowercase letters, digits and single hyphens, starting with a letter" >&2
        exit 1
        ;;
esac

shadows=$(python3 -c 'import sys; print(sys.argv[1] in sys.stdlib_module_names)' "$package")
if [ "$shadows" = True ]; then
    echo "invalid name '$name': package '$package' would shadow a standard library module" >&2
    exit 1
fi

if [ ! -d src/skeleton ]; then
    echo "src/skeleton not found: this checkout was already initialised" >&2
    exit 1
fi

if ! git ls-files --error-unmatch src/skeleton/__init__.py >/dev/null 2>&1; then
    echo "src/skeleton is not tracked by git: run this in a git clone of the template" >&2
    exit 1
fi

sed -i "s/^name = \"skeleton\"$/name = \"$name\"/" pyproject.toml
git ls-files -z -- . ':!scripts/init.sh' | xargs -0 grep -lZ skeleton | xargs -0 -r sed -i "s/skeleton/$package/g"
mv src/skeleton "src/$package"
printf '# %s\n' "$name" > README.md
rm -rf docs/superpowers tests/test_init.py uv.lock scripts/init.sh
rmdir scripts 2>/dev/null || true

echo "initialised as $name. next: make install && make check, then commit"
