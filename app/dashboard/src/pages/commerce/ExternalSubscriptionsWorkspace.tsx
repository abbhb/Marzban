import {
  Alert,
  AlertDescription,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  HStack,
  Icon,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Spinner,
  Switch,
  Text,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowPathIcon,
  ArrowUpTrayIcon,
  KeyIcon,
  PlusIcon,
} from "@heroicons/react/24/outline";
import { DataWorkspace, PaginationControls } from "components/DataWorkspace";
import dayjs from "dayjs";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "react-query";
import { fetch } from "service/http";
import {
  ExternalSubscriptionNode,
  ExternalSubscriptionSource,
  PageResult,
} from "types/Commerce";
import { WorkspaceSearch, initialPageState, pageUrl, useDebouncedValue } from "./shared";

type SourceDraft = {
  name: string;
  groupName: string;
  url: string;
  refreshIntervalMinutes: string;
  enabled: boolean;
};

type MetadataDraft = {
  name: string;
  refreshIntervalMinutes: string;
  enabled: boolean;
};

const emptyDraft: SourceDraft = {
  name: "",
  groupName: "",
  url: "",
  refreshIntervalMinutes: "360",
  enabled: true,
};

const statusColor = (status: string) => {
  switch (status) {
    case "ready":
      return "green";
    case "auth_required":
      return "orange";
    case "error":
      return "red";
    case "disabled":
      return "gray";
    default:
      return "purple";
  }
};

const safeErrorCode = (value?: string | null) =>
  value && /^[A-Za-z0-9_.-]{1,64}$/.test(value) ? value : null;

const formatTime = (value?: string | null) =>
  value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";

