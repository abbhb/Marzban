import { z } from "zod";
import { fetch } from "service/http";

export const categories = ["basic", "connection", "cascade", "advanced"] as const;
export type Category = typeof categories[number];
export const categoryFor = (field: string): Category => field.startsWith("cascade_") ? "cascade"
  : ["sni", "host", "path", "security", "alpn", "fingerprint", "allowinsecure", "use_sni_as_host"].includes(field) ? "connection"
  : ["fragment_setting", "noise_setting", "mux_enable", "random_user_agent"].includes(field) ? "advanced" : "basic";

const hostSchema = z.object({
  remark: z.string().refine(value => !!value.trim(), "hostsPage.required"),
  address: z.string().refine(value => !!value.trim(), "hostsPage.required"),
  port: z.number({ invalid_type_error: "hostsPage.invalidPort" }).int("hostsPage.invalidPort").min(1, "hostsPage.invalidPort").max(65535, "hostsPage.invalidPort").nullable(),
  path: z.string().nullable(), sni: z.string().nullable(), host: z.string().nullable(),
  security: z.string(), alpn: z.string(), fingerprint: z.string(),
  mux_enable: z.boolean().nullable(), allowinsecure: z.boolean().nullable(), is_disabled: z.boolean().nullable(),
  fragment_setting: z.string().nullable(), noise_setting: z.string().nullable(),
  random_user_agent: z.boolean().nullable(), use_sni_as_host: z.boolean().nullable(),
  cascade_mode: z.enum(["off", "replace", "additional"]),
  cascade_entry_id: z.number().int().positive().nullable(),
  cascade_entry_yaml: z.string().max(32768, "hostsPage.yamlTooLong").nullable(),
}).superRefine((host, context) => {
  if (host.cascade_mode !== "off" && !!host.cascade_entry_id === !!host.cascade_entry_yaml?.trim()) {
    for (const field of ["cascade_entry_id", "cascade_entry_yaml"]) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: "cascade.errors.cascade_choose_one_entry" });
    }
  }
});
export const formSchema = z.object({ routes: z.array(z.object({ inbound: z.string(), value: hostSchema })) });
export type Host = z.infer<typeof hostSchema>;
export type HostForm = z.infer<typeof formSchema>;
export type HostMap = Record<string, Host[]>;
export type Inbound = { tag: string; protocol: string; network: string; tls: string; port: number | string; node_ids?: number[] | null };

// Older panels omit node_ids from /inbounds. Use the sudo-only core endpoint
// until the backend is upgraded, then retain only the non-secret scope fields.
export const fetchInboundScopes = async (signal?: AbortSignal): Promise<Inbound[]> => {
  const options = { signal, timeout: 15000 };
  const groups = await fetch<Record<string, Inbound[]>>("/inbounds", options);
  const inbounds = Object.values(groups).flat();
  if (inbounds.every(inbound => Object.prototype.hasOwnProperty.call(inbound, "node_ids"))) return inbounds;
  const core = await fetch<{ inbounds: Array<{ tag: string; "x-marzban-node-ids"?: number[] }> }>("/core/config", options);
  const scopes = new Map(core.inbounds.map(inbound => [inbound.tag, inbound["x-marzban-node-ids"] || null]));
  return inbounds.map(inbound => ({ ...inbound, node_ids: scopes.get(inbound.tag) ?? null }));
};

export const newHost = (): Host => ({
  remark: "", address: "", port: null, path: null, sni: null, host: null,
  security: "inbound_default", alpn: "", fingerprint: "", mux_enable: false,
  allowinsecure: null, is_disabled: false, fragment_setting: null, noise_setting: null,
  random_user_agent: false, use_sni_as_host: false, cascade_mode: "off", cascade_entry_id: null, cascade_entry_yaml: null,
});
export const normalizeHosts = (hosts: HostMap): HostMap => Object.fromEntries(Object.entries(hosts).map(([tag, rows]) => [tag, rows.map(row => ({ ...newHost(), ...row }))]));
export const flattenHosts = (hosts: HostMap): HostForm => ({ routes: Object.entries(hosts).flatMap(([inbound, rows]) => rows.map(value => ({ inbound, value }))) });
export const groupHosts = (routes: HostForm["routes"], tags: string[]): HostMap => {
  const result: HostMap = Object.fromEntries(tags.map(tag => [tag, []]));
  for (const row of routes) (result[row.inbound] ||= []).push(row.value);
  return result;
};
export const endpoint = (host: Host, inbound?: Inbound) => `${host.address?.includes(":") ? `[${host.address}]` : host.address || "—"}:${host.port ?? inbound?.port ?? "—"}`;
const canonical = (value: any): any => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
export const same = (left: unknown, right: unknown) => JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
