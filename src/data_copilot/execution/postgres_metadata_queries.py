"""Program-owned PostgreSQL catalog queries for Phase 2.2."""

LIST_TABLES_SQL = """
SELECT
    namespace.nspname,
    relation.relname,
    CASE relation.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized_view'
        WHEN 'f' THEN 'foreign_table'
    END AS table_type
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
  AND namespace.nspname NOT LIKE 'pg_toast%%'
  AND namespace.nspname NOT LIKE 'pg_temp_%%'
  AND (%s::text IS NULL OR namespace.nspname = %s)
ORDER BY namespace.nspname, relation.relname
LIMIT %s
"""

LOOKUP_TABLE_SQL = """
SELECT
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace
        WHERE nspname = %s
    ) AS schema_exists,
    relation.oid,
    CASE relation.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized_view'
        WHEN 'f' THEN 'foreign_table'
    END AS table_type
FROM (VALUES (1)) AS anchor(value)
LEFT JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.nspname = %s
LEFT JOIN pg_catalog.pg_class AS relation
    ON relation.relnamespace = namespace.oid
   AND relation.relname = %s
   AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
"""

LIST_COLUMNS_SQL = """
SELECT
    attribute.attname,
    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
    NOT attribute.attnotnull AS nullable
FROM pg_catalog.pg_attribute AS attribute
WHERE attribute.attrelid = %s
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY attribute.attnum
LIMIT %s
"""

PRIMARY_KEY_SQL = """
SELECT attribute.attname
FROM pg_catalog.pg_constraint AS constraint_record
JOIN LATERAL unnest(constraint_record.conkey) WITH ORDINALITY AS key(attnum, position)
    ON TRUE
JOIN pg_catalog.pg_attribute AS attribute
    ON attribute.attrelid = constraint_record.conrelid
   AND attribute.attnum = key.attnum
WHERE constraint_record.conrelid = %s
  AND constraint_record.contype = 'p'
ORDER BY key.position
LIMIT %s
"""

OUTBOUND_FOREIGN_KEYS_SQL = """
SELECT
    constraint_record.conname,
    array_agg(source_attribute.attname ORDER BY source_key.position),
    target_namespace.nspname,
    target_relation.relname,
    array_agg(target_attribute.attname ORDER BY source_key.position)
FROM pg_catalog.pg_constraint AS constraint_record
JOIN pg_catalog.pg_class AS target_relation
    ON target_relation.oid = constraint_record.confrelid
JOIN pg_catalog.pg_namespace AS target_namespace
    ON target_namespace.oid = target_relation.relnamespace
JOIN LATERAL unnest(constraint_record.conkey) WITH ORDINALITY
    AS source_key(attnum, position) ON TRUE
JOIN LATERAL unnest(constraint_record.confkey) WITH ORDINALITY
    AS target_key(attnum, position) ON target_key.position = source_key.position
JOIN pg_catalog.pg_attribute AS source_attribute
    ON source_attribute.attrelid = constraint_record.conrelid
   AND source_attribute.attnum = source_key.attnum
JOIN pg_catalog.pg_attribute AS target_attribute
    ON target_attribute.attrelid = constraint_record.confrelid
   AND target_attribute.attnum = target_key.attnum
WHERE constraint_record.conrelid = %s
  AND constraint_record.contype = 'f'
GROUP BY
    constraint_record.oid,
    constraint_record.conname,
    target_namespace.nspname,
    target_relation.relname
ORDER BY constraint_record.conname
LIMIT %s
"""

LIST_INDEXES_SQL = """
SELECT
    index_relation.relname,
    ARRAY(
        SELECT pg_catalog.pg_get_indexdef(index_record.indexrelid, position, TRUE)
        FROM generate_series(1, index_record.indnkeyatts) AS position
        ORDER BY position
    ) AS indexed_columns,
    index_record.indisunique,
    index_record.indisprimary
FROM pg_catalog.pg_index AS index_record
JOIN pg_catalog.pg_class AS index_relation
    ON index_relation.oid = index_record.indexrelid
WHERE index_record.indrelid = %s
  AND index_record.indisvalid
ORDER BY index_relation.relname
LIMIT %s
"""

LIST_RELATIONSHIPS_SQL = """
WITH foreign_keys AS (
    SELECT
        constraint_record.oid,
        constraint_record.conname,
        source_relation.oid AS source_oid,
        source_namespace.nspname AS source_schema,
        source_relation.relname AS source_table,
        array_agg(source_attribute.attname ORDER BY source_key.position) AS source_columns,
        target_relation.oid AS target_oid,
        target_namespace.nspname AS target_schema,
        target_relation.relname AS target_table,
        array_agg(target_attribute.attname ORDER BY source_key.position) AS target_columns
    FROM pg_catalog.pg_constraint AS constraint_record
    JOIN pg_catalog.pg_class AS source_relation
        ON source_relation.oid = constraint_record.conrelid
    JOIN pg_catalog.pg_namespace AS source_namespace
        ON source_namespace.oid = source_relation.relnamespace
    JOIN pg_catalog.pg_class AS target_relation
        ON target_relation.oid = constraint_record.confrelid
    JOIN pg_catalog.pg_namespace AS target_namespace
        ON target_namespace.oid = target_relation.relnamespace
    JOIN LATERAL unnest(constraint_record.conkey) WITH ORDINALITY
        AS source_key(attnum, position) ON TRUE
    JOIN LATERAL unnest(constraint_record.confkey) WITH ORDINALITY
        AS target_key(attnum, position) ON target_key.position = source_key.position
    JOIN pg_catalog.pg_attribute AS source_attribute
        ON source_attribute.attrelid = constraint_record.conrelid
       AND source_attribute.attnum = source_key.attnum
    JOIN pg_catalog.pg_attribute AS target_attribute
        ON target_attribute.attrelid = constraint_record.confrelid
       AND target_attribute.attnum = target_key.attnum
    WHERE constraint_record.contype = 'f'
      AND (
          constraint_record.conrelid = %s
          OR constraint_record.confrelid = %s
      )
    GROUP BY
        constraint_record.oid,
        constraint_record.conname,
        source_relation.oid,
        source_namespace.nspname,
        source_relation.relname,
        target_relation.oid,
        target_namespace.nspname,
        target_relation.relname
), directional_relationships AS (
    SELECT
        'outbound' AS direction,
        conname,
        source_schema,
        source_table,
        source_columns,
        target_schema,
        target_table,
        target_columns
    FROM foreign_keys
    WHERE source_oid = %s
    UNION ALL
    SELECT
        'inbound' AS direction,
        conname,
        source_schema,
        source_table,
        source_columns,
        target_schema,
        target_table,
        target_columns
    FROM foreign_keys
    WHERE target_oid = %s
)
SELECT *
FROM directional_relationships
ORDER BY direction, source_schema, source_table, conname
LIMIT %s
"""
