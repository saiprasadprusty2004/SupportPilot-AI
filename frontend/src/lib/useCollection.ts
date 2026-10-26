import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Page } from "./types";

export function useCollection<T>(
  name: string,
  workspaceId: string,
  enabled: boolean,
  interval: number,
) {
  const query = useInfiniteQuery({
    queryKey: [name, workspaceId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page<T>>(
        `/${name}?limit=50${pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""}`,
      ),
    getNextPageParam: (page) => page.next_cursor || undefined,
    enabled,
    refetchInterval: interval,
  });
  return {
    ...query,
    data: query.data
      ? {
          items: query.data.pages.flatMap((page) => page.items),
          next_cursor: query.data.pages.at(-1)?.next_cursor || null,
        }
      : undefined,
  };
}
