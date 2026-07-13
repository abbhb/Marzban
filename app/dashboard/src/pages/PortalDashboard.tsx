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
  chakra,
  Heading,
  HStack,
  Input,
  Link,
  Progress,
  SimpleGrid,
  Spinner,
  Stat,
  StatLabel,
  StatNumber,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { ArrowLeftOnRectangleIcon, FireIcon } from "@heroicons/react/24/outline";
import { Footer } from "components/Footer";
import { Language } from "components/Language";
import dayjs from "dayjs";
import { QRCodeCanvas } from "qrcode.react";
import { useCallback, useEffect, useRef, useState } from "react";
import CopyToClipboard from "react-copy-to-clipboard";
import { useTranslation } from "react-i18next";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { portalFetch } from "service/http";
import {
  MgmaIssue,
  PortalAccount,
  PortalPurchaseResult,
  SubscriptionPlan,
  WalletTransaction,
} from "types/Commerce";
import { formatBytes } from "utils/formatByte";
import { removePortalAuthToken } from "utils/portalAuthStorage";

const QRCode = chakra(QRCodeCanvas);
const LogoutIcon = chakra(ArrowLeftOnRectangleIcon, { baseStyle: { w: 4, h: 4 } });
const MgmaIcon = chakra(FireIcon, { baseStyle: { w: 5, h: 5 } });

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;
const signedMoney = (minor: number): string =>
  `${minor > 0 ? "+" : minor < 0 ? "-" : ""}¥${(
    Math.abs(minor) / 100
  ).toFixed(2)}`;
const countdown = (seconds: number): string =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

