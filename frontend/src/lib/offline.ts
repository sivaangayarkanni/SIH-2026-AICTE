// Offline-first upload queue: IndexedDB stores the file + form fields while offline and replays them when online.
import { useEffect, useState } from 'react'
import { getToken } from './api'

const DB = 'sealcheck-offline', STORE = 'uploads'
export type QueuedUpload = { id?: number; appId: number; docType: string; labType?: string; name: string; type: string; blob: Blob; queuedAt: string }

function open(): Promise<IDBDatabase> {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1)
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true })
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error)
  })
}
async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open()
  return new Promise((res, rej) => { const q = fn(db.transaction(STORE, mode).objectStore(STORE)); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error) })
}
export const queueUpload = (u: QueuedUpload) => tx('readwrite', (s) => s.add(u)).then((x) => { window.dispatchEvent(new Event('sealcheck:queue')); return x })
export const listQueue = () => tx<QueuedUpload[]>('readonly', (s) => s.getAll() as IDBRequest<QueuedUpload[]>)
export const removeQueued = (id: number) => tx('readwrite', (s) => s.delete(id)).then(() => window.dispatchEvent(new Event('sealcheck:queue')))

export async function uploadNow(appId: number, docType: string, file: Blob, name: string, labType?: string) {
  const fd = new FormData(); fd.append('file', file, name); fd.append('doc_type', docType); if (labType) fd.append('lab_type', labType)
  const r = await fetch(`/api/applications/${appId}/documents`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${getToken()}` } })
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail } catch { /* */ } throw new Error(m) }
  return r.json()
}

export async function syncQueue(): Promise<{ sent: number; failed: string[] }> {
  if (!navigator.onLine) return { sent: 0, failed: [] }
  const items = await listQueue(); let sent = 0; const failed: string[] = []
  for (const it of items) {
    try { await uploadNow(it.appId, it.docType, it.blob, it.name, it.labType); await removeQueued(it.id!); sent++ }
    catch (e: any) { failed.push(`${it.name}: ${e.message}`); if (!navigator.onLine) break }
  }
  if (sent) window.dispatchEvent(new CustomEvent('sealcheck:synced', { detail: sent }))
  return { sent, failed }
}

export function useOnline() {
  const [on, setOn] = useState(navigator.onLine)
  useEffect(() => {
    const a = () => { setOn(true); syncQueue() }, b = () => setOn(false)
    window.addEventListener('online', a); window.addEventListener('offline', b)
    return () => { window.removeEventListener('online', a); window.removeEventListener('offline', b) }
  }, [])
  return on
}

export function useQueueCount() {
  const [n, setN] = useState(0)
  useEffect(() => {
    const f = () => listQueue().then((x) => setN(x.length)).catch(() => {})
    f(); window.addEventListener('sealcheck:queue', f); window.addEventListener('sealcheck:synced', f)
    return () => { window.removeEventListener('sealcheck:queue', f); window.removeEventListener('sealcheck:synced', f) }
  }, [])
  return n
}
