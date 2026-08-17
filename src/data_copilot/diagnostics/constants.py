"""Deterministic limits and formatting policy for diagnostic snapshots."""

MAX_SNAPSHOT_COLUMNS = 200
MAX_DATASET_ID_CHARS = 255
MAX_SNAPSHOT_ID_CHARS = 255
MAX_COLUMN_NAME_CHARS = 255
MAX_DATA_TYPE_CHARS = 128
MAX_COUNT = 2**63 - 1

PERCENTAGE_DECIMAL_PLACES = 4

# One row-count finding, two dataset duplicate findings, and at most seven
# findings per column (schema, null, cardinality, and range observations).
MAX_DRIFT_FINDINGS = 3 + (7 * MAX_SNAPSHOT_COLUMNS)
