export type ApiStatus = "unknown" | "skipped_no_changes" | "completed" | "completed_with_warnings" | "failed" | string;
export type AnalysisStatus =
  | "idle"
  | "startup_pending"
  | "running"
  | "completed"
  | "failed"
  | "auth_failed"
  | "sync_failed";
export type AnalysisAuthStatus = "unknown" | "ok" | "auth_failed" | "sync_failed";

export interface ApiError {
  code: string;
  detail: string;
}

export type ActivityState =
  | "Klar"
  | "Starter"
  | "Starter synkronisering"
  | "Kobler til OneDrive"
  | "Henter endringer"
  | "Synkroniserer prosjekt"
  | "Laster ned filer"
  | "Oppdaterer lokal status"
  | "Fullfører synkronisering"
  | "Synkronisering fullført"
  | "Synkronisering fullført uten endringer"
  | "Synkronisering feilet"
  | "Synkroniserer"
  | "Analyserer"
  | "Genererer rapport"
  | "Sender e-post"
  | "Feilet";
export type ActivityLevel = "INFO" | "SUCCESS" | "WARNING" | "ERROR";
export type ActivityCategory = "Sync" | "Analysis" | "System" | "OneDrive" | "Report" | "Error";
export type ActivityRunMode = "sync_only" | "analysis" | "unknown";
export type SyncStrategy = "delta" | "full" | "fallback_full" | "unknown";

export interface SyncPerformance {
  total_duration_seconds?: number | null;
  authentication_seconds?: number | null;
  graph_query_seconds?: number | null;
  downloads_seconds?: number | null;
  local_state_update_seconds?: number | null;
  finalization_seconds?: number | null;
  graph_requests?: number | null;
  downloaded_bytes?: number | null;
}

export interface ActivityStatusResponse {
  state: ActivityState;
  activity: string | null;
  status: string | null;
  project_name: string | null;
  uptime: string;
  uptime_seconds: number;
  backend_version: string | null;
  appliance_available: boolean;
  last_synced_at: string | null;
  last_analyzed_at: string | null;
  updated_at: string;
  job_type?: "sync" | "analysis" | null;
  job_id?: string | null;
  run_mode?: ActivityRunMode;
  event_code?: string | null;
  current_phase?: string | null;
  current_project?: string | null;
  progress?: number | null;
  sync_strategy?: SyncStrategy;
  sync_strategy_reason?: string | null;
  performance?: SyncPerformance | null;
}

export interface ActivityEvent {
  timestamp: string;
  level: ActivityLevel;
  project_name: string | null;
  component: string | null;
  message: string;
  category?: ActivityCategory;
  source?: string | null;
  event_code?: string | null;
  phase?: string | null;
  run_mode?: ActivityRunMode;
  job_type?: "sync" | "analysis" | null;
  job_id?: string | null;
}

export interface ActivityError {
  timestamp: string;
  project_name: string | null;
  component: string | null;
  message: string;
  category?: "Error";
  source?: string | null;
  event_code?: string | null;
  phase?: string | null;
  run_mode?: ActivityRunMode;
  job_type?: "sync" | "analysis" | null;
  job_id?: string | null;
}

export interface ActivityEventsResponse {
  updated_at: string;
  events: ActivityEvent[];
  errors: ActivityError[];
}

export interface ActivityLogEntry {
  timestamp: string;
  level: ActivityLevel;
  project_name: string | null;
  component: string | null;
  message: string;
  category?: ActivityCategory;
  source?: string | null;
  event_code?: string | null;
  phase?: string | null;
  run_mode?: ActivityRunMode;
  job_type?: "sync" | "analysis" | null;
  job_id?: string | null;
}

export interface ActivityLogsResponse {
  updated_at: string;
  entries: ActivityLogEntry[];
}

export interface HealthResponse {
  appliance_available: boolean;
  uptime_seconds: number;
  uptime: string;
  version: string | null;
  appliance_root: string;
  discovered_projects: number;
  last_synced_at: string | null;
  last_analyzed_at: string | null;
  latest_report_generated_at: string | null;
  project_count: number;
  file_count: number;
  report_count: number;
  one_drive_status: string;
  one_drive_detail: string | null;
  graph_write_status: string;
  graph_write_detail: string | null;
  openai_status: string;
  openai_detail: string | null;
  smtp_status: string;
  smtp_detail: string | null;
  disk_total_bytes: number | null;
  disk_used_bytes: number | null;
  disk_free_bytes: number | null;
  cache_size_bytes: number | null;
  errors_last_24h: number;
  warnings_last_24h: number;
}

