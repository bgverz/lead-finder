"""Local runability CLI for the lead pipeline."""

from __future__ import annotations

import importlib
import os
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import click
from dotenv import load_dotenv

from lead_pipeline.enrichment.apollo import ApolloClient
from lead_pipeline.pipeline import LeadPipeline
from lead_pipeline.utils.database import LeadDatabase, VALID_STATUSES
from lead_pipeline.utils.config import (
    Config,
    load_config,
    missing_api_mode_setup,
    missing_real_data_setup,
    optional_api_mode_warnings,
)

DEFAULT_CONFIG = Path("config/config.yaml")
FALLBACK_CONFIG = Path("config/config.example.yaml")
REQUIRED_ENV = ("CENSUS_API_KEY", "SEC_USER_AGENT")
OPTIONAL_ENV = (
    "ATTOM_API_KEY",
    "OPENCORPORATES_API_KEY",
    "NUMVERIFY_API_KEY",
    "ABSTRACT_PHONE_API_KEY",
    "APOLLO_API_KEY",
)
UNIMPLEMENTED_REAL_INTEGRATIONS = (
    "ATTOM/county property API adapter",
    "OpenCorporates/state SOS business adapter",
    "Apollo contact enrichment adapter",
    "Abstract phone validation adapter",
)
REQUIRED_IMPORTS = (
    "pandas",
    "numpy",
    "yaml",
    "requests",
    "aiohttp",
    "sqlalchemy",
    "openpyxl",
    "rich",
    "click",
    "dotenv",
)


@click.group()
def main() -> None:
    """Accredited investor lead pipeline."""


@main.command()
@click.option("--config", "config_path", default="", help="Path to YAML config.")
@click.option(
    "--mode",
    default="mock",
    type=click.Choice(["mock", "sample", "api", "strict-real"], case_sensitive=False),
    show_default=True,
)
@click.option("--zip-codes", default="", help="Comma-separated ZIP codes to target.")
@click.option("--state", default="", help="Two-letter state code to target.")
@click.option("--output", "output_path", default="", help="Optional XLSX output path.")
@click.option("--no-persist", is_flag=True, help="Skip SQLite persistence.")
@click.option("--limit", type=int, default=None, help="Maximum leads to write.")
@click.option("--open", "open_after", is_flag=True, help="Open the generated workbook after the run.")
@click.option(
    "--profile",
    default="",
    help="Apollo search profile (vc_pe, founders, family_office, real_estate, healthcare, broad_hnw, c_suite).",
)
def run(
    config_path: str,
    mode: str,
    zip_codes: str,
    state: str,
    output_path: str,
    no_persist: bool,
    limit: int | None,
    open_after: bool,
    profile: str,
) -> None:
    """Run the pipeline."""

    load_local_env()
    try:
        config = load_runtime_config(config_path)
        apply_mode(config, mode)
        if profile:
            _apply_search_profile(config, profile)
        print_setup_summary(config, mode)
        if normalize_mode(mode) == "api" and config.apollo.enabled:
            _print_apollo_query_preview(config)
        zip_list = [item.strip() for item in zip_codes.split(",") if item.strip()]
        leads, workbook = LeadPipeline(config).run(
            zip_codes=zip_list or None,
            state=state,
            output_path=output_path or None,
            persist=not no_persist,
            limit=limit,
        )
    except (FileNotFoundError, ValueError, RuntimeError, NotImplementedError) as exc:
        raise click.ClickException(str(exc)) from exc

    counts = {
        tier: sum(1 for lead in leads if lead.score_tier == tier)
        for tier in ("Hot", "Warm", "Cool", "Skip")
    }
    click.echo(f"Generated {len(leads)} leads")
    click.echo(f"Workbook: {workbook}")
    click.echo(f"Tiers: {counts}")

    _print_run_summary(leads, config, workbook, mode)

    if open_after:
        _open_file(Path(workbook))


