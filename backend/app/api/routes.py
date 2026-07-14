from __future__ import annotations

from html import escape
import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from backend.app.models.health import HealthResponse, ReadinessResponse
from backend.app.models.activity import ActivityEventsResponse, ActivityLogsResponse, ActivityStatusResponse
from backend.app.models.operations import (
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisStatusResponse,
    FileUploadResponse,
    FolderCreateRequest,
    FolderCreateResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectLocalCacheDeleteResponse,
    SyncRunResponse,
    SyncStatusResponse,
)
from backend.app.models.project import (
    ProjectDebugPathsResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectReportsResponse,
)
from backend.app.models.files import ProjectFilesResponse
from backend.app.services.appliance import ApplianceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["appliance"])


def _report_media_type(filename: str) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "doc":
        return "application/msword"
    if suffix == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == "xls":
        return "application/vnd.ms-excel"
    if suffix == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == "ppt":
        return "application/vnd.ms-powerpoint"
    if suffix == "pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if suffix == "pdf":
        return "application/pdf"
    return "application/octet-stream"


def _file_media_type(filename: str) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "doc":
        return "application/msword"
    if suffix == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == "xls":
        return "application/vnd.ms-excel"
    if suffix == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == "ppt":
        return "application/vnd.ms-powerpoint"
    if suffix == "pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if suffix == "pdf":
        return "application/pdf"
    if suffix in {"jpg", "jpeg"}:
        return "image/jpeg"
    if suffix == "png":
        return "image/png"
    if suffix == "txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


OFFICE_PREVIEW_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def _is_office_previewable(filename: str) -> bool:
    return Path(filename).suffix.lower() in OFFICE_PREVIEW_SUFFIXES


def _office_preview_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".doc", ".docx"}:
        return "Word"
    if suffix in {".xls", ".xlsx"}:
        return "Excel"
    if suffix in {".ppt", ".pptx"}:
        return "PowerPoint"
    return "Office"


def _office_preview_url(source_url: str) -> str:
    return f"https://view.officeapps.live.com/op/embed.aspx?src={quote(source_url, safe='')}"


def _preview_html(
    *,
    title: str,
    filename: str,
    download_url: str,
    preview_url: str | None = None,
    preview_note: str | None = None,
) -> HTMLResponse:
    escaped_title = escape(title, quote=True)
    escaped_filename = escape(filename, quote=True)
    escaped_download_url = escape(download_url, quote=True)
    escaped_preview_url = escape(preview_url, quote=True) if preview_url else ""
    preview_markup = (
        f'<iframe class="document-preview__frame" src="{escaped_preview_url}" title="Forhåndsvisning av {escaped_filename}" loading="lazy"></iframe>'
        if preview_url
        else ""
    )
    preview_message = escape(preview_note or "Forhåndsvisningen vises i nettleseren hvis filen er tilgjengelig via en offentlig URL.", quote=True)
    html = f"""<!doctype html>
<html lang="no">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escaped_title}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f5f1e8;
        --surface: #ffffff;
        --surface-muted: #f7f4ee;
        --border: #d8d0c2;
        --text: #1d2733;
        --muted: #586575;
        --accent: #1f5ef2;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        background: linear-gradient(180deg, #f6f2ea 0%, #ede7db 100%);
        color: var(--text);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      .shell {{
        min-height: 100vh;
        display: flex;
        flex-direction: column;
      }}
      .header,
      .footer {{
        background: var(--surface);
        border-bottom: 1px solid var(--border);
        padding: 1rem 1.25rem;
      }}
      .footer {{
        border-bottom: 0;
        border-top: 1px solid var(--border);
      }}
      .eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.72rem;
        color: var(--muted);
        margin-bottom: 0.35rem;
      }}
      h1 {{
        font-size: 1.1rem;
        margin: 0;
      }}
      .meta {{
        margin-top: 0.4rem;
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .body {{
        flex: 1;
        display: grid;
        grid-template-rows: auto 1fr auto;
        gap: 1rem;
        padding: 1rem;
      }}
      .note {{
        background: rgba(255, 255, 255, 0.85);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 0.9rem 1rem;
        color: var(--muted);
        line-height: 1.45;
      }}
      .viewer {{
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 18px;
        overflow: hidden;
        min-height: 70vh;
        box-shadow: 0 18px 42px rgba(31, 41, 55, 0.08);
      }}
      .document-preview__frame {{
        width: 100%;
        height: 100%;
        min-height: 70vh;
        border: 0;
        display: block;
        background: #fff;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        align-items: center;
      }}
      .button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        border: 1px solid var(--accent);
        background: var(--accent);
        color: #fff;
        padding: 0.75rem 1rem;
        text-decoration: none;
        font-weight: 600;
      }}
      .button--secondary {{
        background: transparent;
        color: var(--text);
        border-color: var(--border);
      }}
      .fallback {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <header class="header">
        <div class="eyebrow">{escape(_office_preview_kind(filename), quote=True)}</div>
        <h1>{escaped_filename}</h1>
        <div class="meta">Åpnes i forhåndsvisning i nettleseren. Last ned hvis du vil lagre en lokal kopi.</div>
      </header>
      <div class="body">
        <div class="note">{preview_message}</div>
        <section class="viewer" aria-label="Forhåndsvisning">
          {preview_markup}
        </section>
        <div class="note">
          <div class="actions">
            <a class="button" href="{escaped_download_url}">Last ned</a>
            <a class="button button--secondary" href="{escaped_download_url}" target="_blank" rel="noreferrer">Åpne nedlasting</a>
          </div>
          <div class="fallback">Hvis dokumentet ikke vises her, er det som oftest fordi preview-URLen ikke er offentlig tilgjengelig. Da kan du bruke Last ned.</div>
        </div>
      </div>
      <footer class="footer">
        <div class="meta">Nexus skiller nå mellom forhåndsvisning og nedlasting.</div>
      </footer>
    </main>
  </body>
</html>"""
    return HTMLResponse(content=html)


