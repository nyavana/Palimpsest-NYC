import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type FocusState = {
  docId: string | null;
  version: number;
};

type TourFocusContextValue = {
  focus: FocusState;
  focusDocId: (docId: string) => void;
  clearFocus: () => void;
};

const TourFocusContext = createContext<TourFocusContextValue | null>(null);

export function TourFocusProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<FocusState>({ docId: null, version: 0 });

  const focusDocId = useCallback((docId: string) => {
    setFocus((prev) => ({ docId, version: prev.version + 1 }));
  }, []);

  const clearFocus = useCallback(() => {
    setFocus((prev) => ({ docId: null, version: prev.version + 1 }));
  }, []);

  const value = useMemo<TourFocusContextValue>(
    () => ({ focus, focusDocId, clearFocus }),
    [clearFocus, focus, focusDocId],
  );

  return <TourFocusContext.Provider value={value}>{children}</TourFocusContext.Provider>;
}

export function useTourFocus() {
  const ctx = useContext(TourFocusContext);
  if (ctx === null) {
    throw new Error("useTourFocus must be used inside TourFocusProvider");
  }
  return ctx;
}
