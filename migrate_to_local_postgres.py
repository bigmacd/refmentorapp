#!/usr/bin/env python3


# Use default filename: cockroachdb_backup.sql
python migrate_to_local_postgres.py

# Or specify a custom filename:
export BACKUP_FILE="my_backup_2024.sql"
python migrate_to_local_postgres.py

# Using psql or CockroachDB SQL client
psql <your_cockroachdb_connection_string> < cockroachdb_backup.sql

# Or with CockroachDB CLI:
cockroach sql --url <connection_string> < cockroachdb_backup.sql


"""
Script to migrate data from the source database (CockroachDB) to a local PostgreSQL database.
"""

import os
import psycopg
from typing import List, Tuple, Any
from datetime import datetime, date


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

    def create_schema(self):
        """Create all tables in the target database if they don't exist."""
        print("\nCreating schema in target database...")

        # Check and create referees table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'referees'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating referees table...")
            self.target_cursor.execute("""
                CREATE TABLE referees (
                    id BIGSERIAL PRIMARY KEY,
                    lastname TEXT NOT NULL,
                    firstname TEXT NOT NULL,
                    year_certified INTEGER
                )
            """)

        # Check and create mentors table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'mentors'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating mentors table...")
            self.target_cursor.execute("""
                CREATE TABLE mentors (
                    id BIGSERIAL PRIMARY KEY,
                    mentor_last_name TEXT NOT NULL,
                    mentor_first_name TEXT NOT NULL
                )
            """)

        # Check and create mentor_sessions table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'mentor_sessions'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating mentor_sessions table...")
            self.target_cursor.execute("""
                CREATE TABLE mentor_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    mentor BIGINT NOT NULL,
                    mentee BIGINT NOT NULL,
                    position TEXT NOT NULL,
                    date TIMESTAMP NOT NULL,
                    comments TEXT NOT NULL,
                    gameid TEXT
                )
            """)

        # Check and create risky table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'risky'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating risky table...")
            self.target_cursor.execute("""
                CREATE TABLE risky (
                    id BIGSERIAL PRIMARY KEY,
                    mentee BIGINT NOT NULL,
                    mentor_session BIGINT NOT NULL,
                    date TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
        else:
            # Check if columns have wrong type (BIGSERIAL instead of BIGINT) and fix them
            self.target_cursor.execute("""
                SELECT data_type, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'risky' AND column_name = 'mentee'
            """)
            result = self.target_cursor.fetchone()
            # If mentee has a default (sequence), it's BIGSERIAL and needs to be fixed
            if result and result[1] and 'nextval' in str(result[1]):
                print("  Fixing risky table schema (mentee/mentor_session should be BIGINT, not BIGSERIAL)...")
                self.target_cursor.execute("DROP TABLE IF EXISTS risky CASCADE")
                self.target_cursor.execute("""
                    CREATE TABLE risky (
                        id BIGSERIAL PRIMARY KEY,
                        mentee BIGINT NOT NULL,
                        mentor_session BIGINT NOT NULL,
                        date TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)

        # Check and create gamedetails table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'gamedetails'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating gamedetails table...")
            self.target_cursor.execute("""
                CREATE TABLE gamedetails (
                    id BIGSERIAL PRIMARY KEY,
                    venue TEXT NOT NULL,
                    gameId TEXT NOT NULL,
                    center TEXT NOT NULL,
                    ar1 TEXT NOT NULL,
                    ar2 TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    age TEXT NOT NULL,
                    level TEXT NOT NULL
                )
            """)

        # Check and create visitors table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'visitors'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating visitors table...")
            self.target_cursor.execute("""
                CREATE TABLE visitors (
                    id BIGSERIAL PRIMARY KEY,
                    email TEXT NOT NULL,
                    date TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

        # Check and create users table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'users'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating users table...")
            self.target_cursor.execute("""
                CREATE TABLE users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_login TIMESTAMP
                )
            """)

        # Check and create password_reset_tokens table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'password_reset_tokens'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating password_reset_tokens table...")
            self.target_cursor.execute("""
                CREATE TABLE password_reset_tokens (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    used BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)

        # Check and create logs table
        self.target_cursor.execute("""
            SELECT count(table_name) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name = 'logs'
        """)
        if not self.target_cursor.fetchone()[0] == 1:
            print("  Creating logs table...")
            self.target_cursor.execute("""
                CREATE TABLE logs (
                    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                    message TEXT NOT NULL
                )
            """)

        self.target_conn.commit()
        print("Schema creation complete.\n")

    def read_table_data(self, table_name: str, noId = False) -> List[Tuple]:
        """Read all data from a source table."""
        query = f"SELECT * FROM {table_name}"
        if noId is False:
            query += " ORDER BY id"
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
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, bool):
            return 'TRUE' if value else 'FALSE'
        elif isinstance(value, datetime):
            # Format timestamp for SQL (CockroachDB/PostgreSQL compatible)
            # ISO format is automatically recognized
            return f"'{value.isoformat()}'"
        elif isinstance(value, date):
            # Format date for SQL
            return f"'{value.isoformat()}'"
        elif isinstance(value, bytes):
            # Handle binary data (hex format for PostgreSQL/CockroachDB)
            return f"'\\x{value.hex()}'"
        else:
            # Escape single quotes and backslashes in strings
            escaped = str(value).replace("\\", "\\\\").replace("'", "''")
            return f"'{escaped}'"

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
        if table_name == 'logs':
            if self.backup_fp:
                self.backup_fp.write(f"\n-- Table: {table_name} (skipped - not needed)\n")
            return

        try:
            # Get column names
            columns = self.get_table_columns(table_name)
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))

            # Read data from source
            if table_name == "logs":
                data = self.read_table_data(table_name, True)
            else:
                data = self.read_table_data(table_name)

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

            if preserve_ids and 'id' in columns:
                # Preserve IDs by inserting with explicit ID values
                # Need to reset the sequence after inserting
                insert_sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

                # Insert data with IDs
                for row in data:
                    self.target_cursor.execute(insert_sql, row)
                    # Write to backup file
                    self.write_backup_insert(table_name, columns, row)

                # Reset the sequence to the max ID
                id_index = columns.index('id')
                max_id = max(row[id_index] for row in data if row[id_index] is not None)
                if max_id:
                    self.target_cursor.execute(f"SELECT setval('{table_name}_id_seq', {max_id}, true)")
                    # Write sequence reset to backup file
                    if self.backup_fp:
                        self.backup_fp.write(f"SELECT setval('{table_name}_id_seq', {max_id}, true);\n")

                print(f"  Migrated {len(data)} rows (preserving IDs)")
            else:
                # Insert without preserving IDs (for tables without id or logs table)
                insert_sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
                for row in data:
                    self.target_cursor.execute(insert_sql, row)
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

        # Migrate tables in order, respecting foreign key dependencies
        # Tables with no dependencies first
        self.migrate_table('referees')
        self.migrate_table('mentors')
        self.migrate_table('gamedetails')
        self.migrate_table('visitors')
        self.migrate_table('users')

        # Tables that depend on referees and mentors
        self.migrate_table('mentor_sessions')
        self.migrate_table('risky')

        # Tables that depend on users
        self.migrate_table('password_reset_tokens')

        # Logs table (no dependencies)
        self.migrate_table('logs', preserve_ids=False)  # logs doesn't have an id column

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