_FORM_NAME_RE = re.compile(r'name="([^"]+)"')
_FORM_FILENAME_RE = re.compile(r'filename="([^"]*)"')


def _parse_multipart_upload(content_type: str, body: bytes) -> tuple[str, bytes, str | None]:
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if match is None:
        raise ValueError("Upload must be multipart/form-data.")
    boundary = f"--{match.group(1)}".encode("utf-8")
    filename = ""
    file_content: bytes | None = None
    target_folder: str | None = None

    for raw_part in body.split(boundary):
        part = raw_part
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--\r\n"):
            part = part[:-4]
        elif part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--":
            continue
        header_blob, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = _FORM_NAME_RE.search(headers)
        if name_match is None:
            continue
        field_name = name_match.group(1)
        if field_name == "target_folder":
            target_folder = content.decode("utf-8", errors="replace").strip() or None
            continue
        if field_name == "file":
            filename_match = _FORM_FILENAME_RE.search(headers)
            filename = filename_match.group(1).strip() if filename_match else ""
            file_content = content

    if not filename or file_content is None:
        raise ValueError("Multipart upload must contain a file field.")
    return filename, file_content, target_folder


def get_service(request: Request) -> ApplianceService:
    return request.app.state.appliance_service


@router.get("/health", response_model=HealthResponse)
def health(service: ApplianceService = Depends(get_service)) -> HealthResponse:
    return service.health()


@router.get("/system/readiness", response_model=ReadinessResponse)
def readiness(service: ApplianceService = Depends(get_service)) -> ReadinessResponse:
    return service.readiness()


@router.get("/activity/status", response_model=ActivityStatusResponse)
def activity_status(service: ApplianceService = Depends(get_service)) -> ActivityStatusResponse:
    return service.activity_status()


@router.get("/activity/events", response_model=ActivityEventsResponse)
def activity_events(service: ApplianceService = Depends(get_service)) -> ActivityEventsResponse:
    return service.activity_events()


@router.get("/activity/logs", response_model=ActivityLogsResponse)
def activity_logs(service: ApplianceService = Depends(get_service)) -> ActivityLogsResponse:
    return service.activity_logs()


@router.get("/projects", response_model=ProjectListResponse)
def list_projects(
    include_local_cache: bool = Query(False),
    service: ApplianceService = Depends(get_service),
) -> ProjectListResponse:
    return service.list_projects(include_local_cache=include_local_cache)


@router.post("/projects", response_model=ProjectCreateResponse)
def create_project(payload: ProjectCreateRequest, service: ApplianceService = Depends(get_service)) -> ProjectCreateResponse:
    return service.create_project(payload.project_name, folders=payload.folders)


