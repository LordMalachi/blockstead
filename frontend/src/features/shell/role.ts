import { createContext, useContext } from "react";
import type { AppRole } from "../../api/client";

export const RoleContext = createContext<AppRole>("owner");
export function useRole(): AppRole { return useContext(RoleContext); }
