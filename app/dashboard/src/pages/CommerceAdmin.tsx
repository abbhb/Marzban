import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Code,
  FormControl,
  FormLabel,
  Grid,
  Heading,
  HStack,
  Input,
  Select,
  SimpleGrid,
  Spinner,
  Switch,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Textarea,
  useToast,
  useClipboard,
  VStack,
} from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { Footer } from "components/Footer";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import {
  CreatedInvitation,
  IPBlock,
  Invitation,
  PortalAccount,
  PortalSecuritySettings,
  SubscriptionPlan,
} from "types/Commerce";
import { formatBytes } from "utils/formatByte";

type Inbound = { tag: string; protocol: string };
type Draft = {
  name: string;
  description: string;
  price: string;
  durationDays: string;
  dataLimitGb: string;
  inboundTags: string[];
  isVisible: boolean;
};

type InvitationDraft = {
  note: string;
  usageMode: "once" | "limited" | "unlimited";
  maxUses: string;
  validityMode: "permanent" | "scheduled";
  validFrom: string;
  expiresAt: string;
};

type BlockDraft = {
  network: string;
  reason: string;
  expiresAt: string;
};

const emptyDraft: Draft = {
  name: "",
  description: "",
  price: "",
  durationDays: "30",
  dataLimitGb: "100",
  inboundTags: [],
  isVisible: true,
};

const emptyInvitationDraft: InvitationDraft = {
  note: "",
  usageMode: "once",
  maxUses: "5",
  validityMode: "permanent",
  validFrom: "",
  expiresAt: "",
};

const emptyBlockDraft: BlockDraft = { network: "", reason: "", expiresAt: "" };

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;
const localTime = (value: string): string => dayjs.utc(value).local().format("YYYY-MM-DD HH:mm");