export const PortalDashboard = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const [me, setMe] = useState<PortalAccount | null>(null);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [transactions, setTransactions] = useState<WalletTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [mgmaLoading, setMgmaLoading] = useState(false);
  const [mgma, setMgma] = useState<(MgmaIssue & { deadline: number }) | null>(null);
  const [remaining, setRemaining] = useState(0);
  const deadlineRef = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profile, visiblePlans, ledger] = await Promise.all([
        portalFetch<PortalAccount>("/portal/me"),
        portalFetch<SubscriptionPlan[]>("/portal/plans"),
        portalFetch<WalletTransaction[]>("/portal/wallet/transactions"),
      ]);
      setMe(profile);
      setPlans(visiblePlans);
      setTransactions(ledger);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load().catch(() => navigate("/portal/login"));
  }, [load, navigate]);

  useEffect(() => {
    if (!mgma) return;
    const update = () => {
      const seconds = Math.max(0, Math.ceil((deadlineRef.current - performance.now()) / 1000));
      setRemaining(seconds);
      if (!seconds) setMgma(null);
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [mgma]);

  const buy = async (plan: SubscriptionPlan) => {
    if (!window.confirm(t("portal.purchaseOverwriteWarning"))) return;
    setPurchasing(true);
    try {
      await portalFetch<PortalPurchaseResult>("/portal/purchase", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: { plan_id: plan.id },
      });
      toast({ title: t("portal.purchaseSuccess"), status: "success", position: "top" });
      await load();
    } catch (error: any) {
      const detail = error?.data?.detail || error?.response?._data?.detail;
      toast({
        title: t(detail === "Insufficient wallet balance" ? "portal.insufficientBalance" : "portal.requestFailed"),
        status: "error",
        position: "top",
      });
    } finally {
      setPurchasing(false);
    }
  };

  const issueMgma = async () => {
    setMgmaLoading(true);
    try {
      const grant = await portalFetch<MgmaIssue>("/portal/mgma", { method: "POST" });
      const ttl = Math.max(0, grant.ttl_seconds);
      deadlineRef.current = performance.now() + ttl * 1000;
      setMgma({ ...grant, deadline: deadlineRef.current });
      setRemaining(ttl);
    } catch {
      toast({ title: t("portal.mgmaUnavailable"), status: "error", position: "top" });
    } finally {
      setMgmaLoading(false);
    }
  };

  const revokeMgma = async () => {
    await portalFetch("/portal/mgma", { method: "DELETE" });
    setMgma(null);
    setRemaining(0);
  };

  const logout = () => {
    removePortalAuthToken();
    navigate("/portal/login");
  };

  if (loading || !me) {
    return <VStack minH="100vh" justify="center"><Spinner color="primary.500" /></VStack>;
  }

  const limit = me.usage.data_limit || me.subscription?.data_limit || 0;
  const percent = limit ? Math.min(100, (me.usage.used_traffic / limit) * 100) : 0;
  const currentPlan = me.subscription;

  return (
    <VStack minH="100vh" p={{ base: 4, md: 8 }} spacing="6" align="stretch">
      <HStack justify="space-between" flexWrap="wrap">
        <Box>
          <Heading size="lg">{t("portal.dashboardTitle")}</Heading>
          <Text color="gray.500">{me.username}</Text>
        </Box>
        <HStack>
          <Language />
          <Button variant="outline" size="sm" leftIcon={<LogoutIcon />} onClick={logout}>
            {t("header.logout")}
          </Button>
        </HStack>
      </HStack>

      <SimpleGrid columns={{ base: 1, md: 3 }} spacing="4">
        <Card><CardBody><Stat><StatLabel>{t("portal.walletBalance")}</StatLabel><StatNumber>{money(me.wallet_balance_minor)}</StatNumber></Stat></CardBody></Card>
        <Card><CardBody><Stat><StatLabel>{t("portal.currentPlan")}</StatLabel><StatNumber fontSize="xl">{currentPlan?.plan_name || t("portal.noPlan")}</StatNumber>{currentPlan && <Text fontSize="sm" color="gray.500">{t("portal.expiresAt")}: {dayjs(currentPlan.expires_at).format("YYYY-MM-DD HH:mm")}</Text>}</Stat></CardBody></Card>
        <Card><CardBody><Stat><StatLabel>{t("portal.accountStatus")}</StatLabel><StatNumber fontSize="xl">{me.usage.status ? t(`status.${me.usage.status}`) : t("portal.notActivated")}</StatNumber></Stat></CardBody></Card>
      </SimpleGrid>

      <SimpleGrid columns={{ base: 1, lg: 2 }} spacing="5">
        <Card>
          <CardHeader pb="2"><Heading size="md">{t("portal.trafficUsage")}</Heading></CardHeader>
          <CardBody>
            <HStack justify="space-between" mb="2"><Text>{formatBytes(me.usage.used_traffic)}</Text><Text color="gray.500">{limit ? formatBytes(limit) : t("portal.unlimited")}</Text></HStack>
            <Progress value={percent} colorScheme={percent >= 90 ? "red" : "primary"} rounded="full" />
            <Text mt="3" fontSize="sm" color="gray.500">{t("portal.lifetimeUsage")}: {formatBytes(me.usage.lifetime_used_traffic)}</Text>
          </CardBody>
        </Card>

        <Card>
          <CardHeader pb="2"><Heading size="md">{t("portal.subscriptionLink")}</Heading></CardHeader>
          <CardBody>
            <Alert status="warning" rounded="md" mb="4"><AlertIcon /><AlertDescription>{t("mgma.securityNotice")}</AlertDescription></Alert>
            {!mgma ? (
              <Button leftIcon={<MgmaIcon />} colorScheme="orange" onClick={issueMgma} isLoading={mgmaLoading} isDisabled={!me.user_id}>
                {t("portal.getMgma")}
              </Button>
            ) : (
              <VStack align="stretch" spacing="3">
                <HStack justify="space-between"><Badge colorScheme="orange">{t("mgma.expiresIn", { time: countdown(remaining) })}</Badge><Button size="xs" variant="ghost" colorScheme="red" onClick={revokeMgma}>{t("mgma.revoke")}</Button></HStack>
                <Input readOnly value={mgma.url} fontSize="xs" fontFamily="mono" />
                <HStack justify="center"><Box bg="white" p="2" rounded="md"><QRCode value={mgma.url} size={180} /></Box></HStack>
                <CopyToClipboard text={mgma.url}><Button size="sm">{t("mgma.copy")}</Button></CopyToClipboard>
              </VStack>
            )}
          </CardBody>
        </Card>
      </SimpleGrid>

      <Card>
        <CardHeader pb="2"><Heading size="md">{t("portal.purchasePlan")}</Heading></CardHeader>
        <CardBody>
          {!plans.length ? (
            <Text color="gray.500">{t("portal.noAuthorizedPlan")}</Text>
          ) : plans.map((plan) => (
            <SimpleGrid key={plan.id} columns={{ base: 1, md: 3 }} alignItems="center" gap="4">
              <Box><Heading size="sm">{plan.name}</Heading><Text color="gray.500" fontSize="sm">{plan.description}</Text></Box>
              <Box><Text fontWeight="bold" fontSize="xl">{money(plan.price_minor)}</Text><Text fontSize="sm" color="gray.500">{plan.duration_days} {t("portal.days")} · {plan.data_limit ? formatBytes(plan.data_limit) : t("portal.unlimited")}</Text></Box>
              <Button colorScheme="primary" justifySelf={{ md: "end" }} onClick={() => buy(plan)} isLoading={purchasing}>{t("portal.buyNow")}</Button>
            </SimpleGrid>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader pb="2"><Heading size="md">{t("portal.walletHistory")}</Heading></CardHeader>
        <CardBody pt="0">
          {!transactions.length ? <Text color="gray.500">{t("portal.noTransactions")}</Text> : (
            <TableContainer><Table size="sm"><Thead><Tr><Th>{t("portal.time")}</Th><Th>{t("portal.type")}</Th><Th isNumeric>{t("portal.amount")}</Th><Th isNumeric>{t("portal.balanceAfter")}</Th></Tr></Thead><Tbody>
              {transactions.map((item) => <Tr key={item.id}><Td>{dayjs(item.created_at).format("YYYY-MM-DD HH:mm")}</Td><Td>{t(`portal.transaction.${item.kind}`)}</Td><Td isNumeric color={item.amount_minor > 0 ? "green.500" : "red.500"}>{signedMoney(item.amount_minor)}</Td><Td isNumeric>{money(item.balance_after_minor)}</Td></Tr>)}
            </Tbody></Table></TableContainer>
          )}
        </CardBody>
      </Card>

      <HStack justify="center"><Link as={RouterLink} to="/login" fontSize="sm" color="gray.500">{t("portal.adminLogin")}</Link></HStack>
      <Footer />
    </VStack>
  );
};
