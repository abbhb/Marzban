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
import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

const WORKSPACE_IDS = [
  "plans",
  "external-subscriptions",
  "accounts",
  "invitations",
  "security",
  "rules",
] as const;

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
const ExternalSubscriptionsWorkspace = lazy(() =>
  import("./commerce/ExternalSubscriptionsWorkspace").then(
    ({ ExternalSubscriptionsWorkspace }) => ({
      default: ExternalSubscriptionsWorkspace,
    })
  )
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

const RulesWorkspace = lazy(() => import("./commerce/RulesWorkspace").then(({ RulesWorkspace }) => ({ default: RulesWorkspace })));

const WorkspaceFallback = () => (
  <Center minH="240px">
    <Spinner color="primary.500" thickness="3px" />
  </Center>
);

export const CommerceAdmin = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedWorkspace = searchParams.get("tab");
  const requestedTabIndex = Math.max(
    0,
    WORKSPACE_IDS.findIndex((workspace) => workspace === requestedWorkspace)
  );
  const [tabIndex, setTabIndex] = useState(requestedTabIndex);
  const [initialWorkspaceReady, setInitialWorkspaceReady] = useState(false);
  const markInitialWorkspaceReady = useCallback(
    () => setInitialWorkspaceReady(true),
    []
  );

  useEffect(() => {
    setTabIndex(requestedTabIndex);
  }, [requestedTabIndex]);

  const changeWorkspace = (index: number) => {
    setTabIndex(index);
    const next = new URLSearchParams(searchParams);
    next.set("tab", WORKSPACE_IDS[index]);
    if (WORKSPACE_IDS[index] !== "accounts") next.delete("account");
    setSearchParams(next, { replace: true });
  };

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
          onChange={changeWorkspace}
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
            <Tab whiteSpace="nowrap">{t("commerce.externalSubscriptions")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.accounts")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.invitations")}</Tab>
            <Tab whiteSpace="nowrap">{t("commerce.security")}</Tab>
            <Tab whiteSpace="nowrap">{t("rules.title")}</Tab>
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
                <ExternalSubscriptionsWorkspace onReady={markInitialWorkspaceReady} />
                <BootReady ready={initialWorkspaceReady} />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <AccountsWorkspace />
                <BootReady />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <InvitationsWorkspace />
                <BootReady />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}>
                <SecurityWorkspace />
                <BootReady />
              </Suspense>
            </TabPanel>
            <TabPanel px="0" className="liquid-page-enter">
              <Suspense fallback={<WorkspaceFallback />}><RulesWorkspace /><BootReady /></Suspense>
            </TabPanel>
          </TabPanels>
        </Tabs>

        <Footer mt="auto" />
      </VStack>
    </AdminShell>
  );
};
