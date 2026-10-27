import {
  Alert, AlertIcon, Badge, Box, Button, Checkbox, Divider, FormControl,
  FormErrorMessage, FormLabel, HStack, Input, Select, SimpleGrid, Spinner,
  Switch, Text, VStack, useToast,
} from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage, fetch } from "service/http";

type Connection = Record<string, any>;
type Profile = { label: string; enabled?: boolean; address?: string; port?: number; streamSettings?: Connection };
type Row = Profile & { uid: string };
type Inbound = { tag: string; path: string; defaults: Connection; profiles: Profile[] };
type Settings = { revision: string; limit: number; inbounds: Inbound[] };
type Errors = Record<string, string>;
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const transport = (connection: Connection): Connection => connection.xhttpSettings || connection.splithttpSettings || {};
const effective = (connection: Connection): Connection => {
  const raw = transport(connection);
  return raw.extra ? { ...raw.extra, path: raw.path || "", host: raw.host || "", mode: raw.mode || "auto" } : raw;
};
const setTransport = (connection: Connection, updates: Connection): Connection => {
  const result = copy(connection);
  const key = result.xhttpSettings ? "xhttpSettings" : result.splithttpSettings ? "splithttpSettings" : "xhttpSettings";
  const raw = result[key] ||= {};
  for (const [name, value] of Object.entries(updates)) {
    const target = raw.extra && !["path", "host", "mode"].includes(name) ? raw.extra : raw;
    if (value === undefined) delete target[name];
    else target[name] = value;
  }
  return result;
};
const uplink = (row: Profile, defaults: Connection): Connection => row.streamSettings
  ? { ...row.streamSettings, address: row.address, port: row.port }
  : { ...copy(defaults.streamSettings || {}), address: defaults.address, port: defaults.port };
const endpoint = (address: string, port: number): string => `${address?.includes(":") ? `[${address}]` : address || "—"}:${port || "—"}`;
const withUplink = (row: Row, connection: Connection): Row => {
  const { address, port, ...streamSettings } = connection;
  return { ...row, address, port, streamSettings };
};

const ConnectionEditor = ({ connection, onChange, prefix, errors, down = false }: {
  connection: Connection; onChange: (value: Connection) => void; prefix: string; errors: Errors; down?: boolean;
}) => {
  const { t } = useTranslation();
  const settings = effective(connection);
  const security = connection.security || "none";
  const tls = connection[`${security}Settings`] || {};
  const field = (name: string, value: string | number, change: (value: string) => void, options: { type?: string; readOnly?: boolean; hint?: string } = {}) => (
    <FormControl isInvalid={!!errors[`${prefix}-${name}`]}>
      <FormLabel htmlFor={`${prefix}-${name}`} fontSize="sm">{t(`xhttp.${name}`)}</FormLabel>
      <Input id={`${prefix}-${name}`} value={value} type={options.type || "text"} isReadOnly={options.readOnly}
        onChange={event => change(event.target.value)} autoComplete="off" />
      {options.hint && <Text fontSize="xs" color="fg.muted" mt={1}>{options.hint}</Text>}
      <FormErrorMessage>{errors[`${prefix}-${name}`]}</FormErrorMessage>
    </FormControl>
  );
  const changeTls = (updates: Connection) => onChange({ ...connection, [`${security}Settings`]: { ...tls, ...updates } });
  const changeMux = (name: string, value: string) => {
    const xmux = { ...settings.xmux };
    if (value) xmux[name] = value; else delete xmux[name];
    onChange(setTransport(connection, { xmux }));
  };
  return <VStack align="stretch" spacing={4}>
    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
      {field("address", connection.address || "", address => onChange({ ...connection, address }), { hint: t("xhttp.addressHelp") })}
      {field("port", connection.port ?? "", port => onChange({ ...connection, port: port ? Number(port) : undefined }), { type: "number" })}
      <FormControl><FormLabel htmlFor={`${prefix}-security`} fontSize="sm">{t("xhttp.security")}</FormLabel>
        <Select id={`${prefix}-security`} value={security} onChange={event => {
          const next = event.target.value;
          onChange({ ...connection, security: next, ...(next === "none" ? {} : {
            [`${next}Settings`]: connection[`${next}Settings`] || { serverName: tls.serverName || "", fingerprint: tls.fingerprint || "chrome", alpn: tls.alpn || ["h2"] },
          }) });
        }}><option value="tls">TLS</option><option value="reality">REALITY</option><option value="none">HTTP</option></Select>
      </FormControl>
      {security !== "none" && field("serverName", tls.serverName || "", serverName => changeTls({ serverName }))}
      {field("host", settings.host || "", host => onChange(setTransport(connection, { host })))}
      {field("path", settings.path || "", () => {}, { readOnly: true, hint: t("xhttp.pathHelp") })}
      {security !== "none" && field("alpn", (tls.alpn || ["h2"]).join(","), alpn => changeTls({ alpn: alpn.split(",").map(value => value.trim()).filter(Boolean) }))}
      {security !== "none" && field("fingerprint", tls.fingerprint || "chrome", fingerprint => changeTls({ fingerprint }))}
      {security === "reality" && field("publicKey", tls.publicKey || tls.password || "", publicKey => {
        const next = { ...tls, publicKey }; delete next.password;
        onChange({ ...connection, realitySettings: next });
      })}
      {security === "reality" && field("shortId", tls.shortId || "", shortId => changeTls({ shortId }))}
      {!down && <FormControl><FormLabel htmlFor={`${prefix}-mode`} fontSize="sm">{t("xhttp.mode")}</FormLabel>
        <Select id={`${prefix}-mode`} value={settings.mode || "auto"} onChange={event => onChange(setTransport(connection, { mode: event.target.value }))}>
          {["packet-up", "auto", "stream-up", "stream-one"].map(value => <option key={value} value={value}>{value}</option>)}
        </Select></FormControl>}
      {field("maxConcurrency", settings.xmux?.maxConcurrency ?? "", value => changeMux("maxConcurrency", value), { hint: "16-32" })}
      {field("hMaxReusableSecs", settings.xmux?.hMaxReusableSecs ?? "", value => changeMux("hMaxReusableSecs", value), { hint: "1800-3000" })}
    </SimpleGrid>
    {security === "tls" && <Checkbox isChecked={!!tls.allowInsecure} onChange={event => changeTls({ allowInsecure: event.target.checked })}>{t("xhttp.allowInsecure")}</Checkbox>}
  </VStack>;
};

