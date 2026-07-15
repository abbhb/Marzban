import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  chakra,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  NumberInput,
  NumberInputField,
  Select,
  Spinner,
  Switch,
  Text,
  Textarea,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { ShieldCheckIcon } from "@heroicons/react/24/outline";
import { useSubscriptionSecurity } from "contexts/SubscriptionSecurityContext";
import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  SubscriptionSecuritySettingsUpdate,
  SubscriptionSourceMode,
} from "types/Mgma";
import { Icon } from "./Icon";

const SecurityIcon = chakra(ShieldCheckIcon, {
  baseStyle: { w: 5, h: 5 },
});

const parseCidrs = (value: string): string[] =>
  value
    .split(/[\s,]+/)
    .map((cidr) => cidr.trim())
    .filter(Boolean);

export const SubscriptionSecurityModal: FC = () => {
  const { isOpen, isLoading, isSaving, settings, close, load, save } =
    useSubscriptionSecurity();
  const { t } = useTranslation();
  const toast = useToast();
  const [form, setForm] = useState<SubscriptionSecuritySettingsUpdate>({
    mode: "legacy",
    ttl_seconds: 180,
    single_use: false,
    source_mode: "any",
    custom_cidrs: [],
  });
  const [cidrText, setCidrText] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setValidationError(null);
    load().catch(() => {
      toast({
        title: t("subscriptionSecurity.loadError"),
        status: "error",
        isClosable: true,
        position: "top",
        duration: 3000,
      });
    });
  }, [isOpen, load, t, toast]);

  useEffect(() => {
    if (!settings) return;
    setForm({
      mode: settings.mode,
      ttl_seconds: settings.ttl_seconds,
      single_use: settings.single_use,
      source_mode: settings.source_mode,
      custom_cidrs: settings.custom_cidrs,
    });
    setCidrText(settings.custom_cidrs.join("\n"));
  }, [settings]);

  const needsCustomCidrs = useMemo(
    () =>
      form.source_mode === "custom" || form.source_mode === "china_or_custom",
    [form.source_mode]
  );

  const handleSave = async () => {
    const customCidrs = parseCidrs(cidrText);
    if (form.ttl_seconds < 30 || form.ttl_seconds > 900) {
      setValidationError("subscriptionSecurity.ttlError");
      return;
    }
    if (form.source_mode === "custom" && customCidrs.length === 0) {
      setValidationError("subscriptionSecurity.cidrRequired");
      return;
    }

    setValidationError(null);
    try {
      await save({ ...form, custom_cidrs: customCidrs });
      toast({
        title: t("subscriptionSecurity.saved"),
        status: "success",
        isClosable: true,
        position: "top",
        duration: 3000,
      });
      close();
    } catch (error) {
      toast({
        title: t("subscriptionSecurity.saveError"),
        status: "error",
        isClosable: true,
        position: "top",
        duration: 3000,
      });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={close} size="lg" isCentered>
      <ModalOverlay
        bg="blackAlpha.300"
        backdropFilter="var(--marzban-overlay-filter)"
      />
      <ModalContent mx="3">
        <ModalHeader pt={6}>
          <HStack gap={3}>
            <Icon color="primary">
              <SecurityIcon color="white" />
            </Icon>
            <Text fontWeight="semibold" fontSize="lg">
              {t("subscriptionSecurity.title")}
            </Text>
          </HStack>
        </ModalHeader>
        <ModalCloseButton />

        <ModalBody>
          {isLoading && !settings ? (
            <VStack py={10}>
              <Spinner color="primary.500" />
            </VStack>
          ) : (
            <VStack align="stretch" spacing={5}>
              {settings && !settings.pepper_configured && (
                <Alert status="error" borderRadius="md" fontSize="sm">
                  <AlertIcon />
                  <AlertDescription>
                    {t("subscriptionSecurity.pepperMissing")}
                  </AlertDescription>
                </Alert>
              )}

              <FormControl>
                <FormLabel>{t("subscriptionSecurity.mode")}</FormLabel>
                <Select
                  value={form.mode}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      mode: event.target
                        .value as SubscriptionSecuritySettingsUpdate["mode"],
                    })
                  }
                >
                  <option value="legacy">
                    {t("subscriptionSecurity.modeLegacy")}
                  </option>
                  <option value="dual">
                    {t("subscriptionSecurity.modeDual")}
                  </option>
                  <option value="ephemeral">
                    {t("subscriptionSecurity.modeEphemeral")}
                  </option>
                </Select>
                <FormHelperText>
                  {t(`subscriptionSecurity.modeHelp.${form.mode}`)}
                </FormHelperText>
              </FormControl>

              <FormControl
                isInvalid={validationError === "subscriptionSecurity.ttlError"}
              >
                <FormLabel>{t("subscriptionSecurity.ttl")}</FormLabel>
                <NumberInput
                  min={30}
                  max={900}
                  value={form.ttl_seconds}
                  onChange={(_, value) =>
                    setForm({
                      ...form,
                      ttl_seconds: Number.isFinite(value) ? value : 180,
                    })
                  }
                >
                  <NumberInputField />
                </NumberInput>
                <FormHelperText>
                  {t("subscriptionSecurity.ttlHelp")}
                </FormHelperText>
              </FormControl>

              <FormControl>
                <HStack justify="space-between" align="start">
                  <Box>
                    <FormLabel mb={1}>
                      {t("subscriptionSecurity.singleUse")}
                    </FormLabel>
                    <FormHelperText mt={0}>
                      {t("subscriptionSecurity.singleUseHelp")}
                    </FormHelperText>
                  </Box>
                  <Switch
                    colorScheme="primary"
                    isChecked={form.single_use}
                    onChange={(event) =>
                      setForm({ ...form, single_use: event.target.checked })
                    }
                  />
                </HStack>
                {form.single_use && (
                  <Alert
                    status="warning"
                    borderRadius="md"
                    mt={3}
                    fontSize="sm"
                  >
                    <AlertIcon />
                    <AlertDescription>
                      {t("subscriptionSecurity.singleUseWarning")}
                    </AlertDescription>
                  </Alert>
                )}
              </FormControl>

              <FormControl>
                <FormLabel>{t("subscriptionSecurity.sourceMode")}</FormLabel>
                <Select
                  value={form.source_mode}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      source_mode: event.target.value as SubscriptionSourceMode,
                    })
                  }
                >
                  <option value="any">
                    {t("subscriptionSecurity.sourceAny")}
                  </option>
                  <option value="china">
                    {t("subscriptionSecurity.sourceChina")}
                  </option>
                  <option value="custom">
                    {t("subscriptionSecurity.sourceCustom")}
                  </option>
                  <option value="china_or_custom">
                    {t("subscriptionSecurity.sourceChinaOrCustom")}
                  </option>
                </Select>
              </FormControl>

              {needsCustomCidrs && (
                <FormControl
                  isInvalid={
                    validationError === "subscriptionSecurity.cidrRequired"
                  }
                >
                  <FormLabel>{t("subscriptionSecurity.customCidrs")}</FormLabel>
                  <Textarea
                    minH="120px"
                    fontFamily="mono"
                    fontSize="sm"
                    value={cidrText}
                    onChange={(event) => setCidrText(event.target.value)}
                    placeholder={String(
                      t("subscriptionSecurity.customCidrsPlaceholder")
                    )}
                    spellCheck={false}
                  />
                  <FormHelperText>
                    {t("subscriptionSecurity.customCidrsHelp")}
                  </FormHelperText>
                </FormControl>
              )}

              {settings && (
                <HStack
                  layerStyle="glassSubtle"
                  borderRadius="md"
                  p={3}
                  justify="space-between"
                  fontSize="sm"
                >
                  <Text>{t("subscriptionSecurity.cnDataset")}</Text>
                  <HStack>
                    <Badge>{settings.cn_cidr_version || "-"}</Badge>
                    <Badge colorScheme="blue">
                      {t("subscriptionSecurity.cnDatasetCount", {
                        count: settings.cn_cidr_count,
                      })}
                    </Badge>
                  </HStack>
                </HStack>
              )}

              {validationError && (
                <Alert status="error" borderRadius="md" fontSize="sm">
                  <AlertIcon />
                  <AlertDescription>{t(validationError)}</AlertDescription>
                </Alert>
              )}
            </VStack>
          )}
        </ModalBody>

        <ModalFooter>
          <Button size="sm" variant="outline" mr={3} onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            colorScheme="primary"
            isLoading={isSaving}
            isDisabled={isLoading || !settings}
            onClick={handleSave}
          >
            {t("subscriptionSecurity.save")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
