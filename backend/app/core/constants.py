MATERIAL_CATEGORIES = (
    "metals",
    "plastics",
    "paper_cardboard",
    "wood",
    "glass",
    "textiles",
    "organics",
    "electronics",
    "chemicals",
    "other",
)

UNITS = ("kg", "tonne", "litre", "unit")

LISTING_STATUSES = ("draft", "active", "matched", "archived")

REQUIREMENT_STATUSES = ("active", "paused", "closed")

MATCH_STATUSES = ("suggested", "viewed", "interested", "dismissed", "converted")

ORGANIZATION_TYPES = ("generator", "buyer", "recycler", "both", "admin")

RECOVERY_ROUTES = (
    "reuse",
    "recycle",
    "compost",
    "energy_recovery",
    "landfill",
    "other",
)

VERIFICATION_STATUSES = ("unverified", "verified")

ROLES = ("generator", "buyer", "admin")

REGULATION_ITEM_TYPES = ("regulation", "news")

SUPPORTED_JURISDICTIONS = ("IN", "US", "EU", "GLOBAL")

SUPPORTED_TOPICS = (
    "waste-management",
    "hazardous-waste",
    "plastics",
    "e-waste",
    "epr",
    "recycling",
    "reporting",
    "circular-economy",
)

SUMMARY_KINDS = ("source_excerpt", "ai_generated")
