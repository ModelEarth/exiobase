#!/usr/bin/env python3
"""
Configuration loader for Exiobase Trade Flow Analysis
"""

import os
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    env_prefix = ' '.join(f'{k}={v}' for k, v in os.environ.items() if k.startswith('EXIOBASE_'))
    original_cmd = ' '.join(sys.argv)
    retry_cmd = f"{env_prefix + ' ' if env_prefix else ''}.venv/bin/python3 {original_cmd}"
    sys.exit(
        "Missing dependency: PyYAML.\n"
        "This folder has a .venv with it installed. Options:\n"
        f"  1. Just this once:      {retry_cmd}\n"
        "  2. For this session:    source .venv/bin/activate\n"
        "  3. Permanently:         python3 -m pip install -r requirements.txt\n"
        "     (installs into whatever 'python3' you normally run — after this, the short command works in any terminal, no venv needed)"
    )

def load_config():
    """
    Load configuration from config.yaml.
    When run as a subprocess from main.py, EXIOBASE_TRADEFLOW, EXIOBASE_YEAR,
    EXIOBASE_COUNTRY, and EXIOBASE_COUNTRY_LIST environment variables override
    the config file values, so config.yaml mutations from the parent process
    cannot cause stale values inside subprocesses — and so a one-off script
    run (e.g. `EXIOBASE_YEAR=2019 python3 trade.py`) doesn't require editing
    config.yaml's YEAR and remembering to revert it afterward.
    EXIOBASE_YEAR (or config.yaml's YEAR) may be a comma-separated list of
    years (e.g. "2019,2021") — main.py's batch loop resolves that into a
    year list and runs each one in turn.
    """
    config_path = Path(__file__).parent / 'config.yaml'

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Environment variable overrides (set by main.py for each subprocess invocation)
    tradeflow_env = os.environ.get('EXIOBASE_TRADEFLOW')
    year_env = os.environ.get('EXIOBASE_YEAR')
    country_list_env = os.environ.get('EXIOBASE_COUNTRY_LIST')
    country_env = os.environ.get('EXIOBASE_COUNTRY')
    comprehensive_folders_env = os.environ.get('EXIOBASE_COMPREHENSIVE_FOLDERS')
    comprehensive_target_env = os.environ.get('EXIOBASE_COMPREHENSIVE_TARGET')

    if tradeflow_env:
        config['TRADEFLOW'] = tradeflow_env

    if year_env:
        # A comma-separated value (e.g. "2019,2021") is left as a string here;
        # only main.py's batch loop resolves it into a year list and re-exports
        # EXIOBASE_YEAR as a single year per iteration for subprocesses.
        config['YEAR'] = int(year_env) if ',' not in year_env else year_env

    if country_list_env:
        if isinstance(config['COUNTRY'], dict):
            config['COUNTRY']['list'] = country_list_env
        else:
            config['COUNTRY'] = country_list_env

    if country_env:
        if isinstance(config['COUNTRY'], dict):
            config['COUNTRY']['current'] = country_env
        else:
            config['COUNTRY'] = {'list': str(config['COUNTRY']), 'current': country_env}

    if comprehensive_folders_env:
        config.setdefault('COMPREHENSIVE', {})['folders'] = comprehensive_folders_env

    if comprehensive_target_env:
        config.setdefault('COMPREHENSIVE', {})['target'] = comprehensive_target_env

    return config


def get_comprehensive_folders_scope(config):
    """
    Resolve COMPREHENSIVE.folders ("all" or "default") to a lowercase string,
    defaulting to "all" when the key is absent (a config.yaml from before
    this setting existed, or one that never set it). Any value other than
    the literal "default" is treated as "all" — see PLAN-comprehensive.md's
    "config.yaml" section.
    """
    comprehensive = config.get('COMPREHENSIVE') or {}
    folders = str(comprehensive.get('folders', 'all')).strip().lower()
    return 'default' if folders == 'default' else 'all'


