import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  chakra,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerOverlay,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  IconButton,
  Input,
  Select,
  Stack,
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
import { ArrowPathIcon, ChevronRightIcon } from "@heroicons/react/24/outline";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "react-query";
import { fetch } from "service/http";
import { PageResult, PortalAccount, SubscriptionPlan } from "types/Commerce";
import { formatBytes } from "utils/formatByte";
import {
  initialPageState,
  money,
  pageUrl,
  useDebouncedValue,
  WorkspaceSearch,
} from "./shared";

const RefreshIcon = chakra(ArrowPathIcon, { baseStyle: { w: 4, h: 4 } });
const DetailIcon = chakra(ChevronRightIcon, { baseStyle: { w: 4, h: 4 } });

export const AccountsWorkspace = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const drawer = useDisclosure();
  const [list, setList] = useState(initialPageState);
  const debouncedSearch = useDebouncedValue(list.search);
  const queryState = useMemo(
    () => ({ ...list, search: debouncedSearch }),
    [list, debouncedSearch]
  );
  const [selected, setSelected] = useState<PortalAccount | null>(null);
  const [planId, setPlanId] = useState("");
  const [rechargeValue, setRechargeValue] = useState("");
  const [renewValue, setRenewValue] = useState("30");
  const [busy, setBusy] = useState("");

  const accountsQuery = useQuery(
    ["commerce", "accounts", queryState],
    () =>
      fetch<PageResult<PortalAccount>>(
        pageUrl("/commerce/admin/accounts", queryState)
      ),
    { keepPreviousData: true }
  );
  const plansQuery = useQuery(["commerce", "plans"], () =>
    fetch<SubscriptionPlan[]>("/commerce/admin/plans")
  );
  const result = accountsQuery.data || {
    items: [],
    total: 0,
    page: list.page,
    page_size: list.pageSize,
  };

  useEffect(() => {
    if (accountsQuery.isFetching) return;
    const lastPage = Math.max(1, Math.ceil(result.total / list.pageSize));
    if (list.page > lastPage)
      setList((current) => ({ ...current, page: lastPage }));
  }, [accountsQuery.isFetching, list.page, list.pageSize, result.total]);

  const openAccount = (account: PortalAccount) => {
    setSelected(account);
    setPlanId(String(account.subscription?.plan_id || ""));
    setRechargeValue("");
    setRenewValue("30");
    drawer.onOpen();
  };

  const closeDrawer = () => {
    if (busy) return;
    drawer.onClose();
    setSelected(null);
  };

  const run = async (
    name: string,
    url: string,
    body?: object,
    idempotent = false
  ) => {
    setBusy(name);
    try {
      await fetch(url, {
        method: "POST",
        body,
        headers: idempotent
          ? { "Idempotency-Key": crypto.randomUUID() }
          : undefined,
      });
      await queryClient.invalidateQueries(["commerce", "accounts"]);
      toast({
        title: t("commerce.actionSuccess"),
        status: "success",
        position: "top",
      });
      drawer.onClose();
      setSelected(null);
    } catch (error: any) {
      toast({
        title: error?.data?.detail || t("commerce.actionError"),
        status: "error",
        position: "top",
      });
    } finally {
      setBusy("");
    }
  };

  const grant = () =>
    selected &&
    planId &&
    run(
      "grant",
      `/commerce/admin/accounts/${selected.id}/subscription/grant`,
      { plan_id: Number(planId) },
      true
    );

  const recharge = () => {
    if (!selected) return;
    const amount = Math.round(Number(rechargeValue) * 100);
    if (!Number.isFinite(amount) || amount <= 0) return;
    run(
      "recharge",
      `/commerce/admin/accounts/${selected.id}/wallet/recharge`,
      { amount_minor: amount, note: t("commerce.adminRechargeNote") },
      true
    );
  };

  const renew = () => {
    if (!selected) return;
    const days = Number(renewValue);
    if (!Number.isInteger(days) || days <= 0) return;
    run(
      "renew",
      `/commerce/admin/accounts/${selected.id}/subscription/renew`,
      { days },
      true
    );
  };

  return (
    <>
      {accountsQuery.isError && (
        <Alert status="error" rounded="2xl" mb="4">
          <AlertIcon />
          <AlertDescription>{t("commerce.loadError")}</AlertDescription>
        </Alert>
      )}
      <DataWorkspace
        title={t("commerce.accounts")}
        description={t("commerce.accountsWorkspaceHelp")}
        total={result.total}
        isLoading={accountsQuery.isLoading}
        isEmpty={!accountsQuery.isLoading && !result.items.length}
        emptyTitle={
          list.search || list.status
            ? t("commerce.noMatchingAccounts")
            : t("commerce.noAccounts")
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
              isLoading={accountsQuery.isFetching}
              placeholder={t("commerce.searchAccounts")}
            />
            <Select
              size="sm"
              w={{ base: "calc(100% - 48px)", md: "170px" }}
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
              <option value="active">{t("status.active")}</option>
              <option value="on_hold">{t("status.on_hold")}</option>
              <option value="disabled">{t("status.disabled")}</option>
              <option value="limited">{t("status.limited")}</option>
              <option value="expired">{t("status.expired")}</option>
              <option value="not_activated">{t("portal.notActivated")}</option>
            </Select>
            <IconButton
              size="sm"
              variant="ghost"
              aria-label={t("commerce.refresh")}
              icon={
                <RefreshIcon
                  className={accountsQuery.isFetching ? "animate-spin" : ""}
                />
              }
              onClick={() => accountsQuery.refetch()}
            />
          </HStack>
        }
      >
        <TableContainer>
          <Table size="sm" className="workspace-table" minW="940px">
            <Thead>
              <Tr>
                <Th>{t("username")}</Th>
                <Th>{t("commerce.status")}</Th>
                <Th>{t("portal.currentPlan")}</Th>
                <Th>{t("portal.trafficUsage")}</Th>
                <Th isNumeric>{t("portal.walletBalance")}</Th>
                <Th>{t("commerce.createdAt")}</Th>
                <Th w="56px" />
              </Tr>
            </Thead>
            <Tbody>
              {result.items.map((account) => {
                const status = account.usage.status;
                return (
                  <Tr
                    key={account.id}
                    className="workspace-row"
                    role="button"
                    tabIndex={0}
                    aria-label={`${t("commerce.openDetails")}: ${
                      account.username
                    }`}
                    cursor="pointer"
                    _focusVisible={{
                      outline: "2px solid",
                      outlineColor: "primary.400",
                      outlineOffset: "-2px",
                    }}
                    onClick={() => openAccount(account)}
                    onKeyDown={(event) => {
                      if (
                        event.target !== event.currentTarget ||
                        (event.key !== "Enter" && event.key !== " ")
                      )
                        return;
                      event.preventDefault();
                      openAccount(account);
                    }}
                  >
                    <Td>
                      <Text fontWeight="700">{account.username}</Text>
                      <Text fontSize="xs" color="fg.subtle">
                        #{account.id}
                      </Text>
                    </Td>
                    <Td>
                      <Badge
                        colorScheme={
                          status === "active"
                            ? "green"
                            : status === "on_hold"
                            ? "orange"
                            : "gray"
                        }
                        rounded="full"
                      >
                        {status
                          ? t(`status.${status}`)
                          : t("portal.notActivated")}
                      </Badge>
                    </Td>
                    <Td>
                      <Text fontWeight="600">
                        {account.subscription?.plan_name || "—"}
                      </Text>
                      {account.subscription && (
                        <Text fontSize="xs" color="fg.subtle">
                          {dayjs(account.subscription.expires_at).format(
                            "YYYY-MM-DD"
                          )}
                        </Text>
                      )}
                    </Td>
                    <Td>
                      <Text>{formatBytes(account.usage.used_traffic)}</Text>
                      <Text fontSize="xs" color="fg.subtle">
                        /{" "}
                        {account.usage.data_limit
                          ? formatBytes(account.usage.data_limit)
                          : "—"}
                      </Text>
                    </Td>
                    <Td isNumeric fontWeight="700">
                      {money(account.wallet_balance_minor)}
                    </Td>
                    <Td color="fg.muted">
                      {dayjs
                        .utc(account.created_at)
                        .local()
                        .format("YYYY-MM-DD HH:mm")}
                    </Td>
                    <Td>
                      <IconButton
                        size="sm"
                        variant="ghost"
                        aria-label={t("commerce.openDetails")}
                        icon={<DetailIcon />}
                        onClick={(event) => {
                          event.stopPropagation();
                          openAccount(account);
                        }}
                      />
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

      <Drawer
        isOpen={drawer.isOpen}
        onClose={closeDrawer}
        placement="right"
        size="md"
      >
        <DrawerOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <DrawerContent layerStyle="glass-strong">
          <DrawerCloseButton />
          <DrawerHeader borderBottomWidth="1px" borderColor="border.subtle">
            <Text fontSize="xs" color="fg.subtle">
              {t("commerce.accountDetails")}
            </Text>
            <Heading mt="1" size="md">
              {selected?.username}
            </Heading>
          </DrawerHeader>
          <DrawerBody py="6">
            {selected && (
              <VStack align="stretch" spacing="6">
                <Stack direction={{ base: "column", sm: "row" }} spacing="3">
                  <Box flex="1" layerStyle="glassSubtle" rounded="2xl" p="4">
                    <Text fontSize="xs" color="fg.subtle">
                      {t("portal.walletBalance")}
                    </Text>
                    <Text mt="1" fontSize="xl" fontWeight="800">
                      {money(selected.wallet_balance_minor)}
                    </Text>
                  </Box>
                  <Box flex="1" layerStyle="glassSubtle" rounded="2xl" p="4">
                    <Text fontSize="xs" color="fg.subtle">
                      {t("portal.trafficUsage")}
                    </Text>
                    <Text mt="1" fontSize="xl" fontWeight="800">
                      {formatBytes(selected.usage.used_traffic)}
                    </Text>
                  </Box>
                </Stack>

                <Box>
                  <Heading size="sm" mb="3">
                    {t("commerce.subscriptionActions")}
                  </Heading>
                  <FormControl>
                    <FormLabel>{t("commerce.grantPlan")}</FormLabel>
                    <Select
                      value={planId}
                      onChange={(event) => setPlanId(event.target.value)}
                    >
                      <option value="">{t("commerce.selectPlan")}</option>
                      {(plansQuery.data || []).map((plan) => (
                        <option key={plan.id} value={plan.id}>
                          {plan.name}
                          {!plan.is_visible ? ` (${t("commerce.hidden")})` : ""}
                        </option>
                      ))}
                    </Select>
                  </FormControl>
                  <Button
                    mt="3"
                    w="full"
                    colorScheme="primary"
                    onClick={grant}
                    isDisabled={!planId}
                    isLoading={busy === "grant"}
                  >
                    {t("commerce.grantOverwrite")}
                  </Button>
                </Box>

                <Box>
                  <Heading size="sm" mb="3">
                    {t("commerce.walletActions")}
                  </Heading>
                  <HStack>
                    <Input
                      type="number"
                      min="0.01"
                      step="0.01"
                      placeholder={t("commerce.rechargeCny")}
                      value={rechargeValue}
                      onChange={(event) => setRechargeValue(event.target.value)}
                    />
                    <Button onClick={recharge} isLoading={busy === "recharge"}>
                      {t("commerce.recharge")}
                    </Button>
                  </HStack>
                </Box>

                <Box>
                  <Heading size="sm" mb="3">
                    {t("commerce.renewalActions")}
                  </Heading>
                  <HStack>
                    <Input
                      type="number"
                      min="1"
                      value={renewValue}
                      onChange={(event) => setRenewValue(event.target.value)}
                    />
                    <Button
                      onClick={renew}
                      isDisabled={!selected.subscription}
                      isLoading={busy === "renew"}
                    >
                      {t("commerce.renewDays")}
                    </Button>
                  </HStack>
                </Box>

                <Button
                  variant="outline"
                  colorScheme="red"
                  isDisabled={
                    !selected.subscription ||
                    !!selected.subscription.disabled_at
                  }
                  isLoading={busy === "disable"}
                  onClick={() =>
                    run(
                      "disable",
                      `/commerce/admin/accounts/${selected.id}/subscription/disable`
                    )
                  }
                >
                  {t("commerce.disableSubscription")}
                </Button>
              </VStack>
            )}
          </DrawerBody>
          <DrawerFooter borderTopWidth="1px" borderColor="border.subtle">
            <Button variant="ghost" onClick={closeDrawer}>
              {t("close")}
            </Button>
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </>
  );
};
