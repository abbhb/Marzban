import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Divider,
  Grid,
  Heading,
  HStack,
  Icon,
  Spinner,
  Text,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { CheckCircleIcon } from "@heroicons/react/24/outline";
import { BootReady } from "components/BootReady";
import { LiquidSurface } from "components/LiquidSurface";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { portalFetch } from "service/http";
import { PortalPurchaseResult, SubscriptionPlan } from "types/Commerce";
import { formatBytes } from "utils/formatByte";
import { usePortalContext } from "./PortalLayout";

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;

export const PortalPlans = () => {
  const { me, plans, plansError, plansLoading, applyPurchase, loadPlans } =
    usePortalContext();
  const { t } = useTranslation();
  const toast = useToast();
  const dialog = useDisclosure();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [selectedPlan, setSelectedPlan] = useState<SubscriptionPlan | null>(
    null
  );
  const [purchaseAttemptKey, setPurchaseAttemptKey] = useState<string | null>(
    null
  );
  const [purchasingPlanId, setPurchasingPlanId] = useState<number | null>(null);
  const sortedPlans = useMemo(
    () => [...plans].sort((a, b) => a.price_minor - b.price_minor),
    [plans]
  );
  const planGridMaxWidth =
    sortedPlans.length <= 1
      ? "440px"
      : sortedPlans.length === 2
      ? "900px"
      : sortedPlans.length === 3
      ? "1340px"
      : "full";

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  const choosePlan = (plan: SubscriptionPlan) => {
    setSelectedPlan(plan);
    setPurchaseAttemptKey(crypto.randomUUID());
    dialog.onOpen();
  };

  const closeDialog = () => {
    if (purchasingPlanId !== null) return;
    dialog.onClose();
    setSelectedPlan(null);
    setPurchaseAttemptKey(null);
  };

  const buy = async () => {
    if (!selectedPlan || !purchaseAttemptKey) return;
    setPurchasingPlanId(selectedPlan.id);
    try {
      const result = await portalFetch<PortalPurchaseResult>(
        "/portal/purchase",
        {
          method: "POST",
          headers: { "Idempotency-Key": purchaseAttemptKey },
          body: { plan_id: selectedPlan.id },
        }
      );
      applyPurchase(result);
      dialog.onClose();
      setSelectedPlan(null);
      setPurchaseAttemptKey(null);
      toast({
        title: t("portal.purchaseSuccess"),
        status: "success",
        position: "top",
      });
      await loadPlans();
    } catch (error: any) {
      const detail = error?.data?.detail || error?.response?._data?.detail;
      toast({
        title: t(
          detail === "Insufficient wallet balance"
            ? "portal.insufficientBalance"
            : "portal.requestFailed"
        ),
        status: "error",
        position: "top",
      });
    } finally {
      setPurchasingPlanId(null);
    }
  };

  return (
    <VStack align="stretch" spacing="6">
      <Grid
        templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) auto" }}
        gap="4"
        alignItems="center"
      >
        <Box>
          <Heading size="lg" letterSpacing="-.035em">
            {t("portal.storeTitle")}
          </Heading>
          <Text mt="2" color="fg.muted">
            {t("portal.storeSubtitle")}
          </Text>
        </Box>
        <Box layerStyle="glassSubtle" rounded="2xl" px="5" py="3">
          <Text fontSize="xs" color="fg.subtle">
            {t("portal.walletBalance")}
          </Text>
          <Text fontSize="xl" fontWeight="800">
            {money(me.wallet_balance_minor)}
          </Text>
        </Box>
      </Grid>

      <Alert
        status="warning"
        variant="subtle"
        rounded="2xl"
        layerStyle="glassSubtle"
        alignItems="start"
      >
        <AlertIcon mt="1" />
        <Box>
          <Text fontWeight="700">{t("portal.purchaseNoticeTitle")}</Text>
          <AlertDescription>
            {t("portal.purchaseOverwriteWarning")}
          </AlertDescription>
        </Box>
      </Alert>

      {plansError && (
        <Alert status="error" rounded="2xl" alignItems="center">
          <AlertIcon />
          <AlertDescription flex="1">
            {t("portal.dataLoadError")}
          </AlertDescription>
          <Button
            size="sm"
            variant="outline"
            colorScheme="red"
            onClick={loadPlans}
          >
            {t("portal.retry")}
          </Button>
        </Alert>
      )}

      <BootReady ready={!plansLoading} />
      {plansLoading && !sortedPlans.length ? (
        <VStack py="20">
          <Spinner color="primary.500" />
        </VStack>
      ) : plansError && !sortedPlans.length ? null : !sortedPlans.length ? (
        <Card variant="glass">
          <CardBody py="16" textAlign="center">
            <Text color="fg.muted">{t("portal.noAuthorizedPlan")}</Text>
          </CardBody>
        </Card>
      ) : (
        <Grid
          w="full"
          maxW={planGridMaxWidth}
          mx="auto"
          templateColumns={{
            base: "minmax(0, 1fr)",
            md: "repeat(auto-fit, minmax(280px, 1fr))",
          }}
          gap="5"
          alignItems="stretch"
        >
          {sortedPlans.map((plan) => {
            const isCurrent = me.subscription?.plan_id === plan.id;
            return (
              <LiquidSurface
                as={Card}
                key={plan.id}
                rounded="3xl"
                overflow="hidden"
              >
                <Box
                  h="2"
                  bgGradient={
                    isCurrent
                      ? "linear(to-r, primary.400, cyan.300)"
                      : "linear(to-r, primary.200, transparent)"
                  }
                />
                <CardBody
                  p={{ base: 6, md: 7 }}
                  display="flex"
                  flexDirection="column"
                  h="full"
                >
                  <HStack justify="space-between" align="start">
                    <Box>
                      <Heading size="md">{plan.name}</Heading>
                      <Text
                        mt="2"
                        color="fg.muted"
                        fontSize="sm"
                        minH={{ md: "42px" }}
                      >
                        {plan.description || t("portal.planDefaultDescription")}
                      </Text>
                    </Box>
                    {isCurrent && (
                      <Badge colorScheme="blue" rounded="full">
                        {t("portal.currentPlan")}
                      </Badge>
                    )}
                  </HStack>
                  <HStack mt="7" align="baseline" spacing="2">
                    <Text
                      fontSize={{ base: "4xl", md: "5xl" }}
                      lineHeight="1"
                      fontWeight="850"
                      letterSpacing="-.055em"
                    >
                      {money(plan.price_minor)}
                    </Text>
                    <Text color="fg.subtle">
                      / {plan.duration_days} {t("portal.days")}
                    </Text>
                  </HStack>
                  <Button
                    mt="6"
                    w="full"
                    colorScheme="primary"
                    size="lg"
                    onClick={() => choosePlan(plan)}
                    isLoading={purchasingPlanId === plan.id}
                  >
                    {isCurrent ? t("portal.purchaseAgain") : t("portal.buyNow")}
                  </Button>
                  <Divider my="6" borderColor="border.glass" />
                  <VStack align="stretch" spacing="4" flex="1">
                    <HStack align="start">
                      <Icon as={CheckCircleIcon} color="teal.400" mt=".5" />
                      <Text>
                        {t("portal.planTrafficFeature", {
                          amount: plan.data_limit
                            ? formatBytes(plan.data_limit)
                            : t("portal.unlimited"),
                        })}
                      </Text>
                    </HStack>
                    <HStack align="start">
                      <Icon as={CheckCircleIcon} color="teal.400" mt=".5" />
                      <Text>
                        {t("portal.planDurationFeature", {
                          days: plan.duration_days,
                        })}
                      </Text>
                    </HStack>
                    <HStack align="start">
                      <Icon as={CheckCircleIcon} color="teal.400" mt=".5" />
                      <Text>{t("portal.planActivationFeature")}</Text>
                    </HStack>
                  </VStack>
                </CardBody>
              </LiquidSurface>
            );
          })}
        </Grid>
      )}

      <AlertDialog
        isOpen={dialog.isOpen}
        leastDestructiveRef={cancelRef}
        onClose={closeDialog}
        isCentered
        closeOnEsc={purchasingPlanId === null}
        closeOnOverlayClick={purchasingPlanId === null}
      >
        <AlertDialogOverlay backdropFilter="var(--marzban-overlay-filter)">
          <AlertDialogContent layerStyle="glass" rounded="3xl" mx="4">
            <AlertDialogHeader>
              {t("portal.confirmPurchaseTitle")}
            </AlertDialogHeader>
            <AlertDialogBody>
              <Text>
                {t("portal.confirmPurchaseDescription", {
                  plan: selectedPlan?.name,
                  price: selectedPlan ? money(selectedPlan.price_minor) : "",
                })}
              </Text>
              <Alert mt="4" status="warning" rounded="xl">
                <AlertIcon />
                <AlertDescription>
                  {t("portal.purchaseOverwriteWarning")}
                </AlertDescription>
              </Alert>
            </AlertDialogBody>
            <AlertDialogFooter gap="3">
              <Button
                ref={cancelRef}
                variant="ghost"
                onClick={closeDialog}
                isDisabled={purchasingPlanId !== null}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="primary"
                onClick={buy}
                isLoading={purchasingPlanId !== null}
              >
                {t("portal.confirmPurchase")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </VStack>
  );
};
