"""Pipeline orchestration for lead generation."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from lead_pipeline.collectors.business import BusinessEntityMatcher
from lead_pipeline.collectors.census import CensusClient
from lead_pipeline.collectors.property import PropertyRecordCollector
from lead_pipeline.collectors.sec_edgar import SECEdgarMatcher
from lead_pipeline.enrichment.apollo import ApolloClient, ApolloPerson
from lead_pipeline.enrichment.attom import ATTOMClient
from lead_pipeline.enrichment.phone import PhoneValidator
from lead_pipeline.models import Lead
from lead_pipeline.output.excel import ExcelExporter
from lead_pipeline.scoring.scorer import LeadScorer
from lead_pipeline.utils.config import Config
from lead_pipeline.utils.database import LeadDatabase  # also used in _collect_apollo_candidates
from lead_pipeline.utils.dedupe import deduplicate_leads
from lead_pipeline.utils.logger import setup_logger


class LeadPipeline:
    """End-to-end lead generation pipeline."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logger("pipeline", config.pipeline.log_level)
        self.census = CensusClient(config)
        self.properties = PropertyRecordCollector(config)
        self.business = BusinessEntityMatcher(config)
        self.sec = SECEdgarMatcher(config)
        self.phone = PhoneValidator(config)
        self.apollo = ApolloClient(config)
        self.attom = ATTOMClient(config)
        self.scorer = LeadScorer(config)
        self.exporter = ExcelExporter(config)

    def run(
        self,
        zip_codes: list[str] | None = None,
        state: str = "",
        output_path: str | None = None,
        persist: bool = True,
        limit: int | None = None,
    ) -> tuple[list[Lead], str]:
        apollo_candidates = self._collect_apollo_candidates(limit=limit)
        if self.config.sources.mode == "api" and self.apollo.last_stats:
            s = self.apollo.last_stats
            recycled = sum(1 for p in apollo_candidates if getattr(p, "is_recycled", False))
            self.logger.info(
                "Apollo telemetry — raw: %d | seen-filtered: %d | "
                "title-filtered: %d | org-filtered: %d | kept: %d%s",
                s.get("raw_retrieved", 0),
                s.get("seen_filtered", 0),
                s.get("title_filtered", 0),
                s.get("org_filtered", 0),
                s.get("final_kept", len(apollo_candidates)),
                f" ({recycled} recycled)" if recycled else "",
            )

        target_areas = []
        if self.config.sources.mode == "sample" or self.config.census.enabled or zip_codes or state:
            try:
                target_areas = self.census.target_areas(zip_codes, state)
            except Exception as exc:
                if apollo_candidates or self.config.sources.mode == "api":
                    self.logger.warning(
                        "Census/geographic targeting unavailable; continuing with available leads only: %s",
                        _safe_error(exc),
                    )
                    target_areas = []
                else:
                    raise
        else:
            self.logger.warning("Census enrichment disabled; skipping geographic targeting.")
        self.logger.info("Target areas resolved: %s", len(target_areas))

        property_records = []
        try:
            property_records = self.properties.collect(target_areas)
        except (RuntimeError, NotImplementedError) as exc:
            if apollo_candidates or self.config.sources.mode == "api":
                self.logger.warning(
                    "Property collection unavailable; continuing with available leads only: %s",
                    _safe_error(exc),
                )
            else:
                raise
        self.logger.info("Property records collected: %s", len(property_records))

        leads: list[Lead] = []
        for record in property_records:
            try:
                entities = self.business.match(record.owner_name)
            except (RuntimeError, NotImplementedError) as exc:
                self.logger.warning(
                    "Business enrichment unavailable for %s; continuing: %s",
                    record.owner_name,
                    exc,
                )
                entities = []
            if self.config.sec.enabled:
                sec_match, sec_details = self.sec.match(record.owner_name)
            else:
                sec_match, sec_details = False, []
            contact = self.phone.validate_for_name(record.owner_name)
            source_notes = sorted(
                {
                    record.source,
                    *(entity.source for entity in entities),
                    *(detail.get("source", "") for detail in sec_details),
                    contact.source,
                }
            )
            leads.append(
                Lead(
                    name=record.owner_name,
                    property_value=record.property_value,
                    property_address=record.property_address,
                    city=record.city,
                    state=record.state,
                    zip_code=record.zip_code,
                    owner_type=record.owner_type,
                    purchase_date=record.purchase_date,
                    business_entities=entities,
                    sec_match=sec_match,
                    sec_details=sec_details,
                    area_income=record.area_income,
                    area_home_value=record.area_home_value,
                    phone=contact.phone,
                    phone_valid=contact.phone_valid,
                    phone_line_type=contact.phone_line_type,
                    email=contact.email,
                    source_notes="; ".join(note for note in source_notes if note),
                )
            )

        leads.extend(self._apollo_people_to_leads(apollo_candidates))

        # ── Hard country gate ────────────────────────────────────────────────
        # Drop any lead with an explicit non-US country before scoring/output.
        # This is the last-resort safety net; it catches anything that slipped
        # through the Apollo-level filters (e.g. bad Apollo data, reveal updates).
        # Leads with NO country/location data are passed through — those come
        # from Census/property sources and were already geographically targeted.
        leads = self._apply_country_gate(leads)

        deduped = deduplicate_leads(leads, self.config.pipeline.dedup_by)
        deduped = self.attom.enrich_leads(deduped)
        scored = [self.scorer.score(lead) for lead in deduped]
        scored.sort(key=lambda lead: lead.lead_score, reverse=True)
        if limit is not None:
            scored = scored[:limit]

        if persist:
            db = LeadDatabase(self.config.pipeline.database_path)
            try:
                db.apply_stored_statuses(scored)
                db.upsert_many(scored)
            finally:
                db.close()

        # Generate default output path if none provided
        if output_path is None:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.config.output.filename_prefix}_{timestamp}.xlsx"
            output_path = Path(self.config.output.output_dir) / filename
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = self.exporter.export(scored, output_path)
        self.logger.info("Excel workbook written: %s", workbook)
        return scored, str(workbook)

    def _collect_apollo_candidates(self, limit: int | None = None) -> list[ApolloPerson]:
        if self.config.sources.mode != "api" or not self.config.apollo.enabled:
            return []

        # Load previously-seen Apollo IDs for run-diversity deduplication.
        seen_ids: set[str] = set()
        if self.config.apollo.seen_ids_cooldown_days >= 0:
            try:
                db = LeadDatabase(self.config.pipeline.database_path)
                seen_ids = db.load_seen_apollo_ids(self.config.apollo.seen_ids_cooldown_days)
                db.close()
                if seen_ids:
                    self.logger.info(
                        "Apollo: suppressing %d previously-seen IDs (cooldown %d days).",
                        len(seen_ids),
                        self.config.apollo.seen_ids_cooldown_days,
                    )
            except Exception as exc:
                self.logger.warning("Could not load seen Apollo IDs: %s", exc)

        try:
            people = self.apollo.search_people(seen_ids=seen_ids)
        except Exception as exc:
            self.logger.warning("Apollo search failed; continuing without Apollo leads: %s", _safe_error(exc))
            return []

        # ----------------------------------------------------------------
        # Cooldown fallback: if fresh search returns nothing but there are
        # suppressed IDs, retry without suppression and mark as recycled.
        # ----------------------------------------------------------------
        if not people and seen_ids:
            self.logger.warning(
                "Apollo: 0 fresh candidates after suppressing %d seen IDs. "
                "Retrying without seen-ID filter (recycled candidates).",
                len(seen_ids),
            )
            try:
                people = self.apollo.search_people(seen_ids=set())
                if people:
                    for person in people:
                        person.is_recycled = True
                    self.logger.warning(
                        "Apollo cooldown fallback: surfacing %d previously-seen candidates. "
                        "Consider expanding search_rotation or increasing per_page/max_pages.",
                        len(people),
                    )
            except Exception as exc:
                self.logger.warning("Apollo fallback search failed: %s", _safe_error(exc))

        # Persist new IDs so future runs skip them (only persist non-recycled IDs).
        fresh = [p for p in people if not getattr(p, "is_recycled", False)]
        if fresh:
            try:
                db = LeadDatabase(self.config.pipeline.database_path)
                db.save_seen_apollo_ids(fresh)
                db.close()
            except Exception as exc:
                self.logger.warning("Could not save seen Apollo IDs: %s", exc)

        if self.config.apollo.reveal_contacts and self.config.apollo.max_reveals_per_run > 0:
            revealed: list[ApolloPerson] = []
            for index, person in enumerate(people):
                if index >= self.config.apollo.max_reveals_per_run:
                    revealed.append(person)
                    continue
                try:
                    revealed.append(self.apollo.reveal_contact(person))
                except Exception as exc:
                    self.logger.warning(
                        "Apollo reveal failed for person id %s; keeping search result: %s",
                        person.apollo_person_id,
                        _safe_error(exc),
                    )
                    revealed.append(person)
            people = revealed

        # Re-run geo filter after reveals — the reveal API populates country/state
        # for records that were blank in search results, surfacing non-US people.
        people = self.apollo.filter_by_country(people)

        self.logger.info("Apollo candidates collected: %s", len(people))
        if limit is not None:
            people = people[:limit]
        return people

    def _apollo_people_to_leads(self, people: list[ApolloPerson]) -> list[Lead]:
        leads: list[Lead] = []
        for person in people:
            source_notes = ["apollo_search"]
            if person.is_obfuscated:
                source_notes.append("apollo_search_obfuscated")
            if getattr(person, "is_recycled", False):
                source_notes.append("apollo_recycled")

            sec_match = False
            sec_details: list[dict] = []
            if self.config.sec.enabled and (
                person.has_full_name or (person.first_name and person.organization_name)
            ):
                search_name = person.display_name if person.has_full_name else person.organization_name
                try:
                    sec_match, sec_details = self.sec.match(search_name)
                except Exception as exc:
                    self.logger.warning(
                        "Skipping SEC enrichment for Apollo candidate %s: %s",
                        person.apollo_person_id or person.display_name,
                        _safe_error(exc),
                    )
            elif not self.config.sec.enabled:
                source_notes.append("sec_enrichment_disabled")
            else:
                source_notes.append("sec_skipped_insufficient_name")

            if sec_details:
                source_notes.extend(
                    detail.get("source", "") for detail in sec_details if detail.get("source")
                )

            phone = person.phone if person.phone and not person.is_obfuscated else ""
            phone_valid = bool(phone)
            leads.append(
                Lead(
                    name=person.display_name,
                    property_value=0,
                    property_address="",
                    city=person.city,
                    state=person.state,
                    country=getattr(person, "country", ""),
                    owner_type="apollo_person",
                    sec_match=sec_match,
                    sec_details=sec_details,
                    phone=phone,
                    phone_valid=phone_valid,
                    phone_line_type="unknown" if phone_valid else "",
                    email=person.email if person.email and not person.is_obfuscated else "",
                    source_notes="; ".join(note for note in source_notes if note),
                    apollo_person_id=person.apollo_person_id,
                    apollo_first_name=person.first_name,
                    apollo_last_name_obfuscated=person.last_name_obfuscated,
                    apollo_title=person.title,
                    apollo_organization=person.organization_name,
                    apollo_organization_address=getattr(person, "organization_address", ""),
                    apollo_industry=getattr(person, "industry", ""),
                    apollo_has_email=person.has_email,
                    apollo_has_direct_phone=person.has_direct_phone,
                    apollo_obfuscated=person.is_obfuscated,
                    apollo_search_profile=self.config.apollo.active_profile,
                )
            )
        return leads

    def _apply_country_gate(self, leads: list[Lead]) -> list[Lead]:
        """Hard gate: drop any lead with an explicit non-US country before output.

        Leads with an empty country field are passed through — they originate from
        Census/property sources that are already US-geographically targeted, or
        from Apollo records where Apollo's own server-side filter has already been
        applied and country data simply isn't stored.

        Leads with a populated non-US country field are always dropped regardless
        of which source produced them.
        """
        target_countries = self.config.targeting.countries
        if not target_countries:
            return leads

        target_codes = {c.upper() for c in target_countries if c.strip()}
        # Long-form US name variants Apollo sometimes returns.
        us_names = {
            "united states", "united states of america",
            "us", "usa", "u.s.", "u.s.a.", "u.s",
        }

        kept: list[Lead] = []
        dropped = 0
        for lead in leads:
            country = (getattr(lead, "country", "") or "").strip()
            if not country:
                kept.append(lead)  # no country data — pass through
            elif country.upper() in target_codes:
                kept.append(lead)  # explicit US
            elif "US" in target_codes and country.lower() in us_names:
                kept.append(lead)  # long-form US name
            else:
                dropped += 1
                self.logger.debug(
                    "Country gate: dropping '%s' (country=%s)", lead.name, country
                )

        if dropped:
            self.logger.warning(
                "Country hard gate: dropped %d lead(s) with explicit non-US country. "
                "Run with log_level: DEBUG to see per-lead details.",
                dropped,
            )
        return kept


def _safe_error(exc: Exception) -> str:
    """Return provider errors without leaking credentials in query strings."""

    message = str(exc)
    for token in ("key", "api_key", "apikey", "access_key"):
        message = _redact_query_param(message, token)
    return message


def _redact_query_param(message: str, param_name: str) -> str:
    marker = f"{param_name}="
    if marker not in message:
        return message
    parts = message.split()
    redacted_parts = []
    for part in parts:
        if marker not in part:
            redacted_parts.append(part)
            continue
        try:
            split = urlsplit(part)
            query = urlencode(
                [
                    (key, "REDACTED" if key.lower() == param_name else value)
                    for key, value in parse_qsl(split.query, keep_blank_values=True)
                ]
            )
            redacted_parts.append(urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment)))
        except ValueError:
            redacted_parts.append(part.replace(marker, f"{param_name}=REDACTED"))
    return " ".join(redacted_parts)