@main.command("doctor")
@click.option("--config", "config_path", default="", help="Path to YAML config.")
@click.option(
    "--mode",
    default="mock",
    type=click.Choice(["mock", "sample", "api", "strict-real"], case_sensitive=False),
    show_default=True,
)
def doctor(config_path: str, mode: str) -> None:
    """Check whether the project can run locally."""

    load_local_env()
    checks: list[tuple[str, bool, str]] = []
    warnings: list[str] = []

    py_ok = sys.version_info >= (3, 10)
    checks.append(("Python 3.10+", py_ok, sys.version.split()[0]))

    for package in REQUIRED_IMPORTS:
        checks.append((f"import {package}", _can_import(package), ""))

    env_path = Path(".env")
    checks.append((".env file", env_path.exists(), "cp .env.example .env; edit .env"))

    if normalize_mode(mode) == "sample":
        for name in REQUIRED_ENV:
            checks.append((f"real-mode env {name}", True, "not required for mock/sample"))
    else:
        for name in REQUIRED_ENV:
            value = os.getenv(name, "")
            present = bool(value)
            if name == "SEC_USER_AGENT" and present and "contact@example.com" in value:
                detail = "set but still a placeholder - update to a real contact email"
            elif present:
                detail = "configured"
            else:
                detail = "not set (checked after config load)"
            checks.append((f"mode-aware env {name}", True, detail))
    for name in OPTIONAL_ENV:
        present = bool(os.getenv(name))
        checks.append((f"optional env {name}", True, "present" if present else "not set"))

    config_file = resolve_config_path(config_path)
    checks.append(
        ("config YAML", config_file.exists(), f"using {config_file}" if config_file.exists() else "")
    )

    Path("data/input").mkdir(parents=True, exist_ok=True)
    checks.append(("data/input directory", Path("data/input").exists(), ""))

    output_dir = Path("output")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_ok = output_dir.exists()
    except OSError:
        output_ok = False
    checks.append(("output directory", output_ok, str(output_dir)))

    config_loaded = False
    real_setup: list[str] = []
    sample_ok = False
    real_reports = False
    if config_file.exists():
        try:
            config = load_config(config_file)
            apply_mode(config, mode)
            config_loaded = True
            sample_config = clone_for_mode(config, "sample")
            real_setup = setup_blockers(config, mode)
            warnings.extend(setup_warnings(config, mode))
            sample_ok = _mock_pipeline_probe(sample_config)
            real_reports = bool(real_setup or warnings or UNIMPLEMENTED_REAL_INTEGRATIONS)
            checks.append(("Apollo api_search connectivity", True, _apollo_doctor_detail(config)))
        except Exception as exc:  # Doctor should report config errors without a traceback.
            checks.append(("config loads", False, str(exc)))

    if config_loaded:
        checks.append(("config loads", True, str(config_file)))
        checks.append(("mock/sample mode can run offline", sample_ok, "uses data/sample/*.csv"))
        real_detail = "; ".join(real_setup[:2] or warnings[:2] or UNIMPLEMENTED_REAL_INTEGRATIONS[:2])
        checks.append((f"{normalize_mode(mode)} mode setup report", real_reports, real_detail))

    failed = [name for name, ok, _ in checks if not ok]
    for name, ok, detail in checks:
        marker = "OK" if ok else "MISSING"
        suffix = f" - {detail}" if detail else ""
        click.echo(f"[{marker}] {name}{suffix}")
    for warning in warnings:
        click.echo(f"[WARN] {warning}")

    if failed:
        click.echo("")
        click.echo("Doctor found setup items to fix. Mock mode can still run without paid APIs.")
        raise SystemExit(1)

    click.echo("")
    click.echo(f"Doctor passed. {normalize_mode(mode)} mode is ready enough to run.")