def get_comprehensive_target(config):
    """
    Resolve COMPREHENSIVE.target ("year_db" or "industrydb") to a lowercase
    string, defaulting to "year_db" when the key is absent. Any value other
    than the literal "industrydb" is treated as "year_db" — see
    PLAN-comprehensive.md's "Database write path" section.
    """
    comprehensive = config.get('COMPREHENSIVE') or {}
    target = str(comprehensive.get('target', 'year_db')).strip().lower()
    return 'industrydb' if target == 'industrydb' else 'year_db'

def update_config(updates):
    """
    Update configuration file with new values
    """
    config_path = Path(__file__).parent / 'config.yaml'
    
    # Load current config
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Update with new values
    config.update(updates)
    
    # Write back to file
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    return config

def get_output_folder(config, tradeflow_type=None):
    """
    Get the appropriate output folder based on trade flow type
    """
    if tradeflow_type is None:
        tradeflow_type = config['TRADEFLOW']
    
    folder_path = config['FOLDERS'][tradeflow_type]
    # Handle COUNTRY as either string or dict with current sub-parameter
    country_config = config['COUNTRY']
    if isinstance(country_config, dict):
        if 'current' in country_config:
            country = country_config['current']
        elif 'list' in country_config:
            # If no current is set, use first from list
            country_list = country_config['list'].split(',')
            country = country_list[0].strip()
        else:
            country = str(country_config)
    elif isinstance(country_config, str):
        if ',' in country_config:
            country = country_config.split(',')[0].strip()  
        else:
            country = country_config
    else:
        country = str(country_config)
    # Substitute year and country placeholders
    return folder_path.format(year=config['YEAR'], country=country)

def get_file_path(config, file_key, tradeflow_type=None):
    """
    Get full file path for a given file key
    Special handling for trade_factor in domestic vs non-domestic flows
    """
    folder = get_output_folder(config, tradeflow_type)
    
    # Special handling for trade_factor
    if file_key == 'trade_factor':
        current_tradeflow = tradeflow_type or config.get('TRADEFLOW', '')
        if current_tradeflow.lower() == 'domestic':
            # For domestic flows, check if _lg version exists, otherwise use regular
            lg_path = f"{folder}/{config['FILES']['trade_factor_domestic']}"
            regular_path = f"{folder}/{config['FILES']['trade_factor']}"
            
            if Path(lg_path).exists():
                filename = config['FILES']['trade_factor_domestic']
            else:
                filename = config['FILES']['trade_factor']
        else:
            filename = config['FILES'][file_key]
    else:
        filename = config['FILES'][file_key]
    
    # Ensure folder exists
    Path(folder).mkdir(parents=True, exist_ok=True)
    
    return f"{folder}/{filename}"

def get_reference_file_path(config, file_key):
    """
    Get path for reference files (always in base folder)
    """
    base_folder = config['FOLDERS']['base']
    # Substitute year placeholder
    base_folder = base_folder.format(year=config['YEAR'])
    filename = config['FILES'][file_key]
    
    # Ensure folder exists
    Path(base_folder).mkdir(parents=True, exist_ok=True)
    
    return f"{base_folder}/{filename}"

def print_config_summary(config):
    """
    Print current configuration summary
    """
    print(f"Configuration Summary:")
    print(f"  Trade Flow: {config['TRADEFLOW']}")
    print(f"  Year: {config['YEAR']}")
    
    country_config = config['COUNTRY']
    if isinstance(country_config, dict):
        current_country = country_config.get('current', 'Not set')
        country_list = country_config.get('list', 'Not set')
        print(f"  Current Country: {current_country}")
        print(f"  Available Countries: {country_list}")
    else:
        current_country = country_config.split(',')[0].strip() if ',' in str(country_config) else str(country_config)
        print(f"  Current Country: {current_country}")
        if ',' in str(country_config):
            print(f"  All Countries: {country_config}")
    
    print(f"  Output Folder: {get_output_folder(config)}")
    print()

if __name__ == "__main__":
    # Test the configuration loader
    config = load_config()
    print_config_summary(config)
    
    # Test file path generation
    print("Sample file paths:")
    print(f"  Industry trade flow: {get_file_path(config, 'industryflow')}")
    print(f"  Trade employment: {get_file_path(config, 'trade_employment')}")
    print(f"  Industries (ref): {get_reference_file_path(config, 'industries')}")