export const CommerceAdmin = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [accounts, setAccounts] = useState<PortalAccount[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [blocks, setBlocks] = useState<IPBlock[]>([]);
  const [security, setSecurity] = useState<PortalSecuritySettings | null>(null);
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tabIndex, setTabIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [recharges, setRecharges] = useState<Record<number, string>>({});
  const [renewDays, setRenewDays] = useState<Record<number, string>>({});
  const [grantPlans, setGrantPlans] = useState<Record<number, string>>({});
  const [invitationDraft, setInvitationDraft] = useState<InvitationDraft>(emptyInvitationDraft);
  const [blockDraft, setBlockDraft] = useState<BlockDraft>(emptyBlockDraft);
  const [createdCode, setCreatedCode] = useState("");
  const [savingSecurity, setSavingSecurity] = useState(false);
  const { hasCopied, onCopy } = useClipboard(createdCode);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [planRows, accountRows, inboundMap, invitationRows, blockRows, securitySettings] = await Promise.all([
        fetch<SubscriptionPlan[]>("/commerce/admin/plans"),
        fetch<PortalAccount[]>("/commerce/admin/accounts"),
        fetch<Record<string, Inbound[]>>("/inbounds"),
        fetch<Invitation[]>("/commerce/admin/invitations"),
        fetch<IPBlock[]>("/commerce/admin/security/blocks"),
        fetch<PortalSecuritySettings>("/commerce/admin/security/settings"),
      ]);
      setPlans(planRows);
      setAccounts(accountRows);
      setInbounds(Object.values(inboundMap).flat().filter((item) => item.protocol === "vless"));
      setInvitations(invitationRows);
      setBlocks(blockRows);
      setSecurity(securitySettings);
    } catch {
      toast({ title: t("commerce.loadError"), status: "error", position: "top" });
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => { load(); }, [load]);

  const edit = (plan: SubscriptionPlan) => {
    setEditingId(plan.id);
    setDraft({
      name: plan.name,
      description: plan.description,
      price: (plan.price_minor / 100).toFixed(2),
      durationDays: String(plan.duration_days),
      dataLimitGb: String(plan.data_limit / 1024 ** 3),
      inboundTags: plan.inbound_tags,
      isVisible: plan.is_visible,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const savePlan = async () => {
    const priceMinor = Math.round(Number(draft.price) * 100);
    const durationDays = Number(draft.durationDays);
    const dataLimit = Math.round(Number(draft.dataLimitGb) * 1024 ** 3);
    if (!draft.name || !Number.isFinite(priceMinor) || !Number.isFinite(durationDays) || !Number.isFinite(dataLimit) || !draft.inboundTags.length) {
      toast({ title: t("commerce.invalidPlan"), status: "error", position: "top" });
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: draft.name,
        description: draft.description,
        price_minor: priceMinor,
        currency: "CNY",
        duration_days: durationDays,
        data_limit: dataLimit,
        inbound_tags: draft.inboundTags,
        is_visible: draft.isVisible,
      };
      await fetch(editingId ? `/commerce/admin/plans/${editingId}` : "/commerce/admin/plans", {
        method: editingId ? "PUT" : "POST",
        body,
      });
      toast({ title: t("commerce.planSaved"), status: "success", position: "top" });
      setDraft(emptyDraft);
      setEditingId(null);
      await load();
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.saveError"), status: "error", position: "top" });
    } finally {
      setSaving(false);
    }
  };

  const action = async (
    url: string,
    method: "POST" | "PUT",
    body?: object,
    idempotent = false,
  ) => {
    try {
      await fetch(url, {
        method,
        body,
        headers: idempotent ? { "Idempotency-Key": crypto.randomUUID() } : undefined,
      });
      toast({ title: t("commerce.actionSuccess"), status: "success", position: "top" });
      await load();
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    }
  };

  const grant = (accountId: number, planId: string) =>
    action(`/commerce/admin/accounts/${accountId}/subscription/grant`, "POST", {
      plan_id: Number(planId),
    }, true);

  const recharge = (accountId: number) => {
    const amount = Math.round(Number(recharges[accountId]) * 100);
    if (!amount || amount <= 0) return;
    return action(`/commerce/admin/accounts/${accountId}/wallet/recharge`, "POST", {
      amount_minor: amount,
      note: t("commerce.adminRechargeNote"),
    }, true).then(() => setRecharges((values) => ({ ...values, [accountId]: "" })));
  };

  const renew = (accountId: number) => {
    const days = Number(renewDays[accountId] || 30);
    if (!Number.isInteger(days) || days <= 0) return;
    return action(`/commerce/admin/accounts/${accountId}/subscription/renew`, "POST", { days }, true);
  };

  const createInvitation = async () => {
    const maxUses = invitationDraft.usageMode === "unlimited"
      ? null
      : invitationDraft.usageMode === "once"
        ? 1
        : Number(invitationDraft.maxUses);
    if (maxUses !== null && (!Number.isInteger(maxUses) || maxUses < 1)) {
      toast({ title: t("commerce.invitationInvalid"), status: "error", position: "top" });
      return;
    }
    if (invitationDraft.validityMode === "scheduled" && !invitationDraft.expiresAt) {
      toast({ title: t("commerce.invitationExpiryRequired"), status: "error", position: "top" });
      return;
    }
    try {
      const row = await fetch<CreatedInvitation>("/commerce/admin/invitations", {
        method: "POST",
        body: {
          note: invitationDraft.note,
          max_uses: maxUses,
          valid_from: invitationDraft.validityMode === "scheduled" && invitationDraft.validFrom
            ? dayjs(invitationDraft.validFrom).toISOString()
            : null,
          expires_at: invitationDraft.validityMode === "scheduled"
            ? dayjs(invitationDraft.expiresAt).toISOString()
            : null,
        },
      });
      setCreatedCode(row.code);
      setInvitationDraft(emptyInvitationDraft);
      toast({ title: t("commerce.invitationCreated"), status: "success", position: "top" });
      await load();
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    }
  };

  const createBlock = async () => {
    if (!blockDraft.network.trim() || !blockDraft.reason.trim()) {
      toast({ title: t("commerce.blockFieldsRequired"), status: "error", position: "top" });
      return;
    }
    try {
      await fetch("/commerce/admin/security/blocks", {
        method: "POST",
        body: {
          network: blockDraft.network.trim(),
          reason: blockDraft.reason.trim(),
          expires_at: blockDraft.expiresAt ? dayjs(blockDraft.expiresAt).toISOString() : null,
        },
      });
      setBlockDraft(emptyBlockDraft);
      toast({ title: t("commerce.blockCreated"), status: "success", position: "top" });
      await load();
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    }
  };

  const saveSecurity = async () => {
    if (!security) return;
    setSavingSecurity(true);
    try {
      await fetch("/commerce/admin/security/settings", { method: "PUT", body: security });
      toast({ title: t("commerce.securitySaved"), status: "success", position: "top" });
      await load();
    } catch (error: any) {
      toast({ title: error?.data?.detail || t("commerce.actionError"), status: "error", position: "top" });
    } finally {
      setSavingSecurity(false);
    }
  };

  const invitationAvailable = (row: Invitation) =>
    row.is_active
    && (!row.valid_from || !dayjs.utc(row.valid_from).isAfter(dayjs.utc()))
    && (!row.expires_at || dayjs.utc(row.expires_at).isAfter(dayjs.utc()))
    && (row.max_uses === null || row.max_uses === undefined || row.use_count < row.max_uses);

  const blockActive = (row: IPBlock) =>
    row.is_active && (!row.expires_at || dayjs.utc(row.expires_at).isAfter(dayjs.utc()));

  return (
    <AdminShell>
      <VStack minH="100vh" p={{ base: 4, md: 8 }} spacing="6" align="stretch">
        <Box><Heading as="h1" size="lg">{t("commerce.title")}</Heading><Text color="gray.500">{t("commerce.subtitle")}</Text></Box>

        {loading ? <VStack py="20"><Spinner color="primary.500" /></VStack> : (
        <Tabs colorScheme="primary" isLazy index={tabIndex} onChange={setTabIndex}>
          <TabList overflowX="auto">
            <Tab>{t("commerce.plans")}</Tab>
            <Tab>{t("commerce.accounts")}</Tab>
            <Tab>{t("commerce.invitations")}</Tab>
            <Tab>{t("commerce.security")}</Tab>
          </TabList>
          <TabPanels>
            <TabPanel px="0">
              <Card mb="5">
                <CardHeader><Heading size="md">{editingId ? t("commerce.editPlan") : t("commerce.createPlan")}</Heading></CardHeader>
                <CardBody pt="0">
                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing="4">
                    <FormControl><FormLabel>{t("commerce.planName")}</FormLabel><Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.priceCny")}</FormLabel><Input type="number" min="0" step="0.01" value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.durationDays")}</FormLabel><Input type="number" min="1" value={draft.durationDays} onChange={(e) => setDraft({ ...draft, durationDays: e.target.value })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.dataLimitGb")}</FormLabel><Input type="number" min="0" value={draft.dataLimitGb} onChange={(e) => setDraft({ ...draft, dataLimitGb: e.target.value })} /></FormControl>
                    <FormControl gridColumn={{ md: "1 / -1" }}><FormLabel>{t("commerce.description")}</FormLabel><Textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></FormControl>
                    <FormControl gridColumn={{ md: "1 / -1" }}><FormLabel>{t("commerce.allowedNodes")}</FormLabel><SimpleGrid columns={{ base: 1, md: 2 }} spacing="2">{inbounds.map((inbound) => <Checkbox key={inbound.tag} isChecked={draft.inboundTags.includes(inbound.tag)} onChange={(e) => setDraft({ ...draft, inboundTags: e.target.checked ? [...draft.inboundTags, inbound.tag] : draft.inboundTags.filter((tag) => tag !== inbound.tag) })}>{inbound.tag}</Checkbox>)}</SimpleGrid></FormControl>
                    <HStack><Checkbox isChecked={draft.isVisible} onChange={(e) => setDraft({ ...draft, isVisible: e.target.checked })}>{t("commerce.visibleToUsers")}</Checkbox></HStack>
                    <HStack justify={{ md: "end" }}><Button variant="ghost" onClick={() => { setDraft(emptyDraft); setEditingId(null); }}>{t("commerce.clear")}</Button><Button colorScheme="primary" onClick={savePlan} isLoading={saving}>{t("commerce.savePlan")}</Button></HStack>
                  </SimpleGrid>
                </CardBody>
              </Card>

              <SimpleGrid columns={{ base: 1, lg: 2 }} spacing="4">
                {plans.map((plan) => <Card key={plan.id}><CardBody><HStack justify="space-between" align="start"><Box><HStack><Heading size="sm">{plan.name}</Heading>{!plan.is_visible && <Badge>{t("commerce.hidden")}</Badge>}</HStack><Text mt="2" color="gray.500" fontSize="sm">{plan.description}</Text><Text mt="3" fontWeight="bold">{money(plan.price_minor)} · {plan.duration_days} {t("portal.days")} · {plan.data_limit ? formatBytes(plan.data_limit) : t("portal.unlimited")}</Text><Text fontSize="xs" mt="2" color="gray.500">{plan.inbound_tags.join(" · ")}</Text></Box><Button size="sm" onClick={() => edit(plan)}>{t("commerce.edit")}</Button></HStack></CardBody></Card>)}
              </SimpleGrid>
            </TabPanel>

            <TabPanel px="0">
              {!accounts.length && <Alert status="info"><AlertIcon /><AlertDescription>{t("commerce.noAccounts")}</AlertDescription></Alert>}
              <VStack align="stretch" spacing="4">
                {accounts.map((account) => {
                  const selectedPlanId = grantPlans[account.id] || String(account.subscription?.plan_id || "");
                  return <Card key={account.id}><CardBody><Grid templateColumns={{ base: "1fr", xl: "1.2fr 1fr 1.5fr" }} gap="5">
                    <Box><HStack><Heading size="sm">{account.username}</Heading><Badge colorScheme={account.usage.status === "active" ? "green" : "gray"}>{account.usage.status ? t(`status.${account.usage.status}`) : t("portal.notActivated")}</Badge></HStack><Text mt="2">{t("portal.walletBalance")}: <b>{money(account.wallet_balance_minor)}</b></Text><Text fontSize="sm" color="gray.500">{t("portal.trafficUsage")}: {formatBytes(account.usage.used_traffic)} / {account.usage.data_limit ? formatBytes(account.usage.data_limit) : "-"}</Text>{account.subscription && <Text fontSize="sm" color="gray.500">{account.subscription.plan_name} · {dayjs(account.subscription.expires_at).format("YYYY-MM-DD")}</Text>}</Box>
                    <VStack align="stretch"><FormControl><FormLabel>{t("commerce.grantPlan")}</FormLabel><Select value={selectedPlanId} onChange={(e) => setGrantPlans({ ...grantPlans, [account.id]: e.target.value })}><option value="">{t("commerce.selectPlan")}</option>{plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name}{!plan.is_visible ? ` (${t("commerce.hidden")})` : ""}</option>)}</Select></FormControl><Button size="sm" colorScheme="primary" isDisabled={!selectedPlanId} onClick={() => grant(account.id, selectedPlanId)}>{t("commerce.grantOverwrite")}</Button></VStack>
                    <VStack align="stretch"><HStack><Input type="number" min="0.01" step="0.01" placeholder={t("commerce.rechargeCny")} value={recharges[account.id] || ""} onChange={(e) => setRecharges({ ...recharges, [account.id]: e.target.value })} /><Button onClick={() => recharge(account.id)}>{t("commerce.recharge")}</Button></HStack><HStack><Input type="number" min="1" placeholder="30" value={renewDays[account.id] || ""} onChange={(e) => setRenewDays({ ...renewDays, [account.id]: e.target.value })} /><Button isDisabled={!account.subscription} onClick={() => renew(account.id)}>{t("commerce.renewDays")}</Button></HStack><Button size="sm" variant="outline" colorScheme="red" isDisabled={!account.subscription || !!account.subscription.disabled_at} onClick={() => action(`/commerce/admin/accounts/${account.id}/subscription/disable`, "POST")}>{t("commerce.disableSubscription")}</Button></VStack>
                  </Grid></CardBody></Card>;
                })}
              </VStack>
            </TabPanel>

            <TabPanel px="0">
              {createdCode && (
                <Alert status="warning" rounded="md" mb="5" alignItems="start">
                  <AlertIcon />
                  <Box flex="1">
                    <AlertDescription fontWeight="semibold">{t("commerce.invitationShownOnce")}</AlertDescription>
                    <HStack mt="3" align="stretch">
                      <Input readOnly value={createdCode} fontFamily="mono" bg="white" color="black" />
                      <Button onClick={onCopy}>{t(hasCopied ? "commerce.copied" : "commerce.copy")}</Button>
                    </HStack>
                  </Box>
                </Alert>
              )}
              <Card mb="5">
                <CardHeader><Heading size="md">{t("commerce.createInvitation")}</Heading></CardHeader>
                <CardBody pt="0">
                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing="4">
                    <FormControl gridColumn={{ md: "1 / -1" }}>
                      <FormLabel>{t("commerce.invitationNote")}</FormLabel>
                      <Input value={invitationDraft.note} onChange={(e) => setInvitationDraft({ ...invitationDraft, note: e.target.value })} />
                    </FormControl>
                    <FormControl>
                      <FormLabel>{t("commerce.invitationUsage")}</FormLabel>
                      <Select value={invitationDraft.usageMode} onChange={(e) => setInvitationDraft({ ...invitationDraft, usageMode: e.target.value as InvitationDraft["usageMode"] })}>
                        <option value="once">{t("commerce.invitationOnce")}</option>
                        <option value="limited">{t("commerce.invitationNTimes")}</option>
                        <option value="unlimited">{t("commerce.invitationUnlimitedUses")}</option>
                      </Select>
                    </FormControl>
                    {invitationDraft.usageMode === "limited" && (
                      <FormControl>
                        <FormLabel>{t("commerce.invitationMaxUses")}</FormLabel>
                        <Input type="number" min="1" max="1000000" value={invitationDraft.maxUses} onChange={(e) => setInvitationDraft({ ...invitationDraft, maxUses: e.target.value })} />
                      </FormControl>
                    )}
                    <FormControl>
                      <FormLabel>{t("commerce.invitationValidity")}</FormLabel>
                      <Select value={invitationDraft.validityMode} onChange={(e) => setInvitationDraft({ ...invitationDraft, validityMode: e.target.value as InvitationDraft["validityMode"] })}>
                        <option value="permanent">{t("commerce.invitationPermanent")}</option>
                        <option value="scheduled">{t("commerce.invitationScheduled")}</option>
                      </Select>
                    </FormControl>
                    {invitationDraft.validityMode === "scheduled" && (
                      <>
                        <FormControl><FormLabel>{t("commerce.validFrom")}</FormLabel><Input type="datetime-local" value={invitationDraft.validFrom} onChange={(e) => setInvitationDraft({ ...invitationDraft, validFrom: e.target.value })} /></FormControl>
                        <FormControl><FormLabel>{t("commerce.expiresAt")}</FormLabel><Input type="datetime-local" value={invitationDraft.expiresAt} onChange={(e) => setInvitationDraft({ ...invitationDraft, expiresAt: e.target.value })} /></FormControl>
                      </>
                    )}
                    <HStack gridColumn={{ md: "1 / -1" }} justify="end">
                      <Button colorScheme="primary" onClick={createInvitation}>{t("commerce.generateInvitation")}</Button>
                    </HStack>
                  </SimpleGrid>
                </CardBody>
              </Card>

              {!invitations.length && <Alert status="info"><AlertIcon /><AlertDescription>{t("commerce.noInvitations")}</AlertDescription></Alert>}
              <VStack align="stretch" spacing="3">
                {invitations.map((row) => {
                  const available = invitationAvailable(row);
                  return <Card key={row.id}><CardBody><Grid templateColumns={{ base: "1fr", lg: "1.3fr 1fr auto" }} gap="4" alignItems="center">
                    <Box><HStack><Code>{row.code_prefix}…</Code><Badge colorScheme={available ? "green" : "gray"}>{t(available ? "commerce.available" : "commerce.unavailable")}</Badge></HStack><Text mt="2">{row.note || t("commerce.noNote")}</Text><Text fontSize="xs" color="gray.500">{t("commerce.createdBy")}: {row.created_by} · {localTime(row.created_at)}</Text></Box>
                    <Box><Text>{t("commerce.invitationUsageCount")}: {row.use_count} / {row.max_uses ?? t("commerce.unlimited")}</Text><Text fontSize="sm" color="gray.500">{row.valid_from ? localTime(row.valid_from) : t("commerce.immediate")} → {row.expires_at ? localTime(row.expires_at) : t("commerce.neverExpires")}</Text></Box>
                    <Button size="sm" colorScheme="red" variant="outline" isDisabled={!row.is_active} onClick={() => action(`/commerce/admin/invitations/${row.id}/disable`, "POST")}>{t("commerce.disableInvitation")}</Button>
                  </Grid></CardBody></Card>;
                })}
              </VStack>
            </TabPanel>

            <TabPanel px="0">
              {security && <Card mb="5">
                <CardHeader><Heading size="md">{t("commerce.autoBlockPolicy")}</Heading></CardHeader>
                <CardBody pt="0">
                  <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} spacing="4">
                    <FormControl display="flex" alignItems="center"><Switch mr="3" isChecked={security.auto_block_enabled} onChange={(e) => setSecurity({ ...security, auto_block_enabled: e.target.checked })} /><FormLabel mb="0">{t("commerce.autoBlockEnabled")}</FormLabel></FormControl>
                    <FormControl><FormLabel>{t("commerce.loginFailureLimit")}</FormLabel><Input type="number" min="2" max="100" value={security.login_failure_limit} onChange={(e) => setSecurity({ ...security, login_failure_limit: Number(e.target.value) })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.loginWindowMinutes")}</FormLabel><Input type="number" min="1" max="1440" value={security.login_window_seconds / 60} onChange={(e) => setSecurity({ ...security, login_window_seconds: Number(e.target.value) * 60 })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.registrationFailureLimit")}</FormLabel><Input type="number" min="2" max="100" value={security.registration_failure_limit} onChange={(e) => setSecurity({ ...security, registration_failure_limit: Number(e.target.value) })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.registrationWindowMinutes")}</FormLabel><Input type="number" min="1" max="1440" value={security.registration_window_seconds / 60} onChange={(e) => setSecurity({ ...security, registration_window_seconds: Number(e.target.value) * 60 })} /></FormControl>
                    <FormControl><FormLabel>{t("commerce.autoBlockHours")}</FormLabel><Input type="number" min="0" max="720" value={security.auto_block_seconds / 3600} onChange={(e) => setSecurity({ ...security, auto_block_seconds: Number(e.target.value) * 3600 })} /></FormControl>
                    <HStack gridColumn={{ md: "1 / -1" }} justify="end"><Button colorScheme="primary" onClick={saveSecurity} isLoading={savingSecurity}>{t("commerce.saveSecurity")}</Button></HStack>
                  </SimpleGrid>
                  <Text mt="3" fontSize="sm" color="gray.500">{t("commerce.autoBlockHelp")}</Text>
                </CardBody>
              </Card>}

              <Card mb="5">
                <CardHeader><Heading size="md">{t("commerce.manualBlock")}</Heading></CardHeader>
                <CardBody pt="0"><SimpleGrid columns={{ base: 1, md: 3 }} spacing="4">
                  <FormControl><FormLabel>{t("commerce.ipOrCidr")}</FormLabel><Input placeholder="203.0.113.8 or 203.0.113.0/24" value={blockDraft.network} onChange={(e) => setBlockDraft({ ...blockDraft, network: e.target.value })} /></FormControl>
                  <FormControl><FormLabel>{t("commerce.blockReason")}</FormLabel><Input value={blockDraft.reason} onChange={(e) => setBlockDraft({ ...blockDraft, reason: e.target.value })} /></FormControl>
                  <FormControl><FormLabel>{t("commerce.blockExpires")}</FormLabel><Input type="datetime-local" value={blockDraft.expiresAt} onChange={(e) => setBlockDraft({ ...blockDraft, expiresAt: e.target.value })} /></FormControl>
                  <HStack gridColumn={{ md: "1 / -1" }} justify="end"><Button colorScheme="red" onClick={createBlock}>{t("commerce.addToBlacklist")}</Button></HStack>
                </SimpleGrid></CardBody>
              </Card>

              {!blocks.length && <Alert status="info"><AlertIcon /><AlertDescription>{t("commerce.noBlocks")}</AlertDescription></Alert>}
              <VStack align="stretch" spacing="3">
                {blocks.map((row) => {
                  const active = blockActive(row);
                  return <Card key={row.id}><CardBody><Grid templateColumns={{ base: "1fr", lg: "1fr 1.5fr auto" }} gap="4" alignItems="center">
                    <Box><HStack><Code>{row.network}</Code><Badge colorScheme={active ? "red" : "gray"}>{t(active ? "commerce.blocked" : "commerce.inactive")}</Badge><Badge>{t(`commerce.blockSource.${row.source}`)}</Badge></HStack><Text fontSize="xs" mt="2" color="gray.500">{t("commerce.createdBy")}: {row.created_by} · {localTime(row.created_at)}</Text></Box>
                    <Box><Text>{row.reason}</Text><Text fontSize="sm" color="gray.500">{t("commerce.blockExpires")}: {row.expires_at ? localTime(row.expires_at) : t("commerce.neverExpires")}</Text></Box>
                    <Button size="sm" variant="outline" isDisabled={!row.is_active} onClick={() => action(`/commerce/admin/security/blocks/${row.id}/revoke`, "POST")}>{t("commerce.unblock")}</Button>
                  </Grid></CardBody></Card>;
                })}
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
        )}
        <Footer />
      </VStack>
    </AdminShell>
  );
};
