import sqlite3
import os
import csv
import uuid

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Function to generate a new UUID
def generate_uuid():
    return str(uuid.uuid4())

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create models table with all fields
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS models (
        id TEXT PRIMARY KEY,
        name TEXT,
        modelId TEXT,
        description TEXT,
        category TEXT,
        subcategory TEXT,
        size INTEGER,
        createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create engines table with all fields
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS engines (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        helm_chart_repo TEXT,
        createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create inference_instance_config_params table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inference_instance_config_params (
        id TEXT PRIMARY KEY,
        maxInputLength INTEGER,
        maxTokens INTEGER,
        maxBatchPrefillTokens INTEGER,
        maxBatchTotalTokens INTEGER,
        quantization TEXT,
        image TEXT,
        createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create inference_instances table with all fields
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inference_instances (
        id TEXT PRIMARY KEY,
        model_id TEXT,
        engine_id TEXT,
        host TEXT,
        endpoint TEXT,
        healthEndpoint TEXT,
        metricsEndpoint TEXT,
        inference_instance_config_params_id TEXT,
        createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (model_id) REFERENCES models (id),
        FOREIGN KEY (engine_id) REFERENCES engines (id),
        FOREIGN KEY (inference_instance_config_params_id) REFERENCES inference_instance_config_params (id)
    )
    """)

    # Insert data from CSV files
    raw_data_dir = 'raw_data'
    for filename in os.listdir(raw_data_dir):
        if filename.endswith('.csv'):
            with open(os.path.join(raw_data_dir, filename), 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if filename == 'models.csv':
                        cursor.execute("""
                        INSERT OR IGNORE INTO models (id, name, modelId, description, category, subcategory, size)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (generate_uuid(), row['name'], row['modelId'], row['description'], row['category'], row['subcategory'], row['size']))
                    elif filename == 'engines.csv':
                        cursor.execute("""
                        INSERT OR IGNORE INTO engines (id, name, description, helm_chart_repo)
                        VALUES (?, ?, ?, ?)
                        """, (generate_uuid(), row['name'], row['description'], row['helm_chart_repo']))

    conn.commit()
    conn.close()

# init_db()
