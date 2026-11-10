#!/usr/bin/env python3


# Use default filename: cockroachdb_backup.sql
# python migrate_to_local_postgres.py

# Or specify a custom filename:
#export BACKUP_FILE="my_backup_2024.sql"
# python migrate_to_local_postgres.py


"""
Script to migrate data from the source database (CockroachDB) to a local PostgreSQL database.
"""

import json
import os
import uuid
import psycopg
from psycopg.types.json import Json
from typing import List, Tuple, Any
from datetime import datetime, date, time


class DatabaseMigrator:
    def __init__(self, source_db_url: str, target_db_url: str, backup_file: str = None):
        """
        Initialize the migrator with source and target database URLs.

        Args:
            source_db_url: Connection string for the source database
            target_db_url: Connection string for the local PostgreSQL database
                          Example: 'postgresql://username:password@localhost:5432/dbname'
            backup_file: Optional path to write SQL backup file for restoring CockroachDB
        """
        self.source_db_url = source_db_url
        self.target_db_url = target_db_url
        self.backup_file = backup_file
        self.source_conn = None
        self.target_conn = None
        self.backup_fp = None
        if backup_file:
            self.backup_fp = open(backup_file, 'w', encoding='utf-8')
            self.backup_fp.write("-- SQL Backup file for CockroachDB restore\n")
            self.backup_fp.write(f"-- Generated on {datetime.now().isoformat()}\n\n")
            self.backup_fp.write("BEGIN;\n\n")

    def connect(self):
        """Connect to both source and target databases."""
        print("Connecting to source database...")
        self.source_conn = psycopg.connect(self.source_db_url)
        self.source_conn.autocommit = True
        self.source_cursor = self.source_conn.cursor()

        print("Connecting to target database...")
        self.target_conn = psycopg.connect(self.target_db_url)
        self.target_conn.autocommit = True
        self.target_cursor = self.target_conn.cursor()

    def close(self):
        """Close database connections and backup file."""
        if self.source_conn:
            self.source_conn.close()
        if self.target_conn:
            self.target_conn.close()
        if self.backup_fp:
            self.backup_fp.write("\nCOMMIT;\n")
            self.backup_fp.close()
            if self.backup_file:
                print(f"\nBackup file written to: {self.backup_file}")

    # App tables, parents before children. Rebuilt on each run so a previous
    # local schema (missing organization_id, rowid, and so on) cannot reject new rows.
    # Cockroach userfile tables (userfiles_$...) are internal upload storage and are omitted.
    TABLE_DDL = (
        (
            'organizations',
            """
            CREATE TABLE organizations (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                slug TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
        ),
        (
            'users',
            """
            CREATE TABLE users (
                id BIGSERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_login TIMESTAMP,
                first_name TEXT,
                last_name TEXT,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                avatar_jpeg BYTEA
            )
            """,
        ),
        (
            'user_organizations',
            """
            CREATE TABLE user_organizations (
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, organization_id)
            )
            """,
        ),
        (
            'old_mentors',
            """
            CREATE TABLE old_mentors (
                id BIGSERIAL PRIMARY KEY,
                mentor_last_name TEXT NOT NULL,
                mentor_first_name TEXT NOT NULL
            )
            """,
        ),
        (
            'referees',
            """
            CREATE TABLE referees (
                id BIGSERIAL PRIMARY KEY,
                lastname TEXT NOT NULL,
                firstname TEXT NOT NULL,
                year_certified BIGINT,
                organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
            )
            """,
        ),
        (
            'gamedetails',
            """
            CREATE TABLE gamedetails (
                id BIGSERIAL PRIMARY KEY,
                venue TEXT NOT NULL,
                gameid TEXT NOT NULL,
                center TEXT NOT NULL,
                ar1 TEXT NOT NULL,
                ar2 TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                age TEXT NOT NULL,
                level TEXT NOT NULL,
                organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
            )
            """,
        ),
        (
            'mentor_sessions',
            """
            CREATE TABLE mentor_sessions (
                id BIGSERIAL PRIMARY KEY,
                mentor BIGINT NOT NULL,
                mentee BIGINT NOT NULL,
                position TEXT NOT NULL,
                date TIMESTAMP NOT NULL,
                comments TEXT NOT NULL,
                gameid TEXT
            )
            """,
        ),
        (
            'risky',
            """
            CREATE TABLE risky (
                id BIGSERIAL PRIMARY KEY,
                mentee BIGINT NOT NULL,
                mentor_session BIGINT NOT NULL,
                date TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
        ),
        (
            'mentor_game_selections',
            """
            CREATE TABLE mentor_game_selections (
                id BIGSERIAL PRIMARY KEY,
                mentor_id BIGINT NOT NULL REFERENCES users(id),
                game_date TEXT NOT NULL,
                venue TEXT NOT NULL,
                game_id TEXT NOT NULL,
                selected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                UNIQUE (organization_id, mentor_id, game_date, venue, game_id)
            )
            """,
        ),
        (
            'calendar_events',
            """
            CREATE TABLE calendar_events (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                start_date DATE NOT NULL,
                end_date DATE,
                start_time TIME,
                end_time TIME,
                created_by TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
        ),
        (
            'user_visits',
            """
            CREATE TABLE user_visits (
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                email TEXT NOT NULL,
                date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ip_address TEXT,
                user_agent TEXT,
                rowid BIGSERIAL PRIMARY KEY
            )
            """,
        ),
        (
            'password_reset_tokens',
            """
            CREATE TABLE password_reset_tokens (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                used BOOLEAN NOT NULL DEFAULT FALSE
            )
            """,
        ),
        (
            'logs',
            """
            CREATE TABLE logs (
                timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                message TEXT NOT NULL,
                rowid BIGSERIAL PRIMARY KEY
            )
            """,
        ),
        (
            'support_inquiries',
            """
            CREATE TABLE support_inquiries (
                id BIGSERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                reason TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ),
        (
            'mentormapping',
            """
            CREATE TABLE mentormapping (
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                rowid BIGSERIAL PRIMARY KEY
            )
            """,
        ),
    )

    def create_schema(self):
        """Replace local app tables so their columns match the source database."""
        print("\nCreating schema in target database...")
        table_names = ', '.join(name for name, _sql in reversed(self.TABLE_DDL))
        self.target_cursor.execute(f"DROP TABLE IF EXISTS {table_names} CASCADE")

        for name, ddl in self.TABLE_DDL:
            print(f"  Creating {name}...")
            self.target_cursor.execute(ddl)

        self.target_cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS gamedetails_one_per_org_game
            ON gamedetails (organization_id, gameid)
        """)
        self.target_cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mentor_game_selections_one_mentor_per_game
            ON mentor_game_selections (organization_id, game_date, venue, game_id)
        """)

        self.target_conn.commit()
        print("Schema creation complete.\n")

    def read_table_data(self, table_name: str, columns: List[str]) -> List[Tuple]:
        """Read all data from a source table."""
        if 'id' in columns:
            order_col = 'id'
        elif 'rowid' in columns:
            order_col = 'rowid'
        else:
            order_col = None
        # Name the columns. Cockroach hides implicit rowid from SELECT *.
        query = f"SELECT {', '.join(columns)} FROM {table_name}"
        if order_col:
            query += f" ORDER BY {order_col}"
        self.source_cursor.execute(query)
        return self.source_cursor.fetchall()

    def get_table_columns(self, table_name: str) -> List[str]:
        """Get column names for a table."""
        self.source_cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        return [row[0] for row in self.source_cursor.fetchall()]

    def format_value_for_sql(self, value: Any) -> str:
        """Format a Python value for SQL INSERT statement."""
        if value is None:
            return 'NULL'
        elif isinstance(value, bool):
            return 'TRUE' if value else 'FALSE'
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, datetime):
            # Format timestamp for SQL (CockroachDB/PostgreSQL compatible)
            # ISO format is automatically recognized
            return f"'{value.isoformat()}'"
        elif isinstance(value, date):
            # Format date for SQL
            return f"'{value.isoformat()}'"
        elif isinstance(value, time):
            return f"'{value.isoformat()}'"
        elif isinstance(value, memoryview):
            return f"'\\x{bytes(value).hex()}'"
        elif isinstance(value, bytes):
            # Handle binary data (hex format for PostgreSQL/CockroachDB)
            return f"'\\x{value.hex()}'"
        elif isinstance(value, uuid.UUID):
            return f"'{value}'"
        elif isinstance(value, (dict, list)):
            escaped = json.dumps(value).replace("\\", "\\\\").replace("'", "''")
            return f"'{escaped}'"
        else:
            # Escape single quotes and backslashes in strings
            escaped = str(value).replace("\\", "\\\\").replace("'", "''")
            return f"'{escaped}'"

    def adapt_value(self, value: Any) -> Any:
        """Adapt a source value for a psycopg parameter."""
        if isinstance(value, memoryview):
            return bytes(value)
        if isinstance(value, (dict, list)):
            return Json(value)
        return value

    def write_backup_insert(self, table_name: str, columns: List[str], row: Tuple):
        """Write an INSERT statement to the backup file."""
        if not self.backup_fp:
            return

        columns_str = ', '.join(columns)
        values_str = ', '.join(self.format_value_for_sql(val) for val in row)
        insert_stmt = f"INSERT INTO {table_name} ({columns_str}) VALUES ({values_str});\n"
        self.backup_fp.write(insert_stmt)

    def migrate_table(self, table_name: str, preserve_ids: bool = True):
        """
        Migrate data from source to target table.

        Args:
            table_name: Name of the table to migrate
            preserve_ids: If True, preserve original IDs (requires temporarily disabling constraints)
        """
        print(f"Migrating {table_name}...")

        try:
            # Get column names
            columns = self.get_table_columns(table_name)
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))

            # Read data from source
            data = self.read_table_data(table_name, columns)

            if not data:
                print(f"  No data to migrate in {table_name}")
                if self.backup_fp:
                    self.backup_fp.write(f"\n-- Table: {table_name} (empty)\n")
                return

            # Clear existing data if any
            self.target_cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")

            # Write to backup file if enabled
            if self.backup_fp:
                self.backup_fp.write(f"\n-- Table: {table_name}\n")
                if preserve_ids and 'id' in columns:
                    self.backup_fp.write("-- Note: This table preserves IDs\n")

            pk_column = 'id' if 'id' in columns else 'rowid' if 'rowid' in columns else None
            if preserve_ids and pk_column:
                # Preserve IDs by inserting with explicit ID values
                # Need to reset the sequence after inserting
                insert_sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

                # Insert data with IDs
                for row in data:
                    self.target_cursor.execute(insert_sql, [self.adapt_value(value) for value in row])
                    # Write to backup file
                    self.write_backup_insert(table_name, columns, row)

                # Reset the sequence to the max ID. Cockroach unique_rowid() values are
                # larger than a serial sequence, so the local BIGSERIAL must be moved forward.
                pk_index = columns.index(pk_column)
                max_id = max(row[pk_index] for row in data if row[pk_index] is not None)
                if max_id:
                    self.target_cursor.execute(
                        f"SELECT setval('{table_name}_{pk_column}_seq', {max_id}, true)"
                    )
                    # Source id columns use unique_rowid(), which has no sequence to reset.
                    if self.backup_fp and pk_column == 'id':
                        self.backup_fp.write(f"SELECT setval('{table_name}_id_seq', {max_id}, true);\n")

                print(f"  Migrated {len(data)} rows (preserving IDs)")
            else:
                # Insert without preserving IDs (composite keys such as user_organizations)
                insert_sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
                for row in data:
                    self.target_cursor.execute(insert_sql, [self.adapt_value(value) for value in row])
                    # Write to backup file
                    self.write_backup_insert(table_name, columns, row)
                print(f"  Migrated {len(data)} rows")

            self.target_conn.commit()

        except Exception as e:
            print(f"  Error migrating {table_name}: {e}")
            self.target_conn.rollback()
            raise

    def migrate_all(self):
        """Migrate all tables in the correct order to preserve foreign key relationships."""
        print("\nStarting data migration...\n")

        # Parents before children so foreign keys are satisfied.
        for table_name, _ddl in self.TABLE_DDL:
            self.migrate_table(table_name)

        print("\nMigration complete!")


