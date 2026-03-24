"""Custom Jinja2 filters."""

def truncate(value, length=50):
    """Truncate text to length."""
    if len(value) > length:
        return value[:length] + '...'
    return value

def format_code(code, language='text'):
    """Format code block."""
    return f'```{language}\n{code}\n```'
