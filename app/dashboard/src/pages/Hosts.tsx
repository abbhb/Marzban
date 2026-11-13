import {
  Alert, AlertIcon, Badge, Box, Button, Center, Flex, FormControl, FormLabel,
  Heading, HStack, Icon, IconButton, Input, Select, Spinner, Tab, TabList, TabPanel, TabPanels,
  Tabs, Text, VStack, useToast,
} from "@chakra-ui/react";
import { ArrowDownIcon, ArrowUpIcon, DocumentDuplicateIcon, MagnifyingGlassIcon, PlusIcon } from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import { AdminShell } from "components/AdminShell";
import { BootReady } from "components/BootReady";
import { Footer } from "components/Footer";
import { NodeType } from "contexts/NodesContext";
import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { FieldErrors, FormProvider, useFieldArray, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { unstable_useBlocker as useBlocker, useBeforeUnload, useSearchParams } from "react-router-dom";
import { errorMessage, fetch } from "service/http";
import { HostEditor } from "./hosts/HostEditor";
import { Category, HostForm, HostMap, Inbound, categories, categoryFor, endpoint, fetchInboundScopes, flattenHosts, formSchema, groupHosts, newHost, normalizeHosts, same } from "./hosts/schema";

const XhttpProfiles = lazy(() => import("components/XhttpProfiles").then(module => ({ default: module.XhttpProfiles })));
const panelStyle = { bg: "surface.toolbar", borderWidth: "1px", borderColor: "border.subtle", borderRadius: "2xl" };

export const Hosts = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const xhttpTab = params.get("tab") === "xhttp";
  const [xhttpVisited, setXhttpVisited] = useState(xhttpTab);
  const [xhttpDirty, setXhttpDirty] = useState(false);
  const [baseline, setBaseline] = useState<HostMap>({});
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [nodes, setNodes] = useState<NodeType[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [reload, setReload] = useState(0);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState(0);
  const [category, setCategory] = useState<Category>("basic");
  const [search, setSearch] = useState("");
  const [targetInbound, setTargetInbound] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [undo, setUndo] = useState<{ row: HostForm["routes"][number]; index: number } | null>(null);
  const form = useForm<HostForm>({ resolver: zodResolver(formSchema), defaultValues: { routes: [] }, shouldFocusError: false });
  const { fields, append, insert, remove, move } = useFieldArray({ control: form.control, name: "routes" });
  const routes = form.watch("routes") || [];
  // Field-array keys and watched values can update in separate renders.
  const rowKey = (index: number) => fields[index]?.id ?? `pending-${index}`;
  const tags = Object.keys(baseline);
  const grouped = groupHosts(routes, tags);
  const changed = tags.filter(tag => !same(grouped[tag], baseline[tag]));
  const dirty = changed.length > 0 || xhttpDirty;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (dirty || saving) && currentLocation.pathname !== nextLocation.pathname);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => {
    if (dirty || saving) { event.preventDefault(); event.returnValue = ""; }
  }, [dirty, saving]));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoadError("");
    Promise.all([
      fetch<HostMap>("/hosts", { signal: controller.signal, timeout: 15000 }),
      fetchInboundScopes(controller.signal),
      fetch<NodeType[]>("/nodes", { signal: controller.signal, timeout: 15000 }),
    ]).then(([hosts, inboundList, serverNodes]) => {
      const normalized = normalizeHosts(hosts);
      const flat = flattenHosts(normalized);
      const requested = params.get("inbound");
      const initial = requested ? flat.routes.findIndex(row => row.inbound === requested) : -1;
      setBaseline(normalized); form.reset(flat);
      setInbounds(inboundList);
      setNodes(serverNodes);
      setTargetInbound(requested && requested in normalized ? requested : Object.keys(normalized)[0] || ""); setSelected(initial >= 0 ? initial : 0);
    }).catch(() => {
      if (!controller.signal.aborted) setLoadError(t("hostsPage.loadError"));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload, form.reset]);
  useEffect(() => { if (xhttpTab) setXhttpVisited(true); }, [xhttpTab]);
  useEffect(() => setConfirmDelete(false), [selected, fields[selected]?.id]);
  useEffect(() => { if (blocker.state === "blocked") window.scrollTo({ top: 0 }); }, [blocker.state]);

  const current = routes[selected];
  const inbound = inbounds.find(row => row.tag === current?.inbound);
  const peers = routes.map((row, index) => row.inbound === current?.inbound ? index : -1).filter(index => index >= 0);
  const position = peers.indexOf(selected);
  const select = (index: number) => { setSelected(index); setConfirmDelete(false); };
  const routeLabel = (index: number) => routes[index]?.value.remark || t("hostsPage.unnamed");
  const rowChanged = (index: number) => {
    const row = routes[index];
    const slot = routes.slice(0, index).filter(other => other.inbound === row.inbound).length;
    return !same(row.value, baseline[row.inbound]?.[slot]);
  };
  const chooseCategory = (next: Category) => { setCategory(next); setConfirmDelete(false); };
  const focusField = (index: number, field: string) => {
    select(index); setCategory(categoryFor(field));
    requestAnimationFrame(() => form.setFocus(`routes.${index}.value.${field}` as any));
  };
  const invalid = (errors: FieldErrors<HostForm>) => {
    const index = routes.findIndex((_, index) => errors.routes?.[index]?.value);
    if (index >= 0) focusField(index, Object.keys(errors.routes![index]!.value!)[0]);
    setSaveError(t("hostsPage.fixErrors"));
  };
  const save = async (data: HostForm) => {
    const next = groupHosts(data.routes, tags);
    const payload = Object.fromEntries(tags.filter(tag => !same(next[tag], baseline[tag])).map(tag => [tag, next[tag]]));
    if (!Object.keys(payload).length) return;
    setSaving(true); setSaveError("");
    try {
      const result = normalizeHosts(await fetch<HostMap>("/hosts", { method: "PUT", body: payload, retry: 0 }));
      const tag = data.routes[selected]?.inbound;
      const slot = data.routes.slice(0, selected).filter(row => row.inbound === tag).length;
      const matching = flattenHosts(result).routes.map((row, index) => row.inbound === tag ? index : -1).filter(index => index >= 0);
      setBaseline(result); form.reset(flattenHosts(result)); setUndo(null);
      setSelected(matching[slot] ?? 0);
      toast({ title: t("hostsPage.saved"), description: t("hostsPage.savedHelp"), status: "success", isClosable: true });
    } catch (error: any) {
      const detail = error?.data?.detail ?? error?.response?._data?.detail;
      if (Array.isArray(detail)) {
        let first = true;
        for (const issue of detail) {
          const [, tag, slot, field] = issue.loc || [];
          const index = data.routes.map((row, index) => row.inbound === tag ? index : -1).filter(index => index >= 0)[Number(slot)];
          if (index !== undefined && field && field in data.routes[index].value) {
            form.setError(`routes.${index}.value.${field}` as any, { type: "server", message: issue.msg });
            if (first) { focusField(index, field); first = false; }
          }
        }
      }
      const cascadeKey = typeof detail === "string" && detail.startsWith("cascade_") ? `cascade.errors.${detail}` : "";
      setSaveError(cascadeKey ? t(cascadeKey) : errorMessage(error, t("hostsPage.saveError")));
    } finally { setSaving(false); }
  };
  const add = () => {
    if (!targetInbound) return;
    append({ inbound: targetInbound, value: newHost() }, { shouldFocus: false });
    select(routes.length); setCategory("basic"); setSearch("");
    requestAnimationFrame(() => form.setFocus(`routes.${routes.length}.value.remark`));
  };
  const duplicate = () => {
    if (!current) return;
    insert(selected + 1, { inbound: current.inbound, value: { ...current.value, remark: t("hostsPage.copyName", { name: routeLabel(selected) }) } }, { shouldFocus: false });
    select(selected + 1); setSearch("");
  };
  const deleteRoute = () => {
    if (!current) return;
    setUndo({ row: structuredClone(current), index: selected });
    remove(selected); select(Math.max(0, Math.min(selected, routes.length - 2)));
    setConfirmDelete(false);
  };
  const shown = routes.map((row, index) => ({ ...row, index })).filter(row => `${row.inbound} ${row.value.remark} ${row.value.address}`.toLowerCase().includes(search.trim().toLowerCase()));
  const changeTab = (index: number) => { const next = new URLSearchParams(params); if (index) next.set("tab", "xhttp"); else next.delete("tab"); setParams(next, { replace: true }); };

  return <AdminShell>
    <BootReady ready={!loading} />
    <Box px={{ base: 4, md: 7 }} py={6} maxW="1680px" mx="auto">
      {blocker.state === "blocked" && <Alert status="warning" borderRadius="xl" mb={5} alignItems="start" role="alert">
        <AlertIcon /><Box flex="1"><Text fontWeight="semibold">{t("hostsPage.leaveTitle")}</Text><Text fontSize="sm">{t("hostsPage.leaveHelp")}</Text>
          <HStack mt={3} flexWrap="wrap"><Button size="sm" onClick={() => blocker.reset()}>{t("hostsPage.stay")}</Button>
            <Button size="sm" colorScheme="red" variant="outline" isDisabled={saving} onClick={() => blocker.proceed()}>{t("hostsPage.leave")}</Button></HStack>
        </Box>
      </Alert>}
      <Heading as="h1" size="lg">{t("header.hostSettings")}</Heading>
      <Text color="fg.muted" mt={2} mb={5}>{t("hostsPage.relationshipHelp")}</Text>
      <Tabs index={xhttpTab ? 1 : 0} onChange={changeTab}>
        <TabList><Tab>{t("hostsPage.routes")}{changed.length > 0 && <Badge ms={2} colorScheme="orange">{t("hostsPage.unsaved")}</Badge>}</Tab>
          <Tab>{t("xhttp.title")}{xhttpDirty && <Badge ms={2} colorScheme="orange">{t("hostsPage.unsaved")}</Badge>}</Tab></TabList>
      {loading ? <Center minH="300px"><Spinner /><Text ms={3}>{t("hostsDialog.loading")}</Text></Center>
        : loadError ? <Alert status="error" borderRadius="xl"><AlertIcon /><Box flex="1">{loadError}</Box><Button onClick={() => setReload(value => value + 1)}>{t("hostsPage.retry")}</Button></Alert>
        : <TabPanels mt={5}>
          <TabPanel p={0}>
            <Flex {...panelStyle} position="sticky" top={{ base: "68px", lg: "0" }} zIndex="10" p={4} mb={5} gap={3} justify="space-between" align="center" flexWrap="wrap" boxShadow="sm">
              <Box flex="1" minW="0" aria-live="polite">
                {current && <Text fontSize="sm" color="fg.muted" noOfLines={1} title={`${current.inbound} / ${routeLabel(selected)}`}>{t("hostsPage.editing")} · {current.inbound} / {routeLabel(selected)}</Text>}
                <Text fontWeight="semibold">{changed.length ? t("hostsPage.pending", { count: changed.length }) : t("hostsPage.allSaved")}</Text>
                <Text color="fg.muted" fontSize="sm" overflowWrap="anywhere">{changed.length ? changed.join(" · ") : t("hostsPage.saveScope")}</Text></Box>
              <Button colorScheme="primary" onClick={form.handleSubmit(save, invalid)} isDisabled={!changed.length || saving} isLoading={saving}>{t("hostsPage.saveAll")}</Button>
            </Flex>
            {saveError && <Alert status="error" borderRadius="xl" mb={4} role="alert"><AlertIcon /><Text overflowWrap="anywhere">{saveError}</Text></Alert>}
            {undo && <Alert status="info" borderRadius="xl" mb={4}><AlertIcon /><Text flex="1">{t("hostsPage.deleted", { name: undo.row.value.remark || t("hostsPage.unnamed") })}</Text>
              <Button size="sm" isDisabled={saving} onClick={() => { insert(undo.index, undo.row, { shouldFocus: false }); select(undo.index); setUndo(null); setSearch(""); }}>{t("hostsPage.undo")}</Button></Alert>}
            <FormProvider {...form}>
              <Box as="fieldset" disabled={saving} minW="0" border="0" p="0" m="0">
                <Flex gap={5} align="start" direction={{ base: "column", xl: "row" }}>
                  <Box {...panelStyle} w={{ base: "full", xl: "300px" }} flexShrink="0" p={4}>
                    <HStack justify="space-between" mb={3}><Heading size="sm">{t("hostsPage.routes")}</Heading><Badge>{routes.length}</Badge></HStack>
                    <Box position="relative" mb={3}><Icon as={MagnifyingGlassIcon} position="absolute" top="3" insetInlineStart="3" boxSize="5" color="fg.muted" />
                      <Input ps={10} aria-label={t("hostsPage.search")} placeholder={t("hostsPage.search")} value={search} onChange={event => setSearch(event.target.value)} /></Box>
                    <FormControl mb={3}><FormLabel htmlFor="host-target-inbound" fontSize="sm">{t("hostsPage.addTo")}</FormLabel>
                      <HStack><Select id="host-target-inbound" value={targetInbound} onChange={event => setTargetInbound(event.target.value)} minW="0">
                        {tags.map(tag => <option key={tag} value={tag}>{tag}</option>)}</Select>
                        <IconButton aria-label={t("hostsPage.add")} icon={<Icon as={PlusIcon} boxSize="5" />} onClick={add} isDisabled={!targetInbound} /></HStack>
                    </FormControl>
                    <FormControl display={{ base: "block", xl: "none" }}><FormLabel htmlFor="host-current">{t("hostsPage.editing")}</FormLabel>
                      <Select id="host-current" value={current ? selected : ""} onChange={event => select(Number(event.target.value))}>
                        {!shown.length && <option value="">{t("hostsPage.noMatches")}</option>}
                        {current && !shown.some(row => row.index === selected) && <option value={selected}>{current.inbound} / {routeLabel(selected)}</option>}
                        {tags.map(tag => <optgroup label={tag} key={tag}>{shown.filter(row => row.inbound === tag).map(row => <option key={rowKey(row.index)} value={row.index}>{routeLabel(row.index)}{rowChanged(row.index) ? ` · ${t("hostsPage.unsaved")}` : ""}</option>)}</optgroup>)}
                      </Select>
                    </FormControl>
                    <VStack as="nav" aria-label={t("hostsPage.routeList")} display={{ base: "none", xl: "flex" }} align="stretch" spacing={4} maxH="calc(100vh - 340px)" minH="160px" overflowY="auto" pt={2}>
                      {tags.map(tag => {
                        const rows = shown.filter(row => row.inbound === tag);
                        if (!rows.length && search) return null;
                        return <Box key={tag}><Text fontSize="xs" fontWeight="bold" color="fg.muted" mb={2} overflowWrap="anywhere">{tag} · {rows.length}</Text>
                          <VStack align="stretch" spacing={2}>{rows.map(row => <Box as="button" type="button" key={rowKey(row.index)} textAlign="start" w="full" px={3} py={3} borderRadius="xl" borderWidth="1px"
                            borderColor={selected === row.index ? "primary.500" : "border.subtle"} bg={selected === row.index ? "surface.active" : "transparent"}
                            _hover={{ bg: "surface.hover" }} _focusVisible={{ outline: "2px solid", outlineColor: "focus.ring", outlineOffset: "2px" }}
                            aria-pressed={selected === row.index} onClick={() => select(row.index)}>
                            <Text fontWeight="semibold" fontSize="sm" overflowWrap="anywhere">{routeLabel(row.index)}</Text>
                            <Text fontSize="xs" color="fg.muted" overflowWrap="anywhere" mt={1}>{endpoint(row.value, inbounds.find(inbound => inbound.tag === tag))}</Text>
                            <HStack mt={2} spacing={1} flexWrap="wrap">
                              {row.value.is_disabled && <Badge>{t("hostsPage.disabled")}</Badge>}
                              {row.value.cascade_mode !== "off" && <Badge colorScheme="purple">{t("cascade.title")}</Badge>}
                              {rowChanged(row.index) && <Badge colorScheme="orange">{t("hostsPage.unsaved")}</Badge>}
                              {form.formState.errors.routes?.[row.index]?.value && <Badge colorScheme="red">{t("hostsPage.invalid")}</Badge>}
                            </HStack>
                          </Box>)}</VStack>
                          {!rows.length && <Text color="fg.muted" fontSize="sm">{t("hostsPage.emptyInbound")}</Text>}
                        </Box>;
                      })}
                      {!shown.length && search && <Text color="fg.muted">{t("hostsPage.noMatches")}</Text>}
                    </VStack>
                  </Box>
                  <Box {...panelStyle} flex="1" w="full" minW="0" p={{ base: 4, md: 6 }}>
                    {current ? <>
                      <Box borderWidth="1px" borderColor="border.subtle" borderRadius="xl" p={4} mb={5}>
                        <Text fontWeight="semibold" fontSize="sm">{t("hostsPage.relationshipTitle")}</Text>
                        <Text mt={1} fontSize="sm" overflowWrap="anywhere">{t("hostsPage.inboundName")}: {current.inbound}</Text>
                        <Text mt={1} fontSize="sm" overflowWrap="anywhere">{t("hostsPage.runScope")}: {inbound?.node_ids?.length
                          ? inbound.node_ids.map(id => nodes.find(node => node.id === id)?.name || t("hostsPage.unknownNode", { id })).join(" · ")
                          : t("hostsPage.sharedScope")}</Text>
                        <Text mt={1} color="fg.muted" fontSize="sm">{t("hostsPage.relationshipNote")}</Text>
                      </Box>
                      <Flex justify="space-between" gap={3} direction={{ base: "column", md: "row" }} mb={5}>
                        <Box minW="0" flex="1"><Text fontSize="sm" color="fg.muted" overflowWrap="anywhere">{t("hostsPage.editing")} · {current.inbound} · {position + 1}/{peers.length}</Text>
                          <Heading as="h2" size="md" mt={2} overflowWrap="anywhere">{routeLabel(selected)}</Heading>
                          <Text color="fg.muted" fontSize="sm" mt={2} overflowWrap="anywhere">{endpoint(current.value, inbound)}</Text>
                          <HStack mt={3} flexWrap="wrap"><Badge>{inbound?.protocol ?? "—"} / {inbound?.network ?? "—"}</Badge><Badge>{inbound?.tls || "none"}</Badge>
                            <Badge colorScheme={current.value.is_disabled ? "gray" : "green"}>{t(current.value.is_disabled ? "hostsPage.disabled" : "hostsPage.enabled")}</Badge>
                            {rowChanged(selected) && <Badge colorScheme="orange">{t("hostsPage.unsaved")}</Badge>}</HStack>
                        </Box>
                        <HStack align="start" spacing={1}>
                          <IconButton variant="ghost" aria-label={t("hostsPage.duplicate")} title={t("hostsPage.duplicate")} icon={<Icon as={DocumentDuplicateIcon} boxSize="5" />} onClick={duplicate} />
                          <IconButton variant="ghost" aria-label={t("hostsPage.up")} title={t("hostsPage.up")} icon={<Icon as={ArrowUpIcon} boxSize="5" />} isDisabled={position <= 0} onClick={() => { const next = peers[position - 1]; move(selected, next); select(next); }} />
                          <IconButton variant="ghost" aria-label={t("hostsPage.down")} title={t("hostsPage.down")} icon={<Icon as={ArrowDownIcon} boxSize="5" />} isDisabled={position >= peers.length - 1} onClick={() => { const next = peers[position + 1]; move(selected, next); select(next); }} />
                          <Button variant="ghost" colorScheme="red" onClick={() => setConfirmDelete(!confirmDelete)}>{t("hostsPage.delete")}</Button>
                        </HStack>
                      </Flex>
                      {confirmDelete && <Alert status="warning" borderRadius="lg" mb={4} flexWrap="wrap" gap={2}><Text flex="1">{t("hostsPage.deleteConfirm", { name: routeLabel(selected) })}</Text>
                        <Button size="sm" onClick={() => setConfirmDelete(false)}>{t("hostsPage.cancel")}</Button><Button size="sm" colorScheme="red" onClick={deleteRoute}>{t("hostsPage.confirmDelete")}</Button></Alert>}
                      <Tabs isLazy index={categories.indexOf(category)} onChange={index => chooseCategory(categories[index])}>
                        <TabList overflowX="auto">{categories.map(value => <Tab key={value} whiteSpace="nowrap" flexShrink="0">{t(`hostsPage.${value}`)}
                          {Object.keys(form.formState.errors.routes?.[selected]?.value || {}).some(field => categoryFor(field) === value) && <Badge colorScheme="red" ms={1}>!</Badge>}</Tab>)}</TabList>
                        <TabPanels mt={6}>{categories.map(value => <TabPanel p={0} key={value}><HostEditor key={rowKey(selected)} index={selected} category={value} inbound={inbound} /></TabPanel>)}</TabPanels>
                      </Tabs>
                    </> : <Center minH="280px"><VStack><Heading size="sm">{t("hostsPage.empty")}</Heading><Text color="fg.muted">{t("hostsPage.emptyHelp")}</Text><Button onClick={add} isDisabled={!targetInbound}>{t("hostsPage.add")}</Button></VStack></Center>}
                  </Box>
                </Flex>
              </Box>
            </FormProvider>
          </TabPanel>
          <TabPanel p={0}>{xhttpVisited && <Box {...panelStyle} p={{ base: 4, md: 6 }}><Suspense fallback={<Center minH="240px"><Spinner /></Center>}><XhttpProfiles onDirtyChange={setXhttpDirty} /></Suspense></Box>}</TabPanel>
        </TabPanels>}
      </Tabs>
      <Footer mt={6} />
    </Box>
  </AdminShell>;
};