def main():
    """Main function to run the migration."""
    # Get source database URL from environment
    source_db_url = os.environ.get('db_url')
    if not source_db_url:
        print("Error: 'db_url' environment variable is not set.")
        print("Please set it to your source database connection string.")
        return

    # Default target database URL (local PostgreSQL)
    # You can override this with db_url_local environment variable
    target_db_url = os.environ.get('db_url_local')
    if not target_db_url:
        print("Error: 'db_url_local' environment variable is not set.")
        print("Please set it to your local PostgreSQL connection string.")
        print("Example: export db_url_local='postgresql://user:password@localhost:5432/dbname'")
        return

    # Get backup file path (optional)
    backup_file = os.environ.get('BACKUP_FILE', 'cockroachdb_backup.sql')

    print("Database Migration Script")
    print("=" * 50)
    print(f"Source DB: {source_db_url[:50]}...")  # Don't print full connection string
    print(f"Target DB: {target_db_url}")
    print(f"Backup file: {backup_file}")
    print("=" * 50)

    migrator = DatabaseMigrator(source_db_url, target_db_url, backup_file)

    try:
        migrator.connect()
        migrator.create_schema()
        migrator.migrate_all()
    except Exception as e:
        print(f"\nError during migration: {e}")
        raise
    finally:
        migrator.close()


if __name__ == '__main__':
    main()