export type StartupState = "starting" | "connecting" | "ready" | "failed";

export type ErrorCategory =
  | "Startup"
  | "Backend"
  | "Appliance"
  | "OneDrive"
  | "Graph Authentication"
  | "Synchronization"
  | "Analysis"
  | "Unknown";

export interface ReadinessResponse {
  ready: boolean;
  backend: boolean;
  appliance: boolean;
  graph: boolean;
  status: string;
  code?: string | null;
  detail?: string | null;
}

export interface ProjectSummary {
  project_name: string;
  display_name: string;
  source_label: string;
  relative_project_path: string;
  hidden_internal_path: string;
  last_synced_at: string | null;
  latest_comment_document: string | null;
  latest_comment_document_open_url: string | null;
  latest_comment_created_at: string | null;
  latest_comment_modified_at: string | null;
  comment_document_count: number;
  is_sample_project: boolean;
  is_local_cache_only?: boolean;
  project_path: string;
  last_analyzed_at: string | null;
  status: ApiStatus;
  file_count: number;
  report_count: number;
  warnings: string[];
  errors: string[];
}

export interface ProjectListResponse {
  count: number;
  projects: ProjectSummary[];
  warnings: string[];
}

export interface ProjectAnalysisInfo {
  status: ApiStatus;
  last_analyzed_at: string | null;
  provider: string | null;
  model: string | null;
  documents_seen: number | null;
  chunks_created: number | null;
  report_items_count: number | null;
  output_docx_path: string | null;
  run_summary_path: string | null;
  warnings_count: number;
  errors_count: number;
}

export interface ProjectReport {
  report_id: string;
  report_name: string;
  report_path: string;
  report_type: string;
  version: string | null;
  created_at: string | null;
  generated_at: string | null;
  modified_at: string;
  size_bytes: number;
  is_latest: boolean;
  open_url: string;
  download_url: string;
}

export interface CountFacet {
  value: string;
  label: string;
  count: number;
}

export interface FileNode {
  name: string;
  path: string;
  relative_path?: string;
  display_name?: string;
  kind: "folder" | "file";
  file_count: number;
  folder_category: string | null;
  extension: string | null;
  size_bytes: number | null;
  modified_at: string | null;
  open_url?: string | null;
  download_url?: string | null;
  children: FileNode[];
}

export interface FileFilters {
  folder_categories: CountFacet[];
  extensions: CountFacet[];
}

export interface ProjectFilesResponse {
  display_name: string;
  source_label: string;
  relative_project_path: string;
  hidden_internal_path: string;
  last_synced_at: string | null;
  latest_comment_document: string | null;
  latest_comment_document_open_url: string | null;
  latest_comment_created_at: string | null;
  latest_comment_modified_at: string | null;
  comment_document_count: number;
  is_sample_project: boolean;
  is_local_cache_only?: boolean;
  project_name: string;
  project_path: string;
  total_files: number;
  file_tree: FileNode;
  filters: FileFilters;
  warnings: string[];
  errors: string[];
}

export interface ProjectReportsResponse {
  display_name: string;
  source_label: string;
  relative_project_path: string;
  hidden_internal_path: string;
  last_synced_at: string | null;
  latest_comment_document: string | null;
  latest_comment_document_open_url: string | null;
  latest_comment_created_at: string | null;
  latest_comment_modified_at: string | null;
  comment_document_count: number;
  is_sample_project: boolean;
  is_local_cache_only?: boolean;
  project_name: string;
  project_path: string;
  count: number;
  reports: ProjectReport[];
  warnings: string[];
  errors: string[];
}

export interface ProjectDetailResponse extends ProjectSummary {
  analysis: ProjectAnalysisInfo | null;
  reports: ProjectReport[];
}

export interface ProjectDebugPathsResponse {
  project_name: string;
  resolved_project_path: string;
  project_path_exists: boolean;
  total_files_on_disk: number;
  counted_source_files: number;
  comment_documents_found: number;
  first_20_files_on_disk: string[];
  ignored_file_count: number;
  ignored_reasons: string[];
}

export interface ProjectCreateRequest {
  project_name: string;
  template?: string | null;
  folders?: string[];
}

export interface ProjectCreateResponse {
  project_name: string;
  relative_project_path: string;
  mode: "onedrive";
  folders_created: string[];
  warning: string | null;
}

