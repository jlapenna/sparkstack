import re


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", text.lower()).strip("_")
    return re.sub(r"_+", "_", slug) or "default_role"
