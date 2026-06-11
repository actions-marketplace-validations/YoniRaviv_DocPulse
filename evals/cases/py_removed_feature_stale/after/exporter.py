def export(data, fmt="json"):
    """Export data in the given format.

    Args:
        data: The dataset to export.
        fmt: Output format. One of "json" or "csv". Defaults to "json".
    """
    if fmt == "json":
        return _to_json(data)
    elif fmt == "csv":
        return _to_csv(data)
    else:
        raise ValueError(f"Unknown format: {fmt}")
