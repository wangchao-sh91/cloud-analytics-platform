import { StrictMode, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError, fields, statuses } from './api';
import type { Page, Server, Status } from './api';
import './style.css';

function Badge({status}: {status: Status}) { return <span className={`badge ${status}`}><i/>{statuses[status]}</span>; }
function ErrorBox({message, retry}: {message: string; retry?: () => void}) {
  return <div className="error" role="alert">{message} {retry && <button onClick={retry}>Try Again</button>}</div>;
}
function useServer(id: string | undefined) {
  const [server, setServer] = useState<Server | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!id) return;
    let active = true;
    setServer(null); setError('');
    api<Server>(`/servers/${id}`).then(s => { if (active) setServer(s); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id, attempt]);
  return {server, error, retry: () => setAttempt(n => n + 1)};
}
function List() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Page | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const query = params.toString();
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api<Page>(`/servers?${query}`).then(d => { if (active) setData(d); })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, attempt]);
  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const values = new FormData(e.currentTarget);
    const next = new URLSearchParams();
    for (const key of ['q', 'model', 'status']) {
      const value = String(values.get(key) || '').trim(); if (value) next.set(key, value);
    }
    if (params.get('page_size')) next.set('page_size', params.get('page_size')!);
    setParams(next);
  }
  const page = Number(params.get('page') || 1);
  const size = Number(params.get('page_size') || 20);
  function changePage(value: number) { const next = new URLSearchParams(params); next.set('page', String(value)); setParams(next); }
  return <>
    <div className="eyebrow">LAB OPERATIONS / ASSET MANAGEMENT</div>
    <div className="page-heading"><div><h1>Physical Servers</h1><p>Your Dell PowerEdge inventory, in one place.</p></div><Link className="button primary" to="/servers/new"><span aria-hidden="true">+</span> Add Server</Link></div>
    <div className="inventory-summary"><div className="summary-icon">▤</div><div><span className="eyebrow">INVENTORY</span><strong>{loading ? '—' : data?.total ?? '—'} <small>{params.get('q') || params.get('model') || params.get('status') ? 'matching servers' : 'registered servers'}</small></strong></div><span className="summary-note">Dell PowerEdge · Manually maintained</span></div>
    <section className="panel">
      <form className="filters" onSubmit={search} key={query}>
        <label className="search">Search inventory<input name="q" defaultValue={params.get('q') || ''} placeholder="Search name, Service Tag or IP…"/></label>
        <label>Model<input name="model" defaultValue={params.get('model') || ''} placeholder="All models"/></label>
        <label>Status<select aria-label="Status" name="status" defaultValue={params.get('status') || ''}><option value="">All statuses</option>{Object.entries(statuses).map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <button className="button secondary" type="submit">Search</button>
        {query && <Link className="clear" to="/servers">Clear</Link>}
      </form>
      {error ? <ErrorBox message={error} retry={() => setAttempt(n => n + 1)}/> : loading ? <div className="empty" role="status">Loading servers…</div> : data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Server / Service Tag</th><th>Model</th><th>Management IP</th><th>Location</th><th>Owner</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{data.items.map(s => <tr key={s.id}><td><Link className="server-name" to={`/servers/${s.id}`}>{s.name}</Link><code>{s.service_tag}</code></td><td>{s.model}</td><td className="mono">{s.management_ip || '—'}</td><td>{[s.lab, s.rack, s.rack_unit ? `U${s.rack_unit}` : null].filter(Boolean).join(' / ') || '—'}</td><td>{s.owner || '—'}</td><td><Badge status={s.status}/></td><td><Link className="row-action" to={`/servers/${s.id}`}>View ↗</Link></td></tr>)}</tbody></table></div> : <div className="empty"><div className="empty-symbol">▤</div><h2>No servers found</h2><p>{query ? 'Try adjusting your search or filters.' : 'Add your first server to start your inventory.'}</p><Link to="/servers/new" className="button secondary">Add Server</Link></div>}
      <div className="pagination"><span>{data?.total ?? 0} servers · Page {page}</span><label>Rows per page<select aria-label="Rows per page" value={size} onChange={e => {const next = new URLSearchParams(params); next.set('page_size', e.target.value); next.delete('page'); setParams(next);}}>{[10,20,50,100].map(n => <option key={n}>{n}</option>)}</select></label><button disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>← Previous</button><button disabled={loading || !data || page * size >= data.total} onClick={() => changePage(page + 1)}>Next →</button></div>
    </section>
  </>;
}
function ServerForm() {
  const {id} = useParams();
  const {server, error: loadError, retry} = useServer(id);
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string,string>>({});
  const [saving, setSaving] = useState(false);
  const submitting = useRef(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (submitting.current) return;
    const form = new FormData(e.currentTarget);
    const payload: Record<string, unknown> = {};
    for (const [key] of fields) { const value = String(form.get(key) || '').trim(); payload[key] = key === 'rack_unit' ? (value ? Number(value) : null) : (value || null); }
    payload.status = form.get('status');
    const validation: Record<string,string> = {};
    for (const key of ['name','service_tag','model']) if (!payload[key]) validation[key] = 'This field is required.';
    if (Object.keys(validation).length) { setFieldErrors(validation); setError('Please check the highlighted fields.'); return; }
    submitting.current = true; setSaving(true); setError(''); setFieldErrors({});
    try {
      const result = await api<Server>(id ? `/servers/${id}` : '/servers', {method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload)});
      navigate(`/servers/${result.id}`);
    } catch (e) { setError((e as Error).message); if (e instanceof ApiError) setFieldErrors(e.fields); }
    finally { submitting.current = false; setSaving(false); }
  }
  if (loadError) return <ErrorBox message={loadError} retry={retry}/>;
  if (id && !server) return <p role="status">Loading server…</p>;
  return <><Link className="back" to={id ? `/servers/${id}` : '/servers'}>← Back to {id ? 'server' : 'inventory'}</Link><div className="page-heading"><div><h1>{id ? 'Edit Server' : 'Add Server'}</h1><p>Keep your asset information up to date. Fields marked * are required.</p></div></div>
    <form className="panel edit-form" onSubmit={submit} noValidate key={id || 'new'}>
      <h2>Server Information</h2>{error && <ErrorBox message={error}/>}
      <div className="form-grid">{fields.map(([key,label]) => {
        const required = ['name','service_tag','model'].includes(key);
        const multiline = ['cpu_summary','memory_summary','disk_summary','purpose','notes'].includes(key);
        const props = {name: key, id: key, defaultValue: server?.[key] ?? '', required, 'aria-invalid': !!fieldErrors[key], 'aria-describedby': fieldErrors[key] ? `${key}-error` : undefined};
        return <label key={key} className={key === 'notes' ? 'full' : ''} htmlFor={key}>{label}{required && ' *'}{multiline ? <textarea {...props} rows={key === 'notes' ? 4 : 2} maxLength={key === 'notes' ? 10000 : 2000}/> : <input {...props} type={key === 'rack_unit' ? 'number' : 'text'} min={key === 'rack_unit' ? 1 : undefined} max={key === 'rack_unit' ? 2147483647 : undefined} maxLength={key === 'service_tag' ? 64 : 255} placeholder={key === 'model' ? 'e.g. PowerEdge R750' : undefined}/>}{fieldErrors[key] && <small className="field-error" id={`${key}-error`}>{fieldErrors[key]}</small>}</label>;
      })}<label>Status<select aria-label="Status" name="status" defaultValue={server?.status || 'available'}>{Object.entries(statuses).map(([v,l]) => <option value={v} key={v}>{l}</option>)}</select>{fieldErrors.status && <small className="field-error">{fieldErrors.status}</small>}</label></div>
      <div className="form-actions"><Link className="button secondary" to={id ? `/servers/${id}` : '/servers'}>Cancel</Link><button className="button primary" disabled={saving}>{saving ? 'Saving…' : id ? 'Save Changes' : 'Add Server'}</button></div>
    </form></>;
}
function Detail() {
  const {id} = useParams(); const {server, error, retry} = useServer(id); const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false); const [deleteError, setDeleteError] = useState('');
  const [confirm, setConfirm] = useState(false); const dialog = useRef<HTMLDialogElement>(null); const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (confirm) { dialog.current?.showModal(); cancel.current?.focus(); } }, [confirm]);
  async function remove() {
    if (deleting) return; setDeleting(true); setDeleteError('');
    try { await api(`/servers/${id}`, {method: 'DELETE'}); navigate('/servers'); }
    catch (e) { setDeleteError((e as Error).message); setDeleting(false); }
  }
  if (error) return <><Link className="back" to="/servers">← Back to inventory</Link><ErrorBox message={error} retry={retry}/></>;
  if (!server) return <p role="status">Loading server…</p>;
  return <><Link className="back" to="/servers">← Back to inventory</Link><div className="page-heading"><div><div className="eyebrow">{server.service_tag}</div><h1>{server.name}</h1><p>{server.model} <span className="dot">·</span> <Badge status={server.status}/></p></div><div className="actions"><Link className="button secondary" to={`/servers/${id}/edit`}>Edit Server</Link><button className="button danger" onClick={() => setConfirm(true)}>Delete Server</button></div></div>
    <section className="panel detail-panel"><h2>Asset Details</h2><dl className="detail-grid">{fields.map(([key,label]) => <div key={key} className={key === 'notes' ? 'full' : ''}><dt>{label}</dt><dd>{server[key] ?? '—'}</dd></div>)}<div><dt>Created</dt><dd>{new Date(server.created_at).toLocaleString('en-US')}</dd></div><div><dt>Last Updated</dt><dd>{new Date(server.updated_at).toLocaleString('en-US')}</dd></div></dl></section>
    {confirm && <dialog ref={dialog} onCancel={e => {if (deleting) e.preventDefault(); else setConfirm(false);}}><h2>Delete Server?</h2><p>Permanently delete <strong>{server.name}</strong> ({server.service_tag})?</p><p>This action cannot be undone. To keep this record, set its status to Retired instead.</p>{deleteError && <ErrorBox message={deleteError}/>}<div className="form-actions"><button ref={cancel} className="button secondary" disabled={deleting} onClick={() => setConfirm(false)}>Cancel</button><button className="button danger" disabled={deleting} onClick={remove}>{deleting ? 'Deleting…' : 'Delete Permanently'}</button></div></dialog>}
  </>;
}
function App() { return <BrowserRouter><div className="app-shell"><aside><Link className="brand" to="/servers"><span className="brand-mark">L</span>LAB<span className="brand-light"> / INVENTORY</span></Link><div className="nav-label">WORKSPACE</div><Link className="nav-item active" to="/servers"><span>▤</span> Physical Servers <span className="nav-arrow">↗</span></Link><div className="sidebar-footer"><span className="local-dot"/> Local Workspace<small>PowerEdge Asset Management</small></div></aside><div className="workspace"><header><span>Infrastructure <span className="breadcrumb">/</span> <strong>Inventory</strong></span><span className="environment">LOCAL LAB</span></header><main><Routes><Route path="/servers" element={<List/>}/><Route path="/servers/new" element={<ServerForm key="create"/>}/><Route path="/servers/:id/edit" element={<ServerForm key="edit"/>}/><Route path="/servers/:id" element={<Detail/>}/><Route path="/" element={<Navigate to="/servers" replace/>}/><Route path="*" element={<><h1>Page Not Found</h1><Link to="/servers">Back to inventory</Link></>}/></Routes><footer>LAB INVENTORY <span>Built for your lab. Maintained by you.</span></footer></main></div></div></BrowserRouter>; }
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
