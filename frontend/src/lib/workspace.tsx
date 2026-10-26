import { createContext, useContext } from "react";
import type {
  Action,
  Connection,
  Document,
  Run,
  Session,
  Ticket,
} from "./types";

export type WorkspaceData = {
  session: Session;
  role: string;
  preview: boolean;
  tickets: Ticket[];
  runs: Run[];
  actions: Action[];
  documents: Document[];
  connections: Connection[];
  pagination: Record<
    "tickets" | "runs" | "approvals" | "documents",
    { more: boolean; loading: boolean; load: () => void }
  >;
  loading: boolean;
  error: string;
  graphics: boolean;
  setGraphics: (value: boolean) => void;
  refresh: () => void;
  notify: (message: string, kind?: "success" | "error") => void;
  decide: (
    action: Action,
    decision: "approve" | "reject" | "edit",
    args?: Record<string, string | number>,
  ) => Promise<void>;
  startRun: (prompt: string, ticketId?: string) => Promise<Run>;
};
export const WorkspaceContext = createContext<WorkspaceData | null>(null);
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Workspace is not available");
  return value;
}
