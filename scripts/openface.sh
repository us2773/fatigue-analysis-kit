#!/usr/bin/env bash
set -euo pipefail

input=/data/01_raw/movie
temporary=/data/02_intermediate/openface_temporary
results=/data/02_intermediate/openface_result
mkdir -p "$input" "$temporary" "$results"
shopt -s nullglob
movies=("$input"/*.mp4)
if ((${#movies[@]} == 0)); then
  echo "No .mp4 videos found in $input" >&2
  exit 1
fi
for movie in "${movies[@]}"; do
  name=${movie##*/}
  name=${name%.mp4}
  if [[ -f "$results/$name.parquet" ]]; then
    echo "Already imported: $name"
    continue
  fi
  # Use an isolated output directory so a failed run cannot be mistaken for a CSV.
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  /home/openface-build/build/bin/FeatureExtraction -f "$movie" -out_dir "$work" -aus -au_static
  test -s "$work/$name.csv" || { echo "OpenFace CSV missing: $name" >&2; exit 1; }
  cp "$work/$name.csv" "$temporary/$name.csv"
  rm -rf "$work"
  trap - EXIT
done
