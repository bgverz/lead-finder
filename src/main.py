"""Command-line entry point for the accredited investor lead pipeline."""

from __future__ import annotations

import click

from src.pipeline import LeadPipeline
from src.utils.config import load_config, missing_real_data_setup
from src.utils.logger import setup_logger


@click.command()
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--zip-codes", default="", help="Comma-separated ZIP codes to target.")
@click.option("--state", default="", help="Two-letter state code to target.")
@click.option("--output", "output_path", default="", help="Optional XLSX output path.")
@click.option("--no-persist", is_flag=True, help="Skip SQLite persistence.")
def main(config_path: str, zip_codes: str, state: str, output_path: str, no_persist: bool) -> None:
    """Run the lead generation pipeline."""

    config = load_config(config_path)
    logger = setup_logger("cli", config.pipeline.log_level)
    parsed_zip_codes = [item.strip() for item in zip_codes.split(",") if item.strip()]
    missing_setup = missing_real_data_setup(config)
    if config.sources.mode == "sample":
        click.echo("Sample-data mode active: no external API credentials are required.")
        if missing_setup:
            click.echo("Real-data setup still missing:")
            for item in missing_setup:
                click.echo(f"  - {item}")
    elif missing_setup:
        click.echo("Real-data mode selected, but setup is incomplete:")
        for item in missing_setup:
            click.echo(f"  - {item}")

    pipeline = LeadPipeline(config)
    leads, workbook = pipeline.run(
        zip_codes=parsed_zip_codes or None,
        state=state,
        output_path=output_path or None,
        persist=not no_persist,
    )

    counts = {tier: sum(1 for lead in leads if lead.score_tier == tier) for tier in ("Hot", "Warm", "Cool", "Skip")}
    logger.info("Generated %s leads: %s", len(leads), counts)
    click.echo(f"Generated {len(leads)} leads")
    click.echo(f"Workbook: {workbook}")
    click.echo(f"Tiers: {counts}")


if __name__ == "__main__":
    main()
