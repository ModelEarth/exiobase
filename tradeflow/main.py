#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart batch processing with enhanced country list handling
Supports: "all", "default", auto-populate current, cleanup when done

Settings (TRADEFLOW, YEAR, COUNTRY) come from config.yaml, overridable via
EXIOBASE_TRADEFLOW / EXIOBASE_YEAR / EXIOBASE_COUNTRY_LIST env vars so a run
doesn't need to edit config.yaml (safe alongside other processes using it).
Pass --saveconfig to also persist the resolved settings back to config.yaml,
written once up front, before any country/tradeflow processing starts.

Pass --interstate US to also run bea/main.py (interstate/BEA state data)
right after each year's trade data finishes — one combined command instead
of two. Pass a comma-separated list to run more than one, e.g.
--interstate US,IN (a space after the comma is optional, so
--interstate US, IN also works). This script never uses BEA_API_KEY or
India_data itself, but since bea/main.py and india/main.py do, --interstate
checks that each one's prerequisite is findable before any trade
processing starts, so a missing key/directory fails immediately rather
than after a long run.
"""

import subprocess
import sys
import time
from pathlib import Path
from config_loader import load_config  # also validates PyYAML is installed
import yaml

# Set UTF-8 encoding for Windows console
import os
if os.name == 'nt':  # Windows
    import locale
    # Try to set UTF-8 locale
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except:
        pass

def get_existing_countries(year):
    """Get list of countries that have folders in the year directory"""
    year_path = Path(f"year/{year}")
    if not year_path.exists():
        return []
    
    countries = []
    for item in year_path.iterdir():
        if item.is_dir() and len(item.name) == 2:  # Country codes are 2 letters
            countries.append(item.name)
    
    return sorted(countries)

def get_default_countries():
    """Get the default list of 14 countries"""
    return ['AU', 'BR', 'CA', 'CN', 'DE', 'FR', 'GB', 'IN', 'IT', 'JP', 'KR', 'RU', 'US', 'WM']

def update_config_file(updates):
    """Write top-level key updates to config.yaml (opt-in via --saveconfig, called once up front)"""
    config_path = Path(__file__).parent / 'config.yaml'

    with open(config_path, 'r') as f:
        disk_config = yaml.safe_load(f)

    disk_config.update(updates)

    with open(config_path, 'w') as f:
        yaml.dump(disk_config, f, default_flow_style=False, sort_keys=False)

def resolve_year_list(config):
    """Resolve YEAR into a list of ints, supporting a comma-separated value"""
    year_config = config['YEAR']
    if isinstance(year_config, str) and ',' in year_config:
        return [int(y.strip()) for y in year_config.split(',')]
    return [int(year_config)]

def resolve_country_list(config):
    """Resolve country list based on 'all', 'default', or explicit list"""
    country_config = config['COUNTRY']
    
    if isinstance(country_config, dict):
        country_list = country_config.get('list', '')
    else:
        country_list = str(country_config)
    
    year = config['YEAR']
    
    if country_list.lower() == 'all':
        print("[WORLD] Resolving 'all' - checking existing country folders...")
        existing = get_existing_countries(year)
        if existing:
            print(f"Found {len(existing)} existing countries: {', '.join(existing)}")
            return existing
        else:
            print("No existing countries found, using default list")
            return get_default_countries()
    
    elif country_list.lower() == 'default':
        print("[TARGET] Using default country list")
        return get_default_countries()
    
    else:
        # Parse comma-separated list
        countries = [c.strip() for c in country_list.split(',')]
        print(f"[LIST] Using explicit country list: {', '.join(countries)}")
        return countries

def is_country_completed(country, tradeflow, year):
    """Check if a country has already completed processing"""
    config = load_config()
    # Use the folder path from config for the specific tradeflow
    folder_path = config['FOLDERS'][tradeflow].format(year=year, country=country)
    runnote_path = Path(folder_path) / "runnote.md"
    return runnote_path.exists()

def filter_incomplete_countries(countries, tradeflow, year):
    """Filter out countries that have already completed processing"""
    incomplete = []
    completed = []
    
    for country in countries:
        if is_country_completed(country, tradeflow, year):
            completed.append(country)
        else:
            incomplete.append(country)
    
    if completed:
        print(f"[RELOAD] Resume mode: Found {len(completed)} already completed countries: {', '.join(completed)}")
        print(f"[LIST] Processing {len(incomplete)} remaining countries: {', '.join(incomplete) if incomplete else 'None'}")
    
    return incomplete, completed

def run_country_processing(country, tradeflow, batch_start_time, batch_timeout=18000, country_timeout=3600):
    """Run complete processing for a single country with timing and batch timeout check"""
    # Check if batch timeout exceeded before starting country
    elapsed_batch_time = time.time() - batch_start_time
    if elapsed_batch_time >= batch_timeout:
        print(f"[TIME] BATCH TIMEOUT: {elapsed_batch_time/3600:.1f} hours elapsed, stopping before {country}")
        return False
    print(f"\n{'='*80}")
    print(f"[HOME] STARTING {tradeflow.upper()} PROCESSING FOR {country}")
    print(f"{'='*80}")
    
    start_time = time.time()

    scripts = [
        'trade.py',
        'trade_impact.py',
        'trade_resource.py',
        'trade_competitiveness.py',
    ]
    
    success_count = 0
    for i, script in enumerate(scripts, 1):
        # Check both batch and country timeouts before each script
        elapsed_batch_time = time.time() - batch_start_time
        elapsed_country_time = time.time() - start_time
        
        if elapsed_batch_time >= batch_timeout:
            print(f"[TIME] BATCH TIMEOUT: {elapsed_batch_time/3600:.1f} hours elapsed, stopping at {script}")
            break
            
        if elapsed_country_time >= country_timeout:
            print(f"[TIME] COUNTRY TIMEOUT: {elapsed_country_time/60:.1f} minutes elapsed for {country}, stopping at {script}")
            break
            
        script_start = time.time()
        remaining_country_time = (country_timeout - elapsed_country_time) / 60
        print(f"\n[PLAY]  [{i}/{len(scripts)}] Running {script} for {country}...")
        print(f"   [TIMER]  Country time remaining: {remaining_country_time:.1f} minutes")
        
        try:
            result = subprocess.run([
                sys.executable, script
            ], capture_output=True, text=True, timeout=1200,  # 20 minutes per script
               cwd=Path(__file__).parent,
               env={**os.environ, 'EXIOBASE_TRADEFLOW': tradeflow, 'EXIOBASE_COUNTRY': country})
            
            script_time = time.time() - script_start
            
            if result.returncode == 0:
                print(f"[OK] {script} completed in {script_time:.1f}s")
                # Show key output lines
                if result.stdout:
                    lines = result.stdout.strip().split('\n')
                    for line in lines[-3:]:
                        if any(keyword in line for keyword in ['[OK]', 'Created', 'Total', 'completed', 'factors']):
                            print(f"   [CHART] {line}")
                success_count += 1
            else:
                print(f"[ERROR] {script} failed after {script_time:.1f}s")
                if result.stderr:
                    error_lines = result.stderr.strip().split('\n')
                    last_error = error_lines[-1] if error_lines else 'Unknown error'
                    print(f"   [WARN]  Error: {last_error}")
                    if 'ModuleNotFoundError' in result.stderr or 'No module named' in result.stderr:
                        print(f"   [HINT]  Missing Python package. Install dependencies with:")
                        print(f"          pip install -r {Path(__file__).parent / 'requirements.txt'}")
                break
                
        except subprocess.TimeoutExpired:
            script_time = time.time() - script_start
            print(f"[TIME] {script} timed out after {script_time:.1f}s (20 min limit)")
            break
        except Exception as e:
            script_time = time.time() - script_start
            print(f"[ERROR] {script} error after {script_time:.1f}s: {e}")
            break
    
    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = int(total_time % 60)
    
    # Enhanced completion feedback
    print(f"\n{'='*80}")
    print(f"[TARGET] {country} {tradeflow.upper()} PROCESSING COMPLETE")
    print(f"{'='*80}")
    print(f"[TIMER]  Total country time: {minutes}m {seconds}s (limit: {country_timeout/60:.0f} minutes)")
    print(f"[OK] Scripts completed: {success_count}/{len(scripts)}")
    
    # Show completion percentage
    completion_pct = (success_count / len(scripts)) * 100
    print(f"[CHART] Completion rate: {completion_pct:.1f}%")
    
    # Enhanced status message
    if success_count == len(scripts):
        print(f"[SUCCESS] {country} {tradeflow} processing FULLY SUCCESSFUL!")
        print(f"[FOLDER] Generated: trade_factor.csv + trade_factor_lg.csv (721 factors)")
        
        # Create runnote.md for successful completion
        create_runnote(country, tradeflow, start_time, total_time, success_count, len(scripts))
    else:
        print(f"[WARN]  {country} {tradeflow} processing PARTIALLY COMPLETED ({success_count}/{len(scripts)} scripts)")
        if total_time >= country_timeout * 0.9:
            print(f"[TIME] Country approached time limit: {total_time/60:.1f}/{country_timeout/60:.0f} minutes")
    
    # Time efficiency feedback
    if total_time < 300:  # Less than 5 minutes
        print(f"[START] Fast processing - completed in under 5 minutes!")
    elif total_time > 600:  # More than 10 minutes  
        print(f"[SLOW] Slower processing - took over 10 minutes")
    
    return success_count == len(scripts), total_time

# country code -> script that provides its interstate/state-level processing
INTERSTATE_SCRIPTS = {
    'US': 'bea/main.py',
    'IN': 'india/main.py',
}

def resolve_interstate_countries():
    """Parse --interstate <LIST> from sys.argv. LIST is one or more country
    codes from INTERSTATE_SCRIPTS, comma-separated, with or without spaces
    around the commas — --interstate US,IN and --interstate US, IN both
    work (the latter is split by an unquoted shell into two argv tokens,
    "US," and "IN"; both are consumed here). Returns a list of country
    codes (uppercased, order preserved, no duplicates), or [] if
    --interstate wasn't passed."""
    if '--interstate' not in sys.argv:
        return []
    idx = sys.argv.index('--interstate')

    # Consume every following token that isn't itself a flag, so an
    # unquoted "US, IN" (split by the shell into separate argv entries)
    # is still captured.
    tokens = []
    j = idx + 1
    while j < len(sys.argv) and not sys.argv[j].startswith('--'):
        tokens.append(sys.argv[j])
        j += 1

    if not tokens:
        sys.exit("--interstate requires at least one country code, e.g. --interstate US or --interstate US,IN")

    countries = [c.strip().upper() for c in ' '.join(tokens).split(',') if c.strip()]

    unsupported = [c for c in countries if c not in INTERSTATE_SCRIPTS]
    if unsupported:
        sys.exit(
            f"--interstate {','.join(unsupported)} not supported — "
            f"currently supported: {', '.join(INTERSTATE_SCRIPTS)}."
        )

    seen = set()
    result = []
    for c in countries:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result

