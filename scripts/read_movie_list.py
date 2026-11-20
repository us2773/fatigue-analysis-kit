"""Read the single movie stem selected by Kedro."""
import json
import sys
from pathlib import Path


def read_movie_name(filepath: str) -> str:
    with Path(filepath).open(encoding="utf-8") as stream:
        movies = json.load(stream)
    if not isinstance(movies, list) or len(movies) != 1:
        raise ValueError("movie_list must contain exactly one movie name.")
    name = movies[0]
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or any(char in name for char in "/\\\r\n\0")
    ):
        raise ValueError("movie_list must contain a filename stem, without a path.")
    return name


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: read_movie_list.py MOVIE_LIST_JSON")
    try:
        print(read_movie_name(sys.argv[1]))
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