export const ExternalSubscriptionsWorkspace = ({
  onReady,
}: {
  onReady?: () => void;
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const createModal = useDisclosure();
  const metadataModal = useDisclosure();
  const credentialModal = useDisclosure();
  const clearCredentialDialog = useDisclosure();
  const deleteDialog = useDisclosure();
  const detailsDrawer = useDisclosure();
  const snapshotInputRef = useRef<HTMLInputElement | null>(null);
  const deleteCancelRef = useRef<HTMLButtonElement | null>(null);
  const clearCredentialCancelRef = useRef<HTMLButtonElement | null>(null);
  const [draft, setDraft] = useState<SourceDraft>(emptyDraft);
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft>({
    name: "",
    refreshIntervalMinutes: "360",
    enabled: true,
  });
  const [credential, setCredential] = useState("");
  const [selectedSource, setSelectedSource] =
    useState<ExternalSubscriptionSource | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  const [nodeState, setNodeState] = useState(initialPageState);
  const [sourceState, setSourceState] = useState({
    ...initialPageState,
    pageSize: 20,
  });
  const debouncedNodeSearch = useDebouncedValue(nodeState.search);

  const sourcesQuery = useQuery(
    ["commerce", "external-subscriptions"],
    ({ signal }) =>
      fetch<ExternalSubscriptionSource[]>(
        "/commerce/admin/external-subscriptions",
        { timeout: 15000, signal }
      ),
    { retry: false }
  );
  const nodesQuery = useQuery(
    [
      "commerce",
      "external-subscription-nodes",
      selectedSource?.id,
      nodeState.page,
      nodeState.pageSize,
      debouncedNodeSearch,
    ],
    ({ signal }) =>
      fetch<PageResult<ExternalSubscriptionNode>>(
        pageUrl(
          `/commerce/admin/external-subscriptions/${selectedSource?.id}/nodes`,
          { ...nodeState, search: debouncedNodeSearch }
        ),
        { timeout: 15000, signal }
      ),
    {
      enabled: Boolean(selectedSource && detailsDrawer.isOpen),
      keepPreviousData: true,
      retry: false,
    }
  );

  useEffect(() => {
    if (!sourcesQuery.isLoading) onReady?.();
  }, [onReady, sourcesQuery.isLoading]);

  const closeCreate = () => {
    createModal.onClose();
    setDraft(emptyDraft);
  };

  const closeCredential = () => {
    credentialModal.onClose();
    setCredential("");
  };

  const showActionError = () =>
    toast({
      title: t("commerce.externalActionError"),
      status: "error",
      position: "top",
    });

  const createSource = async () => {
    const interval = Number(draft.refreshIntervalMinutes);
    if (
      !draft.name.trim() ||
      !Number.isInteger(interval) ||
      interval < 15
    ) {
      toast({
        title: t("commerce.externalInvalid"),
        status: "error",
        position: "top",
      });
      return;
    }
    setSaving(true);
    try {
      await fetch("/commerce/admin/external-subscriptions", {
        method: "POST",
        body: {
          name: draft.name.trim(),
          group_name: draft.groupName.trim() || draft.name.trim(),
          url: draft.url.trim() || undefined,
          refresh_interval_minutes: interval,
          enabled: draft.enabled,
        },
      });
      await queryClient.invalidateQueries([
        "commerce",
        "external-subscriptions",
      ]);
      toast({
        title: t("commerce.externalCreated"),
        status: "success",
        position: "top",
      });
      closeCreate();
    } catch {
      showActionError();
    } finally {
      setSaving(false);
    }
  };

  const closeMetadata = () => {
    metadataModal.onClose();
    setMetadataDraft({
      name: "",
      refreshIntervalMinutes: "360",
      enabled: true,
    });
  };

  const openMetadata = (source: ExternalSubscriptionSource) => {
    setSelectedSource(source);
    setMetadataDraft({
      name: source.name,
      refreshIntervalMinutes: String(source.refresh_interval_minutes),
      enabled: source.enabled,
    });
    metadataModal.onOpen();
  };

  const saveMetadata = async () => {
    const interval = Number(metadataDraft.refreshIntervalMinutes);
    if (
      !selectedSource ||
      !metadataDraft.name.trim() ||
      !Number.isInteger(interval) ||
      interval < 15 ||
      interval > 10080
    ) {
      toast({
        title: t("commerce.externalInvalid"),
        status: "error",
        position: "top",
      });
      return;
    }
    setSaving(true);
    try {
      await fetch(`/commerce/admin/external-subscriptions/${selectedSource.id}`, {
        method: "PUT",
        body: {
          name: metadataDraft.name.trim(),
          refresh_interval_minutes: interval,
          enabled: metadataDraft.enabled,
        },
      });
      await queryClient.invalidateQueries([
        "commerce",
        "external-subscriptions",
      ]);
      toast({
        title: t("commerce.externalUpdated"),
        status: "success",
        position: "top",
      });
      closeMetadata();
    } catch {
      showActionError();
    } finally {
      setSaving(false);
    }
  };

  const requestDelete = (source: ExternalSubscriptionSource) => {
    setSelectedSource(source);
    deleteDialog.onOpen();
  };

  const deleteSource = async () => {
    if (!selectedSource) return;
    setSaving(true);
    try {
      await fetch(`/commerce/admin/external-subscriptions/${selectedSource.id}`, {
        method: "DELETE",
      });
      await Promise.all([
        queryClient.invalidateQueries(["commerce", "external-subscriptions"]),
        queryClient.invalidateQueries(["commerce", "plans"]),
      ]);
      toast({
        title: t("commerce.externalDeleted"),
        status: "success",
        position: "top",
      });
      deleteDialog.onClose();
      setSelectedSource(null);
    } catch (error: any) {
      toast({
        title:
          error?.data?.detail === "source_in_use"
            ? t("commerce.externalDeleteInUse")
            : t("commerce.externalActionError"),
        status: "error",
        position: "top",
      });
    } finally {
      setSaving(false);
    }
  };

  const refreshSource = async (source: ExternalSubscriptionSource) => {
    setActionId(source.id);
    try {
      await fetch(`/commerce/admin/external-subscriptions/${source.id}/refresh`, {
        method: "POST",
      });
      await Promise.all([
        queryClient.invalidateQueries(["commerce", "external-subscriptions"]),
        queryClient.invalidateQueries([
          "commerce",
          "external-subscription-nodes",
          source.id,
        ]),
      ]);
      toast({
        title: t("commerce.externalRefreshCompleted"),
        status: "success",
        position: "top",
      });
    } catch {
      showActionError();
    } finally {
      setActionId(null);
    }
  };

  const replaceCredential = async () => {
    if (!selectedSource || !credential.trim()) return;
    setSaving(true);
    try {
      await fetch(
        `/commerce/admin/external-subscriptions/${selectedSource.id}/credential`,
        { method: "POST", body: { url: credential.trim() } }
      );
      await queryClient.invalidateQueries([
        "commerce",
        "external-subscriptions",
      ]);
      toast({
        title: t("commerce.externalCredentialSaved"),
        status: "success",
        position: "top",
      });
      closeCredential();
    } catch {
      showActionError();
    } finally {
      setSaving(false);
    }
  };

  const requestClearCredential = () => {
    if (!selectedSource?.credential_configured) return;
    setCredential("");
    credentialModal.onClose();
    clearCredentialDialog.onOpen();
  };

  const clearCredential = async () => {
    if (!selectedSource) return;
    setSaving(true);
    try {
      await fetch(
        `/commerce/admin/external-subscriptions/${selectedSource.id}/credential`,
        { method: "DELETE" }
      );
      await queryClient.invalidateQueries([
        "commerce",
        "external-subscriptions",
      ]);
      toast({
        title: t("commerce.externalCredentialRemoved"),
        status: "success",
        position: "top",
      });
      clearCredentialDialog.onClose();
      setSelectedSource(null);
    } catch {
      showActionError();
    } finally {
      setSaving(false);
    }
  };

  const uploadSnapshot = async (event: ChangeEvent<HTMLInputElement>) => {
    const source = selectedSource;
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!source || !file) return;
    const body = new FormData();
    body.append("file", file);
    setActionId(source.id);
    try {
      await fetch(
        `/commerce/admin/external-subscriptions/${source.id}/snapshot`,
        { method: "POST", body }
      );
      await Promise.all([
        queryClient.invalidateQueries(["commerce", "external-subscriptions"]),
        queryClient.invalidateQueries([
          "commerce",
          "external-subscription-nodes",
          source.id,
        ]),
      ]);
      toast({
        title: t("commerce.externalSnapshotImported"),
        status: "success",
        position: "top",
      });
    } catch {
      showActionError();
    } finally {
      setActionId(null);
    }
  };

  const openDetails = (source: ExternalSubscriptionSource) => {
    setSelectedSource(source);
    setNodeState(initialPageState);
    detailsDrawer.onOpen();
  };

  const openCredential = (source: ExternalSubscriptionSource) => {
    setSelectedSource(source);
    setCredential("");
    credentialModal.onOpen();
  };

  if (sourcesQuery.isLoading) {
    return (
      <VStack py="20">
        <Spinner color="primary.500" />
      </VStack>
    );
  }

  if (sourcesQuery.isError) {
    return (
      <Alert status="error" rounded="2xl" alignItems="center">
        <AlertIcon />
        <AlertDescription flex="1">
          {t("commerce.externalLoadError")}
        </AlertDescription>
        <Button size="sm" variant="outline" onClick={() => sourcesQuery.refetch()}>
          {t("portal.retry")}
        </Button>
      </Alert>
    );
  }

  const sources = sourcesQuery.data || [];
  const normalizedSourceSearch = sourceState.search.trim().toLocaleLowerCase();
  const filteredSources = normalizedSourceSearch
    ? sources.filter((source) =>
        [source.name, source.group_name, source.status].some((value) =>
          value.toLocaleLowerCase().includes(normalizedSourceSearch)
        )
      )
    : sources;
  const sourcePageCount = Math.max(
    1,
    Math.ceil(filteredSources.length / sourceState.pageSize)
  );
  const safeSourcePage = Math.min(sourceState.page, sourcePageCount);
  const visibleSources = filteredSources.slice(
    (safeSourcePage - 1) * sourceState.pageSize,
    safeSourcePage * sourceState.pageSize
  );

  return (
    <>
      <Alert
        status="warning"
        rounded="2xl"
        mb="4"
        alignItems="flex-start"
        layerStyle="glassSubtle"
      >
        <AlertIcon mt="0.5" />
        <AlertDescription fontSize="sm">
          {t("commerce.externalSecurityBoundary")}
        </AlertDescription>
      </Alert>
      <DataWorkspace
        title={t("commerce.externalSubscriptions")}
        description={t("commerce.externalWorkspaceHelp")}
        total={filteredSources.length}
        toolbar={
          <HStack
            justify={{ base: "stretch", sm: "flex-end" }}
            flexWrap="wrap"
          >
            <WorkspaceSearch
              state={sourceState}
              setState={setSourceState}
              placeholder={t("commerce.externalSearchSources")}
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => sourcesQuery.refetch()}
              leftIcon={<Icon as={ArrowPathIcon} boxSize="4" />}
            >
              {t("commerce.refresh")}
            </Button>
            <Button
              size="sm"
              colorScheme="primary"
              onClick={createModal.onOpen}
              leftIcon={<Icon as={PlusIcon} boxSize="4" />}
            >
              {t("commerce.externalCreate")}
            </Button>
          </HStack>
        }
        isEmpty={!filteredSources.length}
        emptyTitle={
          sources.length
            ? t("commerce.externalNoSourcesMatch")
            : t("commerce.externalEmpty")
        }
        emptyDescription={
          sources.length ? undefined : t("commerce.externalEmptyHelp")
        }
      >
        <>
          <SimpleGrid
            columns={{ base: 1, xl: 2 }}
            spacing="4"
            px={{ base: 4, md: 6 }}
            pb="6"
          >
          {visibleSources.map((source) => {
            const errorCode = safeErrorCode(source.last_error_code);
            return (
              <Card key={source.id} rounded="2xl" variant="outline">
                <CardBody>
                  <HStack align="start" justify="space-between" gap="4">
                    <Box minW="0">
                      <HStack flexWrap="wrap">
                        <Heading size="sm" noOfLines={1}>
                          {source.name}
                        </Heading>
                        <Badge colorScheme={statusColor(source.status)}>
                          {t(`commerce.externalStatus.${source.status}`, {
                            defaultValue: source.status,
                          })}
                        </Badge>
                      </HStack>
                      <Text mt="1" fontSize="sm" color="fg.muted" noOfLines={1}>
                        {source.group_name}
                      </Text>
                    </Box>
                    <Text fontWeight="750" whiteSpace="nowrap">
                      {t("commerce.externalNodeCount", {
                        count: source.node_count,
                      })}
                    </Text>
                  </HStack>

                  <SimpleGrid columns={{ base: 1, sm: 2 }} spacing="3" mt="5">
                    <Box>
                      <Text fontSize="xs" color="fg.subtle">
                        {t("commerce.externalLastSuccess")}
                      </Text>
                      <Text fontSize="sm">{formatTime(source.last_success_at)}</Text>
                    </Box>
                    <Box>
                      <Text fontSize="xs" color="fg.subtle">
                        {t("commerce.externalNextUpdate")}
                      </Text>
                      <Text fontSize="sm">{formatTime(source.next_refresh_at)}</Text>
                    </Box>
                    <Box>
                      <Text fontSize="xs" color="fg.subtle">
                        {t("commerce.externalCredential")}
                      </Text>
                      <Text fontSize="sm">
                        {source.credential_configured
                          ? t("commerce.externalCredentialConfigured")
                          : t("commerce.externalCredentialMissing")}
                      </Text>
                    </Box>
                    <Box>
                      <Text fontSize="xs" color="fg.subtle">
                        {t("commerce.externalSkippedNodes")}
                      </Text>
                      <Text fontSize="sm">{source.skipped_node_count}</Text>
                    </Box>
                  </SimpleGrid>

                  {errorCode && (
                    <Text mt="3" fontSize="xs" color="orange.600">
                      {t("commerce.externalErrorCode")}: {errorCode}
                    </Text>
                  )}

                  <Divider my="4" borderColor="border.subtle" />
                  <HStack flexWrap="wrap" justify="flex-end">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => openMetadata(source)}
                    >
                      {t("commerce.externalEdit")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => openDetails(source)}>
                      {t("commerce.externalViewNodes")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      leftIcon={<Icon as={KeyIcon} boxSize="4" />}
                      onClick={() => openCredential(source)}
                    >
                      {t("commerce.externalReplaceCredential")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      leftIcon={<Icon as={ArrowUpTrayIcon} boxSize="4" />}
                      onClick={() => {
                        setSelectedSource(source);
                        snapshotInputRef.current?.click();
                      }}
                      isLoading={actionId === source.id}
                    >
                      {t("commerce.externalUploadSnapshot")}
                    </Button>
                    <Button
                      size="sm"
                      colorScheme="primary"
                      variant="outline"
                      leftIcon={<Icon as={ArrowPathIcon} boxSize="4" />}
                      onClick={() => refreshSource(source)}
                      isLoading={actionId === source.id}
                      isDisabled={!source.enabled || !source.credential_configured}
                    >
                      {t("commerce.externalRefreshNow")}
                    </Button>
                    <Button
                      size="sm"
                      colorScheme="red"
                      variant="ghost"
                      onClick={() => requestDelete(source)}
                    >
                      {t("commerce.externalDelete")}
                    </Button>
                  </HStack>
                </CardBody>
              </Card>
            );
          })}
          </SimpleGrid>
          <PaginationControls
            page={safeSourcePage}
            pageSize={sourceState.pageSize}
            total={filteredSources.length}
            pageSizeOptions={[10, 20]}
            onPageChange={(page) =>
              setSourceState((value) => ({ ...value, page }))
            }
            onPageSizeChange={(pageSize) =>
              setSourceState((value) => ({ ...value, pageSize, page: 1 }))
            }
          />
        </>
      </DataWorkspace>

      <Input
        ref={snapshotInputRef}
        type="file"
        display="none"
        accept=".yaml,.yml,text/yaml,application/x-yaml"
        onChange={uploadSnapshot}
      />

      <Modal isOpen={createModal.isOpen} onClose={closeCreate} isCentered size="xl">
        <ModalOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>{t("commerce.externalCreate")}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack align="stretch" spacing="4">
              <FormControl isRequired>
                <FormLabel>{t("commerce.externalName")}</FormLabel>
                <Input
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.externalGroupName")}</FormLabel>
                <Input
                  value={draft.groupName}
                  onChange={(event) =>
                    setDraft({ ...draft, groupName: event.target.value })
                  }
                />
                <FormHelperText>{t("commerce.externalGroupNameHelp")}</FormHelperText>
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.externalUrl")}</FormLabel>
                <Input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={draft.url}
                  onChange={(event) => setDraft({ ...draft, url: event.target.value })}
                />
                <FormHelperText>{t("commerce.externalUrlHelp")}</FormHelperText>
              </FormControl>
              <FormControl isRequired>
                <FormLabel>{t("commerce.externalInterval")}</FormLabel>
                <Input
                  type="number"
                  min="15"
                  step="1"
                  value={draft.refreshIntervalMinutes}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      refreshIntervalMinutes: event.target.value,
                    })
                  }
                />
              </FormControl>
              <FormControl display="flex" alignItems="center" justifyContent="space-between">
                <FormLabel mb="0">{t("commerce.externalEnabled")}</FormLabel>
                <Switch
                  colorScheme="primary"
                  isChecked={draft.enabled}
                  onChange={(event) =>
                    setDraft({ ...draft, enabled: event.target.checked })
                  }
                />
              </FormControl>
            </VStack>
          </ModalBody>
          <ModalFooter gap="3">
            <Button variant="ghost" onClick={closeCreate}>
              {t("cancel")}
            </Button>
            <Button colorScheme="primary" onClick={createSource} isLoading={saving}>
              {t("commerce.externalCreate")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal
        isOpen={metadataModal.isOpen}
        onClose={closeMetadata}
        isCentered
        size="lg"
      >
        <ModalOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>{t("commerce.externalEdit")}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack align="stretch" spacing="4">
              <FormControl isRequired>
                <FormLabel>{t("commerce.externalName")}</FormLabel>
                <Input
                  value={metadataDraft.name}
                  onChange={(event) =>
                    setMetadataDraft({
                      ...metadataDraft,
                      name: event.target.value,
                    })
                  }
                />
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.externalGroupName")}</FormLabel>
                <Input value={selectedSource?.group_name || ""} isReadOnly />
                <FormHelperText>
                  {t("commerce.externalGroupNameImmutable")}
                </FormHelperText>
              </FormControl>
              <FormControl isRequired>
                <FormLabel>{t("commerce.externalInterval")}</FormLabel>
                <Input
                  type="number"
                  min="15"
                  max="10080"
                  step="1"
                  value={metadataDraft.refreshIntervalMinutes}
                  onChange={(event) =>
                    setMetadataDraft({
                      ...metadataDraft,
                      refreshIntervalMinutes: event.target.value,
                    })
                  }
                />
              </FormControl>
              <FormControl
                display="flex"
                alignItems="center"
                justifyContent="space-between"
              >
                <FormLabel mb="0">{t("commerce.externalEnabled")}</FormLabel>
                <Switch
                  colorScheme="primary"
                  isChecked={metadataDraft.enabled}
                  onChange={(event) =>
                    setMetadataDraft({
                      ...metadataDraft,
                      enabled: event.target.checked,
                    })
                  }
                />
              </FormControl>
            </VStack>
          </ModalBody>
          <ModalFooter gap="3">
            <Button variant="ghost" onClick={closeMetadata}>
              {t("cancel")}
            </Button>
            <Button colorScheme="primary" onClick={saveMetadata} isLoading={saving}>
              {t("commerce.externalSaveChanges")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal
        isOpen={credentialModal.isOpen}
        onClose={closeCredential}
        isCentered
        size="lg"
      >
        <ModalOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>{t("commerce.externalReplaceCredential")}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <Alert status="info" rounded="2xl" mb="4">
              <AlertIcon />
              <AlertDescription>
                {t("commerce.externalCredentialWriteOnly")}
              </AlertDescription>
            </Alert>
            <FormControl isRequired>
              <FormLabel>{t("commerce.externalUrl")}</FormLabel>
              <Input
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
              />
            </FormControl>
            {selectedSource?.credential_configured && (
              <Button
                mt="4"
                size="sm"
                colorScheme="red"
                variant="outline"
                onClick={requestClearCredential}
              >
                {t("commerce.externalRemoveCredential")}
              </Button>
            )}
          </ModalBody>
          <ModalFooter gap="3">
            <Button variant="ghost" onClick={closeCredential}>
              {t("cancel")}
            </Button>
            <Button
              colorScheme="primary"
              onClick={replaceCredential}
              isLoading={saving}
              isDisabled={!credential.trim()}
            >
              {t("commerce.externalSaveCredential")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Drawer
        isOpen={detailsDrawer.isOpen}
        placement="right"
        size="lg"
        onClose={() => {
          detailsDrawer.onClose();
          setSelectedSource(null);
        }}
      >
        <DrawerOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <DrawerContent bg="surface.glass-strong" backdropFilter="var(--marzban-glass-filter-strong)">
          <DrawerCloseButton />
          <DrawerHeader>
            <Text>{selectedSource?.name}</Text>
            <Text mt="1" fontSize="sm" fontWeight="normal" color="fg.muted">
              {t("commerce.externalNodeMetadataOnly")}
            </Text>
          </DrawerHeader>
          <DrawerBody px={{ base: 4, md: 6 }} pb="6">
            <WorkspaceSearch
              state={nodeState}
              setState={setNodeState}
              isLoading={nodesQuery.isFetching}
              placeholder={t("commerce.externalSearchNodes")}
            />
            {nodesQuery.isError ? (
              <Alert mt="4" status="error" rounded="2xl">
                <AlertIcon />
                <AlertDescription>{t("commerce.externalNodesLoadError")}</AlertDescription>
              </Alert>
            ) : nodesQuery.isLoading ? (
              <VStack py="16">
                <Spinner color="primary.500" />
              </VStack>
            ) : (
              <VStack mt="4" align="stretch" spacing="2">
                {(nodesQuery.data?.items || []).map((node) => (
                  <HStack
                    key={node.id}
                    px="4"
                    py="3"
                    rounded="xl"
                    bg="surface.muted"
                    justify="space-between"
                    gap="3"
                  >
                    <Box minW="0">
                      <Text fontWeight="650" noOfLines={1}>
                        {node.name}
                      </Text>
                    </Box>
                    <HStack>
                      <Badge>{node.proxy_type}</Badge>
                      {!node.is_active && (
                        <Badge colorScheme="orange">
                          {t("commerce.externalNodeMissing")}
                        </Badge>
                      )}
                    </HStack>
                  </HStack>
                ))}
                {!(nodesQuery.data?.items || []).length && (
                  <VStack py="16">
                    <Text fontWeight="700">{t("commerce.externalNoNodes")}</Text>
                  </VStack>
                )}
              </VStack>
            )}
            {nodesQuery.data && (
              <PaginationControls
                page={nodeState.page}
                pageSize={nodeState.pageSize}
                total={nodesQuery.data.total}
                onPageChange={(page) => setNodeState((value) => ({ ...value, page }))}
                onPageSizeChange={(pageSize) =>
                  setNodeState((value) => ({ ...value, pageSize, page: 1 }))
                }
              />
            )}
          </DrawerBody>
        </DrawerContent>
      </Drawer>

      <AlertDialog
        isOpen={deleteDialog.isOpen}
        leastDestructiveRef={deleteCancelRef}
        onClose={() => {
          deleteDialog.onClose();
          setSelectedSource(null);
        }}
        isCentered
      >
        <AlertDialogOverlay backdropFilter="var(--marzban-overlay-filter)">
          <AlertDialogContent layerStyle="glass-strong" rounded="3xl" mx="4">
            <AlertDialogHeader>{t("commerce.externalDelete")}</AlertDialogHeader>
            <AlertDialogBody>
              {t("commerce.externalDeleteWarning", {
                name: selectedSource?.name,
              })}
            </AlertDialogBody>
            <AlertDialogFooter gap="3">
              <Button
                ref={deleteCancelRef}
                variant="ghost"
                onClick={() => {
                  deleteDialog.onClose();
                  setSelectedSource(null);
                }}
              >
                {t("cancel")}
              </Button>
              <Button colorScheme="red" onClick={deleteSource} isLoading={saving}>
                {t("commerce.externalConfirmDelete")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>

      <AlertDialog
        isOpen={clearCredentialDialog.isOpen}
        leastDestructiveRef={clearCredentialCancelRef}
        onClose={() => {
          clearCredentialDialog.onClose();
          setSelectedSource(null);
        }}
        isCentered
      >
        <AlertDialogOverlay backdropFilter="var(--marzban-overlay-filter)">
          <AlertDialogContent layerStyle="glass-strong" rounded="3xl" mx="4">
            <AlertDialogHeader>
              {t("commerce.externalRemoveCredential")}
            </AlertDialogHeader>
            <AlertDialogBody>
              {t("commerce.externalRemoveCredentialWarning")}
            </AlertDialogBody>
            <AlertDialogFooter gap="3">
              <Button
                ref={clearCredentialCancelRef}
                variant="ghost"
                onClick={() => {
                  clearCredentialDialog.onClose();
                  setSelectedSource(null);
                }}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="red"
                variant="outline"
                onClick={clearCredential}
                isLoading={saving}
              >
                {t("commerce.externalConfirmRemoveCredential")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  );
};
