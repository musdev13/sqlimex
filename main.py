import os
import json
import sys
import pyodbc
import argparse
import re
import datetime


def load_config():
    config_dir = os.path.expanduser("~/.config/sqlimex")
    config_path = os.path.join(config_dir, "config.json")

    if not os.path.exists(config_dir):
        os.makedirs(config_dir)

    if not os.path.exists(config_path):
        empty = {
            "server": "",
            "username": "",
            "password": ""
        }
        with open(config_path, "w") as f:
            json.dump(empty, f, indent=4)

        print("⚠️ Created config: ~/.config/sqlimex/config.json")
        print("💛 Please fill in server, username, password.")
        sys.exit(1)

    with open(config_path, "r") as f:
        cfg = json.load(f)

    if (not cfg.get("server") or
        not cfg.get("username") or
        not cfg.get("password")):

        print("⚠️ Config is incomplete. Fill in all fields:")
        print("~/.config/sqlimex/config.json")
        sys.exit(1)

    return cfg



def import_sql_file(server, username, password, database, sql_file):
    print(f"📥 Importing SQL into database '{database}'...")

    # Create DB if needed
    conn_master = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=no;",
        autocommit=True
    )
    cursor_master = conn_master.cursor()
    cursor_master.execute(f"IF DB_ID('{database}') IS NULL CREATE DATABASE [{database}]")
    cursor_master.close()
    conn_master.close()

    # Connect to DB
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=no;",
        autocommit=True
    )
    cursor = conn.cursor()

    # Read SQL
    print("🔍 Reading SQL file...")
    with open(sql_file, "r", encoding="utf-8") as f:
        sql_text = f.read()

    # replace USE [...]
    sql_text = re.sub(
        r"USE\s*\[[^\]]*\]",
        f"USE [{database}]",
        sql_text,
        count=1
    )

    commands = sql_text.split("GO")
    executed = 0

    for cmd in commands:
        cmd = cmd.strip()
        if not cmd:
            continue

        try:
            cursor.execute(cmd)
            executed += 1
        except Exception as e:
            print("❌ Error executing SQL block:")
            print(cmd[:200], "...\n")
            print(e)
            break

    cursor.close()
    conn.close()
    print(f"✅ Import complete! Executed {executed} SQL blocks.")



def export_sql_file(server, username, password, database, output_path):
    print(f"📤 Exporting database '{database}' into '{output_path}'...")

    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=no;",
        autocommit=True
    )
    cursor = conn.cursor()

    sql_dump = []
    sql_dump.append(f"USE [{database}]\nGO\n\n")

    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
    """)
    tables = [row.TABLE_NAME for row in cursor.fetchall()]

    for table in tables:
        sql_dump.append(f"-- TABLE: {table}\n")

        # Structure
        cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}'
        """)
        columns = cursor.fetchall()

        create_sql = f"CREATE TABLE [{table}] (\n"
        col_lines = []

        for col in columns:
            name = col.COLUMN_NAME
            dtype = col.DATA_TYPE

            if col.CHARACTER_MAXIMUM_LENGTH and col.CHARACTER_MAXIMUM_LENGTH > 0:
                dtype += f"({col.CHARACTER_MAXIMUM_LENGTH})"

            col_lines.append(f"    [{name}] {dtype}")

        create_sql += ",\n".join(col_lines) + "\n);\nGO\n\n"
        sql_dump.append(create_sql)

        # Data
        cursor.execute(f"SELECT * FROM [{table}]")
        rows = cursor.fetchall()

        if rows:
            for row in rows:
                values = []

                for value in row:
                    if value is None:
                        values.append("NULL")

                    elif isinstance(value, str):
                        values.append("'" + value.replace("'", "''") + "'")

                    elif isinstance(value, datetime.datetime):
                        iso = value.isoformat(timespec='milliseconds')
                        values.append(f"'{iso}'")

                    elif isinstance(value, datetime.date):
                        values.append(f"'{value.isoformat()}'")

                    elif isinstance(value, datetime.time):
                        iso = value.isoformat(timespec='milliseconds')
                        values.append(f"'{iso}'")

                    else:
                        values.append(str(value))

                sql_dump.append(
                    f"INSERT INTO [{table}] VALUES ({', '.join(values)});\n"
                )
            sql_dump.append("GO\n\n")

    cursor.close()
    conn.close()

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(sql_dump)

    print(f"✅ Export complete! File saved to: {output_path}")



# ---- MAIN ----
cfg = load_config()

parser = argparse.ArgumentParser()

parser.add_argument("--db", type=str, help="Database name")
parser.add_argument("-i", "--import", dest="import_file", type=str)
parser.add_argument("-e", "-o", "--export", "--output", dest="export_file", type=str)

args = parser.parse_args()

server = cfg["server"]
username = cfg["username"]
password = cfg["password"]

# ---- DB validation ----
if args.db is None:
    print("⚠️ Please set the DB name with --db")
    sys.exit(1)

# EMPTY STRING → show DB list
if args.db.strip() == "":
    print("📚 Available databases:\n")

    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=no;",
        autocommit=True
    )
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sys.databases")

    for row in cursor.fetchall():
        print(f"- {row.name}")

    cursor.close()
    conn.close()

    print("\n⚠️ Please set a valid DB name with --db 😊")
    sys.exit(0)

database = args.db


# ---- IMPORT ----
if args.import_file:
    import_sql_file(server, username, password, database, args.import_file)
    sys.exit(0)

# ---- EXPORT ----
if args.export_file:
    export_sql_file(server, username, password, database, args.export_file)
    sys.exit(0)

# ---- SHOW TABLES ----
conn = pyodbc.connect(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={server};"
    f"DATABASE={database};"
    f"UID={username};"
    f"PWD={password};"
    "Encrypt=no;"
)
cursor = conn.cursor()

cursor.execute("""
    SELECT TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
""")

print("Tables:")
for row in cursor.fetchall():
    print("- " + row.TABLE_NAME)

cursor.close()
conn.close()
