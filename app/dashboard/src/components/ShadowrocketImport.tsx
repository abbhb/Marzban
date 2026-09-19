import { Box, Button, HStack, Text, VStack } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import { SubscriptionLinkField } from "./SubscriptionLinkField";

export function ShadowrocketImport({ value }: { value: string }) {
  const { t } = useTranslation();
  const url = new URL(value);
  url.pathname = `${url.pathname.replace(/\/$/, "")}/shadowrocket`;
  const subscriptionUrl = url.toString();
  const encodedUrl = encodeURIComponent(subscriptionUrl);

  return (
    <Box borderWidth="1px" borderRadius="xl" p="4" w="full">
      <VStack align="stretch" spacing="3">
        <Text fontWeight="600">{t("shadowrocket.title")}</Text>
        <Text fontSize="sm" color="fg.muted">{t("shadowrocket.help")}</Text>
        <HStack flexWrap="wrap">
          <Button as="a" href={`shadowrocket://config/add/${encodedUrl}`} size="sm" colorScheme="primary">
            {t("shadowrocket.importConfig")}
          </Button>
          <Button as="a" href={`shadowrocket://add/${encodedUrl}`} size="sm" variant="outline">
            {t("shadowrocket.importNodes")}
          </Button>
        </HStack>
        <SubscriptionLinkField value={subscriptionUrl} />
        <Text fontSize="xs" color="fg.muted">{t("shadowrocket.manual")}</Text>
      </VStack>
    </Box>
  );
}