def run_interstate_step(year, interstate_countries):
    """Run each requested country's interstate/state-level script for one
    year, right after that year's trade data finishes. Inherits os.environ,
    which already has EXIOBASE_YEAR set for this year (and BEA_API_KEY
    loaded, if US was requested, found by main()'s pre-flight check before
    any processing started)."""
    for country in interstate_countries:
        script = INTERSTATE_SCRIPTS[country]
        print(f"\n{'='*100}")
        print(f"[INTERSTATE] STARTING {script} FOR YEAR: {year} ({country})")
        print(f"{'='*100}")
        result = subprocess.run([sys.executable, script], cwd=Path(__file__).parent, env=os.environ)
        if result.returncode == 0:
            print(f"[INTERSTATE] {script} completed successfully for {year}")
        else:
            print(f"[ERROR] {script} failed for {year} (exit code {result.returncode})")

def main():
    """Smart batch processing with enhanced country handling"""
    run_start_time = time.time()
    save_config = '--saveconfig' in sys.argv
    interstate_countries = resolve_interstate_countries()

    if interstate_countries:
        print(f"[INTERSTATE] --interstate {','.join(interstate_countries)} requested — checking prerequisites before starting...")

        if 'US' in interstate_countries:
            from bea_key import find_bea_api_key
            if not find_bea_api_key():
                sys.exit(
                    "BEA_API_KEY not found, but --interstate US was requested.\n"
                    "main.py doesn't use the key itself, but bea/main.py will need it after trade\n"
                    "processing finishes — add BEA_API_KEY=your_key to webroot/docker/.env or\n"
                    "webroot/.env before starting this run, so a missing key fails now instead of\n"
                    "after a long trade-data run.\n"
                    "Register at https://apps.bea.gov/api/signup/"
                )
            print("[INTERSTATE] BEA_API_KEY found.")

        if 'IN' in interstate_countries:
            india_data_dir = Path(__file__).parent.parent / 'India_data'
            if not india_data_dir.exists():
                sys.exit(
                    f"India_data directory not found at {india_data_dir}, but --interstate IN was requested.\n"
                    "india/main.py needs source files there (GSDP, GSVA, SUT, TradeStat exports/imports) —\n"
                    "create the directory and add them before starting this run, so a missing input\n"
                    "fails now instead of after a long trade-data run."
                )
            print("[INTERSTATE] India_data directory found.")

        scripts = ', '.join(INTERSTATE_SCRIPTS[c] for c in interstate_countries)
        print(f"[INTERSTATE] Prerequisites OK — {scripts} will run for each year after its trade data completes.")

    config = load_config()
    tradeflow_config = config['TRADEFLOW']
    years = resolve_year_list(config)

    if len(years) > 1:
        print(f"[YEARS] Processing multiple years: {', '.join(str(y) for y in years)}")

    # Handle comma-separated tradeflows
    if ',' in tradeflow_config:
        tradeflows = [tf.strip() for tf in tradeflow_config.split(',')]
        print(f"[LIST] Processing multiple tradeflows: {', '.join(tradeflows)}")
    else:
        tradeflows = [tradeflow_config]

    # Optionally persist the resolved (possibly env-overridden) settings to
    # config.yaml, once, before any processing starts.
    if save_config:
        country_config = config['COUNTRY']
        country_to_save = country_config.get('list', '') if isinstance(country_config, dict) else country_config
        print(f"[SAVE] --saveconfig: writing TRADEFLOW={tradeflow_config}, YEAR={config['YEAR']}, COUNTRY.list={country_to_save} to config.yaml")
        update_config_file({
            'TRADEFLOW': tradeflow_config,
            'YEAR': config['YEAR'],
            'COUNTRY': {'list': country_to_save},
        })

    # Process each year separately
    for year in years:
        if len(years) > 1:
            print(f"\n{'#'*100}")
            print(f"[YEAR] STARTING BATCH PROCESSING FOR YEAR: {year}")
            print(f"{'#'*100}")

        config['YEAR'] = year
        # Subprocesses inherit os.environ, so re-export a single resolved
        # year even if the shell originally passed a comma-separated list.
        os.environ['EXIOBASE_YEAR'] = str(year)

        # Process each tradeflow separately
        for tradeflow in tradeflows:
            print(f"\n{'='*100}")
            print(f"[START] STARTING BATCH PROCESSING FOR TRADEFLOW: {tradeflow.upper()}")
            print(f"{'='*100}")

            config['TRADEFLOW'] = tradeflow

            # Resolve country list (handles 'all', 'default', explicit)
            all_countries = resolve_country_list(config)

            # Filter out already completed countries for resume functionality
            countries, completed_countries = filter_incomplete_countries(all_countries, tradeflow, config['YEAR'])

            process_tradeflow(config, tradeflow, all_countries, countries, completed_countries)

        if interstate_countries:
            run_interstate_step(year, interstate_countries)

    total_run_time = time.time() - run_start_time
    hours = int(total_run_time // 3600)
    minutes = int((total_run_time % 3600) // 60)
    seconds = int(total_run_time % 60)
    output_for = f"{len(years)} year(s), {len(tradeflows)} tradeflow(s)"
    if interstate_countries:
        output_for += f", {' '.join(interstate_countries)} interstate"
    print(f"\n{'='*100}")
    print(f"[DONE] TOTAL RUN TIME: {hours}h {minutes}m {seconds}s")
    print(f"OUTPUT FOR: {output_for}")
    print(f"{'='*100}")

def process_tradeflow(config, tradeflow, all_countries, countries, completed_countries):
    """Process a single tradeflow for all countries"""
    print(f"\n[START] STARTING SMART BATCH PROCESSING")
    print(f"Trade Flow: {tradeflow}")
    print(f"All countries: {', '.join(all_countries)}")
    print(f"Countries to process: {', '.join(countries) if countries else 'None - All completed!'}")
    print(f"Total countries to process: {len(countries)}")
    print(f"Estimated time per country: ~{300/len(countries) if countries else 0:.0f} minutes")
    
    # If all countries are completed, show summary and exit
    if not countries:
        print(f"\n[SUCCESS] ALL COUNTRIES ALREADY COMPLETED!")
        print(f"[OK] Completed countries: {', '.join(completed_countries)}")
        return
    
    batch_start = time.time()
    batch_timeout = 18000  # 5 hours - hard safety ceiling, not a pace estimate
    country_timeout = 3600  # 1 hour per country - hard safety ceiling, not a pace estimate
    print(f"[TIME] Per-country safety limit: {country_timeout/60:.0f} minutes (hard stop; actual pace is estimated below once measured)")
    results = {}
    country_durations = []  # actual measured seconds per country, this run only

    # Initialize results for completed countries as successful
    for country in completed_countries:
        results[country] = True

    for i, country in enumerate(countries, 1):
        # Check batch timeout before starting each country
        elapsed_batch_time = time.time() - batch_start
        if elapsed_batch_time >= batch_timeout:
            print(f"\n[TIME] BATCH TIMEOUT REACHED: {elapsed_batch_time/3600:.1f} hours elapsed")
            print(f"[STOP] Stopping processing. Remaining countries: {', '.join(countries[i-1:])}")
            # Mark remaining countries as not processed
            for remaining_country in countries[i-1:]:
                results[remaining_country] = False
            break

        remaining_countries = len(countries) - (i - 1)
        print(f"\n{'[RELOAD]' * 20}")
        print(f"PROCESSING COUNTRY {i}/{len(countries)}: {country}")
        if country_durations:
            # Use the 2nd country's measured time alone once available — the
            # 1st often runs slower due to one-time startup/caching overhead.
            estimate_per_country = country_durations[1] if len(country_durations) >= 2 else country_durations[0]
            est_remaining_minutes = estimate_per_country * remaining_countries / 60
            print(f"[TIME] Estimated time remaining: {est_remaining_minutes:.1f} minutes (~{estimate_per_country/60:.1f} min/country, based on measured pace)")
        else:
            remaining_time = (batch_timeout - elapsed_batch_time) / 3600
            print(f"[TIME] Batch time remaining: {remaining_time:.1f} hours (safety limit; no measured pace yet)")
        print(f"{'[RELOAD]' * 20}")

        country_success, country_duration = run_country_processing(country, tradeflow, batch_start, batch_timeout, country_timeout)
        results[country] = country_success
        country_durations.append(country_duration)

        # If country processing was stopped due to batch timeout, break
        if not country_success and elapsed_batch_time >= batch_timeout:
            break
    
    # Final batch summary
    batch_time = time.time() - batch_start
    batch_minutes = int(batch_time // 60)
    batch_seconds = int(batch_time % 60)
    
    successful = [c for c, success in results.items() if success]
    failed = [c for c, success in results.items() if not success]
    
    print(f"\n{'='*80}")
    print(f"[FINISH] SMART BATCH PROCESSING COMPLETE FOR {tradeflow.upper()}")
    print(f"{'='*80}")
    print(f"[TIMER]  Total batch time: {batch_minutes}m {batch_seconds}s (of 5 hour limit)")
    if batch_time >= batch_timeout * 0.9:  # If we used 90%+ of time limit
        print(f"[WARN]  Close to time limit: {batch_time/3600:.1f}/5.0 hours used")
    print(f"[OK] All successful countries: {', '.join(successful) if successful else 'None'}")
    if failed:
        print(f"[ERROR] Failed countries: {', '.join(failed)}")
    if completed_countries:
        print(f"[RELOAD] Previously completed: {', '.join(completed_countries)}")
        print(f"🆕 Newly processed: {', '.join([c for c in countries if c in successful])}")
    total_countries = len(all_countries)
    print(f"[CHART] Overall success rate: {len(successful)}/{total_countries} ({len(successful)/total_countries*100:.1f}%)")
    
    # Show final file counts
    print(f"\n[FOLDER] Final output summary:")
    year = config['YEAR']
    for country in all_countries:
        try:
            folder_path = config['FOLDERS'][tradeflow].format(year=year, country=country)
            result = subprocess.run(['find', folder_path, '-name', '*.csv', '-type', 'f'],
                                  capture_output=True, text=True)
            file_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            status = "[OK]" if results[country] else "[WARN] "
            print(f"  {status} {country}: {file_count} CSV files created")
        except:
            print(f"  [QUESTION] {country}: Unable to count files")

def create_runnote(country, tradeflow, start_time, total_time, success_count, total_scripts):
    """Create runnote.md file to mark successful completion"""
    from datetime import datetime
    import os
    
    config = load_config()
    
    # Get the output folder path for this tradeflow
    folder_path = config['FOLDERS'][tradeflow].format(year=config['YEAR'], country=country)
    runnote_path = Path(folder_path) / "runnote.md"
    
    # Ensure the directory exists
    runnote_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check which files actually exist
    expected_files = ['trade.csv', 'trade_factor.csv', 'trade_impact.csv', 
                     'trade_employment.csv', 'trade_resource.csv', 'trade_material.csv']
    
    existing_files = []
    missing_files = []
    
    for filename in expected_files:
        file_path = runnote_path.parent / filename
        if file_path.exists():
            existing_files.append(filename)
        else:
            missing_files.append(filename)
    
    # Create runnote content
    processing_date = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
    
    files_section = ""
    if existing_files or missing_files:
        files_section += "## Files Generated\n\n"
        
        if existing_files:
            files_section += "### Files Successfully Created:\n"
            for filename in existing_files:
                files_section += f"- [OK] {filename}\n"
            
            if missing_files:
                files_section += "\n"
        
        if missing_files:
            files_section += "### Files Not Created:\n"
            for filename in missing_files:
                files_section += f"- [ERROR] {filename}\n"
        
        files_section += "\n"
    
    # Determine actual success based on both scripts and files created
    scripts_successful = success_count == total_scripts
    files_created = len(existing_files) > 0
    truly_successful = scripts_successful and files_created
    
    if truly_successful:
        status = "[OK] FULLY SUCCESSFUL"
        completion_note = "successful completion"
    elif scripts_successful and not files_created:
        status = "[WARN] SCRIPTS COMPLETED - NO FILES CREATED"
        completion_note = "script completion without file output"
    elif files_created and not scripts_successful:
        status = "[WARN] PARTIALLY COMPLETED - SOME FILES CREATED"
        completion_note = "partial completion with some file output"
    else:
        status = "[ERROR] FAILED"
        completion_note = "failed processing"
    
    # Format duration section only if we have meaningful duration
    duration_minutes = total_time / 60
    duration_section = f"**Duration:** {duration_minutes:.1f} minutes\n" if duration_minutes >= 0.1 else ""
    
    # Format title based on completion status
    title_suffix = "Processing Complete" if truly_successful else "Run Note"
    title = f"# {config['YEAR']} {country} {tradeflow.title()} - {title_suffix}"
    
    runnote_content = f"""{title}

**Processing Date:** {processing_date}
{duration_section}**Scripts Completed:** {success_count}/{total_scripts}
**Status:** {status}

{files_section}## Processing Notes
Generated by main.py automated batch processing.
"""
    
    # Write the runnote file
    with open(runnote_path, 'w') as f:
        f.write(runnote_content)
    
    print(f"[NOTE] Created runnote.md at: {runnote_path}")
    return runnote_path

if __name__ == "__main__":
    main()