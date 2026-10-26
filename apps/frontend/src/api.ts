export const statuses = {
  available: 'Available', in_use: 'In Use', maintenance: 'Under Maintenance', retired: 'Retired',
} as const;
export type Status = keyof typeof statuses;
export const fields = [
  ['name', 'Server Name'], ['service_tag', 'Service Tag'], ['model', 'Model'],
  ['management_ip', 'Management IP'], ['idrac_ip', 'iDRAC IP'],
  ['lab', 'Laboratory'], ['rack', 'Rack'], ['rack_unit', 'Rack Unit'],
  ['cpu_summary', 'CPU'], ['memory_summary', 'Memory'], ['disk_summary', 'Storage'],
  ['owner', 'Owner'], ['purpose', 'Purpose'], ['notes', 'Notes'],
] as const;
export type Field = typeof fields[number][0];
export type Server = Record<Exclude<Field, 'rack_unit'>, string | null> & {
  id: string; name: string; service_tag: string; model: string;
  rack_unit: number | null; status: Status; created_at: string; updated_at: string;
};
export type Page = {items: Server[]; total: number; page: number; page_size: number};
export class ApiError extends Error {
  constructor(message: string, public status: number, public fields: Record<string, string> = {}) { super(message); }
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  } catch {
    throw new ApiError('Unable to connect. Check your connection and try again.', 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.message || 'Something went wrong. Please try again.', response.status, body.field_errors);
  }
  return response.status === 204 ? undefined as T : response.json();
}
