import { Box, Button, Center, Spinner, Text, VStack } from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { DeleteUserModal } from "components/DeleteUserModal";
import { Filters } from "components/Filters";
import { Footer } from "components/Footer";
import { Header } from "components/Header";
import { ResetAllUsageModal } from "components/ResetAllUsageModal";
import { ResetUserUsageModal } from "components/ResetUserUsageModal";
import { RevokeSubscriptionModal } from "components/RevokeSubscriptionModal";
import { UsersTable } from "components/UsersTable";
import { fetchInbounds, useDashboard } from "contexts/DashboardContext";
import { useMgma } from "contexts/MgmaContext";
import { useSubscriptionSecurity } from "contexts/SubscriptionSecurityContext";
import { FC, Suspense, lazy, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { Statistics } from "../components/Statistics";

const CoreSettingsModal = lazy(() =>
  import("components/CoreSettingsModal").then(({ CoreSettingsModal }) => ({
    default: CoreSettingsModal,
  }))
);
const HostsDialog = lazy(() =>
  import("components/HostsDialog").then(({ HostsDialog }) => ({
    default: HostsDialog,
  }))
);
const MgmaLinkModal = lazy(() =>
  import("components/MgmaLinkModal").then(({ MgmaLinkModal }) => ({
    default: MgmaLinkModal,
  }))
);
const NodesDialog = lazy(() =>
  import("components/NodesModal").then(({ NodesDialog }) => ({
    default: NodesDialog,
  }))
);
const NodesUsage = lazy(() =>
  import("components/NodesUsage").then(({ NodesUsage }) => ({
    default: NodesUsage,
  }))
);
const SubscriptionSecurityModal = lazy(() =>
  import("components/SubscriptionSecurityModal").then(
    ({ SubscriptionSecurityModal }) => ({ default: SubscriptionSecurityModal })
  )
);
const UserDialog = lazy(() =>
  import("components/UserDialog").then(({ UserDialog }) => ({
    default: UserDialog,
  }))
);

const DeferredDialogFallback = ({
  failed = false,
  onRetry,
  onCancel,
}: {
  failed?: boolean;
  onRetry?: () => void;
  onCancel?: () => void;
}) => {
  const { t } = useTranslation();
  return (
    <Center
      position="fixed"
      inset="0"
      zIndex="modal"
      bg="blackAlpha.200"
      backdropFilter="var(--marzban-overlay-filter)"
      pointerEvents="auto"
      role={failed ? "alert" : "status"}
      aria-live="polite"
    >
      <VStack layerStyle="glass-strong" rounded="2xl" p="5" spacing="3">
        {failed ? (
          <>
            <Text fontWeight="semibold">{t("portal.requestFailed")}</Text>
            <Box>
              <Button size="sm" colorScheme="primary" onClick={onRetry} me="2">
                {t("portal.retry")}
              </Button>
              <Button size="sm" variant="ghost" onClick={onCancel}>
                {t("cancel")}
              </Button>
            </Box>
          </>
        ) : (
          <>
            <Spinner color="primary.500" thickness="3px" />
            <Text fontSize="sm" color="fg.muted">
              {t("hostsDialog.loading")}
            </Text>
          </>
        )}
      </VStack>
    </Center>
  );
};

export const Dashboard: FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const showUserDialog = useDashboard(
    (state) => state.isCreatingNewUser || Boolean(state.editingUser)
  );
  const showHosts = useDashboard((state) => state.isEditingHosts);
  const showNodes = useDashboard((state) => state.isEditingNodes);
  const showNodesUsage = useDashboard((state) => state.isShowingNodesUsage);
  const showCoreSettings = useDashboard((state) => state.isEditingCore);
  const inboundsStatus = useDashboard((state) => state.inboundsStatus);
  const inboundsLoaded = inboundsStatus === "success";
  const inboundsFailed = inboundsStatus === "error";
  const showMgma = useMgma((state) => state.isOpen);
  const showSubscriptionSecurity = useSubscriptionSecurity(
    (state) => state.isOpen
  );

  useEffect(() => {
    if ((showUserDialog || showHosts) && inboundsStatus === "idle") {
      void fetchInbounds().catch((error) => {
        console.error("Failed to load inbound options", error);
      });
    }
  }, [inboundsStatus, showHosts, showUserDialog]);

  const closeInboundDialog = () => {
    useDashboard.setState({
      isCreatingNewUser: false,
      editingUser: null,
      isEditingHosts: false,
    });
  };

  const retryInbounds = () => {
    void fetchInbounds().catch((error) => {
      console.error("Failed to retry inbound options", error);
    });
  };

  useEffect(() => {
    const panel = new URLSearchParams(location.search).get("panel");
    let handled = true;

    switch (panel) {
      case "hosts":
        useDashboard.getState().onEditingHosts(true);
        break;
      case "nodes":
        useDashboard.getState().onEditingNodes(true);
        break;
      case "node-usage":
        useDashboard.getState().onShowingNodesUsage(true);
        break;
      case "reset-usage":
        useDashboard.getState().onResetAllUsage(true);
        break;
      case "subscription-security":
        useSubscriptionSecurity.getState().open();
        break;
      case "core":
        useDashboard.setState({ isEditingCore: true });
        break;
      default:
        handled = false;
    }

    if (handled) navigate("/", { replace: true });
  }, [location.search, navigate]);

  return (
    <AdminShell>
      <VStack
        justifyContent="space-between"
        minH="100vh"
        p={{ base: 4, md: 6 }}
        rowGap={4}
        className="liquid-page-enter"
      >
        <Box w="full">
          <Header />
          <Statistics mt="4" />
          <Filters />
          <UsersTable />
          <DeleteUserModal />
          <ResetUserUsageModal />
          <RevokeSubscriptionModal />
          <ResetAllUsageModal />
          {(showUserDialog || showHosts) && !inboundsLoaded ? (
            <DeferredDialogFallback
              failed={inboundsFailed}
              onRetry={retryInbounds}
              onCancel={closeInboundDialog}
            />
          ) : null}
          <Suspense fallback={<DeferredDialogFallback />}>
            {showUserDialog && inboundsLoaded ? <UserDialog /> : null}
            {showMgma ? <MgmaLinkModal /> : null}
            {showHosts && inboundsLoaded ? <HostsDialog /> : null}
            {showNodes ? <NodesDialog /> : null}
            {showNodesUsage ? <NodesUsage /> : null}
            {showCoreSettings ? <CoreSettingsModal /> : null}
            {showSubscriptionSecurity ? <SubscriptionSecurityModal /> : null}
          </Suspense>
        </Box>
        <Footer />
      </VStack>
    </AdminShell>
  );
};

export default Dashboard;
