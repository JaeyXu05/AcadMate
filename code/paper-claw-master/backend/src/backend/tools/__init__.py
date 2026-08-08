from backend.tools.paper_acquisition import (
    acquire_paper_artifacts,
    download_arxiv_paper_artifacts,
    download_paper_pdf_from_url,
    mark_paper_artifact_upload_required,
    register_local_paper_pdf,
    register_local_paper_source,
)
from backend.tools.paper_parsing import ingest_paper_document, parse_paper, process_paper_document
from backend.tools.paper_metadata import update_paper_metadata
from backend.tools.paper_qa import embed_paper_chunks, retrieve_paper_evidence
from backend.tools.paper_reports import generate_paper_report
from backend.tools.paper_search import confirm_paper_candidate, get_paper, search_papers
from backend.tools.paper_status import get_active_paper, get_paper_pipeline_status, list_paper_artifacts, list_paper_reports, search_local_papers, set_thread_focus

MAIN_AGENT_TOOLS = [
    get_active_paper,
    set_thread_focus,
    get_paper,
    search_local_papers,
    get_paper_pipeline_status,
    list_paper_artifacts,
    list_paper_reports,
    confirm_paper_candidate,
    update_paper_metadata,
]

DISCOVERY_AGENT_TOOLS = [
    search_papers,
    get_paper,
]

INGESTION_AGENT_TOOLS = [
    get_paper_pipeline_status,
    list_paper_artifacts,
    download_arxiv_paper_artifacts,
    download_paper_pdf_from_url,
    mark_paper_artifact_upload_required,
    ingest_paper_document,
]

EVIDENCE_AGENT_TOOLS = [
    get_paper_pipeline_status,
    retrieve_paper_evidence,
]

REPORT_AGENT_TOOLS = [
    get_paper_pipeline_status,
    list_paper_reports,
    generate_paper_report,
]

PAPER_CLAW_TOOLS = MAIN_AGENT_TOOLS

__all__ = [
    "DISCOVERY_AGENT_TOOLS",
    "EVIDENCE_AGENT_TOOLS",
    "INGESTION_AGENT_TOOLS",
    "MAIN_AGENT_TOOLS",
    "PAPER_CLAW_TOOLS",
    "REPORT_AGENT_TOOLS",
    "acquire_paper_artifacts",
    "confirm_paper_candidate",
    "download_arxiv_paper_artifacts",
    "download_paper_pdf_from_url",
    "embed_paper_chunks",
    "generate_paper_report",
    "get_active_paper",
    "get_paper",
    "get_paper_pipeline_status",
    "ingest_paper_document",
    "list_paper_artifacts",
    "list_paper_reports",
    "mark_paper_artifact_upload_required",
    "parse_paper",
    "process_paper_document",
    "register_local_paper_pdf",
    "register_local_paper_source",
    "retrieve_paper_evidence",
    "search_local_papers",
    "search_papers",
    "set_thread_focus",
    "update_paper_metadata",
]
