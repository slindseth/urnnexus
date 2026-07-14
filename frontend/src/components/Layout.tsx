import { useEffect, useState, type ReactNode, type SVGProps } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAppData, type DailySyncState } from "../context/AppDataContext";
import { StatusPill } from "./StatusPill";

export const THEME_STORAGE_KEY = "urn-nexus:theme";
type ThemeMode = "light" | "dark";

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark";
}

function readStoredTheme(): ThemeMode | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeMode(storedTheme) ? storedTheme : null;
  } catch {
    return null;
  }
}

function writeStoredTheme(theme: ThemeMode): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Theme still changes for the current session if storage is unavailable.
  }
}

function getSystemTheme(): ThemeMode {
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function getInitialTheme(): ThemeMode {
  return readStoredTheme() ?? getSystemTheme();
}

function applyTheme(theme: ThemeMode): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

function useThemePreference() {
  const [theme, setTheme] = useState<ThemeMode>(() => getInitialTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return undefined;
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      if (!readStoredTheme()) {
        setTheme(event.matches ? "dark" : "light");
      }
    };

    media.addEventListener?.("change", handleChange);
    return () => media.removeEventListener?.("change", handleChange);
  }, []);

  function toggleTheme() {
    setTheme((currentTheme) => {
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      writeStoredTheme(nextTheme);
      return nextTheme;
    });
  }

  return { theme, toggleTheme };
}

export function AppLayout() {
  const { dailySync, dismissDailySync, retryDailySync, startupState, startupError, retryStartup } = useAppData();
  const { theme, toggleTheme } = useThemePreference();

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="app-main__frame">
          <div className="global-toolbar" aria-label="Globale valg">
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
          </div>
          <Outlet />
        </div>
      </main>
      {startupState && startupState !== "ready" ? <StartupOverlay state={startupState} error={startupError ?? null} onRetry={retryStartup ?? (() => undefined)} /> : null}
      {dailySync && startupState === "ready" ? <DailySyncOverlay state={dailySync} onDismiss={dismissDailySync ?? (() => undefined)} onRetry={retryDailySync ?? (() => undefined)} /> : null}
    </div>
  );
}

function StartupOverlay({ state, error, onRetry }: { state: "starting" | "connecting" | "failed"; error: string | null; onRetry: () => void }) {
  if (state === "failed") {
    return <StartupFailureOverlay error={error} onRetry={onRetry} />;
  }

  return (
    <div className="modal-backdrop modal-backdrop--sync" role="status" aria-live="polite" aria-busy="true">
      <section className="modal-panel modal-panel--sync" aria-labelledby="startup-title" aria-describedby="startup-description">
        <div className="sync-loader" aria-hidden="true" />
        <div className="section-kicker">NEXUS</div>
        <h2 className="section-title" id="startup-title">
          Starter NEXUS
        </h2>
        <p className="modal-copy" id="startup-description">
          Kobler til tjenestene og henter systemstatus.
        </p>
        <div className="sync-loader__detail">Dette tar vanligvis noen sekunder.</div>
      </section>
    </div>
  );
}

function StartupFailureOverlay({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  return (
    <div className="modal-backdrop modal-backdrop--sync" role="alert" aria-live="assertive">
      <section className="modal-panel modal-panel--sync" aria-labelledby="startup-failure-title" aria-describedby="startup-failure-description">
        <div className="section-kicker">NEXUS</div>
        <h2 className="section-title" id="startup-failure-title">
          NEXUS kunne ikke starte
        </h2>
        <p className="modal-copy" id="startup-failure-description">
          {error ?? "Status kunne ikke hentes."}
        </p>
        <div className="modal-panel__actions modal-panel__actions--sync">
          <button type="button" className="button button--secondary" onClick={onRetry}>
            Prøv igjen
          </button>
          <Link className="button" to="/health">
            Se detaljer
          </Link>
        </div>
      </section>
    </div>
  );
}

function ThemeToggle({ theme, onToggle }: { theme: ThemeMode; onToggle: () => void }) {
  const isDark = theme === "dark";
  return (
    <button type="button" className="theme-toggle" aria-label={isDark ? "Bytt til lys modus" : "Bytt til mørk modus"} aria-pressed={isDark} onClick={onToggle}>
      <span className={`theme-toggle__icon ${!isDark ? "theme-toggle__icon--active" : ""}`} aria-hidden="true">
        <SunIcon />
      </span>
      <span className={`theme-toggle__icon ${isDark ? "theme-toggle__icon--active" : ""}`} aria-hidden="true">
        <MoonIcon />
      </span>
    </button>
  );
}

function Sidebar() {
  const { healthError } = useAppData();

  return (
    <aside className="sidebar">
      <Link className="sidebar__brand" to="/about" aria-label="Om URN Nexus">
        <img className="sidebar__logo" src="/brand/urn_nexus_128.png" alt="" aria-hidden="true" />
        <div className="sidebar__brand-text">
          <div className="sidebar__title">URN Nexus</div>
        </div>
      </Link>

      <SidebarSection title="Oversikt">
        <SidebarNavItem to="/" end label="Dashboard" icon={<DashboardIcon />} />
        <SidebarNavItem to="/projects" label="Prosjekter" icon={<ProjectsIcon />} />
      </SidebarSection>

      <SidebarSection title="Arbeid">
        <SidebarNavItem to="/analysis" label="Analyse" icon={<AnalysisIcon />} />
      </SidebarSection>

      <SidebarSection title="Drift">
        <SidebarNavItem to="/health" label="Helse" icon={<HealthIcon />} />
        <SidebarNavItem to="/activity" label="Aktivitet" icon={<ActivityIcon />} />
        <SidebarNavItem to="/about" label="Om" icon={<AboutIcon />} />
      </SidebarSection>

      {healthError ? <div className="sidebar__error">{healthError}</div> : null}
    </aside>
  );
}

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="sidebar-section" aria-label={title}>
      <div className="sidebar-section-title">{title}</div>
      <nav className="sidebar-nav" aria-label={title}>
        {children}
      </nav>
    </section>
  );
}

