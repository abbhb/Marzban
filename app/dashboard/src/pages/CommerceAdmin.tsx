import { Box, Heading, Tab, TabList, TabPanel, TabPanels, Tabs, Text, VStack } from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { Footer } from "components/Footer";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AccountsWorkspace } from "./commerce/AccountsWorkspace";
import { InvitationsWorkspace } from "./commerce/InvitationsWorkspace";
import { PlansWorkspace } from "./commerce/PlansWorkspace";
import { SecurityWorkspace } from "./commerce/SecurityWorkspace";

export const CommerceAdmin = () => {
  const { t } = useTranslation();
  const [tabIndex, setTabIndex] = useState(0);

  return (
    <AdminShell>
      <VStack minH="100vh" p={{ base: 4, md: 8 }} spacing="6" align="stretch">
        <Box>
          <Heading as="h1" size="lg" letterSpacing="-.035em">{t("commerce.title")}</Heading>
          <Text mt="1" color="fg.muted">{t("commerce.subtitle")}</Text>
        </Box>

        <Tabs colorScheme="primary" isLazy index={tabIndex} onChange={setTabIndex} variant="soft-rounded">
          <TabList
            w="fit-content"
            maxW="full"
            overflowX="auto"
            p="1.5"
            gap="1"
            layerStyle="glassSubtle"
            rounded="2xl"
          >
            <Tab whiteSpace="nowrap">{t("commerce.plans")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.accounts")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.invitations")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.security")}</Tab>
          </TabList>
          <TabPanels mt="4">
            <TabPanel px="0"><PlansWorkspace /></TabPanel>
            <TabPanel px="0"><AccountsWorkspace /></TabPanel>
            <TabPanel px="0"><InvitationsWorkspace /></TabPanel>
            <TabPanel px="0"><SecurityWorkspace /></TabPanel>
          </TabPanels>
        </Tabs>

        <Footer mt="auto" />
      </VStack>
    </AdminShell>
  );
};
