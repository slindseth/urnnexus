import { useEffect, useState, type ReactNode } from "react";
import {
  IconLayoutGrid as DashboardIcon, IconFolder as ProjectsIcon,
  IconChartBar as AnalysisIcon, IconHeartbeat as HealthIcon,
  IconListDetails as ActivityIcon, IconInfoCircle as AboutIcon,
  IconSun as SunIcon, IconMoon as MoonIcon, IconRefresh,
  IconX, IconCloudDownload, IconAlertTriangle,
} from "@tabler/icons-react";
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
          {dailySync && startupState === "ready" ? <DailySyncBanner state={dailySync} onDismiss={dismissDailySync ?? (() => undefined)} onRetry={retryDailySync ?? (() => undefined)} /> : null}
          <Outlet />
        </div>
      </main>
      {startupState && startupState !== "ready" ? <StartupOverlay state={startupState} error={startupError ?? null} onRetry={retryStartup ?? (() => undefined)} /> : null}
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
  const { healthError, health } = useAppData();

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

      <div className="sidebar__footer">
        <span>Urban Reuse Norway</span>
        <Link to="/health" className="sidebar__service">
          <StatusPill status={health?.appliance_available ? "online" : "pending"} label={health?.appliance_available ? "Tjenestene er klare" : "Se systemstatus"} />
        </Link>
        {healthError ? <div className="sidebar__error">{healthError}</div> : null}
      </div>
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
        {description?.trim() ? <p className="page-header__description">{description}</p> : null}
      </div>
      <div className="page-header__actions">
        <button type="button" className="button button--secondary" onClick={refresh}>
          <IconRefresh size={16} stroke={1.7} aria-hidden="true" />
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

function DailySyncBanner({ state, onDismiss, onRetry }: { state: DailySyncState; onDismiss: () => void; onRetry: () => void }) {
  const isRunning = state.mode === "onboarding";
  return (
    <section className={`sync-banner sync-banner--${state.mode}`} role={isRunning ? "status" : "alert"} aria-live="polite">
      <span className="sync-banner__icon" aria-hidden="true">
        {isRunning ? <IconCloudDownload size={22} stroke={1.7} /> : <IconAlertTriangle size={22} stroke={1.7} />}
      </span>
      <div className="sync-banner__copy">
        <strong>{state.title}</strong>
        <p>{state.message}</p>
        {distinctDetail(state.message, state.detail) ? <small>{state.detail}</small> : null}
      </div>
      <div className="sync-banner__actions">
        {!isRunning ? <button type="button" className="button button--secondary" onClick={onRetry}>{state.mode === "fatal" ? "Prøv synkronisering på nytt" : "Prøv igjen"}</button> : null}
        <Link className="button button--subtle" to="/activity" onClick={onDismiss}>{state.mode === "fatal" ? "Gå til Aktivitet" : "Se detaljer"}</Link>
        <button type="button" className="icon-button" aria-label="Skjul synkmelding" onClick={onDismiss}><IconX size={18} stroke={1.7} aria-hidden="true" /></button>
      </div>
    </section>
  );
}

function distinctDetail(message: string, detail: string | null): string | null {
  if (!detail || detail.trim().toLowerCase() === message.trim().toLowerCase()) {
    return null;
  }
  return detail;
}
