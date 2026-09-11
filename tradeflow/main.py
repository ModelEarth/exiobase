#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart batch processing with enhanced country list handling
Supports: "all", "default", auto-populate current, cleanup when done
"""

import subprocess
import sys
import time
import yaml
from pathlib import Path
from config_loader import load_config

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
    """Get the default list of 12 countries"""
    return ['CN', 'DE', 'JP', 'GB', 'FR', 'IT', 'CA', 'BR', 'AU', 'KR', 'US', 'IN']

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

def update_config_file(updates):
    """Update config.yaml file with new values"""
    config_path = Path(__file__).parent / 'config.yaml'
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Apply updates
    for key, value in updates.items():
        if '.' in key:
            # Handle nested keys like COUNTRY.current
            parts = key.split('.')
            current_level = config
            for part in parts[:-1]:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]
            current_level[parts[-1]] = value
        else:
            config[key] = value
    
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

def remove_config_key(key_path):
    """Remove a key from config.yaml"""
    config_path = Path(__file__).parent / 'config.yaml'
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Remove nested key
    parts = key_path.split('.')
    current_level = config
    for part in parts[:-1]:
        if part in current_level:
            current_level = current_level[part]
        else:
            return  # Key doesn't exist
    
    if parts[-1] in current_level:
        del current_level[parts[-1]]
        
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

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
    
    # Set current country in config
    update_config_file({'COUNTRY.current': country})
    
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
    
    return success_count == len(scripts)

def main():
    """Smart batch processing with enhanced country handling"""
    config = load_config()
    tradeflow_config = config['TRADEFLOW']
    
    # Handle comma-separated tradeflows
    if ',' in tradeflow_config:
        tradeflows = [tf.strip() for tf in tradeflow_config.split(',')]
        print(f"[LIST] Processing multiple tradeflows: {', '.join(tradeflows)}")
    else:
        tradeflows = [tradeflow_config]
    
    # Process each tradeflow separately
    for tradeflow in tradeflows:
        print(f"\n{'='*100}")
        print(f"[START] STARTING BATCH PROCESSING FOR TRADEFLOW: {tradeflow.upper()}")
        print(f"{'='*100}")
        
        # Temporarily update config file for this tradeflow
        original_tradeflow = config['TRADEFLOW']
        update_config_file({'TRADEFLOW': tradeflow})
        config['TRADEFLOW'] = tradeflow
        
        # Resolve country list (handles 'all', 'default', explicit)
        all_countries = resolve_country_list(config)
        
        # Filter out already completed countries for resume functionality
        countries, completed_countries = filter_incomplete_countries(all_countries, tradeflow, config['YEAR'])
        
        process_tradeflow(config, tradeflow, all_countries, countries, completed_countries)
        
        # Restore original config file
        update_config_file({'TRADEFLOW': original_tradeflow})
        config['TRADEFLOW'] = original_tradeflow

def process_tradeflow(config, tradeflow, all_countries, countries, completed_countries):
    """Process a single tradeflow for all countries"""
    print(f"\n[START] STARTING SMART BATCH PROCESSING")
    print(f"Trade Flow: {tradeflow}")
    print(f"All countries: {', '.join(all_countries)}")
    print(f"Countries to process: {', '.join(countries) if countries else 'None - All completed!'}")
    print(f"Total countries to process: {len(countries)}")
    print(f"Time allocation: 5 hours total for entire batch")
    print(f"Estimated time per country: ~{300/len(countries) if countries else 0:.0f} minutes")
    
    # If all countries are completed, show summary and exit
    if not countries:
        print(f"\n[SUCCESS] ALL COUNTRIES ALREADY COMPLETED!")
        print(f"[OK] Completed countries: {', '.join(completed_countries)}")
        print(f"[CLEAN] Cleaning up config - removing current country setting...")
        remove_config_key('COUNTRY.current')
        return
    
    batch_start = time.time()
    batch_timeout = 18000  # 5 hours in seconds
    country_timeout = 3600  # 1 hour per country (60 minutes)
    print(f"[TIME] Per-country time limit: {country_timeout/60:.0f} minutes")
    results = {}
    
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
            
        remaining_time = (batch_timeout - elapsed_batch_time) / 3600
        print(f"\n{'[RELOAD]' * 20}")
        print(f"PROCESSING COUNTRY {i}/{len(countries)}: {country}")
        print(f"[TIME] Batch time remaining: {remaining_time:.1f} hours")
        print(f"{'[RELOAD]' * 20}")
        
        country_success = run_country_processing(country, tradeflow, batch_start, batch_timeout, country_timeout)
        results[country] = country_success
        
        # If country processing was stopped due to batch timeout, break
        if not country_success and elapsed_batch_time >= batch_timeout:
            break
    
    # Clean up - remove current from config when done
    print(f"\n[CLEAN] Cleaning up config - removing current country setting...")
    remove_config_key('COUNTRY.current')
    
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
            result = subprocess.run(['find', f'year/{year}/{country}/{tradeflow}', '-name', '*.csv', '-type', 'f'], 
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