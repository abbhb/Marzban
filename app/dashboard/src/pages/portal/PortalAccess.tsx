import {
  Alert,
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
  Input,
  Text,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { FireIcon } from "@heroicons/react/24/outline";
import { LiquidSurface } from "components/LiquidSurface";
import { QRCodeCanvas } from "qrcode.react";
import { useEffect, useRef, useState } from "react";
import CopyToClipboard from "react-copy-to-clipboard";
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
  const [mgma, setMgma] = useState<(MgmaIssue & { deadline: number }) | null>(
    null
  );
  const [remaining, setRemaining] = useState(0);
  const deadlineRef = useRef(0);
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

  const issueMgma = async () => {
    setMgmaLoading(true);
    try {
      const grant = await portalFetch<MgmaIssue>("/portal/mgma", {
        method: "POST",
      });
      const ttl = Math.max(0, grant.ttl_seconds);
      deadlineRef.current = performance.now() + ttl * 1000;
      setMgma({ ...grant, deadline: deadlineRef.current });
      setRemaining(ttl);
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

  const revokeMgma = async () => {
    try {
      await portalFetch("/portal/mgma", { method: "DELETE" });
      setMgma(null);
      setRemaining(0);
    } catch {
      toast({
        title: t("portal.requestFailed"),
        status: "error",
        position: "top",
      });
    }
  };

  return (
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
        <LiquidSurface
          as={Card}
          interactive
          lift={false}
          rounded="3xl"
          w="full"
        >
          <CardBody p={{ base: 6, md: 8 }}>
            <Alert status="warning" rounded="2xl" mb="6" alignItems="start">
              <AlertIcon mt="1" />
              <Box>
                <Text fontWeight="700">{t("portal.temporaryLinkNotice")}</Text>
                <AlertDescription>{t("mgma.securityNotice")}</AlertDescription>
              </Box>
            </Alert>
            {!mgma ? (
              <VStack py={{ base: 8, md: 12 }} spacing="5">
                <Box layerStyle="glassSubtle" rounded="full" p="5">
                  <MgmaIcon w="9" h="9" color="orange.400" />
                </Box>
                <Box textAlign="center">
                  <Heading size="md">{t("portal.createTemporaryLink")}</Heading>
                  <Text mt="2" color="fg.muted" maxW="520px">
                    {t("portal.temporaryLinkHelp")}
                  </Text>
                </Box>
                <Button
                  leftIcon={<MgmaIcon />}
                  colorScheme="orange"
                  size="lg"
                  onClick={issueMgma}
                  isLoading={mgmaLoading}
                  isDisabled={!canIssueMgma}
                >
                  {t("portal.getMgma")}
                </Button>
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
                      onClick={revokeMgma}
                    >
                      {t("mgma.revoke")}
                    </Button>
                  </HStack>
                  <Input
                    readOnly
                    value={mgma.url}
                    fontSize="xs"
                    fontFamily="mono"
                    bg="surface.input"
                  />
                  <CopyToClipboard text={mgma.url}>
                    <Button colorScheme="primary">{t("mgma.copy")}</Button>
                  </CopyToClipboard>
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
        <LiquidSurface
          as={Card}
          interactive
          lift={false}
          rounded="3xl"
          w="full"
        >
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
  );
};
