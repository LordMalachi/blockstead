import { createContext, useContext } from "react";

export interface WalkthroughContextValue {
  active: boolean;
  start: () => void;
  close: () => void;
}

export const WalkthroughContext = createContext<WalkthroughContextValue | null>(null);

export function useWalkthrough(): WalkthroughContextValue {
  const value = useContext(WalkthroughContext);
  if (!value) throw new Error("useWalkthrough must be used inside WalkthroughProvider");
  return value;
}
