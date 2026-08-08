"""current schema baseline

Revision ID: 0001_current_schema
Revises:
Create Date: 2026-06-05 13:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('artifacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('storage_backend', sa.String(length=80), nullable=False),
    sa.Column('storage_uri', sa.Text(), nullable=True),
    sa.Column('original_filename', sa.String(length=500), nullable=True),
    sa.Column('remote_url', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.String(length=255), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_artifacts'))
    )
    op.create_index(op.f('ix_artifacts_checksum_sha256'), 'artifacts', ['checksum_sha256'], unique=False)
    op.create_index(op.f('ix_artifacts_kind'), 'artifacts', ['kind'], unique=False)
    op.create_index(op.f('ix_artifacts_status'), 'artifacts', ['status'], unique=False)
    op.create_table('arxiv_task_daily_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('run_time', sa.String(length=5), nullable=False),
    sa.Column('last_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_daily_config'))
    )
    op.create_index(op.f('ix_arxiv_task_daily_config_status'), 'arxiv_task_daily_config', ['status'], unique=False)
    op.create_table('arxiv_task_harvest_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('subscription_ids_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('requested_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('stats_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_harvest_jobs'))
    )
    op.create_index(op.f('ix_arxiv_task_harvest_jobs_kind'), 'arxiv_task_harvest_jobs', ['kind'], unique=False)
    op.create_index(op.f('ix_arxiv_task_harvest_jobs_requested_end'), 'arxiv_task_harvest_jobs', ['requested_end'], unique=False)
    op.create_index(op.f('ix_arxiv_task_harvest_jobs_requested_start'), 'arxiv_task_harvest_jobs', ['requested_start'], unique=False)
    op.create_index(op.f('ix_arxiv_task_harvest_jobs_status'), 'arxiv_task_harvest_jobs', ['status'], unique=False)
    op.create_table('arxiv_task_papers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('arxiv_id', sa.String(length=120), nullable=False),
    sa.Column('arxiv_base_id', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=1000), nullable=False),
    sa.Column('abstract', sa.Text(), nullable=True),
    sa.Column('authors_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('primary_category', sa.String(length=40), nullable=True),
    sa.Column('categories_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at_source', sa.DateTime(timezone=True), nullable=True),
    sa.Column('landing_page_url', sa.Text(), nullable=True),
    sa.Column('pdf_url', sa.Text(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('journal_ref', sa.Text(), nullable=True),
    sa.Column('doi', sa.String(length=500), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_papers'))
    )
    op.create_index(op.f('ix_arxiv_task_papers_arxiv_base_id'), 'arxiv_task_papers', ['arxiv_base_id'], unique=True)
    op.create_index(op.f('ix_arxiv_task_papers_arxiv_id'), 'arxiv_task_papers', ['arxiv_id'], unique=False)
    op.create_index(op.f('ix_arxiv_task_papers_doi'), 'arxiv_task_papers', ['doi'], unique=False)
    op.create_index(op.f('ix_arxiv_task_papers_primary_category'), 'arxiv_task_papers', ['primary_category'], unique=False)
    op.create_index(op.f('ix_arxiv_task_papers_published_at'), 'arxiv_task_papers', ['published_at'], unique=False)
    op.create_index(op.f('ix_arxiv_task_papers_updated_at_source'), 'arxiv_task_papers', ['updated_at_source'], unique=False)
    op.create_table('arxiv_task_subscriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_subscriptions')),
    sa.UniqueConstraint('name', name=op.f('uq_arxiv_task_subscriptions_name'))
    )
    op.create_index(op.f('ix_arxiv_task_subscriptions_enabled'), 'arxiv_task_subscriptions', ['enabled'], unique=False)
    op.create_table('papers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=1000), nullable=False),
    sa.Column('abstract', sa.Text(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at_source', sa.DateTime(timezone=True), nullable=True),
    sa.Column('venue', sa.String(length=500), nullable=True),
    sa.Column('authors_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('keywords_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('categories_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('citation_count', sa.Integer(), nullable=True),
    sa.Column('best_pdf_url', sa.Text(), nullable=True),
    sa.Column('landing_page_url', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_papers'))
    )
    op.create_index(op.f('ix_papers_status'), 'papers', ['status'], unique=False)
    op.create_index(op.f('ix_papers_year'), 'papers', ['year'], unique=False)
    op.create_table('provider_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('base_url', sa.String(length=1000), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('api_key_ref', sa.Text(), nullable=True),
    sa.Column('temperature', sa.Float(), nullable=True),
    sa.Column('settings_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_configs')),
    sa.UniqueConstraint('kind', 'name', name='uq_provider_configs_kind_name')
    )
    op.create_index(op.f('ix_provider_configs_kind'), 'provider_configs', ['kind'], unique=False)
    op.create_table('arxiv_task_paper_subscriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('subscription_id', sa.Integer(), nullable=False),
    sa.Column('query_snapshot', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['arxiv_task_papers.id'], name=op.f('fk_arxiv_task_paper_subscriptions_paper_id_arxiv_task_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subscription_id'], ['arxiv_task_subscriptions.id'], name=op.f('fk_arxiv_task_paper_subscriptions_subscription_id_arxiv_task_subscriptions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_paper_subscriptions')),
    sa.UniqueConstraint('paper_id', 'subscription_id', name='uq_arxiv_task_paper_subscriptions_paper_subscription')
    )
    op.create_index(op.f('ix_arxiv_task_paper_subscriptions_paper_id'), 'arxiv_task_paper_subscriptions', ['paper_id'], unique=False)
    op.create_index(op.f('ix_arxiv_task_paper_subscriptions_subscription_id'), 'arxiv_task_paper_subscriptions', ['subscription_id'], unique=False)
    op.create_table('arxiv_task_query_windows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subscription_id', sa.Integer(), nullable=False),
    sa.Column('query_snapshot', sa.Text(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('total_results', sa.Integer(), nullable=True),
    sa.Column('fetched_count', sa.Integer(), nullable=False),
    sa.Column('inserted_count', sa.Integer(), nullable=False),
    sa.Column('updated_count', sa.Integer(), nullable=False),
    sa.Column('page_size', sa.Integer(), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('warning_code', sa.String(length=120), nullable=True),
    sa.Column('parent_window_id', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['arxiv_task_harvest_jobs.id'], name=op.f('fk_arxiv_task_query_windows_job_id_arxiv_task_harvest_jobs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_window_id'], ['arxiv_task_query_windows.id'], name=op.f('fk_arxiv_task_query_windows_parent_window_id_arxiv_task_query_windows'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['subscription_id'], ['arxiv_task_subscriptions.id'], name=op.f('fk_arxiv_task_query_windows_subscription_id_arxiv_task_subscriptions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arxiv_task_query_windows'))
    )
    op.create_index(op.f('ix_arxiv_task_query_windows_job_id'), 'arxiv_task_query_windows', ['job_id'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_kind'), 'arxiv_task_query_windows', ['kind'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_parent_window_id'), 'arxiv_task_query_windows', ['parent_window_id'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_status'), 'arxiv_task_query_windows', ['status'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_subscription_id'), 'arxiv_task_query_windows', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_window_end'), 'arxiv_task_query_windows', ['window_end'], unique=False)
    op.create_index(op.f('ix_arxiv_task_query_windows_window_start'), 'arxiv_task_query_windows', ['window_start'], unique=False)
    op.create_table('paper_identifiers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('identifier_type', sa.String(length=80), nullable=False),
    sa.Column('identifier_value', sa.String(length=500), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_paper_identifiers_paper_id_papers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_identifiers')),
    sa.UniqueConstraint('identifier_type', 'identifier_value', name='uq_paper_identifiers_type_value')
    )
    op.create_index(op.f('ix_paper_identifiers_paper_id'), 'paper_identifiers', ['paper_id'], unique=False)
    op.create_table('paper_source_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('source_record_id', sa.String(length=500), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('raw_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_paper_source_records_paper_id_papers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_source_records'))
    )
    op.create_index(op.f('ix_paper_source_records_paper_id'), 'paper_source_records', ['paper_id'], unique=False)
    op.create_index('uq_paper_source_records_source_record_id', 'paper_source_records', ['source', 'source_record_id'], unique=True, postgresql_where=sa.text('source_record_id IS NOT NULL'))
    op.create_table('threads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('surface', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('current_focus_paper_id', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('deepagent_thread_id', sa.String(length=255), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['current_focus_paper_id'], ['papers.id'], name=op.f('fk_threads_current_focus_paper_id_papers'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_threads'))
    )
    op.create_index(op.f('ix_threads_deepagent_thread_id'), 'threads', ['deepagent_thread_id'], unique=False)
    op.create_index(op.f('ix_threads_status'), 'threads', ['status'], unique=False)
    op.create_table('agent_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=True),
    sa.Column('workflow', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('deepagent_run_id', sa.String(length=255), nullable=True),
    sa.Column('deepagent_thread_id', sa.String(length=255), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('input_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], name=op.f('fk_agent_runs_thread_id_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs'))
    )
    op.create_index(op.f('ix_agent_runs_deepagent_run_id'), 'agent_runs', ['deepagent_run_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_deepagent_thread_id'), 'agent_runs', ['deepagent_thread_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_status'), 'agent_runs', ['status'], unique=False)
    op.create_index(op.f('ix_agent_runs_thread_id'), 'agent_runs', ['thread_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_workflow'), 'agent_runs', ['workflow'], unique=False)
    op.create_table('memories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=1000), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('memory_type', sa.String(length=40), nullable=False),
    sa.Column('scope_type', sa.String(length=40), nullable=False),
    sa.Column('scope_id', sa.String(length=255), nullable=True),
    sa.Column('paper_id', sa.Integer(), nullable=True),
    sa.Column('content_text', sa.Text(), nullable=False),
    sa.Column('content_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('source_thread_id', sa.Integer(), nullable=True),
    sa.Column('source_paper_id', sa.Integer(), nullable=True),
    sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_memories_paper_id_papers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_paper_id'], ['papers.id'], name=op.f('fk_memories_source_paper_id_papers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_thread_id'], ['threads.id'], name=op.f('fk_memories_source_thread_id_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memories')),
    sa.UniqueConstraint('path', name='uq_memories_path')
    )
    op.create_index(op.f('ix_memories_memory_type'), 'memories', ['memory_type'], unique=False)
    op.create_index(op.f('ix_memories_paper_id'), 'memories', ['paper_id'], unique=False)
    op.create_index(op.f('ix_memories_scope_id'), 'memories', ['scope_id'], unique=False)
    op.create_index(op.f('ix_memories_scope_type'), 'memories', ['scope_type'], unique=False)
    op.create_index(op.f('ix_memories_source'), 'memories', ['source'], unique=False)
    op.create_index(op.f('ix_memories_status'), 'memories', ['status'], unique=False)
    op.create_table('paper_artifacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('artifact_id', sa.Integer(), nullable=False),
    sa.Column('source_record_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.String(length=80), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], name=op.f('fk_paper_artifacts_artifact_id_artifacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_paper_artifacts_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_record_id'], ['paper_source_records.id'], name=op.f('fk_paper_artifacts_source_record_id_paper_source_records'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_artifacts')),
    sa.UniqueConstraint('paper_id', 'artifact_id', name='uq_paper_artifacts_paper_artifact')
    )
    op.create_table('acquisition_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('requested_source', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('input_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_acquisition_jobs_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_acquisition_jobs_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], name=op.f('fk_acquisition_jobs_thread_id_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_acquisition_jobs'))
    )
    op.create_index(op.f('ix_acquisition_jobs_paper_id'), 'acquisition_jobs', ['paper_id'], unique=False)
    op.create_index(op.f('ix_acquisition_jobs_run_id'), 'acquisition_jobs', ['run_id'], unique=False)
    op.create_index(op.f('ix_acquisition_jobs_status'), 'acquisition_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_acquisition_jobs_thread_id'), 'acquisition_jobs', ['thread_id'], unique=False)
    op.create_table('agent_run_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('level', sa.String(length=40), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_agent_run_events_run_id_agent_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_run_events')),
    sa.UniqueConstraint('run_id', 'sequence', name='uq_agent_run_events_run_id_sequence')
    )
    op.create_index(op.f('ix_agent_run_events_run_id'), 'agent_run_events', ['run_id'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('content_text', sa.Text(), nullable=True),
    sa.Column('content_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('token_input', sa.Integer(), nullable=True),
    sa.Column('token_output', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_messages_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], name=op.f('fk_messages_thread_id_threads'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index('ix_messages_run_id', 'messages', ['run_id'], unique=False)
    op.create_index('ix_messages_thread_id_created_at', 'messages', ['thread_id', 'created_at'], unique=False)
    op.create_table('parse_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('input_artifact_id', sa.Integer(), nullable=True),
    sa.Column('strategy', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('parser_version', sa.String(length=120), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('settings_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['input_artifact_id'], ['artifacts.id'], name=op.f('fk_parse_jobs_input_artifact_id_artifacts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_parse_jobs_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_parse_jobs_run_id_agent_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parse_jobs'))
    )
    op.create_index(op.f('ix_parse_jobs_paper_id'), 'parse_jobs', ['paper_id'], unique=False)
    op.create_index(op.f('ix_parse_jobs_run_id'), 'parse_jobs', ['run_id'], unique=False)
    op.create_index(op.f('ix_parse_jobs_status'), 'parse_jobs', ['status'], unique=False)
    op.create_table('search_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('query_text', sa.Text(), nullable=False),
    sa.Column('source_preference', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('selected_candidate_id', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_search_sessions_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['selected_candidate_id'], ['search_candidates.id'], name='fk_search_sessions_selected_candidate_id_search_candidates', ondelete='SET NULL', use_alter=True),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], name=op.f('fk_search_sessions_thread_id_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_search_sessions'))
    )
    op.create_index(op.f('ix_search_sessions_run_id'), 'search_sessions', ['run_id'], unique=False)
    op.create_index(op.f('ix_search_sessions_status'), 'search_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_search_sessions_thread_id'), 'search_sessions', ['thread_id'], unique=False)
    op.create_table('parsed_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('parse_job_id', sa.Integer(), nullable=False),
    sa.Column('source_artifact_id', sa.Integer(), nullable=True),
    sa.Column('parser_kind', sa.String(length=80), nullable=False),
    sa.Column('plain_text', sa.Text(), nullable=True),
    sa.Column('markdown_content', sa.Text(), nullable=True),
    sa.Column('json_content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('quality_status', sa.String(length=40), nullable=False),
    sa.Column('quality_summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_parsed_documents_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parse_job_id'], ['parse_jobs.id'], name=op.f('fk_parsed_documents_parse_job_id_parse_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_artifact_id'], ['artifacts.id'], name=op.f('fk_parsed_documents_source_artifact_id_artifacts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parsed_documents')),
    sa.UniqueConstraint('parse_job_id', name='uq_parsed_documents_parse_job_id')
    )
    op.create_index(op.f('ix_parsed_documents_paper_id'), 'parsed_documents', ['paper_id'], unique=False)
    op.create_table('parser_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('parse_job_id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('level', sa.String(length=40), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_parser_events_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parse_job_id'], ['parse_jobs.id'], name=op.f('fk_parser_events_parse_job_id_parse_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parser_events')),
    sa.UniqueConstraint('parse_job_id', 'sequence', name='uq_parser_events_parse_job_sequence')
    )
    op.create_index(op.f('ix_parser_events_paper_id'), 'parser_events', ['paper_id'], unique=False)
    op.create_index(op.f('ix_parser_events_parse_job_id'), 'parser_events', ['parse_job_id'], unique=False)
    op.create_table('search_candidates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('search_session_id', sa.Integer(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=80), nullable=False),
    sa.Column('source_record_id', sa.String(length=500), nullable=True),
    sa.Column('paper_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=1000), nullable=False),
    sa.Column('abstract', sa.Text(), nullable=True),
    sa.Column('authors_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('doi', sa.String(length=500), nullable=True),
    sa.Column('arxiv_id', sa.String(length=120), nullable=True),
    sa.Column('openalex_id', sa.String(length=120), nullable=True),
    sa.Column('landing_page_url', sa.Text(), nullable=True),
    sa.Column('pdf_url', sa.Text(), nullable=True),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_search_candidates_paper_id_papers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['search_session_id'], ['search_sessions.id'], name=op.f('fk_search_candidates_search_session_id_search_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_search_candidates')),
    sa.UniqueConstraint('search_session_id', 'rank', name='uq_search_candidates_session_rank')
    )
    op.create_index(op.f('ix_search_candidates_paper_id'), 'search_candidates', ['paper_id'], unique=False)
    op.create_table('processed_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('parsed_document_id', sa.Integer(), nullable=False),
    sa.Column('parse_job_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('content_markdown', sa.Text(), nullable=True),
    sa.Column('content_text', sa.Text(), nullable=True),
    sa.Column('quality_status', sa.String(length=40), nullable=False),
    sa.Column('quality_summary', sa.Text(), nullable=True),
    sa.Column('processing_profile', sa.String(length=120), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_processed_documents_paper_id_papers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parse_job_id'], ['parse_jobs.id'], name=op.f('fk_processed_documents_parse_job_id_parse_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parsed_document_id'], ['parsed_documents.id'], name=op.f('fk_processed_documents_parsed_document_id_parsed_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processed_documents')),
    sa.UniqueConstraint('paper_id', 'version', name='uq_processed_documents_paper_version')
    )
    op.create_index(op.f('ix_processed_documents_paper_id'), 'processed_documents', ['paper_id'], unique=False)
    op.create_table('document_chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('processed_document_id', sa.Integer(), nullable=False),
    sa.Column('chunk_key', sa.String(length=120), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('heading_path_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_section_ids_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('content_text', sa.Text(), nullable=False),
    sa.Column('token_estimate', sa.Integer(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
    sa.Column('embedding_model', sa.String(length=255), nullable=True),
    sa.Column('embedding_dimension', sa.Integer(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['processed_document_id'], ['processed_documents.id'], name=op.f('fk_document_chunks_processed_document_id_processed_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks')),
    sa.UniqueConstraint('processed_document_id', 'chunk_index', name='uq_document_chunks_doc_index'),
    sa.UniqueConstraint('processed_document_id', 'chunk_key', name='uq_document_chunks_doc_key')
    )
    op.create_table('document_sections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('processed_document_id', sa.Integer(), nullable=False),
    sa.Column('section_index', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('heading_path_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('cleaned_text', sa.Text(), nullable=True),
    sa.Column('token_estimate', sa.Integer(), nullable=True),
    sa.Column('quality_flags_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['processed_document_id'], ['processed_documents.id'], name=op.f('fk_document_sections_processed_document_id_processed_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_sections')),
    sa.UniqueConstraint('processed_document_id', 'section_index', name='uq_document_sections_doc_index')
    )
    op.create_table('paper_references',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('processed_document_id', sa.Integer(), nullable=False),
    sa.Column('reference_index', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('normalized_text', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=1000), nullable=True),
    sa.Column('authors_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('doi', sa.String(length=500), nullable=True),
    sa.Column('arxiv_id', sa.String(length=120), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('resolved_paper_id', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['processed_document_id'], ['processed_documents.id'], name=op.f('fk_paper_references_processed_document_id_processed_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolved_paper_id'], ['papers.id'], name=op.f('fk_paper_references_resolved_paper_id_papers'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_references')),
    sa.UniqueConstraint('processed_document_id', 'reference_index', name='uq_paper_references_doc_index')
    )
    op.create_table('reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('paper_id', sa.Integer(), nullable=True),
    sa.Column('processed_document_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('report_type', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('markdown_content', sa.Text(), nullable=True),
    sa.Column('json_content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source_scope', sa.String(length=80), nullable=False),
    sa.Column('source_refs_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_reports_paper_id_papers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['processed_document_id'], ['processed_documents.id'], name=op.f('fk_reports_processed_document_id_processed_documents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_reports_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], name=op.f('fk_reports_thread_id_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    op.create_index(op.f('ix_reports_paper_id'), 'reports', ['paper_id'], unique=False)
    op.create_index(op.f('ix_reports_run_id'), 'reports', ['run_id'], unique=False)
    op.create_index(op.f('ix_reports_status'), 'reports', ['status'], unique=False)
    op.create_index(op.f('ix_reports_thread_id'), 'reports', ['thread_id'], unique=False)
    op.create_table('report_evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('report_id', sa.Integer(), nullable=False),
    sa.Column('evidence_type', sa.String(length=40), nullable=False),
    sa.Column('chunk_id', sa.Integer(), nullable=True),
    sa.Column('reference_id', sa.Integer(), nullable=True),
    sa.Column('paper_id', sa.Integer(), nullable=True),
    sa.Column('quote_text', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['document_chunks.id'], name=op.f('fk_report_evidence_chunk_id_document_chunks'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], name=op.f('fk_report_evidence_paper_id_papers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reference_id'], ['paper_references.id'], name=op.f('fk_report_evidence_reference_id_paper_references'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['report_id'], ['reports.id'], name=op.f('fk_report_evidence_report_id_reports'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_evidence'))
    )
    op.create_index(op.f('ix_report_evidence_report_id'), 'report_evidence', ['report_id'], unique=False)
    # ### end Alembic commands ###

def downgrade() -> None:
    op.drop_index(op.f('ix_report_evidence_report_id'), table_name='report_evidence')
    op.drop_table('report_evidence')
    op.drop_index(op.f('ix_reports_thread_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_status'), table_name='reports')
    op.drop_index(op.f('ix_reports_run_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_paper_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_table('paper_references')
    op.drop_table('document_sections')
    op.drop_table('document_chunks')
    op.drop_index(op.f('ix_processed_documents_paper_id'), table_name='processed_documents')
    op.drop_table('processed_documents')
    op.drop_index(op.f('ix_search_candidates_paper_id'), table_name='search_candidates')
    op.drop_table('search_candidates')
    op.drop_index(op.f('ix_parser_events_parse_job_id'), table_name='parser_events')
    op.drop_index(op.f('ix_parser_events_paper_id'), table_name='parser_events')
    op.drop_table('parser_events')
    op.drop_index(op.f('ix_parsed_documents_paper_id'), table_name='parsed_documents')
    op.drop_table('parsed_documents')
    op.drop_index(op.f('ix_search_sessions_thread_id'), table_name='search_sessions')
    op.drop_index(op.f('ix_search_sessions_status'), table_name='search_sessions')
    op.drop_index(op.f('ix_search_sessions_run_id'), table_name='search_sessions')
    op.drop_table('search_sessions')
    op.drop_index(op.f('ix_parse_jobs_status'), table_name='parse_jobs')
    op.drop_index(op.f('ix_parse_jobs_run_id'), table_name='parse_jobs')
    op.drop_index(op.f('ix_parse_jobs_paper_id'), table_name='parse_jobs')
    op.drop_table('parse_jobs')
    op.drop_index('ix_messages_thread_id_created_at', table_name='messages')
    op.drop_index('ix_messages_run_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_agent_run_events_run_id'), table_name='agent_run_events')
    op.drop_table('agent_run_events')
    op.drop_index(op.f('ix_acquisition_jobs_thread_id'), table_name='acquisition_jobs')
    op.drop_index(op.f('ix_acquisition_jobs_status'), table_name='acquisition_jobs')
    op.drop_index(op.f('ix_acquisition_jobs_run_id'), table_name='acquisition_jobs')
    op.drop_index(op.f('ix_acquisition_jobs_paper_id'), table_name='acquisition_jobs')
    op.drop_table('acquisition_jobs')
    op.drop_table('paper_artifacts')
    op.drop_index(op.f('ix_memories_status'), table_name='memories')
    op.drop_index(op.f('ix_memories_source'), table_name='memories')
    op.drop_index(op.f('ix_memories_scope_type'), table_name='memories')
    op.drop_index(op.f('ix_memories_scope_id'), table_name='memories')
    op.drop_index(op.f('ix_memories_paper_id'), table_name='memories')
    op.drop_index(op.f('ix_memories_memory_type'), table_name='memories')
    op.drop_table('memories')
    op.drop_index(op.f('ix_agent_runs_workflow'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_thread_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_status'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_deepagent_thread_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_deepagent_run_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index(op.f('ix_threads_status'), table_name='threads')
    op.drop_index(op.f('ix_threads_deepagent_thread_id'), table_name='threads')
    op.drop_table('threads')
    op.drop_index('uq_paper_source_records_source_record_id', table_name='paper_source_records', postgresql_where=sa.text('source_record_id IS NOT NULL'))
    op.drop_index(op.f('ix_paper_source_records_paper_id'), table_name='paper_source_records')
    op.drop_table('paper_source_records')
    op.drop_index(op.f('ix_paper_identifiers_paper_id'), table_name='paper_identifiers')
    op.drop_table('paper_identifiers')
    op.drop_index(op.f('ix_arxiv_task_query_windows_window_start'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_window_end'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_subscription_id'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_status'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_parent_window_id'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_kind'), table_name='arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_query_windows_job_id'), table_name='arxiv_task_query_windows')
    op.drop_table('arxiv_task_query_windows')
    op.drop_index(op.f('ix_arxiv_task_paper_subscriptions_subscription_id'), table_name='arxiv_task_paper_subscriptions')
    op.drop_index(op.f('ix_arxiv_task_paper_subscriptions_paper_id'), table_name='arxiv_task_paper_subscriptions')
    op.drop_table('arxiv_task_paper_subscriptions')
    op.drop_index(op.f('ix_provider_configs_kind'), table_name='provider_configs')
    op.drop_table('provider_configs')
    op.drop_index(op.f('ix_papers_year'), table_name='papers')
    op.drop_index(op.f('ix_papers_status'), table_name='papers')
    op.drop_table('papers')
    op.drop_index(op.f('ix_arxiv_task_subscriptions_enabled'), table_name='arxiv_task_subscriptions')
    op.drop_table('arxiv_task_subscriptions')
    op.drop_index(op.f('ix_arxiv_task_papers_updated_at_source'), table_name='arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_papers_published_at'), table_name='arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_papers_primary_category'), table_name='arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_papers_doi'), table_name='arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_papers_arxiv_id'), table_name='arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_papers_arxiv_base_id'), table_name='arxiv_task_papers')
    op.drop_table('arxiv_task_papers')
    op.drop_index(op.f('ix_arxiv_task_harvest_jobs_status'), table_name='arxiv_task_harvest_jobs')
    op.drop_index(op.f('ix_arxiv_task_harvest_jobs_requested_start'), table_name='arxiv_task_harvest_jobs')
    op.drop_index(op.f('ix_arxiv_task_harvest_jobs_requested_end'), table_name='arxiv_task_harvest_jobs')
    op.drop_index(op.f('ix_arxiv_task_harvest_jobs_kind'), table_name='arxiv_task_harvest_jobs')
    op.drop_table('arxiv_task_harvest_jobs')
    op.drop_index(op.f('ix_arxiv_task_daily_config_status'), table_name='arxiv_task_daily_config')
    op.drop_table('arxiv_task_daily_config')
    op.drop_index(op.f('ix_artifacts_status'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_kind'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_checksum_sha256'), table_name='artifacts')
    op.drop_table('artifacts')
    # ### end Alembic commands ###