@router.delete("/projects/{project_name}", response_model=ProjectDeleteResponse)
def delete_project(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectDeleteResponse:
    return service.delete_project(project_name)


@router.delete("/projects/{project_name}/local-cache", response_model=ProjectLocalCacheDeleteResponse)
def delete_project_local_cache(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectLocalCacheDeleteResponse:
    return service.delete_project_local_cache(project_name)


@router.post("/sync/run", response_model=SyncRunResponse)
def run_sync(service: ApplianceService = Depends(get_service)) -> SyncRunResponse:
    return service.start_sync()


@router.get("/sync/status", response_model=SyncStatusResponse)
def sync_status(service: ApplianceService = Depends(get_service)) -> SyncStatusResponse:
    return service.sync_status()


@router.post("/analysis/run", response_model=AnalysisRunResponse)
def run_analysis(payload: AnalysisRunRequest, service: ApplianceService = Depends(get_service)) -> AnalysisRunResponse:
    return service.start_analysis(payload.project_name, email_mode=payload.email_mode)


@router.get("/analysis/status", response_model=AnalysisStatusResponse)
def analysis_status(service: ApplianceService = Depends(get_service)) -> AnalysisStatusResponse:
    return service.analysis_status()


@router.get("/projects/{project_name}", response_model=ProjectDetailResponse)
def get_project(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectDetailResponse:
    return service.get_project(project_name)


@router.get("/projects/{project_name}/reports", response_model=ProjectReportsResponse)
def get_reports(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectReportsResponse:
    return service.list_reports(project_name)


@router.get("/projects/{project_name}/reports/{report_id}/open")
def open_report(
    project_name: str,
    report_id: str,
    request: Request,
    service: ApplianceService = Depends(get_service),
) -> Response:
    report = service.open_report(project_name, report_id)
    download_url = str(request.url_for("download_report", project_name=project_name, report_id=report_id))
    if _is_office_previewable(report.report_name):
        return _preview_html(
            title=f"Forhåndsvisning av {report.report_name}",
            filename=report.report_name,
            download_url=download_url,
            preview_url=_office_preview_url(download_url),
        )
    return FileResponse(
        report.report_path,
        filename=report.report_name,
        media_type=_report_media_type(report.report_name),
        content_disposition_type="inline",
    )


@router.get("/projects/{project_name}/reports/{report_id}/download")
def download_report(project_name: str, report_id: str, service: ApplianceService = Depends(get_service)) -> FileResponse:
    report = service.open_report(project_name, report_id)
    return FileResponse(
        report.report_path,
        filename=report.report_name,
        media_type=_report_media_type(report.report_name),
        content_disposition_type="attachment",
    )


@router.get("/projects/{project_name}/files", response_model=ProjectFilesResponse)
def get_files(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectFilesResponse:
    return service.list_files(project_name)


LOCAL_DESKTOP_FILE_SUFFIXES = {".ifc", ".dwg", ".rvt", ".nwd", ".nwc", ".smc"}


def _open_content_disposition(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in LOCAL_DESKTOP_FILE_SUFFIXES:
        return "attachment"
    return "inline"


@router.get("/projects/{project_name}/files/open")
def open_file(
    project_name: str,
    request: Request,
    path: str = Query(..., min_length=1),
    service: ApplianceService = Depends(get_service),
) -> Response:
    file_path, filename = service.resolve_project_file(project_name, path)
    download_url = str(request.url_for("download_file", project_name=project_name).include_query_params(path=path))
    if _is_office_previewable(filename):
        return _preview_html(
            title=f"Forhåndsvisning av {filename}",
            filename=filename,
            download_url=download_url,
            preview_url=_office_preview_url(download_url),
        )
    return FileResponse(
        file_path,
        filename=filename,
        media_type=_file_media_type(filename),
        content_disposition_type=_open_content_disposition(filename),
    )


@router.get("/projects/{project_name}/files/download")
def download_file(
    project_name: str,
    path: str = Query(..., min_length=1),
    service: ApplianceService = Depends(get_service),
) -> FileResponse:
    file_path, filename = service.resolve_project_file(project_name, path)
    return FileResponse(file_path, filename=filename, media_type=_file_media_type(filename), content_disposition_type="attachment")


@router.post("/projects/{project_name}/files/upload", response_model=FileUploadResponse)
async def upload_file(project_name: str, request: Request, service: ApplianceService = Depends(get_service)) -> FileUploadResponse:
    filename, content, form_target_folder = _parse_multipart_upload(request.headers.get("content-type", ""), await request.body())
    target_folder = request.query_params.get("target_folder") or form_target_folder
    return service.upload_file(project_name, filename, content, target_folder=target_folder)


@router.post("/projects/{project_name}/files/folders", response_model=FolderCreateResponse)
def create_folder(project_name: str, payload: FolderCreateRequest, service: ApplianceService = Depends(get_service)) -> FolderCreateResponse:
    return service.create_project_folder(project_name, payload.folder_name, target_folder=payload.target_folder)


@router.get("/projects/{project_name}/debug-paths", response_model=ProjectDebugPathsResponse)
def get_debug_paths(project_name: str, service: ApplianceService = Depends(get_service)) -> ProjectDebugPathsResponse:
    return service.debug_paths(project_name)
