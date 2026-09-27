"""Main entry point for the Snippen Doorman Service."""

import argparse
import logging
import sys


def main_cli() -> None:
    """CLI entry point for the Snippen Doorman Service."""
    parser = argparse.ArgumentParser(
        description="Snippen Doorman Service - Access control for Yale Doorman locks"
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--database-path", default="data/doorman.db", help="Database path")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting Snippen Doorman Service")


if __name__ == "__main__":
    main_cli()
