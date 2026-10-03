import {useEffect, useState} from 'react';
import {request} from './api';

type Report = {id: string; name: string; status: string; split: string; summary: Record<string, Record<string, number>>; hardware: {platform: string}; indexing: Record<string, {files: number; chunks: number; total_seconds: number; peak_rss_bytes: number}>};

export function Reports() {
  const [reports, setReports] = useState<Report[]>([]);
  const [error, setError] = useState('');
  async function refresh() {try {setReports(await request('/reports')); setError('');} catch (error) {setError(String(error));}}
  useEffect(() => {refresh();}, []);
  return <section><h2>Retrieval evaluation</h2><button onClick={refresh}>Refresh reports</button>{error && <p role="alert" className="error">{error}</p>}
    {!reports.length && <p className="muted">Run the evaluation CLI with an output directory under .repomap/reports to view results here.</p>}
    {reports.map(report => <article key={report.id}><h3>{report.name || 'Evaluation'} · {report.status}</h3><p>Split: {report.split} · {report.hardware.platform}</p><div style={{overflowX:'auto'}}><table><thead><tr><th>Strategy</th><th>Recall@5</th><th>Recall@10</th><th>Recall@20</th><th>MRR@10</th><th>p50 ms</th><th>p95 ms</th></tr></thead><tbody>
      {Object.entries(report.summary).map(([strategy, metrics]) => <tr key={strategy}><td>{strategy}</td>{['recall@5', 'recall@10', 'recall@20', 'mrr@10', 'p50_ms', 'p95_ms'].map(key => <td key={key}>{metrics[key].toFixed(4)}</td>)}</tr>)}</tbody></table></div>
      <details><summary>Indexing performance</summary>{Object.entries(report.indexing).map(([name, metrics]) => <p key={name}>{name}: {metrics.files} files · {metrics.chunks} chunks · {metrics.total_seconds.toFixed(2)} s · {(metrics.peak_rss_bytes / 1024 / 1024).toFixed(1)} MB peak process RSS</p>)}</details></article>)}
  </section>;
}
