import { Button, Heading, HStack, Text, VStack } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export const AdminError = () => {
  const { t } = useTranslation();
  return (
    <VStack
      as="main"
      minH="100vh"
      justify="center"
      spacing="4"
      px="6"
      textAlign="center"
    >
      <Heading as="h1" size="lg">
        {t("startup.loadErrorTitle")}
      </Heading>
      <Text color="fg.muted">{t("startup.loadErrorDescription")}</Text>
      <HStack spacing="3">
        <Button colorScheme="primary" onClick={() => window.location.reload()}>
          {t("portal.retry")}
        </Button>
        <Button as={Link} to="/login" variant="ghost">
          {t("portal.backToLogin")}
        </Button>
      </HStack>
    </VStack>
  );
};
