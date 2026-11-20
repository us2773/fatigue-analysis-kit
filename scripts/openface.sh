#!/usr/bin/env bash
set -euo pipefail

data_dir=${OPENFACE_DATA_DIR:-/data}
input="$data_dir/01_raw/movie"
temporary="$data_dir/02_intermediate/openface_temporary"
results="$data_dir/02_intermediate/openface_result"
feature_extraction=${OPENFACE_BIN:-/home/openface-build/build/bin/FeatureExtraction}

if (($# > 2)); then
  echo "Usage: openface.sh [MOVIE_STEM [static|dynamic]]" >&2
  exit 2
fi
au_model=${2:-static}
case "$au_model" in
  static|dynamic) ;;
  *) echo "Unknown AU model: $au_model" >&2; exit 2 ;;
esac
mkdir -p "$input" "$temporary" "$results"

process_movie() (
  movie=$1
  name=${movie##*/}
  name=${name%.mp4}
  # Publish only a successful CSV; keep all auxiliary output isolated.
  work=$(mktemp -d "$temporary/.openface.XXXXXX")
  trap 'rm -rf -- "$work"' EXIT
  set -- -f "$movie" -out_dir "$work" -aus
  if [[ "$au_model" == "static" ]]; then
    set -- "$@" -au_static
  fi
  "$feature_extraction" "$@"
  test -s "$work/$name.csv" || { echo "OpenFace CSV missing: $name" >&2; exit 1; }
  mv -- "$work/$name.csv" "$temporary/$name.csv"
)

if (($#)); then
  # An explicit selection always processes exactly this movie, even on a retry.
  name=$1
  if [[ -z "$name" || "$name" == "." || "$name" == ".." || "$name" == *"/"* || "$name" == *"\\"* || "$name" == *$'\n'* || "$name" == *$'\r'* ]]; then
    echo "Expected a single movie filename stem, without a path." >&2
    exit 2
  fi
  movie="$input/$name.mp4"
  test -f "$movie" || { echo "Movie not found: $movie" >&2; exit 1; }
  process_movie "$movie"
  exit 0
fi

# No argument retains the original batch behavior.
shopt -s nullglob
movies=("$input"/*.mp4)
if (("${#movies[@]}" == 0)); then
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
  process_movie "$movie"
done
