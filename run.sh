#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if (($# != 2)); then
  echo "Usage: bash run.sh ENV PIPELINE (example: bash run.sh my_experiment ext_v4)" >&2
  exit 2
fi
env_name=$1
pipeline=$2
mkdir -p data/01_raw/movie data/01_raw/metadata_csv data/02_intermediate/openface_temporary data/02_intermediate/openface_result
docker compose run --rm openface
shopt -s nullglob
csv=(data/02_intermediate/openface_temporary/*.csv)
if ((${#csv[@]})); then
  docker compose run --rm kedro run --env="$env_name" --pipeline=external_csv
else
  echo "No new OpenFace CSV files to import."
fi
docker compose run --rm kedro run --env="$env_name" --pipeline="$pipeline"
