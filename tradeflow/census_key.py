#!/usr/bin/env python3
"""
Shared CENSUS_API_KEY lookup, used by bea/census_api_client.py. Mirrors
bea_key.py's resolution order exactly (see that file for the reasoning
behind each step) -- Census's own API/Census_API.yml in USEPA/USEEIO says
`api_key_required: False`, but that's out of date: as of 2026-09-24 the
Census international trade API redirects keyless requests to
https://api.census.gov/data/missing_key.html (confirmed by a real request,
not documentation) -- a key is required now. Register at
https://api.census.gov/data/key_signup.html.
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def _resolve_env_file_from_paths_yaml(paths_yaml_path):
    """Read the last `env_file:` line from paths.yaml and resolve it
    relative to paths.yaml's own directory."""
    env_line = None
    for line in paths_yaml_path.read_text().splitlines():
        line = line.strip()
        if line.lower().startswith('env_file:'):
            env_line = line
    if env_line is None:
        return None
    value = env_line.split(':', 1)[1].strip().strip('"')
    if not value:
        return None
    return (paths_yaml_path.parent / value).resolve()


def _try_load_local_cloud_repo_env(start_dir):
    """Same lookup as bea_key.py's helper of the same name -- see there for
    the full explanation. Duplicated rather than imported so this file has
    no dependency on bea_key.py staying import-compatible."""
    current = Path(start_dir).resolve()
    for _ in range(4):
        parent = current.parent
        if parent == current:
            break
        try:
            siblings = [d for d in parent.iterdir() if d.is_dir()]
        except OSError:
            break
        for sibling in siblings:
            if sibling == current:
                continue
            if not sibling.name.lower().startswith('cloud'):
                continue
            paths_yaml = sibling / 'automation' / 'paths.yaml'
            if not paths_yaml.exists():
                continue
            env_file = _resolve_env_file_from_paths_yaml(paths_yaml)
            if env_file and env_file.exists():
                load_dotenv(env_file)
                return True
        current = parent
    return False


def find_census_api_key(provided_key=None, start_dir=None):
    """
    Resolve CENSUS_API_KEY from, in order: a provided value, a local
    cloud-repo .env, webroot/automation/paths.yaml's env_file: target,
    webroot/docker/.env, webroot/.env, then the system environment. Returns
    the key string, or None if not found anywhere.
    """
    if provided_key:
        return provided_key

    start_dir = Path(start_dir) if start_dir else Path(__file__).parent

    if _try_load_local_cloud_repo_env(start_dir):
        env_key = os.getenv('CENSUS_API_KEY')
        if env_key:
            print("Loaded Census API key from local environment")
            return env_key

    # Callers pass start_dir=<tradeflow dir> (see census_api_client.py),
    # matching bea_key.py's own convention: tradeflow -> exiobase -> webroot.
    webroot = start_dir.resolve().parents[1]

    paths_yaml = webroot / 'automation' / 'paths.yaml'
    if paths_yaml.exists():
        env_file = _resolve_env_file_from_paths_yaml(paths_yaml)
        if env_file and env_file.exists():
            load_dotenv(env_file)
            env_key = os.getenv('CENSUS_API_KEY')
            if env_key:
                print(f"Loaded Census API key from {env_file} (via automation/paths.yaml)")
                return env_key

    search_paths = [
        webroot / 'docker' / '.env',
        webroot / '.env',
    ]
    for env_path in search_paths:
        if env_path.exists():
            load_dotenv(env_path)
            env_key = os.getenv('CENSUS_API_KEY')
            if env_key:
                print(f"Loaded Census API key from {env_path}")
                return env_key

    env_key = os.getenv('CENSUS_API_KEY')
    if env_key:
        print("Loaded Census API key from system environment")
        return env_key

    return None
