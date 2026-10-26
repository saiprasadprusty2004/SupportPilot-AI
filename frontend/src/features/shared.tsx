import { useWorkspace } from "../lib/workspace";
import { Button } from "../components/ui";

export function Heading({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading feature-heading">
      <div>
        <div className="welcome-line">
          <span className="greeting-dot" />
          {eyebrow}
        </div>
        <h1>
          {title}
          <span className="mint">.</span>
        </h1>
        <p>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}
export function useError() {
  const { notify } = useWorkspace();
  return (error: unknown) => notify((error as Error).message, "error");
}

export function LoadMore({
  collection,
}: {
  collection: "tickets" | "runs" | "approvals" | "documents";
}) {
  const value = useWorkspace().pagination[collection];
  if (!value.more) return null;
  return (
    <div className="load-more">
      <Button variant="secondary" disabled={value.loading} onClick={value.load}>
        {value.loading ? "Loading…" : "Load more"}
      </Button>
    </div>
  );
}
