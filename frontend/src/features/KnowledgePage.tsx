import { useRef, useState } from "react";

import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  FileText,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  Modal,
  ProviderIcon,
  SectionHeading,
  Time,
} from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api, post } from "../lib/api";

import type { Citation } from "../lib/types";

import { Heading, LoadMore, useError } from "./shared";
export default function KnowledgePage() {
  const data = useWorkspace();
  const [term, setTerm] = useState("");
  const [searchResults, setSearchResults] = useState<Citation[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [driveOpen, setDriveOpen] = useState(false);
  const [driveFiles, setDriveFiles] = useState<
    { id: string; name: string; mimeType: string }[]
  >([]);
  const [publish, setPublish] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const report = useError();
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    if (data.preview) {
      data.notify(
        "Preview only. Uploads are available in the connected application.",
      );
      return;
    }
    setBusy(true);
    try {
      for (const file of files) {
        if (file.size > 25 * 1024 * 1024)
          throw new Error("Files must be 25 MB or smaller");
        const form = new FormData();
        form.append("file", file);
        await api("/documents", { method: "POST", body: form });
      }
      data.refresh();
      data.notify("Upload complete. Your pilot is indexing the documents.");
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  async function find() {
    if (!term.trim()) return;
    if (data.preview) {
      setSearchResults(data.actions[0]?.citations || []);
      return;
    }
    setBusy(true);
    try {
      const result = await post<{ items: Citation[] }>("/search", {
        query: term,
      });
      setSearchResults(result.items);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function drive() {
    setDriveOpen(true);
    if (data.preview) {
      setDriveFiles([
        { id: "demo", name: "Getting started guide", mimeType: "Google Doc" },
      ]);
      return;
    }
    try {
      setDriveFiles(
        (await api<{ items: typeof driveFiles }>("/documents/drive/files"))
          .items,
      );
    } catch (e) {
      report(e);
    }
  }
  return (
    <div className="page-enter">
      <Heading
        eyebrow="ANSWERS WITH SOMETHING TO STAND ON"
        title="Your source of truth"
        subtitle="Give your pilot the knowledge to turn good questions into great answers."
      >
        <Button onClick={() => input.current?.click()} disabled={busy}>
          <Plus size={16} />
          Add documents
        </Button>
      </Heading>
      <input
        ref={input}
        type="file"
        hidden
        multiple
        accept=".pdf,.docx,.txt,.md"
        onChange={(e) => void upload(e.target.files)}
      />
      <div className="knowledge-top-grid">
        <div
          className="upload-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            void upload(e.dataTransfer.files);
          }}
        >
          <span className="upload-icon">
            <Upload size={25} />
          </span>
          <h3>A little knowledge goes a long way.</h3>
          <p>
            Drop your documents here, or{" "}
            <button onClick={() => input.current?.click()}>browse files</button>
          </p>
          <small>PDF, DOCX, TXT, or Markdown · Up to 25 MB each</small>
        </div>
        <div className="panel knowledge-connect">
          <span className="provider-tile">
            <ProviderIcon provider="googledrive" size={28} />
          </span>
          <h3>Your docs. Already connected.</h3>
          <p>
            Bring selected Google Drive files into your team’s shared knowledge.
          </p>
          <Button variant="secondary" onClick={() => void drive()}>
            Import from Drive
            <ArrowUpRight size={14} />
          </Button>
        </div>
      </div>
      <div className="panel knowledge-search">
        <Sparkles size={18} />
        <input
          aria-label="Search your knowledge"
          placeholder="Ask a question across your documents…"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void find()}
        />
        <Button
          variant="secondary"
          disabled={busy || !term.trim()}
          onClick={() => void find()}
        >
          Search
          <ArrowRight size={14} />
        </Button>
      </div>
      {searchResults && (
        <div className="search-passage-list">
          {searchResults.length ? (
            searchResults.map((c) => (
              <article className="panel search-passage" key={c.chunk_id}>
                <span>
                  <FileText size={16} />
                  {c.name}
                  <Badge status="ready">Page {c.page}</Badge>
                </span>
                <p>{c.excerpt}</p>
              </article>
            ))
          ) : (
            <Empty
              title="No supporting passages found"
              description="Try a more specific query or add relevant product documentation."
            />
          )}
        </div>
      )}
      <section className="panel document-list">
        <SectionHeading title="Your knowledge library">
          <span className="subtle-count">
            {data.documents.length} documents
          </span>
        </SectionHeading>
        {data.documents.map((doc) => (
          <div className="document-row" key={doc.id}>
            <span
              className={`document-icon ${doc.source_url ? "doc-drive" : ""}`}
            >
              {doc.source_url ? (
                <ProviderIcon provider="googledrive" size={23} />
              ) : (
                <FileText size={24} />
              )}
            </span>
            <div className="document-info">
              <strong>{doc.name}</strong>
              <span>
                {(doc.size / 1024).toFixed(0)} KB · Version {doc.version} ·{" "}
                <Time at={doc.created_at} />
              </span>
              {doc.error && <small className="field-error">{doc.error}</small>}
            </div>
            <Badge status={doc.status} />
            <button
              className="icon-button"
              aria-label={"Refresh " + doc.name}
              onClick={async () => {
                if (data.preview) {
                  data.notify("Preview: document refresh requested");
                  return;
                }
                try {
                  await post("/documents/" + doc.id + "/refresh", {});
                  data.refresh();
                } catch (e) {
                  report(e);
                }
              }}
            >
              <RefreshCw size={15} />
            </button>
            <button
              className="icon-button danger-text"
              aria-label={"Delete " + doc.name}
              onClick={async () => {
                if (data.preview) {
                  data.notify(
                    "Preview: sample documents are kept for exploration",
                  );
                  return;
                }
                try {
                  await api("/documents/" + doc.id, { method: "DELETE" });
                  data.refresh();
                  data.notify("Document removed from future searches");
                } catch (e) {
                  report(e);
                }
              }}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {!data.documents.length && (
          <Empty
            icon={<BookOpen size={26} />}
            title="Good answers start here"
            description="Upload your first product guide, policy, or help article."
          />
        )}
        <LoadMore collection="documents" />
        <div className="panel-footer">
          <ShieldCheck size={13} />
          <span>
            Shared with your workspace. Cited in every supported answer.
          </span>
        </div>
      </section>
      <Modal
        open={driveOpen}
        onOpenChange={setDriveOpen}
        title="Bring your knowledge along"
        description="Importing creates a shared workspace snapshot. Your original Drive file stays unchanged."
      >
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={publish}
            onChange={(e) => setPublish(e.target.checked)}
          />
          I confirm these selected files may be searched by my entire workspace.
        </label>
        <div className="drive-file-list">
          {driveFiles.map((file) => (
            <div key={file.id}>
              <FileText size={18} />
              <span>{file.name}</span>
              <Button
                variant="secondary"
                disabled={!publish}
                onClick={async () => {
                  if (data.preview) {
                    data.notify("Preview: no file was imported");
                    return;
                  }
                  try {
                    await post("/documents/drive/import", {
                      file_id: file.id,
                      publish_to_workspace: true,
                    });
                    data.refresh();
                    data.notify(
                      "Drive snapshot imported and queued for indexing",
                    );
                    setDriveOpen(false);
                  } catch (e) {
                    report(e);
                  }
                }}
              >
                Import
                <Plus size={13} />
              </Button>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
