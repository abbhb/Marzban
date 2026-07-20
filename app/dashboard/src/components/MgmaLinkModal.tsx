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
  chakra,
  HStack,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowPathIcon,
  FireIcon,
  NoSymbolIcon,
} from "@heroicons/react/24/outline";
import { useMgma } from "contexts/MgmaContext";
import { QRCodeCanvas } from "qrcode.react";
import { FC, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";
import { SubscriptionLinkField } from "./SubscriptionLinkField";

const QRCode = chakra(QRCodeCanvas);
const MgmaIcon = chakra(FireIcon, { baseStyle: { w: 5, h: 5 } });
const RegenerateIcon = chakra(ArrowPathIcon, {
  baseStyle: { w: 4, h: 4 },
});
const RevokeIcon = chakra(NoSymbolIcon, { baseStyle: { w: 4, h: 4 } });

const formatCountdown = (seconds: number): string => {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(
    2,
    "0"
  )}`;
};

export const MgmaLinkModal: FC = () => {
  const {
    user,
    grant,
    isOpen,
    isLoading,
    isRevoking,
    isRegeneratingSubscription,
    isExpired,
    error,
    regenerate,
    regenerateSubscription,
    revoke,
    expire,
    close,
  } = useMgma();
  const { t } = useTranslation();
  const toast = useToast();
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const deadlineRef = useRef<number | null>(null);
  const cancelRegenerateRef = useRef<HTMLButtonElement>(null);
  const regenerateDialog = useDisclosure();

  useEffect(() => {
    if (!grant) {
      deadlineRef.current = null;
      setRemainingSeconds(0);
      return;
    }

    const issuedAt = Date.parse(grant.issued_at);
    const expiresAt = Date.parse(grant.expires_at);
    const timestampTtl = (expiresAt - issuedAt) / 1000;
    const ttl = Number.isFinite(timestampTtl)
      ? Math.max(0, Math.min(grant.ttl_seconds, timestampTtl))
      : Math.max(0, grant.ttl_seconds);
    // The countdown uses a monotonic relative deadline, so a skewed or changed
    // client wall clock cannot make the secret persist in UI past its TTL.
    deadlineRef.current =
      (grant.client_requested_at_ms || performance.now()) + ttl * 1000;

    const update = () => {
      const remaining = Math.max(
        0,
        Math.ceil(((deadlineRef.current || 0) - performance.now()) / 1000)
      );
      setRemainingSeconds(remaining);
      if (remaining === 0) expire(grant.url);
    };

    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [grant, expire]);

  const expiryText = useMemo(
    () => formatCountdown(remainingSeconds),
    [remainingSeconds]
  );

  const handleRevoke = async () => {
    try {
      await revoke();
      toast({
        title: t("mgma.revoked"),
        status: "success",
        isClosable: true,
        position: "top",
        duration: 3000,
      });
    } catch (error) {
      // The store exposes a localized error state in the modal.
    }
  };

  const handleRegenerateSubscription = async () => {
    try {
      await regenerateSubscription();
      regenerateDialog.onClose();
      toast({
        title: t("mgma.subscriptionRegenerated"),
        status: "success",
        isClosable: true,
        position: "top",
        duration: 3500,
      });
    } catch {
      toast({
        title: t("mgma.subscriptionRegenerateError"),
        status: "error",
        isClosable: true,
        position: "top",
        duration: 3500,
      });
    }
  };

  return (
    <>
      <Modal isOpen={isOpen} onClose={close} size="lg" isCentered>
        <ModalOverlay
          bg="blackAlpha.300"
          backdropFilter="var(--marzban-overlay-filter)"
        />
        <ModalContent mx="3">
          <ModalHeader pt={6}>
            <HStack gap={3}>
              <Icon color="orange">
                <MgmaIcon color="white" />
              </Icon>
              <Box>
                <Text fontWeight="semibold" fontSize="lg">
                  {t("mgma.title")}
                </Text>
                {user && (
                  <Text fontSize="sm" color="gray.500" fontWeight="normal">
                    {user.username}
                  </Text>
                )}
              </Box>
            </HStack>
          </ModalHeader>
          <ModalCloseButton />

          <ModalBody>
            <Alert status="warning" borderRadius="md" mb={4} fontSize="sm">
              <AlertIcon />
              <AlertDescription>{t("mgma.securityNotice")}</AlertDescription>
            </Alert>

            {isLoading && (
              <VStack py={10} spacing={3}>
                <Spinner color="primary.500" />
                <Text fontSize="sm" color="gray.500">
                  {t("mgma.generating")}
                </Text>
              </VStack>
            )}

            {!isLoading && error && (
              <Alert status="error" borderRadius="md">
                <AlertIcon />
                <AlertDescription>{t(error)}</AlertDescription>
              </Alert>
            )}

            {!isLoading && grant && (
              <VStack align="stretch" spacing={4}>
                <HStack justify="space-between">
                  <Text fontSize="sm" fontWeight="medium">
                    {t("mgma.temporaryLink")}
                  </Text>
                  <Badge
                    colorScheme={remainingSeconds <= 30 ? "red" : "orange"}
                    fontFamily="mono"
                    fontSize="sm"
                    px={2}
                    py={1}
                  >
                    {t("mgma.expiresIn", { time: expiryText })}
                  </Badge>
                </HStack>

                <SubscriptionLinkField value={grant.url} />
                <Text fontSize="xs" color="gray.500">
                  {t("mgma.stablePathNotice")}
                </Text>

                <Box alignSelf="center" bg="white" borderRadius="md" p={2}>
                  <QRCode
                    size={220}
                    level="L"
                    includeMargin={false}
                    value={grant.url}
                    bg="white"
                  />
                </Box>
                <Text fontSize="xs" color="gray.500" textAlign="center">
                  {t("mgma.qrNotice")}
                </Text>
              </VStack>
            )}

            {!isLoading && !grant && isExpired && !error && (
              <Alert status="info" borderRadius="md">
                <AlertIcon />
                <AlertDescription>{t("mgma.expired")}</AlertDescription>
              </Alert>
            )}

            {!isLoading && !grant && !isExpired && !error && (
              <Alert status="info" borderRadius="md">
                <AlertIcon />
                <AlertDescription>{t("mgma.noActiveLink")}</AlertDescription>
              </Alert>
            )}
          </ModalBody>

          <ModalFooter gap={3} flexWrap="wrap">
            <Button
              size="sm"
              variant="outline"
              colorScheme="red"
              leftIcon={<RevokeIcon />}
              isLoading={isRevoking}
              isDisabled={!grant || isLoading}
              onClick={handleRevoke}
            >
              {t("mgma.revoke")}
            </Button>
            <Button
              size="sm"
              colorScheme="primary"
              leftIcon={<RegenerateIcon />}
              isLoading={isLoading && !isRegeneratingSubscription}
              isDisabled={isRevoking || isRegeneratingSubscription}
              onClick={() => void regenerate()}
            >
              {t(grant ? "mgma.refreshAuthorization" : "mgma.authorize")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              colorScheme="orange"
              leftIcon={<RegenerateIcon />}
              isLoading={isRegeneratingSubscription}
              isDisabled={
                isRevoking || (isLoading && !isRegeneratingSubscription)
              }
              onClick={regenerateDialog.onOpen}
            >
              {t("mgma.regenerateSubscription")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
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
                isDisabled={isRegeneratingSubscription}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="orange"
                onClick={() => void handleRegenerateSubscription()}
                isLoading={isRegeneratingSubscription}
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
