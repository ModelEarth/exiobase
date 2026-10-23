#!/usr/bin/env python3
"""
Shared API key lookup for tradeflow, used by bea_key.py (BEA_API_KEY) and
census_key.py (CENSUS_API_KEY).

A key is looked up in, in order: a provided value, the env file a nearby
cloud repo's automation/paths.yaml points at, the env file
webroot/automation/paths.yaml points at (its env_file: line, relative to the
automation folder), webroot/.env, then the system environment. Any env file
found is loaded into os.environ, so a later subprocess (e.g. bea/main.py,
invoked from main.py) inherits the key without searching again. The env
file's location and the key's value are never printed.
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
    whatever env file it points to. Returns True if an env file was loaded,
    False if no such repo/file is present (e.g. in Docker or CI).
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


def find_env_key(name, label, provided_key=None, start_dir=None):
    """
    Resolve the environment variable `name` (e.g. 'BEA_API_KEY') as described
    above. `label` names it in the log line (e.g. 'BEA API key'). `start_dir`
    is the tradeflow folder (its default); webroot is two folders up.
    Returns the key string, or None if not found anywhere.
    """
    if provided_key:
        return provided_key

    start_dir = Path(start_dir) if start_dir else Path(__file__).parent

    if _try_load_local_cloud_repo_env(start_dir):
        env_key = os.getenv(name)
        if env_key:
            print(f"Loaded {label} from local environment")
            return env_key

    # tradeflow -> exiobase -> webroot
    webroot = start_dir.resolve().parents[1]

    # webroot/automation/paths.yaml's env_file: key is the canonical location
    # (same resolution as chat/ingestion/test_vectordb_sync.py's
    # resolve_env_path() and chat/lib/env-loader.ts); the env file lives
    # outside webroot.
    paths_yaml = webroot / 'automation' / 'paths.yaml'
    if paths_yaml.exists():
        env_file = _resolve_env_file_from_paths_yaml(paths_yaml)
        if env_file and env_file.exists():
            load_dotenv(env_file)
            env_key = os.getenv(name)
            if env_key:
                print(f"Loaded {label} from the env file set in automation/paths.yaml")
                return env_key

    env_path = webroot / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        env_key = os.getenv(name)
        if env_key:
            print(f"Loaded {label} from webroot env file")
            return env_key

    env_key = os.getenv(name)
    if env_key:
        print(f"Loaded {label} from system environment")
        return env_key

    return None
