#!/usr/bin/env python3
"""
Guides a developer through downloading the raw Exiobase MRIO year file
(IOT_{year}_pxp.zip, roughly 0.2–4 GB depending on year) before running any processing.

trade.py calls ensure_exiobase_file() automatically and silently as part of
its own run, but a large download with no visible starting point is easy
to mistake for a hang. Run this on its own first so the download happens (and
its progress is visible) before any processing begins:

    python3 exiobase_download.py            # uses YEAR from config.yaml
    python3 exiobase_download.py --year 2021
"""

import argparse
from pathlib import Path

import pymrio

MODEL_TYPE = 'pxp'  # product-by-product matrix


def _download_direct(model_path: Path, year: int, model_type: str = MODEL_TYPE) -> Path:
    """
    Direct download from Zenodo using the current API URL format.
    pymrio's built-in downloader uses a regex that no longer matches Zenodo's
    URLs (Zenodo changed from /records/ID/files/NAME.zip to
    /api/records/ID/files/NAME.zip/content), so this method bypasses it.
    """
    import requests

    filename = f"IOT_{year}_{model_type}.zip"
    dest = model_path / filename

    doi_url = "https://doi.org/10.5281/zenodo.3583070"
    print("Resolving Zenodo DOI to find current record ID...")
    r = requests.get(doi_url, allow_redirects=True, timeout=30)
    record_id = r.url.rstrip('/').split('/')[-1]
    if not record_id.isdigit():
        raise RuntimeError(f"Could not extract Zenodo record ID from URL: {r.url}")

    download_url = f"https://zenodo.org/api/records/{record_id}/files/{filename}/content"
    print(f"Downloading {filename} from Zenodo record {record_id}...")
    print(f"URL: {download_url}")
    print("(This may take anywhere from under a minute to over an hour depending on file size and connection speed)")

    with requests.get(download_url, stream=True, timeout=3600) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  Progress: {pct:.1f}% ({downloaded/1e9:.2f}/{total/1e9:.2f} GB)",
                          end='', flush=True)
    print()
    print(f"Successfully downloaded {filename}")
    return dest


def ensure_exiobase_file(model_path: Path, year: int, model_type: str = MODEL_TYPE):
    """
    Ensure the Exiobase zip for `year` is present, downloading it if needed.
    Tries pymrio's downloader first, then a direct Zenodo download. There's no
    prior-year fallback: output folders are named by the requested year, so another
    year's tables would be written under the wrong year.

    Returns the path on success, or None if both downloads failed.
    """
    model_path.mkdir(exist_ok=True)
    exio_file = model_path / f'IOT_{year}_{model_type}.zip'
    if exio_file.exists():
        print(f"Found existing Exiobase file: {exio_file}")
        return exio_file

    print(f"No local Exiobase {year} file found — starting download.")
    print(f"Destination: {exio_file}")
    print("Source: Exiobase v3 MRIO, via Zenodo (https://doi.org/10.5281/zenodo.3583070)")
    print("Expect anywhere from under a minute to over an hour depending on file size (roughly 0.2-4 GB) and connection speed.\n")

    try:
        print(f"Downloading Exiobase {year} data via pymrio...")
        pymrio.download_exiobase3(storage_folder=model_path, system=model_type, years=[year])
        if not exio_file.exists():
            raise RuntimeError(
                f"pymrio.download_exiobase3 completed without error but did not create "
                f"{exio_file.name}. pymrio's URL regex no longer matches Zenodo's current "
                f"API format (/api/records/ID/files/NAME.zip/content). Trying direct download."
            )
        print(f"Successfully downloaded Exiobase {year} data")
        return exio_file
    except Exception as e:
        print(f"pymrio download issue: {e}")

    try:
        return _download_direct(model_path, year, model_type)
    except Exception as direct_e:
        print(f"Direct download failed for {year}: {direct_e}")
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--year', type=int, default=None, help='Exiobase year to download (default: YEAR in config.yaml)')
    args = parser.parse_args()

    if args.year is None:
        from config_loader import load_config
        args.year = load_config()['YEAR']

    model_path = Path(__file__).parent / 'exiobase_data'
    path = ensure_exiobase_file(model_path, args.year)

    if path is None:
        print("\nDownload unavailable — trade.py will stop if run for this year now.")
        raise SystemExit(1)

    print(f"\nReady: {path}")


if __name__ == "__main__":
    main()
