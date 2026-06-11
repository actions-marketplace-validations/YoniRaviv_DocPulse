def send(message, recipient, urgent=False):
    """Send a message to a recipient."""
    prefix = "[URGENT] " if urgent else ""
    return f"to {recipient}: {prefix}{message}"
