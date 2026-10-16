from __future__ import annotations

from html import escape
from xml.etree import ElementTree
from zipfile import ZipFile, BadZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from .routes import get_service
from ..services.project_memory import MemoryAction

router = APIRouter(
    prefix="/api/projects/{project_name}/memory", tags=["project-memory"]
)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_memory(service=Depends(get_service)):
    return service.memory


def explicit_action(request: Request):
    if request.headers.get("x-nexus-action") != "project-memory":
        raise HTTPException(403, "Jobbkontroll må sendes eksplisitt fra Nexus.")


@router.get("/jobs")
def jobs(project_name: str, after: int = Query(0, ge=0), memory=Depends(get_memory)):
    return memory.jobs(project_name, after)


@router.post("/run", status_code=202, dependencies=[Depends(explicit_action)])
def run(project_name: str, payload: MemoryAction, memory=Depends(get_memory)):
    return memory.start(project_name, payload)


@router.get("/jobs/{job_id}")
def status(project_name: str, job_id: str, memory=Depends(get_memory)):
    return memory.status(project_name, job_id)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(explicit_action)])
def cancel(project_name: str, job_id: str, memory=Depends(get_memory)):
    return memory.cancel(project_name, job_id)


@router.get("/jobs/{job_id}/reports")
def reports(
    project_name: str,
    job_id: str,
    after: int = Query(0, ge=0),
    memory=Depends(get_memory),
):
    return memory.reports(project_name, job_id, after)


@router.get("/jobs/{job_id}/reports/{report_id}/download")
def report_download(
    project_name: str, job_id: str, report_id: str, memory=Depends(get_memory)
):
    path, name = memory.report_file(project_name, job_id, report_id)
    return FileResponse(path, filename=name, media_type=DOCX)


@router.get("/jobs/{job_id}/reports/{report_id}/preview", response_class=HTMLResponse)
def report_preview(
    project_name: str, job_id: str, report_id: str, memory=Depends(get_memory)
):
    path, name = memory.report_file(project_name, job_id, report_id)
    try:
        with ZipFile(path) as archive:
            if archive.getinfo("word/document.xml").file_size > 8 * 1024 * 1024:
                raise ValueError("Too large")
            document = ElementTree.fromstring(archive.read("word/document.xml"))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = [
            "".join(t.text or "" for t in p.iter(ns + "t"))
            for p in document.iter(ns + "p")
        ]
    except (OSError, ValueError, KeyError, BadZipFile, ElementTree.ParseError) as exc:
        raise HTTPException(
            422, "Tekstvisningen kunne ikke lages. Last ned Word-dokumentet."
        ) from exc
    url = memory.url(project_name, job_id, f"reports/{report_id}/download")
    body = "".join("<p>" + escape(p) + "</p>" for p in paragraphs)
    return HTMLResponse(
        "<!doctype html><html lang='no'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>"
        + escape(name)
        + "</title><style>body{font:16px/1.6 system-ui;max-width:850px;margin:auto;padding:24px;overflow-wrap:anywhere;background:#f7f5ef;color:#172737}a{color:#174994}p{white-space:pre-wrap}</style>"
        "<h1>"
        + escape(name)
        + "</h1><p>Tekstvisning av den lagrede rapportversjonen. Tabeller, figurer og formatering kan avvike fra Word.</p>"
        "<a href='"
        + escape(url, quote=True)
        + "'>Last ned Word-dokumentet</a><hr>"
        + body
        + "</html>",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/jobs/{job_id}/evidence/{evidence_id}")
def evidence(
    project_name: str, job_id: str, evidence_id: str, memory=Depends(get_memory)
):
    return memory.evidence(project_name, job_id, evidence_id)


@router.get("/jobs/{job_id}/evidence/{evidence_id}/source")
def source(
    project_name: str, job_id: str, evidence_id: str, memory=Depends(get_memory)
):
    path, name = memory.source_file(project_name, job_id, evidence_id)
    return FileResponse(
        path, filename=name, headers={"X-Content-Type-Options": "nosniff"}
    )


@router.get("/jobs/{job_id}/views")
def views(
    project_name: str,
    job_id: str,
    after: int = Query(0, ge=0),
    memory=Depends(get_memory),
):
    return memory.views(project_name, job_id, after)


@router.get("/jobs/{job_id}/units/{unit_id}/source")
def unit_source(
    project_name: str, job_id: str, unit_id: str, memory=Depends(get_memory)
):
    path, name = memory.unit_source_file(project_name, job_id, unit_id)
    return FileResponse(
        path, filename=name, headers={"X-Content-Type-Options": "nosniff"}
    )


@router.get("/jobs/{job_id}/{operation}")
def page(
    project_name: str,
    job_id: str,
    operation: str,
    after: int = Query(0, ge=0),
    memory=Depends(get_memory),
):
    return memory.page(project_name, job_id, operation, after)