export const XhttpProfiles = ({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [rows, setRows] = useState<Record<string, Row[]>>({});
  const [tag, setTag] = useState("");
  const [expanded, setExpanded] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const errorRef = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const clean = (values: Row[]) => values.map(({ uid, ...profile }) => profile);
  const changes = Object.fromEntries((settings?.inbounds || []).filter(inbound =>
    JSON.stringify(clean(rows[inbound.tag] || [])) !== JSON.stringify(inbound.profiles)
  ).map(inbound => [inbound.tag, clean(rows[inbound.tag] || [])]));
  const dirty = Object.keys(changes).length > 0;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  const accept = (value: Settings) => {
    setSettings(value);
    setRows(Object.fromEntries(value.inbounds.map(inbound => [inbound.tag, inbound.profiles.map(profile => ({ ...profile, uid: `xhttp-${++sequence.current}` }))])));
    setTag(current => value.inbounds.some(inbound => inbound.tag === current) ? current : value.inbounds[0]?.tag || "");
    setErrors({}); setExpanded("");
  };
  const load = async () => {
    if (dirty && !window.confirm(t("xhttp.discard"))) return;
    setBusy(true); setError("");
    try { accept(await fetch<Settings>("/core/xhttp-profiles")); }
    catch (e) { setError(errorMessage(e, t("commerce.loadError"))); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const update = (uid: string, transform: (row: Row) => Row) => {
    setRows(current => ({ ...current, [tag]: current[tag].map(row => row.uid === uid ? transform(row) : row) }));
    setErrors({}); setError("");
  };
  const move = (index: number, delta: number) => setRows(current => {
    const values = [...current[tag]];
    [values[index], values[index + delta]] = [values[index + delta], values[index]];
    return { ...current, [tag]: values };
  });
  const validate = (): Errors => {
    const found: Errors = {};
    for (const values of Object.values(rows)) {
      const labels = new Set<string>();
      for (const row of values) {
        if (!row.label.trim()) found[`${row.uid}-label`] = t("xhttp.required");
        else if (labels.has(row.label.trim())) found[`${row.uid}-label`] = t("xhttp.duplicateName");
        labels.add(row.label.trim());
        if (!row.streamSettings) continue;
        const validateConnection = (connection: Connection, prefix: string) => {
          if (!connection.address?.trim()) found[`${prefix}-address`] = t("xhttp.required");
          if (!Number.isInteger(connection.port) || connection.port < 1 || connection.port > 65535) found[`${prefix}-port`] = t("xhttp.invalidPort");
          const security = connection.security || "none";
          const tls = connection[`${security}Settings`] || {};
          if (security !== "none" && !tls.serverName?.trim()) found[`${prefix}-serverName`] = t("xhttp.required");
          if (security !== "none" && (!tls.alpn?.length || tls.alpn.some((a: string) => !["h2", "http/1.1", "h3"].includes(a)))) found[`${prefix}-alpn`] = t("xhttp.invalidAlpn");
          if (security === "reality" && !/^[A-Za-z0-9_-]{43}$/.test(tls.publicKey || tls.password || "")) found[`${prefix}-publicKey`] = t("xhttp.invalidKey");
          if (security === "reality" && !/^(?:[0-9a-fA-F]{2}){0,8}$/.test(tls.shortId || "")) found[`${prefix}-shortId`] = t("xhttp.invalidShortId");
          for (const name of ["maxConcurrency", "hMaxReusableSecs"]) {
            const value = effective(connection).xmux?.[name];
            if (value === undefined || value === "") continue;
            const numbers = String(value).split("-").map(Number);
            if (!/^\d+(?:-\d+)?$/.test(String(value)) || numbers[0] > numbers[numbers.length - 1]) found[`${prefix}-${name}`] = t("xhttp.invalidRange");
          }
        };
        const up = uplink(row, {});
        validateConnection(up, `${row.uid}-up`);
        const down = effective(up).downloadSettings;
        if (down) validateConnection(down, `${row.uid}-down`);
      }
    }
    return found;
  };
  const save = async () => {
    if (!settings || busy) return;
    const invalid = validate(); setErrors(invalid); setError("");
    if (Object.keys(invalid).length) {
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }
    setBusy(true);
    try {
      accept(await fetch<Settings>("/core/xhttp-profiles", { method: "PUT", body: { revision: settings.revision, inbounds: changes } }));
      toast({ title: t("xhttp.saved"), status: "success", isClosable: true });
    } catch (e) {
      setError(errorMessage(e, t("commerce.saveError")));
      requestAnimationFrame(() => errorRef.current?.focus());
    } finally { setBusy(false); }
  };
  const inbound = settings?.inbounds.find(item => item.tag === tag);
  const values = rows[tag] || [];
  const reveal = (id: string) => {
    const entry = Object.entries(rows).find(([, items]) => items.some(row => id.startsWith(row.uid + "-")));
    if (!entry) return;
    setTag(entry[0]);
    setExpanded(entry[1].find(row => id.startsWith(row.uid + "-"))!.uid);
    requestAnimationFrame(() => document.getElementById(id)?.focus());
  };
  return <VStack align="stretch" spacing={4} py={4}>
    <Text color="fg.muted" fontSize="sm">{t("xhttp.help")}</Text>
    <HStack flexWrap="wrap" justify="space-between">
      <Button type="button" variant="ghost" onClick={load} isDisabled={busy}>{t("xhttp.reload")}</Button>
      <Button type="button" colorScheme="primary" onClick={save} isLoading={busy && !!settings} isDisabled={!dirty || busy}>{t("xhttp.save")}{dirty ? " *" : ""}</Button>
    </HStack>
    {(error || Object.keys(errors).length > 0) && <Box ref={errorRef} tabIndex={-1} role="alert" borderWidth="1px" borderColor="red.400" borderRadius="md" p={3}>
      {error && <Text>{error}</Text>}
      {Object.entries(errors).map(([id, message]) => <Button key={id} display="block" variant="link" whiteSpace="normal" textAlign="start" mt={2} onClick={() => reveal(id)}>{t("xhttp.fixField")}: {t(`xhttp.${id.split("-").slice(-1)[0]}`)} — {message}</Button>)}
    </Box>}
    {!settings && busy && <Spinner alignSelf="center" />}
    {settings && !inbound && <Text>{t("xhttp.emptyInbounds")}</Text>}
    {inbound && <>
      <FormControl><FormLabel htmlFor="xhttp-inbound">{t("xhttp.inbound")}</FormLabel>
        <Select id="xhttp-inbound" value={tag} isDisabled={busy} onChange={event => { setTag(event.target.value); setExpanded(""); }}>
          {settings!.inbounds.map(item => <option key={item.tag} value={item.tag}>{item.tag}</option>)}
        </Select>
      </FormControl>
      <HStack justify="space-between"><Text fontSize="sm">{t("xhttp.count", { active: values.filter(row => row.enabled !== false).length, total: values.length, limit: settings!.limit })}</Text>
        <Button size="sm" type="button" isDisabled={busy || values.length >= settings!.limit} onClick={() => {
          const uid = `xhttp-${++sequence.current}`;
          setRows(current => ({ ...current, [tag]: [...current[tag], { uid, label: "", enabled: true }] })); setExpanded(uid);
        }}>{t("xhttp.add")}</Button>
      </HStack>
      {!values.length && <Alert status="info"><AlertIcon />{t("xhttp.emptyProfiles")}</Alert>}
      <Box as="fieldset" disabled={busy} border={0} p={0} m={0} minW={0}>
        <VStack align="stretch" spacing={3}>
          {values.map((row, index) => {
            const up = uplink(row, inbound.defaults);
            const down = effective(up).downloadSettings;
            const editing = expanded === row.uid;
            return <Box key={row.uid} borderWidth="1px" borderRadius="md" p={{ base: 3, md: 4 }}>
              <HStack justify="space-between" align={{ base: "stretch", md: "start" }} flexDirection={{ base: "column", md: "row" }} spacing={3}>
                <Box minW={0} flex="1" overflowWrap="anywhere"><HStack align="start"><Badge flexShrink={0} mt={1}>{index + 1}</Badge><Text fontWeight="semibold">{row.label || t("xhttp.unnamed")}</Text></HStack>
                  <Text fontSize="xs" color="fg.muted" mt={2}>{t("xhttp.uplink")}: {endpoint(up.address, up.port)}</Text>
                  <Text fontSize="xs" color="fg.muted">{t("xhttp.downlink")}: {down ? endpoint(down.address || up.address, down.port || up.port) : t("xhttp.sameUplink")}</Text>
                </Box>
                <FormControl display="flex" alignItems="center" w="auto" gap={2}><FormLabel htmlFor={`${row.uid}-enabled`} mb={0} fontSize="sm">{row.enabled !== false ? t("xhttp.enabled") : t("xhttp.disabled")}</FormLabel>
                  <Switch id={`${row.uid}-enabled`} aria-label={`${row.label} ${t("xhttp.enableInSubscription")}`} isChecked={row.enabled !== false} onChange={event => update(row.uid, item => ({ ...item, enabled: event.target.checked }))} />
                </FormControl>
              </HStack>
              <HStack mt={3} flexWrap="wrap" spacing={2}>
                <Button type="button" size="sm" aria-expanded={editing} aria-controls={`${row.uid}-editor`} onClick={() => setExpanded(editing ? "" : row.uid)}>{editing ? t("xhttp.collapse") : t("xhttp.edit")}</Button>
                <Button type="button" size="sm" variant="ghost" aria-label={`${row.label} ${t("xhttp.up")}`} isDisabled={index === 0} onClick={() => move(index, -1)}>{t("xhttp.up")}</Button>
                <Button type="button" size="sm" variant="ghost" aria-label={`${row.label} ${t("xhttp.down")}`} isDisabled={index === values.length - 1} onClick={() => move(index, 1)}>{t("xhttp.down")}</Button>
                <Button type="button" size="sm" variant="ghost" colorScheme="red" onClick={() => setRows(current => ({ ...current, [tag]: current[tag].filter(item => item.uid !== row.uid) }))}>{t("xhttp.remove")}</Button>
              </HStack>
              {editing && <VStack id={`${row.uid}-editor`} align="stretch" spacing={5} mt={5}>
                <FormControl isInvalid={!!errors[`${row.uid}-label`]}><FormLabel htmlFor={`${row.uid}-label`}>{t("xhttp.label")}</FormLabel>
                  <Input id={`${row.uid}-label`} maxLength={150} value={row.label} onChange={event => update(row.uid, item => ({ ...item, label: event.target.value }))} />
                  <FormErrorMessage>{errors[`${row.uid}-label`]}</FormErrorMessage>
                </FormControl>
                <Checkbox isChecked={!row.streamSettings} onChange={event => update(row.uid, item => {
                  if (!event.target.checked) return withUplink(item, uplink({ label: item.label }, inbound.defaults));
                  const next = { ...item }; delete next.streamSettings; delete next.address; delete next.port; return next;
                })}>{t("xhttp.inherit")}</Checkbox>
                {row.streamSettings && <>
                  <Text fontWeight="semibold">{t("xhttp.uplink")}</Text>
                  <ConnectionEditor connection={up} prefix={`${row.uid}-up`} errors={errors} onChange={value => update(row.uid, item => withUplink(item, value))} />
                  <Divider />
                  <Checkbox isChecked={!!down} onChange={event => update(row.uid, item => {
                    const connection = uplink(item, inbound.defaults);
                    const separate = event.target.checked ? copy(connection) : undefined;
                    if (separate) {
                      separate.xhttpSettings = { path: inbound.path, host: effective(connection).host || "", ...(effective(connection).xmux ? { xmux: copy(effective(connection).xmux) } : {}) };
                      delete separate.splithttpSettings;
                    }
                    return withUplink(item, setTransport(connection, { downloadSettings: separate }));
                  })}>{t("xhttp.separateDownlink")}</Checkbox>
                  {down && <><Text fontWeight="semibold">{t("xhttp.downlink")}</Text>
                    <ConnectionEditor connection={down} prefix={`${row.uid}-down`} errors={errors} down onChange={value => update(row.uid, item => withUplink(item, setTransport(uplink(item, inbound.defaults), { downloadSettings: value })))} />
                  </>}
                </>}
              </VStack>}
            </Box>;
          })}
        </VStack>
      </Box>
      <Text fontSize="xs" color="fg.muted">{t("xhttp.refreshHelp")}</Text>
    </>}
  </VStack>;
};