export interface ProjectLocalCacheDeleteResponse {
  project_name: string;
  hidden: boolean;
  removed_paths: string[];
  removed_state_rows: number;
  message: string;
}

export interface ProjectDeleteResponse {
  project_name: string;
  deleted_remote_path: string;
  deleted: boolean;
  existed: boolean;
  synced: boolean;
  message: string;
}

export interface FileUploadResponse {
  project_name: string;
  filename: string;
  target_folder: string;
  relative_path: string;
  size_bytes: number;
  mode: "onedrive" | "local_cache_only";
  warning: string | null;
}

export interface FolderCreateRequest {
  folder_name: string;
  target_folder?: string | null;
}

export interface FolderCreateResponse {
  project_name: string;
  folder_name: string;
  target_folder: string;
  relative_path: string;
  mode: "onedrive" | "local_cache_only";
  warning: string | null;
}

export interface SyncRunResponse {
  job_id: string;
  running: boolean;
  started_at: string;
  status: string;
  sync_only: boolean;
  analysis_started: boolean;
  reports_generated: number;
  projects_synced: number;
  files_changed: number;
  reports_found: number;
  job_type?: "sync";
  requested_by?: string;
  requested_at?: string | null;
  current_phase?: string | null;
  current_project?: string | null;
  progress?: number | null;
  process_id?: number | null;
  appliance_run_id?: string | null;
  run_mode?: ActivityRunMode;
  event_code?: string | null;
  sync_strategy?: SyncStrategy;
  sync_strategy_reason?: string | null;
  remote_items_examined?: number;
  files_downloaded?: number;
  files_deleted?: number;
  elapsed_seconds?: number | null;
  performance?: SyncPerformance | null;
}

export interface SyncStatusResponse {
  running: boolean;
  process_alive: boolean;
  lock_exists: boolean;
  lock_stale: boolean;
  activity: "sync" | "analysis" | "idle";
  job_id: string | null;
  last_started_at: string | null;
  last_completed_at: string | null;
  last_error: string | null;
  error_code?: string | null;
  projects_synced: number;
  files_changed: number;
  reports_found: number;
  status: string;
  job_type?: "sync";
  requested_by?: string;
  requested_at?: string | null;
  current_phase?: string | null;
  current_project?: string | null;
  progress?: number | null;
  process_id?: number | null;
  appliance_run_id?: string | null;
  run_mode?: ActivityRunMode;
  event_code?: string | null;
  sync_strategy?: SyncStrategy;
  sync_strategy_reason?: string | null;
  remote_items_examined?: number;
  files_downloaded?: number;
  files_deleted?: number;
  elapsed_seconds?: number | null;
  performance?: SyncPerformance | null;
}

export interface AnalysisRunRequest {
  project_name?: string | null;
  email_mode: "daily_digest" | "immediate";
}

export interface AnalysisRunResponse {
  job_id: string;
  running: boolean;
  started_at: string;
  status: string;
  analysis_started: boolean;
  reports_generated: number;
  projects_synced: number;
  files_changed: number;
  reports_found: number;
  email_mode: "daily_digest" | "immediate";
  project_name: string | null;
  job_type?: "analysis";
  requested_by?: string;
  requested_at?: string | null;
  current_phase?: string | null;
  current_project?: string | null;
  progress?: number | null;
  process_id?: number | null;
  appliance_run_id?: string | null;
  run_mode?: ActivityRunMode;
  event_code?: string | null;
}

export interface AnalysisStatusResponse {
  running: boolean;
  process_alive: boolean;
  lock_exists: boolean;
  lock_stale: boolean;
  activity: "sync" | "analysis" | "idle";
  job_id: string | null;
  start_requested_at: string | null;
  last_started_at: string | null;
  last_completed_at: string | null;
  startup_grace_active: boolean;
  process_spawned: boolean;
  auth_status: AnalysisAuthStatus;
  last_error: string | null;
  last_start_error: string | null;
  error_code?: string | null;
  projects_synced: number;
  files_changed: number;
  reports_found: number;
  reports_generated: number;
  email_mode: "daily_digest" | "immediate" | null;
  project_name: string | null;
  status: AnalysisStatus;
  analysis_started: boolean;
  job_type?: "analysis";
  requested_by?: string;
  requested_at?: string | null;
  current_phase?: string | null;
  current_project?: string | null;
  progress?: number | null;
  process_id?: number | null;
  appliance_run_id?: string | null;
  run_mode?: ActivityRunMode;
  event_code?: string | null;
}