@main.command("smoke-test")
@click.option("--config", "config_path", default="", help="Path to YAML config.")
def smoke_test(config_path: str) -> None:
    """Run a tiny end-to-end mock pipeline and write Excel output."""

    load_local_env()
    try:
        config = load_runtime_config(config_path)
        apply_mode(config, "mock")
        config.output.output_dir = "output"
        config.pipeline.database_path = "data/processed/smoke_test.db"
        leads, workbook = LeadPipeline(config).run(persist=True)
    except (FileNotFoundError, ValueError, RuntimeError, NotImplementedError) as exc:
        raise click.ClickException(f"Smoke test failed: {exc}") from exc

    if not leads:
        raise click.ClickException("Smoke test failed: mock pipeline produced zero leads.")

    click.echo(f"Smoke test passed: generated {len(leads)} leads")
    click.echo(f"Excel file: {workbook}")


@main.command("open-latest")
@click.option("--config", "config_path", default="", help="Path to YAML config.")
def open_latest(config_path: str) -> None:
    """Open the most recently generated Excel workbook."""

    load_local_env()
    search_dirs: list[Path] = []

    # Prefer the configured output directory.
    try:
        config = load_runtime_config(config_path)
        search_dirs.append(Path(config.output.output_dir))
    except Exception:
        pass

    # Always check the common defaults as fallbacks.
    for default in ("data/output", "output"):
        p = Path(default)
        if p not in search_dirs:
            search_dirs.append(p)

    candidates: list[Path] = []
    for d in search_dirs:
        if d.is_dir():
            candidates.extend(d.glob("*.xlsx"))

    if not candidates:
        raise click.ClickException(
            "No .xlsx workbooks found in "
            + ", ".join(str(d) for d in search_dirs)
            + ". Run the pipeline first."
        )

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    click.echo(f"Opening: {latest}")
    _open_file(latest)


