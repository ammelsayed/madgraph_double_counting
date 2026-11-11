#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ammelsayed/madgraph_double_counting}"
BRANCH="${BRANCH:-main}"
MG5="${MG5AMC_HOME:-$HOME/softwares/MG5_aMC_v3_8_1}"
FROM_LOCAL=0

usage() {
    cat <<EOF
Usage: ./install.sh [--mg5 PATH] [--from-local] [--branch NAME] [--repo URL]

Installs the double_counting plugin into MG5aMC's PLUGIN directory.

  --mg5 PATH       MG5aMC installation (default: \$MG5AMC_HOME or
                   \$HOME/softwares/MG5_aMC_v3_8_1)
  --from-local     install the copy next to this script instead of downloading
  --branch NAME    git branch to download (default: main)
  --repo URL       repository URL (default: $REPO_URL)
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --mg5) MG5="$2"; shift 2 ;;
        --from-local) FROM_LOCAL=1; shift ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --repo) REPO_URL="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

if [ ! -x "$MG5/bin/mg5_aMC" ] || [ ! -d "$MG5/PLUGIN" ]; then
    echo "Not an MG5aMC installation: $MG5" >&2
    exit 1
fi

TMPDIR=""
cleanup() {
    if [ -n "$TMPDIR" ]; then
        rm -rf "$TMPDIR"
    fi
}
trap cleanup EXIT

if [ "$FROM_LOCAL" -eq 1 ]; then
    SRC="$(cd "$(dirname "$0")" && pwd)"
else
    TMPDIR="$(mktemp -d)"
    ARCHIVE="$TMPDIR/plugin.tar.gz"
    echo "Downloading $REPO_URL ($BRANCH)"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$REPO_URL/archive/refs/heads/$BRANCH.tar.gz" -o "$ARCHIVE"
    else
        wget -q "$REPO_URL/archive/refs/heads/$BRANCH.tar.gz" -O "$ARCHIVE"
    fi
    tar -xzf "$ARCHIVE" -C "$TMPDIR"
    SRC="$(find "$TMPDIR" -maxdepth 2 -type d -name double_counting -printf '%h\n' | head -1)"
fi

if [ ! -f "$SRC/double_counting/__init__.py" ]; then
    echo "double_counting plugin not found under $SRC" >&2
    exit 1
fi

rm -rf "$MG5/PLUGIN/double_counting"
cp -R "$SRC/double_counting" "$MG5/PLUGIN/double_counting"

cat > "$MG5/bin/mg5_aMC_double_counting" <<EOF
#!/usr/bin/env bash
exec "$MG5/bin/mg5_aMC" --mode=double_counting "\$@"
EOF
chmod +x "$MG5/bin/mg5_aMC_double_counting"

echo "Installed double_counting in $MG5/PLUGIN/double_counting"
echo
echo "Run:"
echo "  $MG5/bin/mg5_aMC --mode=double_counting"
echo "or:"
echo "  $MG5/bin/mg5_aMC_double_counting"
