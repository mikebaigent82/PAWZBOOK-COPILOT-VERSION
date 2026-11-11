"use client";

import { useState } from "react";
import { Button, Card, Empty, ErrorBox, PageHeader, Select, Table } from "@/components/ui";
import { api, download } from "@/lib/api";
import { dateText } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Report { id: string; title: string; file_format: "pdf" | "xlsx" | "csv"; filename: string; size_bytes: number; created_at: string; input_hash: string }

const FORMATS = [
  { value: "pdf", label: "PDF: a printable summary to read or share" },
  { value: "xlsx", label: "Excel: every number, year by year" },
  { value: "csv", label: "CSV: raw yearly data for other programs" },
];

export default function Reports() {
  const reports = useApi<Report[]>("/reports");
  const scenarios = useApi<{ scenarios: { id: string; name: string }[] }>("/scenarios");
  const [format, setFormat] = useState("pdf");
  const [scenario, setScenario] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<Report>("/reports", { file_format: format, scenario_id: scenario || null });
      await download(`/reports/${r.id}/download`, r.filename);
      reports.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Reports" intro="Save or print your plan. Every report lists the date, the assumptions used, how current your data is, and a reminder that it is an estimate." />
      <Card title="Make a report" className="mb-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select value={format} onChange={setFormat} options={FORMATS} />
          <Select value={scenario} onChange={setScenario} options={[{ value: "", label: "My current plan" }, ...(scenarios.data?.scenarios ?? []).map((s) => ({ value: s.id, label: `What-if: ${s.name}` }))]} />
        </div>
        <ErrorBox error={error} />
        <Button className="mt-4" busy={busy} onClick={create}>Create and download</Button>
      </Card>
      <Card title="Earlier reports">
        {reports.data?.length === 0 && <Empty title="No reports yet" />}
        {!!reports.data?.length && (
          <Table
            numericFrom={3}
            head={["Report", "Type", "Made on", "Size", ""]}
            rows={reports.data.map((r) => [
              r.title,
              r.file_format.toUpperCase(),
              dateText(r.created_at),
              `${Math.max(1, Math.round(r.size_bytes / 1024))} KB`,
              <span key="a" className="flex justify-end gap-1">
                <Button variant="ghost" className="min-h-8 px-2 text-sm" onClick={() => download(`/reports/${r.id}/download`, r.filename)}>Download</Button>
                <Button variant="ghost" className="min-h-8 px-2 text-sm" onClick={async () => { await api.del(`/reports/${r.id}`); reports.reload(); }}>Delete</Button>
              </span>,
            ])}
          />
        )}
      </Card>
    </>
  );
}
