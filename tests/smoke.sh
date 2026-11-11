#!/usr/bin/env bash
set -euo pipefail

MG5="${MG5:-$HOME/softwares/MG5_aMC_v3_8_1}"
PYTHON="${PYTHON:-$HOME/miniconda3/envs/py310/bin/python}"
LOG="$(mktemp)"
OUT="$(mktemp)"
PDF="$(mktemp --suffix=.pdf)"
WORKDIR="$(mktemp -d)"
trap 'rm -f "$LOG" "$OUT" "$PDF"; rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

cat > "$LOG" <<EOF
import model sm
generate p p > w+ w- b b~
check double_counting { p p > t t~, t > b w+, t~ > b~ w- } --show=chain --save=$PDF
exit
EOF

if ! "$PYTHON" "$MG5/bin/mg5_aMC" --mode=double_counting "$LOG" > "$OUT" 2>&1; then
    cat "$OUT"
    exit 1
fi

grep -q '7 diagram(s) appear in more than one set' "$OUT"
grep -q 'u u~ > t t~ > w+ w- b b~' "$OUT"
test -s "$PDF"
head -c 4 "$PDF" | grep -q '%PDF'

echo "plugin smoke test passed"
