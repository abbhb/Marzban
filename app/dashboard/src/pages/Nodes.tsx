import {
  Alert, AlertIcon, Badge, Box, Button, Center, Flex, Heading, HStack, Input,
  SimpleGrid, Spinner, Tab, TabList, TabPanel, TabPanels, Tabs, Text, useToast,
} from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { BootReady } from "components/BootReady";
import { Footer } from "components/Footer";
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { Link, unstable_useBlocker as useBlocker, useBeforeUnload, useParams, useSearchParams } from "react-router-dom";
import { errorMessage, fetch } from "service/http";
import { ServiceNode } from "./nodes/types";

const Connections = lazy(() => import("./nodes/Connections").then(module => ({ default: module.Connections })));
const NodeSettings = lazy(() => import("./nodes/NodeSettings").then(module => ({ default: module.NodeSettings })));
const panelStyle = { bg: "surface.toolbar", borderWidth: "1px", borderColor: "border.subtle", borderRadius: "2xl" };

export const Nodes = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { nodeId } = useParams();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const guard = useRef({ dirty: false, saving: false });
  const onDirty = useCallback((value: boolean) => { guard.current.dirty = value; setDirty(value); }, []);
  const onSaving = useCallback((value: boolean) => { guard.current.saving = value; setSaving(value); }, []);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (guard.current.dirty || guard.current.saving) && currentLocation.pathname !== nextLocation.pathname);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => {
    if (guard.current.dirty || guard.current.saving) { event.preventDefault(); event.returnValue = ""; }
  }, []));
  const queries = useQueryClient();
  const query = useQuery("node-services", () => fetch<ServiceNode[]>("/node-services", { timeout: 15000 }), {
    refetchInterval: 10000, refetchIntervalInBackground: false, refetchOnWindowFocus: false,
  });
  const node = query.data?.find(row => String(row.id) === nodeId);
  const isNew = nodeId === "new";
  const settingsTab = isNew || params.get("tab") === "settings";
  const name = (row: ServiceNode) => row.id === 0 ? t("nodeServices.local") : row.name;
  const reconnect = useMutation(() => fetch(`/node/${node!.id}/reconnect`, { method: "POST", retry: 0 }), {
    onSuccess: () => { queries.invalidateQueries("node-services"); toast({ title: t("nodeServices.reconnectQueued"), status: "info" }); },
    onError: error => { toast({ title: errorMessage(error, t("nodeServices.saveError")), status: "error", isClosable: true }); },
  });
  useEffect(() => { if (nodeId) document.getElementById("service-host-heading")?.focus(); }, [nodeId]);
  const changeTab = (index: number) => {
    const next = new URLSearchParams(params);
    if (index) next.set("tab", "settings"); else next.delete("tab");
    setParams(next);
  };
  const shown = (query.data || []).filter(row => `${name(row)} ${row.address}`.toLowerCase().includes(search.trim().toLowerCase()));
  return <AdminShell>
    <BootReady ready={!query.isLoading} />
    <Box px={{ base: 4, md: 7 }} py={6} maxW="1680px" mx="auto">
      {blocker.state === "blocked" && <Alert status="warning" borderRadius="xl" mb={5} alignItems="start"><AlertIcon /><Box>
        <Text fontWeight="semibold">{t("hostsPage.leaveTitle")}</Text><Text fontSize="sm">{t("hostsPage.leaveHelp")}</Text>
        <HStack mt={3}><Button size="sm" onClick={() => blocker.reset()}>{t("hostsPage.stay")}</Button><Button size="sm" colorScheme="red" variant="outline" isDisabled={saving} onClick={() => blocker.proceed()}>{t("hostsPage.leave")}</Button></HStack>
      </Box></Alert>}
      {nodeId && <Button as={Link} to="/nodes" variant="link" mb={4}>← {t("nodeServices.back")}</Button>}
      <Flex justify="space-between" align="start" flexWrap="wrap" gap={4} mb={6}>
        <Box minW={0}><Heading id="service-host-heading" tabIndex={-1} as="h1" size="lg" overflowWrap="anywhere" _focus={{ outline: "none" }}>{isNew ? t("nodes.addNewMarzbanNode") : node ? name(node) : t("nodeServices.title")}</Heading>
          <Text color="fg.muted" mt={2}>{node ? node.id === 0 ? t("nodeServices.localDescription") : node.address : t("nodeServices.description")}</Text>
          {node && <HStack mt={3} flexWrap="wrap"><Badge colorScheme={node.status === "connected" ? "green" : node.status === "error" ? "red" : "gray"}>{t(`nodeModal.status.${node.status}`)}</Badge>
            <Badge>Xray {node.xray_version || "—"}</Badge><Badge>{t("nodeServices.inboundCount", { count: node.inbound_tags.length })}</Badge></HStack>}
        </Box>
        {!nodeId && <Button as={Link} to="/nodes/new" colorScheme="primary">{t("nodes.addNode")}</Button>}
        {node && node.id !== 0 && <Button variant="outline" isLoading={reconnect.isLoading} isDisabled={saving || dirty} onClick={() => reconnect.mutate()}>{t("nodes.reconnect")}</Button>}
      </Flex>
      {query.isError && query.data && <Alert status="warning" borderRadius="xl" mb={4}><AlertIcon /><Text flex={1}>{t("nodeServices.refreshError")}</Text><Button onClick={() => query.refetch()}>{t("hostsPage.retry")}</Button></Alert>}
      {query.isLoading ? <Center minH="240px"><Spinner /><Text ms={3}>{t("hostsDialog.loading")}</Text></Center>
        : query.isError && !query.data ? <Alert status="error" borderRadius="xl"><AlertIcon /><Text flex={1}>{t("nodeServices.loadError")}</Text><Button onClick={() => query.refetch()}>{t("hostsPage.retry")}</Button></Alert>
        : !nodeId ? <>
          <Input aria-label={t("nodeServices.search")} placeholder={t("nodeServices.search")} value={search} onChange={event => setSearch(event.target.value)} maxW="440px" mb={5} />
          <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} gap={4}>{shown.map(row => <Box key={row.id} {...panelStyle} p={5}>
            <HStack justify="space-between" align="start" flexWrap="wrap"><Heading as="h2" size="md" overflowWrap="anywhere"><Box as={Link} to={`/nodes/${row.id}`} color="primary.600" _dark={{ color: "primary.300" }}>{name(row)}</Box></Heading>
              <Badge colorScheme={row.status === "connected" ? "green" : row.status === "error" ? "red" : "gray"}>{t(`nodeModal.status.${row.status}`)}</Badge></HStack>
            <Text color="fg.muted" mt={3} overflowWrap="anywhere">{row.id === 0 ? t("nodeServices.localDescription") : row.address}</Text>
            <Text fontSize="sm" mt={3}>{t("nodeServices.inboundCount", { count: row.inbound_tags.length })} · Xray {row.xray_version || "—"}</Text>
            <Button as={Link} to={`/nodes/${row.id}`} size="sm" mt={4} variant="outline">{t("nodeServices.openConnections")}</Button>
          </Box>)}</SimpleGrid>
          {!shown.length && <Text color="fg.muted">{t("hostsPage.noMatches")}</Text>}
        </> : !node && !isNew ? <Alert status="warning" borderRadius="xl"><AlertIcon />{t("nodeServices.notFound")}</Alert>
        : <Box {...panelStyle} p={{ base: 4, md: 6 }} key={nodeId}>
          {node?.message && <Alert status="warning" borderRadius="xl" mb={4}><AlertIcon /><Text overflowWrap="anywhere">{node.message}</Text></Alert>}
          <Tabs index={settingsTab ? 1 : 0} onChange={changeTab} isLazy lazyBehavior="keepMounted">
            {!isNew && <TabList><Tab>{t("connections.title")}</Tab><Tab>{t("nodeServices.settings")}{dirty && <Badge ms={2} colorScheme="orange">{t("hostsPage.unsaved")}</Badge>}</Tab></TabList>}
            <TabPanels>
              <TabPanel px={0} pt={5}><Suspense fallback={<Spinner />}>
                {node && !settingsTab && <Connections nodeId={node.id} inbound={params.get("inbound") || ""} key={nodeId} />}
              </Suspense></TabPanel>
              <TabPanel px={0} pt={isNew ? 0 : 5}><Suspense fallback={<Spinner />}>
                <NodeSettings node={node} onDirty={onDirty} onSaving={onSaving} key={nodeId} />
              </Suspense></TabPanel>
            </TabPanels>
          </Tabs>
          {node && <Box mt={6} borderTopWidth="1px" borderColor="border.subtle" pt={5}>
            <Text fontWeight="semibold" mb={3}>{t("nodes.inboundSummary")}</Text><HStack flexWrap="wrap" gap={2}>
              {node.inbound_tags.map(tag => <Button as={Link} to={`/hosts?inbound=${encodeURIComponent(tag)}`} key={tag} size="sm" variant="outline" whiteSpace="normal" h="auto" minH="9" py={2}>{tag}</Button>)}
              {!node.inbound_tags.length && <Text color="fg.muted" fontSize="sm">{t("nodeServices.noInbounds")}</Text>}</HStack>
          </Box>}
        </Box>}
    </Box>
    <Footer />
  </AdminShell>;
};