function SidebarNavItem({
  to,
  end = false,
  label,
  icon,
}: {
  to: string;
  end?: boolean;
  label: string;
  icon: ReactNode;
}) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `sidebar-nav-item ${isActive ? "sidebar-nav-item-active" : ""}`}>
      <span className="sidebar-nav-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="sidebar-nav-label">{label}</span>
    </NavLink>
  );
}

function DashboardIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="2.5" y="2.5" width="4" height="4" rx="1" />
      <rect x="9.5" y="2.5" width="4" height="4" rx="1" />
      <rect x="2.5" y="9.5" width="4" height="4" rx="1" />
      <rect x="9.5" y="9.5" width="4" height="4" rx="1" />
    </svg>
  );
}

function ProjectsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 5.25A1.25 1.25 0 0 1 3.75 4h3l1.2 1.4H12.25A1.25 1.25 0 0 1 13.5 6.65v4.1A1.25 1.25 0 0 1 12.25 12H3.75A1.25 1.25 0 0 1 2.5 10.75z" />
      <path d="M2.5 6.1h11" />
    </svg>
  );
}

function AnalysisIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 11.5h11" />
      <path d="M4.5 9.5l2.1-2.1 1.8 1.5L12 5.3" />
      <circle cx="4.5" cy="9.5" r=".7" fill="currentColor" stroke="none" />
      <circle cx="6.6" cy="7.4" r=".7" fill="currentColor" stroke="none" />
      <circle cx="8.4" cy="8.9" r=".7" fill="currentColor" stroke="none" />
      <circle cx="12" cy="5.3" r=".7" fill="currentColor" stroke="none" />
    </svg>
  );
}

function HealthIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 8h2.1l1.4-2.8 1.8 5.6 1.5-3h4.2" />
      <path d="M13.5 8.2A5.5 5.5 0 0 1 8 13.5 5.5 5.5 0 0 1 2.5 8a5.5 5.5 0 0 1 11 0Z" />
    </svg>
  );
}

function ActivityIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 4.5h10" />
      <path d="M3 8h6.5" />
      <path d="M3 11.5h10" />
      <circle cx="11.8" cy="8" r=".8" fill="currentColor" stroke="none" />
    </svg>
  );
}

function AboutIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 7.2v3.6" />
      <path d="M8 5.1h.01" />
    </svg>
  );
}

function SunIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="8" cy="8" r="2.6" />
      <path d="M8 1.8v1.3" />
      <path d="M8 12.9v1.3" />
      <path d="m3.6 3.6.9.9" />
      <path d="m11.5 11.5.9.9" />
      <path d="M1.8 8h1.3" />
      <path d="M12.9 8h1.3" />
      <path d="m3.6 12.4.9-.9" />
      <path d="m11.5 4.5.9-.9" />
    </svg>
  );
}

function MoonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M13.4 9.5A5.2 5.2 0 0 1 6.5 2.6 5.5 5.5 0 1 0 13.4 9.5Z" />
    </svg>
  );
}

