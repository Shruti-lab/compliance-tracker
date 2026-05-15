#!/usr/bin/env python3
"""
Database setup script for Compliance Tracker
Creates PostgreSQL database and initializes schema
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from pathlib import Path


def create_database(host, port, user, password, db_name):
    """Create the database if it doesn't exist."""
    try:
        # Connect to PostgreSQL server (default postgres database)
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database='postgres'
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (db_name,)
        )
        exists = cursor.fetchone()
        
        if not exists:
            cursor.execute(f'CREATE DATABASE {db_name}')
            print(f"✓ Database '{db_name}' created successfully")
        else:
            print(f"✓ Database '{db_name}' already exists")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Error creating database: {e}")
        return False


def initialize_schema(host, port, user, password, db_name, schema_file):
    """Initialize database schema from SQL file."""
    try:
        # Connect to the target database
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db_name
        )
        cursor = conn.cursor()
        
        # Read and execute schema file
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        cursor.execute(schema_sql)
        conn.commit()
        
        print(f"✓ Schema initialized successfully from {schema_file}")
        
        # Verify tables were created
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        print(f"\n✓ Created {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")
        
        # Verify views were created
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.views 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        views = cursor.fetchall()
        
        if views:
            print(f"\n✓ Created {len(views)} views:")
            for view in views:
                print(f"  - {view[0]}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Error initializing schema: {e}")
        return False


def test_connection(host, port, user, password, db_name):
    """Test database connection."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db_name
        )
        cursor = conn.cursor()
        cursor.execute('SELECT version()')
        version = cursor.fetchone()
        print(f"\n✓ Connection successful!")
        if version:
            print(f"  PostgreSQL version: {version[0].split(',')[0]}")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Connection test failed: {e}")
        return False


def main():
    """Main setup function."""
    print("=" * 60)
    print("Compliance Tracker - Database Setup")
    print("=" * 60)
    
    # Get database configuration from environment or use defaults
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', ''),
        'db_name': os.getenv('POSTGRES_DB', 'compliance_tracker')
    }
    
    print(f"\nDatabase Configuration:")
    print(f"  Host: {db_config['host']}")
    print(f"  Port: {db_config['port']}")
    print(f"  User: {db_config['user']}")
    print(f"  Database: {db_config['db_name']}")
    print()
    
    # Get schema file path
    script_dir = Path(__file__).parent
    schema_file = script_dir / 'schema.sql'
    
    if not schema_file.exists():
        print(f"✗ Schema file not found: {schema_file}")
        sys.exit(1)
    
    # Step 1: Create database
    print("Step 1: Creating database...")
    if not create_database(**db_config):
        sys.exit(1)
    
    # Step 2: Initialize schema
    print("\nStep 2: Initializing schema...")
    if not initialize_schema(**db_config, schema_file=schema_file):
        sys.exit(1)
    
    # Step 3: Test connection
    print("\nStep 3: Testing connection...")
    if not test_connection(**db_config):
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✓ Database setup completed successfully!")
    print("=" * 60)
    print("\nYou can now run the compliance tracker application.")
    print(f"Connection string: postgresql://{db_config['user']}@{db_config['host']}:{db_config['port']}/{db_config['db_name']}")


if __name__ == '__main__':
    main()

# Made with Bob
