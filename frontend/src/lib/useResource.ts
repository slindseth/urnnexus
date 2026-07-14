import { useEffect, useState, type DependencyList } from "react";
import { getUserFacingErrorMessage } from "./api";

interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useResource<T>(loader: () => Promise<T>, dependencies: DependencyList): ResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadIndex, setReloadIndex] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    Promise.resolve()
      .then(loader)
      .then((value) => {
        if (active) {
          setData(value);
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setData(null);
          setError(getUserFacingErrorMessage(reason, "Kunne ikke laste inn data."));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [...dependencies, reloadIndex]);

  return {
    data,
    loading,
    error,
    reload: () => setReloadIndex((value) => value + 1),
  };
}
