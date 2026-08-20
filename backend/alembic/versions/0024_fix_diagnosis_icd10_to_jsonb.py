"""Fix diagnosis_icd10 column type from VARCHAR to JSONB.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-29 07:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Apply to public schema if any consultations table exists there (shouldn't)
    # op.execute("SET search_path TO public, public")

    # Iterate through all tenant schemas and convert the column
    # First, get list of all schemas (public, and all tenants)
    conn = op.get_bind()
    
    # Get all tenant schemas
    schemas_result = conn.execute(
        sa.text("""
            SELECT schema_name FROM information_schema.schemata 
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'pg_temp_1', 'public')
            ORDER BY schema_name
        """)
    )
    schemas = [row[0] for row in schemas_result]
    
    for schema in schemas:
        # Check if consultations table exists in this schema
        table_exists = conn.execute(
            sa.text(f"""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema='{schema}' AND table_name='consultations'
                )
            """)
        ).scalar()
        
        if table_exists:
            # Convert diagnosis_icd10 from VARCHAR to JSONB
            op.execute(f"""
                ALTER TABLE "{schema}".consultations 
                ALTER COLUMN diagnosis_icd10 TYPE jsonb USING diagnosis_icd10::jsonb
            """)


def downgrade() -> None:
    # Downgrade: convert back to VARCHAR
    conn = op.get_bind()
    
    schemas_result = conn.execute(
        sa.text("""
            SELECT schema_name FROM information_schema.schemata 
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'pg_temp_1', 'public')
            ORDER BY schema_name
        """)
    )
    schemas = [row[0] for row in schemas_result]
    
    for schema in schemas:
        table_exists = conn.execute(
            sa.text(f"""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema='{schema}' AND table_name='consultations'
                )
            """)
        ).scalar()
        
        if table_exists:
            op.execute(f"""
                ALTER TABLE "{schema}".consultations 
                ALTER COLUMN diagnosis_icd10 TYPE character varying USING diagnosis_icd10::character varying
            """)
