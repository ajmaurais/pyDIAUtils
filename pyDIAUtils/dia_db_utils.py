
import sqlite3
from datetime import datetime

import pandas as pd

from .metadata import Dtype
from .logger import LOGGER

METADATA_TIME_FORMAT = '%m/%d/%Y %H:%M:%S'

PRECURSOR_KEY_COLS = ('replicateId', 'modifiedSequence', 'precursorCharge')

SCHEMA_VERSION = '1.9'

SCHEMA = [
'''
CREATE TABLE replicates (
    replicateId INTEGER PRIMARY KEY,
    replicate TEXT NOT NULL,
    project TEXT NOT NULL,
    acquiredTime BLOB NOT NULL,
    acquiredRank INTEGER NOT NULL,
    ticArea REAL NOT NULL,
    UNIQUE(replicate, project) ON CONFLICT FAIL
)''',
f'''
CREATE TABLE precursors (
    replicateId INTEGER NOT NULL,
    modifiedSequence VARCHAR(200) NOT NULL,
    precursorCharge INTEGER NOT NULL,
    precursorMz REAL,
    averageMassErrorPPM REAL,
    totalAreaFragment REAL,
    totalAreaMs1 REAL,
    normalizedArea REAL,
    rt REAL,
    minStartTime REAL,
    maxEndTime REAL,
    maxFwhm REAL,
    libraryDotProduct REAL,
    isotopeDotProduct REAL,
    PRIMARY KEY ({', '.join(PRECURSOR_KEY_COLS)}),
    FOREIGN KEY (replicateId) REFERENCES replicates(replicateId)
)''',
'''
CREATE TABLE sampleMetadata (
    replicateId INTEGER NOT NULL,
    annotationKey TEXT NOT NULL,
    annotationValue TEXT,
    PRIMARY KEY (replicateId, annotationKey),
    FOREIGN KEY (replicateId) REFERENCES replicates(replicateId)
    FOREIGN KEY (annotationKey) REFERENCES sampleMetadataTypes(annotationKey)
)''',
'''
CREATE TABLE sampleMetadataTypes (
    annotationKey TEXT NOT NULL,
    annotationType VARCHAR(6) CHECK( annotationType IN ('BOOL', 'INT', 'FLOAT', 'STRING')) NOT NULL DEFAULT 'STRING',
    PRIMARY KEY (annotationKey)
)''',
'''
CREATE TABLE metadata (
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (key)
)''',
'''
CREATE TABLE proteins (
    proteinId INTEGER PRIMARY KEY,
    accession VARCHAR(25),
    name VARCHAR(50) UNIQUE,
    description VARCHAR(200)
)''',
'''
CREATE TABLE proteinQuants (
    replicateId INTEGER NOT NULL,
    proteinId INTEGER NOT NULL,
    abundance REAL,
    normalizedAbundance REAL,
    PRIMARY KEY (replicateId, proteinId),
    FOREIGN KEY (replicateId) REFERENCES replicates(replicateId),
    FOREIGN KEY (proteinId) REFERENCES proteins(proteinId)
)''',
'''
CREATE TABLE peptideToProtein (
    proteinId INTEGER NOT NULL,
    modifiedSequence VARCHAR(200) NOT NULL,
    PRIMARY KEY (modifiedSequence, proteinId),
    FOREIGN KEY (proteinId) REFERENCES proteins(proteinId),
    FOREIGN KEY (modifiedSequence) REFERENCES precursors(modifiedSequence)
)''']


def is_normalized(conn):
    ''' Determine if metadata.is_normalized is True '''

    cur = conn.cursor()
    cur.execute('SELECT value FROM metadata WHERE key == "is_normalized"')
    value = cur.fetchall()

    if len(value) == 0:
        LOGGER.warning("'is_normalized' key not in metadata table!")
        return False

    value = value[0][0].lower()
    if value in ('true', '1'):
        return True

    LOGGER.warning('metadata.is_normalized is False. Only using unnormalized values.')
    return False


