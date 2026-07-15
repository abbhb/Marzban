import { Box, VStack } from "@chakra-ui/react";
import { AdminShell } from "components/AdminShell";
import { CoreSettingsModal } from "components/CoreSettingsModal";
import { DeleteUserModal } from "components/DeleteUserModal";
import { Filters } from "components/Filters";
import { Footer } from "components/Footer";
import { Header } from "components/Header";
import { HostsDialog } from "components/HostsDialog";
import { MgmaLinkModal } from "components/MgmaLinkModal";
import { NodesDialog } from "components/NodesModal";
import { NodesUsage } from "components/NodesUsage";
import { ResetAllUsageModal } from "components/ResetAllUsageModal";
import { ResetUserUsageModal } from "components/ResetUserUsageModal";
import { RevokeSubscriptionModal } from "components/RevokeSubscriptionModal";
import { SubscriptionSecurityModal } from "components/SubscriptionSecurityModal";
import { UserDialog } from "components/UserDialog";
import { UsersTable } from "components/UsersTable";
import { fetchInbounds, useDashboard } from "contexts/DashboardContext";
import { useSubscriptionSecurity } from "contexts/SubscriptionSecurityContext";
import { FC, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Statistics } from "../components/Statistics";

export const Dashboard: FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    useDashboard.getState().refetchUsers();
    fetchInbounds();
  }, []);

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
      <VStack justifyContent="space-between" minH="100vh" p="6" rowGap={4}>
        <Box w="full">
          <Header />
          <Statistics mt="4" />
          <Filters />
          <UsersTable />
          <UserDialog />
          <DeleteUserModal />
          <MgmaLinkModal />
          <HostsDialog />
          <ResetUserUsageModal />
          <RevokeSubscriptionModal />
          <NodesDialog />
          <NodesUsage />
          <ResetAllUsageModal />
          <CoreSettingsModal />
          <SubscriptionSecurityModal />
        </Box>
        <Footer />
      </VStack>
    </AdminShell>
  );
};

export default Dashboard;
