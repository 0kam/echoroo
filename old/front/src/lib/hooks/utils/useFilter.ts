import { useCallback, useMemo, useRef, useState } from "react";
import { useDebounce } from "react-use";

import type { Filter } from "@/lib/types";

const _fixed: any[] = [];
const _emptyObject: any = {};

/**
 * Shallow compare two objects for equality.
 */
function shallowEqual<T extends Object>(a: T, b: T): boolean {
  if (a === b) return true;
  const keysA = Object.keys(a) as (keyof T)[];
  const keysB = Object.keys(b) as (keyof T)[];
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    if (a[key] !== b[key]) return false;
  }
  return true;
}

/**
 * A React hook for managing a debounced filter state object.
 * The filter state is debounced by default.
 *
 * @param defaults - The default filter state.
 * @param fixed - An array of keys that cannot be changed.
 * @param debounce - The debounce time in milliseconds.
 * @returns An object with the filter state, a set function, a get function,
 * and utility functions for managing the state.
 */
export default function useFilter<T extends Object>({
  defaults = _emptyObject,
  fixed = _fixed,
  debounce = 500,
}: {
  defaults?: T;
  fixed?: (keyof T)[];
  debounce?: number;
  prefix?: string;
} = {}): Filter<T> {
  const [state, setState] = useState<T>(defaults);
  const [debouncedState, setDebouncedState] = useState<T>(state);
  const prevDefaultsRef = useRef<T>(defaults);

  // Reset the state when defaults actually change (shallow comparison)
  if (!shallowEqual(prevDefaultsRef.current, defaults)) {
    prevDefaultsRef.current = defaults;
    setState(defaults);
    setDebouncedState(defaults);
  }

  const isFixed = useCallback((key: keyof T) => fixed.includes(key), [fixed]);

  const set = useCallback(
    <K extends keyof T>(
      key: K,
      value: (typeof state)[K],
      force: boolean = false,
    ) => {
      if (isFixed(key) && !force) return;
      setState((prev) => ({ ...prev, [key]: value }));
    },
    [isFixed],
  );
  const get = useCallback(
    <K extends keyof T>(key: K): (typeof state)[K] => state[key],
    [state],
  );
  const clear = useCallback(
    <K extends keyof T>(key: K, force: boolean = false) => {
      if (isFixed(key) && !force) return;
      setState((prev) => {
        // Delete the key from a copy of the state
        const newState = { ...prev };
        delete newState[key];

        // Do not debounce when clearing
        setDebouncedState(newState);

        return newState;
      });
    },
    [isFixed],
  );

  const reset = useCallback(() => setState(prevDefaultsRef.current), []);

  const update = useCallback((value: Partial<T>) => {
    setState((prev) => ({ ...prev, ...value }));
  }, []);

  useDebounce(
    () => {
      setDebouncedState(state);
    },
    debounce,
    [state],
  );

  const submit = useCallback(() => {
    setDebouncedState(state);
  }, [state]);

  const size = useMemo(() => {
    // @ts-ignore
    return Object.keys(state).filter((key) => !isFixed(key)).length;
  }, [state, isFixed]);

  return {
    filter: debouncedState,
    update,
    set,
    get,
    clear,
    reset,
    submit,
    size,
    isFixed,
    fixed,
  };
}
