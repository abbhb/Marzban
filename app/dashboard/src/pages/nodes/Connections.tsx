import {
  Alert, AlertIcon, Badge, Box, Button, Flex, FormControl, FormLabel, HStack,
  Input, Select, SimpleGrid, Spinner, Table, TableContainer, Tbody, Td, Text,
  Th, Thead, Tr,
} from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getAuthToken } from "utils/authStorage";
import { ConnectionRecord, ConnectionSnapshot } from "./types";

type StreamState = "connecting" | "connected" | "paused" | "offline" | "error" | "unauthorized";
const pathFor = (row: ConnectionRecord) => `${row.source_family || "?"} → ${row.egress_family || "?"}`;

export const Connections = ({ nodeId, inbound = "" }: { nodeId: number; inbound?: string }) => {
  const { t, i18n } = useTranslation();
  const [snapshot, setSnapshot] = useState<ConnectionSnapshot | null>(null);
  const [state, setState] = useState<StreamState>("connecting");
  const [paused, setPaused] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState("");
  const [selectedInbound, setSelectedInbound] = useState(inbound);
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => setSelectedInbound(inbound), [inbound]);
  useEffect(() => {
    const change = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", change);
    return () => document.removeEventListener("visibilitychange", change);
  }, []);
  useEffect(() => {
    if (paused || !visible) { setState("paused"); return; }
    let disposed = false;
    setState("connecting");
    const base = new URL(import.meta.env.VITE_BASE_API || "/api/", window.location.origin);
    base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
    base.pathname = `${base.pathname.replace(/\/$/, "")}/node/${nodeId}/connections`;
    const socket = new WebSocket(base);
    socket.onopen = () => { if (disposed) socket.close(); else socket.send(JSON.stringify({ token: getAuthToken() })); };
    socket.onmessage = event => {
      if (disposed) return;
      try {
        const data = JSON.parse(event.data) as ConnectionSnapshot;
        if (data.type !== "snapshot" || !Array.isArray(data.records)) return;
        setSnapshot(data); setState("connected");
      } catch { setState("error"); }
    };
    socket.onerror = () => { if (!disposed) setState("error"); };
    socket.onclose = event => {
      if (!disposed) setState(event.code === 4401 || event.code === 4403 ? "unauthorized" : event.code === 4400 ? "offline" : "error");
    };
    return () => { disposed = true; if (socket.readyState !== WebSocket.CONNECTING) socket.close(); };
  }, [nodeId, paused, visible, attempt]);
  const records = snapshot?.records || [];
  const rows = records.filter(row => (!selectedInbound || row.inbound === selectedInbound)
    && (!family || pathFor(row) === family)
    && `${row.user} ${row.source} ${row.target} ${row.remote} ${row.outbound}`.toLowerCase().includes(search.trim().toLowerCase()));
  const inbounds = [...new Set([inbound, ...records.map(row => row.inbound)].filter(Boolean))];
  const users = new Set(rows.map(row => row.identity)).size;
  const observed = rows.filter(row => row.evidence === "socket").length;
  return <Box>
    <Flex justify="space-between" gap={3} flexWrap="wrap" align="center" mb={4}>
      <HStack><Badge colorScheme={state === "connected" ? "green" : "gray"}>{t(`connections.stream.${state}`)}</Badge>
        {state === "connecting" && <Spinner size="sm" />}</HStack>
      <HStack flexWrap="wrap"><Button size="sm" variant="outline" onClick={() => setPaused(value => !value)}>{t(paused ? "connections.resume" : "connections.pause")}</Button>
        {(state === "error" || state === "offline" || state === "unauthorized") && <Button size="sm" onClick={() => setAttempt(value => value + 1)}>{t("hostsPage.retry")}</Button>}</HStack>
    </Flex>
    <Text color="fg.muted" fontSize="sm" mb={4}>{t("connections.description")}</Text>
    {state === "error" || state === "offline" || state === "unauthorized" ? <Alert status="error" borderRadius="xl" mb={4}><AlertIcon />{t(`connections.error.${state}`)}</Alert> : null}
    {snapshot && !snapshot.observer && <Alert status="info" borderRadius="xl" mb={4} alignItems="start"><AlertIcon /><Box>
      <Text fontWeight="semibold">{t("connections.observerNeeded")}</Text><Text fontSize="sm">{t("connections.observerHelp")}</Text>
    </Box></Alert>}
    <SimpleGrid columns={{ base: 2, md: 4 }} gap={3} mb={5}>
      {[["connections.records", rows.length], ["connections.users", users], ["connections.observed", observed], ["connections.unknown", rows.length - observed]].map(([key, count]) =>
        <Box key={key} borderWidth="1px" borderColor="border.subtle" borderRadius="xl" p={4}><Text color="fg.muted" fontSize="sm">{t(String(key))}</Text><Text fontSize="2xl" fontWeight="semibold">{count}</Text></Box>)}
    </SimpleGrid>
    <Flex gap={3} flexWrap="wrap" align="end" mb={5}>
      <FormControl flex="2" minW="min(240px, 100%)"><FormLabel htmlFor="connection-search" fontSize="sm">{t("connections.search")}</FormLabel>
        <Input id="connection-search" value={search} onChange={event => setSearch(event.target.value)} placeholder={t("connections.searchPlaceholder")} /></FormControl>
      <FormControl flex="1" minW="min(180px, 100%)"><FormLabel htmlFor="connection-family" fontSize="sm">{t("connections.path")}</FormLabel>
        <Select id="connection-family" value={family} onChange={event => setFamily(event.target.value)}><option value="">{t("connections.allPaths")}</option>
          {["IPv4 → IPv4", "IPv4 → IPv6", "IPv6 → IPv4", "IPv6 → IPv6"].map(path => <option key={path}>{path}</option>)}</Select></FormControl>
      <FormControl flex="1" minW="min(180px, 100%)"><FormLabel htmlFor="connection-inbound" fontSize="sm">{t("connections.inbound")}</FormLabel>
        <Select id="connection-inbound" value={selectedInbound} onChange={event => setSelectedInbound(event.target.value)}><option value="">{t("connections.allInbounds")}</option>
          {inbounds.map(tag => <option key={tag}>{tag}</option>)}</Select></FormControl>
    </Flex>
    <Box borderWidth="1px" borderColor="border.subtle" borderRadius="xl" overflow="hidden">
      {!rows.length ? <Box p={8} textAlign="center"><Text fontWeight="semibold">{t(records.length ? "connections.noMatches" : "connections.empty")}</Text>
        <Text fontSize="sm" color="fg.muted" mt={2}>{t("connections.emptyHelp")}</Text></Box>
        : <>
          <TableContainer display={{ base: "none", xl: "block" }}><Table size="sm"><Thead><Tr>
            {["user", "path", "source", "target", "remote", "route", "time"].map(key => <Th key={key}>{t(`connections.${key}`)}</Th>)}
          </Tr></Thead><Tbody>{rows.map(row => <Tr key={row.id}>
            <Td maxW="160px" whiteSpace="normal" overflowWrap="anywhere"><Text fontWeight="semibold">{row.user}</Text><Badge mt={1}>{row.network.toUpperCase()}</Badge></Td>
            <Td><Badge textTransform="none" colorScheme={row.evidence === "socket" ? row.egress_family === "IPv6" ? "purple" : "blue" : "gray"}>{pathFor(row)}</Badge><Text fontSize="xs" color="fg.muted" mt={1}>{t(`connections.evidence.${row.evidence}`)}</Text></Td>
            <Td fontFamily="mono" fontSize="xs" maxW="200px" whiteSpace="normal" overflowWrap="anywhere">{row.source}</Td>
            <Td maxW="200px" whiteSpace="normal" overflowWrap="anywhere">{row.target}</Td>
            <Td maxW="210px" whiteSpace="normal" overflowWrap="anywhere"><Text fontFamily="mono" fontSize="xs">{row.remote || t("connections.notObserved")}</Text>
              {row.local && <Text color="fg.muted" fontSize="xs" mt={1}>{t("connections.local")}: {row.local}</Text>}</Td>
            <Td maxW="170px" whiteSpace="normal" overflowWrap="anywhere"><Text>{row.inbound || "—"}</Text><Text color="fg.muted" fontSize="xs">→ {row.outbound || "—"}</Text></Td>
            <Td fontSize="xs">{new Date(row.timestamp).toLocaleTimeString(i18n.language)}</Td>
          </Tr>)}</Tbody></Table></TableContainer>
          <Box display={{ base: "block", xl: "none" }}>{rows.map(row => <Box key={row.id} p={4} borderBottomWidth="1px" borderColor="border.subtle" overflowWrap="anywhere">
            <HStack justify="space-between" flexWrap="wrap"><Text fontWeight="semibold">{row.user}</Text><Badge textTransform="none" colorScheme={row.evidence === "socket" ? "purple" : "gray"}>{pathFor(row)}</Badge></HStack>
            <Text fontSize="sm" mt={2}>{t("connections.source")}: {row.source}</Text><Text fontSize="sm">{t("connections.target")}: {row.target}</Text>
            <Text fontSize="sm">{t("connections.remote")}: {row.remote || t("connections.notObserved")}</Text>
            {row.local && <Text fontSize="xs" color="fg.muted">{t("connections.local")}: {row.local}</Text>}
            <Text fontSize="xs" color="fg.muted" mt={2}>{row.inbound} → {row.outbound} · {row.network.toUpperCase()} · {new Date(row.timestamp).toLocaleTimeString(i18n.language)} · {t(`connections.evidence.${row.evidence}`)}</Text>
          </Box>)}</Box>
        </>}
    </Box>
    <Text fontSize="xs" color="fg.muted" mt={3}>{t("connections.scope", { count: snapshot?.limit || 500 })}</Text>
  </Box>;
};
