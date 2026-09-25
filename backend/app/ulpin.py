"""
3D ULPIN generation service.

Format:  <14-digit 2D ULPIN>-B##-F##-U##
Example: 20010030450231-B01-F03-U01

IMPORTANT -- honesty note (also shown in the API docs and the frontend):
The prefix follows the real government ULPIN/Bhu-Aadhaar digit structure
(state:2 + district:2 + subdistrict:3 + village:3 + plot:4 = 14 digits) so
the format is realistic, but it is a REPRESENTATIVE/SAMPLE id, not fetched
from a live DoLR system (no public API exists for that). In production
this prefix would come from DoLR's ULPIN database via an official
integration.

Every field always ends up as digits in the final ULPIN:
1. If a field is typed as pure digits (a surveyor who knows the real LGD
   code), it's zero-padded to that field's width and used as-is.
2. If a field contains letters (e.g. a real district name like "East
   Singhbhum" from address lookup, or a real Khasra/plot number like
   "123/2") -- since no free address-lookup API returns the government's
   official numeric LGD codes -- it's resolved to a numeric code via the
   `location_codes` registry table: the same name always resolves to the
   same code (first-seen assigns it, every later use of that name reuses
   it), so the final ULPIN is always the strict 14-digit numeric form.

The ID is:
- Deterministic: the same name always maps to the same numeric code, so
  the same parcel/building/floor/unit always yields the same ID
- Unique: enforced by DB unique constraints on units.ulpin_3d and
  location_codes(field_type, code)
- Searchable: indexed column
- Linked to parent parcel: via the foreign key chain unit -> floor -> building -> parcel
"""
import hashlib
import re

FIELD_WIDTHS = {
    "state": 2,
    "district": 2,
    "subdistrict": 3,
    "village": 3,
    "plot": 4,
}
FIELD_ORDER = ["state", "district", "subdistrict", "village", "plot"]


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def resolve_numeric_code(db, field_type: str, value: str) -> str:
    """
    Look up (or allocate) a deterministic numeric code for a real place name
    entered into a field that expects a government numeric code. Same name
    -> same code every time, persisted in the location_codes table.
    """
    from . import models

    width = FIELD_WIDTHS[field_type]
    normalized = _normalize_name(value)

    existing = (
        db.query(models.LocationCode)
        .filter(models.LocationCode.field_type == field_type, models.LocationCode.name_normalized == normalized)
        .first()
    )
    if existing:
        return existing.code

    max_code = 10 ** width
    digest = int(hashlib.sha256(f"{field_type}:{normalized}".encode()).hexdigest(), 16)
    start = digest % max_code
    for offset in range(max_code):
        candidate = (start + offset) % max_code
        if candidate == 0:
            continue
        code = str(candidate).zfill(width)
        taken = (
            db.query(models.LocationCode)
            .filter(models.LocationCode.field_type == field_type, models.LocationCode.code == code)
            .first()
        )
        if not taken:
            entry = models.LocationCode(
                field_type=field_type, name_normalized=normalized,
                display_name=value.strip(), code=code,
            )
            db.add(entry)
            db.flush()
            return code

    raise ValueError(f"No numeric codes left to assign for {field_type} (all {max_code - 1} in use)")


def generate_2d_ulpin(db, state_code: str, district_code: str, subdistrict_code: str,
                       village_code: str, plot_code: str) -> str:
    """Build the representative 2D ULPIN -- always the strict 14-digit
    numeric form. A field typed as pure digits is zero-padded and used
    as-is; a field typed as a real name/Khasra number is resolved to a
    persisted numeric code first (see resolve_numeric_code)."""
    parts_raw = [state_code, district_code, subdistrict_code, village_code, plot_code]
    if any(not p or not p.strip() for p in parts_raw):
        raise ValueError("State, district, sub-district, village, and plot are all required")

    resolved = []
    for field_type, value in zip(FIELD_ORDER, parts_raw):
        v = value.strip()
        width = FIELD_WIDTHS[field_type]
        if v.isdigit():
            resolved.append(v.zfill(width))
        else:
            resolved.append(resolve_numeric_code(db, field_type, v))

    ulpin = "".join(resolved)
    if len(ulpin) != 14 or not ulpin.isdigit():
        raise ValueError(f"Constructed ULPIN is not a 14-digit number: {ulpin}")
    return ulpin


def generate_3d_ulpin(ulpin_2d: str, building_code: str, floor_code: str, unit_code: str) -> str:
    """
    Compose the full 3D ULPIN. building_code/floor_code/unit_code are expected
    already formatted like 'B01', 'F03', 'U01'.
    """
    return f"{ulpin_2d}-{building_code}-{floor_code}-{unit_code}"


def format_code(prefix: str, number: int) -> str:
    return f"{prefix}{number:02d}"
