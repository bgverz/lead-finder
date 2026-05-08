"""Lead deduplication helpers."""

from __future__ import annotations

from collections import defaultdict

from lead_pipeline.models import Lead


def deduplicate_leads(leads: list[Lead], fields: list[str]) -> list[Lead]:
    """Deduplicate leads and merge useful signals onto the strongest record."""

    grouped: dict[tuple, list[Lead]] = defaultdict(list)
    for lead in leads:
        key = tuple(_normalize(getattr(lead, field, "")) for field in fields)
        grouped[key].append(lead)

    merged: list[Lead] = []
    for group in grouped.values():
        group.sort(key=lambda lead: lead.property_value, reverse=True)
        primary = group[0]
        primary.property_count = max(primary.property_count, len(group))
        for duplicate in group[1:]:
            primary.property_value = max(primary.property_value, duplicate.property_value)
            primary.business_entities.extend(
                entity
                for entity in duplicate.business_entities
                if entity.name not in {existing.name for existing in primary.business_entities}
            )
            primary.sec_match = primary.sec_match or duplicate.sec_match
            primary.sec_details.extend(duplicate.sec_details)
            primary.recency_signal = primary.recency_signal or duplicate.recency_signal
            notes = [primary.source_notes, duplicate.source_notes]
            primary.source_notes = "; ".join(note for note in notes if note)
        merged.append(primary)

    return sorted(merged, key=lambda lead: lead.property_value, reverse=True)


def _normalize(value: object) -> str:
    return " ".join(str(value or "").lower().replace(".", "").split())
