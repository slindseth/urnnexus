import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getUserFacingErrorMessage } from "./api";
import {
  memoryJobs,
  memoryStatus,
  startMemory,
  type MemoryJobs,
  type MemoryStatus,
} from "./memory";

/** Only lightweight reads on mount. Job identity lives in the appliance and URL. */
export function useMemoryJob(project: string) {
  const [search, setSearch] = useSearchParams();
  const requested = search.get("job");
  const [listing, setListing] = useState<MemoryJobs | null>(null);
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [revision, setRevision] = useState(0);
  const launching = useRef<{
    until: number;
    prior: string | null;
    resume: boolean;
    updatedAt?: string;
  } | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError(null);
    setStatus(null);
    async function load() {
      try {
        const list = await memoryJobs(project);
        if (!active) return;
        setListing(list);
        const launch = launching.current;
        const id =
          launch && !launch.resume && list.jobs[0]?.id !== launch.prior
            ? list.jobs[0]?.id
            : (requested ?? list.jobs[0]?.id);
        if (id) {
          if (!requested && !launch) {
            setSearch(
              (old) => {
                const next = new URLSearchParams(old);
                next.set("job", id);
                return next;
              },
              { replace: true },
            );
            return;
          }
          const value = await memoryStatus(project, id);
          if (!active) return;
          setStatus(value);
          if (
            launch &&
            (launch.resume
              ? value.worker_active || value.job.updated_at !== launch.updatedAt
              : id !== launch.prior)
          ) {
            launching.current = null;
            setStarting(false);
            if (!launch.resume)
              setSearch(
                (old) => {
                  const next = new URLSearchParams(old);
                  next.set("job", id);
                  return next;
                },
                { replace: true },
              );
          }
        }
        if (
          launching.current &&
          !list.worker_active &&
          Date.now() > launching.current.until
        ) {
          launching.current = null;
          setStarting(false);
          setActionError(
            "Arbeideren startet ingen ny jobb. Kontroller appliance-konfigurasjonen og prøv igjen.",
          );
        }
        if (active && (list.worker_active || launching.current))
          timer = setTimeout(() => void load(), 2000);
        setError(null);
      } catch (reason) {
        if (active) {
          setError(
            getUserFacingErrorMessage(
              reason,
              "Gjennomgangen kunne ikke hentes. Prøv igjen.",
            ),
          );
          setStarting(false);
          launching.current = null;
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [project, requested, revision, setSearch]);

  const reload = () => setRevision((value) => value + 1);
  async function run(mode: "incremental" | "full" | "resume") {
    if (starting) return;
    setActionError(null);
    setStarting(true);
    try {
      await startMemory(
        project,
        mode,
        mode === "resume" ? status?.job.job_id : undefined,
      );
      launching.current = {
        until: Date.now() + 10_000,
        prior: listing?.jobs[0]?.id ?? null,
        resume: mode === "resume",
        updatedAt: status?.job.updated_at,
      };
      reload();
    } catch (reason) {
      setActionError(
        getUserFacingErrorMessage(reason, "Analysen kunne ikke startes."),
      );
      setStarting(false);
    }
  }
  const select = (id: string) =>
    setSearch((old) => {
      const next = new URLSearchParams(old);
      next.set("job", id);
      return next;
    });
  async function older() {
    if (listing?.next_after == null) return;
    try {
      const next = await memoryJobs(project, listing.next_after);
      setListing((current) =>
        current ? { ...next, jobs: [...current.jobs, ...next.jobs] } : next,
      );
    } catch (reason) {
      setActionError(
        getUserFacingErrorMessage(reason, "Eldre jobber kunne ikke hentes."),
      );
    }
  }
  return {
    listing,
    status,
    loading,
    error,
    starting,
    actionError,
    run,
    select,
    older,
    reload,
    revision,
  };
}