export function AppHeader({
  title,
  description,
  eyebrow = null,
}: {
  title: string;
  description?: string;
  eyebrow?: string | null;
}) {
  const { refresh } = useAppData();
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <div className="page-header__eyebrow">{eyebrow}</div> : null}
        <h1 className="page-header__title">{title}</h1>
        {description ? <p className="page-header__description">{description}</p> : null}
      </div>
      <div className="page-header__actions">
        <button type="button" className="button button--secondary" onClick={refresh}>
          Oppdater visning
        </button>
      </div>
    </header>
  );
}

export function ProjectHeader({
  title,
  breadcrumbPath,
  sourceLabel,
  status,
  meta,
  statusLabel,
  actions,
}: {
  title: string;
  breadcrumbPath: string;
  sourceLabel: string;
  status: string;
  meta?: string[];
  statusLabel?: string;
  actions?: ReactNode;
}) {
  return (
    <section className="project-header">
      <div>
        <h1 className="project-header__title">{title}</h1>
        <div className="project-header__meta">
          <StatusPill status={status} label={statusLabel} />
          {(meta ?? []).map((item) => (
            <span key={item} className="project-header__meta-item">
              {item}
            </span>
          ))}
        </div>
      </div>
      {actions ? <div className="project-header__actions">{actions}</div> : null}
    </section>
  );
}

function DailySyncOverlay({ state, onDismiss, onRetry }: { state: DailySyncState; onDismiss: () => void; onRetry: () => void }) {
  if (state.mode === "onboarding") {
    return <OnboardingOverlay title={state.title} message={state.message} detail={state.detail} />;
  }
  if (state.mode === "warning") {
    return <RecoverableWarningOverlay title={state.title} message={state.message} detail={state.detail} onDismiss={onDismiss} onRetry={onRetry} />;
  }
  return <FatalSyncErrorOverlay title={state.title} message={state.message} detail={state.detail} onRetry={onRetry} />;
}

function OnboardingOverlay({ title, message, detail }: { title: string; message: string; detail: string | null }) {
  return (
    <div className="modal-backdrop modal-backdrop--sync" role="presentation">
      <section className="modal-panel modal-panel--sync" role="status" aria-live="polite" aria-busy="true" aria-labelledby="daily-sync-title" aria-describedby="daily-sync-description">
        <div className="sync-loader" aria-hidden="true" />
        <div className="section-kicker">OneDrive</div>
        <h2 className="section-title" id="daily-sync-title">
          {title}
        </h2>
        <p className="modal-copy" id="daily-sync-description">
          {message}
        </p>
        {detail ? <div className="sync-loader__detail">{detail}</div> : null}
      </section>
    </div>
  );
}

function RecoverableWarningOverlay({
  title,
  message,
  detail,
  onDismiss,
  onRetry,
}: {
  title: string;
  message: string;
  detail: string | null;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="modal-backdrop modal-backdrop--sync" role="presentation">
      <section className="modal-panel modal-panel--sync" role="dialog" aria-modal="true" aria-labelledby="sync-warning-title" aria-describedby="sync-warning-description">
        <div className="section-kicker">OneDrive</div>
        <h2 className="section-title" id="sync-warning-title">{title}</h2>
        <p className="modal-copy" id="sync-warning-description">{message}</p>
        {distinctDetail(message, detail) ? <div className="sync-loader__detail">{detail}</div> : null}
        <div className="modal-panel__actions modal-panel__actions--sync">
          <button type="button" className="button button--secondary" onClick={onRetry}>Prøv igjen</button>
          <Link className="button" to="/activity" onClick={onDismiss}>Se detaljer</Link>
        </div>
      </section>
    </div>
  );
}

function FatalSyncErrorOverlay({ title, message, detail, onRetry }: { title: string; message: string; detail: string | null; onRetry: () => void }) {
  return (
    <div className="modal-backdrop modal-backdrop--sync" role="presentation">
      <section className="modal-panel modal-panel--sync" role="alertdialog" aria-modal="true" aria-labelledby="sync-failure-title" aria-describedby="sync-failure-description">
        <div className="section-kicker">OneDrive</div>
        <h2 className="section-title" id="sync-failure-title">{title}</h2>
        <p className="modal-copy" id="sync-failure-description">{message}</p>
        {distinctDetail(message, detail) ? <div className="sync-loader__detail">{detail}</div> : null}
        <div className="modal-panel__actions modal-panel__actions--sync">
          <button type="button" className="button button--secondary" onClick={onRetry}>Prøv synkronisering på nytt</button>
          <Link className="button" to="/activity">Gå til Aktivitet</Link>
        </div>
      </section>
    </div>
  );
}

function distinctDetail(message: string, detail: string | null): string | null {
  if (!detail || detail.trim().toLowerCase() === message.trim().toLowerCase()) {
    return null;
  }
  return detail;
}