@main.command("prepare-reveal")
@click.option("--config", "config_path", default="", help="Path to YAML config.")
@click.option("--min-score", type=float, default=45.0, show_default=True, help="Minimum score to consider.")
@click.option("--limit", type=int, default=25, show_default=True, help="Max leads to display.")
def prepare_reveal(config_path: str, min_score: float, limit: int) -> None:
    """Show top Apollo leads worth revealing and estimate credit cost."""

    load_local_env()
    try:
        config = load_runtime_config(config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    db = LeadDatabase(config.pipeline.database_path)
    try:
        candidates = db.load_reveal_candidates(min_score=min_score)
    finally:
        db.close()

    if not candidates:
        click.echo(f"No leads with score >= {min_score:.0f} in the database.")
        click.echo("Run the pipeline first: python -m lead_pipeline run")
        return

    apollo_obfuscated = [r for r in candidates if r.get("apollo_obfuscated") and r.get("apollo_person_id")]
    non_apollo = [r for r in candidates if not r.get("apollo_person_id")]
    needs_address = [r for r in candidates if r.get("address_needed")]

    high = [r for r in apollo_obfuscated if r.get("contact_reveal_priority") == "high"]
    medium = [r for r in apollo_obfuscated if r.get("contact_reveal_priority") == "medium"]
    low = [r for r in apollo_obfuscated if r.get("contact_reveal_priority") == "low"]
    recommended = len(high) + len(medium)

    click.echo("")
    click.echo("─" * 62)
    click.echo("  Reveal Candidates  (Apollo credits required)")
    click.echo("─" * 62)
    click.echo(f"  High priority   : {len(high):>4}  (~{len(high)} credits)")
    click.echo(f"  Medium priority : {len(medium):>4}  (~{len(medium)} credits)")
    click.echo(f"  Low priority    : {len(low):>4}  (review first)")
    click.echo(f"  Non-Apollo leads: {len(non_apollo):>4}  (find contact externally)")
    click.echo(f"  Address needed  : {len(needs_address):>4}  (export to get address)")
    click.echo("")
    click.echo(f"  Recommended: reveal high + medium = ~{recommended} credits")
    click.echo("")

    to_show = (high + medium)[:limit]
    if to_show:
        click.echo("  Leads to reveal (high → medium, by score):")
        for row in to_show:
            name = row.get("name", "Unknown")
            score = float(row.get("lead_score") or 0)
            tier = row.get("score_tier", "")
            title = row.get("apollo_title", "")
            org = row.get("apollo_organization", "")
            priority = (row.get("contact_reveal_priority") or "").upper()
            status = row.get("_db_lead_status", "new")
            profile = row.get("apollo_search_profile", "")
            click.echo(f"  • [{priority}] {name}  {score:.0f} ({tier})")
            role = " @ ".join(p for p in [title, org] if p)
            if role:
                click.echo(f"      Role    : {role}")
            if profile:
                click.echo(f"      Profile : {profile}")
            click.echo(f"      Status  : {status}")
    click.echo("─" * 62)


@main.command("compare-profiles")
@click.option("--config", "config_path", default="", help="Path to YAML config.")
def compare_profiles(config_path: str) -> None:
    """Compare Apollo search profile effectiveness from the database."""

    load_local_env()
    try:
        config = load_runtime_config(config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    db = LeadDatabase(config.pipeline.database_path)
    try:
        stats = db.load_profile_stats()
    finally:
        db.close()

    if not stats:
        click.echo("No leads in the database yet.")
        click.echo("Run: python -m lead_pipeline run --profile <name>")
        return

    click.echo("")
    click.echo("─" * 70)
    click.echo("  Profile Comparison  (from database)")
    click.echo(f"  {'Profile':<22} {'Total':>5} {'Avg':>6}  {'Hot':>4} {'Warm':>4} {'Cool':>4} {'Skip':>4}  {'Hot%':>5}")
    click.echo("─" * 70)
    for row in stats:
        total = row["total"] or 0
        hot_pct = f"{row['hot'] / total * 100:.0f}%" if total > 0 else "—"
        click.echo(
            f"  {row['profile']:<22} {total:>5} {row['avg_score']:>6.1f}"
            f"  {row['hot']:>4} {row['warm']:>4} {row['cool']:>4} {row['skip_count']:>4}"
            f"  {hot_pct:>5}"
        )
    click.echo("─" * 70)
    click.echo("  Tip: python -m lead_pipeline run --profile <name>  to populate a profile.")
    click.echo("")


@main.command("import-feedback")
@click.argument("csv_path", type=click.Path(exists=True))
@click.option("--config", "config_path", default="", help="Path to YAML config.")
@click.option("--dry-run", is_flag=True, help="Preview without writing to the database.")
def import_feedback(csv_path: str, config_path: str, dry_run: bool) -> None:
    """Import lead status updates from a CSV file.

    \b
    Required CSV columns : name, status
    Optional CSV columns : property_address, notes
    Valid status values  : new, revealed, contacted, skipped, converted, do_not_contact
    """
    import csv as _csv

    load_local_env()
    try:
        config = load_runtime_config(config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    rows: list[dict] = []
    parse_errors: list[str] = []

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = _csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            status = (row.get("status") or "").strip().lower()
            if not name:
                parse_errors.append(f"Row {i}: missing 'name'")
                continue
            if not status:
                parse_errors.append(f"Row {i}: missing 'status' for '{name}'")
                continue
            if status not in VALID_STATUSES:
                parse_errors.append(
                    f"Row {i}: invalid status '{status}' for '{name}' "
                    f"— valid: {', '.join(sorted(VALID_STATUSES))}"
                )
                continue
            rows.append(row)

    if parse_errors:
        click.echo("Validation errors:")
        for err in parse_errors:
            click.echo(f"  {err}")

    if not rows:
        raise click.ClickException("No valid rows to import.")

    click.echo(f"Found {len(rows)} valid feedback row(s).")

    if dry_run:
        click.echo("[dry-run] No changes written. Preview:")
        for row in rows[:10]:
            click.echo(f"  {row.get('name')} → {row.get('status')}"
                       + (f"  ({row.get('notes')})" if row.get("notes") else ""))
        if len(rows) > 10:
            click.echo(f"  … and {len(rows) - 10} more")
        return

    db = LeadDatabase(config.pipeline.database_path)
    try:
        updated, not_found = db.import_feedback(rows)
    finally:
        db.close()

    click.echo(f"Updated : {updated} lead(s)")
    if not_found:
        click.echo(f"Not found: {not_found} row(s) — run the pipeline first to populate the database")


def load_local_env() -> None:
    """Load .env without overriding already-exported values."""

    load_dotenv(dotenv_path=".env", override=False)


def resolve_config_path(config_path: str = "") -> Path:
    if config_path:
        return Path(config_path)
    if DEFAULT_CONFIG.exists():
        return DEFAULT_CONFIG
    return FALLBACK_CONFIG


def load_runtime_config(config_path: str = "") -> Config:
    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            "No config file found. Copy config/config.example.yaml to config/config.yaml."
        )
    return load_config(path)


def normalize_mode(mode: str) -> str:
    normalized = mode.lower()
    if normalized in {"mock", "sample"}:
        return "sample"
    if normalized in {"api", "strict-real"}:
        return normalized
    raise ValueError(f"Unknown run mode: {mode}")


def apply_mode(config: Config, mode: str) -> None:
    normalized = normalize_mode(mode)
    config.sources.mode = "sample" if normalized == "sample" else "api"


def clone_for_mode(config: Config, mode: str) -> Config:
    cloned = deepcopy(config)
    cloned.sources.mode = mode
    return cloned


def setup_blockers(config: Config, mode: str) -> list[str]:
    normalized = normalize_mode(mode)
    if normalized == "sample":
        return []
    if normalized == "api":
        return missing_api_mode_setup(config)
    missing = missing_real_data_setup(config)
    if config.apollo.enabled and not config.api_keys.apollo:
        missing.append("Apollo API key: set api_keys.apollo or APOLLO_API_KEY")
    return missing


def setup_warnings(config: Config, mode: str) -> list[str]:
    normalized = normalize_mode(mode)
    if normalized == "api":
        return optional_api_mode_warnings(config)
    if normalized == "sample":
        return missing_real_data_setup(config)
    return []


def print_setup_summary(config: Config, mode: str) -> None:
    normalized = normalize_mode(mode)
    missing = setup_blockers(config, normalized)
    warnings = setup_warnings(config, normalized)
    if normalized == "sample":
        click.echo("Mock/sample mode active: no external API credentials are required.")
        if warnings:
            click.echo("Real-data setup still missing:")
            for item in warnings:
                click.echo(f"  - {item}")
    elif missing:
        details = "\n".join(f"  - {item}" for item in missing)
        raise RuntimeError(f"{normalized} mode is not fully configured:\n{details}")
    else:
        click.echo(f"{normalized} mode active: using configured APIs and fallbacks.")
        for warning in warnings:
            click.echo(f"Warning: {warning}")
        if normalized == "api" and any("SEC EDGAR User-Agent" in warning for warning in warnings):
            config.sec.enabled = False
            click.echo("SEC enrichment disabled: update SEC_USER_AGENT to a real contact email to enable it.")


def _can_import(package: str) -> bool:
    try:
        importlib.import_module(package)
    except ImportError:
        return False
    return True


def _mock_pipeline_probe(config: Config) -> bool:
    sample_paths = (
        config.sources.sample_properties,
        config.sources.sample_business_entities,
        config.sources.sample_sec_matches,
        config.sources.sample_contacts,
    )
    if not all(Path(path).exists() for path in sample_paths):
        return False

    with TemporaryDirectory() as tmp:
        probe = deepcopy(config)
        probe.sources.mode = "sample"
        probe.output.output_dir = str(Path(tmp) / "output")
        probe.pipeline.database_path = str(Path(tmp) / "prospects.db")
        leads, workbook = LeadPipeline(probe).run(persist=True)
        return bool(leads) and Path(workbook).exists()


def _apply_search_profile(config: "Config", profile_name: str) -> None:
    """Overlay a built-in search profile onto the apollo config section."""
    from lead_pipeline.utils.profiles import get_profile, list_profiles

    try:
        get_profile(profile_name)  # validate before mutating config
    except ValueError:
        available = ", ".join(list_profiles())
        raise click.BadParameter(
            f"Unknown profile '{profile_name}'. Available: {available}",
            param_hint="--profile",
        )
    config.apollo.active_profile = profile_name


def _print_apollo_query_preview(config: "Config") -> None:
    """Print Apollo search parameters before the run starts."""
    from lead_pipeline.enrichment.apollo import _build_employee_ranges
    from lead_pipeline.utils.profiles import get_profile

    apollo = config.apollo
    click.echo("")
    click.echo("─" * 56)
    click.echo("  Apollo Search Parameters")
    click.echo("─" * 56)

    # Active profile overrides title/emp display.
    if apollo.active_profile:
        try:
            prof = get_profile(apollo.active_profile)
            click.echo(f"  Profile            : {prof.name} — {prof.description}")
            click.echo(f"  Titles (profile)   : {', '.join(prof.person_titles[:6])}" +
                       (" …" if len(prof.person_titles) > 6 else ""))
            if prof.employee_count_max:
                ranges = _build_employee_ranges(prof.employee_count_min, prof.employee_count_max)
                click.echo(f"  Employee range     : {prof.employee_count_min}–{prof.employee_count_max} → {', '.join(ranges)}")
        except ValueError:
            click.echo(f"  Profile            : {apollo.active_profile} (unknown — will use base filters)")
    else:
        # Show rotation variants or base titles.
        if apollo.search_rotation:
            names = [v.get("name", f"variant-{i}") for i, v in enumerate(apollo.search_rotation)]
            click.echo(f"  Search rotation    : {len(apollo.search_rotation)} variants — {', '.join(names)}")
            click.echo("                       (one selected randomly each run)")
        else:
            titles = (apollo.filters or {}).get("person_titles") or []
            if titles:
                click.echo(f"  Included titles    : {', '.join(titles[:6])}" + (" …" if len(titles) > 6 else ""))

        emp_min = apollo.employee_count_min or 0
        emp_max = apollo.employee_count_max or 0
        if emp_min or emp_max:
            ranges = _build_employee_ranges(emp_min, emp_max)
            click.echo(f"  Employee range     : {emp_min or 'any'}–{emp_max or 'any'} → {', '.join(ranges)}")

    if apollo.excluded_organizations:
        n = len(apollo.excluded_organizations)
        sample = ", ".join(apollo.excluded_organizations[:5])
        more = f" (+{n - 5} more)" if n > 5 else ""
        click.echo(f"  Excluded orgs      : {sample}{more}")

    page_info = (
        f"random 1–{apollo.random_page_offset_max}" if apollo.random_page_offset_max > 1
        else "1"
    )
    click.echo(f"  Pages              : start={page_info}, max={apollo.max_pages}, per_page={apollo.per_page}")

    cooldown = apollo.seen_ids_cooldown_days
    click.echo(f"  Seen-ID cooldown   : {cooldown} days" if cooldown > 0 else "  Seen-ID cooldown   : suppress forever")
    click.echo("─" * 56)
    click.echo("")


def _print_run_summary(leads: list, config: "Config", workbook: str, mode: str = "mock") -> None:
    """Print a run summary with tier breakdown, contact quality, and reveal-credit estimate."""
    from collections import Counter

    is_api = normalize_mode(mode) == "api"
    click.echo("")
    click.echo("═" * 60)
    click.echo("  Run Summary")
    click.echo("═" * 60)

    # --- Tier breakdown ---
    tier_counts: Counter = Counter(lead.score_tier for lead in leads)
    click.echo(f"  Total leads  : {len(leads)}")
    for tier in ("Hot", "Warm", "Cool", "Skip"):
        click.echo(f"    {tier:<8}: {tier_counts.get(tier, 0)}")

    # --- Contact quality ---
    quality_counts: Counter = Counter(lead.contact_quality for lead in leads)
    click.echo("")
    click.echo("  Contact quality:")
    click.echo(f"    Full        : {quality_counts.get('full', 0)}  (email + phone ready)")
    click.echo(f"    Partial     : {quality_counts.get('partial', 0)}  (one channel or flags only)")
    click.echo(f"    None        : {quality_counts.get('none', 0)}  (no contact info)")

    # --- Reveal credit estimate ---
    high_rev = [l for l in leads if l.contact_reveal_priority == "high"]
    med_rev = [l for l in leads if l.contact_reveal_priority == "medium"]
    low_rev = [l for l in leads if l.contact_reveal_priority == "low"]
    recommended_credits = len(high_rev) + len(med_rev)
    click.echo("")
    click.echo("  Apollo reveal (credits):")
    click.echo(f"    High        : {len(high_rev)}  (reveal now)")
    click.echo(f"    Medium      : {len(med_rev)}  (review, then reveal)")
    click.echo(f"    Low         : {len(low_rev)}  (skip or research first)")
    click.echo(f"    Recommended : ~{recommended_credits} credits  (high + medium)")

    # --- Address / lookup status ---
    addr_needed = sum(1 for l in leads if l.address_needed)
    if addr_needed:
        click.echo("")
        click.echo(f"  Address needed  : {addr_needed} lead(s) — export to get address for ATTOM lookup")

    # --- API-mode extras ---
    if is_api:
        apollo_count = sum(1 for l in leads if l.apollo_person_id)
        recycled = sum(1 for l in leads if "apollo_recycled" in (l.source_notes or ""))
        if apollo_count:
            fresh = apollo_count - recycled
            detail = f"{fresh} fresh" + (f", {recycled} recycled" if recycled else "")
            click.echo("")
            click.echo(f"  Apollo leads    : {apollo_count} ({detail})")

        if config.apollo.active_profile:
            click.echo(f"  Profile used    : {config.apollo.active_profile}")

        prop_enriched = sum(1 for l in leads if l.property_match_confidence > 0)
        if config.api_keys.attom:
            click.echo(f"  ATTOM matches   : {prop_enriched}")

    # --- Top leads preview ---
    top = sorted(leads, key=lambda l: l.lead_score, reverse=True)[:5]
    if top:
        click.echo("")
        click.echo("  Top leads:")
        for lead in top:
            score_info = f"{lead.lead_score:.0f} ({lead.score_tier})"
            role_parts = [p for p in (lead.apollo_title, lead.apollo_organization) if p]
            role = " @ ".join(role_parts) if role_parts else ""
            click.echo(f"  • {lead.name or 'Unknown'}  {score_info}")
            if role:
                click.echo(f"      Role    : {role}")
            click.echo(f"      Action  : {lead.next_action}")
            click.echo(f"      Contact : {lead.contact_quality} / reveal={lead.contact_reveal_priority}")

    click.echo("")
    click.echo(f"  Workbook : {workbook}")
    if recommended_credits:
        click.echo(f"  Next     : python -m lead_pipeline prepare-reveal")
    click.echo("═" * 60)


def _open_file(path: Path) -> None:
    """Open a file with the OS default application."""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
    except Exception as exc:
        click.echo(f"Could not open file automatically: {exc}")
        click.echo(f"Open manually: {path}")


def _apollo_doctor_detail(config: Config) -> str:
    if not config.api_keys.apollo:
        return "not checked; APOLLO_API_KEY not set"
    probe = deepcopy(config)
    probe.apollo.enabled = True
    probe.apollo.per_page = 1
    probe.apollo.max_pages = 1
    probe.apollo.reveal_contacts = False
    try:
        ok, obfuscated, message = ApolloClient(probe).search_probe()
    except Exception as exc:
        return f"check failed without crashing: {exc}"
    if not ok:
        return f"check failed: {message}"
    obfuscation = "returned obfuscated fields" if obfuscated else "no obfuscation detected"
    return (
        f"{message}; {obfuscation}; contact reveal may require additional "
        "Apollo permissions or credits"
    )
