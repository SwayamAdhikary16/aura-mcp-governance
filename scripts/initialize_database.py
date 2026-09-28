"""Initialize the AURA SQLite database and seed governance catalogs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.database import initialize_database  # noqa: E402
from aura.repositories import AuraRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize AURA SQLite governance database.")
    parser.add_argument("--db-path", type=str, default=None, help="Optional custom SQLite DB path.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate existing database.")
    args = parser.parse_args()

    db_file = initialize_database(db_path=args.db_path, reset=args.reset)
    repo = AuraRepository(db_path=db_file)
    models = repo.get_model_catalog()
    routing = repo.get_active_routing_policy()
    challenger = repo.get_active_governance_policy()
    prompts = repo.get_prompt_catalog()

    sys.stderr.write(
        f"[AURA DB INIT] Initialized SQLite database at: {db_file}\n"
        f"  - Models seeded: {len(models)} ({', '.join(m['model_id'] for m in models)})\n"
        f"  - Active routing policy: {routing['policy_id']} (v{routing['policy_version']})\n"
        f"  - Active challenger policy: {challenger['policy_id']} (v{challenger['policy_version']})\n"
        f"  - Prompt versions seeded: {len(prompts)}\n"
    )


if __name__ == "__main__":
    main()
