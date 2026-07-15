import {
  Accordion,
  AccordionButton,
  AccordionIcon,
  AccordionItem,
  AccordionPanel,
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  chakra,
  Code,
  FormControl,
  FormLabel,
  HStack,
  IconButton,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  SimpleGrid,
  Switch,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { DataWorkspace, PaginationControls } from "components/DataWorkspace";
import { ArrowPathIcon, PlusIcon } from "@heroicons/react/24/outline";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "react-query";
import { fetch } from "service/http";
import { IPBlock, PageResult, PortalSecuritySettings } from "types/Commerce";
import { initialPageState, pageUrl, useDebouncedValue, WorkspaceSearch } from "./shared";

const RefreshIcon = chakra(ArrowPathIcon, { baseStyle: { w: 4, h: 4 } });
const AddIcon = chakra(PlusIcon, { baseStyle: { w: 4, h: 4 } });

const blockStatus = (row: IPBlock): "blocked" | "expired" | "revoked" => {
  if (!row.is_active) return "revoked";
  if (row.expires_at && !dayjs.utc(row.expires_at).isAfter(dayjs.utc())) return "expired";
  return "blocked";
};

export const SecurityWorkspace = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const createModal = useDisclosure();
  const [list, setList] = useState(initialPageState);
  const [source, setSource] = useState("");
  const debouncedSearch = useDebouncedValue(list.search);
  const queryState = useMemo(() => ({ ...list, search: debouncedSearch }), [list, debouncedSearch]);
  const [security, setSecurity] = useState<PortalSecuritySettings | null>(null);
  const [network, setNetwork] = useState("");
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [savingSecurity, setSavingSecurity] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  const blocksQuery = useQuery(
    ["commerce", "blocks", queryState, source],
    () => fetch<PageResult<IPBlock>>(pageUrl("/commerce/admin/security/blocks", queryState, { source })),
    { keepPreviousData: true },
  );
  const securityQuery = useQuery(["commerce", "security-settings"], () => fetch<PortalSecuritySettings>("/commerce/admin/security/settings"));
  useEffect(() => { if (securityQuery.data) setSecurity(securityQuery.data); }, [securityQuery.data]);
  const result = blocksQuery.data || { items: [], total: 0, page: list.page, page_size: list.pageSize };

  useEffect(() => {
    if (blocksQuery.isFetching) return;
    const lastPage = Math.max(1, Math.ceil(result.total / list.pageSize));
    if (list.page > lastPage) setList((current) => ({ ...current, page: lastPage }));
  }, [blocksQuery.isFetching, list.page, list.pageSize, result.total]);

  const saveSecurity = async () => {
    if (!security) return;
    setSavingSecurity(true);
    try {
      const updated = await fetch<PortalSecuritySettings>("/commerce/admin/security/settings", { method: "PUT", body: security });
      setSecurity(updated);
      queryClient.setQueryData(["commerce", "security-settings"], updated);
      toast({ title: t("commerce.securitySaved"), status: "success", position: "top" });
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    } finally {
      setSavingSecurity(false);
    }
  };

  const createBlock = async () => {
    if (!network.trim() || !reason.trim()) {
      toast({ title: t("commerce.blockFieldsRequired"), status: "error", position: "top" });
      return;
    }
    setCreating(true);
    try {
      await fetch("/commerce/admin/security/blocks", {
        method: "POST",
        body: { network: network.trim(), reason: reason.trim(), expires_at: expiresAt ? dayjs(expiresAt).toISOString() : null },
      });
      setNetwork(""); setReason(""); setExpiresAt("");
      createModal.onClose();
      await queryClient.invalidateQueries(["commerce", "blocks"]);
      toast({ title: t("commerce.blockCreated"), status: "success", position: "top" });
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id: number) => {
    setRevokingId(id);
    try {
      await fetch(`/commerce/admin/security/blocks/${id}/revoke`, { method: "POST" });
      await queryClient.invalidateQueries(["commerce", "blocks"]);
      toast({ title: t("commerce.actionSuccess"), status: "success", position: "top" });
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <VStack align="stretch" spacing="4">
      {securityQuery.isError && (
        <Alert status="error" rounded="2xl">
          <AlertIcon />
          <AlertDescription flex="1">{t("commerce.loadError")}</AlertDescription>
          <Button size="sm" variant="ghost" onClick={() => securityQuery.refetch()}>{t("commerce.refresh")}</Button>
        </Alert>
      )}
      <Accordion allowToggle layerStyle="glass" rounded="3xl" overflow="hidden">
        <AccordionItem border="0">
          <AccordionButton px={{ base: 4, md: 6 }} py="5">
            <Box flex="1" textAlign="start"><Text fontWeight="750">{t("commerce.autoBlockPolicy")}</Text><Text mt="1" fontSize="sm" color="fg.muted">{t("commerce.autoBlockHelp")}</Text></Box>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel px={{ base: 4, md: 6 }} pb="6">
            {security && (
              <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} spacing="4">
                <FormControl display="flex" alignItems="center" gap="3"><Switch isChecked={security.auto_block_enabled} onChange={(event) => setSecurity({ ...security, auto_block_enabled: event.target.checked })} /><FormLabel mb="0">{t("commerce.autoBlockEnabled")}</FormLabel></FormControl>
                <FormControl><FormLabel>{t("commerce.loginFailureLimit")}</FormLabel><Input type="number" min="2" max="100" value={security.login_failure_limit} onChange={(event) => setSecurity({ ...security, login_failure_limit: Number(event.target.value) })} /></FormControl>
                <FormControl><FormLabel>{t("commerce.loginWindowMinutes")}</FormLabel><Input type="number" min="1" value={security.login_window_seconds / 60} onChange={(event) => setSecurity({ ...security, login_window_seconds: Number(event.target.value) * 60 })} /></FormControl>
                <FormControl><FormLabel>{t("commerce.registrationFailureLimit")}</FormLabel><Input type="number" min="2" max="100" value={security.registration_failure_limit} onChange={(event) => setSecurity({ ...security, registration_failure_limit: Number(event.target.value) })} /></FormControl>
                <FormControl><FormLabel>{t("commerce.registrationWindowMinutes")}</FormLabel><Input type="number" min="1" value={security.registration_window_seconds / 60} onChange={(event) => setSecurity({ ...security, registration_window_seconds: Number(event.target.value) * 60 })} /></FormControl>
                <FormControl><FormLabel>{t("commerce.autoBlockHours")}</FormLabel><Input type="number" min="0" value={security.auto_block_seconds / 3600} onChange={(event) => setSecurity({ ...security, auto_block_seconds: Number(event.target.value) * 3600 })} /></FormControl>
                <Button gridColumn={{ md: "2", xl: "3" }} justifySelf="end" colorScheme="primary" onClick={saveSecurity} isLoading={savingSecurity}>{t("commerce.saveSecurity")}</Button>
              </SimpleGrid>
            )}
          </AccordionPanel>
        </AccordionItem>
      </Accordion>

      {blocksQuery.isError && (
        <Alert status="error" rounded="2xl">
          <AlertIcon />
          <AlertDescription flex="1">{t("commerce.loadError")}</AlertDescription>
          <Button size="sm" variant="ghost" onClick={() => blocksQuery.refetch()}>{t("commerce.refresh")}</Button>
        </Alert>
      )}

      <DataWorkspace
        title={t("commerce.blacklist")}
        description={t("commerce.blacklistWorkspaceHelp")}
        total={result.total}
        isLoading={blocksQuery.isLoading}
        isEmpty={!blocksQuery.isLoading && !result.items.length}
        emptyTitle={list.search || list.status || source ? t("commerce.noMatchingBlocks") : t("commerce.noBlocks")}
        toolbar={(
          <HStack w={{ base: "full", md: "auto" }} flexWrap="wrap" justify="flex-end">
            <WorkspaceSearch state={list} setState={setList} isLoading={blocksQuery.isFetching} placeholder={t("commerce.searchBlocks")} />
            <Select size="sm" w={{ base: "calc(50% - 8px)", md: "140px" }} rounded="xl" value={list.status} onChange={(event) => setList((value) => ({ ...value, status: event.target.value, page: 1 }))} aria-label={t("commerce.filterByStatus")}>
              <option value="">{t("commerce.allStatuses")}</option><option value="blocked">{t("commerce.blocked")}</option><option value="expired">{t("commerce.expired")}</option><option value="revoked">{t("commerce.revoked")}</option>
            </Select>
            <Select size="sm" w={{ base: "calc(50% - 8px)", md: "150px" }} rounded="xl" value={source} onChange={(event) => { setSource(event.target.value); setList((value) => ({ ...value, page: 1 })); }} aria-label={t("commerce.filterBySource")}>
              <option value="">{t("commerce.allSources")}</option><option value="manual">{t("commerce.blockSource.manual")}</option><option value="portal_login">{t("commerce.blockSource.portal_login")}</option><option value="admin_login">{t("commerce.blockSource.admin_login")}</option><option value="portal_registration">{t("commerce.blockSource.portal_registration")}</option>
            </Select>
            <IconButton size="sm" variant="ghost" aria-label={t("commerce.refresh")} icon={<RefreshIcon className={blocksQuery.isFetching ? "animate-spin" : ""} />} onClick={() => blocksQuery.refetch()} />
            <Button size="sm" colorScheme="red" leftIcon={<AddIcon />} onClick={createModal.onOpen}>{t("commerce.addToBlacklist")}</Button>
          </HStack>
        )}
      >
        <TableContainer>
          <Table size="sm" className="workspace-table" minW="980px">
            <Thead><Tr><Th>{t("commerce.ipOrCidr")}</Th><Th>{t("commerce.status")}</Th><Th>{t("commerce.source")}</Th><Th>{t("commerce.blockReason")}</Th><Th>{t("commerce.expiresAt")}</Th><Th>{t("commerce.createdBy")}</Th><Th w="100px" /></Tr></Thead>
            <Tbody>
              {result.items.map((row) => {
                const state = blockStatus(row);
                return (
                  <Tr key={row.id} className="workspace-row">
                    <Td><Code fontSize="xs">{row.network}</Code></Td>
                    <Td><Badge colorScheme={state === "blocked" ? "red" : "gray"} rounded="full">{t(`commerce.${state}`)}</Badge></Td>
                    <Td>{t(`commerce.blockSource.${row.source}`)}</Td>
                    <Td maxW="300px"><Text noOfLines={2}>{row.reason}</Text></Td>
                    <Td>{row.expires_at ? dayjs.utc(row.expires_at).local().format("YYYY-MM-DD HH:mm") : t("commerce.neverExpires")}</Td>
                    <Td><Text>{row.created_by}</Text><Text fontSize="xs" color="fg.subtle">{dayjs.utc(row.created_at).local().format("YYYY-MM-DD HH:mm")}</Text></Td>
                    <Td isNumeric><Button size="xs" variant="ghost" colorScheme="red" isDisabled={!row.is_active} isLoading={revokingId === row.id} onClick={() => revoke(row.id)}>{t("commerce.unblock")}</Button></Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </TableContainer>
        <PaginationControls page={result.page} pageSize={result.page_size} total={result.total} onPageChange={(page) => setList((value) => ({ ...value, page }))} onPageSizeChange={(pageSize) => setList((value) => ({ ...value, page: 1, pageSize }))} />
      </DataWorkspace>

      <Modal isOpen={createModal.isOpen} onClose={createModal.onClose} size="xl" isCentered>
        <ModalOverlay backdropFilter="blur(12px)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>{t("commerce.manualBlock")}</ModalHeader><ModalCloseButton />
          <ModalBody><VStack align="stretch" spacing="4"><FormControl><FormLabel>{t("commerce.ipOrCidr")}</FormLabel><Input placeholder="203.0.113.8 or 203.0.113.0/24" value={network} onChange={(event) => setNetwork(event.target.value)} /></FormControl><FormControl><FormLabel>{t("commerce.blockReason")}</FormLabel><Input value={reason} onChange={(event) => setReason(event.target.value)} /></FormControl><FormControl><FormLabel>{t("commerce.blockExpires")}</FormLabel><Input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></FormControl></VStack></ModalBody>
          <ModalFooter gap="3"><Button variant="ghost" onClick={createModal.onClose}>{t("cancel")}</Button><Button colorScheme="red" onClick={createBlock} isLoading={creating}>{t("commerce.addToBlacklist")}</Button></ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  );
};
