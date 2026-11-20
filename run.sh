#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if (($# != 2)); then
  echo "Usage: bash run.sh ENV PIPELINE (example: bash run.sh my_experiment analyze)" >&2
  exit 2
fi
env_name=$1
pipeline=$2
mkdir -p data/01_raw/movie data/01_raw/metadata_csv data/02_intermediate/openface_temporary data/02_intermediate/openface_result

if [[ "$pipeline" == "analyze" ]]; then
  docker compose run --rm kedro run --env="$env_name" --pipeline=select_movie
  # Use Kedro's Python so neither the host nor the OpenFace image needs a JSON tool.
  movie_name=$(docker compose run --rm -T --entrypoint python kedro \
    /scripts/read_movie_list.py /app/data/02_intermediate/movie_list.json)
  docker compose run --rm openface "$movie_name" "${OPENFACE_AU_MODEL:-static}"
  docker compose run --rm kedro run --env="$env_name" --pipeline=analyze
  exit 0
fi

# Keep the existing batch workflow for metadata-based analysis pipelines.
docker compose run --rm openface
shopt -s nullglob
csv=(data/02_intermediate/openface_temporary/*.csv)
if (("${#csv[@]}")); then
  docker compose run --rm kedro run --env="$env_name" --pipeline=external_csv
else
  echo "No new OpenFace CSV files to import."
fi
docker compose run --rm kedro run --env="$env_name" --pipeline="$pipeline"
