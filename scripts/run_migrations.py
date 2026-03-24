#!/usr/bin/env python3
"""Run database migrations."""

from baddocs.storage.migrations import MigrationManager
from baddocs.storage.connection import get_session

def main():
    session = get_session()
    manager = MigrationManager(session)
    manager.migrate()
    print('Migrations completed')

if __name__ == '__main__':
    main()
