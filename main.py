
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent

PIPELINE = [
    ("ENGINE 1: DATA INGESTION", "engine1/ingestion.py"),
    ("ENGINE 2: DATA NORMALIZATION", "engine2/normalization.py"),
    ("ENGINE 3: ENTITY RESOLUTION", "engine3/matcher.py"),
    ("ENGINE 4: DATA INTEGRATION", "engine4/integration.py"),
]


def run_engine(name, script):
    script_path = BASE_DIR / script

    print("\n" + "=" * 65)
    print(f"RUNNING {name}")
    print("=" * 65)

    if not script_path.exists():
        raise FileNotFoundError(f"Engine file not found: {script_path}")

    subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=BASE_DIR,
        check=True
    )

    print(f"\n{name} COMPLETED SUCCESSFULLY")


def main():
    start_time = datetime.now()

    print("\n")
    print("*" * 65)
    print(" MULTI-SOURCE MOVIE DATA INTEGRATION PIPELINE")
    print("*" * 65)

    try:
        for name, script in PIPELINE:
            run_engine(name, script)

        duration = (datetime.now() - start_time).total_seconds()

        print("\n" + "*" * 65)
        print(" COMPLETE PIPELINE EXECUTED SUCCESSFULLY!")
        print("*" * 65)

        print(f"Total execution time: {duration:.2f} seconds")

        print("\nFINAL OUTPUT FILES:")
        print("1. output/unified_movies.json")
        print("2. output/unified_movies.csv")
        print("3. output/movie_sources.csv")

    except subprocess.CalledProcessError as error:
        print("\nPIPELINE FAILED!")
        print("Failed script:", error.cmd)
        print("Exit code:", error.returncode)
        sys.exit(error.returncode)

    except Exception as error:
        print("\nPIPELINE ERROR:", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
