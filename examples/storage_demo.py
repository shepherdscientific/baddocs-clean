#!/usr/bin/env python3
"""Storage Demo - Example usage of BadDocs storage."""

from baddocs.storage import get_session
from baddocs.storage.models import Repository

if __name__ == '__main__':
    session = get_session()
    print('Connected to database')