def insert_program_metadata_key_pairs(conn, metadata):
    '''
    Insert multiple metadata key, value pairs into the metadata table.
    If the key already exists it is overwritten.

    Parameters
    ----------
    conn: sqlite3.Connection:
        Database connection.
    metadata: dict
        A dict with key, value pairs.
    '''
    cur = conn.cursor()
    for key, value in metadata.items():
        cur.execute(f'''
            INSERT INTO metadata
                (key, value) VALUES ("{key}", "{value}")
            ON CONFLICT(key) DO UPDATE SET value = "{value}" ''')
    conn.commit()
    return conn


def get_meta_value(conn, key):
    ''' Get the value for a key from the metadata table '''
    cur = conn.cursor()
    cur.execute('SELECT value FROM metadata WHERE key == ?', (key,))
    value = cur.fetchall()
    if len(value) == 1:
        return value[0][0]
    LOGGER.error(f"Could not get key '{key}' from metadata table!")
    return None


def check_schema_version(conn):
    db_version = get_meta_value(conn, 'schema_version')
    if db_version is None or db_version != SCHEMA_VERSION:
        LOGGER.error(f'Database schema version ({db_version}) does not match program ({SCHEMA_VERSION})')
        return False
    return True


def update_meta_value(conn, key, value):
    '''
    Add or update value in metadata table.
    
    Parameters
    ----------
    conn: sqlite3.Connection:
        Database connection.
    key: str
        The metadata key
    value: str
        The metadata value
    '''
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO metadata
            (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = ? ''',
                (key, value, value))
    conn.commit()

    return conn


def update_acquired_ranks(conn):
    '''
    Populate acquiredRank column in replicates table.

    Parameters
    ----------
    conn: sqlite3.Connection:
        Database connection.
    '''

    replicates = pd.read_sql('SELECT replicateId, acquiredTime FROM replicates;', conn)

    # parse acquired times and add acquiredRank
    replicates['acquiredTime'] = replicates['acquiredTime'].apply(lambda x: datetime.strptime(x, METADATA_TIME_FORMAT))
    ranks = [(rank, i) for rank, i in enumerate(replicates['acquiredTime'].sort_values().index)]
    replicates['acquiredRank'] = [x[0] for x in sorted(ranks, key=lambda x: x[1])]

    acquired_ranks = [(row.acquiredRank, row.replicateId) for row in replicates.itertuples()]
    cur = conn.cursor()
    cur.executemany('UPDATE replicates SET acquiredRank = ? WHERE replicateId = ?', acquired_ranks)
    conn.commit()

    update_meta_value(conn, 'replicates.acquiredRank updated', True)

    return conn


def update_metadata_dtypes(conn, new_types):
    '''
    Update metadata annotationType column to fix cases where
    two projects have a different annotationTypes for the same
    annotationKey. This function will consolidate conflicting
    types using the order in the Dtype Enum class.

    Parameters
    ----------
    conn: sqlite3.Connection:
        Database connection.
    new_types: dict
        A dictionary of new annotationKey, annotationType pairs.
    '''

    # Consolidate differing annotationTypes
    cur = conn.cursor()
    cur.execute('SELECT annotationKey, annotationType FROM sampleMetadataTypes;')
    existing_types = {x[0]: Dtype[x[1]] for x in cur.fetchall()}

    # consolidate new and existing data types
    for key, value in new_types.items():
        if key not in existing_types:
            existing_types[key] = value
            continue
        existing_types[key] = max(existing_types[key], value)

    # Update database
    insert_query = '''
        INSERT INTO sampleMetadataTypes (annotationKey, annotationType)
        VALUES(?, ?)
        ON CONFLICT(annotationKey) DO UPDATE SET annotationType = ?
    '''
    cur = conn.cursor()
    for annotationKey, dtype in existing_types.items():
        annotationType = str(dtype)
        cur.execute(insert_query, (annotationKey, annotationType, annotationType))
    conn.commit()

    return conn

