import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  Code,
  HStack,
  Text,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { ClipboardDocumentIcon } from "@heroicons/react/24/outline";
import copyToClipboard from "copy-to-clipboard";
import { useTranslation } from "react-i18next";

type OneTimePasswordPanelProps = {
  username: string;
  password: string;
};

export const OneTimePasswordPanel = ({
  username,
  password,
}: OneTimePasswordPanelProps) => {
  const { t } = useTranslation();
  const toast = useToast();

  const copy = (value: string) => {
    const copied = copyToClipboard(value);
    toast({
      title: t(copied ? "usersTable.copied" : "mgma.copyFailed"),
      status: copied ? "success" : "error",
      position: "top",
      duration: 2200,
    });
  };

  return (
    <VStack align="stretch" spacing="4">
      <Alert status="warning" alignItems="flex-start" rounded="2xl">
        <AlertIcon mt="0.5" />
        <AlertDescription>
          <Text fontWeight="800">{t("userDialog.passwordShownOnce")}</Text>
          <Text mt="1" fontSize="sm">
            {t("userDialog.passwordShownOnceHelp")}
          </Text>
        </AlertDescription>
      </Alert>
      <Box layerStyle="glassSubtle" rounded="2xl" p="4">
        <Text fontSize="xs" fontWeight="700" color="fg.subtle">
          {t("username")}
        </Text>
        <HStack mt="1" justify="space-between">
          <Code fontSize="md" bg="transparent" userSelect="all">
            {username}
          </Code>
          <Button
            size="sm"
            variant="ghost"
            leftIcon={<ClipboardDocumentIcon width="16" />}
            onClick={() => copy(username)}
          >
            {t("mgma.copy")}
          </Button>
        </HStack>
      </Box>
      <Box layerStyle="glassSubtle" rounded="2xl" p="4">
        <Text fontSize="xs" fontWeight="700" color="fg.subtle">
          {t("password")}
        </Text>
        <HStack mt="1" justify="space-between" align="flex-start">
          <Code
            fontSize="md"
            bg="transparent"
            overflowWrap="anywhere"
            userSelect="all"
          >
            {password}
          </Code>
          <Button
            size="sm"
            colorScheme="primary"
            leftIcon={<ClipboardDocumentIcon width="16" />}
            onClick={() => copy(password)}
          >
            {t("mgma.copy")}
          </Button>
        </HStack>
      </Box>
    </VStack>
  );
};
