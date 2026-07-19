# Data Model: Provider Symbol Mapping

## ProviderSymbolMapping

| Field | Meaning |
|---|---|
| `security_id` | Stable internal identity; never inferred from replacement ticker |
| `constituent_symbol` | Symbol appearing in the index source |
| `provider_id` | Stable data-provider identifier |
| `provider_symbol` | Provider-specific retrieval symbol |
| `exchange_code` | Provider/configured exchange code |
| `effective_from` | Inclusive start date |
| `effective_to` | Inclusive end date or null |
| `mapping_type` | Formatting alias, rename, share class, merger successor, acquisition successor, provider fallback, or unknown |
| `reason` | Human-readable rationale |
| `evidence_ref` | Citation or internal evidence reference |
| `approval_status` | Pending, approved, or rejected |
| `reviewer` | Reviewer identifier required for approval/rejection |
| `reviewed_at` | Review timestamp required for approval/rejection |

## Invariants

- Mapping intervals for the same constituent/provider MUST NOT overlap.
- An approved mapping MUST contain reason, evidence, reviewer, and review timestamp.
- An unknown mapping cannot be approved.
- Pending and rejected mappings are quarantined and cannot produce automated
  download symbols.
- No mapping record means direct resolution to the unchanged constituent symbol;
  provider punctuation transformations remain provider-adapter behavior.
- A successor mapping does not by itself merge price histories. The stable
  `security_id` and corporate-action policy govern lineage separately.

## Legacy migration

Legacy `dict[str, str]` substitutions are imported as pending/unknown review rows.
Identity mappings such as `INGR -> INGR` are omitted because direct resolution
already covers them. The migration report counts imported, omitted, and invalid
entries and preserves source/target values for review.

