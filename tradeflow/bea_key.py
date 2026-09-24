#!/usr/bin/env python3
"""
Shared BEA_API_KEY lookup, used by both bea/main.py (to actually call the
BEA API) and main.py (to fail fast, before a long trade-data run, when
--interstate is requested even though main.py itself never uses the key).
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
    """
    Look for a repo folder near `start_dir` whose name starts with "cloud"
    and that has an automation/paths.yaml file — the same file that repo's
    own automation reads to find its env file — and, if found, load
    whatever env file it points to. Never logs the resolved path or its
    contents. Returns True if an env file was loaded, False if no such
    repo/file is present (e.g. in Docker or CI).
    """
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


def find_bea_api_key(provided_key=None, start_dir=None):
    """
    Resolve BEA_API_KEY from, in order: a provided value, a local cloud-repo
    .env, webroot/automation/paths.yaml's env_file: target, webroot/docker/.env,
    webroot/.env, then the system environment. Loads any discovered .env file
    into os.environ so a later subprocess (e.g. bea/main.py, invoked from
    main.py) inherits the key without re-searching. Returns the key string,
    or None if not found anywhere.
    """
    if provided_key:
        return provided_key

    start_dir = Path(start_dir) if start_dir else Path(__file__).parent

    if _try_load_local_cloud_repo_env(start_dir):
        env_key = os.getenv('BEA_API_KEY')
        if env_key:
            print("Loaded BEA API key from local environment")
            return env_key

    # tradeflow -> exiobase -> webroot
    webroot = start_dir.resolve().parents[1]

    # webroot/automation/paths.yaml's env_file: key is the current canonical
    # location (same resolution as chat/ingestion/test_vectordb_sync.py's
    # resolve_env_path() and chat/lib/env-loader.ts) -- the .env holding
    # secrets like BEA_API_KEY now lives outside webroot (e.g. a sibling
    # safe/ folder), not in docker/.env, which is checked below only as a
    # deprecated fallback for checkouts that haven't migrated yet.
    paths_yaml = webroot / 'automation' / 'paths.yaml'
    if paths_yaml.exists():
        env_file = _resolve_env_file_from_paths_yaml(paths_yaml)
        if env_file and env_file.exists():
            load_dotenv(env_file)
            env_key = os.getenv('BEA_API_KEY')
            if env_key:
                print(f"Loaded BEA API key from {env_file} (via automation/paths.yaml)")
                return env_key

    search_paths = [
        webroot / 'docker' / '.env',  # deprecated location, kept as a fallback
        webroot / '.env',
    ]
    for env_path in search_paths:
        if env_path.exists():
            load_dotenv(env_path)
            env_key = os.getenv('BEA_API_KEY')
            if env_key:
                print(f"Loaded BEA API key from {env_path}")
                return env_key

    env_key = os.getenv('BEA_API_KEY')
    if env_key:
        print("Loaded BEA API key from system environment")
        return env_key

    return None
