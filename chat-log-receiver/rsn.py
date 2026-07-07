def normalize_string(s: str) -> str:
    if not s:
        return ""
    return s.lower().replace(" ", "").replace("_", "").replace("-", "").replace(".", "")
