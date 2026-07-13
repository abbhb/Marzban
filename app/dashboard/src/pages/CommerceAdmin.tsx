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
  FormControl,
  FormLabel,
  Grid,
  Heading,
  HStack,
  Input,
  Select,
  SimpleGrid,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Textarea,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { Footer } from "components/Footer";
import { Language } from "components/Language";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import { PortalAccount, SubscriptionPlan } from "types/Commerce";
import { formatBytes } from "utils/formatByte";

type Inbound = { tag: string; protocol: string };
type Draft = {
  name: string;
  description: string;
  price: string;
  durationDays: string;
  dataLimitGb: string;
  inboundTags: string[];
  isActive: boolean;
  isDefault: boolean;
};

const emptyDraft: Draft = {
  name: "",
  description: "",
  price: "",
  durationDays: "30",
  dataLimitGb: "100",
  inboundTags: [],
  isActive: true,
  isDefault: false,
};

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;

export const CommerceAdmin = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [accounts, setAccounts] = useState<PortalAccount[]>([]);
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tabIndex, setTabIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [recharges, setRecharges] = useState<Record<number, string>>({});
  const [renewDays, setRenewDays] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [planRows, accountRows, inboundMap] = await Promise.all([
        fetch<SubscriptionPlan[]>("/commerce/admin/plans"),
        fetch<PortalAccount[]>("/commerce/admin/accounts"),
        fetch<Record<string, Inbound[]>>("/inbounds"),
      ]);
      setPlans(planRows);
      setAccounts(accountRows);
      setInbounds(Object.values(inboundMap).flat().filter((item) => item.protocol === "vless"));
    } catch {
      toast({ title: t("commerce.loadError"), status: "error", position: "top" });
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => { load(); }, [load]);

  const planById = useMemo(() => new Map(plans.map((plan) => [plan.id, plan])), [plans]);

  const edit = (plan: SubscriptionPlan) => {
    setEditingId(plan.id);
    setDraft({
      name: plan.name,
      description: plan.description,
      price: (plan.price_minor / 100).toFixed(2),
      durationDays: String(plan.duration_days),
      dataLimitGb: String(plan.data_limit / 1024 ** 3),
      inboundTags: plan.inbound_tags,
      isActive: plan.is_active,
      isDefault: plan.is_default,
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
        is_active: draft.isActive,
        is_default: draft.isDefault,
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

  const assign = (accountId: number, value: string) =>
    action(`/commerce/admin/accounts/${accountId}/assigned-plan`, "PUT", {
      plan_id: value ? Number(value) : null,
    });

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

  return (
    <VStack minH="100vh" p={{ base: 4, md: 8 }} spacing="6" align="stretch">
      <HStack justify="space-between">
        <Box><Heading size="lg">{t("commerce.title")}</Heading><Text color="gray.500">{t("commerce.subtitle")}</Text></Box>
        <HStack><Language /><Button variant="outline" onClick={() => navigate("/")}>{t("commerce.backToUsers")}</Button></HStack>
      </HStack>

      {loading ? <VStack py="20"><Spinner color="primary.500" /></VStack> : (
        <Tabs colorScheme="primary" isLazy index={tabIndex} onChange={setTabIndex}>
          <TabList><Tab>{t("commerce.plans")}</Tab><Tab>{t("commerce.accounts")}</Tab></TabList>
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
                    <HStack><Checkbox isChecked={draft.isActive} onChange={(e) => setDraft({ ...draft, isActive: e.target.checked })}>{t("commerce.active")}</Checkbox><Checkbox isChecked={draft.isDefault} onChange={(e) => setDraft({ ...draft, isDefault: e.target.checked })}>{t("commerce.defaultForRegistration")}</Checkbox></HStack>
                    <HStack justify={{ md: "end" }}><Button variant="ghost" onClick={() => { setDraft(emptyDraft); setEditingId(null); }}>{t("commerce.clear")}</Button><Button colorScheme="primary" onClick={savePlan} isLoading={saving}>{t("commerce.savePlan")}</Button></HStack>
                  </SimpleGrid>
                </CardBody>
              </Card>

              <SimpleGrid columns={{ base: 1, lg: 2 }} spacing="4">
                {plans.map((plan) => <Card key={plan.id}><CardBody><HStack justify="space-between" align="start"><Box><HStack><Heading size="sm">{plan.name}</Heading>{plan.is_default && <Badge colorScheme="purple">{t("commerce.default")}</Badge>}{!plan.is_active && <Badge>{t("commerce.offShelf")}</Badge>}</HStack><Text mt="2" color="gray.500" fontSize="sm">{plan.description}</Text><Text mt="3" fontWeight="bold">{money(plan.price_minor)} · {plan.duration_days} {t("portal.days")} · {plan.data_limit ? formatBytes(plan.data_limit) : t("portal.unlimited")}</Text><Text fontSize="xs" mt="2" color="gray.500">{plan.inbound_tags.join(" · ")}</Text></Box><Button size="sm" onClick={() => edit(plan)}>{t("commerce.edit")}</Button></HStack></CardBody></Card>)}
              </SimpleGrid>
            </TabPanel>

            <TabPanel px="0">
              {!accounts.length && <Alert status="info"><AlertIcon /><AlertDescription>{t("commerce.noAccounts")}</AlertDescription></Alert>}
              <VStack align="stretch" spacing="4">
                {accounts.map((account) => {
                  const assigned = account.assigned_plan_id ? planById.get(account.assigned_plan_id) : null;
                  return <Card key={account.id}><CardBody><Grid templateColumns={{ base: "1fr", xl: "1.2fr 1fr 1.5fr" }} gap="5">
                    <Box><HStack><Heading size="sm">{account.username}</Heading><Badge colorScheme={account.usage.status === "active" ? "green" : "gray"}>{account.usage.status ? t(`status.${account.usage.status}`) : t("portal.notActivated")}</Badge></HStack><Text mt="2">{t("portal.walletBalance")}: <b>{money(account.wallet_balance_minor)}</b></Text><Text fontSize="sm" color="gray.500">{t("portal.trafficUsage")}: {formatBytes(account.usage.used_traffic)} / {account.usage.data_limit ? formatBytes(account.usage.data_limit) : "-"}</Text>{account.subscription && <Text fontSize="sm" color="gray.500">{account.subscription.plan_name} · {dayjs(account.subscription.expires_at).format("YYYY-MM-DD")}</Text>}</Box>
                    <VStack align="stretch"><FormControl><FormLabel>{t("commerce.visiblePlan")}</FormLabel><Select value={account.assigned_plan_id || ""} onChange={(e) => assign(account.id, e.target.value)}><option value="">{t("commerce.noPlanAssigned")}</option>{plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name}{!plan.is_active ? ` (${t("commerce.offShelf")})` : ""}</option>)}</Select></FormControl><Button size="sm" colorScheme="primary" isDisabled={!assigned} onClick={() => action(`/commerce/admin/accounts/${account.id}/subscription/grant`, "POST", {}, true)}>{t("commerce.grantOverwrite")}</Button></VStack>
                    <VStack align="stretch"><HStack><Input type="number" min="0.01" step="0.01" placeholder={t("commerce.rechargeCny")} value={recharges[account.id] || ""} onChange={(e) => setRecharges({ ...recharges, [account.id]: e.target.value })} /><Button onClick={() => recharge(account.id)}>{t("commerce.recharge")}</Button></HStack><HStack><Input type="number" min="1" placeholder="30" value={renewDays[account.id] || ""} onChange={(e) => setRenewDays({ ...renewDays, [account.id]: e.target.value })} /><Button isDisabled={!account.subscription} onClick={() => renew(account.id)}>{t("commerce.renewDays")}</Button></HStack><Button size="sm" variant="outline" colorScheme="red" isDisabled={!account.subscription || !!account.subscription.disabled_at} onClick={() => action(`/commerce/admin/accounts/${account.id}/subscription/disable`, "POST")}>{t("commerce.disableSubscription")}</Button></VStack>
                  </Grid></CardBody></Card>;
                })}
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      )}
      <Footer />
    </VStack>
  );
};
