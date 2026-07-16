import {
  Box,
  Heading,
  Center,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  VStack,
} from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { BootReady } from "components/BootReady";
import { Footer } from "components/Footer";
import { Suspense, lazy, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

const PlansWorkspace = lazy(() =>
  import("./commerce/PlansWorkspace").then(({ PlansWorkspace }) => ({
    default: PlansWorkspace,
  }))
);
const AccountsWorkspace = lazy(() =>
  import("./commerce/AccountsWorkspace").then(({ AccountsWorkspace }) => ({
    default: AccountsWorkspace,
  }))
);
const InvitationsWorkspace = lazy(() =>
  import("./commerce/InvitationsWorkspace").then(
    ({ InvitationsWorkspace }) => ({ default: InvitationsWorkspace })
  )
);
const SecurityWorkspace = lazy(() =>
  import("./commerce/SecurityWorkspace").then(({ SecurityWorkspace }) => ({
    default: SecurityWorkspace,
  }))
);

const WorkspaceFallback = () => (
  <Center minH="240px">
    <Spinner color="primary.500" thickness="3px" />
  </Center>
);

export const CommerceAdmin = () => {
  const { t } = useTranslation();
  const [tabIndex, setTabIndex] = useState(0);
  const [initialWorkspaceReady, setInitialWorkspaceReady] = useState(false);
  const markInitialWorkspaceReady = useCallback(
    () => setInitialWorkspaceReady(true),
    []
  );

  return (
    <AdminShell>
      <VStack
        minH="100vh"
        p={{ base: 4, md: 8 }}
        spacing="6"
        align="stretch"
        className="liquid-page-enter"
      >
        <Box>
          <Heading as="h1" size="lg" letterSpacing="-.035em">
            {t("commerce.title")}
          </Heading>
          <Text mt="1" color="fg.muted">
            {t("commerce.subtitle")}
          </Text>
        </Box>

        <Tabs
          colorScheme="primary"
          isLazy
          index={tabIndex}
          onChange={setTabIndex}
          variant="unstyled"
        >
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
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <PlansWorkspace onReady={markInitialWorkspaceReady} />
                <BootReady ready={initialWorkspaceReady} />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <AccountsWorkspace />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <InvitationsWorkspace />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <SecurityWorkspace />
              </Suspense>
            </TabPanel>
          </TabPanels>
        </Tabs>

        <Footer mt="auto" />
      </VStack>
    </AdminShell>
  );
};
