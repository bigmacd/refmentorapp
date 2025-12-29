import psycopg
from psycopg.extras import execute_values

# CockroachDB Cloud connection parameters
cockroach_conn_params = {
    "dbname": "defaultdb",
    "user": "martin-refmentor-ui-support",
    "password": "QKBvf2BypDni6zTqEyvSZQ",
    "host": "refmentor-roach-2992.g8z.cockroachlabs.cloud",
    "port": 26257,
    "sslmode": "true",
    "sslrootcert": "/path/to/cockroachdb-ca.cert"  # download from CockroachDB Cloud UI
}


# Local PostgreSQL connection parameters
local_pg_conn_params = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "docker",
    "host": "localhost",
    "port": 5432
}

def fetch_data_from_cockroach(query):
    with psycopg.connect(**cockroach_conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def insert_data_to_postgres(table_name, columns, data):
    with psycopg.connect(**local_pg_conn_params) as conn:
        with conn.cursor() as cur:
            # Construct insert query with placeholders
            cols_str = ', '.join(columns)
            placeholders = ', '.join([f'%s' for _ in columns])
            insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES %s"

            # Use execute_values for efficient bulk insert
            execute_values(cur, insert_query, data)
            conn.commit()


def main():
    # Example: fetch all rows from table 'users' in CockroachDB
    select_query = "SELECT id, name, email FROM users"

    data = fetch_data_from_cockroach(select_query)

    # Define destination local table and columns matching CockroachDB result
    dest_table = "users"
    dest_columns = ["id", "name", "email"]

    insert_data_to_postgres(dest_table, dest_columns, data)

    print(f"Transferred {len(data)} records from CockroachDB to PostgreSQL.")


if __name__ == "__main__":
    main()
