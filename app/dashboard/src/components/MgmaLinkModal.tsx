import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  chakra,
  HStack,
  Input,
  InputGroup,
  InputRightElement,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  Tooltip,
  useToast,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowPathIcon,
  CheckIcon,
  ClipboardIcon,
  FireIcon,
  NoSymbolIcon,
} from "@heroicons/react/24/outline";
import { useMgma } from "contexts/MgmaContext";
import { QRCodeCanvas } from "qrcode.react";
import { FC, useEffect, useMemo, useRef, useState } from "react";
import CopyToClipboard from "react-copy-to-clipboard";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

const QRCode = chakra(QRCodeCanvas);
const MgmaIcon = chakra(FireIcon, { baseStyle: { w: 5, h: 5 } });
const CopyIcon = chakra(ClipboardIcon, { baseStyle: { w: 4, h: 4 } });
const CopiedIcon = chakra(CheckIcon, { baseStyle: { w: 4, h: 4 } });
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
    isExpired,
    error,
    regenerate,
    revoke,
    expire,
    close,
  } = useMgma();
  const { t } = useTranslation();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const deadlineRef = useRef<number | null>(null);

  useEffect(() => {
    setCopied(false);
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

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

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

  return (
    <Modal isOpen={isOpen} onClose={close} size="lg" isCentered>
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
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
        <ModalCloseButton mt={3} />

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

              <InputGroup>
                <Input
                  value={grant.url}
                  readOnly
                  fontFamily="mono"
                  fontSize="xs"
                  pr="2.75rem"
                  autoComplete="off"
                  spellCheck={false}
                />
                <InputRightElement>
                  <CopyToClipboard
                    text={grant.url}
                    onCopy={() => setCopied(true)}
                  >
                    <Tooltip
                      label={t(copied ? "usersTable.copied" : "mgma.copy")}
                    >
                      <Button
                        aria-label={String(t("mgma.copy"))}
                        variant="ghost"
                        size="sm"
                        minW="auto"
                        px={2}
                      >
                        {copied ? <CopiedIcon /> : <CopyIcon />}
                      </Button>
                    </Tooltip>
                  </CopyToClipboard>
                </InputRightElement>
              </InputGroup>

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

        <ModalFooter gap={3}>
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
            isLoading={isLoading}
            isDisabled={isRevoking}
            onClick={() => regenerate()}
          >
            {t(grant ? "mgma.regenerate" : "mgma.generateAgain")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
