import {
  Alert,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  chakra,
  Grid,
  Heading,
  HStack,
  Text,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { FireIcon } from "@heroicons/react/24/outline";
import { LiquidSurface } from "components/LiquidSurface";
import { SubscriptionLinkField } from "components/SubscriptionLinkField";
import { QRCodeCanvas } from "qrcode.react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { portalFetch } from "service/http";
import { MgmaIssue } from "types/Commerce";
import { usePortalContext } from "./PortalLayout";

const QRCode = chakra(QRCodeCanvas);
const MgmaIcon = chakra(FireIcon, { baseStyle: { w: 5, h: 5 } });
const countdown = (seconds: number): string =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60
  ).padStart(2, "0")}`;

export const PortalAccess = () => {
  const { me } = usePortalContext();
  const { t } = useTranslation();
  const toast = useToast();
  const [mgmaLoading, setMgmaLoading] = useState(false);
  const [subscriptionLoading, setSubscriptionLoading] = useState(false);
  const [revokeLoading, setRevokeLoading] = useState(false);
  const [mgma, setMgma] = useState<(MgmaIssue & { deadline: number }) | null>(
    null
  );
  const [remaining, setRemaining] = useState(0);
  const deadlineRef = useRef(0);
  const requestSequenceRef = useRef(0);
  const cancelRegenerateRef = useRef<HTMLButtonElement>(null);
  const regenerateDialog = useDisclosure();
  const canIssueMgma = Boolean(
    me.user_id && ["active", "on_hold"].includes(me.usage.status || "")
  );

  useEffect(() => {
    if (!mgma) return;
    const update = () => {
      const seconds = Math.max(
        0,
        Math.ceil((deadlineRef.current - performance.now()) / 1000)
      );
      setRemaining(seconds);
      if (!seconds) setMgma(null);
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [mgma]);

  const applyGrant = (grant: MgmaIssue, clientRequestedAt: number) => {
    const issuedAt = Date.parse(grant.issued_at);
    const expiresAt = Date.parse(grant.expires_at);
    const timestampTtl = (expiresAt - issuedAt) / 1000;
    const ttl = Number.isFinite(timestampTtl)
      ? Math.max(0, Math.min(grant.ttl_seconds, timestampTtl))
      : Math.max(0, grant.ttl_seconds);
    deadlineRef.current = clientRequestedAt + ttl * 1000;
    if (deadlineRef.current <= performance.now()) {
      setMgma(null);
      setRemaining(0);
      return false;
    }
    setMgma({ ...grant, deadline: deadlineRef.current });
    setRemaining(
      Math.max(0, Math.ceil((deadlineRef.current - performance.now()) / 1000))
    );
    return true;
  };

  const requestMgma = async (path: string) => {
    const sequence = ++requestSequenceRef.current;
    const clientRequestedAt = performance.now();
    const grant = await portalFetch<MgmaIssue>(path, { method: "POST" });
    if (sequence !== requestSequenceRef.current) return null;
    return applyGrant(grant, clientRequestedAt);
  };

  const issueMgma = async () => {
    setMgmaLoading(true);
    try {
      const applied = await requestMgma("/portal/mgma");
      if (applied === null) return;
      if (!applied) {
        throw new Error("MGMA authorization expired before it was displayed");
      }
    } catch {
      toast({
        title: t("portal.mgmaUnavailable"),
        status: "error",
        position: "top",
      });
    } finally {
      setMgmaLoading(false);
    }
  };

  const regenerateSubscription = async () => {
    setSubscriptionLoading(true);
    try {
      const applied = await requestMgma("/portal/subscription/regenerate");
      if (applied === null) return;
      if (!applied) {
        throw new Error("MGMA authorization expired before it was displayed");
      }
      regenerateDialog.onClose();
      toast({
        title: t("mgma.subscriptionRegenerated"),
        status: "success",
        position: "top",
      });
    } catch {
      toast({
        title: t("mgma.subscriptionRegenerateError"),
        status: "error",
        position: "top",
      });
    } finally {
      setSubscriptionLoading(false);
    }
  };

  const revokeMgma = async () => {
    const sequence = ++requestSequenceRef.current;
    setRevokeLoading(true);
    try {
      await portalFetch("/portal/mgma", { method: "DELETE" });
      if (sequence !== requestSequenceRef.current) return;
      setMgma(null);
      setRemaining(0);
    } catch {
      if (sequence === requestSequenceRef.current) {
        setMgma(null);
        setRemaining(0);
        toast({
          title: t("portal.requestFailed"),
          status: "error",
          position: "top",
        });
      }
    } finally {
      setRevokeLoading(false);
    }
  };

  return (
    <>
      <VStack align="stretch" spacing="6">
        <Box>
          <Heading size="lg" letterSpacing="-.035em">
            {t("portal.accessTitle")}
          </Heading>
          <Text mt="2" color="fg.muted">
            {t("portal.accessSubtitle")}
          </Text>
        </Box>
        <Grid
          templateColumns={{
            base: "1fr",
            xl: "minmax(0, 1.4fr) minmax(300px, .6fr)",
          }}
          gap="5"
          alignItems="start"
        >
          <LiquidSurface as={Card} rounded="3xl" w="full">
            <CardBody p={{ base: 6, md: 8 }}>
              <Alert status="warning" rounded="2xl" mb="6" alignItems="start">
                <AlertIcon mt="1" />
                <Box>
                  <Text fontWeight="700">
                    {t("portal.temporaryLinkNotice")}
                  </Text>
                  <AlertDescription>
                    {t("mgma.securityNotice")}
                  </AlertDescription>
                </Box>
              </Alert>
              {!mgma ? (
                <VStack py={{ base: 8, md: 12 }} spacing="5">
                  <Box layerStyle="glassSubtle" rounded="full" p="5">
                    <MgmaIcon w="9" h="9" color="orange.400" />
                  </Box>
                  <Box textAlign="center">
                    <Heading size="md">
                      {t("portal.createTemporaryLink")}
                    </Heading>
                    <Text mt="2" color="fg.muted" maxW="520px">
                      {t("portal.temporaryLinkHelp")}
                    </Text>
                  </Box>
                  <HStack flexWrap="wrap" justify="center">
                    <Button
                      leftIcon={<MgmaIcon />}
                      colorScheme="orange"
                      size="lg"
                      onClick={() => void issueMgma()}
                      isLoading={mgmaLoading}
                      isDisabled={!canIssueMgma || subscriptionLoading}
                    >
                      {t("mgma.authorize")}
                    </Button>
                    <Button
                      variant="outline"
                      colorScheme="orange"
                      size="lg"
                      onClick={regenerateDialog.onOpen}
                      isLoading={subscriptionLoading}
                      isDisabled={!canIssueMgma || mgmaLoading}
                    >
                      {t("mgma.regenerateSubscription")}
                    </Button>
                  </HStack>
                </VStack>
              ) : (
                <Grid
                  templateColumns={{ base: "1fr", md: "minmax(0, 1fr) auto" }}
                  gap="6"
                  alignItems="center"
                >
                  <VStack align="stretch" spacing="4">
                    <HStack justify="space-between">
                      <Badge colorScheme="orange" rounded="full" px="3" py="1">
                        {t("mgma.expiresIn", { time: countdown(remaining) })}
                      </Badge>
                      <Button
                        size="sm"
                        variant="ghost"
                        colorScheme="red"
                        onClick={() => void revokeMgma()}
                        isLoading={revokeLoading}
                        isDisabled={mgmaLoading || subscriptionLoading}
                      >
                        {t("mgma.revoke")}
                      </Button>
                    </HStack>
                    <SubscriptionLinkField value={mgma.url} />
                    <Text fontSize="xs" color="fg.muted">
                      {t("mgma.stablePathNotice")}
                    </Text>
                    <HStack flexWrap="wrap">
                      <Button
                        colorScheme="primary"
                        onClick={() => void issueMgma()}
                        isLoading={mgmaLoading}
                        isDisabled={subscriptionLoading || revokeLoading}
                      >
                        {t("mgma.refreshAuthorization")}
                      </Button>
                      <Button
                        variant="outline"
                        colorScheme="orange"
                        onClick={regenerateDialog.onOpen}
                        isLoading={subscriptionLoading}
                        isDisabled={mgmaLoading || revokeLoading}
                      >
                        {t("mgma.regenerateSubscription")}
                      </Button>
                    </HStack>
                  </VStack>
                  <Box
                    bg="white"
                    p="3"
                    rounded="2xl"
                    justifySelf="center"
                    boxShadow="0 14px 35px rgba(15, 23, 42, .12)"
                  >
                    <QRCode value={mgma.url} size={190} />
                  </Box>
                </Grid>
              )}
            </CardBody>
          </LiquidSurface>
          <LiquidSurface as={Card} rounded="3xl" w="full">
            <CardBody p="6">
              <Text color="fg.subtle" fontSize="sm">
                {t("portal.accessBoundTo", { username: me.username })}
              </Text>
              <Heading mt="2" size="md">
                {me.subscription?.plan_name || t("portal.noPlan")}
              </Heading>
              <Text mt="4" color="fg.muted" fontSize="sm">
                {t("portal.accessPlanHelp")}
              </Text>
            </CardBody>
          </LiquidSurface>
        </Grid>
      </VStack>
      <AlertDialog
        isOpen={regenerateDialog.isOpen}
        leastDestructiveRef={cancelRegenerateRef}
        onClose={regenerateDialog.onClose}
        isCentered
      >
        <AlertDialogOverlay bg="blackAlpha.400" backdropFilter="blur(16px)">
          <AlertDialogContent mx="3">
            <AlertDialogHeader>
              {t("mgma.regenerateSubscriptionTitle")}
            </AlertDialogHeader>
            <AlertDialogBody>
              {t("mgma.regenerateSubscriptionPrompt")}
            </AlertDialogBody>
            <AlertDialogFooter gap="3">
              <Button
                ref={cancelRegenerateRef}
                onClick={regenerateDialog.onClose}
                isDisabled={subscriptionLoading}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="orange"
                onClick={() => void regenerateSubscription()}
                isLoading={subscriptionLoading}
                isDisabled={revokeLoading}
              >
                {t("mgma.regenerateSubscription")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  );
};
