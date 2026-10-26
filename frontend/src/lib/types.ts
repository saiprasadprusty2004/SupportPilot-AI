import type { components } from "./api.generated";
export type Theme = "light" | "dark" | "system";
export type Connection = Omit<
  components["schemas"]["ConnectionOut"],
  "created_at"
> & { created_at?: number };
export type Citation = components["schemas"]["CitationOut"];
export type Run = components["schemas"]["RunOut"];
export type Ticket = components["schemas"]["TicketOut"];
export type Action = components["schemas"]["ActionOut"];
export type Document = Omit<
  components["schemas"]["DocumentOut"],
  "embedding_config"
> & { embedding_config?: Record<string, unknown> };
export type Event = components["schemas"]["EventOut"];
export type Session = components["schemas"]["SessionOut"];
export type Page<T> = { items: T[]; next_cursor: string | null };
