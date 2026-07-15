import {
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
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useClipboard,
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
import { CreatedInvitation, Invitation, PageResult } from "types/Commerce";
import {
  initialPageState,
  pageUrl,
  useDebouncedValue,
  WorkspaceSearch,
} from "./shared";

const RefreshIcon = chakra(ArrowPathIcon, { baseStyle: { w: 4, h: 4 } });
const AddIcon = chakra(PlusIcon, { baseStyle: { w: 4, h: 4 } });

type InvitationDraft = {
  note: string;
  usageMode: "once" | "limited" | "unlimited";
  maxUses: string;
  validityMode: "permanent" | "scheduled";
  validFrom: string;
  expiresAt: string;
};

const emptyDraft: InvitationDraft = {
  note: "",
  usageMode: "once",
  maxUses: "5",
  validityMode: "permanent",
  validFrom: "",
  expiresAt: "",
};

const invitationStatus = (
  row: Invitation
): "available" | "scheduled" | "expired" | "exhausted" | "disabled" => {
  if (!row.is_active) return "disabled";
  if (row.valid_from && dayjs.utc(row.valid_from).isAfter(dayjs.utc()))
    return "scheduled";
  if (row.expires_at && !dayjs.utc(row.expires_at).isAfter(dayjs.utc()))
    return "expired";
  if (
    row.max_uses !== null &&
    row.max_uses !== undefined &&
    row.use_count >= row.max_uses
  )
    return "exhausted";
  return "available";
};

export const InvitationsWorkspace = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const createModal = useDisclosure();
  const [list, setList] = useState(initialPageState);
  const debouncedSearch = useDebouncedValue(list.search);
  const queryState = useMemo(
    () => ({ ...list, search: debouncedSearch }),
    [list, debouncedSearch]
  );
  const [draft, setDraft] = useState(emptyDraft);
  const [createdCode, setCreatedCode] = useState("");
  const [saving, setSaving] = useState(false);
  const [disablingId, setDisablingId] = useState<number | null>(null);
  const clipboard = useClipboard(createdCode);
  const invitationsQuery = useQuery(
    ["commerce", "invitations", queryState],
    () =>
      fetch<PageResult<Invitation>>(
        pageUrl("/commerce/admin/invitations", queryState)
      ),
    { keepPreviousData: true }
  );
  const result = invitationsQuery.data || {
    items: [],
    total: 0,
    page: list.page,
    page_size: list.pageSize,
  };

  useEffect(() => {
    if (invitationsQuery.isFetching) return;
    const lastPage = Math.max(1, Math.ceil(result.total / list.pageSize));
    if (list.page > lastPage)
      setList((current) => ({ ...current, page: lastPage }));
  }, [invitationsQuery.isFetching, list.page, list.pageSize, result.total]);

  const createInvitation = async () => {
    const maxUses =
      draft.usageMode === "unlimited"
        ? null
        : draft.usageMode === "once"
        ? 1
        : Number(draft.maxUses);
    if (maxUses !== null && (!Number.isInteger(maxUses) || maxUses < 1)) {
      toast({
        title: t("commerce.invitationInvalid"),
        status: "error",
        position: "top",
      });
      return;
    }
    if (draft.validityMode === "scheduled" && !draft.expiresAt) {
      toast({
        title: t("commerce.invitationExpiryRequired"),
        status: "error",
        position: "top",
      });
      return;
    }
    setSaving(true);
    try {
      const row = await fetch<CreatedInvitation>(
        "/commerce/admin/invitations",
        {
          method: "POST",
          body: {
            note: draft.note,
            max_uses: maxUses,
            valid_from:
              draft.validityMode === "scheduled" && draft.validFrom
                ? dayjs(draft.validFrom).toISOString()
                : null,
            expires_at:
              draft.validityMode === "scheduled"
                ? dayjs(draft.expiresAt).toISOString()
                : null,
          },
        }
      );
      setCreatedCode(row.code);
      setDraft(emptyDraft);
      createModal.onClose();
      await queryClient.invalidateQueries(["commerce", "invitations"]);
      toast({
        title: t("commerce.invitationCreated"),
        status: "success",
        position: "top",
      });
    } catch (error: any) {
      toast({
        title: error?.data?.detail || t("commerce.actionError"),
        status: "error",
        position: "top",
      });
    } finally {
      setSaving(false);
    }
  };

  const disable = async (id: number) => {
    setDisablingId(id);
    try {
      await fetch(`/commerce/admin/invitations/${id}/disable`, {
        method: "POST",
      });
      await queryClient.invalidateQueries(["commerce", "invitations"]);
      toast({
        title: t("commerce.actionSuccess"),
        status: "success",
        position: "top",
      });
    } catch (error: any) {
      toast({
        title: error?.data?.detail || t("commerce.actionError"),
        status: "error",
        position: "top",
      });
    } finally {
      setDisablingId(null);
    }
  };

  return (
    <>
      {invitationsQuery.isError && (
        <Alert status="error" rounded="2xl" mb="4">
          <AlertIcon />
          <AlertDescription flex="1">
            {t("commerce.loadError")}
          </AlertDescription>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => invitationsQuery.refetch()}
          >
            {t("commerce.refresh")}
          </Button>
        </Alert>
      )}
      {createdCode && (
        <Alert
          status="warning"
          rounded="2xl"
          mb="4"
          alignItems="start"
          layerStyle="glassSubtle"
        >
          <AlertIcon mt="1" />
          <Box flex="1" minW="0">
            <AlertDescription fontWeight="700">
              {t("commerce.invitationShownOnce")}
            </AlertDescription>
            <HStack mt="3" align="stretch">
              <Input
                readOnly
                value={createdCode}
                fontFamily="mono"
                bg="surface.input"
              />
              <Button onClick={clipboard.onCopy}>
                {t(clipboard.hasCopied ? "commerce.copied" : "commerce.copy")}
              </Button>
            </HStack>
          </Box>
        </Alert>
      )}

      <DataWorkspace
        title={t("commerce.invitations")}
        description={t("commerce.invitationsWorkspaceHelp")}
        total={result.total}
        isLoading={invitationsQuery.isLoading}
        isEmpty={!invitationsQuery.isLoading && !result.items.length}
        emptyTitle={
          list.search || list.status
            ? t("commerce.noMatchingInvitations")
            : t("commerce.noInvitations")
        }
        toolbar={
          <HStack
            w={{ base: "full", md: "auto" }}
            flexWrap="wrap"
            justify="flex-end"
          >
            <WorkspaceSearch
              state={list}
              setState={setList}
              isLoading={invitationsQuery.isFetching}
              placeholder={t("commerce.searchInvitations")}
            />
            <Select
              size="sm"
              w={{ base: "calc(100% - 48px)", md: "150px" }}
              rounded="xl"
              value={list.status}
              onChange={(event) =>
                setList((value) => ({
                  ...value,
                  status: event.target.value,
                  page: 1,
                }))
              }
              aria-label={t("commerce.filterByStatus")}
            >
              <option value="">{t("commerce.allStatuses")}</option>
              <option value="available">{t("commerce.available")}</option>
              <option value="scheduled">{t("commerce.scheduled")}</option>
              <option value="expired">{t("commerce.expired")}</option>
              <option value="exhausted">{t("commerce.exhausted")}</option>
              <option value="disabled">{t("status.disabled")}</option>
            </Select>
            <IconButton
              size="sm"
              variant="ghost"
              aria-label={t("commerce.refresh")}
              icon={
                <RefreshIcon
                  className={invitationsQuery.isFetching ? "animate-spin" : ""}
                />
              }
              onClick={() => invitationsQuery.refetch()}
            />
            <Button
              size="sm"
              colorScheme="primary"
              leftIcon={<AddIcon />}
              onClick={createModal.onOpen}
            >
              {t("commerce.createInvitation")}
            </Button>
          </HStack>
        }
      >
        <TableContainer>
          <Table size="sm" className="workspace-table" minW="900px">
            <Thead>
              <Tr>
                <Th>{t("commerce.invitationCode")}</Th>
                <Th>{t("commerce.invitationNote")}</Th>
                <Th>{t("commerce.status")}</Th>
                <Th>{t("commerce.invitationUsageCount")}</Th>
                <Th>{t("commerce.validityWindow")}</Th>
                <Th>{t("commerce.createdBy")}</Th>
                <Th w="100px" />
              </Tr>
            </Thead>
            <Tbody>
              {result.items.map((row) => {
                const state = invitationStatus(row);
                return (
                  <Tr key={row.id} className="workspace-row">
                    <Td>
                      <Code fontSize="xs">{row.code_prefix}…</Code>
                    </Td>
                    <Td maxW="260px">
                      <Text noOfLines={2}>
                        {row.note || t("commerce.noNote")}
                      </Text>
                    </Td>
                    <Td>
                      <Badge
                        colorScheme={
                          state === "available"
                            ? "green"
                            : state === "scheduled"
                            ? "blue"
                            : "gray"
                        }
                        rounded="full"
                      >
                        {t(
                          state === "disabled"
                            ? "status.disabled"
                            : `commerce.${state}`
                        )}
                      </Badge>
                    </Td>
                    <Td>
                      {row.use_count} /{" "}
                      {row.max_uses ?? t("commerce.unlimited")}
                    </Td>
                    <Td>
                      <Text fontSize="xs">
                        {row.valid_from
                          ? dayjs
                              .utc(row.valid_from)
                              .local()
                              .format("YYYY-MM-DD HH:mm")
                          : t("commerce.immediate")}
                      </Text>
                      <Text fontSize="xs" color="fg.subtle">
                        →{" "}
                        {row.expires_at
                          ? dayjs
                              .utc(row.expires_at)
                              .local()
                              .format("YYYY-MM-DD HH:mm")
                          : t("commerce.neverExpires")}
                      </Text>
                    </Td>
                    <Td>
                      <Text>{row.created_by}</Text>
                      <Text fontSize="xs" color="fg.subtle">
                        {dayjs
                          .utc(row.created_at)
                          .local()
                          .format("YYYY-MM-DD HH:mm")}
                      </Text>
                    </Td>
                    <Td isNumeric>
                      <Button
                        size="xs"
                        variant="ghost"
                        colorScheme="red"
                        isDisabled={!row.is_active}
                        isLoading={disablingId === row.id}
                        onClick={() => disable(row.id)}
                      >
                        {t("commerce.disableInvitation")}
                      </Button>
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </TableContainer>
        <PaginationControls
          page={result.page}
          pageSize={result.page_size}
          total={result.total}
          onPageChange={(page) => setList((value) => ({ ...value, page }))}
          onPageSizeChange={(pageSize) =>
            setList((value) => ({ ...value, page: 1, pageSize }))
          }
        />
      </DataWorkspace>

      <Modal
        isOpen={createModal.isOpen}
        onClose={createModal.onClose}
        size="2xl"
        isCentered
      >
        <ModalOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>{t("commerce.createInvitation")}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack align="stretch" spacing="4">
              <FormControl>
                <FormLabel>{t("commerce.invitationNote")}</FormLabel>
                <Input
                  value={draft.note}
                  onChange={(event) =>
                    setDraft({ ...draft, note: event.target.value })
                  }
                />
              </FormControl>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing="4">
                <FormControl>
                  <FormLabel>{t("commerce.invitationUsage")}</FormLabel>
                  <Select
                    value={draft.usageMode}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        usageMode: event.target
                          .value as InvitationDraft["usageMode"],
                      })
                    }
                  >
                    <option value="once">{t("commerce.invitationOnce")}</option>
                    <option value="limited">
                      {t("commerce.invitationNTimes")}
                    </option>
                    <option value="unlimited">
                      {t("commerce.invitationUnlimitedUses")}
                    </option>
                  </Select>
                </FormControl>
                {draft.usageMode === "limited" && (
                  <FormControl>
                    <FormLabel>{t("commerce.invitationMaxUses")}</FormLabel>
                    <Input
                      type="number"
                      min="1"
                      max="1000000"
                      value={draft.maxUses}
                      onChange={(event) =>
                        setDraft({ ...draft, maxUses: event.target.value })
                      }
                    />
                  </FormControl>
                )}
                <FormControl>
                  <FormLabel>{t("commerce.invitationValidity")}</FormLabel>
                  <Select
                    value={draft.validityMode}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        validityMode: event.target
                          .value as InvitationDraft["validityMode"],
                      })
                    }
                  >
                    <option value="permanent">
                      {t("commerce.invitationPermanent")}
                    </option>
                    <option value="scheduled">
                      {t("commerce.invitationScheduled")}
                    </option>
                  </Select>
                </FormControl>
                {draft.validityMode === "scheduled" && (
                  <>
                    <FormControl>
                      <FormLabel>{t("commerce.validFrom")}</FormLabel>
                      <Input
                        type="datetime-local"
                        value={draft.validFrom}
                        onChange={(event) =>
                          setDraft({ ...draft, validFrom: event.target.value })
                        }
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>{t("commerce.expiresAt")}</FormLabel>
                      <Input
                        type="datetime-local"
                        value={draft.expiresAt}
                        onChange={(event) =>
                          setDraft({ ...draft, expiresAt: event.target.value })
                        }
                      />
                    </FormControl>
                  </>
                )}
              </SimpleGrid>
            </VStack>
          </ModalBody>
          <ModalFooter gap="3">
            <Button variant="ghost" onClick={createModal.onClose}>
              {t("cancel")}
            </Button>
            <Button
              colorScheme="primary"
              onClick={createInvitation}
              isLoading={saving}
            >
              {t("commerce.generateInvitation")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
};
